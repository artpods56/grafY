"""Provider-operation cache: one Workspace's answer to one provider request.

This is not the kernel result store. The result store answers "has this node
instance already computed these outputs?" and is keyed by node fingerprint
(ADR 0020); a stored node result is the unit the canvas shows, statuses are drawn
from it, and it grows with the graph. This module answers a narrower and
lower-level question: "has this Workspace already asked this provider for exactly
this request?". It sits under a node, because one node computation can issue many
provider calls and because a lazy operation has no node instance of its own at
all: a TIFF window can ask for the text under a crop when the crop is read, so
there is no fingerprint to consult and no stored output to point at. Nothing in
here is visible to the canvas, and a provider binding never learns it exists.

A key is three things, and only the caller can state them honestly:

**Operation identity** — :class:`CacheSpec` names the operation, the deployment it
is aimed at, an immutable implementation or model ``revision``, and the
``schema_version`` of the answer. The revision must move whenever the answer could
change for the same request; nothing here can detect a stale revision, which is
why a caller without a stable one does not get a cache rather than getting a
guess.

**Request identity** — the ``request`` the caller hands
:meth:`ProviderCache.get_or_compute`: canonical JSON of every output-affecting
setting plus a digest of the input bytes. Bytes never go in raw and credentials
never go in at all: a key that carried a credential would be a key that leaks it,
and display metadata that no longer matches the bytes would serve one page's
answer for another's.

**Workspace** — supplied by Grafy, never derived from the request. It is a
required argument of every store operation and leads the stored primary key, so
two Workspaces using the same provider credential cannot read each other's
answers.

What a caller may rely on, and what it may not:

- A hit is decoded through the spec's codec. A payload the codec refuses is
  dropped and the operation runs; a cache row never becomes a node failure.
- An empty answer and a JSON ``null`` answer are answers. Re-asking a provider for
  a crop with no text in it is the cost this module exists to remove.
- Each successful call is written immediately, so the calls a run completed before
  it was interrupted are reusable by the run after it.
- A provider error or a cancellation writes nothing, and is never swallowed as a
  cache miss. Only failures of the cache itself are swallowed, at the store
  boundary, and only for this cache: an optional accelerator must not become an
  outage.
- Concurrent misses for one key inside one API process make one provider call.
  Across processes there is no shared call graph: both may call the provider, and
  atomic storage makes the outcome one complete row rather than a torn one.
  Cross-process single-flight is out of scope, deliberately.
- Entries expire, and expiry ends an entry's visibility at once; reclamation of the
  rows themselves is the bounded cleanup path, see
  :class:`CacheStoreMaintenance`.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import wraps
import hashlib
import json
import logging
import math
from typing import Protocol, cast, runtime_checkable
from uuid import UUID

from pydantic import JsonValue, SecretStr, TypeAdapter, ValidationError

logger = logging.getLogger(__name__)

#: Longest canonical request identity Grafy will hash. A crop is a handful of
#: numbers, so an identity that runs to kilobytes is a caller that stopped naming
#: its inputs and started inlining them.
MAX_CANONICAL_IDENTITY_CHARS = 65_536

#: How often one API process sweeps expired rows after a write, and how many rows
#: one sweep takes. Both bound the housekeeping, not the correctness of a read.
DEFAULT_CLEANUP_INTERVAL_SECONDS = 900.0
DEFAULT_CLEANUP_BATCH_ROWS = 500


class ProviderCacheError(ValueError):
    """A caller asked for caching it has not described well enough to cache."""


class UnstableRequestError(ProviderCacheError):
    """A request identity is not canonical JSON.

    Raised instead of hashing something arbitrary: a value ``json.dumps`` cannot
    name has no stable digest, and a silent fallback would let two different
    requests share one answer.
    """


class ProviderOperationPayloadTooLargeError(RuntimeError):
    """A store refused an answer too large to keep.

    The operation still returns its result; the entry is simply not cached.
    """


class CacheStore(Protocol):
    """Where answers live, partitioned by Workspace.

    A store owns its own transaction or connection per call and never holds one
    across a provider request — that is why this is not a repository on the unit
    of work: the unit of work of a node computation spans materializing inputs
    and calling a provider over minutes, and a cache read must not pin it.
    """

    async def get(self, workspace: UUID, key: str) -> bytes | None:
        """The stored payload for this Workspace and key, or None.

        None covers "never stored", "expired", and "reclaimed" alike, so a reader
        can never mistake an expired entry for a live one.
        """
        ...

    async def put_if_absent(
        self, workspace: UUID, key: str, value: bytes, *, ttl_seconds: int
    ) -> bytes:
        """Store ``value`` unless a live entry already holds this key.

        Returns the bytes now stored, which is ``value`` on the common path and
        the competing writer's payload when another process won the race. An entry
        whose ttl has passed counts as absent, so replacement is atomic with this
        decision and cannot interleave a second writer's payload with this one's
        expiry.
        """
        ...


@runtime_checkable
class CacheStoreMaintenance(Protocol):
    """What a store offers beyond the two operations the cache path needs.

    Both are housekeeping, so a store that cannot do them is a working cache with
    no self-repair: :class:`ProviderCache` skips the unreadable-payload repair and
    the bounded cleanup rather than failing an operation over them.
    """

    async def put(
        self, workspace: UUID, key: str, value: bytes, *, ttl_seconds: int
    ) -> None:
        """Replace this key's entry whatever it holds.

        Used only to retire a payload the codec refused. Ordinary writes go
        through :meth:`CacheStore.put_if_absent` so a competing process's winner
        survives.

        ``ttl_seconds`` may be 0, which stores an entry that has already expired:
        no reader sees it and the next sweep reclaims the row. That is how a caller
        gives up an entry it can no longer read, without a delete of its own.
        """
        ...

    async def delete_expired(self, *, now: datetime, limit: int) -> int:
        """Delete at most ``limit`` entries expired at or before ``now``.

        Every Workspace at once: expiry is storage housekeeping, not a
        Workspace-visible fact, so reclaiming space needs no scope. Called
        repeatedly while rows remain, which is what makes one batch bounded.
        """
        ...


@dataclass(frozen=True)
class CacheSpec[T]:
    """One cacheable operation: what it is, how its answer is encoded, how long
    an answer stays acceptable.

    ``revision`` is the immutable implementation or model revision — a digest of
    the code that builds the request and reads the response, or the model id the
    provider names in its answer. ``schema_version`` belongs to the codec: bump it
    when the encoded answer changes shape, and the old entries retire themselves
    as misses rather than being decoded into something new.
    """

    operation: str
    deployment: str
    revision: str
    schema_version: int
    codec: TypeAdapter[T]
    ttl_seconds: int

    def __post_init__(self) -> None:
        for label, value in (
            ("Operation id", self.operation),
            ("Deployment identity", self.deployment),
            ("Implementation revision", self.revision),
        ):
            if value.strip() == "" or value != value.strip():
                raise ProviderCacheError(
                    f"{label} must be non-empty without surrounding whitespace"
                )
            if len(value) > 255:
                raise ProviderCacheError(f"{label} must be at most 255 characters")
        if self.schema_version < 1:
            raise ProviderCacheError("Schema version must be at least 1")
        if self.ttl_seconds < 1:
            raise ProviderCacheError("ttl_seconds must be at least 1")

    def key(self, request: JsonValue) -> str:
        """The digest one request maps to, independent of argument order."""

        document = [
            self.operation,
            self.deployment,
            self.revision,
            self.schema_version,
            request,
        ]
        return hashlib.sha256(_canonical_identity(document)).hexdigest()


@dataclass
class _Gate:
    """One in-process attempt at one key, and who is waiting on it.

    The count, not a weak reference, is what bounds this map: an entry exists
    exactly while some call holds it, and every acquirer releases it in a
    ``finally``, so a cancelled or failing attempt cannot leave a lock behind and
    the map cannot grow with the number of keys a deployment has ever served.
    """

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    holders: int = 0


class ProviderCache:
    """Reuses a Workspace's stored answer for one provider request.

    ``store`` is the only required collaborator: with no cache to configure, do not
    wrap the call rather than wrapping it around a cache that is absent.
    Concurrency is in-process only, keyed by ``(workspace, key)``, and lives as long
    as the call does. A failed or cancelled attempt releases its gate and stores
    nothing, so a transient provider failure cannot poison a key.
    """

    def __init__(
        self,
        store: CacheStore,
        *,
        clock: Callable[[], datetime] | None = None,
        cleanup_interval_seconds: float = DEFAULT_CLEANUP_INTERVAL_SECONDS,
        cleanup_batch_rows: int = DEFAULT_CLEANUP_BATCH_ROWS,
    ) -> None:
        if cleanup_interval_seconds <= 0:
            raise ProviderCacheError("cleanup_interval_seconds must be positive")
        if cleanup_batch_rows < 1:
            raise ProviderCacheError("cleanup_batch_rows must be at least 1")
        self._store = store
        self._clock = clock if clock is not None else _utc_now
        self._cleanup_interval_seconds = cleanup_interval_seconds
        self._cleanup_batch_rows = cleanup_batch_rows
        self._gates: dict[tuple[UUID, str], _Gate] = {}
        self._next_cleanup_at = 0.0

    @property
    def in_flight(self) -> int:
        """Keys this process currently holds a gate for.

        Zero whenever no call is running, which is the check that the coalescing
        map is bounded by concurrency rather than by history.
        """

        return len(self._gates)

    async def get_or_compute[T](
        self,
        workspace: UUID,
        spec: CacheSpec[T],
        request: JsonValue,
        compute: Callable[[], Awaitable[T]],
    ) -> tuple[T, bool]:
        """The answer for one request, and whether this call skipped ``compute``.

        ``request`` must name everything that changes the answer and nothing that
        merely describes the work. ``compute`` runs with no cache transaction
        around it and with the in-process lock held, which is what coalesces two
        concurrent misses into one provider call.

        The boolean is exactly "this caller did not call the provider": a hit, or
        a write that lost to another process whose answer is being returned. A
        caller that ran its own ``compute`` sees False even when another process
        had already stored the same answer.
        """

        key = spec.key(request)
        outcome = await self._coalesced(workspace, key, spec, compute)
        # Housekeeping belongs outside the coalescing gate: a sweep is one process's
        # turn to pay for everyone's expired rows and no caller should wait on it.
        await self._cleanup_if_due()
        return outcome

    async def get_or_compute_many[T](
        self,
        workspace: UUID,
        spec: CacheSpec[T],
        requests: Sequence[JsonValue],
        compute: Callable[[Sequence[int]], Awaitable[Sequence[T]]],
    ) -> list[tuple[T, bool]]:
        """The answer for each request, and whether that request skipped ``compute``.

        ``compute`` receives the indexes of the misses, in request order. A key
        that appears twice is listed once, at its first index, and both positions
        share that answer. One call covers every miss. Hits are left out of it.

        Locks are taken in key order. Locks for hits are released before
        ``compute`` runs, so a stored answer does not wait on the provider call
        for a neighbouring miss. Each miss keeps its lock until its answer is
        written, which is what makes a second batch wait and then read that
        answer instead of calling the provider again.
        """

        if not requests:
            return []
        keys = [spec.key(request) for request in requests]
        unique: list[str] = list(dict.fromkeys(keys))
        gates: dict[str, _Gate] = {}
        coalesced: dict[str, bool] = {}
        for key in unique:
            gate = self._gates.setdefault((workspace, key), _Gate())
            coalesced[key] = gate.holders > 0
            gate.holders += 1
            gates[key] = gate

        acquired: list[str] = []
        released: set[str] = set()
        resolved: dict[str, tuple[T, bool]] = {}
        try:
            for key in sorted(unique):
                await gates[key].lock.acquire()
                acquired.append(key)
            missing = await self._collect_misses(
                workspace, spec, keys, coalesced, resolved
            )
            miss_keys = {keys[index] for index in missing}
            for key in acquired:
                if key in miss_keys:
                    continue
                gates[key].lock.release()
                released.add(key)
            if missing:
                computed = await compute(missing)
                if len(computed) != len(missing):
                    raise ProviderCacheError(
                        f"Batch compute returned {len(computed)} answers for "
                        f"{len(missing)} misses"
                    )
                for index, result in zip(missing, computed, strict=True):
                    resolved[keys[index]] = await self._remember(
                        workspace, spec, keys[index], result
                    )
        finally:
            for key in acquired:
                if key in released:
                    continue
                gates[key].lock.release()
            for key in unique:
                gate = gates[key]
                gate.holders -= 1
                if gate.holders == 0 and self._gates.get((workspace, key)) is gate:
                    del self._gates[(workspace, key)]
        await self._cleanup_if_due()
        return [resolved[key] for key in keys]

    async def _coalesced[T](
        self,
        workspace: UUID,
        key: str,
        spec: CacheSpec[T],
        compute: Callable[[], Awaitable[T]],
    ) -> tuple[T, bool]:
        gate = self._gates.setdefault((workspace, key), _Gate())
        # Who else had this key claimed when this caller arrived. Only the log line
        # uses it: a caller that waited and found the leader's write is a hit like
        # any other, and the answer it got does not depend on who asked first.
        coalesced = gate.holders > 0
        # Registered before anything is awaited and released in a finally, so an
        # entry cannot outlive the calls that made it — including a cancellation
        # that lands while this caller is queued behind another's provider call.
        gate.holders += 1
        try:
            async with gate.lock:
                return await self._under_lock(
                    workspace, spec, key, compute, coalesced=coalesced
                )
        finally:
            gate.holders -= 1
            if gate.holders == 0 and self._gates.get((workspace, key)) is gate:
                del self._gates[(workspace, key)]

    async def cleanup_expired(self, *, limit: int | None = None) -> int:
        """Reclaim expired entries now; report how many rows went.

        An explicit call reports the store's own failure instead of swallowing it,
        unlike the opportunistic sweep after a write.
        """

        store = self._store
        if not isinstance(store, CacheStoreMaintenance):
            raise ProviderCacheError(
                "This cache store does not reclaim expired entries; entries stop "
                "being served when their ttl passes, and the rows go with a store "
                "that implements CacheStoreMaintenance.delete_expired"
            )
        return await store.delete_expired(
            now=self._clock(),
            limit=self._cleanup_batch_rows if limit is None else limit,
        )

    async def _under_lock[T](
        self,
        workspace: UUID,
        spec: CacheSpec[T],
        key: str,
        compute: Callable[[], Awaitable[T]],
        *,
        coalesced: bool,
    ) -> tuple[T, bool]:
        stored = await self._read(workspace, key)
        if stored is not None:
            try:
                answer = spec.codec.validate_json(stored)
            except ValidationError as exc:
                # A payload this codec cannot read is not this answer: retire the
                # row, then compute. It is never a node failure.
                logger.warning(
                    "provider_cache_payload_unreadable workspace=%s key=%s error=%s",
                    workspace,
                    key,
                    type(exc).__name__,
                )
                await self._retire(workspace, key, spec)
            else:
                logger.debug(
                    "provider_cache_hit workspace=%s operation=%s key=%s coalesced=%s",
                    workspace,
                    spec.operation,
                    key,
                    coalesced,
                )
                return answer, True

        logger.debug(
            "provider_cache_miss workspace=%s operation=%s key=%s",
            workspace,
            spec.operation,
            key,
        )
        result = await compute()
        payload = self._encode(spec, workspace, key, result)
        if payload is None:
            return result, False
        winner = await self._write(
            workspace, key, payload, ttl_seconds=spec.ttl_seconds
        )
        if winner is None or winner == payload:
            return result, False
        # Another process stored an answer for this key first. Its bytes are the
        # persisted state, so they are what this call returns; this call still ran
        # its provider, so it is not reported as a hit.
        try:
            return spec.codec.validate_json(winner), False
        except ValidationError as exc:
            logger.warning(
                "provider_cache_competing_payload_unreadable workspace=%s key=%s error=%s",
                workspace,
                key,
                type(exc).__name__,
            )
            return result, False

    async def _collect_misses[T](
        self,
        workspace: UUID,
        spec: CacheSpec[T],
        keys: Sequence[str],
        coalesced: dict[str, bool],
        resolved: dict[str, tuple[T, bool]],
    ) -> list[int]:
        """Indexes of the first occurrence of each key that is not stored."""

        missing: list[int] = []
        seen: set[str] = set()
        for index, key in enumerate(keys):
            if key in seen:
                continue
            seen.add(key)
            found = await self._cached_answer(
                workspace, spec, key, coalesced=coalesced[key]
            )
            if found is None:
                missing.append(index)
                continue
            resolved[key] = found
        return missing

    async def _cached_answer[T](
        self,
        workspace: UUID,
        spec: CacheSpec[T],
        key: str,
        *,
        coalesced: bool,
    ) -> tuple[T, bool] | None:
        """A stored answer, or None when this key has to be computed."""

        stored = await self._read(workspace, key)
        if stored is not None:
            try:
                answer = spec.codec.validate_json(stored)
            except ValidationError as exc:
                logger.warning(
                    "provider_cache_payload_unreadable workspace=%s key=%s error=%s",
                    workspace,
                    key,
                    type(exc).__name__,
                )
                await self._retire(workspace, key, spec)
            else:
                logger.debug(
                    "provider_cache_hit workspace=%s operation=%s key=%s coalesced=%s",
                    workspace,
                    spec.operation,
                    key,
                    coalesced,
                )
                return answer, True
        logger.debug(
            "provider_cache_miss workspace=%s operation=%s key=%s",
            workspace,
            spec.operation,
            key,
        )
        return None

    async def _remember[T](
        self,
        workspace: UUID,
        spec: CacheSpec[T],
        key: str,
        result: T,
    ) -> tuple[T, bool]:
        """Store one computed answer and report that this call did not skip it."""

        payload = self._encode(spec, workspace, key, result)
        if payload is None:
            return result, False
        winner = await self._write(
            workspace, key, payload, ttl_seconds=spec.ttl_seconds
        )
        if winner is None or winner == payload:
            return result, False
        try:
            return spec.codec.validate_json(winner), False
        except ValidationError as exc:
            logger.warning(
                "provider_cache_competing_payload_unreadable workspace=%s key=%s error=%s",
                workspace,
                key,
                type(exc).__name__,
            )
            return result, False

    async def _read(self, workspace: UUID, key: str) -> bytes | None:
        """A store failure is a cache miss, here and only here."""

        try:
            return await self._store.get(workspace, key)
        except Exception as exc:
            logger.warning(
                "provider_cache_read_failed workspace=%s key=%s error_type=%s",
                workspace,
                key,
                type(exc).__name__,
            )
            return None

    async def _write(
        self, workspace: UUID, key: str, payload: bytes, *, ttl_seconds: int
    ) -> bytes | None:
        try:
            return await self._store.put_if_absent(
                workspace, key, payload, ttl_seconds=ttl_seconds
            )
        except Exception as exc:
            logger.warning(
                "provider_cache_write_failed workspace=%s key=%s error_type=%s",
                workspace,
                key,
                type(exc).__name__,
            )
            return None

    async def _retire[T](self, workspace: UUID, key: str, spec: CacheSpec[T]) -> None:
        """Give up the space an unreadable payload holds, best effort."""

        store = self._store
        if not isinstance(store, CacheStoreMaintenance):
            return
        try:
            await store.put(workspace, key, b"", ttl_seconds=0)
        except Exception as exc:
            logger.warning(
                "provider_cache_retire_failed workspace=%s key=%s error_type=%s",
                workspace,
                key,
                type(exc).__name__,
            )

    async def _cleanup_if_due(self) -> None:
        store = self._store
        if not isinstance(store, CacheStoreMaintenance):
            return
        loop_time = asyncio.get_running_loop().time()
        if loop_time < self._next_cleanup_at:
            return
        # The schedule moves before the attempt: a store that cannot sweep must not
        # make every following call pay for another one.
        self._next_cleanup_at = loop_time + self._cleanup_interval_seconds
        try:
            removed = await store.delete_expired(
                now=self._clock(), limit=self._cleanup_batch_rows
            )
        except Exception as exc:
            logger.warning(
                "provider_cache_cleanup_failed error_type=%s", type(exc).__name__
            )
            return
        if removed:
            logger.info("provider_cache_expired_rows_removed rows=%s", removed)

    def _encode[T](
        self, spec: CacheSpec[T], workspace: UUID, key: str, result: T
    ) -> bytes | None:
        try:
            return spec.codec.dump_json(result)
        except Exception as exc:
            logger.warning(
                "provider_cache_encode_failed workspace=%s key=%s error_type=%s",
                workspace,
                key,
                type(exc).__name__,
            )
            return None


def cached_call[T, **P](
    operation: Callable[P, Awaitable[T]],
    /,
    *,
    cache: ProviderCache,
    workspace: UUID,
    spec: CacheSpec[T],
    identify: Callable[P, JsonValue],
    observe_hit: Callable[[bool], None] | None = None,
) -> Callable[P, Awaitable[T]]:
    """The same callable, with a cache in front of it.

    Composition-time opt-in: wrap the binding where the provider is chosen and the
    Workspace is known, and every caller of the result — a node, a lazy window
    read, a test — keeps the original signature and never mentions the cache.
    ``identify`` names the request from the arguments and must be total over them:
    a setting it omits is a setting two calls will disagree about while sharing one
    entry. ``observe_hit`` is told what happened before the answer is handed back,
    which is where progress reporting will hook; nothing in the canvas reads it yet.
    """

    @wraps(operation)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        result, hit = await cache.get_or_compute(
            workspace,
            spec,
            identify(*args, **kwargs),
            lambda: operation(*args, **kwargs),
        )
        if observe_hit is not None:
            observe_hit(hit)
        return result

    return wrapped


class InMemoryCacheStore:
    """A :class:`CacheStore` for tests and for a runtime with no database.

    Expiry and the write race are resolved the way the SQL store resolves them, so
    a behavior test over this store is a statement about the contract rather than
    about SQLite.
    """

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock if clock is not None else _utc_now
        self._entries: dict[tuple[UUID, str], tuple[bytes, datetime]] = {}

    @property
    def entries(self) -> int:
        """Rows held, including any whose ttl has passed but which no sweep took."""

        return len(self._entries)

    async def get(self, workspace: UUID, key: str) -> bytes | None:
        entry = self._entries.get((workspace, key))
        if entry is None:
            return None
        payload, expires_at = entry
        if expires_at <= self._clock():
            return None
        return payload

    async def put_if_absent(
        self, workspace: UUID, key: str, value: bytes, *, ttl_seconds: int
    ) -> bytes:
        now = self._clock()
        entry = self._entries.get((workspace, key))
        if entry is not None and entry[1] > now:
            return entry[0]
        self._entries[(workspace, key)] = (value, now + timedelta(seconds=ttl_seconds))
        return value

    async def put(
        self, workspace: UUID, key: str, value: bytes, *, ttl_seconds: int
    ) -> None:
        self._entries[(workspace, key)] = (
            value,
            self._clock() + timedelta(seconds=ttl_seconds),
        )

    async def delete_expired(self, *, now: datetime, limit: int) -> int:
        doomed = [
            stored_key
            for stored_key, (_, expires_at) in self._entries.items()
            if expires_at <= now
        ][:limit]
        for stored_key in doomed:
            del self._entries[stored_key]
        return len(doomed)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _canonical_identity(document: object) -> bytes:
    """Canonical JSON for a request identity, or the reason it cannot have one."""

    try:
        canonical = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise UnstableRequestError(_explain_identity_failure(document, exc)) from exc
    if len(canonical) > MAX_CANONICAL_IDENTITY_CHARS:
        raise UnstableRequestError(
            f"Request identity is {len(canonical)} characters, over the "
            f"{MAX_CANONICAL_IDENTITY_CHARS} Grafy will hash: put a digest of the "
            "input in the request instead of the input"
        )
    return canonical.encode("utf-8")


def _explain_identity_failure(document: object, error: Exception) -> str:
    """Name the offending value, because the json message does not say where."""

    offender = _first_unstable(document, "$")
    if offender is not None:
        return offender
    return f"Request identity must be canonical JSON: {error}"


def _first_unstable(value: object, path: str) -> str | None:
    """Describe the first value in a request that has no JSON form, if any."""

    kind = type(value).__name__
    if isinstance(value, float) and not math.isfinite(value):
        return f"Request value at {path} is {value}, which has no JSON form."
    if value is None or isinstance(value, bool | int | float | str):
        return None
    if isinstance(value, SecretStr):
        return (
            f"Request value at {path} is a credential. A credential is not part of "
            "what a request asks for and never enters a cache key."
        )
    if isinstance(value, bytes | bytearray | memoryview):
        return (
            f"Request value at {path} is bytes. Put the sha256 hex digest of those "
            "bytes in the request instead, so the key describes the content without "
            "carrying it."
        )
    if isinstance(value, dict):
        return _first_unstable_field(cast("Mapping[object, object]", value), path)
    if isinstance(value, list | tuple):
        return _first_unstable_element(cast("Sequence[object]", value), path)
    if isinstance(value, (set, frozenset)):
        return (
            f"Request value at {path} is a {kind}, whose iteration order is not part "
            "of its meaning. Sort it into a list."
        )
    return (
        f"Request value at {path} is {kind}, which is not a JSON value. Name the "
        "setting it stands for — a revision, a digest, a page, a bound — instead of "
        "the object itself."
    )


def _first_unstable_field(fields: Mapping[object, object], path: str) -> str | None:
    for name, item in fields.items():
        if not isinstance(name, str):
            return f"Request key at {path} is {type(name).__name__}, not a string."
        offender = _first_unstable(item, f"{path}.{name}")
        if offender is not None:
            return offender
    return None


def _first_unstable_element(items: Sequence[object], path: str) -> str | None:
    for index, item in enumerate(items):
        offender = _first_unstable(item, f"{path}[{index}]")
        if offender is not None:
            return offender
    return None


__all__ = [
    "DEFAULT_CLEANUP_BATCH_ROWS",
    "DEFAULT_CLEANUP_INTERVAL_SECONDS",
    "MAX_CANONICAL_IDENTITY_CHARS",
    "CacheSpec",
    "CacheStore",
    "CacheStoreMaintenance",
    "InMemoryCacheStore",
    "ProviderCache",
    "ProviderCacheError",
    "ProviderOperationPayloadTooLargeError",
    "UnstableRequestError",
    "cached_call",
]

"""Provider-operation cache behavior, over an in-memory store.

The store here enforces expiry and the write race exactly as the SQL store does, so
each assertion below is about the contract rather than about SQLite or asyncio
scheduling accidents.
"""

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
import gc
import inspect
from typing import cast
from uuid import UUID, uuid4

from pydantic import BaseModel, JsonValue, SecretStr, TypeAdapter
import pytest

from grafy_core.provider_cache import (
    MAX_CANONICAL_IDENTITY_CHARS,
    CacheSpec,
    InMemoryCacheStore,
    ProviderCache,
    ProviderCacheError,
    ProviderOperationPayloadTooLargeError,
    UnstableRequestError,
    cached_call,
)

WORKSPACE = uuid4()
OTHER_WORKSPACE = uuid4()

TEXT_SPEC = CacheSpec(
    operation="ocr.window",
    deployment="fake.ocr@1",
    revision="rev-aaaa",
    schema_version=1,
    codec=TypeAdapter(str),
    ttl_seconds=600,
)

NULLABLE_TEXT: TypeAdapter[str | None] = TypeAdapter(str | None)

NULLABLE_SPEC: CacheSpec[str | None] = CacheSpec(
    operation="ocr.crop",
    deployment="fake.ocr@1",
    revision="rev-aaaa",
    schema_version=1,
    codec=NULLABLE_TEXT,
    ttl_seconds=600,
)


class Reading(BaseModel):
    markdown: str
    pages: int


class FakeClock:
    """A clock a test moves by hand, since expiry must not depend on wall time."""

    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, *, seconds: float) -> None:
        self.at = self.at + timedelta(seconds=seconds)


class FlakyStore(InMemoryCacheStore):
    """An in-memory store with named failures, for the fail-open paths."""

    def __init__(self, *, fail_get: bool = False, fail_put: bool = False) -> None:
        super().__init__()
        self.fail_get = fail_get
        self.fail_put = fail_put
        self.get_calls = 0
        self.put_calls = 0

    async def get(self, workspace: UUID, key: str) -> bytes | None:
        self.get_calls += 1
        if self.fail_get:
            raise TimeoutError("cache read timed out")
        return await super().get(workspace, key)

    async def put_if_absent(
        self, workspace: UUID, key: str, value: bytes, *, ttl_seconds: int
    ) -> bytes:
        self.put_calls += 1
        if self.fail_put:
            raise TimeoutError("cache write timed out")
        return await super().put_if_absent(
            workspace, key, value, ttl_seconds=ttl_seconds
        )


class CountingStore(InMemoryCacheStore):
    """An in-memory store that says how often it was asked to sweep."""

    def __init__(self, *, clock: FakeClock | None = None) -> None:
        super().__init__(clock=clock)
        self.sweeps: list[int] = []

    async def delete_expired(self, *, now: datetime, limit: int) -> int:
        self.sweeps.append(limit)
        return await super().delete_expired(now=now, limit=limit)


class RefusingStore(InMemoryCacheStore):
    async def put_if_absent(
        self, workspace: UUID, key: str, value: bytes, *, ttl_seconds: int
    ) -> bytes:
        raise ProviderOperationPayloadTooLargeError(
            "over the bound this deployment keeps"
        )


def test_same_request_maps_to_one_key_whatever_the_argument_order() -> None:
    def key_of(request: JsonValue) -> str:
        return TEXT_SPEC.key(request)

    assert key_of({"page": 2, "crop": [1, 2, 3, 4], "language": "cs"}) == key_of(
        {"language": "cs", "crop": [1, 2, 3, 4], "page": 2}
    )
    assert key_of({"page": 2}) != key_of({"page": 3})

    # Each part of the operation identity moves the key on its own, which is what
    # lets a deployment retire a family of answers by bumping one field.
    moved_revision = CacheSpec(
        operation=TEXT_SPEC.operation,
        deployment=TEXT_SPEC.deployment,
        revision="rev-bbbb",
        schema_version=TEXT_SPEC.schema_version,
        codec=TEXT_SPEC.codec,
        ttl_seconds=TEXT_SPEC.ttl_seconds,
    )
    assert moved_revision.key({"page": 2}) != key_of({"page": 2})


@pytest.mark.parametrize(
    ("attribute", "value", "reason"),
    [
        ("crop_bytes", b"tiff-window-bytes", "sha256 hex digest"),
        ("api_key", SecretStr("sk-secret"), "credential"),
        ("languages", {"cs", "de"}, "iteration order"),
        ("confidence", float("nan"), "no JSON form"),
    ],
)
async def test_a_request_that_cannot_be_described_is_refused_not_guessed(
    attribute: str, value: object, reason: str
) -> None:
    store = InMemoryCacheStore()
    cache = ProviderCache(store)
    calls = 0

    async def compute() -> str:
        nonlocal calls
        calls += 1
        return "text"

    request = cast(JsonValue, {attribute: value})
    with pytest.raises(UnstableRequestError) as refusal:
        await cache.get_or_compute(WORKSPACE, TEXT_SPEC, request, compute)
    assert reason in str(refusal.value)
    assert calls == 0
    assert store.entries == 0


async def test_an_oversized_request_is_refused_with_the_digest_instead() -> None:
    cache = ProviderCache(InMemoryCacheStore())

    async def compute() -> str:
        return "text"

    inline = "x" * (MAX_CANONICAL_IDENTITY_CHARS + 1)
    with pytest.raises(UnstableRequestError, match="digest of the input"):
        await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"crop": inline}, compute)


async def test_a_miss_computes_once_and_the_answer_survives_the_call() -> None:
    store = InMemoryCacheStore()
    cache = ProviderCache(store)
    calls = 0

    async def compute() -> str:
        nonlocal calls
        calls += 1
        return "page text"

    assert await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, compute) == (
        "page text",
        False,
    )
    # Written immediately, not at the end of the run: the calls an interrupted
    # computation already made are the ones worth keeping.
    assert store.entries == 1
    assert await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, compute) == (
        "page text",
        True,
    )
    assert calls == 1

    # Another process over the same rows — a second cache here — reads the same answer.
    other_process = ProviderCache(store)
    assert await other_process.get_or_compute(
        WORKSPACE, TEXT_SPEC, {"page": 1}, compute
    ) == ("page text", True)
    assert calls == 1


async def test_an_empty_answer_is_an_answer() -> None:
    cache = ProviderCache(InMemoryCacheStore())
    calls = 0

    async def find_text_on_crop() -> str | None:
        nonlocal calls
        calls += 1
        return None

    request: JsonValue = {"crop_sha256": "b" * 64}
    assert await cache.get_or_compute(
        WORKSPACE, NULLABLE_SPEC, request, find_text_on_crop
    ) == (None, False)
    assert await cache.get_or_compute(
        WORKSPACE, NULLABLE_SPEC, request, find_text_on_crop
    ) == (None, True)
    assert calls == 1


async def test_a_structured_result_round_trips_through_its_codec() -> None:
    cache = ProviderCache(InMemoryCacheStore())
    spec = CacheSpec(
        operation="ocr.read",
        deployment="fake.ocr@1",
        revision="rev-aaaa",
        schema_version=1,
        codec=TypeAdapter(Reading),
        ttl_seconds=600,
    )

    async def read() -> Reading:
        return Reading(markdown="# page", pages=1)

    first, _ = await cache.get_or_compute(WORKSPACE, spec, {"page": 1}, read)
    assert isinstance(first, Reading)
    second = await cache.get_or_compute(WORKSPACE, spec, {"page": 1}, read)
    assert second[0] == first
    assert second[1] is True


async def test_a_provider_failure_writes_nothing_and_poisons_no_key() -> None:
    store = InMemoryCacheStore()
    cache = ProviderCache(store)
    attempts = 0

    async def failing() -> str:
        nonlocal attempts
        attempts += 1
        raise ConnectionError("provider refused")

    with pytest.raises(ConnectionError):
        await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, failing)
    assert store.entries == 0

    # The next attempt is not told this key is known-bad, because a transient
    # provider failure would otherwise last until someone changed the graph.
    with pytest.raises(ConnectionError):
        await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, failing)
    assert attempts == 2
    assert cache.in_flight == 0


async def test_cancellation_writes_nothing_and_releases_the_key() -> None:
    store = InMemoryCacheStore()
    cache = ProviderCache(store)
    started = asyncio.Event()
    never = asyncio.Event()

    async def hanging() -> str:
        started.set()
        await never.wait()
        return "too late"

    async def cancelled_call() -> None:
        task = asyncio.create_task(
            cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, hanging)
        )
        await started.wait()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    await cancelled_call()
    assert store.entries == 0
    gc.collect()
    # Nothing holds the attempt any more, so the map gives its lock up: a key that
    # was cancelled once does not keep a lock for the life of the process.
    assert cache.in_flight == 0

    async def after() -> str:
        return "computed later"

    assert await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, after) == (
        "computed later",
        False,
    )


async def test_locks_are_not_kept_for_keys_that_have_finished() -> None:
    cache = ProviderCache(InMemoryCacheStore())

    async def read() -> str:
        return "text"

    async def many_keys() -> None:
        for page in range(20):
            await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": page}, read)

    await many_keys()
    gc.collect()
    assert cache.in_flight == 0


async def test_concurrent_misses_on_one_key_make_one_provider_call() -> None:
    cache = ProviderCache(InMemoryCacheStore())
    calls = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_read() -> str:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return "one answer"

    first = asyncio.create_task(
        cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, slow_read)
    )
    await entered.wait()
    second = asyncio.create_task(
        cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, slow_read)
    )
    third = asyncio.create_task(
        cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, slow_read)
    )
    await _let_tasks_reach_the_lock([second, third])
    release.set()
    results = await asyncio.gather(first, second, third)

    assert calls == 1
    assert [value for value, _ in results] == ["one answer"] * 3
    # Exactly one caller computed. The boolean means "this caller skipped compute",
    # so the two that waited on the first are the hits.
    assert sorted(hit for _, hit in results) == [False, True, True]


async def test_a_cancelled_leader_does_not_strand_a_waiter() -> None:
    cache = ProviderCache(InMemoryCacheStore())
    calls = 0
    entered = asyncio.Event()
    never = asyncio.Event()

    async def hanging() -> str:
        nonlocal calls
        calls += 1
        entered.set()
        await never.wait()
        return "never"

    async def computed() -> str:
        nonlocal calls
        calls += 1
        return "answered after the cancellation"

    leader = asyncio.create_task(
        cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, hanging)
    )
    await entered.wait()
    waiter = asyncio.create_task(
        cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, computed)
    )
    await _let_tasks_reach_the_lock([waiter])
    leader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await leader
    assert await waiter == ("answered after the cancellation", False)
    assert calls == 2


async def test_two_requests_in_flight_at_once_do_not_wait_on_each_other() -> None:
    cache = ProviderCache(InMemoryCacheStore())
    entered = asyncio.Event()
    release = asyncio.Event()

    async def read(page: int) -> str:
        entered.set()
        await release.wait()
        return f"text of page {page}"

    first = asyncio.create_task(
        cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, lambda: read(1))
    )
    await entered.wait()
    second = asyncio.create_task(
        cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 2}, lambda: read(2))
    )
    await _let_tasks_reach_the_lock([second])
    release.set()

    assert await first == ("text of page 1", False)
    assert await second == ("text of page 2", False)


async def test_answers_never_cross_the_workspace_partition() -> None:
    store = InMemoryCacheStore()
    cache = ProviderCache(store)
    calls = 0

    async def read() -> str:
        nonlocal calls
        calls += 1
        return f"reading {calls}"

    assert await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, read) == (
        "reading 1",
        False,
    )
    assert await cache.get_or_compute(
        OTHER_WORKSPACE, TEXT_SPEC, {"page": 1}, read
    ) == (
        "reading 2",
        False,
    )
    assert await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, read) == (
        "reading 1",
        True,
    )
    assert store.entries == 2


async def test_an_expired_entry_is_a_miss_that_gets_replaced() -> None:
    clock = FakeClock(datetime(2026, 7, 20, 8, 0, tzinfo=UTC))
    store = InMemoryCacheStore(clock=clock)
    cache = ProviderCache(store, clock=clock)
    calls = 0

    async def read() -> str:
        nonlocal calls
        calls += 1
        return f"read number {calls}"

    spec = CacheSpec(
        operation=TEXT_SPEC.operation,
        deployment=TEXT_SPEC.deployment,
        revision=TEXT_SPEC.revision,
        schema_version=TEXT_SPEC.schema_version,
        codec=TEXT_SPEC.codec,
        ttl_seconds=60,
    )
    assert await cache.get_or_compute(WORKSPACE, spec, {"page": 1}, read) == (
        "read number 1",
        False,
    )
    clock.advance(seconds=61)
    assert await store.get(WORKSPACE, spec.key({"page": 1})) is None
    assert await cache.get_or_compute(WORKSPACE, spec, {"page": 1}, read) == (
        "read number 2",
        False,
    )
    assert await cache.get_or_compute(WORKSPACE, spec, {"page": 1}, read) == (
        "read number 2",
        True,
    )
    assert store.entries == 1  # the expired row was replaced, not stacked behind it


async def test_a_payload_the_codec_refuses_is_dropped_not_raised() -> None:
    store = InMemoryCacheStore()
    cache = ProviderCache(store)
    calls = 0
    await store.put(
        WORKSPACE, TEXT_SPEC.key({"page": 1}), b'{"pages": "two"}', ttl_seconds=600
    )

    async def read() -> str:
        nonlocal calls
        calls += 1
        return "recomputed"

    assert await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, read) == (
        "recomputed",
        False,
    )
    # The unreadable row was retired, so the next call hits the answer that
    # replaced it instead of paying the provider again forever.
    assert await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, read) == (
        "recomputed",
        True,
    )
    assert calls == 1


async def test_hits_and_misses_are_visible_in_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A deployment needs to tell a working cache from an absent one.

    The line carries the operation and the key rather than the request, because the
    request is what may name a document; the key is already a digest of it.
    """

    cache = ProviderCache(InMemoryCacheStore())
    calls = 0

    async def read() -> str:
        nonlocal calls
        calls += 1
        return "text"

    with caplog.at_level(logging.DEBUG, logger="grafy_core.provider_cache"):
        await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 7}, read)
        await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 7}, read)

    lines = [record.getMessage() for record in caplog.records]
    miss = next(line for line in lines if "provider_cache_miss" in line)
    hit = next(line for line in lines if "provider_cache_hit" in line)
    assert f"operation={TEXT_SPEC.operation}" in miss
    assert "coalesced=False" in hit
    assert calls == 1

    # A request value never reaches the log, only its digest.
    secret_request: JsonValue = {
        "page": 7,
        "document_title": "scan of the sealed annex",
    }
    await cache.get_or_compute(WORKSPACE, TEXT_SPEC, secret_request, read)
    assert "sealed annex" not in caplog.text


async def test_a_caller_that_waited_on_another_is_logged_as_coalesced(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache = ProviderCache(InMemoryCacheStore())
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_read() -> str:
        entered.set()
        await release.wait()
        return "one answer"

    leader = asyncio.create_task(
        cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, slow_read)
    )
    await entered.wait()
    with caplog.at_level(logging.DEBUG, logger="grafy_core.provider_cache"):
        waiter = asyncio.create_task(
            cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, slow_read)
        )
        await _let_tasks_reach_the_lock([waiter])
        release.set()
        assert await leader == ("one answer", False)
        assert await waiter == ("one answer", True)

    lines = [record.getMessage() for record in caplog.records]
    hit = next(line for line in lines if "provider_cache_hit" in line)
    assert "coalesced=True" in hit


async def test_a_cache_that_cannot_read_is_a_cache_that_was_not_there() -> None:
    cache = ProviderCache(FlakyStore(fail_get=True))

    async def read() -> str:
        return "the provider answered"

    assert await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, read) == (
        "the provider answered",
        False,
    )


async def test_a_cache_that_cannot_write_keeps_the_answer_anyway() -> None:
    store = FlakyStore(fail_put=True)
    cache = ProviderCache(store)
    calls = 0

    async def read() -> str:
        nonlocal calls
        calls += 1
        return "the provider answered"

    for _ in range(2):
        assert await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, read) == (
            "the provider answered",
            False,
        )
    assert calls == 2
    assert store.put_calls == 2


async def test_a_write_that_loses_the_race_returns_the_stored_answer() -> None:
    class ContestedStore(InMemoryCacheStore):
        """A store where another process has already written by the time we do."""

        async def put_if_absent(
            self, workspace: UUID, key: str, value: bytes, *, ttl_seconds: int
        ) -> bytes:
            await super().put_if_absent(
                workspace, key, b'"the other process"', ttl_seconds=ttl_seconds
            )
            return await super().put_if_absent(
                workspace, key, value, ttl_seconds=ttl_seconds
            )

    cache = ProviderCache(ContestedStore())

    async def read() -> str:
        return "mine"

    assert await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, read) == (
        "the other process",
        False,
    )  # not a hit: this caller did call its provider


async def test_an_answer_too_large_to_keep_is_still_an_answer() -> None:
    cache = ProviderCache(RefusingStore())

    async def read() -> str:
        return "a very large transcription"

    assert await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, read) == (
        "a very large transcription",
        False,
    )


async def test_expired_rows_are_reclaimed_in_bounded_batches() -> None:
    clock = FakeClock(datetime(2026, 7, 20, 8, 0, tzinfo=UTC))
    store = CountingStore(clock=clock)
    cache = ProviderCache(store, clock=clock, cleanup_batch_rows=2)
    short_lived = CacheSpec(
        operation=TEXT_SPEC.operation,
        deployment=TEXT_SPEC.deployment,
        revision=TEXT_SPEC.revision,
        schema_version=TEXT_SPEC.schema_version,
        codec=TEXT_SPEC.codec,
        ttl_seconds=1,
    )

    async def read() -> str:
        return "text"

    for page in range(4):
        await cache.get_or_compute(WORKSPACE, short_lived, {"page": page}, read)
    assert store.entries == 4

    clock.advance(seconds=5)
    assert await cache.cleanup_expired(limit=2) == 2
    assert store.entries == 2
    assert await cache.cleanup_expired() == 2
    assert store.entries == 0


async def test_the_opportunistic_sweep_runs_once_per_interval_not_per_write() -> None:
    store = CountingStore()
    cache = ProviderCache(store, cleanup_interval_seconds=3_600, cleanup_batch_rows=10)

    async def read() -> str:
        return "text"

    for page in range(5):
        await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": page}, read)
    assert store.sweeps == [10]


def test_cached_call_keeps_the_signature_and_reports_what_happened() -> None:
    cache = ProviderCache(InMemoryCacheStore())
    observations: list[bool] = []
    calls = 0

    async def read(page: int, *, language: str = "en") -> str:
        nonlocal calls
        calls += 1
        return f"{language} text of page {page}"

    wrapped = cached_call(
        read,
        cache=cache,
        workspace=WORKSPACE,
        spec=TEXT_SPEC,
        identify=lambda page, language="en": {"page": page, "language": language},
        observe_hit=observations.append,
    )
    assert inspect.signature(wrapped) == inspect.signature(read)

    async def exercise() -> list[str]:
        return [
            await wrapped(3),
            await wrapped(3, language="en"),
            await wrapped(3, language="de"),
        ]

    assert asyncio.run(exercise()) == ["en text of page 3"] * 2 + ["de text of page 3"]
    assert calls == 2
    assert observations == [False, True, False]


async def test_a_batch_asks_the_provider_only_for_the_misses() -> None:
    cache = ProviderCache(InMemoryCacheStore())
    calls: list[list[int]] = []

    async def compute_one() -> str:
        return "stored"

    await cache.get_or_compute(WORKSPACE, TEXT_SPEC, {"page": 1}, compute_one)
    pages = [0, 1, 0, 2]

    async def compute_many(missing: Sequence[int]) -> list[str]:
        calls.append(list(missing))
        return [f"page {pages[index]}" for index in missing]

    found = await cache.get_or_compute_many(
        WORKSPACE,
        TEXT_SPEC,
        [{"page": page} for page in pages],
        compute_many,
    )

    assert calls == [[0, 3]]
    assert found == [
        ("page 0", False),
        ("stored", True),
        ("page 0", False),
        ("page 2", False),
    ]
    assert cache.in_flight == 0

    async def explode(missing: Sequence[int]) -> list[str]:
        raise AssertionError(missing)

    again = await cache.get_or_compute_many(
        WORKSPACE,
        TEXT_SPEC,
        [{"page": 0}, {"page": 1}, {"page": 2}],
        explode,
    )
    assert [hit for _, hit in again] == [True, True, True]


async def test_a_failed_batch_stores_nothing() -> None:
    store = InMemoryCacheStore()
    cache = ProviderCache(store)

    async def boom(missing: Sequence[int]) -> list[str]:
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError, match="provider down"):
        await cache.get_or_compute_many(
            WORKSPACE, TEXT_SPEC, [{"page": 1}, {"page": 2}], boom
        )
    assert cache.in_flight == 0
    assert store.entries == 0

    async def short(missing: Sequence[int]) -> list[str]:
        return ["only"]

    with pytest.raises(ProviderCacheError, match="2 misses"):
        await cache.get_or_compute_many(
            WORKSPACE, TEXT_SPEC, [{"page": 1}, {"page": 2}], short
        )
    assert store.entries == 0


async def test_overlapping_batches_compute_a_shared_key_once() -> None:
    cache = ProviderCache(InMemoryCacheStore())
    entered = asyncio.Event()
    release = asyncio.Event()
    computed: list[int] = []

    async def run(pages: list[int]) -> list[tuple[str, bool]]:
        async def slow(missing: Sequence[int]) -> list[str]:
            computed.extend(pages[index] for index in missing)
            if pages == [1, 2]:
                entered.set()
                await release.wait()
            return [f"page {pages[index]}" for index in missing]

        return await cache.get_or_compute_many(
            WORKSPACE, TEXT_SPEC, [{"page": page} for page in pages], slow
        )

    first = asyncio.create_task(run([1, 2]))
    await entered.wait()
    second = asyncio.create_task(run([2, 3]))
    await _let_tasks_reach_the_lock([second])
    release.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert sorted(computed) == [1, 2, 3]
    assert first_result == [("page 1", False), ("page 2", False)]
    assert second_result[0] == ("page 2", True)
    assert second_result[1] == ("page 3", False)
    assert cache.in_flight == 0


async def _let_tasks_reach_the_lock(tasks: list[asyncio.Task[object]]) -> None:
    """Give each task its turns until it is parked, rather than sleeping.

    Waiting on the lock is the thing under test, so the test hands over control
    until the waiter is queued and asserts against what it observes afterwards.
    """

    for _ in range(4):
        await asyncio.sleep(0)
    done = [task for task in tasks if task.done()]
    assert done == []

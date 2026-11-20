"""SQL store for the provider-operation cache.

Unlike every other adapter here, this one takes a session *factory* instead of a
session. The difference is the point: a node computation holds its unit of work
while it materializes inputs and waits on a provider, and a cache read must never
be pulled into that transaction — it would hold the transaction open across the
provider call, and the write that has to land the moment the answer arrives could
not land at all. Each operation below therefore opens, uses, and commits a
transaction of its own.

Atomicity is what replaces the cross-process lock Grafy does not run: the insert
decides existence and expiry in one statement and the winner is read back in the
same transaction, so two API processes writing the same key leave one complete row
rather than a torn one, and the loser is handed the bytes that persisted.
"""

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from grafy_core.provider_cache import (
    CacheStore,
    CacheStoreMaintenance,
    ProviderOperationPayloadTooLargeError,
)

from grafy_persistence import schema

#: A dense page of OCR markdown is well under this. The bound exists so the cache
#: cannot become the largest table in a deployment by accident: an answer too large
#: to keep is simply not kept, and the operation that produced it is unaffected.
DEFAULT_MAX_PAYLOAD_BYTES = 2_000_000


class SqlProviderOperationStore(CacheStore, CacheStoreMaintenance):
    """Workspace-partitioned provider answers in the relational database.

    Failures are raised for :class:`~grafy_core.provider_cache.ProviderCache` to
    absorb at the store boundary. This class does not decide whether a failure is
    recoverable and never turns one into an empty answer: a store that swallows its
    own errors would hide them from the one place that logs them.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
    ) -> None:
        if max_payload_bytes < 1:
            raise ValueError("max_payload_bytes must be at least 1")
        self._sessions = sessions
        self._max_payload_bytes = max_payload_bytes

    async def get(self, workspace: UUID, key: str) -> bytes | None:
        """The live payload for this Workspace and key, or None.

        ``expires_at`` is compared in the statement, so an entry whose ttl has
        passed is a miss here whether or not a sweep has reclaimed its row.
        """

        table = schema.provider_operations
        async with self._sessions() as session:
            return await session.scalar(
                select(table.c.payload)
                .where(table.c.workspace_id == workspace)
                .where(table.c.key_sha256 == key)
                .where(table.c.expires_at > datetime.now(UTC))
            )

    async def put_if_absent(
        self, workspace: UUID, key: str, value: bytes, *, ttl_seconds: int
    ) -> bytes:
        self._check_size(value)
        return await self._write(
            workspace, key, value, ttl_seconds=ttl_seconds, only_replacing_expired=True
        )

    async def put(
        self, workspace: UUID, key: str, value: bytes, *, ttl_seconds: int
    ) -> None:
        self._check_size(value)
        await self._write(
            workspace, key, value, ttl_seconds=ttl_seconds, only_replacing_expired=False
        )

    async def delete_expired(self, *, now: datetime, limit: int) -> int:
        """Reclaim at most ``limit`` expired rows, in every Workspace.

        The bound is a row-value ``IN`` over a keyed subquery rather than
        ``DELETE ... LIMIT``, which PostgreSQL does not have: one sweep stays a
        bounded statement, and a deployment far behind on its expiry pays for it
        over several calls instead of in one long statement.
        """

        if limit < 1:
            return 0
        table = schema.provider_operations
        doomed = (
            select(table.c.workspace_id, table.c.key_sha256)
            .where(table.c.expires_at <= now)
            .limit(limit)
        )
        doomed_rows = tuple_(table.c.workspace_id, table.c.key_sha256).in_(doomed)
        async with self._sessions() as session:
            async with session.begin():
                deleted = cast(
                    "CursorResult[tuple[object, ...]]",
                    await session.execute(delete(table).where(doomed_rows)),
                )
                return deleted.rowcount

    async def _write(
        self,
        workspace: UUID,
        key: str,
        value: bytes,
        *,
        ttl_seconds: int,
        only_replacing_expired: bool,
    ) -> bytes:
        """Insert, then report what the key holds.

        With ``only_replacing_expired`` an existing live row survives and its bytes
        come back, which is the whole cross-process guarantee: both writers got an
        answer, one of them is the stored one, and neither left a partial row.
        Without it the key is replaced whatever it holds, which is how a caller
        retires an entry it can no longer decode. ``ttl_seconds`` of 0 stores a row
        that is already expired: invisible at once, reclaimed by the next sweep.
        """

        table = schema.provider_operations
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        async with self._sessions() as session:
            async with session.begin():
                dialect_name = session.get_bind().dialect.name
                if dialect_name == "sqlite":
                    insert = sqlite_insert(table)
                elif dialect_name == "postgresql":
                    insert = postgresql_insert(table)
                else:
                    raise NotImplementedError(
                        "Provider-operation cache writes require SQLite or "
                        f"PostgreSQL; received dialect {dialect_name!r}"
                    )
                insert = insert.values(
                    workspace_id=workspace,
                    key_sha256=key,
                    payload=value,
                    stored_at=now,
                    expires_at=expires_at,
                )
                replacement = {
                    "payload": insert.excluded.payload,
                    "stored_at": insert.excluded.stored_at,
                    "expires_at": insert.excluded.expires_at,
                }
                index_elements = (table.c.workspace_id, table.c.key_sha256)
                if only_replacing_expired:
                    await session.execute(
                        insert.on_conflict_do_update(
                            index_elements=index_elements,
                            set_=replacement,
                            where=table.c.expires_at <= now,
                        )
                    )
                else:
                    await session.execute(
                        insert.on_conflict_do_update(
                            index_elements=index_elements,
                            set_=replacement,
                        )
                    )
                stored = await session.scalar(
                    select(table.c.payload)
                    .where(table.c.workspace_id == workspace)
                    .where(table.c.key_sha256 == key)
                )
        if stored is None:
            # The row vanished behind us — a Workspace deletion cascaded onto it.
            # The caller has a real answer in hand, so handing back the bytes it
            # wrote keeps the report honest; the next caller just misses.
            return value
        return stored

    def _check_size(self, value: bytes) -> None:
        if len(value) > self._max_payload_bytes:
            raise ProviderOperationPayloadTooLargeError(
                f"Provider answer is {len(value)} bytes, over the "
                f"{self._max_payload_bytes} this deployment keeps"
            )


__all__ = ["DEFAULT_MAX_PAYLOAD_BYTES", "SqlProviderOperationStore"]

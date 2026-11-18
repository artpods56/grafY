"""The SQL provider-operation store: partition, expiry, and the write race.

These run on SQLite. The statements that carry the guarantees — an upsert whose
update is conditional on expiry, and a row-value ``IN`` delete for the sweep — are
the two a dialect tends to get wrong, and both are written once for SQLite and
PostgreSQL.
"""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import TypeAdapter
from sqlalchemy import insert, select
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from grafy_core.domain.identity import Workspace, WorkspaceKind
from grafy_core.provider_cache import (
    CacheSpec,
    ProviderCache,
    ProviderOperationPayloadTooLargeError,
)
from grafy_persistence import schema
from grafy_persistence.database import Database, create_database
from grafy_persistence.adapters.repositories import SqlProviderOperationStore
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

WORKSPACE = UUID("00000000-0000-0000-0000-0000000000a1")
OTHER_WORKSPACE = UUID("00000000-0000-0000-0000-0000000000b2")
UNKNOWN_WORKSPACE = UUID("00000000-0000-0000-0000-0000000000c3")

KEY = "a" * 64
OTHER_KEY = "b" * 64
LIVE_KEY = "c" * 64

TEXT_ADAPTER: TypeAdapter[str] = TypeAdapter(str)


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    created = create_database(
        f"sqlite+aiosqlite:///{tmp_path / 'provider-ops.sqlite3'}"
    )
    async with created.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    async with SqlAlchemyUnitOfWork(created.sessions) as uow:
        for workspace_id in (WORKSPACE, OTHER_WORKSPACE):
            await uow.identity.add_workspace(
                Workspace(
                    id=workspace_id,
                    slug=f"ws-{str(workspace_id)[-4:]}",
                    name="Team",
                    kind=WorkspaceKind.SHARED,
                )
            )
        await uow.commit()
    try:
        yield created
    finally:
        await created.dispose()


@pytest.fixture
def store(database: Database) -> SqlProviderOperationStore:
    return SqlProviderOperationStore(database.sessions)


async def test_an_answer_round_trips_and_is_scoped_to_its_workspace(
    store: SqlProviderOperationStore, database: Database
) -> None:
    assert await store.get(WORKSPACE, KEY) is None
    assert await store.put_if_absent(
        WORKSPACE, KEY, b'"page text"', ttl_seconds=600
    ) == (b'"page text"')
    assert await store.get(WORKSPACE, KEY) == b'"page text"'

    # The same key in another Workspace is a different row, in both directions.
    assert await store.get(OTHER_WORKSPACE, KEY) is None
    await store.put_if_absent(OTHER_WORKSPACE, KEY, b'"other answer"', ttl_seconds=600)
    assert await store.get(WORKSPACE, KEY) == b'"page text"'
    assert await store.get(OTHER_WORKSPACE, KEY) == b'"other answer"'

    assert {(row[0], row[1]) for row in await _rows(database)} == {
        (WORKSPACE, KEY),
        (OTHER_WORKSPACE, KEY),
    }


async def test_a_key_only_exists_inside_a_workspace(
    store: SqlProviderOperationStore,
) -> None:
    """The foreign key is what makes the partition a storage fact, not a convention."""

    with pytest.raises(IntegrityError):
        await store.put_if_absent(UNKNOWN_WORKSPACE, KEY, b'"x"', ttl_seconds=60)
    assert await store.get(UNKNOWN_WORKSPACE, KEY) is None


async def test_deleting_a_workspace_takes_its_answers(
    store: SqlProviderOperationStore, database: Database
) -> None:
    await store.put_if_absent(WORKSPACE, KEY, b'"page text"', ttl_seconds=600)
    async with database.sessions() as session:
        async with session.begin():
            await session.execute(
                schema.workspaces.delete().where(schema.workspaces.c.id == WORKSPACE)
            )
    assert await store.get(WORKSPACE, KEY) is None
    assert await _rows(database) == []


async def test_a_live_entry_survives_a_second_writer_and_an_expired_one_does_not(
    store: SqlProviderOperationStore,
) -> None:
    winner = await store.put_if_absent(WORKSPACE, KEY, b'"first"', ttl_seconds=600)
    loser = await store.put_if_absent(WORKSPACE, KEY, b'"second"', ttl_seconds=600)

    assert winner == b'"first"'
    assert loser == b'"first"'  # the persisted bytes, not the ones this caller sent
    assert await store.get(WORKSPACE, KEY) == b'"first"'

    # A zero ttl stores an entry that has already expired: invisible at once, and
    # absent for the next writer, which is how a caller retires an entry it cannot
    # decode instead of blocking the key forever.
    await store.put(WORKSPACE, KEY, b"", ttl_seconds=0)
    assert await store.get(WORKSPACE, KEY) is None
    assert await store.put_if_absent(WORKSPACE, KEY, b'"third"', ttl_seconds=600) == (
        b'"third"'
    )
    assert await store.get(WORKSPACE, KEY) == b'"third"'


async def test_put_replaces_what_the_key_holds(
    store: SqlProviderOperationStore,
) -> None:
    await store.put_if_absent(WORKSPACE, KEY, b'"unreadable"', ttl_seconds=600)
    await store.put(WORKSPACE, KEY, b'"replaced"', ttl_seconds=600)
    assert await store.get(WORKSPACE, KEY) == b'"replaced"'


async def test_expiry_ends_service_before_any_sweep(
    store: SqlProviderOperationStore,
) -> None:
    await store.put_if_absent(WORKSPACE, KEY, b'"brief"', ttl_seconds=0)
    assert await store.get(WORKSPACE, KEY) is None


async def test_expired_rows_are_reclaimed_in_bounded_batches(
    store: SqlProviderOperationStore, database: Database
) -> None:
    now = datetime.now(UTC)
    async with database.sessions() as session:
        async with session.begin():
            for key in (KEY, OTHER_KEY):
                await session.execute(
                    insert(schema.provider_operations).values(
                        workspace_id=WORKSPACE,
                        key_sha256=key,
                        payload=b'"stale"',
                        stored_at=now - timedelta(hours=2),
                        expires_at=now - timedelta(hours=1),
                    )
                )
            await session.execute(
                insert(schema.provider_operations).values(
                    workspace_id=WORKSPACE,
                    key_sha256=LIVE_KEY,
                    payload=b'"live"',
                    stored_at=now,
                    expires_at=now + timedelta(hours=1),
                )
            )

    assert await store.delete_expired(now=now, limit=1) == 1
    assert await store.delete_expired(now=now, limit=10) == 1
    assert await store.delete_expired(now=now, limit=10) == 0
    assert await store.delete_expired(now=now, limit=0) == 0
    assert await store.get(WORKSPACE, LIVE_KEY) == b'"live"'


async def test_an_answer_larger_than_the_bound_is_refused(
    database: Database,
) -> None:
    store = SqlProviderOperationStore(database.sessions, max_payload_bytes=16)
    with pytest.raises(ProviderOperationPayloadTooLargeError):
        await store.put_if_absent(WORKSPACE, KEY, b"x" * 17, ttl_seconds=60)
    with pytest.raises(ProviderOperationPayloadTooLargeError):
        await store.put(WORKSPACE, KEY, b"x" * 17, ttl_seconds=60)
    assert await store.get(WORKSPACE, KEY) is None


async def test_the_cache_read_and_write_paths_run_over_the_sql_store(
    store: SqlProviderOperationStore, database: Database
) -> None:
    """End to end, because a store that fits a protocol on paper is not enough.

    Each call takes its own short transaction, so nothing is held open while a
    provider is waited on, and the second call finds the row the first committed.
    """

    calls = 0
    spec = CacheSpec(
        operation="ocr.window",
        deployment="fake.ocr@1",
        revision="rev-aaaa",
        schema_version=1,
        codec=TEXT_ADAPTER,
        ttl_seconds=600,
    )
    cache = ProviderCache(store)

    async def read() -> str:
        nonlocal calls
        calls += 1
        return "the provider answered"

    assert await cache.get_or_compute(WORKSPACE, spec, {"page": 1}, read) == (
        "the provider answered",
        False,
    )
    assert await cache.get_or_compute(WORKSPACE, spec, {"page": 1}, read) == (
        "the provider answered",
        True,
    )
    assert calls == 1
    assert len(await _rows(database)) == 1

    # Another API process, here a second engine over the same file, reads the same
    # answer: the row is the cross-process state, not the in-memory call graph.
    other_engine = create_async_engine(database.engine.url)
    try:
        other_process = SqlProviderOperationStore(
            async_sessionmaker(other_engine, expire_on_commit=False)
        )
        assert await other_process.get(WORKSPACE, spec.key({"page": 1})) == (
            b'"the provider answered"'
        )
    finally:
        await other_engine.dispose()


async def _rows(database: Database) -> Sequence[Row[tuple[UUID, str]]]:
    """Every row, as storage sees it, so a test asserts on rows and not only answers."""

    table = schema.provider_operations
    async with database.sessions() as session:
        result = await session.execute(
            select(table.c.workspace_id, table.c.key_sha256).order_by(
                table.c.workspace_id, table.c.key_sha256
            )
        )
        return list(result)

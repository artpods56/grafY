import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from grafy_core.domain.execution_history import TransientExecution
from grafy_persistence import schema
from grafy_persistence.database import Database, create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_persistence.adapters.repositories import (
    SqlGraphExecutionHistoryRepository,
    SqlPluginReleaseRepository,
)


@pytest.fixture(params=["sqlite", "postgresql"])
async def fence_database(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[Database]:
    if request.param == "postgresql":
        url = os.environ.get("GRAFY_TEST_TRANSIENT_POSTGRES_URL")
        if url is None:
            pytest.skip("Transient-fence PostgreSQL is not configured")
        admin = create_database(url)
        schema_name = "transient_test_" + uuid4().hex
        async with admin.engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        engine = create_async_engine(
            url, connect_args={"server_settings": {"search_path": schema_name}}
        )
        database = Database(
            engine=engine, sessions=async_sessionmaker(engine, expire_on_commit=False)
        )
        try:
            async with engine.begin() as connection:
                await connection.run_sync(schema.metadata.create_all)
            yield database
        finally:
            await engine.dispose()
            async with admin.engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
            await admin.dispose()
    else:
        database = create_database(f"sqlite+aiosqlite:///{tmp_path / 'fence.sqlite3'}")
        try:
            async with database.engine.begin() as connection:
                await connection.run_sync(schema.metadata.create_all)
            yield database
        finally:
            await database.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("admission_first", [True, False])
async def test_transient_insert_and_maintenance_have_conflicting_database_locks(
    fence_database: Database, admission_first: bool
) -> None:
    database = fence_database
    marker = TransientExecution(
        execution_id=uuid4(),
        workspace_id=uuid4(),
        owner_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as first:
        if admission_first:
            await first.execution_history.add_transient(marker)
        else:
            assert await first.plugin_releases.lock_system_revocation() == ()
        async with database.sessions() as second_session:
            if database.engine.dialect.name == "postgresql":
                await second_session.execute(text("SET LOCAL lock_timeout = '50ms'"))
            with pytest.raises(DBAPIError) as blocked:
                if admission_first:
                    await SqlPluginReleaseRepository(
                        second_session
                    ).lock_system_revocation()
                else:
                    await SqlGraphExecutionHistoryRepository(
                        second_session
                    ).add_transient(marker)
            message = str(blocked.value).lower()
            assert "database is locked" in message or "lock timeout" in message
            await second_session.rollback()
        await first.commit()
    async with SqlAlchemyUnitOfWork(database.sessions) as following:
        if admission_first:
            active = await following.plugin_releases.lock_system_revocation()
            assert [execution.execution_id for execution in active] == [
                marker.execution_id
            ]
        else:
            await following.execution_history.add_transient(marker)
        await following.commit()
    async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
        assert await transaction.execution_history.list_transient() == (marker,)

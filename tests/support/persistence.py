"""Disposable SQL adapter fixtures, isolated by PostgreSQL schema per test."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from grafy_persistence import schema
from grafy_persistence.database import Database, create_database

metadata = schema.metadata

WORKSPACE_ONE = UUID("00000000-0000-0000-0000-000000000001")
WORKSPACE_TWO = UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture(params=["sqlite", "postgresql"])
async def database(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> AsyncIterator[Database]:
    backend = cast(Literal["sqlite", "postgresql"], request.param)
    admin: Database | None = None
    schema_name = "persistence_test_" + uuid4().hex
    if backend == "postgresql":
        database_url = os.environ.get("GRAFY_TEST_POSTGRES_URL")
        if database_url is None:
            pytest.skip("GRAFY_TEST_POSTGRES_URL is not configured")
        if not database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("GRAFY_TEST_POSTGRES_URL must use postgresql+asyncpg")
        admin = create_database(database_url)
        async with admin.engine.begin() as connection:
            await connection.execute(CreateSchema(schema_name))
        engine = create_async_engine(
            database_url,
            connect_args={"server_settings": {"search_path": schema_name}},
        )
        created = Database(engine, async_sessionmaker(engine, expire_on_commit=False))
    else:
        created = create_database(
            f"sqlite+aiosqlite:///{tmp_path / 'persistence.sqlite3'}"
        )
    try:
        async with created.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(
                schema.workspaces.insert(),
                [
                    {
                        "id": WORKSPACE_ONE,
                        "slug": "one",
                        "name": "One",
                        "kind": "shared",
                        "created_at": datetime(2026, 7, 1, tzinfo=UTC),
                        "updated_at": datetime(2026, 7, 1, tzinfo=UTC),
                    },
                    {
                        "id": WORKSPACE_TWO,
                        "slug": "two",
                        "name": "Two",
                        "kind": "shared",
                        "created_at": datetime(2026, 7, 1, tzinfo=UTC),
                        "updated_at": datetime(2026, 7, 1, tzinfo=UTC),
                    },
                ],
            )
        yield created
    finally:
        await created.dispose()
        if admin is not None:
            try:
                async with admin.engine.begin() as connection:
                    await connection.execute(DropSchema(schema_name, cascade=True))
            finally:
                await admin.dispose()

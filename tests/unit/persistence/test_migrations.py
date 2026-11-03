import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from grafy_api.settings import get_settings
from grafy_persistence import schema
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

MIGRATION_DIRECTORY = REPOSITORY_ROOT / "infra" / "db" / "migrations" / "versions"

# The schema in one baseline: every table `0001_baseline` creates. A table that
# appears or disappears here is a schema decision, so it is named rather than
# read back out of the metadata the migration is checked against.
BASELINE_TABLES = {
    "artifact_objects",
    "auth_sessions",
    "library_artifact_placements",
    "library_folders",
    "node_secrets",
    "oidc_identities",
    "oidc_login_transactions",
    "personal_access_tokens",
    "project_checkpoint_mappings",
    "project_checkpoints",
    "project_command_receipts",
    "project_folders",
    "project_heads",
    "project_organizations",
    "projects",
    "security_audit_events",
    "uploads",
    "user_project_states",
    "users",
    "workspace_invitations",
    "workspace_memberships",
    "workspaces",
}


def _alembic_config() -> Config:
    return Config(REPOSITORY_ROOT / "alembic.ini")


def _table_names(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names())


async def _postgresql_migration_state(
    database_url: str,
) -> tuple[list[str], str | None, int | None]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
            if "alembic_version" not in tables:
                return tables, None, None
            revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            if "workspaces" not in tables:
                return tables, revision, None
            workspace_count = await connection.scalar(
                text("SELECT COUNT(*) FROM workspaces")
            )
            return tables, revision, workspace_count
    finally:
        await engine.dispose()


def test_migration_directory_holds_one_baseline_revision() -> None:
    """ADR 0020 keeps no rows, so there is no revision history to walk."""

    files = sorted(path.name for path in MIGRATION_DIRECTORY.glob("*.py"))
    assert files == ["0001_baseline.py"]

    config = _alembic_config()
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert heads == ["0001_baseline"]
    revisions = list(script.walk_revisions())
    assert [revision.revision for revision in revisions] == ["0001_baseline"]
    assert revisions[0].down_revision is None


def test_fresh_postgresql_database_upgrades_to_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.environ.get("GRAFY_TEST_POSTGRES_URL")
    if database_url is None:
        pytest.skip("GRAFY_TEST_POSTGRES_URL is not configured")
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError(
            "GRAFY_TEST_POSTGRES_URL must use the postgresql+asyncpg driver"
        )

    monkeypatch.setenv("GRAFY_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _alembic_config()
    try:
        existing_tables, _, _ = asyncio.run(_postgresql_migration_state(database_url))
        if existing_tables:
            raise RuntimeError(
                "GRAFY_TEST_POSTGRES_URL must reference an empty disposable database"
            )

        command.upgrade(config, "head")

        tables, revision, workspace_count = asyncio.run(
            _postgresql_migration_state(database_url)
        )
        heads = ScriptDirectory.from_config(config).get_heads()
        assert len(heads) == 1
        assert revision == heads[0]
        assert set(tables) == BASELINE_TABLES | {"alembic_version"}
        assert workspace_count == 0
        command.check(config)

        command.downgrade(config, "base")
        tables, revision, workspace_count = asyncio.run(
            _postgresql_migration_state(database_url)
        )
        assert tables == ["alembic_version"]
        assert revision is None
        assert workspace_count is None

        command.upgrade(config, "head")
        tables, _, _ = asyncio.run(_postgresql_migration_state(database_url))
        assert set(tables) == BASELINE_TABLES | {"alembic_version"}
        command.check(config)
    finally:
        get_settings.cache_clear()


def test_baseline_upgrades_downgrades_and_has_no_schema_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "nested" / "baseline.sqlite3"
    monkeypatch.setenv("GRAFY_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    get_settings.cache_clear()

    config = _alembic_config()
    try:
        command.upgrade(config, "head")
        with create_engine(f"sqlite:///{database_path}").connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert _table_names(connection) == BASELINE_TABLES | {"alembic_version"}
            assert connection.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        command.check(config)

        command.downgrade(config, "base")
        with create_engine(f"sqlite:///{database_path}").connect() as connection:
            assert _table_names(connection) == {"alembic_version"}

        command.upgrade(config, "head")
        with create_engine(f"sqlite:///{database_path}").connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert _table_names(connection) == BASELINE_TABLES | {"alembic_version"}
        command.check(config)
    finally:
        get_settings.cache_clear()


def test_baseline_declares_every_index_the_metadata_declares(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partial unique indexes are the schema's own, so they have to survive."""

    database_path = tmp_path / "indexes.sqlite3"
    monkeypatch.setenv("GRAFY_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    get_settings.cache_clear()
    try:
        command.upgrade(_alembic_config(), "head")
        engine = create_engine(f"sqlite:///{database_path}")
        try:
            with engine.connect() as connection:
                inspected = inspect(connection)
                for table in schema.metadata.tables.values():
                    expected = {index.name for index in table.indexes}
                    actual = {
                        index["name"] for index in inspected.get_indexes(table.name)
                    }
                    assert expected == actual, table.name
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()

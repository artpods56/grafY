import asyncio
import json
import importlib
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import Connection, Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.sql.schema import SchemaItem
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects import sqlite

from grafy_api.settings import get_settings
from grafy_persistence.schema import (
    plugin_installations,
    plugin_release_selections,
    plugin_releases,
    staged_uploads,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


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
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    try:
        existing_tables, _, _ = asyncio.run(_postgresql_migration_state(database_url))
        if existing_tables:
            raise RuntimeError(
                "GRAFY_TEST_POSTGRES_URL must reference an empty disposable database"
            )

        command.upgrade(config, "head")

        _, revision, workspace_count = asyncio.run(
            _postgresql_migration_state(database_url)
        )
        assert revision == "0026_drop_plugin_distribution"
        assert workspace_count == 0
        command.check(config)

        command.downgrade(config, "base")
        tables, revision, workspace_count = asyncio.run(
            _postgresql_migration_state(database_url)
        )
        assert tables == ["alembic_version"]
        assert revision is None
        assert workspace_count is None
    finally:
        get_settings.cache_clear()


def test_tenant_rebuild_uses_postgresql_temporary_constraint_names() -> None:
    migration = importlib.import_module(
        "infra.db.migrations.versions.0008_tenant_existing_resources"
    )
    mock_postgresql = type("Dialect", (), {"name": "postgresql"})()
    temporary_name = migration._rebuild_constraint_name(
        type("Connection", (), {"dialect": mock_postgresql})(),
        "pk_saved_graphs",
        "u",
    )
    assert temporary_name == "tmp_0008u_pk_saved_graphs"
    table = Table(
        "_0008_saved_graphs",
        MetaData(),
        Column("id", Integer, primary_key=True),
    )
    table.primary_key.name = temporary_name
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "CONSTRAINT tmp_0008u_pk_saved_graphs PRIMARY KEY" in ddl
    sqlite_upload_ddl = str(
        CreateTable(staged_uploads).compile(dialect=sqlite.dialect())
    )
    postgres_upload_ddl = str(
        CreateTable(staged_uploads).compile(dialect=postgresql.dialect())
    )
    assert "instr(upload_key, char(92)) = 0" in sqlite_upload_ddl
    assert "position(chr(92) in upload_key) = 0" in postgres_upload_ddl


def test_all_0008_upgrade_and_downgrade_tables_compile_for_postgresql() -> None:
    migration = importlib.import_module(
        "infra.db.migrations.versions.0008_tenant_existing_resources"
    )
    captured_tables: list[tuple[str, tuple[SchemaItem, ...]]] = []
    captured_indexes: list[tuple[str, str, tuple[str, ...]]] = []

    class CaptureOperations:
        def create_table(
            self,
            name: str,
            *elements: SchemaItem,
            **kwargs: object,
        ) -> None:
            del kwargs
            captured_tables.append((name, elements))

        def create_index(
            self,
            name: str,
            table_name: str,
            columns: list[str],
            *args: object,
            **kwargs: object,
        ) -> None:
            del args, kwargs
            captured_indexes.append((name, table_name, tuple(columns)))

    class PostgresqlConnection:
        dialect = postgresql.dialect()

        def exec_driver_sql(self, statement: str) -> None:
            del statement

    setattr(migration, "op", CaptureOperations())
    connection = PostgresqlConnection()
    migration._create_tenant_tables(connection)
    migration._create_staged_upload_table(connection)
    migration._create_indexes()
    migration._rebuild_legacy_tables(connection)

    metadata = MetaData()
    Table("workspaces", metadata, Column("id", postgresql.UUID()))
    Table("users", metadata, Column("id", postgresql.UUID()))
    for table_name, elements in captured_tables:
        Table(table_name, metadata, *elements)

    expected_tables = {
        *(f"_0008_{name}" for name in migration._LEGACY_RESOURCE_TABLES),
        "staged_uploads",
        *(f"_0008d_{name}" for name in migration._LEGACY_RESOURCE_TABLES),
    }
    assert {name for name, _ in captured_tables} == expected_tables
    for table in metadata.tables.values():
        if not table.name.startswith(("_0008", "staged_uploads")):
            continue
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert ddl.startswith("\nCREATE TABLE")
        for constraint in table.constraints:
            assert constraint.name is None or len(str(constraint.name)) <= 63
    node_secret_table = next(
        table
        for table in metadata.tables.values()
        if table.name == "_0008_node_secrets"
    )
    node_secret_ddl = str(
        CreateTable(node_secret_table).compile(dialect=postgresql.dialect())
    )
    assert "CONSTRAINT ck_node_secrets_aad_version CHECK (aad_version IN (1, 2))" in (
        node_secret_ddl
    )
    for name, table_name, columns in captured_indexes:
        assert len(name) <= 63
        table = metadata.tables.get(table_name)
        if table is None:
            table = metadata.tables[f"_0008_{table_name}"]
        index = sa.Index(name, *[table.c[column] for column in columns])
        assert str(CreateIndex(index).compile(dialect=postgresql.dialect()))


def test_identity_downgrade_guard_uses_typed_uuid_bind_for_postgresql() -> None:
    migration = importlib.import_module(
        "infra.db.migrations.versions.0007_identity_workspace_foundation"
    )
    statement = migration._local_workspace_guard_query()
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "WHERE id = %(local_id)s" in compiled
    assert isinstance(statement._bindparams["local_id"].type, sa.Uuid)


def test_tenant_upgrade_preflight_leaves_no_temporary_tables_and_retries_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "preflight" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0007_identity_workspace_foundation")
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text("UPDATE workspaces SET slug = 'temporarily-invalid' WHERE id = :id"),
            {"id": "00000000000000000000000000000007"},
        )

    with pytest.raises(RuntimeError, match="deterministic local workspace"):
        command.upgrade(config, "head")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        assert not any(
            table_name.startswith("_0008")
            for table_name in inspect(connection).get_table_names()
        )
        connection.commit()
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text("UPDATE workspaces SET slug = 'local' WHERE id = :id"),
            {"id": "00000000000000000000000000000007"},
        )
    command.upgrade(config, "head")
    get_settings.cache_clear()


def test_tenant_downgrade_preflight_rejects_leftovers_before_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "downgrade-preflight" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "head")
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(text("CREATE TABLE _0008d_saved_graphs (id INTEGER)"))

    with pytest.raises(RuntimeError, match="temporary table"):
        command.downgrade(config, "0007_identity_workspace_foundation")
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        assert "_0008d_saved_graphs" in inspect(connection).get_table_names()
        connection.execute(text("DROP TABLE _0008d_saved_graphs"))
    command.downgrade(config, "0007_identity_workspace_foundation")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        assert not any(
            table_name.startswith("_0008d_")
            for table_name in inspect(connection).get_table_names()
        )
    get_settings.cache_clear()


def test_alembic_migration_upgrades_downgrades_and_has_no_schema_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "fresh" / "nested" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()

    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0003_node_secrets")

    graph_id = UUID("00000000-0000-0000-0000-000000000401")
    document: dict[str, object] = {
        "schema_version": 3,
        "nodes": [],
        "edges": [],
    }
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO saved_graphs "
                "(id, name, document, revision, created_at, updated_at) "
                "VALUES (:id, :name, :document, :revision, :created_at, :updated_at)"
            ),
            {
                "id": graph_id.hex,
                "name": "Existing graph",
                "document": json.dumps(document),
                "revision": 7,
                "created_at": "2026-07-14 08:00:00",
                "updated_at": "2026-07-16 09:30:00",
            },
        )

    command.upgrade(config, "0019_scoped_plugin_releases")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT graph_id, revision, name, document, created_at "
                    "FROM saved_graph_revisions"
                )
            )
            .mappings()
            .one()
        )
        assert row["graph_id"] == graph_id.hex
        assert row["revision"] == 7
        assert row["name"] == "Existing graph"
        assert json.loads(row["document"]) == {**document, "schema_version": 5}
        assert str(row["created_at"]) == "2026-07-16 09:30:00"

    command.downgrade(config, "0003_node_secrets")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        assert "saved_graph_revisions" not in inspect(connection).get_table_names()

    command.downgrade(config, "base")
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")

    command.upgrade(config, "head")
    assert database_path.exists()
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        assert set(inspect(connection).get_table_names()) == {
            "alembic_version",
            "artifact_objects",
            "collaborative_graph_heads",
            "graph_checkpoint_mappings",
            "graph_command_receipts",
            "graph_execution_nodes",
            "graph_executions",
            "graph_folders",
            "graph_organizations",
            "invocation_cache_entries",
            "materialized_node_outputs",
            "module_releases",
            "modules",
            "plugin_releases",
            "plugin_installations",
            "plugin_release_revocations",
            "plugin_release_selections",
            "node_secrets",
            "users",
            "oidc_identities",
            "oidc_login_transactions",
            "workspaces",
            "workspace_memberships",
            "workspace_invitations",
            "auth_sessions",
            "personal_access_tokens",
            "platform_access_tokens",
            "security_audit_events",
            "saved_graphs",
            "saved_graph_revisions",
            "staged_uploads",
            "user_graph_states",
            "templates",
        }
        assert connection.execute(
            text("SELECT COUNT(*) FROM workspaces WHERE slug = 'local'")
        ).scalar_one() == 0
    command.check(config)

    command.downgrade(config, "base")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        assert inspect(connection).get_table_names() == ["alembic_version"]

    command.upgrade(config, "head")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert set(inspect(connection).get_table_names()) == {
            "alembic_version",
            "artifact_objects",
            "collaborative_graph_heads",
            "graph_checkpoint_mappings",
            "graph_command_receipts",
            "graph_execution_nodes",
            "graph_executions",
            "graph_folders",
            "graph_organizations",
            "invocation_cache_entries",
            "materialized_node_outputs",
            "module_releases",
            "modules",
            "plugin_releases",
            "plugin_installations",
            "plugin_release_revocations",
            "plugin_release_selections",
            "node_secrets",
            "users",
            "oidc_identities",
            "oidc_login_transactions",
            "workspaces",
            "workspace_memberships",
            "workspace_invitations",
            "auth_sessions",
            "personal_access_tokens",
            "platform_access_tokens",
            "security_audit_events",
            "saved_graphs",
            "saved_graph_revisions",
            "staged_uploads",
            "user_graph_states",
            "templates",
        }
        assert connection.execute(
            text("SELECT COUNT(*) FROM workspaces WHERE slug = 'local'")
        ).scalar_one() == 0

    get_settings.cache_clear()


def test_identity_migration_creates_sealed_local_workspace_and_audit_indexes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "identity" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")

    command.upgrade(config, "0007_identity_workspace_foundation")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        local = (
            connection.execute(
                text(
                    "SELECT slug, kind, personal_owner_user_id "
                    "FROM workspaces WHERE slug = 'local'"
                )
            )
            .mappings()
            .one()
        )
        assert local == {
            "slug": "local",
            "kind": "shared",
            "personal_owner_user_id": None,
        }
        assert connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 0
        workspaces_ddl = connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'workspaces'"
            )
        ).scalar_one()
        assert "GLOB" not in workspaces_ddl.upper()
        assert "lower(trim(slug))" in workspaces_ddl
        indexes = {
            row[1]
            for row in connection.execute(
                text("PRAGMA index_list('security_audit_events')")
            )
        }
        assert indexes >= {
            "ix_security_audit_events_workspace_occurred_at",
            "ix_security_audit_events_actor_occurred_at",
            "ix_security_audit_events_operation_occurred_at",
            "ix_security_audit_events_retention",
        }
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO workspaces "
                    "(id, slug, name, kind, personal_owner_user_id, "
                    "created_at, updated_at) VALUES "
                    "(:id, :slug, :name, :kind, NULL, :created_at, :updated_at)"
                ),
                {
                    "id": "00000000000000000000000000000008",
                    "slug": "Not-Normalized",
                    "name": "Invalid",
                    "kind": "shared",
                    "created_at": "2026-08-07 00:00:00",
                    "updated_at": "2026-08-07 00:00:00",
                },
            )

    get_settings.cache_clear()


def test_remove_local_workspace_renames_owned_tenant_and_preserves_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "remove-owned-local" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0021_plugin_release_revocations")

    local_id = UUID("00000000-0000-0000-0000-000000000007").hex
    owner_id = UUID("00000000-0000-0000-0000-000000002201").hex
    folder_id = UUID("00000000-0000-0000-0000-000000002202").hex
    timestamp = "2026-08-26 08:00:00"
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, display_name, active, created_at, updated_at) "
                "VALUES (:id, 'owner@example.test', 'Owner', 1, :now, :now)"
            ),
            {"id": owner_id, "now": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO workspace_memberships "
                "(workspace_id, user_id, role, authorization_version, revoked_at, "
                "created_at, updated_at) "
                "VALUES (:workspace_id, :user_id, 'owner', 1, NULL, :now, :now)"
            ),
            {"workspace_id": local_id, "user_id": owner_id, "now": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO graph_folders "
                "(id, workspace_id, name, created_at, updated_at) "
                "VALUES (:id, :workspace_id, 'Legacy', :now, :now)"
            ),
            {"id": folder_id, "workspace_id": local_id, "now": timestamp},
        )

    command.upgrade(config, "0025_platform_access_tokens")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        workspace = (
            connection.execute(
                text(
                    "SELECT slug, name, kind FROM workspaces WHERE id = :local_id"
                ),
                {"local_id": local_id},
            )
            .mappings()
            .one()
        )
        assert workspace == {
            "slug": "migrated-workspace",
            "name": "Migrated workspace",
            "kind": "shared",
        }
        assert connection.execute(
            text("SELECT workspace_id FROM graph_folders WHERE id = :folder_id"),
            {"folder_id": folder_id},
        ).scalar_one() == local_id
        assert "oidc_bootstrap_owner_mappings" not in inspect(
            connection
        ).get_table_names()

    command.downgrade(config, "0021_plugin_release_revocations")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        assert connection.execute(
            text("SELECT slug FROM workspaces WHERE id = :local_id"),
            {"local_id": local_id},
        ).scalar_one() == "local"
        assert "oidc_bootstrap_owner_mappings" in inspect(
            connection
        ).get_table_names()
    get_settings.cache_clear()


def test_remove_local_workspace_refuses_unowned_tenant_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "remove-unowned-local" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0021_plugin_release_revocations")

    local_id = UUID("00000000-0000-0000-0000-000000000007").hex
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO graph_folders "
                "(id, workspace_id, name, created_at, updated_at) "
                "VALUES (:id, :workspace_id, 'Unowned', :now, :now)"
            ),
            {
                "id": UUID("00000000-0000-0000-0000-000000002203").hex,
                "workspace_id": local_id,
                "now": "2026-08-26 08:00:00",
            },
        )

    with pytest.raises(
        RuntimeError,
        match=r"unowned local workspace containing tenant data \(graph_folders=1\)",
    ):
        command.upgrade(config, "head")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        assert connection.execute(
            text("SELECT slug FROM workspaces WHERE id = :local_id"),
            {"local_id": local_id},
        ).scalar_one() == "local"
        assert "oidc_bootstrap_owner_mappings" in inspect(
            connection
        ).get_table_names()
    get_settings.cache_clear()


def test_saved_graph_revision_migration_backfills_the_current_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "backfill" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()

    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0003_node_secrets")

    graph_id = UUID("00000000-0000-0000-0000-000000000401")
    document: dict[str, object] = {
        "schema_version": 3,
        "nodes": [],
        "edges": [],
    }
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO saved_graphs "
                "(id, name, document, revision, created_at, updated_at) "
                "VALUES (:id, :name, :document, :revision, :created_at, :updated_at)"
            ),
            {
                "id": graph_id.hex,
                "name": "Existing graph",
                "document": json.dumps(document),
                "revision": 7,
                "created_at": "2026-07-14 08:00:00",
                "updated_at": "2026-07-16 09:30:00",
            },
        )

    command.upgrade(config, "0019_scoped_plugin_releases")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT graph_id, revision, name, document, created_at "
                    "FROM saved_graph_revisions"
                )
            )
            .mappings()
            .one()
        )
        assert row["graph_id"] == graph_id.hex
        assert row["revision"] == 7
        assert row["name"] == "Existing graph"
        assert json.loads(row["document"]) == {**document, "schema_version": 5}
        assert str(row["created_at"]) == "2026-07-16 09:30:00"
        head = (
            connection.execute(
                text(
                    "SELECT graph_id, collaboration_sequence, checkpoint_sequence, "
                    "checkpoint_revision, name "
                    "FROM collaborative_graph_heads"
                )
            )
            .mappings()
            .one()
        )
        assert head["graph_id"] == graph_id.hex
        assert head["collaboration_sequence"] == 0
        assert head["checkpoint_sequence"] == 0
        assert head["checkpoint_revision"] == 7
        assert head["name"] == "Existing graph"

    command.downgrade(config, "0003_node_secrets")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        assert "saved_graph_revisions" not in inspect(connection).get_table_names()

    get_settings.cache_clear()


def test_collaboration_head_migration_backfills_exactly_one_sequence_zero_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "collab-heads" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0008_tenant_existing_resources")

    workspace_id = UUID("00000000-0000-0000-0000-000000000007")
    graph_a = UUID("00000000-0000-0000-0000-000000000901")
    graph_b = UUID("00000000-0000-0000-0000-000000000902")
    document: dict[str, object] = {
        "schema_version": 3,
        "nodes": [],
        "edges": [],
    }
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        for graph_id, name, revision in (
            (graph_a, "Graph A", 2),
            (graph_b, "Graph B", 5),
        ):
            connection.execute(
                text(
                    "INSERT INTO saved_graphs "
                    "(workspace_id, id, name, document, revision, created_at, updated_at) "
                    "VALUES ("
                    ":workspace_id, :id, :name, :document, :revision, "
                    ":created_at, :updated_at"
                    ")"
                ),
                {
                    "workspace_id": workspace_id.hex,
                    "id": graph_id.hex,
                    "name": name,
                    "document": json.dumps(document),
                    "revision": revision,
                    "created_at": "2026-08-01 10:00:00",
                    "updated_at": "2026-08-01 11:00:00",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO saved_graph_revisions "
                    "(workspace_id, graph_id, revision, name, document, created_at) "
                    "VALUES ("
                    ":workspace_id, :graph_id, :revision, :name, :document, :created_at"
                    ")"
                ),
                {
                    "workspace_id": workspace_id.hex,
                    "graph_id": graph_id.hex,
                    "revision": revision,
                    "name": name,
                    "document": json.dumps(document),
                    "created_at": "2026-08-01 11:00:00",
                },
            )

    command.upgrade(config, "0009_collaborative_graph_heads")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        heads = (
            connection.execute(
                text(
                    "SELECT workspace_id, graph_id, collaboration_sequence, "
                    "checkpoint_sequence, checkpoint_revision, name "
                    "FROM collaborative_graph_heads "
                    "ORDER BY graph_id"
                )
            )
            .mappings()
            .all()
        )
        assert len(heads) == 2
        assert [head["graph_id"] for head in heads] == [graph_a.hex, graph_b.hex]
        for head, expected_revision, expected_name in (
            (heads[0], 2, "Graph A"),
            (heads[1], 5, "Graph B"),
        ):
            assert head["workspace_id"] == workspace_id.hex
            assert head["collaboration_sequence"] == 0
            assert head["checkpoint_sequence"] == 0
            assert head["checkpoint_revision"] == expected_revision
            assert head["name"] == expected_name
        orphan_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM saved_graphs g "
                "LEFT JOIN collaborative_graph_heads h "
                "ON h.workspace_id = g.workspace_id AND h.graph_id = g.id "
                "WHERE h.graph_id IS NULL"
            )
        ).scalar_one()
        assert orphan_count == 0
        duplicate_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM ("
                "SELECT workspace_id, graph_id, COUNT(*) AS n "
                "FROM collaborative_graph_heads "
                "GROUP BY workspace_id, graph_id "
                "HAVING n > 1"
                ")"
            )
        ).scalar_one()
        assert duplicate_count == 0

    get_settings.cache_clear()


def test_tenant_migration_backfills_all_0006_resources_and_checks_composite_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "tenant-backfill" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0006_execution_history")

    graph_id = UUID("00000000-0000-0000-0000-000000000801")
    execution_id = UUID("00000000-0000-0000-0000-000000000802")
    artifact_id = UUID("00000000-0000-0000-0000-000000000803")
    generation_id = UUID("00000000-0000-0000-0000-000000000804")
    workflow_run_id = UUID("00000000-0000-0000-0000-000000000805")
    timestamp = "2026-08-07 08:00:00"
    document = json.dumps({"schema_version": 3, "nodes": [], "edges": []})
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO saved_graphs "
                "(id, name, document, revision, created_at, updated_at) "
                "VALUES (:id, 'Migrated graph', :document, 1, :created_at, :updated_at)"
            ),
            {
                "id": graph_id.hex,
                "document": document,
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO saved_graph_revisions "
                "(graph_id, revision, name, document, created_at) "
                "VALUES (:graph_id, 1, 'Migrated graph', :document, :created_at)"
            ),
            {"graph_id": graph_id.hex, "document": document, "created_at": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO artifact_objects "
                "(id, artifact_type, schema_version, content_type, storage_backend, "
                "metadata) VALUES (:id, 'test.artifact', 1, 'application/json', "
                "'inline', '{}')"
            ),
            {"id": artifact_id.hex},
        )
        connection.execute(
            text(
                "INSERT INTO invocation_cache_entries "
                "(key_sha256, generation, outputs, created_at) "
                "VALUES (:key, :generation, '[]', :created_at)"
            ),
            {
                "key": "a" * 64,
                "generation": generation_id.hex,
                "created_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO materialized_node_outputs "
                "(graph_id, graph_revision, node_id, workflow_run_id, outputs, "
                "materialized_at) VALUES (:graph_id, 1, 'node', :workflow_run_id, "
                "'[]', :created_at)"
            ),
            {
                "graph_id": graph_id.hex,
                "workflow_run_id": workflow_run_id.hex,
                "created_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO node_secrets "
                "(graph_id, node_id, name, operator_id, operator_version, key_id, "
                "dependency_sha256, nonce, ciphertext, created_at, updated_at) "
                "VALUES (:graph_id, 'node', 'secret', 'test.operator', 1, 'key', "
                ":dependency, :nonce, :ciphertext, :created_at, :updated_at)"
            ),
            {
                "graph_id": graph_id.hex,
                "dependency": "b" * 64,
                "nonce": b"0" * 12,
                "ciphertext": b"ciphertext",
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO graph_executions "
                "(execution_id, graph_id, graph_revision, status, scope, created_at) "
                "VALUES (:execution_id, :graph_id, 1, 'succeeded', 'all', :created_at)"
            ),
            {
                "execution_id": execution_id.hex,
                "graph_id": graph_id.hex,
                "created_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO graph_execution_requested_nodes "
                "(execution_id, node_id, position) VALUES (:execution_id, 'node', 0)"
            ),
            {"execution_id": execution_id.hex},
        )
        connection.execute(
            text(
                "INSERT INTO graph_execution_node_results "
                "(execution_id, node_id, position, status, outputs, artifact_count, "
                "completed_at) VALUES (:execution_id, 'node', 0, 'succeeded', '[]', "
                "0, :completed_at)"
            ),
            {"execution_id": execution_id.hex, "completed_at": timestamp},
        )

    command.upgrade(config, "0013_thin_execution_schema")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        for table_name in (
            "saved_graphs",
            "saved_graph_revisions",
            "artifact_objects",
            "invocation_cache_entries",
            "materialized_node_outputs",
            "node_secrets",
            "graph_executions",
            "graph_execution_nodes",
        ):
            assert (
                connection.execute(
                    text(
                        f"SELECT COUNT(*) FROM {table_name} "
                        "WHERE workspace_id = '00000000000000000000000000000007'"
                    )
                ).scalar_one()
                == 1
            )
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        connection.execute(
            text(
                "INSERT INTO workspaces "
                "(id, slug, name, kind, created_at, updated_at) VALUES "
                "(:id, 'other', 'Other', 'shared', :created_at, :created_at)"
            ),
            {"id": "00000000000000000000000000000009", "created_at": timestamp},
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO saved_graph_revisions "
                    "(workspace_id, graph_id, revision, name, document, created_at) "
                    "VALUES (:workspace_id, :graph_id, 2, 'Foreign', :document, "
                    ":created_at)"
                ),
                {
                    "workspace_id": "00000000000000000000000000000009",
                    "graph_id": graph_id.hex,
                    "document": document,
                    "created_at": timestamp,
                },
            )
        connection.execute(
            text("DELETE FROM workspaces WHERE id = '00000000000000000000000000000009'")
        )

    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text("UPDATE node_secrets SET aad_version = 2 WHERE graph_id = :graph_id"),
            {"graph_id": graph_id.hex},
        )
    with pytest.raises(RuntimeError, match="AAD version 2"):
        command.downgrade(config, "0006_execution_history")
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text("UPDATE node_secrets SET aad_version = 1 WHERE graph_id = :graph_id"),
            {"graph_id": graph_id.hex},
        )

    command.downgrade(config, "0006_execution_history")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        materialized_foreign_keys = inspect(connection).get_foreign_keys(
            "materialized_node_outputs"
        )
        assert materialized_foreign_keys == [
            {
                "name": "fk_materialized_node_outputs_graph_id_saved_graphs",
                "constrained_columns": ["graph_id"],
                "referred_schema": None,
                "referred_table": "saved_graphs",
                "referred_columns": ["id"],
                "options": {"ondelete": "CASCADE"},
            }
        ]

    command.downgrade(config, "0004_saved_graph_revisions")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        assert "materialized_node_outputs" in inspect(connection).get_table_names()

    get_settings.cache_clear()


def test_direct_0007_downgrade_refuses_identity_data_but_allows_empty_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "identity-guard" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0007_identity_workspace_foundation")
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, active, created_at, updated_at) VALUES "
                "('00000000000000000000000000000008', 1, :created_at, :created_at)"
            ),
            {"created_at": "2026-08-07 08:00:00"},
        )
    with pytest.raises(RuntimeError, match="identity/security data"):
        command.downgrade(config, "0006_execution_history")

    empty_database_path = tmp_path / "identity-empty" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{empty_database_path}",
    )
    get_settings.cache_clear()
    empty_config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(empty_config, "0007_identity_workspace_foundation")
    command.downgrade(empty_config, "0006_execution_history")
    get_settings.cache_clear()


def _seed_execution_graph(database_path: Path) -> tuple[str, str]:
    """Create one workspace/graph/revision at 0012 plus execution fixtures."""
    workspace_id = UUID("00000000-0000-0000-0000-000000000007")
    graph_id = UUID("00000000-0000-0000-0000-000000000a01")
    document = json.dumps({"schema_version": 3, "nodes": [], "edges": []})
    timestamp = "2026-08-20 08:00:00"
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO saved_graphs "
                "(workspace_id, id, name, document, revision, created_at, updated_at) "
                "VALUES (:workspace_id, :id, 'Merged', :document, 1, :ts, :ts)"
            ),
            {
                "workspace_id": workspace_id.hex,
                "id": graph_id.hex,
                "document": document,
                "ts": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO saved_graph_revisions "
                "(workspace_id, graph_id, revision, name, document, created_at) "
                "VALUES (:workspace_id, :id, 1, 'Merged', :document, :ts)"
            ),
            {
                "workspace_id": workspace_id.hex,
                "id": graph_id.hex,
                "document": document,
                "ts": timestamp,
            },
        )
    return workspace_id.hex, graph_id.hex


def test_0013_merges_node_tables_preserves_data_and_reconstructs_on_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "merge" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0012_template_library")

    workspace_hex, graph_hex = _seed_execution_graph(database_path)
    execution_hex = UUID("00000000-0000-0000-0000-000000000a02").hex
    active_hex = UUID("00000000-0000-0000-0000-000000000a04").hex
    timestamp = "2026-08-20 09:00:00"
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO graph_executions "
                "(workspace_id, execution_id, graph_id, graph_revision, status, "
                "scope, created_at) VALUES (:ws, :e, :g, 1, 'succeeded', 'all', :ts)"
            ),
            {"ws": workspace_hex, "e": execution_hex, "g": graph_hex, "ts": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO graph_executions "
                "(workspace_id, execution_id, graph_id, graph_revision, status, "
                "scope, created_at) VALUES (:ws, :e, :g, 1, 'running', 'all', :ts)"
            ),
            {"ws": workspace_hex, "e": active_hex, "g": graph_hex, "ts": timestamp},
        )
        # Requested nodes: two for the finished execution, one for the active.
        for execution, node, position in (
            (execution_hex, "alpha", 0),
            (execution_hex, "beta", 1),
            (active_hex, "solo", 0),
        ):
            connection.execute(
                text(
                    "INSERT INTO graph_execution_requested_nodes "
                    "(workspace_id, execution_id, node_id, position) "
                    "VALUES (:ws, :e, :n, :p)"
                ),
                {"ws": workspace_hex, "e": execution, "n": node, "p": position},
            )
        # Terminal results recorded out of request order (result position 0 is
        # beta), preserving compiled-plan visit order semantics.
        connection.execute(
            text(
                "INSERT INTO graph_execution_node_results "
                "(workspace_id, execution_id, node_id, position, status, outputs, "
                "artifact_count, error, completed_at) VALUES "
                "(:ws, :e, 'beta', 0, 'succeeded', '[{\"kind\":\"ref\"}]', 2, NULL, :ts)"
            ),
            {"ws": workspace_hex, "e": execution_hex, "ts": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO graph_execution_node_results "
                "(workspace_id, execution_id, node_id, position, status, outputs, "
                "artifact_count, error, completed_at) VALUES "
                "(:ws, :e, 'alpha', 1, 'failed', '[]', 0, 'boom', :ts)"
            ),
            {"ws": workspace_hex, "e": execution_hex, "ts": timestamp},
        )

    command.upgrade(config, "0013_thin_execution_schema")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        rows = (
            connection.execute(
                text(
                    "SELECT execution_id, node_id, position, result_status, "
                    "result_position, artifact_count, error "
                    "FROM graph_execution_nodes "
                    "ORDER BY execution_id, position"
                )
            )
            .mappings()
            .all()
        )
        assert [(row["node_id"], row["position"]) for row in rows] == [
            ("alpha", 0),
            ("beta", 1),
            ("solo", 0),
        ]
        by_node = {row["node_id"]: row for row in rows}
        assert by_node["alpha"]["result_status"] == "failed"
        assert by_node["alpha"]["result_position"] == 1
        assert by_node["alpha"]["error"] == "boom"
        assert by_node["beta"]["result_status"] == "succeeded"
        assert by_node["beta"]["result_position"] == 0
        assert by_node["beta"]["artifact_count"] == 2
        assert by_node["solo"]["result_status"] is None

        # One active execution per workspace graph is enforced.
        index_rows = connection.execute(
            text("PRAGMA index_list('graph_executions')")
        ).fetchall()
        index_names = {row[1] for row in index_rows}
        assert "uq_graph_executions_one_active_per_graph" in index_names
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO graph_executions "
                    "(workspace_id, execution_id, graph_id, graph_revision, status, "
                    "scope, created_at) VALUES (:ws, :e, :g, 1, 'queued', 'all', :ts)"
                ),
                {
                    "ws": workspace_hex,
                    "e": UUID("00000000-0000-0000-0000-000000000a05").hex,
                    "g": graph_hex,
                    "ts": timestamp,
                },
            )

    command.downgrade(config, "0012_template_library")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        requested = (
            connection.execute(
                text(
                    "SELECT execution_id, node_id, position "
                    "FROM graph_execution_requested_nodes "
                    "ORDER BY execution_id, position"
                )
            )
            .mappings()
            .all()
        )
        assert [(row["node_id"], row["position"]) for row in requested] == [
            ("alpha", 0),
            ("beta", 1),
            ("solo", 0),
        ]
        results = (
            connection.execute(
                text(
                    "SELECT node_id, position, status, artifact_count "
                    "FROM graph_execution_node_results "
                    "ORDER BY execution_id, position"
                )
            )
            .mappings()
            .all()
        )
        assert [
            (row["node_id"], row["position"], row["status"]) for row in results
        ] == [
            ("beta", 0, "succeeded"),
            ("alpha", 1, "failed"),
        ]
        slot = (
            connection.execute(text("SELECT * FROM graph_active_execution_slots"))
            .mappings()
            .one()
        )
        assert slot["execution_id"] == active_hex
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM graph_command_journal")
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM graph_execution_idempotency")
            ).scalar_one()
            == 0
        )

    get_settings.cache_clear()


def test_0013_upgrade_rejects_duplicate_active_executions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "duplicate-active" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0012_template_library")
    workspace_hex, graph_hex = _seed_execution_graph(database_path)
    timestamp = "2026-08-20 10:00:00"
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        for suffix in ("0b01", "0b02"):
            connection.execute(
                text(
                    "INSERT INTO graph_executions "
                    "(workspace_id, execution_id, graph_id, graph_revision, status, "
                    "scope, created_at) VALUES (:ws, :e, :g, 1, 'running', 'all', :ts)"
                ),
                {
                    "ws": workspace_hex,
                    "e": UUID(f"00000000-0000-0000-0000-00000000{suffix}").hex,
                    "g": graph_hex,
                    "ts": timestamp,
                },
            )

    with pytest.raises(RuntimeError, match="multiple queued/running/cancelling"):
        command.upgrade(config, "head")
    get_settings.cache_clear()


def test_0013_upgrade_rejects_results_without_requested_nodes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "orphan-result" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0012_template_library")
    workspace_hex, graph_hex = _seed_execution_graph(database_path)
    execution_hex = UUID("00000000-0000-0000-0000-000000000c01").hex
    timestamp = "2026-08-20 11:00:00"
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO graph_executions "
                "(workspace_id, execution_id, graph_id, graph_revision, status, "
                "scope, created_at) VALUES (:ws, :e, :g, 1, 'succeeded', 'all', :ts)"
            ),
            {"ws": workspace_hex, "e": execution_hex, "g": graph_hex, "ts": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO graph_execution_node_results "
                "(workspace_id, execution_id, node_id, position, status, outputs, "
                "artifact_count, error, completed_at) VALUES "
                "(:ws, :e, 'ghost', 0, 'succeeded', '[]', 0, NULL, :ts)"
            ),
            {"ws": workspace_hex, "e": execution_hex, "ts": timestamp},
        )

    with pytest.raises(RuntimeError, match="without a matching requested node"):
        command.upgrade(config, "head")
    get_settings.cache_clear()


def _seed_0019_workspace_release_and_references(
    database_path: Path,
) -> tuple[str, str, str, str, str]:
    workspace_hex = UUID("00000000-0000-0000-0000-000000000007").hex
    graph_hex = UUID("00000000-0000-0000-0000-000000001901").hex
    execution_hex = UUID("00000000-0000-0000-0000-000000001902").hex
    artifact_hex = UUID("00000000-0000-0000-0000-000000001903").hex
    template_hex = UUID("00000000-0000-0000-0000-000000001904").hex
    room_epoch_hex = UUID("00000000-0000-0000-0000-000000001905").hex
    timestamp = "2026-08-24 10:00:00"
    pin = {"slug": "notes", "revision": 3}
    document = {
        "schema_version": 4,
        "nodes": [
            {
                "id": "notes",
                "operator_id": "notes.echo",
                "operator_version": 1,
                "config": {},
                "position": {"x": 0, "y": 0},
                "plugin_release_pin": pin,
            }
        ],
        "edges": [],
    }
    submitted_request = {
        "schema_version": 4,
        "nodes": [
            {
                "id": "notes",
                "operator_id": "notes.echo",
                "operator_version": 1,
                "plugin_release": pin,
            }
        ],
        "edges": [],
    }
    provenance = {
        "plugin_release": {
            **pin,
            "source_digest": "b" * 64,
            "contract_digest": "d" * 64,
        }
    }

    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO plugin_releases ("
                "workspace_id, slug, revision, catalog, contract_digest, "
                "capabilities, capability_digest, protocol_digest, profile_digest, "
                "source_object_key, source_digest, lock_digest, runtime_profile, "
                "runtime_image_digest, runtime_artifact, descriptor_digest, "
                "published_by_user_id, published_at) VALUES ("
                ":workspace_id, 'notes', 3, :catalog, :contract_digest, "
                ":capabilities, :capability_digest, :protocol_digest, "
                ":profile_digest, 'plugin-releases/notes/source.tar.gz', "
                ":source_digest, :lock_digest, 'python-uv', NULL, NULL, "
                ":descriptor_digest, NULL, :published_at)"
            ),
            {
                "workspace_id": workspace_hex,
                "catalog": json.dumps(
                    {
                        "slug": "notes",
                        "title": "Notes",
                        "artifact_types": [],
                        "nodes": [],
                    }
                ),
                "contract_digest": "d" * 64,
                "capabilities": json.dumps({"capabilities": []}),
                "capability_digest": "a" * 64,
                "protocol_digest": "e" * 64,
                "profile_digest": "f" * 64,
                "source_digest": "b" * 64,
                "lock_digest": "c" * 64,
                "descriptor_digest": "1" * 64,
                "published_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO saved_graphs "
                "(workspace_id, id, name, document, revision, created_at, updated_at) "
                "VALUES (:workspace_id, :graph_id, 'Scoped migration', :document, "
                "7, :timestamp, :timestamp)"
            ),
            {
                "workspace_id": workspace_hex,
                "graph_id": graph_hex,
                "document": json.dumps(document),
                "timestamp": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO saved_graph_revisions "
                "(workspace_id, graph_id, revision, name, document, created_at) "
                "VALUES (:workspace_id, :graph_id, 7, 'Scoped migration', "
                ":document, :timestamp)"
            ),
            {
                "workspace_id": workspace_hex,
                "graph_id": graph_hex,
                "document": json.dumps(document),
                "timestamp": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO collaborative_graph_heads "
                "(workspace_id, graph_id, room_epoch, collaboration_sequence, "
                "checkpoint_sequence, checkpoint_revision, name, document, "
                "updated_at) VALUES (:workspace_id, :graph_id, :room_epoch, 0, "
                "0, 7, 'Scoped migration', :document, :timestamp)"
            ),
            {
                "workspace_id": workspace_hex,
                "graph_id": graph_hex,
                "room_epoch": room_epoch_hex,
                "document": json.dumps(document),
                "timestamp": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO templates "
                "(id, workspace_id, source_graph_id, source_revision, "
                "source_graph_name, snapshot_document, name, description, state, "
                "created_by_user_id, created_at, updated_at) VALUES ("
                ":template_id, :workspace_id, :graph_id, 7, 'Scoped migration', "
                ":document, 'Scoped template', NULL, 'active', NULL, :timestamp, "
                ":timestamp)"
            ),
            {
                "template_id": template_hex,
                "workspace_id": workspace_hex,
                "graph_id": graph_hex,
                "document": json.dumps(document),
                "timestamp": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO graph_executions "
                "(workspace_id, execution_id, graph_id, graph_revision, status, "
                "scope, submitted_request, created_at) VALUES ("
                ":workspace_id, :execution_id, :graph_id, 7, 'succeeded', 'all', "
                ":submitted_request, :timestamp)"
            ),
            {
                "workspace_id": workspace_hex,
                "execution_id": execution_hex,
                "graph_id": graph_hex,
                "submitted_request": json.dumps(submitted_request),
                "timestamp": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO artifact_objects "
                "(id, workspace_id, artifact_type, schema_version, content_type, "
                "storage_backend, metadata) VALUES (:artifact_id, :workspace_id, "
                "'test.scoped', 1, 'application/json', 'inline', :metadata)"
            ),
            {
                "artifact_id": artifact_hex,
                "workspace_id": workspace_hex,
                "metadata": json.dumps(provenance),
            },
        )
        connection.execute(
            text(
                "INSERT INTO graph_execution_nodes "
                "(workspace_id, execution_id, node_id, position, result_status, "
                "result_position, outputs, artifact_count, diagnostics, "
                "completed_at) VALUES (:workspace_id, :execution_id, 'notes', 0, "
                "'succeeded', 0, '[]', 0, :diagnostics, :timestamp)"
            ),
            {
                "workspace_id": workspace_hex,
                "execution_id": execution_hex,
                "diagnostics": json.dumps(provenance),
                "timestamp": timestamp,
            },
        )
    return workspace_hex, graph_hex, execution_hex, artifact_hex, timestamp


def _assert_0019_timestamps_unchanged(
    connection: sa.Connection,
    graph_hex: str,
    timestamp: str,
) -> None:
    timestamp_queries = (
        (
            "SELECT created_at, updated_at FROM saved_graphs WHERE id = :graph_id",
            (timestamp, timestamp),
        ),
        (
            "SELECT created_at FROM saved_graph_revisions WHERE graph_id = :graph_id",
            (timestamp,),
        ),
        (
            "SELECT updated_at FROM collaborative_graph_heads "
            "WHERE graph_id = :graph_id",
            (timestamp,),
        ),
        (
            "SELECT created_at, updated_at FROM templates "
            "WHERE source_graph_id = :graph_id",
            (timestamp, timestamp),
        ),
    )
    for statement, expected in timestamp_queries:
        assert (
            connection.execute(
                text(statement),
                {"graph_id": graph_hex},
            ).one()
            == expected
        )


def test_0019_scopes_releases_and_normalizes_retained_references_without_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "scoped-releases" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0018_local_execution_queue")
    workspace_hex, graph_hex, execution_hex, artifact_hex, timestamp = (
        _seed_0019_workspace_release_and_references(database_path)
    )

    command.upgrade(config, "0019_scoped_plugin_releases")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        release = (
            connection.execute(
                text(
                    "SELECT id, scope, workspace_id, slug, revision, source_digest, "
                    "descriptor_digest, execution_policy, distribution "
                    "FROM plugin_releases"
                )
            )
            .mappings()
            .one()
        )
        assert release["id"] is not None
        assert release["scope"] == "workspace"
        assert release["workspace_id"] == workspace_hex
        assert release["slug"] == "notes"
        assert release["revision"] == 3
        assert release["source_digest"] == "b" * 64
        assert release["descriptor_digest"] == "1" * 64
        assert release["execution_policy"] == "isolated-only"
        assert release["distribution"] is None

        indexes = {
            row[1]
            for row in connection.execute(text("PRAGMA index_list('plugin_releases')"))
        }
        assert indexes >= {
            "uq_plugin_releases_system_slug_revision",
            "uq_plugin_releases_workspace_slug_revision",
            "uq_plugin_releases_system_slug_descriptor",
            "uq_plugin_releases_workspace_slug_descriptor",
        }
        graph_row = (
            connection.execute(
                text(
                    "SELECT revision, created_at, updated_at FROM saved_graphs "
                    "WHERE id = :graph_id"
                ),
                {"graph_id": graph_hex},
            )
            .mappings()
            .one()
        )
        assert graph_row == {
            "revision": 7,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        _assert_0019_timestamps_unchanged(connection, graph_hex, timestamp)

        document_columns = (
            ("saved_graphs", "document"),
            ("saved_graph_revisions", "document"),
            ("collaborative_graph_heads", "document"),
            ("templates", "snapshot_document"),
        )
        for table_name, column_name in document_columns:
            stored = connection.execute(
                text(f"SELECT {column_name} FROM {table_name}")
            ).scalar_one()
            document = json.loads(stored)
            assert document["schema_version"] == 5
            assert document["edges"] == []
            node = document["nodes"][0]
            assert node["id"] == "notes"
            assert node["operator_id"] == "notes.echo"
            assert node["operator_version"] == 1
            assert node["config"] == {}
            assert node["position"] == {"x": 0, "y": 0}
            pin = node["plugin_release_pin"]
            assert pin == {"scope": "workspace", "slug": "notes", "revision": 3}

        submitted = connection.execute(
            text(
                "SELECT submitted_request FROM graph_executions "
                "WHERE execution_id = :execution_id"
            ),
            {"execution_id": execution_hex},
        ).scalar_one()
        submitted_request = json.loads(submitted)
        assert submitted_request["schema_version"] == 4
        assert submitted_request["nodes"][0]["plugin_release"] == {
            "scope": "workspace",
            "slug": "notes",
            "revision": 3,
        }
        metadata = connection.execute(
            text("SELECT metadata FROM artifact_objects WHERE id = :artifact_id"),
            {"artifact_id": artifact_hex},
        ).scalar_one()
        diagnostics = connection.execute(
            text(
                "SELECT diagnostics FROM graph_execution_nodes "
                "WHERE execution_id = :execution_id"
            ),
            {"execution_id": execution_hex},
        ).scalar_one()
        for retained in (metadata, diagnostics):
            assert json.loads(retained)["plugin_release"]["scope"] == "workspace"

    command.downgrade(config, "0018_local_execution_queue")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("plugin_releases")
        }
        assert {"id", "scope", "execution_policy", "distribution"}.isdisjoint(columns)
        release = connection.execute(
            text(
                "SELECT workspace_id, slug, revision, source_digest, "
                "descriptor_digest FROM plugin_releases"
            )
        ).one()
        assert release == (workspace_hex, "notes", 3, "b" * 64, "1" * 64)
        saved_document = connection.execute(
            text("SELECT document FROM saved_graphs WHERE id = :graph_id"),
            {"graph_id": graph_hex},
        ).scalar_one()
        downgraded_document = json.loads(saved_document)
        assert downgraded_document["schema_version"] == 4
        assert downgraded_document["nodes"][0]["plugin_release_pin"] == {
            "slug": "notes",
            "revision": 3,
        }
        submitted = connection.execute(
            text(
                "SELECT submitted_request FROM graph_executions "
                "WHERE execution_id = :execution_id"
            ),
            {"execution_id": execution_hex},
        ).scalar_one()
        downgraded_request = json.loads(submitted)
        assert downgraded_request["schema_version"] == 4
        assert downgraded_request["nodes"][0]["plugin_release"] == {
            "slug": "notes",
            "revision": 3,
        }
        _assert_0019_timestamps_unchanged(connection, graph_hex, timestamp)
    get_settings.cache_clear()


def test_0019_downgrade_refuses_system_release_data_and_system_pins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "scoped-release-downgrade-guard" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0018_local_execution_queue")
    _, graph_hex, _, _, _ = _seed_0019_workspace_release_and_references(database_path)
    command.upgrade(config, "0019_scoped_plugin_releases")

    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO plugin_releases ("
                "id, scope, workspace_id, slug, revision, catalog, contract_digest, "
                "capabilities, capability_digest, protocol_digest, profile_digest, "
                "source_object_key, source_digest, lock_digest, runtime_profile, "
                "runtime_image_digest, runtime_artifact, descriptor_digest, "
                "execution_policy, distribution, published_by_user_id, published_at) "
                "SELECT :id, 'system', NULL, 'system-notes', 1, catalog, "
                "contract_digest, capabilities, capability_digest, protocol_digest, "
                "profile_digest, source_object_key, :source_digest, lock_digest, "
                "runtime_profile, runtime_image_digest, runtime_artifact, "
                ":descriptor_digest, 'host-eligible', 'bundled', NULL, published_at "
                "FROM plugin_releases WHERE scope = 'workspace' LIMIT 1"
            ),
            {
                "id": UUID("00000000-0000-0000-0000-000000001999").hex,
                "source_digest": "9" * 64,
                "descriptor_digest": "8" * 64,
            },
        )

    with pytest.raises(RuntimeError, match="System Plugin release data"):
        command.downgrade(config, "0018_local_execution_queue")

    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(text("DELETE FROM plugin_releases WHERE scope = 'system'"))
        stored = connection.execute(
            text("SELECT document FROM saved_graphs WHERE id = :graph_id"),
            {"graph_id": graph_hex},
        ).scalar_one()
        document = json.loads(stored)
        document["nodes"][0]["plugin_release_pin"]["scope"] = "system"
        connection.execute(
            text("UPDATE saved_graphs SET document = :document WHERE id = :graph_id"),
            {"document": json.dumps(document), "graph_id": graph_hex},
        )

    with pytest.raises(RuntimeError, match="System Plugin release pins or provenance"):
        command.downgrade(config, "0018_local_execution_queue")

    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        document["nodes"][0]["plugin_release_pin"]["scope"] = "workspace"
        connection.execute(
            text("UPDATE saved_graphs SET document = :document WHERE id = :graph_id"),
            {"document": json.dumps(document), "graph_id": graph_hex},
        )
    command.downgrade(config, "0018_local_execution_queue")
    get_settings.cache_clear()


def test_0020_backfills_exact_current_selection_without_mutating_releases_or_graphs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "plugin-release-selections" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0018_local_execution_queue")
    _, graph_hex, _, _, _ = _seed_0019_workspace_release_and_references(database_path)
    command.upgrade(config, "0019_scoped_plugin_releases")

    selected_release_hex = UUID("00000000-0000-0000-0000-000000002005").hex
    selected_timestamp = "2026-08-24 11:00:00"
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO plugin_releases ("
                "id, scope, workspace_id, slug, revision, catalog, contract_digest, "
                "capabilities, capability_digest, protocol_digest, profile_digest, "
                "source_object_key, source_digest, lock_digest, runtime_profile, "
                "runtime_image_digest, runtime_artifact, descriptor_digest, "
                "execution_policy, distribution, published_by_user_id, published_at) "
                "SELECT :id, scope, workspace_id, slug, 5, catalog, contract_digest, "
                "capabilities, capability_digest, protocol_digest, profile_digest, "
                "source_object_key, :source_digest, lock_digest, runtime_profile, "
                "runtime_image_digest, runtime_artifact, :descriptor_digest, "
                "execution_policy, distribution, published_by_user_id, :published_at "
                "FROM plugin_releases WHERE scope = 'workspace' AND slug = 'notes' "
                "LIMIT 1"
            ),
            {
                "id": selected_release_hex,
                "source_digest": "5" * 64,
                "descriptor_digest": "6" * 64,
                "published_at": selected_timestamp,
            },
        )
        release_snapshot = connection.execute(
            text(
                "SELECT id, scope, workspace_id, slug, revision, source_digest, "
                "descriptor_digest, published_at FROM plugin_releases ORDER BY id"
            )
        ).all()
        graph_snapshot = connection.execute(
            text(
                "SELECT revision, document, created_at, updated_at FROM saved_graphs "
                "WHERE id = :graph_id"
            ),
            {"graph_id": graph_hex},
        ).one()

    command.upgrade(config, "0020_plugin_release_selections")
    migration = importlib.import_module(
        "infra.db.migrations.versions.0020_plugin_release_selections"
    )
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        selection = (
            connection.execute(
                text(
                    "SELECT scope, workspace_id, slug, selected_release_id, "
                    "selected_revision, lifecycle, generation, updated_at, "
                    "updated_by_actor FROM plugin_release_selections"
                )
            )
            .mappings()
            .one()
        )
        assert selection["scope"] == "workspace"
        assert selection["workspace_id"] is not None
        assert selection["slug"] == "notes"
        assert selection["selected_release_id"] == selected_release_hex
        assert selection["selected_revision"] == 5
        assert selection["lifecycle"] == "published"
        assert selection["generation"] == 1
        assert str(selection["updated_at"]) == f"{selected_timestamp}.000000"
        assert selection["updated_by_actor"] == "migration:0020"

        migration._backfill_selections(connection)
        migration._backfill_selections(connection)
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM plugin_release_selections")
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                text(
                    "SELECT id, scope, workspace_id, slug, revision, source_digest, "
                    "descriptor_digest, published_at FROM plugin_releases ORDER BY id"
                )
            ).all()
            == release_snapshot
        )
        assert (
            connection.execute(
                text(
                    "SELECT revision, document, created_at, updated_at FROM saved_graphs "
                    "WHERE id = :graph_id"
                ),
                {"graph_id": graph_hex},
            ).one()
            == graph_snapshot
        )
        assert "published_by_platform_actor" in {
            column["name"]
            for column in inspect(connection).get_columns("plugin_releases")
        }
        indexes = {
            row[1]
            for row in connection.execute(
                text("PRAGMA index_list('plugin_release_selections')")
            )
        }
        assert indexes >= {
            "uq_plugin_release_selections_system_slug",
            "uq_plugin_release_selections_workspace_slug",
        }

    command.downgrade(config, "0019_scoped_plugin_releases")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        assert "plugin_release_selections" not in inspect(connection).get_table_names()
        assert "published_by_platform_actor" not in {
            column["name"]
            for column in inspect(connection).get_columns("plugin_releases")
        }
        assert (
            connection.execute(
                text(
                    "SELECT id, scope, workspace_id, slug, revision, source_digest, "
                    "descriptor_digest, published_at FROM plugin_releases ORDER BY id"
                )
            ).all()
            == release_snapshot
        )
        assert (
            connection.execute(
                text(
                    "SELECT revision, document, created_at, updated_at FROM saved_graphs "
                    "WHERE id = :graph_id"
                ),
                {"graph_id": graph_hex},
            ).one()
            == graph_snapshot
        )
    get_settings.cache_clear()


def test_0020_downgrade_refuses_to_drop_system_publisher_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "system-publisher-downgrade" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0018_local_execution_queue")
    _seed_0019_workspace_release_and_references(database_path)
    command.upgrade(config, "0020_plugin_release_selections")

    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO plugin_releases ("
                "id, scope, workspace_id, slug, revision, catalog, contract_digest, "
                "capabilities, capability_digest, protocol_digest, profile_digest, "
                "source_object_key, source_digest, lock_digest, runtime_profile, "
                "runtime_image_digest, runtime_artifact, descriptor_digest, "
                "execution_policy, distribution, published_by_user_id, "
                "published_by_platform_actor, published_at) "
                "SELECT :id, 'system', NULL, 'system-notes', 1, catalog, "
                "contract_digest, capabilities, capability_digest, protocol_digest, "
                "profile_digest, source_object_key, :source_digest, lock_digest, "
                "runtime_profile, runtime_image_digest, runtime_artifact, "
                ":descriptor_digest, 'host-eligible', 'bundled', NULL, "
                "'migration-test:system', published_at FROM plugin_releases "
                "WHERE scope = 'workspace' LIMIT 1"
            ),
            {
                "id": UUID("00000000-0000-0000-0000-000000002099").hex,
                "source_digest": "9" * 64,
                "descriptor_digest": "8" * 64,
            },
        )

    with pytest.raises(RuntimeError, match="publisher provenance"):
        command.downgrade(config, "0019_scoped_plugin_releases")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        assert "plugin_release_selections" in inspect(connection).get_table_names()
        assert (
            connection.execute(
                text(
                    "SELECT published_by_platform_actor FROM plugin_releases "
                    "WHERE scope = 'system'"
                )
            ).scalar_one()
            == "migration-test:system"
        )
    get_settings.cache_clear()


def _assert_0020_downgrade_refused_leaves_schema_unchanged(
    connection: Connection,
    selection_snapshot: Sequence[Row[Any]],
    release_snapshot: Sequence[Row[Any]],
) -> None:
    assert "plugin_release_selections" in inspect(connection).get_table_names()
    assert (
        connection.execute(
            text(
                "SELECT scope, workspace_id, slug, selected_release_id, "
                "selected_revision, lifecycle, generation, updated_at, "
                "updated_by_actor FROM plugin_release_selections "
                "ORDER BY slug"
            )
        ).all()
        == selection_snapshot
    )
    indexes = {
        str(row[1])
        for row in connection.execute(
            text("PRAGMA index_list('plugin_release_selections')")
        )
    }
    assert indexes >= {
        "uq_plugin_release_selections_system_slug",
        "uq_plugin_release_selections_workspace_slug",
    }
    table_sql = connection.execute(
        text(
            "SELECT sql FROM sqlite_master "
            "WHERE name = 'plugin_release_selections'"
        )
    ).scalar_one()
    assert (
        "ck_plugin_release_selections_plugin_release_selection_lifecycle" in table_sql
    )
    assert "published_by_platform_actor" in {
        column["name"] for column in inspect(connection).get_columns("plugin_releases")
    }
    assert (
        connection.execute(
            text(
                "SELECT id, scope, workspace_id, slug, revision, source_digest, "
                "descriptor_digest, published_at FROM plugin_releases ORDER BY id"
            )
        ).all()
        == release_snapshot
    )


def _selection_snapshot(connection: Connection) -> Sequence[Row[Any]]:
    return connection.execute(
        text(
            "SELECT scope, workspace_id, slug, selected_release_id, "
            "selected_revision, lifecycle, generation, updated_at, "
            "updated_by_actor FROM plugin_release_selections ORDER BY slug"
        )
    ).all()


def _release_snapshot(connection: Connection) -> Sequence[Row[Any]]:
    return connection.execute(
        text(
            "SELECT id, scope, workspace_id, slug, revision, source_digest, "
            "descriptor_digest, published_at FROM plugin_releases ORDER BY id"
        )
    ).all()


def test_0020_downgrade_refuses_selection_pointing_at_older_retained_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "older-revision-downgrade" / "migrated.sqlite3"
    monkeypatch.setenv("GRAFY_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0018_local_execution_queue")
    _seed_0019_workspace_release_and_references(database_path)
    command.upgrade(config, "0020_plugin_release_selections")

    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO plugin_releases ("
                "id, scope, workspace_id, slug, revision, catalog, contract_digest, "
                "capabilities, capability_digest, protocol_digest, profile_digest, "
                "source_object_key, source_digest, lock_digest, runtime_profile, "
                "runtime_image_digest, runtime_artifact, descriptor_digest, "
                "execution_policy, distribution, published_by_user_id, published_at) "
                "SELECT :id, scope, workspace_id, slug, 4, catalog, contract_digest, "
                "capabilities, capability_digest, protocol_digest, profile_digest, "
                "source_object_key, :source_digest, lock_digest, runtime_profile, "
                "runtime_image_digest, runtime_artifact, :descriptor_digest, "
                "execution_policy, distribution, published_by_user_id, :published_at "
                "FROM plugin_releases WHERE scope = 'workspace' AND slug = 'notes' "
                "LIMIT 1"
            ),
            {
                "id": UUID("00000000-0000-0000-0000-000000002101").hex,
                "source_digest": "7" * 64,
                "descriptor_digest": "8" * 64,
                "published_at": "2026-08-25 10:00:00",
            },
        )
        selection_snapshot = _selection_snapshot(connection)
        release_snapshot = _release_snapshot(connection)

    with pytest.raises(
        RuntimeError,
        match=r"family 'notes' of workspace .* selection state selects revision 3 "
        r"instead of the family's maximum retained revision 4",
    ):
        command.downgrade(config, "0019_scoped_plugin_releases")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        _assert_0020_downgrade_refused_leaves_schema_unchanged(
            connection,
            selection_snapshot,
            release_snapshot,
        )
    get_settings.cache_clear()


@pytest.mark.parametrize("lifecycle", ["deprecated", "withdrawn"])
def test_0020_downgrade_refuses_mutated_selection_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lifecycle: str,
) -> None:
    database_path = (
        tmp_path / f"{lifecycle}-downgrade" / "migrated.sqlite3"
    )
    monkeypatch.setenv("GRAFY_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0018_local_execution_queue")
    _seed_0019_workspace_release_and_references(database_path)
    command.upgrade(config, "0020_plugin_release_selections")

    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "UPDATE plugin_release_selections SET lifecycle = :lifecycle "
                "WHERE scope = 'workspace'"
            ),
            {"lifecycle": lifecycle},
        )
        selection_snapshot = _selection_snapshot(connection)
        release_snapshot = _release_snapshot(connection)

    with pytest.raises(
        RuntimeError,
        match=r"family 'notes' of workspace .* has lifecycle "
        rf"'{lifecycle}' instead of 'published'",
    ):
        command.downgrade(config, "0019_scoped_plugin_releases")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        _assert_0020_downgrade_refused_leaves_schema_unchanged(
            connection,
            selection_snapshot,
            release_snapshot,
        )
    get_settings.cache_clear()


def test_0020_downgrade_refuses_generation_above_backfill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "generation-downgrade" / "migrated.sqlite3"
    monkeypatch.setenv("GRAFY_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0018_local_execution_queue")
    _seed_0019_workspace_release_and_references(database_path)
    command.upgrade(config, "0020_plugin_release_selections")

    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "UPDATE plugin_release_selections SET generation = 2, "
                "updated_by_actor = 'user:00000000-0000-0000-0000-000000000007' "
                "WHERE scope = 'workspace'"
            )
        )
        selection_snapshot = _selection_snapshot(connection)
        release_snapshot = _release_snapshot(connection)

    with pytest.raises(
        RuntimeError,
        match=r"family 'notes' of workspace .* is at generation 2 instead of 1",
    ):
        command.downgrade(config, "0019_scoped_plugin_releases")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        _assert_0020_downgrade_refused_leaves_schema_unchanged(
            connection,
            selection_snapshot,
            release_snapshot,
        )
    get_settings.cache_clear()


def test_0020_downgrade_refuses_non_migration_selection_actor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "actor-downgrade" / "migrated.sqlite3"
    monkeypatch.setenv("GRAFY_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0018_local_execution_queue")
    _seed_0019_workspace_release_and_references(database_path)
    command.upgrade(config, "0020_plugin_release_selections")

    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text(
                "UPDATE plugin_release_selections SET updated_by_actor = "
                "'user:00000000-0000-0000-0000-000000000007' "
                "WHERE scope = 'workspace'"
            )
        )
        selection_snapshot = _selection_snapshot(connection)
        release_snapshot = _release_snapshot(connection)

    with pytest.raises(
        RuntimeError,
        match=r"family 'notes' of workspace .* was last updated by "
        r"'user:00000000-0000-0000-0000-000000000007' instead of the 0020 "
        r"migration backfill",
    ):
        command.downgrade(config, "0019_scoped_plugin_releases")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        _assert_0020_downgrade_refused_leaves_schema_unchanged(
            connection,
            selection_snapshot,
            release_snapshot,
        )
    get_settings.cache_clear()


def test_0020_downgrade_refuses_family_without_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "missing-selection-downgrade" / "migrated.sqlite3"
    monkeypatch.setenv("GRAFY_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0018_local_execution_queue")
    _seed_0019_workspace_release_and_references(database_path)
    command.upgrade(config, "0020_plugin_release_selections")

    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.execute(
            text("DELETE FROM plugin_release_selections WHERE scope = 'workspace'")
        )
        selection_snapshot = _selection_snapshot(connection)
        release_snapshot = _release_snapshot(connection)

    with pytest.raises(
        RuntimeError,
        match=r"family 'notes' of workspace .* has releases but no explicit "
        r"selection",
    ):
        command.downgrade(config, "0019_scoped_plugin_releases")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        _assert_0020_downgrade_refused_leaves_schema_unchanged(
            connection,
            selection_snapshot,
            release_snapshot,
        )
    get_settings.cache_clear()


def test_0021_adds_empty_exact_revocations_without_release_schema_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "plugin-release-revocations" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0020_plugin_release_selections")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        release_columns = [
            (
                column["name"],
                str(column["type"]),
                column["nullable"],
                column["default"],
                column["primary_key"],
            )
            for column in inspect(connection).get_columns("plugin_releases")
        ]
        assert "plugin_release_revocations" not in inspect(
            connection
        ).get_table_names()

    command.upgrade(config, "0021_plugin_release_revocations")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        inspector = inspect(connection)
        assert [
            (
                column["name"],
                str(column["type"]),
                column["nullable"],
                column["default"],
                column["primary_key"],
            )
            for column in inspector.get_columns("plugin_releases")
        ] == release_columns
        assert "plugin_release_revocations" in inspector.get_table_names()
        assert [
            column["name"]
            for column in inspector.get_columns("plugin_release_revocations")
        ] == [
            "release_id",
            "scope",
            "workspace_id",
            "slug",
            "revision",
            "reason",
            "revoked_by_user_id",
            "revoked_by_platform_actor",
            "revoked_at",
        ]
        assert inspector.get_pk_constraint("plugin_release_revocations")[
            "constrained_columns"
        ] == ["release_id"]
        release_foreign_key = next(
            foreign_key
            for foreign_key in inspector.get_foreign_keys(
                "plugin_release_revocations"
            )
            if foreign_key["constrained_columns"] == ["release_id"]
        )
        assert release_foreign_key["referred_table"] == "plugin_releases"
        assert release_foreign_key["options"]["ondelete"] == "RESTRICT"
        assert connection.execute(
            text("SELECT COUNT(*) FROM plugin_release_revocations")
        ).scalar_one() == 0
    command.upgrade(config, "head")
    command.check(config)

    command.downgrade(config, "0020_plugin_release_selections")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        assert "plugin_release_revocations" not in inspect(
            connection
        ).get_table_names()
        assert [
            (
                column["name"],
                str(column["type"]),
                column["nullable"],
                column["default"],
                column["primary_key"],
            )
            for column in inspect(connection).get_columns("plugin_releases")
        ] == release_columns
    get_settings.cache_clear()


def test_0021_downgrade_refuses_to_discard_revocation_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "revocation-downgrade" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0018_local_execution_queue")
    _seed_0019_workspace_release_and_references(database_path)
    command.upgrade(config, "0021_plugin_release_revocations")

    actor_id = UUID("00000000-0000-0000-0000-000000002101").hex
    timestamp = "2026-08-24 12:00:00"
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.execute(
            text(
                "INSERT INTO users (id, email, display_name, active, created_at, "
                "updated_at) VALUES (:id, 'revoker@example.test', 'Revoker', 1, "
                ":timestamp, :timestamp)"
            ),
            {"id": actor_id, "timestamp": timestamp},
        )
        release = (
            connection.execute(
                text(
                    "SELECT id, scope, workspace_id, slug, revision "
                    "FROM plugin_releases WHERE slug = 'notes'"
                )
            )
            .mappings()
            .one()
        )
        connection.execute(
            text(
                "INSERT INTO plugin_release_revocations (release_id, scope, "
                "workspace_id, slug, revision, reason, revoked_by_user_id, "
                "revoked_by_platform_actor, revoked_at) VALUES (:release_id, "
                ":scope, :workspace_id, :slug, :revision, 'security', :actor_id, "
                "NULL, :timestamp)"
            ),
            {
                **release,
                "release_id": release["id"],
                "actor_id": actor_id,
                "timestamp": timestamp,
            },
        )

    with pytest.raises(RuntimeError, match="revocations would be lost"):
        command.downgrade(config, "0020_plugin_release_selections")
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM plugin_release_revocations")
        ).scalar_one() == 1
        connection.execute(text("DELETE FROM plugin_release_revocations"))
    command.downgrade(config, "0020_plugin_release_selections")
    get_settings.cache_clear()


def test_0026_wipes_graph_plugin_data_and_drops_installation_distribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "drop-distribution" / "migrated.sqlite3"
    monkeypatch.setenv("GRAFY_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0025_platform_access_tokens")

    user_hex = UUID("00000000-0000-0000-0000-000000002601").hex
    workspace_hex = UUID("00000000-0000-0000-0000-000000002602").hex
    graph_hex = UUID("00000000-0000-0000-0000-000000002603").hex
    artifact_hex = UUID("00000000-0000-0000-0000-000000002604").hex
    release_hex = UUID("00000000-0000-0000-0000-000000002605").hex
    installation_hex = UUID("00000000-0000-0000-0000-000000002606").hex
    timestamp = "2026-09-01 10:00:00"
    document = json.dumps({"schema_version": 6, "nodes": [], "edges": []})
    digest = "a" * 64

    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert "distribution" in {
            column["name"]
            for column in inspect(connection).get_columns("plugin_installations")
        }
        connection.execute(
            text(
                "INSERT INTO users (id, email, display_name, active, created_at, "
                "updated_at) VALUES (:id, 'cutover@example.test', 'Cutover', 1, "
                ":timestamp, :timestamp)"
            ),
            {"id": user_hex, "timestamp": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO workspaces "
                "(id, slug, name, kind, created_at, updated_at) VALUES "
                "(:id, 'cutover', 'Cutover', 'shared', :timestamp, :timestamp)"
            ),
            {"id": workspace_hex, "timestamp": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO saved_graphs "
                "(workspace_id, id, name, document, revision, created_at, "
                "updated_at) VALUES (:workspace_id, :graph_id, 'Cutover graph', "
                ":document, 1, :timestamp, :timestamp)"
            ),
            {
                "workspace_id": workspace_hex,
                "graph_id": graph_hex,
                "document": document,
                "timestamp": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO artifact_objects "
                "(id, workspace_id, artifact_type, schema_version, content_type, "
                "storage_backend, metadata) VALUES (:artifact_id, :workspace_id, "
                "'scalar.text', 1, 'application/json', 'inline', '{}')"
            ),
            {"artifact_id": artifact_hex, "workspace_id": workspace_hex},
        )
        connection.execute(
            text(
                "INSERT INTO plugin_releases ("
                "id, slug, revision, catalog, capabilities, capability_digest, "
                "source_object_key, source_digest, lock_digest, runtime_profile, "
                "loader_target, published_by_platform_actor, published_at) VALUES ("
                ":id, 'notes', 1, :catalog, :capabilities, :digest, "
                "'plugin-releases/system/notes/source.tar.gz', :digest, :digest, "
                "'python-uv', 'grafy_plugin:PLUGIN', 'test:cutover', :timestamp)"
            ),
            {
                "id": release_hex,
                "catalog": json.dumps({"slug": "notes", "title": "Notes"}),
                "capabilities": json.dumps({"capabilities": []}),
                "digest": digest,
                "timestamp": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO plugin_installations ("
                "id, release_id, scope, workspace_id, slug, release_revision, "
                "execution_policy, distribution, installed_by_user_id, "
                "installed_by_platform_actor, installed_at) VALUES ("
                ":id, :release_id, 'system', NULL, 'notes', 1, 'isolated-only', "
                "'optional', NULL, 'test:cutover', :timestamp)"
            ),
            {
                "id": installation_hex,
                "release_id": release_hex,
                "timestamp": timestamp,
            },
        )

    command.upgrade(config, "head")
    command.check(config)
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("plugin_installations")
        }
        assert "distribution" not in columns
        table_sql = connection.execute(
            text(
                "SELECT sql FROM sqlite_master WHERE name = 'plugin_installations'"
            )
        ).scalar_one()
        assert "bundled" not in table_sql
        assert "isolated-only" in table_sql
        assert connection.execute(text("SELECT COUNT(*) FROM saved_graphs")).scalar_one() == 0
        assert (
            connection.execute(text("SELECT COUNT(*) FROM plugin_releases")).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM plugin_installations")
            ).scalar_one()
            == 0
        )
        assert connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 1
        assert (
            connection.execute(text("SELECT COUNT(*) FROM workspaces")).scalar_one() == 1
        )
        assert (
            connection.execute(text("SELECT COUNT(*) FROM artifact_objects")).scalar_one()
            == 1
        )

    command.downgrade(config, "0025_platform_access_tokens")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("plugin_installations")
        }
        assert "distribution" in columns
        assert connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 1
        assert (
            connection.execute(text("SELECT COUNT(*) FROM artifact_objects")).scalar_one()
            == 1
        )
        assert connection.execute(text("SELECT COUNT(*) FROM saved_graphs")).scalar_one() == 0
    get_settings.cache_clear()


def test_plugin_registry_unique_indexes_compile_for_postgresql() -> None:
    indexes = {
        str(index.name): index
        for table in (
            plugin_releases,
            plugin_installations,
            plugin_release_selections,
        )
        for index in table.indexes
        if index.name is not None
    }
    expected = {
        "uq_plugin_releases_slug_revision",
        "uq_plugin_releases_slug_descriptor",
        "uq_plugin_installations_system_slug_revision",
        "uq_plugin_installations_workspace_slug_revision",
        "uq_plugin_release_selections_system_slug",
        "uq_plugin_release_selections_workspace_slug",
    }
    assert expected <= indexes.keys()
    for index_name in expected:
        ddl = str(
            CreateIndex(indexes[index_name]).compile(dialect=postgresql.dialect())
        )
        assert ddl.startswith(f"CREATE UNIQUE INDEX {index_name}")
        if index_name == "uq_plugin_releases_slug_revision":
            assert " WHERE " not in ddl
        elif index_name == "uq_plugin_releases_slug_descriptor":
            assert " WHERE descriptor_digest IS NOT NULL" in ddl
        else:
            assert " WHERE scope = " in ddl

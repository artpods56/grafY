import json
import importlib
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects import sqlite

from grafy_api.settings import get_settings
from grafy_persistence.schema import staged_uploads


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


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
    captured_tables: list[tuple[str, tuple[object, ...]]] = []
    captured_indexes: list[tuple[str, str, tuple[str, ...]]] = []

    class CaptureOperations:
        def create_table(self, name: str, *elements: object, **kwargs: object) -> None:
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

    migration.op = CaptureOperations()
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

    command.upgrade(config, "head")
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
        assert json.loads(row["document"]) == document
        assert str(row["created_at"]) == "2026-07-16 09:30:00"

    command.downgrade(config, "0003_node_secrets")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        assert "saved_graph_revisions" not in inspect(connection).get_table_names()

    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")

    command.upgrade(config, "head")
    assert database_path.exists()
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        assert set(inspect(connection).get_table_names()) == {
            "agent_environments",
            "agent_events",
            "agent_runs",
            "agent_threads",
            "alembic_version",
            "artifact_objects",
            "collaborative_graph_heads",
            "capability_approvals",
            "draft_nodes",
            "graph_active_execution_slots",
            "graph_checkpoint_mappings",
            "graph_command_journal",
            "graph_command_receipts",
            "graph_execution_idempotency",
            "graph_execution_node_results",
            "graph_execution_requested_nodes",
            "graph_executions",
            "graph_folders",
            "graph_organizations",
            "invocation_cache_entries",
            "materialized_node_outputs",
            "module_releases",
            "modules",
            "node_secrets",
            "node_build_attempts",
            "node_releases",
            "users",
            "oidc_identities",
            "oidc_login_transactions",
            "oidc_bootstrap_owner_mappings",
            "workspaces",
            "workspace_memberships",
            "auth_sessions",
            "personal_access_tokens",
            "security_audit_events",
            "saved_graphs",
            "saved_graph_revisions",
            "staged_uploads",
            "user_graph_states",
            "templates",
        }
    command.check(config)

    command.downgrade(config, "base")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        assert inspect(connection).get_table_names() == ["alembic_version"]

    command.upgrade(config, "head")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert set(inspect(connection).get_table_names()) == {
            "agent_environments",
            "agent_events",
            "agent_runs",
            "agent_threads",
            "alembic_version",
            "artifact_objects",
            "collaborative_graph_heads",
            "capability_approvals",
            "draft_nodes",
            "graph_active_execution_slots",
            "graph_checkpoint_mappings",
            "graph_command_journal",
            "graph_command_receipts",
            "graph_execution_idempotency",
            "graph_execution_node_results",
            "graph_execution_requested_nodes",
            "graph_executions",
            "graph_folders",
            "graph_organizations",
            "invocation_cache_entries",
            "materialized_node_outputs",
            "module_releases",
            "modules",
            "node_secrets",
            "node_build_attempts",
            "node_releases",
            "users",
            "oidc_identities",
            "oidc_login_transactions",
            "oidc_bootstrap_owner_mappings",
            "workspaces",
            "workspace_memberships",
            "auth_sessions",
            "personal_access_tokens",
            "security_audit_events",
            "saved_graphs",
            "saved_graph_revisions",
            "staged_uploads",
            "user_graph_states",
            "templates",
        }

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

    command.upgrade(config, "head")
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
        assert json.loads(row["document"]) == document
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
    document = {"schema_version": 3, "nodes": [], "edges": []}
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

    command.upgrade(config, "head")
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
            "graph_execution_requested_nodes",
            "graph_execution_node_results",
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


def test_retire_daytona_provider_rewrites_failed_environments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "daytona-retire" / "migrated.sqlite3"
    monkeypatch.setenv(
        "GRAFY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    command.upgrade(config, "0013_agent_authoring")

    failed_id = "94c5ff29131445c1907906767b606642"
    ready_id = "a4c5ff29131445c1907906767b606643"
    with create_engine(f"sqlite:///{database_path}").begin() as connection:
        workspace_id = connection.execute(
            text("SELECT id FROM workspaces LIMIT 1")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO agent_environments "
                "(id, workspace_id, name, profile_id, provider, status, "
                "provider_environment_id, provisioning_fencing_token, "
                "failure_message, created_at, updated_at) VALUES "
                "(:id, :workspace_id, :name, 'python-uv', 'daytona', :status, "
                ":provider_environment_id, 1, :failure_message, "
                ":created_at, :updated_at)"
            ),
            [
                {
                    "id": failed_id,
                    "workspace_id": workspace_id,
                    "name": "Failed Daytona lab",
                    "status": "failed",
                    "provider_environment_id": None,
                    "failure_message": "No sandbox provider is configured for 'daytona'",
                    "created_at": "2026-08-17 14:00:00",
                    "updated_at": "2026-08-17 14:00:00",
                },
                {
                    "id": ready_id,
                    "workspace_id": workspace_id,
                    "name": "Ready Daytona lab",
                    "status": "ready",
                    "provider_environment_id": "sandbox-keep",
                    "failure_message": None,
                    "created_at": "2026-08-17 14:00:00",
                    "updated_at": "2026-08-17 14:00:00",
                },
            ],
        )

    command.upgrade(config, "head")
    with create_engine(f"sqlite:///{database_path}").connect() as connection:
        rows = {
            row["id"]: row
            for row in connection.execute(
                text(
                    "SELECT id, provider, status, failure_message, "
                    "provider_environment_id FROM agent_environments"
                )
            ).mappings()
        }
        assert rows[failed_id]["provider"] == "docker-trusted-development"
        assert rows[failed_id]["status"] == "provisioning"
        assert rows[failed_id]["failure_message"] is None
        assert rows[ready_id]["provider"] == "docker-trusted-development"
        assert rows[ready_id]["status"] == "ready"
        assert rows[ready_id]["provider_environment_id"] == "sandbox-keep"

    get_settings.cache_clear()

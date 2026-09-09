import tomllib
from io import BytesIO
from pathlib import Path

from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.table_contracts import (
    TABLE_DATA,
)
from grafy_workbench.table import TABLES
from grafy_workbench.table.persistence import TableArtifactResolver, TableArtifactWriter
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.storage import SaveFileCommand, StoredFile, StoredObjectInfo
from grafy_core.runtime.persistence import InlineModelOutputWriter
from grafy_core.runtime.resolvers import InlineModelResolver
from grafy_plugin_sql import SQL
from grafy_plugin_sql.artifacts import SQL_RESULT, SQL_STATEMENT
from grafy_plugin_sql.models import SqlResult, SqlStatement
from grafy_plugin_sql.nodes import (
    ExecuteSqlNode,
    QueryArtifactTablesNode,
    RawSqlStatementNode,
)


class EmptyStorage:
    async def save(self, command: SaveFileCommand) -> StoredFile:
        raise AssertionError(f"Unexpected save to {command.bucket}/{command.path}")

    async def move(
        self,
        bucket: str,
        source_path: str,
        destination_path: str,
    ) -> None:
        raise AssertionError(
            f"Unexpected move in {bucket}: {source_path} to {destination_path}"
        )

    async def load(self, bucket: str, path: str) -> BytesIO:
        raise AssertionError(f"Unexpected load from {bucket}/{path}")

    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        raise AssertionError(f"Unexpected stat for {bucket}/{path}")

    async def load_range(
        self,
        bucket: str,
        path: str,
        start: int,
        end_exclusive: int,
    ) -> bytes:
        raise AssertionError(
            f"Unexpected range load from {bucket}/{path}: {start}:{end_exclusive}"
        )

    async def delete(self, bucket: str, path: str) -> None:
        raise AssertionError(f"Unexpected delete from {bucket}/{path}")


def test_sql_plugin_declares_complete_runtime_contributions(tmp_path: Path) -> None:
    registry = PluginRegistry()
    registry.install(TABLES)
    registry.install(SQL)
    registry.freeze()
    context = PluginRuntimeContext(
        workspace=tmp_path,
        uploads_dir=tmp_path / "uploads",
        storage=EmptyStorage(),
        uow=InMemoryUnitOfWork(),
        bucket="artifacts",
    )

    assert SQL.slug == "external.sql"
    assert SQL.title == "SQL"
    assert {registration.key for registration in SQL.nodes} == {
        ("sql.artifacts.query", 1),
        ("sql.statement.raw", 1),
        ("sql.postgresql.execute", 1),
    }
    assert {artifact.key for artifact in registry.artifact_types} == {
        TABLE_DATA.key,
        SQL_STATEMENT.key,
        SQL_RESULT.key,
    }
    assert SQL_STATEMENT.payload_schema == SqlStatement.model_json_schema()
    assert SQL_RESULT.payload_schema == SqlResult.model_json_schema()
    assert SQL_RESULT.field_projections[0].path == ("table",)
    assert SQL_RESULT.field_projections[0].target == TABLE_DATA.key
    assert isinstance(
        registry.build_node("sql.statement.raw", 1, context),
        RawSqlStatementNode,
    )
    assert isinstance(
        registry.build_node("sql.artifacts.query", 1, context),
        QueryArtifactTablesNode,
    )
    assert isinstance(
        registry.build_node("sql.postgresql.execute", 1, context),
        ExecuteSqlNode,
    )

    resolvers = registry.build_resolvers(context)
    writers = registry.build_writers(context)

    assert {
        resolver.source: resolver.target
        for resolver in resolvers
        if isinstance(resolver, InlineModelResolver)
    } == {
        SQL_STATEMENT.key: SqlStatement,
        SQL_RESULT.key: SqlResult,
    }
    assert any(isinstance(resolver, TableArtifactResolver) for resolver in resolvers)
    assert {
        writer.artifact_type
        for writer in writers
        if isinstance(writer, InlineModelOutputWriter)
    } == {SQL_STATEMENT.key, SQL_RESULT.key}
    assert any(isinstance(writer, TableArtifactWriter) for writer in writers)


def test_sql_execute_declares_password_bound_to_connection_config() -> None:
    registration = next(
        registration
        for registration in SQL.nodes
        if registration.key == ("sql.postgresql.execute", 1)
    )

    assert len(registration.secret_inputs) == 1
    assert registration.secret_inputs[0].name == "password"
    assert registration.secret_inputs[0].config_dependencies == (
        "host",
        "port",
        "database",
        "username",
        "ssl_mode",
    )


def test_sql_package_metadata_has_no_ambient_plugin_entry_point() -> None:
    project_root = Path(__file__).parents[3]
    metadata = tomllib.loads(
        (project_root / "plugins" / "sql" / "pyproject.toml").read_text()
    )

    assert metadata["project"]["name"] == "grafy-plugin-sql"
    assert "duckdb==1.5.5" in metadata["project"]["dependencies"]
    assert "entry-points" not in metadata["project"]

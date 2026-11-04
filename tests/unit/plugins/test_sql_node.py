from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr, ValidationError

from grafy_core.domain.node_secrets import JsonValue
from grafy_core.nodes import NodeExecutionContext, PortShape
from grafy_core.table_contracts import (
    TABLE_DATA,
    Table,
    TableColumn,
    TableValueType,
)
from grafy_plugin_sql.artifacts import SQL_RESULT, SQL_STATEMENT
from grafy_plugin_sql.models import SqlResult, SqlStatement
from grafy_plugin_sql.nodes import (
    ArtifactQueryExecutionError,
    ArtifactQueryRelation,
    ExecuteSqlConfig,
    ExecuteSqlInput,
    ExecuteSqlNode,
    PostgresSslMode,
    QueryArtifactTablesConfig,
    QueryArtifactTablesInput,
    QueryArtifactTablesNode,
    RawSqlStatementConfig,
    RawSqlStatementInput,
    RawSqlStatementNode,
    SqlExecutionError,
)


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


class FakeSecretResolver:
    def __init__(self, password: SecretStr, error: Exception | None = None) -> None:
        self._password = password
        self._error = error
        self.request: dict[str, object] | None = None

    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> SecretStr:
        self.request = {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "graph_id": graph_id,
            "node_id": node_id,
            "name": name,
            "dependencies": dict(dependencies),
        }
        if self._error is not None:
            raise self._error
        return self._password

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str:
        del workspace_id, project_id, graph_id, node_id, name, dependencies
        return "unused"


class FakeBatchExecutor:
    def __init__(
        self,
        results: list[SqlResult],
        error: Exception | None = None,
    ) -> None:
        self._results = results
        self._error = error
        self.config: ExecuteSqlConfig | None = None
        self.password: SecretStr | None = None
        self.statements: list[SqlStatement] | None = None

    async def execute(
        self,
        config: ExecuteSqlConfig,
        password: SecretStr,
        statements: list[SqlStatement],
        /,
    ) -> list[SqlResult]:
        self.config = config
        self.password = password
        self.statements = statements
        if self._error is not None:
            raise self._error
        return self._results


class FakeArtifactTableExecutor:
    def __init__(
        self,
        tables: list[Table],
        error: Exception | None = None,
    ) -> None:
        self._tables = tables
        self._error = error
        self.statements: list[SqlStatement] | None = None
        self.relation_aliases: list[str] | None = None
        self.relations: list[Table] | None = None

    async def execute(
        self,
        statements: list[SqlStatement],
        relation_aliases: list[str],
        relations: list[Table],
        /,
    ) -> list[Table]:
        self.statements = statements
        self.relation_aliases = relation_aliases
        self.relations = relations
        if self._error is not None:
            raise self._error
        return self._tables


def execute_config() -> ExecuteSqlConfig:
    return ExecuteSqlConfig(
        host="db.internal",
        database="grafy",
        username="worker",
        ssl_mode=PostgresSslMode.REQUIRE,
    )


def test_artifact_query_config_requires_unique_stable_relation_names() -> None:
    with pytest.raises(ValidationError, match="aliases must be unique"):
        QueryArtifactTablesConfig(
            relations=[
                ArtifactQueryRelation(id="plug-a", alias="Parcels"),
                ArtifactQueryRelation(id="plug-b", alias="parcels"),
            ]
        )
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        ArtifactQueryRelation(id="plug", alias='source"; drop table source')


def test_raw_sql_statement_config_declares_sql_editor_schema() -> None:
    sql_schema = RawSqlStatementConfig.model_json_schema()["properties"]["sql"]
    assert sql_schema["format"] == "textarea"
    assert sql_schema["contentMediaType"] == "application/sql"


def test_sql_nodes_declare_statement_plugs_and_result_sequence() -> None:
    statement_output = RawSqlStatementNode.output_contract.ports["statement"]
    statements_input = ExecuteSqlNode.input_contract.ports["statements"]
    results_output = ExecuteSqlNode.output_contract.ports["results"]

    assert statement_output.produces == SQL_STATEMENT.key
    assert statement_output.shape is PortShape.ONE
    assert statements_input.accepts == SQL_STATEMENT.key
    assert statements_input.variadic
    assert statements_input.instance_plugs
    assert statements_input.target_type is SqlStatement
    assert results_output.produces == SQL_RESULT.key
    assert results_output.shape is PortShape.MANY

    artifact_statements = QueryArtifactTablesNode.input_contract.ports["statements"]
    artifact_relations = QueryArtifactTablesNode.input_contract.ports["relations"]
    artifact_tables = QueryArtifactTablesNode.output_contract.ports["tables"]

    assert artifact_statements.accepts == SQL_STATEMENT.key
    assert artifact_statements.variadic
    assert artifact_statements.instance_plugs
    assert artifact_relations.accepts == TABLE_DATA.key
    assert artifact_relations.variadic
    assert artifact_relations.instance_plugs
    assert artifact_relations.target_type is Table
    assert artifact_tables.produces == TABLE_DATA.key
    assert artifact_tables.shape is PortShape.MANY


async def test_raw_sql_statement_node_builds_parameterized_artifact() -> None:
    output = await RawSqlStatementNode().run(
        NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="statement"),
        RawSqlStatementConfig(
            sql="select * from invoices where id = :id and paid = :paid",
            parameters={"id": 42, "paid": False},
        ),
        RawSqlStatementInput(),
    )

    assert output.statement == SqlStatement(
        sql="select * from invoices where id = :id and paid = :paid",
        parameters={"id": 42, "paid": False},
    )


async def test_query_artifact_tables_preserves_statement_and_relation_order() -> None:
    statements = [
        SqlStatement(sql="select * from parcels"),
        SqlStatement(sql="select * from owners"),
    ]
    relations = [
        Table(
            columns=[
                TableColumn(
                    id="parcel_id",
                    title="Parcel ID",
                    value_type=TableValueType.INTEGER,
                )
            ],
            rows=[{"parcel_id": 7}],
        ),
        Table(
            columns=[
                TableColumn(
                    id="owner",
                    title="Owner",
                    value_type=TableValueType.TEXT,
                )
            ],
            rows=[{"owner": "Ada"}],
        ),
    ]
    expected_tables = [relations[0], relations[1]]
    executor = FakeArtifactTableExecutor(expected_tables)
    node = QueryArtifactTablesNode(executor=executor)

    output = await node.run(
        NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="query-artifacts"),
        QueryArtifactTablesConfig(
            relations=[
                ArtifactQueryRelation(id="plug-parcels", alias="parcels"),
                ArtifactQueryRelation(id="plug-owners", alias="owners"),
            ]
        ),
        QueryArtifactTablesInput(statements=statements, relations=relations),
    )

    assert output.tables == expected_tables
    assert executor.statements == statements
    assert executor.relation_aliases == ["parcels", "owners"]
    assert executor.relations == relations


async def test_query_artifact_tables_rejects_stale_relation_plugs_before_execution() -> (
    None
):
    executor = FakeArtifactTableExecutor([])
    node = QueryArtifactTablesNode(executor=executor)

    with pytest.raises(
        ArtifactQueryExecutionError,
        match="configured 2 relations but received 1 table inputs",
    ):
        await node.run(
            NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="query-artifacts"),
            QueryArtifactTablesConfig(
                relations=[
                    ArtifactQueryRelation(id="plug-parcels", alias="parcels"),
                    ArtifactQueryRelation(id="plug-owners", alias="owners"),
                ]
            ),
            QueryArtifactTablesInput(
                statements=[SqlStatement(sql="select * from parcels")],
                relations=[
                    Table(
                        columns=[
                            TableColumn(
                                id="id",
                                title="ID",
                                value_type=TableValueType.INTEGER,
                            )
                        ],
                        rows=[],
                    )
                ],
            ),
        )

    assert executor.statements is None


async def test_query_artifact_tables_chains_isolated_batch_failure() -> None:
    failure = RuntimeError("read-only query rejected")
    table = Table(
        columns=[
            TableColumn(
                id="id",
                title="ID",
                value_type=TableValueType.INTEGER,
            )
        ],
        rows=[],
    )
    node = QueryArtifactTablesNode(
        executor=FakeArtifactTableExecutor([], error=failure)
    )

    with pytest.raises(
        ArtifactQueryExecutionError,
        match="query-artifacts.*2 statements.*1 relations",
    ) as captured:
        await node.run(
            NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="query-artifacts"),
            QueryArtifactTablesConfig(
                relations=[ArtifactQueryRelation(id="plug", alias="source")]
            ),
            QueryArtifactTablesInput(
                statements=[
                    SqlStatement(sql="select 1"),
                    SqlStatement(sql="delete from source"),
                ],
                relations=[table],
            ),
        )

    assert captured.value.__cause__ is failure


async def test_execute_sql_resolves_bound_secret_and_preserves_result_order() -> None:
    project_id = uuid4()
    statements = [
        SqlStatement(
            sql="insert into jobs(name) values(:name)",
            parameters={"name": "ocr"},
        ),
        SqlStatement(sql="select id, name from jobs order by id"),
    ]
    expected_results = [
        SqlResult(
            statement_index=0,
            returns_rows=False,
            table=Table(columns=[], rows=[]),
            affected_rows=1,
        ),
        SqlResult(
            statement_index=1,
            returns_rows=True,
            table=Table(
                columns=[
                    TableColumn(
                        id="column_1",
                        title="id",
                        value_type=TableValueType.INTEGER,
                    ),
                    TableColumn(
                        id="column_2",
                        title="name",
                        value_type=TableValueType.TEXT,
                    ),
                ],
                rows=[{"column_1": 7, "column_2": "ocr"}],
            ),
        ),
    ]
    password = SecretStr("database-password")
    secrets = FakeSecretResolver(password)
    executor = FakeBatchExecutor(expected_results)
    node = ExecuteSqlNode(executor=executor, node_secrets=secrets)
    config = execute_config()

    output = await node.run(
        NodeExecutionContext(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            graph_id="warehouse",
            node_id="execute-postgres",
        ),
        config,
        ExecuteSqlInput(statements=statements),
    )

    assert output.results == expected_results
    assert executor.config == config
    assert executor.password is password
    assert executor.statements == statements
    assert secrets.request == {
        "workspace_id": WORKSPACE_ID,
        "project_id": project_id,
        "graph_id": "warehouse",
        "node_id": "execute-postgres",
        "name": "password",
        "dependencies": {
            "host": "db.internal",
            "port": 5432,
            "database": "grafy",
            "username": "worker",
            "ssl_mode": "require",
        },
    }


async def test_execute_sql_chains_batch_failure_with_connection_context() -> None:
    failure = RuntimeError("statement at index 1 failed")
    node = ExecuteSqlNode(
        executor=FakeBatchExecutor([], error=failure),
        node_secrets=FakeSecretResolver(SecretStr("password")),
    )

    with pytest.raises(
        SqlExecutionError,
        match="grafy.*db.internal.*2 statements",
    ) as captured:
        await node.run(
            NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="execute-postgres"),
            execute_config(),
            ExecuteSqlInput(
                statements=[
                    SqlStatement(sql="select 1"),
                    SqlStatement(sql="select 2"),
                ]
            ),
        )

    assert captured.value.__cause__ is failure


async def test_execute_sql_rejects_missing_results() -> None:
    node = ExecuteSqlNode(
        executor=FakeBatchExecutor(
            [
                SqlResult(
                    statement_index=0,
                    returns_rows=True,
                    table=Table(columns=[], rows=[]),
                )
            ]
        ),
        node_secrets=FakeSecretResolver(SecretStr("password")),
    )

    with pytest.raises(SqlExecutionError, match="1 results for 2 statements"):
        await node.run(
            NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="execute-postgres"),
            execute_config(),
            ExecuteSqlInput(
                statements=[
                    SqlStatement(sql="select 1"),
                    SqlStatement(sql="select 2"),
                ]
            ),
        )

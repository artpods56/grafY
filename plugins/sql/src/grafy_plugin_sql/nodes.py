from enum import StrEnum
from typing import Annotated, Protocol, Self, final, override

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import InPort, Node, NodeExecutionContext, OutPort
from grafy_core.table_contracts import TABLE_DATA, Table
from grafy_core.plugins import (
    NodeCachePolicy,
    NodeSecretInput,
    PluginRuntimeContext,
)
from grafy_core.ports.node_secrets import NodeSecretResolverPort

from grafy_plugin_sql.artifacts import SQL_RESULT, SQL_STATEMENT
from grafy_plugin_sql.declaration import SQL
from grafy_plugin_sql.models import SqlResult, SqlStatement, SqlValue


class RawSqlStatementConfig(NodeConfig):
    sql: StrictStr = Field(
        min_length=1,
        max_length=1_000_000,
        description=(
            "SQL statement using canonical named :parameter placeholders. "
            "Executors translate this binding syntax for their database driver."
        ),
        json_schema_extra={
            "format": "textarea",
            "contentMediaType": "application/sql",
        },
    )
    parameters: dict[str, SqlValue] = Field(
        default_factory=dict,
        max_length=10_000,
        description=(
            "Named non-secret values bound to :name parameters. Values are "
            "persisted in the statement artifact."
        ),
    )

    @field_validator("sql")
    @classmethod
    def validate_sql(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("sql must contain a non-whitespace statement")
        return value


class RawSqlStatementInput(NodeInput):
    pass


class RawSqlStatementOutput(NodeOutput):
    statement: Annotated[
        SqlStatement,
        OutPort(SQL_STATEMENT),
        Field(description="Parameterized SQL statement ready for execution."),
    ]


@SQL.function_node(
    operator_id="sql.statement.raw",
    version=1,
    title="Raw SQL statement",
    cache_policy=NodeCachePolicy.EXACT,
)
async def raw_sql_statement(
    config: RawSqlStatementConfig,
    _inputs: RawSqlStatementInput,
) -> RawSqlStatementOutput:
    """Builds one inert parameterized SQL statement."""
    return RawSqlStatementOutput(
        statement=SqlStatement(sql=config.sql, parameters=config.parameters)
    )


RawSqlStatementNode = SQL.nodes[-1].node_class


class ArtifactQueryRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(
        min_length=1,
        max_length=255,
        description="Stable ID shared with this relation's table input plug.",
    )
    alias: StrictStr = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        description="SQL table name exposed to every statement in this batch.",
    )

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("relation id must not have surrounding whitespace")
        return value


class QueryArtifactTablesConfig(NodeConfig):
    relations: list[ArtifactQueryRelation] = Field(
        min_length=1,
        max_length=32,
        description=(
            "Ordered table relations. Each ID matches an input plug and each "
            "alias is visible as a SQL table name."
        ),
    )

    @model_validator(mode="after")
    def validate_unique_relations(self) -> Self:
        relation_ids = [relation.id for relation in self.relations]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("relation ids must be unique")
        aliases = [relation.alias.casefold() for relation in self.relations]
        if len(aliases) != len(set(aliases)):
            raise ValueError("relation aliases must be unique ignoring case")
        return self


class QueryArtifactTablesInput(NodeInput):
    statements: Annotated[
        list[SqlStatement],
        InPort(SQL_STATEMENT, variadic=True, instance_plugs=True),
        Field(
            min_length=1,
            max_length=32,
            description=(
                "Read-only queries evaluated independently in saved plug order."
            ),
        ),
    ]
    relations: Annotated[
        list[Table],
        InPort(TABLE_DATA, variadic=True, instance_plugs=True),
        Field(
            min_length=1,
            max_length=32,
            description=(
                "Table artifacts matched positionally to configured relations."
            ),
        ),
    ]


class QueryArtifactTablesOutput(NodeOutput):
    tables: Annotated[
        list[Table],
        OutPort(TABLE_DATA),
        Field(
            min_length=1,
            max_length=32,
            description="One ordered table result for each query statement.",
        ),
    ]


class ArtifactTableBatchExecutor(Protocol):
    async def execute(
        self,
        statements: list[SqlStatement],
        relation_aliases: list[str],
        relations: list[Table],
        /,
    ) -> list[Table]: ...


class ArtifactQueryExecutionError(RuntimeError):
    pass


def build_query_artifact_tables_node(
    _context: PluginRuntimeContext,
) -> "QueryArtifactTablesNode":
    from grafy_plugin_sql.artifact_query import IsolatedDuckDbArtifactTableExecutor

    return QueryArtifactTablesNode(executor=IsolatedDuckDbArtifactTableExecutor())


@SQL.node(
    operator_id="sql.artifacts.query",
    version=1,
    title="Query artifact tables",
    factory=build_query_artifact_tables_node,
    required_capabilities=(PluginRuntimeCapability.UNTRUSTED_SQL,),
    cache_policy=NodeCachePolicy.NEVER,
)
@final
class QueryArtifactTablesNode(
    Node[
        QueryArtifactTablesConfig,
        QueryArtifactTablesInput,
        QueryArtifactTablesOutput,
    ]
):
    """Runs ordered, read-only SQL queries over one immutable table snapshot."""

    def __init__(self, *, executor: ArtifactTableBatchExecutor) -> None:
        self._executor = executor

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: QueryArtifactTablesConfig,
        inputs: QueryArtifactTablesInput,
        /,
    ) -> QueryArtifactTablesOutput:
        if len(config.relations) != len(inputs.relations):
            raise ArtifactQueryExecutionError(
                f"Artifact query node {context.node_id!r} configured "
                f"{len(config.relations)} relations but received "
                f"{len(inputs.relations)} table inputs"
            )
        try:
            tables = await self._executor.execute(
                inputs.statements,
                [relation.alias for relation in config.relations],
                inputs.relations,
            )
        except Exception as exc:
            raise ArtifactQueryExecutionError(
                f"Artifact query batch failed for node {context.node_id!r} with "
                f"{len(inputs.statements)} statements and "
                f"{len(inputs.relations)} relations"
            ) from exc
        if len(tables) != len(inputs.statements):
            raise ArtifactQueryExecutionError(
                "Artifact query executor returned "
                f"{len(tables)} tables for {len(inputs.statements)} statements"
            )
        return QueryArtifactTablesOutput(tables=tables)


class PostgresSslMode(StrEnum):
    DISABLE = "disable"
    PREFER = "prefer"
    REQUIRE = "require"
    VERIFY_CA = "verify-ca"
    VERIFY_FULL = "verify-full"


class ExecuteSqlConfig(NodeConfig):
    host: StrictStr = Field(min_length=1, max_length=255)
    port: StrictInt = Field(default=5432, ge=1, le=65535)
    database: StrictStr = Field(min_length=1, max_length=255)
    username: StrictStr = Field(min_length=1, max_length=255)
    ssl_mode: PostgresSslMode = PostgresSslMode.PREFER
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=900.0)
    max_result_rows: StrictInt = Field(default=10_000, ge=1, le=100_000)

    @field_validator("host", "database", "username")
    @classmethod
    def validate_non_whitespace(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("connection values must not be blank")
        if value != value.strip():
            raise ValueError("connection values must not have surrounding whitespace")
        return value


class ExecuteSqlInput(NodeInput):
    statements: Annotated[
        list[SqlStatement],
        InPort(SQL_STATEMENT, variadic=True, instance_plugs=True),
        Field(
            min_length=1,
            description="Statements executed atomically in saved plug order.",
        ),
    ]


class ExecuteSqlOutput(NodeOutput):
    results: Annotated[
        list[SqlResult],
        OutPort(SQL_RESULT),
        Field(description="One ordered result for each executed statement."),
    ]


class PostgresBatchExecutor(Protocol):
    async def execute(
        self,
        config: ExecuteSqlConfig,
        password: SecretStr,
        statements: list[SqlStatement],
        /,
    ) -> list[SqlResult]: ...


class SqlExecutionError(RuntimeError):
    pass


def build_execute_sql_node(context: PluginRuntimeContext) -> "ExecuteSqlNode":
    from grafy_plugin_sql.sqlalchemy import SqlAlchemyPostgresBatchExecutor

    return ExecuteSqlNode(
        executor=SqlAlchemyPostgresBatchExecutor(),
        node_secrets=context.node_secrets,
    )


@SQL.node(
    operator_id="sql.postgresql.execute",
    version=1,
    title="Execute PostgreSQL",
    factory=build_execute_sql_node,
    required_capabilities=(
        PluginRuntimeCapability.NODE_SECRETS,
        PluginRuntimeCapability.POSTGRESQL_EGRESS,
        PluginRuntimeCapability.UNTRUSTED_SQL,
    ),
    secret_inputs=(
        NodeSecretInput(
            name="password",
            title="Password",
            description="Write-only password for the configured PostgreSQL account.",
            config_dependencies=(
                "host",
                "port",
                "database",
                "username",
                "ssl_mode",
            ),
        ),
    ),
)
@final
class ExecuteSqlNode(Node[ExecuteSqlConfig, ExecuteSqlInput, ExecuteSqlOutput]):
    """Executes ordered PostgreSQL statements in one atomic transaction."""

    def __init__(
        self,
        *,
        executor: PostgresBatchExecutor,
        node_secrets: NodeSecretResolverPort,
    ) -> None:
        self._executor = executor
        self._node_secrets = node_secrets

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: ExecuteSqlConfig,
        inputs: ExecuteSqlInput,
        /,
    ) -> ExecuteSqlOutput:
        dependencies = {
            "host": config.host,
            "port": config.port,
            "database": config.database,
            "username": config.username,
            "ssl_mode": config.ssl_mode.value,
        }
        try:
            password = await self._node_secrets.resolve_secret(
                workspace_id=context.workspace_id,
                project_id=context.project_id,
                graph_id=context.graph_id,
                node_id=context.node_id,
                name="password",
                dependencies=dependencies,
            )
        except Exception as exc:
            raise SqlExecutionError(
                "PostgreSQL execution could not resolve the password for "
                f"node {context.node_id!r}, account {config.username!r}, "
                f"database {config.database!r}, and host {config.host!r}"
            ) from exc

        try:
            results = await self._executor.execute(
                config,
                password,
                inputs.statements,
            )
        except Exception as exc:
            raise SqlExecutionError(
                f"PostgreSQL batch execution failed for node {context.node_id!r}, "
                f"database {config.database!r}, host {config.host!r}, and "
                f"{len(inputs.statements)} statements"
            ) from exc
        if len(results) != len(inputs.statements):
            raise SqlExecutionError(
                "PostgreSQL executor returned "
                f"{len(results)} results for {len(inputs.statements)} statements"
            )
        return ExecuteSqlOutput(results=results)

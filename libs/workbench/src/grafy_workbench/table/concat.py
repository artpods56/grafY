"""Stack multiple tables with compatible or overlapping columns into one table."""

from typing import Annotated, final, override

from pydantic import Field, StringConstraints

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.config_ui import field_ui, when_field_eq
from grafy_core.node_context import UserFacingNodeError
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.table_contracts import Table, TableColumn, TableValue, TableValueType

from grafy_workbench.table.declaration import TABLES

type ColumnId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


def _unify_value_types(
    current: TableValueType, incoming: TableValueType
) -> TableValueType:
    if current == TableValueType.UNKNOWN:
        return incoming
    if incoming == TableValueType.UNKNOWN or current == incoming:
        return current
    if {current, incoming} == {TableValueType.INTEGER, TableValueType.NUMBER}:
        return TableValueType.NUMBER
    return TableValueType.MIXED


class ConcatTablesConfig(NodeConfig):
    add_source_index: bool = Field(
        default=False,
        title="Add source index column",
        description="Record the 1-based index of the input table each row came from.",
        json_schema_extra=field_ui(widget="switch"),
    )
    source_index_column: ColumnId = Field(
        default="source_index",
        title="Source index column ID",
        json_schema_extra=field_ui(
            visible_when=when_field_eq("add_source_index", True)
        ),
    )


class ConcatTablesInput(NodeInput):
    tables: list[Table] = Field(
        min_length=1,
        title="Tables",
        description="Ordered sequence of tables to stack into one table.",
    )


class ConcatTablesOutput(NodeOutput):
    table: Table = Field(title="Combined table")


@TABLES.node(
    operator_id="table.concat",
    version=1,
    title="Concatenate tables",
)
@final
class ConcatTablesNode(Node[ConcatTablesConfig, ConcatTablesInput, ConcatTablesOutput]):
    """Stack rows from an ordered sequence of tables into one table."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: ConcatTablesConfig,
        inputs: ConcatTablesInput,
        /,
    ) -> ConcatTablesOutput:
        del context
        column_order: list[str] = []
        titles: dict[str, str] = {}
        types: dict[str, TableValueType] = {}

        for table in inputs.tables:
            for column in table.columns:
                if column.id not in titles:
                    column_order.append(column.id)
                    titles[column.id] = column.title
                    types[column.id] = column.value_type
                else:
                    types[column.id] = _unify_value_types(
                        types[column.id], column.value_type
                    )

        if config.add_source_index and config.source_index_column in titles:
            raise UserFacingNodeError(
                f"Source index column {config.source_index_column!r} already exists "
                "in the input tables"
            )

        out_columns: list[TableColumn] = []
        if config.add_source_index:
            out_columns.append(
                TableColumn(
                    id=config.source_index_column,
                    title="Source",
                    value_type=TableValueType.INTEGER,
                )
            )
        out_columns.extend(
            TableColumn(id=col_id, title=titles[col_id], value_type=types[col_id])
            for col_id in column_order
        )

        out_rows: list[dict[str, TableValue]] = []
        for source_index, table in enumerate(inputs.tables, start=1):
            for raw_row in table.rows:
                row: dict[str, TableValue] = {}
                if config.add_source_index:
                    row[config.source_index_column] = source_index
                for col_id in column_order:
                    row[col_id] = raw_row.get(col_id)
                out_rows.append(row)

        return ConcatTablesOutput(table=Table(columns=out_columns, rows=out_rows))

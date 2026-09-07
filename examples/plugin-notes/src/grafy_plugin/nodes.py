from typing import Annotated

from pydantic import Field

from grafy_core.nodes import InPort, OutPort
from grafy_core.table_contracts import TABLE_DATA, Table
from grafy_core.plugins import NodeCachePolicy

from grafy_plugin.artifacts import TABLE_SUMMARY
from grafy_plugin.declaration import PLUGIN
from grafy_plugin.models import TableSummary


@PLUGIN.callable_node(
    operator_id="notes.table.summarize",
    version=1,
    title="Summarize table",
    output_name="summary",
    cache_policy=NodeCachePolicy.EXACT,
)
def summarize_table(
    table: Annotated[
        Table,
        InPort(TABLE_DATA),
        Field(description="Builtin table.data@1; this Plugin does not own Table."),
    ],
) -> Annotated[
    TableSummary,
    OutPort(TABLE_SUMMARY),
    Field(description="Plugin-owned notes.table_summary@1."),
]:
    """Count rows and columns on a core Table."""

    return TableSummary(
        row_count=len(table.rows),
        column_count=len(table.columns),
        column_ids=tuple(column.id for column in table.columns),
    )


@PLUGIN.callable_node(
    operator_id="notes.summary.render",
    version=1,
    title="Render table summary",
    output_name="text",
    cache_policy=NodeCachePolicy.EXACT,
)
def render_summary(
    summary: Annotated[
        TableSummary,
        InPort(TABLE_SUMMARY),
        Field(description="The family contract shared by both nodes."),
    ],
    *,
    prefix: Annotated[str, Field(description="Text placed before the summary.")] = "",
) -> str:
    """Render the Plugin-owned summary as core text."""

    columns = ", ".join(summary.column_ids) if summary.column_ids else "(none)"
    return (
        f"{prefix}{summary.row_count} rows, {summary.column_count} columns: {columns}"
    )

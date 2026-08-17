from grafy_core.artifacts import NoConfig
from grafy_core.operators.tables import Table, TableColumn, TableValueType
from grafy_plugin_notes.models import TableSummary
from grafy_plugin_notes.nodes import (
    RenderSummaryInput,
    SummarizeTableInput,
    render_summary,
    summarize_table,
)


async def test_family_nodes_round_trip_a_core_table() -> None:
    table = Table(
        columns=[
            TableColumn(id="name", title="Name", value_type=TableValueType.TEXT),
        ],
        rows=[{"name": "ada"}, {"name": "grace"}],
    )
    summarized = await summarize_table(
        NoConfig(),
        SummarizeTableInput(table=table),
    )
    assert summarized.summary == TableSummary(
        row_count=2,
        column_count=1,
        column_ids=("name",),
    )
    rendered = await render_summary(
        NoConfig(),
        RenderSummaryInput(summary=summarized.summary),
    )
    assert rendered.text.value == "2 rows, 1 columns: name"

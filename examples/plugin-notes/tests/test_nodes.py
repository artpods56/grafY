import os
from pathlib import Path
from typing import cast

import pytest

from grafy_core.domain.plugin_releases import PluginCatalogManifest
from grafy_core.table_contracts import Table, TableColumn, TableValueType
from grafy_plugin import PLUGIN
from grafy_plugin.models import TableSummary
from grafy_plugin.nodes import render_summary, summarize_table


def test_family_nodes_are_directly_callable() -> None:
    table = Table(
        columns=[
            TableColumn(id="name", title="Name", value_type=TableValueType.TEXT),
        ],
        rows=[{"name": "ada"}, {"name": "grace"}],
    )
    summarized = summarize_table(table)
    assert summarized == TableSummary(
        row_count=2,
        column_count=1,
        column_ids=("name",),
    )
    assert render_summary(summarized, prefix="Table: ") == (
        "Table: 2 rows, 1 columns: name"
    )


def test_family_node_contracts_keep_stable_port_names() -> None:
    catalog = PluginCatalogManifest.from_plugin(PLUGIN)
    contracts = {node.operator_id: node for node in catalog.nodes}

    summarize = contracts["notes.table.summarize"]
    assert [port.name for port in summarize.inputs] == ["table"]
    assert summarize.inputs[0].artifact_type is not None
    assert summarize.inputs[0].artifact_type.id == "table.data"
    assert [port.name for port in summarize.outputs] == ["summary"]
    assert summarize.outputs[0].artifact_type is not None
    assert summarize.outputs[0].artifact_type.id == "notes.table_summary"

    render = contracts["notes.summary.render"]
    assert [port.name for port in render.inputs] == ["summary"]
    assert render.inputs[0].artifact_type is not None
    assert render.inputs[0].artifact_type.id == "notes.table_summary"
    properties = cast(dict[str, object], render.config_schema["properties"])
    assert list(properties) == ["prefix"]
    assert cast(dict[str, object], properties["prefix"])["default"] == ""
    assert [port.name for port in render.outputs] == ["text"]
    assert render.outputs[0].artifact_type is not None
    assert render.outputs[0].artifact_type.id == "scalar.text"


def test_publisher_environment_cannot_see_host_secrets() -> None:
    assert "GRAFY_PLUGIN_SENTINEL_SECRET" not in os.environ


@pytest.mark.skipif(
    os.environ.get("GRAFY_PLUGIN_PUBLISHING") != "1",
    reason="only meaningful inside the publisher's verification environment",
)
def test_working_copy_mutations_cannot_reach_the_freeze() -> None:
    init_path = Path("src/grafy_plugin/__init__.py")
    original = init_path.read_text(encoding="utf-8")
    init_path.write_text(
        original + "\nMUTATED_DURING_TESTS = True\n",
        encoding="utf-8",
    )

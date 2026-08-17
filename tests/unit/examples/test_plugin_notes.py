import tomllib
from pathlib import Path
from uuid import uuid4

from grafy_core.artifacts import InMemoryUnitOfWork
from grafy_core.nodes import NodeExecutionContext
from grafy_core.operators.arithmetic import ARITHMETIC
from grafy_core.operators.tables import TABLES, TABLE_DATA
from grafy_core.operators.text import TEXT, TEXT_VALUE
from grafy_core.plugins import PluginOrigin, PluginRegistry
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import ArtifactWriteContext
from grafy_plugin_notes import NOTES, RUNTIME_PROFILE
from grafy_plugin_notes.artifacts import TABLE_SUMMARY
from grafy_plugin_notes.models import TableSummary
from grafy_plugin_notes.persistence import (
    table_summary_resolver,
    table_summary_writer,
)

EXAMPLE_ROOT = Path(__file__).resolve().parents[3] / "examples" / "plugin-notes"


def test_example_plugin_is_a_uv_project_without_a_host_entry_point() -> None:
    metadata = tomllib.loads((EXAMPLE_ROOT / "pyproject.toml").read_text())
    project = metadata["project"]

    assert project["name"] == "grafy-plugin-notes"
    assert project["dependencies"] == ["grafy-core", "pydantic"]
    assert "grafy-plugin-gis" not in project["dependencies"]
    assert "entry-points" not in project
    assert RUNTIME_PROFILE == "python-uv"


def test_notes_family_declares_two_nodes_and_an_owned_type() -> None:
    registry = PluginRegistry()
    registry.install(ARITHMETIC, origin=PluginOrigin.BUILTIN)
    registry.install(TABLES, origin=PluginOrigin.BUILTIN)
    registry.install(TEXT, origin=PluginOrigin.BUILTIN)
    registry.install(NOTES, origin=PluginOrigin.AGENT)
    registry.freeze()

    assert NOTES.slug == "notes"
    operator_ids = {
        registration.key
        for registration in registry.nodes
        if registration.plugin_slug == "notes"
    }
    assert operator_ids == {
        ("notes.table.summarize", 1),
        ("notes.summary.render", 1),
    }
    assert TABLE_SUMMARY.key in {spec.key for spec in registry.artifact_types}
    summarize = registry.node_registration("notes.table.summarize", 1)
    render = registry.node_registration("notes.summary.render", 1)
    assert summarize.node_class.input_contract.ports["table"].accepts == TABLE_DATA.key
    assert (
        summarize.node_class.output_contract.ports["summary"].produces
        == TABLE_SUMMARY.key
    )
    assert (
        render.node_class.input_contract.ports["summary"].accepts == TABLE_SUMMARY.key
    )
    assert render.node_class.output_contract.ports["text"].produces == TEXT_VALUE.key


async def test_plugin_owned_summary_has_writer_and_resolver() -> None:
    workspace_id = uuid4()
    uow = InMemoryUnitOfWork()
    writer = table_summary_writer(uow)
    resolver = table_summary_resolver(uow)
    summary = TableSummary(row_count=2, column_count=1, column_ids=("name",))

    ref = await writer.write(
        summary,
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=workspace_id,
                node_id="notes.table.summarize",
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )
    assert ref.key() == TABLE_SUMMARY.key
    loaded = await resolver.resolve(ref, workspace_id)
    assert loaded == summary

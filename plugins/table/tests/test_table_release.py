from importlib.metadata import requires

from grafy_core.plugins import PluginRegistry
from grafy_plugin_table import TABLES


def test_plugin_declares_only_the_moved_operator() -> None:
    registry = PluginRegistry()
    registry.install(TABLES)
    registry.freeze()

    assert TABLES.slug == "external.table"
    assert {node.key for node in registry.nodes} == {("table.import", 1)}
    assert TABLES.artifact_types == ()
    assert TABLES.artifact_conversions == ()
    assert "grafy-core==0.1.0" in (requires("grafy-plugin-table") or [])

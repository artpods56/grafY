from importlib.metadata import requires

from grafy_core.domain.plugin_releases import PluginCatalogManifest
from grafy_core.plugins import PluginRegistry
from grafy_plugin_table import TABLES


def test_plugin_declares_only_the_moved_operator() -> None:
    registry = PluginRegistry()
    registry.install(TABLES)
    registry.freeze()
    catalog = PluginCatalogManifest.from_plugin(TABLES)

    assert catalog.slug == "external.table"
    assert {node.key for node in registry.nodes} == {("table.import", 1)}
    assert catalog.artifact_types == ()
    assert catalog.artifact_conversions == ()
    assert "grafy-core==0.1.0" in (requires("grafy-plugin-table") or [])

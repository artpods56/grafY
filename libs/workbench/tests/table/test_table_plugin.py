from grafy_core.domain.plugin_releases import PluginCatalogManifest
from grafy_core.plugins import PluginRegistry
from grafy_core.table_contracts import TABLE_DATA
from grafy_workbench.table import TABLES


def test_table_plugin_preserves_catalog_identity_and_freezes() -> None:
    registry = PluginRegistry()
    registry.install(TABLES)
    registry.freeze()
    manifest = PluginCatalogManifest.from_plugin(TABLES)

    assert TABLES.slug == "table"
    assert {artifact.key for artifact in TABLES.artifact_types} == {TABLE_DATA.key}
    assert {(node.operator_id, node.operator_version) for node in manifest.nodes} == {
        ("table.import", 1),
        ("table.fuzzy_match", 1),
        ("table.text.normalize", 1),
    }

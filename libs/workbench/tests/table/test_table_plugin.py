from grafy_core.plugins import PluginRegistry
from grafy_core.table_contracts import TABLE_DATA
from grafy_workbench.table import TABLES


def test_table_plugin_preserves_catalog_identity_and_freezes() -> None:
    registry = PluginRegistry()
    registry.install(TABLES)
    registry.freeze()

    assert TABLES.slug == "table"
    assert {artifact.key for artifact in TABLES.artifact_types} == {TABLE_DATA.key}
    assert TABLES.nodes == ()

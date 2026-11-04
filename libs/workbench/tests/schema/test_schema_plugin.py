from grafy_core.domain.plugin_releases import PluginCatalogManifest
from grafy_core.plugins import PluginRegistry
from grafy_core.schema_contracts import JSON_SCHEMA
from grafy_workbench.schema import SCHEMAS


def test_schema_plugin_preserves_catalog_identity_and_freezes() -> None:
    registry = PluginRegistry()
    registry.install(SCHEMAS)
    registry.freeze()
    manifest = PluginCatalogManifest.from_plugin(SCHEMAS)

    assert SCHEMAS.slug == "schema"
    assert {artifact.key for artifact in SCHEMAS.artifact_types} == {JSON_SCHEMA.key}
    assert {(node.operator_id, node.operator_version) for node in manifest.nodes} == {
        ("schema.builder", 1),
    }

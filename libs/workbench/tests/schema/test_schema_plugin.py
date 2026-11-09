from grafy_core.plugins import PluginRegistry
from grafy_core.schema_contracts import JSON_SCHEMA
from grafy_workbench.schema import SCHEMAS


def test_schema_plugin_preserves_catalog_identity_and_freezes() -> None:
    registry = PluginRegistry()
    registry.install(SCHEMAS)
    registry.freeze()

    assert SCHEMAS.slug == "schema"
    assert {artifact.key for artifact in SCHEMAS.artifact_types} == {JSON_SCHEMA.key}
    assert {node.key for node in registry.nodes} == {
        ("schema.builder", 1),
    }

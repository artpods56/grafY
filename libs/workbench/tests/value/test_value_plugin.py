from grafy_core.artifact_contracts import INTEGER_VALUE
from grafy_core.domain.plugin_releases import PluginCatalogManifest
from grafy_core.plugins import PluginRegistry
from grafy_workbench.value import VALUE


def test_value_plugin_preserves_catalog_identity_and_freezes() -> None:
    registry = PluginRegistry()
    registry.install(VALUE)
    registry.freeze()
    manifest = PluginCatalogManifest.from_plugin(VALUE)

    assert VALUE.slug == "value"
    assert VALUE.artifact_type_dependencies == ()
    assert {artifact.key for artifact in VALUE.artifact_types} == {INTEGER_VALUE.key}
    assert {(node.operator_id, node.operator_version) for node in manifest.nodes} == {
        ("value.integer", 1),
    }

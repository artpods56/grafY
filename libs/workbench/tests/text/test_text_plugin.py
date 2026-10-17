from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.domain.plugin_releases import PluginCatalogManifest
from grafy_core.plugins import PluginRegistry
from grafy_workbench.text import TEXT


def test_text_plugin_preserves_catalog_identity_and_freezes() -> None:
    registry = PluginRegistry()
    registry.install(TEXT)
    registry.freeze()
    manifest = PluginCatalogManifest.from_plugin(TEXT)

    assert TEXT.slug == "text"
    assert TEXT.artifact_type_dependencies == ()
    assert TEXT_VALUE.key in {artifact.key for artifact in TEXT.artifact_types}
    assert {(node.operator_id, node.operator_version) for node in manifest.nodes} == {
        ("text.input", 1),
    }

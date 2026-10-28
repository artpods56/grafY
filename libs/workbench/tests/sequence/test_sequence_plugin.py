from grafy_core.artifact_contracts import INTEGER_VALUE
from grafy_core.domain.plugin_releases import PluginCatalogManifest
from grafy_core.plugins import PluginRegistry
from grafy_workbench.sequence import SEQUENCES


def test_sequence_plugin_preserves_catalog_identity_and_freezes() -> None:
    registry = PluginRegistry()
    registry.install(SEQUENCES)
    registry.freeze()
    manifest = PluginCatalogManifest.from_plugin(SEQUENCES)

    assert SEQUENCES.slug == "sequence"
    assert SEQUENCES.artifact_types == ()
    assert SEQUENCES.artifact_type_dependencies == (INTEGER_VALUE,)
    assert {(node.operator_id, node.operator_version) for node in manifest.nodes} == {
        ("sequence.collect", 1),
        ("sequence.count", 1),
        ("sequence.slice", 1),
        ("sequence.item_at", 1),
    }

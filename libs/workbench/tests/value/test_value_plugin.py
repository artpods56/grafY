from grafy_core.artifact_contracts import INTEGER_VALUE
from grafy_core.plugins import PluginRegistry
from grafy_workbench.value import VALUE


def test_value_plugin_preserves_catalog_identity_and_freezes() -> None:
    registry = PluginRegistry()
    registry.install(VALUE)
    registry.freeze()

    assert VALUE.slug == "value"
    assert VALUE.artifact_type_dependencies == ()
    assert {artifact.key for artifact in VALUE.artifact_types} == {INTEGER_VALUE.key}
    assert {node.key for node in registry.nodes} == {
        ("value.integer", 1),
    }

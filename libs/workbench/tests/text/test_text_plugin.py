from grafy_core.artifact_contracts import HTML_PAGE, TEXT_VALUE
from grafy_core.plugins import PluginRegistry
from grafy_workbench.text import TEXT


def test_text_plugin_preserves_catalog_identity_and_freezes() -> None:
    registry = PluginRegistry()
    registry.install(TEXT)
    registry.freeze()

    assert TEXT.slug == "text"
    assert TEXT.artifact_type_dependencies == ()
    assert {TEXT_VALUE.key, HTML_PAGE.key} <= {
        artifact.key for artifact in TEXT.artifact_types
    }
    assert {node.key for node in registry.nodes} == {
        ("text.input", 1),
    }

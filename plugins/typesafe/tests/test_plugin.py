from importlib.metadata import requires

from grafy_core.plugins import Plugin, PluginRegistry
from grafy_plugin_typesafe.plugin import TYPESAFE


def test_manifest_loader_target_preserves_system_identity_and_freezes() -> None:
    registry = PluginRegistry()
    registry.install(TYPESAFE)
    registry.freeze()

    assert isinstance(TYPESAFE, Plugin)
    assert TYPESAFE.slug == "external.typesafe"
    assert "grafy-core==0.1.0" in (requires("grafy-plugin-typesafe") or [])
    assert {registration.key for registration in TYPESAFE.nodes} == {
        ("typesafe.question", 1),
        ("typesafe.evaluate", 1),
        ("typesafe.decide", 1),
        ("typesafe.score.combine", 1),
    }

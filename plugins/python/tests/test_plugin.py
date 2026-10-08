from importlib.metadata import requires

from grafy_core.plugins import Plugin, PluginRegistry
from grafy_plugin_python.plugin import PYTHON


def test_manifest_loader_target_preserves_system_identity_and_freezes() -> None:
    registry = PluginRegistry()
    registry.install(PYTHON)
    registry.freeze()

    assert isinstance(PYTHON, Plugin)
    assert PYTHON.slug == "external.python"
    assert {registration.key for registration in PYTHON.nodes} == {
        ("python.transform", 1),
        ("python.inspect", 1),
    }
    assert not any(registration.listed for registration in PYTHON.nodes)
    assert "grafy-core==0.1.0" in (requires("grafy-plugin-python") or [])

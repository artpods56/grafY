from importlib.metadata import requires

from grafy_core.plugins import Plugin, PluginRegistry
from grafy_plugin_mistral.plugin import MISTRAL


def test_manifest_loader_target_preserves_system_identity_and_freezes() -> None:
    registry = PluginRegistry()
    registry.install(MISTRAL)
    registry.freeze()

    assert isinstance(MISTRAL, Plugin)
    assert MISTRAL.slug == "external.mistral"
    assert {registration.key for registration in MISTRAL.nodes} == {
        ("mistral.ocr.process", 1),
    }
    assert "grafy-core==0.1.0" in (requires("grafy-plugin-mistral") or [])

    assert registry.declared_artifact_types == ()
    contract = MISTRAL.nodes[0].http_egress
    assert contract is not None
    assert contract.fixed_destinations == ("https://api.mistral.ai",)
    assert contract.configured_inputs == ()
    assert not contract.dynamic_destinations

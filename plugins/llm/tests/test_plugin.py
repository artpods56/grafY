from importlib.metadata import requires

from grafy_core.plugins import Plugin, PluginRegistry
from grafy_plugin_llm.plugin import LLM


def test_manifest_loader_target_preserves_system_identity_and_freezes() -> None:
    registry = PluginRegistry()
    registry.install(LLM)
    registry.freeze()

    assert isinstance(LLM, Plugin)
    assert LLM.slug == "external.llm"
    assert LLM.title == "Language model"
    assert {registration.key for registration in LLM.nodes} == {
        ("llm.ocr.provider", 1),
        ("llm.openai_compatible.chat_completion", 1),
        ("prompt.message.create", 2),
    }
    assert "grafy-core==0.1.0" in (requires("grafy-plugin-llm") or [])

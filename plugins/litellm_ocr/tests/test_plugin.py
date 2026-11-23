from grafy_api.services.families import build_application_registry
from grafy_core.contracts.ocr import CropTextReader, TextBoxDetector
from grafy_plugin_litellm_ocr import LITELLM_OCR


def test_catalog_registers_the_litellm_providers_with_vault_credentials() -> None:
    registry = build_application_registry()
    assert LITELLM_OCR.slug == "external.litellm_ocr"
    assert {
        contract.protocol for contract in LITELLM_OCR.service_contract_dependencies
    } == {
        TextBoxDetector,
        CropTextReader,
    }
    assert {node.key for node in LITELLM_OCR.nodes} == {
        ("ocr.craft_provider", 1),
        ("ocr.paddle_cyrillic_provider", 1),
    }
    for node in LITELLM_OCR.nodes:
        assert registry.node_registration(*node.key).plugin_slug == LITELLM_OCR.slug
        assert [
            (secret.name, secret.provider_kind) for secret in node.secret_inputs
        ] == [("api_key", "litellm")]

from grafy_core.contracts.ocr import CropTextReader, TextBoxDetector
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.plugins import Plugin

LITELLM_OCR = Plugin(
    slug="external.litellm_ocr",
    title="LiteLLM OCR",
    capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
)
LITELLM_OCR.register_service_contract_dependency(TextBoxDetector)
LITELLM_OCR.register_service_contract_dependency(CropTextReader)

from grafy_core.contracts.ocr import DocumentOcr
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.plugins import Plugin

MISTRAL = Plugin(
    slug="external.mistral",
    title="Mistral",
    capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
)
MISTRAL.register_service_contract_dependency(DocumentOcr)

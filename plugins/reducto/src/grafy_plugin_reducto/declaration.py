from grafy_core.contracts.ocr import DocumentOcr
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.plugins import Plugin

REDUCTO = Plugin(
    slug="external.reducto",
    title="Reducto",
    capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
)
REDUCTO.register_service_contract_dependency(DocumentOcr)

from grafy_core.artifact_contracts import RASTER_IMAGE, TEXT_VALUE
from grafy_core.contracts.ocr import DocumentOcr
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.plugins import Plugin
from grafy_core.schema_contracts import JSON_SCHEMA


LLM = Plugin(
    slug="external.llm",
    title="Language model",
    capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
)
LLM.register_artifact_type_dependency(TEXT_VALUE)
LLM.register_artifact_type_dependency(RASTER_IMAGE)
LLM.register_artifact_type_dependency(JSON_SCHEMA)
LLM.register_service_contract_dependency(DocumentOcr)

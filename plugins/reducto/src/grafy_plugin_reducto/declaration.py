from grafy_core.artifact_contracts import (
    MARKDOWN,
    RASTER_IMAGE,
    TEXT_VALUE,
)
from grafy_core.contracts.ocr import DocumentOcr
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.file_contracts import PDF_FILE
from grafy_core.plugins import Plugin
from grafy_core.table_contracts import TABLE_DATA

REDUCTO = Plugin(
    slug="external.reducto",
    title="Reducto",
    capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
)
REDUCTO.register_artifact_type_dependency(TEXT_VALUE)
REDUCTO.register_artifact_type_dependency(RASTER_IMAGE)
REDUCTO.register_artifact_type_dependency(PDF_FILE)
REDUCTO.register_artifact_type_dependency(TABLE_DATA)
REDUCTO.register_artifact_type_dependency(MARKDOWN)
REDUCTO.register_service_contract_dependency(DocumentOcr)

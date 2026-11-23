from grafy_core.contracts.ocr import CropTextReader, TextBoxDetector
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.plugins import Plugin
from grafy_core.file_contracts import TIFF_FILE
from grafy_core.table_contracts import TABLE_DATA

MAP_TOPONYMS = Plugin(
    slug="external.map_toponyms",
    title="Historical Map Toponyms",
    capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
)
MAP_TOPONYMS.register_service_contract_dependency(TextBoxDetector)
MAP_TOPONYMS.register_service_contract_dependency(CropTextReader)
MAP_TOPONYMS.register_artifact_type_dependency(TIFF_FILE)
MAP_TOPONYMS.register_artifact_type_dependency(TABLE_DATA)

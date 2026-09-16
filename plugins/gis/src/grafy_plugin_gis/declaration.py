from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.file_contracts import GEOJSON_FILE, JSON_FILE, TIFF_FILE
from grafy_core.plugins import Plugin
from grafy_core.table_contracts import TABLE_DATA


GIS = Plugin(
    slug="external.gis",
    title="GIS",
    capabilities=(
        PluginRuntimeCapability.NATIVE_GDAL,
        PluginRuntimeCapability.NETWORK_EGRESS,
    ),
)
GIS.register_artifact_type_dependency(TABLE_DATA)
GIS.register_artifact_type_dependency(GEOJSON_FILE)
GIS.register_artifact_type_dependency(JSON_FILE)
GIS.register_artifact_type_dependency(TIFF_FILE)

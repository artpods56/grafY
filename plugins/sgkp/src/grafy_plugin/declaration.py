from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.file_contracts import JSON_FILE
from grafy_core.plugins import Plugin
from grafy_core.table_contracts import TABLE_DATA


PLUGIN = Plugin(
    slug="sgkp",
    title="SGKP",
    capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
)
PLUGIN.register_artifact_type_dependency(TABLE_DATA)
PLUGIN.register_artifact_type_dependency(JSON_FILE)

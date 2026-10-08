from grafy_core.artifact_contracts import RASTER_IMAGE, TEXT_VALUE
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.plugins import Plugin
from grafy_core.schema_contracts import JSON_SCHEMA


MISTRAL = Plugin(
    slug="external.mistral",
    title="Mistral",
    capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
)
MISTRAL.register_artifact_type_dependency(TEXT_VALUE)
MISTRAL.register_artifact_type_dependency(RASTER_IMAGE)
MISTRAL.register_artifact_type_dependency(JSON_SCHEMA)

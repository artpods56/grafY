from grafy_core.artifact_contracts import (
    IMAGE_REGIONS,
    RASTER_IMAGE,
    TEXT_VALUE,
    MARKDOWN,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.plugins import Plugin
from grafy_core.table_contracts import TABLE_DATA


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
MISTRAL.register_artifact_type_dependency(TABLE_DATA)
MISTRAL.register_artifact_type_dependency(IMAGE_REGIONS)
MISTRAL.register_artifact_type_dependency(MARKDOWN)

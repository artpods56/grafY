from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.plugins import Plugin


TYPESAFE = Plugin(
    slug="external.typesafe",
    title="TypeSafe",
    capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
)
TYPESAFE.register_artifact_type_dependency(TEXT_VALUE)

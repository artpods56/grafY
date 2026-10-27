"""The deployment-owned node families, shared by every API environment."""

from grafy_core.plugins import Plugin, PluginRegistry
from grafy_plugin_gis.plugin import GIS
from grafy_plugin_image.plugin import IMAGES
from grafy_plugin_llm.plugin import LLM
from grafy_plugin_mistral.plugin import MISTRAL
from grafy_plugin_table.plugin import TABLES
from grafy_plugin_typesafe.plugin import TYPESAFE
from grafy_workbench.catalog import BUILTIN_FAMILIES, build_builtin_registry


# SQL stays unavailable until its in-process safety review is complete.
APPLICATION_FAMILIES: tuple[Plugin, ...] = (
    *BUILTIN_FAMILIES,
    GIS,
    IMAGES,
    TABLES,
    LLM,
    MISTRAL,
    TYPESAFE,
)


def build_application_registry() -> PluginRegistry:
    return build_builtin_registry(APPLICATION_FAMILIES)

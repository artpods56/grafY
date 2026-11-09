"""App-owned builtin operators and their supported versions."""

from collections.abc import Iterable

from grafy_core.plugins import (
    Plugin,
    PluginRegistry,
)

from grafy_workbench.file import FILES
from grafy_workbench.image import IMAGES
from grafy_workbench.schema import SCHEMAS
from grafy_workbench.sequence import SEQUENCES
from grafy_workbench.table import TABLES
from grafy_workbench.text import TEXT
from grafy_workbench.value import VALUE


BUILTIN_FAMILIES: tuple[Plugin, ...] = (
    IMAGES,
    SEQUENCES,
    VALUE,
    TEXT,
    SCHEMAS,
    TABLES,
    FILES,
)


def build_builtin_registry(
    families: Iterable[Plugin] = BUILTIN_FAMILIES,
) -> PluginRegistry:
    registry = PluginRegistry()
    for plugin in families:
        registry.install(plugin)
    registry.freeze()
    return registry

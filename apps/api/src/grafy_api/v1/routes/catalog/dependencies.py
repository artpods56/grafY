from typing import Annotated

from fastapi import Depends, Request

from grafy_core.plugins import PluginRegistry

from grafy_api.app_state import get_resources


def plugin_registry(request: Request) -> PluginRegistry:
    return get_resources(request.app).workbench.plugin_registry


PluginRegistryDependency = Annotated[
    PluginRegistry,
    Depends(plugin_registry),
]


__all__ = ["PluginRegistryDependency", "plugin_registry"]

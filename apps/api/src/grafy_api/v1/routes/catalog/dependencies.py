from typing import Annotated

from fastapi import Depends, Request

from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.plugins import PluginRegistry
from grafy_core.ports.modules import GraphModuleExecutorPort

from grafy_api.app_state import get_resources


def plugin_registry(request: Request) -> PluginRegistry:
    return get_resources(request.app).workbench.plugin_registry


PluginRegistryDependency = Annotated[
    PluginRegistry,
    Depends(plugin_registry),
]


def plugin_release_service(request: Request) -> PluginReleaseService | None:
    return get_resources(request.app).workbench.plugin_releases


PluginReleaseServiceDependency = Annotated[
    PluginReleaseService | None,
    Depends(plugin_release_service),
]


def graph_module_executor(request: Request) -> GraphModuleExecutorPort:
    return get_resources(request.app).workbench.run_graph


GraphModuleExecutorDependency = Annotated[
    GraphModuleExecutorPort,
    Depends(graph_module_executor),
]


__all__ = [
    "GraphModuleExecutorDependency",
    "PluginRegistryDependency",
    "PluginReleaseServiceDependency",
    "graph_module_executor",
    "plugin_registry",
    "plugin_release_service",
]

from typing import Annotated

from fastapi import Depends, Request

from grafy_core.application.agent_authoring import AgentAuthoringService
from grafy_core.plugins import PluginRegistry
from grafy_core.ports.modules import GraphModuleExecutorPort

from grafy_api.app_state import get_resources

from .services import GraphModuleCatalog


def plugin_registry(request: Request) -> PluginRegistry:
    return get_resources(request.app).plugin_registry


PluginRegistryDependency = Annotated[
    PluginRegistry,
    Depends(plugin_registry),
]


def graph_module_catalog(request: Request) -> GraphModuleCatalog:
    return get_resources(request.app).graph_modules


GraphModuleCatalogDependency = Annotated[
    GraphModuleCatalog,
    Depends(graph_module_catalog),
]


def graph_module_executor(request: Request) -> GraphModuleExecutorPort:
    return get_resources(request.app).run_graph


GraphModuleExecutorDependency = Annotated[
    GraphModuleExecutorPort,
    Depends(graph_module_executor),
]


def agent_authoring_catalog(request: Request) -> AgentAuthoringService:
    return get_resources(request.app).agent_authoring


AgentAuthoringCatalogDependency = Annotated[
    AgentAuthoringService,
    Depends(agent_authoring_catalog),
]


def generated_execution_available(request: Request) -> bool:
    return get_resources(request.app).generated_executor is not None


GeneratedExecutionAvailabilityDependency = Annotated[
    bool,
    Depends(generated_execution_available),
]


__all__ = [
    "AgentAuthoringCatalogDependency",
    "GraphModuleCatalogDependency",
    "GraphModuleExecutorDependency",
    "GeneratedExecutionAvailabilityDependency",
    "PluginRegistryDependency",
    "agent_authoring_catalog",
    "graph_module_catalog",
    "graph_module_executor",
    "generated_execution_available",
    "plugin_registry",
]

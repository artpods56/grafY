from typing import Annotated

from fastapi import Depends, Request

from grafy_core.plugins import PluginRegistry

from grafy_api.app_state import get_identity, get_resources
from grafy_api.catalog_packs import CatalogPolicy


def plugin_registry(request: Request) -> PluginRegistry:
    return get_resources(request.app).workbench.plugin_registry


PluginRegistryDependency = Annotated[
    PluginRegistry,
    Depends(plugin_registry),
]


def catalog_policy(request: Request) -> CatalogPolicy:
    return get_identity(request.app).catalog_policy


CatalogPolicyDependency = Annotated[CatalogPolicy, Depends(catalog_policy)]

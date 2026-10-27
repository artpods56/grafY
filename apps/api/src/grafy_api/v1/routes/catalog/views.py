from fastapi import APIRouter

from grafy_core.domain.identity import WorkspaceCapability

from grafy_api.catalog import CatalogSnapshot
from grafy_api.v1.routes.auth.dependencies import require_workspace_capability

from .dependencies import (
    GraphModuleExecutorDependency,
    PluginRegistryDependency,
)
from grafy_api.v1.routes.modules.dependencies import ModuleLibraryDependency

from .models import NodeRegistryResponse


router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["workbench"])


@router.get("/nodes", response_model=NodeRegistryResponse)
async def list_nodes(
    registry: PluginRegistryDependency,
    modules: ModuleLibraryDependency,
    module_executor: GraphModuleExecutorDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_GRAPH),
) -> NodeRegistryResponse:
    module_listing = await modules.catalog_definitions(access.workspace_id)
    return NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(
            registry,
            module_listing,
            [],
        ),
        module_executor,
    )


__all__ = ["router"]

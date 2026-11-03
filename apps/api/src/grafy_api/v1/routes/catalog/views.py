from fastapi import APIRouter

from grafy_core.domain.identity import WorkspaceCapability

from grafy_api.catalog import CatalogSnapshot
from grafy_api.v1.routes.auth.dependencies import require_workspace_capability

from .dependencies import (
    PluginRegistryDependency,
)

from .models import NodeRegistryResponse


router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["workbench"])


@router.get("/nodes", response_model=NodeRegistryResponse)
async def list_nodes(
    registry: PluginRegistryDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
) -> NodeRegistryResponse:
    return NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(registry),
    )


__all__ = ["router"]

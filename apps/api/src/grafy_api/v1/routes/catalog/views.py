from fastapi import APIRouter, Request

from grafy_core.domain.identity import WorkspaceCapability

from grafy_api.catalog import CatalogSnapshot
from grafy_api.app_state import get_resources
from grafy_api.v1.routes.auth.dependencies import require_workspace_capability

from .dependencies import (
    GraphModuleExecutorDependency,
    PluginReleaseServiceDependency,
    PluginRegistryDependency,
)
from grafy_api.v1.routes.modules.dependencies import ModuleLibraryDependency

from .models import NodeRegistryResponse
from grafy_api.catalog import PluginCatalogReleaseState


router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["workbench"])


@router.get("/nodes", response_model=NodeRegistryResponse)
async def list_nodes(
    request: Request,
    registry: PluginRegistryDependency,
    modules: ModuleLibraryDependency,
    plugin_releases: PluginReleaseServiceDependency,
    module_executor: GraphModuleExecutorDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_GRAPH),
) -> NodeRegistryResponse:
    resources = get_resources(request.app)
    module_listing = await modules.catalog_definitions(access.workspace_id)
    catalog_releases = (
        []
        if plugin_releases is None
        else await plugin_releases.list_catalog(access.workspace_id)
    )
    releases = [entry.release for entry in catalog_releases]
    release_states = {
        entry.release.id: PluginCatalogReleaseState(
            selection=entry.selection, revocation=entry.revocation
        )
        for entry in catalog_releases
    }
    return NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(
            registry,
            module_listing,
            releases,
            workspace_id=access.workspace_id,
            release_admission=resources.release_admission,
            plugin_release_states=release_states,
        ),
        module_executor,
    )


__all__ = ["router"]

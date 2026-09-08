from uuid import UUID

from fastapi import APIRouter, Request

from grafy_core.domain.identity import WorkspaceCapability
from grafy_core.domain.plugin_releases import PluginReleaseScope

from grafy_api.app_state import get_resources
from grafy_api.v1.routes.auth.dependencies import require_workspace_capability

from .dependencies import (
    GraphModuleExecutorDependency,
    PluginReleaseServiceDependency,
    PluginRegistryDependency,
)
from grafy_api.v1.routes.modules.dependencies import ModuleLibraryDependency

from .models import NodeRegistryResponse, PluginCatalogReleaseState


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
    system_plugin_releases = (
        [] if plugin_releases is None else await plugin_releases.list_current_system()
    )
    workspace_plugin_releases = (
        []
        if plugin_releases is None
        else await plugin_releases.list_current(access.workspace_id)
    )
    releases = [*system_plugin_releases, *workspace_plugin_releases]
    release_states: dict[UUID, PluginCatalogReleaseState] = {}
    if plugin_releases is not None:
        for release in releases:
            selection = await plugin_releases.get_selection(
                access.workspace_id,
                release.slug,
                scope=release.scope,
            )
            if release.scope is PluginReleaseScope.SYSTEM:
                revocation = await plugin_releases.get_system_revocation(
                    slug=release.slug,
                    revision=release.revision,
                )
            else:
                revocation = await plugin_releases.get_revocation(
                    workspace_id=access.workspace_id,
                    slug=release.slug,
                    revision=release.revision,
                )
            release_states[release.id] = PluginCatalogReleaseState(
                selection=selection,
                revocation=revocation,
            )
    return NodeRegistryResponse.from_registry(
        registry,
        module_listing,
        module_executor,
        releases,
        workspace_id=access.workspace_id,
        release_admission=resources.release_admission,
        plugin_release_states=release_states,
    )


__all__ = ["router"]

from fastapi import APIRouter

from grafy_core.domain.identity import WorkspaceCapability

from grafy_api.v1.routes.auth.dependencies import require_workspace_capability

from .dependencies import (
    AgentAuthoringCatalogDependency,
    GeneratedExecutionAvailabilityDependency,
    GraphModuleCatalogDependency,
    GraphModuleExecutorDependency,
    PluginRegistryDependency,
)
from .models import NodeRegistryResponse


router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["workbench"])


@router.get("/nodes", response_model=NodeRegistryResponse)
async def list_nodes(
    registry: PluginRegistryDependency,
    modules: GraphModuleCatalogDependency,
    module_executor: GraphModuleExecutorDependency,
    authoring: AgentAuthoringCatalogDependency,
    generated_execution_available: GeneratedExecutionAvailabilityDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_GRAPH),
) -> NodeRegistryResponse:
    module_listing = await modules.list(access.workspace_id)
    drafts = await authoring.list_drafts(access.workspace_id)
    releases = await authoring.list_releases(access.workspace_id)
    return NodeRegistryResponse.from_registry(
        registry,
        module_listing,
        module_executor,
        agent_drafts=drafts,
        agent_releases=releases,
        generated_execution_available=generated_execution_available,
    )


__all__ = ["router"]

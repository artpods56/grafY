from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.identity import WorkspaceCapability
from grafy_core.domain.module_library import ModuleLibraryError
from grafy_core.domain.modules import GraphModuleDefinition, GraphModuleReference

from grafy_api.v1.routes.auth.dependencies import (
    require_workspace_capability,
)
from grafy_core.application.modules import ModuleLibraryService
from grafy_core.domain.modules import GraphModuleDefinitionError
from grafy_api.v1.routes.modules.dependencies import ModuleLibraryDependency
from grafy_api.v1.routes.modules.models import (
    ImportModuleReleaseRequest,
    ImportModuleReleaseResponse,
    ModuleListResponse,
    ModuleResponse,
    PublishModuleReleaseRequest,
)


router = APIRouter(prefix="/workspaces/{workspace_id}/modules", tags=["modules"])


async def _definition_for_module(
    service: ModuleLibraryService,
    *,
    workspace_id: UUID,
    source_graph_id: UUID,
    revision: int | None,
) -> GraphModuleDefinition | None:
    if revision is None:
        return None
    try:
        return await service.resolve_definition(
            GraphModuleReference(graph_id=source_graph_id, revision=revision),
            workspace_id=workspace_id,
        )
    except (NotFoundError, GraphModuleDefinitionError):
        return None


@router.get("", response_model=ModuleListResponse)
async def list_modules(
    service: ModuleLibraryDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_GRAPH),
) -> ModuleListResponse:
    modules = await service.list_library(access.workspace_id)
    responses: list[ModuleResponse] = []
    for module in modules:
        releases = await service.list_releases(access.workspace_id, module.id)
        definition = await _definition_for_module(
            service,
            workspace_id=access.workspace_id,
            source_graph_id=module.source_graph_id,
            revision=module.current_library_release,
        )
        responses.append(
            ModuleResponse.from_module(
                module,
                releases=releases,
                definition=definition,
            )
        )
    return ModuleListResponse(modules=responses)


@router.get("/{module_id}", response_model=ModuleResponse)
async def get_module(
    module_id: UUID,
    service: ModuleLibraryDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_GRAPH),
) -> ModuleResponse:
    try:
        module = await service.get(access.workspace_id, module_id)
        releases = await service.list_releases(access.workspace_id, module_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    definition = await _definition_for_module(
        service,
        workspace_id=access.workspace_id,
        source_graph_id=module.source_graph_id,
        revision=module.current_library_release,
    )
    return ModuleResponse.from_module(
        module,
        releases=releases,
        definition=definition,
    )


@router.post(
    "/publish",
    response_model=ModuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def publish_module_release(
    body: PublishModuleReleaseRequest,
    service: ModuleLibraryDependency,
    access: require_workspace_capability(WorkspaceCapability.PUBLISH_MODULE),
) -> ModuleResponse:
    try:
        module, _release, definition = await service.publish_release(
            actor=access.actor,
            workspace_id=access.workspace_id,
            source_graph_id=body.source_graph_id,
            revision=body.revision,
            name=body.name,
            description=body.description,
        )
        releases = await service.list_releases(access.workspace_id, module.id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ModuleLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ModuleResponse.from_module(
        module,
        releases=releases,
        definition=definition,
    )


@router.post("/{module_id}/deprecate", response_model=ModuleResponse)
async def deprecate_module(
    module_id: UUID,
    service: ModuleLibraryDependency,
    access: require_workspace_capability(WorkspaceCapability.MANAGE_MODULE_LIBRARY),
) -> ModuleResponse:
    try:
        module = await service.deprecate(
            actor=access.actor,
            workspace_id=access.workspace_id,
            module_id=module_id,
        )
        releases = await service.list_releases(access.workspace_id, module_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ModuleLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    definition = await _definition_for_module(
        service,
        workspace_id=access.workspace_id,
        source_graph_id=module.source_graph_id,
        revision=module.current_library_release,
    )
    return ModuleResponse.from_module(
        module,
        releases=releases,
        definition=definition,
    )


@router.post("/{module_id}/withdraw", response_model=ModuleResponse)
async def withdraw_module(
    module_id: UUID,
    service: ModuleLibraryDependency,
    access: require_workspace_capability(WorkspaceCapability.MANAGE_MODULE_LIBRARY),
) -> ModuleResponse:
    try:
        module = await service.withdraw(
            actor=access.actor,
            workspace_id=access.workspace_id,
            module_id=module_id,
        )
        releases = await service.list_releases(access.workspace_id, module_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ModuleLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ModuleResponse.from_module(module, releases=releases)


@router.post(
    "/import",
    response_model=ImportModuleReleaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_module_release(
    body: ImportModuleReleaseRequest,
    service: ModuleLibraryDependency,
    access: require_workspace_capability(WorkspaceCapability.CREATE_GRAPH),
) -> ImportModuleReleaseResponse:
    if body.source_workspace_id == access.workspace_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "Import into the same workspace is not supported; "
                "publish locally instead"
            ),
        )
    try:
        graph, module, release, definition = await service.import_release(
            actor=access.actor,
            source_workspace_id=body.source_workspace_id,
            source_module_id=body.source_module_id,
            source_revision=body.revision,
            destination_workspace_id=access.workspace_id,
            name=body.name,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ModuleLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ImportModuleReleaseResponse.from_import(
        graph,
        module,
        releases=[release],
        definition=definition,
    )

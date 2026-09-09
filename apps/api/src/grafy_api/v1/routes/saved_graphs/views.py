from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from grafy_core.domain.collaboration import (
    CommandReceiptOutcome,
    ReplaceDocumentCommand,
)
from grafy_core.domain.errors import (
    CollaborationActiveExecutionError,
    CollaborationCommandRejectedError,
    CollaborationHeadConflictError,
    CollaborationIdempotencyMismatchError,
    CollaborationUncheckpointedError,
    GraphFolderNameConflictError,
    MissingCollaborativeHeadError,
    NotFoundError,
    SavedGraphRevisionConflictError,
)
from grafy_core.domain.identity import ActorContext, WorkspaceCapability

from grafy_api.app_state import get_resources
from grafy_api.realtime.publish import (
    close_graph_room,
    publish_accepted_command,
    publish_epoch_reset,
)
from grafy_api.v1.routes.auth.dependencies import (
    IdentityUnitOfWorkFactoryDependency,
    browser_actor,
    require_workspace_capability,
)

from .dependencies import CollaborationDependency, SavedGraphDependency
from .models import (
    AssignGraphFolderRequest,
    CheckpointGraphRequest,
    CheckpointGraphResponse,
    CollaborativeHeadResponse,
    CopyExactHeadRequest,
    CreateSavedGraphRequest,
    GraphBrowserListResponse,
    GraphCommandReceiptResponse,
    GraphFolderListResponse,
    GraphFolderResponse,
    GraphFolderWriteRequest,
    GraphOrganizationResponse,
    SavedGraphListResponse,
    SavedGraphResponse,
    SubmitGraphCommandRequest,
    SubmitGraphCommandResponse,
    UpdateSavedGraphRequest,
    UserGraphStateResponse,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/graphs", tags=["saved graphs"])
browser_router = APIRouter(prefix="/me/graphs", tags=["graph browser"])
folder_router = APIRouter(
    prefix="/workspaces/{workspace_id}/graph-folders",
    tags=["graph folders"],
)


@browser_router.get("", response_model=GraphBrowserListResponse)
async def list_accessible_graphs(
    service: SavedGraphDependency,
    actor: Annotated[ActorContext, Depends(browser_actor)],
) -> GraphBrowserListResponse:
    return GraphBrowserListResponse.from_items(await service.list_accessible(actor))


@folder_router.get("", response_model=GraphFolderListResponse)
async def list_graph_folders(
    service: SavedGraphDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_GRAPH),
) -> GraphFolderListResponse:
    folders = await service.list_folders(
        actor=access.actor,
        workspace_id=access.workspace_id,
    )
    return GraphFolderListResponse.from_folders(folders)


@folder_router.post(
    "",
    response_model=GraphFolderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_graph_folder(
    request: GraphFolderWriteRequest,
    service: SavedGraphDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> GraphFolderResponse:
    try:
        folder = await service.create_folder(
            actor=access.actor,
            workspace_id=access.workspace_id,
            name=request.name,
        )
    except GraphFolderNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GraphFolderResponse.from_folder(folder)


@folder_router.patch("/{folder_id}", response_model=GraphFolderResponse)
async def rename_graph_folder(
    folder_id: UUID,
    request: GraphFolderWriteRequest,
    service: SavedGraphDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> GraphFolderResponse:
    try:
        folder = await service.rename_folder(
            actor=access.actor,
            workspace_id=access.workspace_id,
            folder_id=folder_id,
            name=request.name,
        )
    except GraphFolderNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GraphFolderResponse.from_folder(folder)


@folder_router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_graph_folder(
    folder_id: UUID,
    service: SavedGraphDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> Response:
    await service.delete_folder(
        actor=access.actor,
        workspace_id=access.workspace_id,
        folder_id=folder_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=SavedGraphListResponse)
async def list_saved_graphs(
    service: SavedGraphDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_GRAPH),
) -> SavedGraphListResponse:
    graphs = await service.list(access.workspace_id)
    return SavedGraphListResponse.from_graphs(graphs)


@router.put("/{graph_id}/folder", response_model=GraphOrganizationResponse)
async def assign_graph_folder(
    graph_id: UUID,
    request: AssignGraphFolderRequest,
    service: SavedGraphDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> GraphOrganizationResponse:
    organization = await service.assign_folder(
        actor=access.actor,
        workspace_id=access.workspace_id,
        graph_id=graph_id,
        folder_id=request.folder_id,
    )
    return GraphOrganizationResponse.from_organization(organization)


@router.put("/{graph_id}/archive", response_model=GraphOrganizationResponse)
async def archive_graph(
    graph_id: UUID,
    service: SavedGraphDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> GraphOrganizationResponse:
    organization = await service.archive(
        actor=access.actor,
        workspace_id=access.workspace_id,
        graph_id=graph_id,
    )
    return GraphOrganizationResponse.from_organization(organization)


@router.delete("/{graph_id}/archive", response_model=GraphOrganizationResponse)
async def restore_graph(
    graph_id: UUID,
    service: SavedGraphDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> GraphOrganizationResponse:
    organization = await service.restore(
        actor=access.actor,
        workspace_id=access.workspace_id,
        graph_id=graph_id,
    )
    return GraphOrganizationResponse.from_organization(organization)


@router.put("/{graph_id}/star", response_model=UserGraphStateResponse)
async def star_graph(
    graph_id: UUID,
    service: SavedGraphDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_GRAPH),
) -> UserGraphStateResponse:
    state = await service.set_starred(
        actor=access.actor,
        workspace_id=access.workspace_id,
        graph_id=graph_id,
        starred=True,
    )
    return UserGraphStateResponse.from_state(state)


@router.delete("/{graph_id}/star", response_model=UserGraphStateResponse)
async def unstar_graph(
    graph_id: UUID,
    service: SavedGraphDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_GRAPH),
) -> UserGraphStateResponse:
    state = await service.set_starred(
        actor=access.actor,
        workspace_id=access.workspace_id,
        graph_id=graph_id,
        starred=False,
    )
    return UserGraphStateResponse.from_state(state)


@router.post("/{graph_id}/opened", response_model=UserGraphStateResponse)
async def record_graph_open(
    graph_id: UUID,
    service: SavedGraphDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_GRAPH),
) -> UserGraphStateResponse:
    state = await service.record_open(
        actor=access.actor,
        workspace_id=access.workspace_id,
        graph_id=graph_id,
    )
    return UserGraphStateResponse.from_state(state)


@router.post(
    "",
    response_model=SavedGraphResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_saved_graph(
    request: CreateSavedGraphRequest,
    collaboration: CollaborationDependency,
    access: require_workspace_capability(WorkspaceCapability.CREATE_GRAPH),
) -> SavedGraphResponse:
    graph, _, _ = await collaboration.bootstrap_graph(
        actor=access.actor,
        workspace_id=access.workspace_id,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(
            name=request.name,
            document=request.document,
        ),
    )
    return SavedGraphResponse.from_graph(graph)


@router.post(
    "/copies",
    response_model=SavedGraphResponse,
    status_code=status.HTTP_201_CREATED,
)
async def copy_exact_head(
    request: CopyExactHeadRequest,
    collaboration: CollaborationDependency,
    access: require_workspace_capability(WorkspaceCapability.CREATE_GRAPH),
) -> SavedGraphResponse:
    try:
        graph, _, _ = await collaboration.copy_exact_head(
            actor=access.actor,
            source_workspace_id=request.source_workspace_id,
            source_graph_id=request.source_graph_id,
            target_workspace_id=access.workspace_id,
            expected_room_epoch=request.expected_room_epoch,
            expected_sequence=request.expected_sequence,
            command_id=request.command_id,
            name=request.name,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingCollaborativeHeadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CollaborationCommandRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (
        CollaborationHeadConflictError,
        CollaborationIdempotencyMismatchError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SavedGraphResponse.from_graph(graph)


@router.get("/{graph_id}", response_model=SavedGraphResponse)
async def get_saved_graph(
    graph_id: UUID,
    service: SavedGraphDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_GRAPH),
) -> SavedGraphResponse:
    try:
        graph = await service.get(access.workspace_id, graph_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SavedGraphResponse.from_graph(graph)


@router.get("/{graph_id}/head", response_model=CollaborativeHeadResponse)
async def get_collaborative_head(
    graph_id: UUID,
    collaboration: CollaborationDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_GRAPH),
) -> CollaborativeHeadResponse:
    try:
        head = await collaboration.get_head(
            actor=access.actor,
            workspace_id=access.workspace_id,
            graph_id=graph_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingCollaborativeHeadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CollaborativeHeadResponse.from_head(head)


@router.post(
    "/{graph_id}/commands",
    response_model=SubmitGraphCommandResponse,
)
async def submit_graph_command(
    graph_id: UUID,
    request: SubmitGraphCommandRequest,
    http_request: Request,
    collaboration: CollaborationDependency,
    uow_factory: IdentityUnitOfWorkFactoryDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> SubmitGraphCommandResponse:
    try:
        head, receipt = await collaboration.accept_command(
            actor=access.actor,
            workspace_id=access.workspace_id,
            graph_id=graph_id,
            command_id=request.command_id,
            observed_sequence=request.observed_sequence,
            observed_room_epoch=request.room_epoch,
            command=request.command,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingCollaborativeHeadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CollaborationCommandRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (
        CollaborationHeadConflictError,
        CollaborationIdempotencyMismatchError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Idempotent retries return the original receipt over HTTP and must not
    # rebroadcast an accepted command that peers already applied.
    if receipt.outcome is not CommandReceiptOutcome.IDEMPOTENT_REPLAY:
        await publish_accepted_command(
            get_resources(http_request.app).graph_room_hub,
            actor=access.actor,
            workspace_id=access.workspace_id,
            graph_id=graph_id,
            command=request.command,
            receipt=receipt,
            uow_factory=uow_factory,
        )
    return SubmitGraphCommandResponse(
        head=CollaborativeHeadResponse.from_head(head),
        receipt=GraphCommandReceiptResponse.from_receipt(receipt),
    )


@router.post(
    "/{graph_id}/checkpoint",
    response_model=CheckpointGraphResponse,
)
async def checkpoint_graph(
    graph_id: UUID,
    request: CheckpointGraphRequest,
    collaboration: CollaborationDependency,
    access: require_workspace_capability(WorkspaceCapability.CHECKPOINT_GRAPH),
) -> CheckpointGraphResponse:
    try:
        head, revision = await collaboration.checkpoint(
            actor=access.actor,
            workspace_id=access.workspace_id,
            graph_id=graph_id,
            expected_sequence=request.expected_sequence,
            expected_room_epoch=request.expected_room_epoch,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingCollaborativeHeadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        CollaborationHeadConflictError,
        SavedGraphRevisionConflictError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CheckpointGraphResponse(
        head=CollaborativeHeadResponse.from_head(head),
        saved_revision=revision,
    )


@router.put("/{graph_id}", response_model=SavedGraphResponse)
async def update_saved_graph(
    graph_id: UUID,
    request: UpdateSavedGraphRequest,
    http_request: Request,
    collaboration: CollaborationDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> SavedGraphResponse:
    try:
        graph, head = await collaboration.replace_complete_document(
            actor=access.actor,
            workspace_id=access.workspace_id,
            graph_id=graph_id,
            name=request.name,
            document=request.document,
            expected_revision=request.expected_revision,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingCollaborativeHeadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        SavedGraphRevisionConflictError,
        CollaborationUncheckpointedError,
        CollaborationHeadConflictError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await publish_epoch_reset(
        get_resources(http_request.app).graph_room_hub,
        workspace_id=access.workspace_id,
        graph_id=graph_id,
        head=head,
    )
    return SavedGraphResponse.from_graph(graph)


@router.delete("/{graph_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_graph(
    graph_id: UUID,
    http_request: Request,
    collaboration: CollaborationDependency,
    access: require_workspace_capability(WorkspaceCapability.DELETE_GRAPH),
    expected_revision: Annotated[int, Query(ge=1)],
    expected_room_epoch: Annotated[UUID | None, Query()] = None,
    expected_sequence: Annotated[int | None, Query(ge=0)] = None,
) -> Response:
    if (expected_room_epoch is None) != (expected_sequence is None):
        raise HTTPException(
            status_code=422,
            detail=(
                "expected_room_epoch and expected_sequence must both be provided "
                "for collaboration-aware delete"
            ),
        )
    try:
        await collaboration.delete_graph(
            actor=access.actor,
            workspace_id=access.workspace_id,
            graph_id=graph_id,
            expected_revision=expected_revision,
            expected_room_epoch=expected_room_epoch,
            expected_sequence=expected_sequence,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingCollaborativeHeadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        SavedGraphRevisionConflictError,
        CollaborationUncheckpointedError,
        CollaborationActiveExecutionError,
        CollaborationHeadConflictError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await close_graph_room(
        get_resources(http_request.app).graph_room_hub,
        workspace_id=access.workspace_id,
        graph_id=graph_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

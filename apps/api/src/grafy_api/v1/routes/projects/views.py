"""Project HTTP routes (ADR 0020).

One Project, one room, one command sequence. These routes are the only HTTP door to
a Project: the browser and filing surface on :class:`ProjectService`, the head, the
command batches, the checkpoints and the restore on :class:`CollaborationService`.

Four rules hold on every route here:

* **Tenancy first.** The Project is always read under the workspace in the path, so a
  Project of another Workspace is a 404 and never a 403 with a hint that it exists.
* **Effective permission is role ∩ PAT scope ∩ capability.** A route asks for it through
  :func:`require_workspace_capability`, the only place the intersection is computed; a
  route that declares one capability less than its service requires answers for a
  narrower token than it serves.
* **A batch is the unit of acceptance.** ``POST /commands`` answers for the whole
  batch: accepted, with the new head and the receipt, or rejected with the head
  untouched.
* **An accepted change is published.** Peers hear about it on the room, and the Run
  service re-derives the Project's instances. The way back from either is a restore, and
  neither outcome is renegotiated once the write committed.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import Response
from grafy_core.domain.collaboration import CommandReceiptOutcome
from grafy_core.domain.errors import (
    CollaborationCommandRejectedError,
    CollaborationHeadConflictError,
    CollaborationIdempotencyMismatchError,
    CollaborationUncheckpointedError,
    MissingProjectHeadError,
    NotFoundError,
    ProjectCheckpointConflictError,
    ProjectFolderNameConflictError,
)
from grafy_core.domain.identity import ActorContext, WorkspaceCapability

from grafy_api.app_state import get_resources
from grafy_api.project_contracts import (
    AssignProjectFolderRequest,
    CheckpointProjectRequest,
    CheckpointProjectResponse,
    CopyExactHeadRequest,
    CreateProjectRequest,
    ProjectBrowserListResponse,
    ProjectCheckpointListResponse,
    ProjectCheckpointResponse,
    ProjectCommandReceiptResponse,
    ProjectFolderListResponse,
    ProjectFolderResponse,
    ProjectFolderWriteRequest,
    ProjectHeadResponse,
    ProjectListResponse,
    ProjectOrganizationResponse,
    ProjectResponse,
    SubmitProjectCommandRequest,
    SubmitProjectCommandResponse,
    UserProjectStateResponse,
)
from grafy_api.realtime.publish import (
    close_project_room,
    publish_accepted_command,
    publish_epoch_reset,
    rederive_instances,
)
from grafy_api.v1.routes.auth.dependencies import (
    IdentityUnitOfWorkFactoryDependency,
    browser_actor,
    require_workspace_capability,
)
from grafy_api.v1.routes.projects.dependencies import (
    CollaborationDependency,
    ProjectDependency,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/projects", tags=["projects"])
browser_router = APIRouter(prefix="/me/projects", tags=["project browser"])
folder_router = APIRouter(
    prefix="/workspaces/{workspace_id}/project-folders",
    tags=["project folders"],
)


@browser_router.get("", response_model=ProjectBrowserListResponse)
async def list_accessible_projects(
    service: ProjectDependency,
    actor: Annotated[ActorContext, Depends(browser_actor)],
) -> ProjectBrowserListResponse:
    return ProjectBrowserListResponse.from_items(
        await service.list_accessible(actor=actor)
    )


@folder_router.get("", response_model=ProjectFolderListResponse)
async def list_project_folders(
    service: ProjectDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
) -> ProjectFolderListResponse:
    folders = await service.list_folders(
        actor=access.actor,
        workspace_id=access.workspace_id,
    )
    return ProjectFolderListResponse.from_folders(folders)


@folder_router.post(
    "",
    response_model=ProjectFolderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_folder(
    request: ProjectFolderWriteRequest,
    service: ProjectDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_PROJECT),
) -> ProjectFolderResponse:
    try:
        folder = await service.create_folder(
            actor=access.actor,
            workspace_id=access.workspace_id,
            name=request.name,
        )
    except ProjectFolderNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ProjectFolderResponse.from_folder(folder)


@folder_router.patch("/{folder_id}", response_model=ProjectFolderResponse)
async def rename_project_folder(
    folder_id: UUID,
    request: ProjectFolderWriteRequest,
    service: ProjectDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_PROJECT),
) -> ProjectFolderResponse:
    try:
        folder = await service.rename_folder(
            actor=access.actor,
            workspace_id=access.workspace_id,
            folder_id=folder_id,
            name=request.name,
        )
    except ProjectFolderNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ProjectFolderResponse.from_folder(folder)


@folder_router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_folder(
    folder_id: UUID,
    service: ProjectDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_PROJECT),
) -> Response:
    await service.delete_folder(
        actor=access.actor,
        workspace_id=access.workspace_id,
        folder_id=folder_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    service: ProjectDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
) -> ProjectListResponse:
    items = await service.list_accessible(
        actor=access.actor,
        workspace_id=access.workspace_id,
    )
    return ProjectListResponse.from_items(items)


# Creation writes checkpoint 1 and the head in the same breath, so it needs the
# checkpointing capability as well as the creating one. The service asks for it too, but it
# can only ever see the role: a personal access token's scope is known at the route and
# nowhere below, so a token scoped for creating alone used to open a Project it was
# already checkpointing on the way in.
@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    request: CreateProjectRequest,
    collaboration: CollaborationDependency,
    access: require_workspace_capability(WorkspaceCapability.CREATE_PROJECT),
    checkpoint_access: require_workspace_capability(
        WorkspaceCapability.CHECKPOINT_PROJECT
    ),
) -> ProjectResponse:
    try:
        creation = await collaboration.create_project(
            actor=access.actor,
            workspace_id=access.workspace_id,
            name=request.name,
            graph_id=request.graph_id,
            graph_name=request.graph_name,
            project_id=request.project_id,
            command_id=request.command_id,
        )
    except (NotFoundError, MissingProjectHeadError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CollaborationCommandRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (
        CollaborationHeadConflictError,
        CollaborationIdempotencyMismatchError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ProjectResponse.from_project(creation.project)


# A copy is an opening, not a pointer: it stages the copied document as a new Project with
# checkpoint 1 and its own head, exactly as creation does, so it needs the checkpointing
# capability the creating scope alone used to be served without. The service asks for
# `view_project` on the source and `create_project` on the target and never for
# checkpointing at all, and below the routes a token's scope is invisible anyway.
@router.post(
    "/copies",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def copy_exact_head(
    request: CopyExactHeadRequest,
    collaboration: CollaborationDependency,
    access: require_workspace_capability(WorkspaceCapability.CREATE_PROJECT),
    checkpoint_access: require_workspace_capability(
        WorkspaceCapability.CHECKPOINT_PROJECT
    ),
    view_access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
) -> ProjectResponse:
    try:
        copy = await collaboration.copy_project(
            actor=access.actor,
            source_workspace_id=request.source_workspace_id,
            source_project_id=request.source_project_id,
            target_workspace_id=access.workspace_id,
            expected_room_epoch=request.expected_room_epoch,
            expected_sequence=request.expected_sequence,
            command_id=request.command_id,
            project_id=request.project_id,
            name=request.name,
        )
    except (NotFoundError, MissingProjectHeadError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CollaborationCommandRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (
        CollaborationHeadConflictError,
        CollaborationIdempotencyMismatchError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ProjectResponse.from_project(copy.project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    service: ProjectDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
) -> ProjectResponse:
    try:
        project = await service.get(
            workspace_id=access.workspace_id,
            project_id=project_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectResponse.from_project(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    http_request: Request,
    collaboration: CollaborationDependency,
    access: require_workspace_capability(WorkspaceCapability.DELETE_PROJECT),
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
        await collaboration.delete_project(
            actor=access.actor,
            workspace_id=access.workspace_id,
            project_id=project_id,
            expected_room_epoch=expected_room_epoch,
            expected_sequence=expected_sequence,
        )
    except (NotFoundError, MissingProjectHeadError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        CollaborationUncheckpointedError,
        CollaborationHeadConflictError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await close_project_room(
        get_resources(http_request.app).project_room_hub,
        workspace_id=access.workspace_id,
        project_id=project_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/head", response_model=ProjectHeadResponse)
async def get_project_head(
    project_id: UUID,
    collaboration: CollaborationDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
) -> ProjectHeadResponse:
    try:
        head = await collaboration.get_head(
            actor=access.actor,
            workspace_id=access.workspace_id,
            project_id=project_id,
        )
    except (NotFoundError, MissingProjectHeadError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectHeadResponse.from_head(head)


@router.post(
    "/{project_id}/commands",
    response_model=SubmitProjectCommandResponse,
)
async def submit_project_commands(
    project_id: UUID,
    request: SubmitProjectCommandRequest,
    http_request: Request,
    collaboration: CollaborationDependency,
    uow_factory: IdentityUnitOfWorkFactoryDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_PROJECT),
) -> SubmitProjectCommandResponse:
    try:
        submission = await collaboration.submit_commands(
            actor=access.actor,
            workspace_id=access.workspace_id,
            project_id=project_id,
            command_id=request.command_id,
            observed_sequence=request.observed_sequence,
            observed_room_epoch=request.room_epoch,
            commands=request.commands,
        )
    except (NotFoundError, MissingProjectHeadError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CollaborationCommandRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (
        CollaborationHeadConflictError,
        CollaborationIdempotencyMismatchError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    resources = get_resources(http_request.app)
    # Idempotent retries return the original receipt over HTTP and must not
    # rebroadcast a batch that peers already applied.
    if submission.receipt.outcome is not CommandReceiptOutcome.IDEMPOTENT_REPLAY:
        await publish_accepted_command(
            resources.project_room_hub,
            actor=access.actor,
            workspace_id=access.workspace_id,
            project_id=project_id,
            commands=request.commands,
            receipt=submission.receipt,
            uow_factory=uow_factory,
        )
        # The document moved, so every instance of this Project reads against new
        # fingerprints. What is in flight keeps running; this only re-derives state.
        await rederive_instances(
            resources.runs, workspace_id=access.workspace_id, project_id=project_id
        )
    return SubmitProjectCommandResponse(
        head=ProjectHeadResponse.from_head(submission.head),
        receipt=ProjectCommandReceiptResponse.from_receipt(submission.receipt),
    )


@router.post(
    "/{project_id}/checkpoints",
    response_model=CheckpointProjectResponse,
)
async def checkpoint_project(
    project_id: UUID,
    request: CheckpointProjectRequest,
    collaboration: CollaborationDependency,
    access: require_workspace_capability(WorkspaceCapability.CHECKPOINT_PROJECT),
) -> CheckpointProjectResponse:
    try:
        outcome = await collaboration.checkpoint(
            actor=access.actor,
            workspace_id=access.workspace_id,
            project_id=project_id,
            expected_sequence=request.expected_sequence,
            expected_room_epoch=request.expected_room_epoch,
        )
    except (NotFoundError, MissingProjectHeadError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        CollaborationHeadConflictError,
        ProjectCheckpointConflictError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CheckpointProjectResponse(
        head=ProjectHeadResponse.from_head(outcome.head),
        checkpoint_revision=outcome.revision,
    )


@router.get(
    "/{project_id}/checkpoints",
    response_model=ProjectCheckpointListResponse,
)
async def list_project_checkpoints(
    project_id: UUID,
    service: ProjectDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
) -> ProjectCheckpointListResponse:
    try:
        checkpoints = await service.list_checkpoints(
            workspace_id=access.workspace_id,
            project_id=project_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectCheckpointListResponse.from_checkpoints(checkpoints)


@router.get(
    "/{project_id}/checkpoints/{revision}",
    response_model=ProjectCheckpointResponse,
)
async def get_project_checkpoint(
    project_id: UUID,
    revision: Annotated[int, Path(ge=1)],
    service: ProjectDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
) -> ProjectCheckpointResponse:
    try:
        checkpoint = await service.get_checkpoint(
            workspace_id=access.workspace_id,
            project_id=project_id,
            revision=revision,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectCheckpointResponse.from_checkpoint(checkpoint)


# Both capabilities are required here, because both are exercised: a restore is an edit of
# the Project and it lands as a checkpoint. The service has always asked for
# `checkpoint_project` and keeps asking, but against the role alone, so a token scoped to
# `edit_project` used to pass the route and then satisfy that role-only check — which is how
# a backup token ended up rewriting a room and forcing every participant to rehydrate.
@router.post(
    "/{project_id}/checkpoints/{revision}/restore",
    response_model=CheckpointProjectResponse,
)
async def restore_project_checkpoint(
    project_id: UUID,
    revision: Annotated[int, Path(ge=1)],
    request: CheckpointProjectRequest,
    http_request: Request,
    collaboration: CollaborationDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_PROJECT),
    checkpoint_access: require_workspace_capability(
        WorkspaceCapability.CHECKPOINT_PROJECT
    ),
) -> CheckpointProjectResponse:
    """Bring a retained checkpoint back as the current state.

    Checkpoints are append-only, so this writes the old document forward under a new
    revision and reopens the room: peers rehydrate rather than rewind.
    """

    try:
        outcome = await collaboration.restore_checkpoint(
            actor=access.actor,
            workspace_id=access.workspace_id,
            project_id=project_id,
            revision=revision,
            expected_room_epoch=request.expected_room_epoch,
            expected_sequence=request.expected_sequence,
        )
    except (NotFoundError, MissingProjectHeadError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CollaborationUncheckpointedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (
        CollaborationHeadConflictError,
        ProjectCheckpointConflictError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    resources = get_resources(http_request.app)
    await publish_epoch_reset(
        resources.project_room_hub,
        workspace_id=access.workspace_id,
        project_id=project_id,
        head=outcome.head,
    )
    await rederive_instances(
        resources.runs, workspace_id=access.workspace_id, project_id=project_id
    )
    return CheckpointProjectResponse(
        head=ProjectHeadResponse.from_head(outcome.head),
        checkpoint_revision=outcome.revision,
    )


@router.put("/{project_id}/folder", response_model=ProjectOrganizationResponse)
async def assign_project_folder(
    project_id: UUID,
    request: AssignProjectFolderRequest,
    service: ProjectDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_PROJECT),
) -> ProjectOrganizationResponse:
    organization = await service.assign_folder(
        actor=access.actor,
        workspace_id=access.workspace_id,
        project_id=project_id,
        folder_id=request.folder_id,
    )
    return ProjectOrganizationResponse.from_organization(organization)


@router.put("/{project_id}/archive", response_model=ProjectOrganizationResponse)
async def archive_project(
    project_id: UUID,
    service: ProjectDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_PROJECT),
) -> ProjectOrganizationResponse:
    organization = await service.archive(
        actor=access.actor,
        workspace_id=access.workspace_id,
        project_id=project_id,
    )
    return ProjectOrganizationResponse.from_organization(organization)


@router.delete("/{project_id}/archive", response_model=ProjectOrganizationResponse)
async def restore_project(
    project_id: UUID,
    service: ProjectDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_PROJECT),
) -> ProjectOrganizationResponse:
    organization = await service.restore(
        actor=access.actor,
        workspace_id=access.workspace_id,
        project_id=project_id,
    )
    return ProjectOrganizationResponse.from_organization(organization)


@router.put("/{project_id}/star", response_model=UserProjectStateResponse)
async def star_project(
    project_id: UUID,
    service: ProjectDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
) -> UserProjectStateResponse:
    state = await service.set_starred(
        actor=access.actor,
        workspace_id=access.workspace_id,
        project_id=project_id,
        starred=True,
    )
    return UserProjectStateResponse.from_state(state)


@router.delete("/{project_id}/star", response_model=UserProjectStateResponse)
async def unstar_project(
    project_id: UUID,
    service: ProjectDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
) -> UserProjectStateResponse:
    state = await service.set_starred(
        actor=access.actor,
        workspace_id=access.workspace_id,
        project_id=project_id,
        starred=False,
    )
    return UserProjectStateResponse.from_state(state)


@router.post("/{project_id}/opened", response_model=UserProjectStateResponse)
async def record_project_open(
    project_id: UUID,
    service: ProjectDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
) -> UserProjectStateResponse:
    state = await service.record_open(
        actor=access.actor,
        workspace_id=access.workspace_id,
        project_id=project_id,
    )
    return UserProjectStateResponse.from_state(state)

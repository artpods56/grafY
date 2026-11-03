"""Post-commit publication helpers for HTTP and room command paths."""

from collections.abc import Callable
from uuid import UUID

from grafy_core.domain.collaboration import (
    ProjectHead,
    ProjectCommand,
    ProjectCommandReceipt,
)
from grafy_core.domain.identity import ActorContext
from grafy_core.ports.identity import IdentityUnitOfWorkPort

from grafy_api.project_contracts import ProjectHeadResponse
from grafy_api.realtime.hub import (
    CLOSE_ACCESS_REVOKED,
    CLOSE_PROJECT_DELETED,
    CLOSE_PERMISSIONS_CHANGED,
    ProjectRoomHub,
)
from grafy_api.realtime.protocol import (
    ActorPresentation,
    ProjectCommandAcceptedMessage,
    RoomRehydrateMessage,
    actor_display_color,
    bounded_display_name,
)


async def actor_presentation_for(
    uow_factory: Callable[[], IdentityUnitOfWorkPort],
    actor: ActorContext,
) -> ActorPresentation:
    async with uow_factory() as unit_of_work:
        user = await unit_of_work.identity.get_user(actor.user_id)
    display_name = "collaborator"
    if user is not None:
        display_name = bounded_display_name(user.display_name, user.email)
    return ActorPresentation(
        actor_id=actor.user_id,
        display_name=display_name,
        color=actor_display_color(actor.user_id),
    )


async def publish_accepted_command(
    hub: ProjectRoomHub,
    *,
    actor: ActorContext,
    workspace_id: UUID,
    project_id: UUID,
    commands: tuple[ProjectCommand, ...],
    receipt: ProjectCommandReceipt,
    project_room_session_id: UUID | None = None,
    uow_factory: Callable[[], IdentityUnitOfWorkPort],
) -> None:
    presentation = await actor_presentation_for(uow_factory, actor)
    await hub.publish_accepted(
        workspace_id=workspace_id,
        project_id=project_id,
        accepted=ProjectCommandAcceptedMessage(
            command_id=receipt.command_id,
            room_epoch=receipt.room_epoch,
            sequence=receipt.accepted_sequence,
            actor=presentation,
            project_room_session_id=project_room_session_id,
            commands=commands,
        ),
    )


async def publish_epoch_reset(
    hub: ProjectRoomHub,
    *,
    workspace_id: UUID,
    project_id: UUID,
    head: ProjectHead,
) -> None:
    await hub.publish_rehydrate(
        workspace_id=workspace_id,
        project_id=project_id,
        message=RoomRehydrateMessage(
            head=ProjectHeadResponse.from_head(head),
        ),
    )


async def close_project_room(
    hub: ProjectRoomHub,
    *,
    workspace_id: UUID,
    project_id: UUID,
) -> None:
    await hub.close_project(
        workspace_id=workspace_id,
        project_id=project_id,
        code=CLOSE_PROJECT_DELETED[0],
        reason=CLOSE_PROJECT_DELETED[1],
    )


async def close_user_rooms_for_permission_change(
    hub: ProjectRoomHub,
    *,
    workspace_id: UUID,
    user_id: UUID,
    access_revoked: bool,
) -> None:
    if access_revoked:
        code, reason = CLOSE_ACCESS_REVOKED
    else:
        code, reason = CLOSE_PERMISSIONS_CHANGED
    await hub.close_workspace_user(
        workspace_id=workspace_id,
        user_id=user_id,
        code=code,
        reason=reason,
    )

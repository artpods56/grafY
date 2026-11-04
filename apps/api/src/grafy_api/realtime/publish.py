"""Post-commit publication helpers for HTTP and room command paths."""

import logging
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
from grafy_api.runs.service import RunService


logger = logging.getLogger(__name__)


async def rederive_instances(
    runs: RunService,
    *,
    workspace_id: UUID,
    project_id: UUID,
) -> None:
    """Re-derive a Project's instances after a durable change, never at that change's cost.

    Every HTTP write that moves what an instance reads — an accepted batch, a restore, a
    secret rotated under a node — owes peers the recomputed state, because a fingerprint
    folds in the secret revisions of the node that ran. But by the time this runs the write
    has committed and its outcome is already owed to the caller: a derivation this build
    cannot make, or a room nobody will read, cannot honestly turn a rotated credential into
    a failure of the credential dialog. A peer that misses a freshness push has a stale view
    until the next read; a 500 on a write that worked loses the secret.

    So the failure is logged and left to the next Run, which is what the room path does for
    the same call, and this is the one place every HTTP path reports it: one event name for
    an operator to watch, whatever moved the document.
    """

    try:
        await runs.project_changed(
            workspace_id=workspace_id,
            project_id=project_id,
        )
    except Exception:
        logger.exception(
            "project_http_instance_publish_failed workspace_id=%s project_id=%s",
            workspace_id,
            project_id,
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

"""Post-commit publication helpers for HTTP and room command paths."""

from collections.abc import Callable
from uuid import UUID

from grafy_core.domain.collaboration import (
    CollaborativeGraphHead,
    GraphCommand,
    GraphCommandReceipt,
)
from grafy_core.domain.identity import ActorContext
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from grafy_api.graph_contracts import CollaborativeHeadResponse
from grafy_api.realtime.hub import (
    CLOSE_ACCESS_REVOKED,
    CLOSE_GRAPH_DELETED,
    CLOSE_PERMISSIONS_CHANGED,
    GraphRoomHub,
)
from grafy_api.realtime.protocol import (
    ActorPresentation,
    GraphCommandAcceptedMessage,
    RoomRehydrateMessage,
    actor_display_color,
    bounded_display_name,
)


async def actor_presentation_for(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
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
    hub: GraphRoomHub,
    *,
    actor: ActorContext,
    workspace_id: UUID,
    graph_id: UUID,
    command: GraphCommand,
    receipt: GraphCommandReceipt,
    graph_room_session_id: UUID | None = None,
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    presentation = await actor_presentation_for(uow_factory, actor)
    await hub.publish_accepted(
        workspace_id=workspace_id,
        graph_id=graph_id,
        accepted=GraphCommandAcceptedMessage(
            command_id=receipt.command_id,
            room_epoch=receipt.room_epoch,
            sequence=receipt.accepted_sequence,
            actor=presentation,
            graph_room_session_id=graph_room_session_id,
            command=command,
        ),
    )


async def publish_epoch_reset(
    hub: GraphRoomHub,
    *,
    workspace_id: UUID,
    graph_id: UUID,
    head: CollaborativeGraphHead,
) -> None:
    await hub.publish_rehydrate(
        workspace_id=workspace_id,
        graph_id=graph_id,
        message=RoomRehydrateMessage(
            head=CollaborativeHeadResponse.from_head(head),
        ),
    )


async def close_graph_room(
    hub: GraphRoomHub,
    *,
    workspace_id: UUID,
    graph_id: UUID,
) -> None:
    await hub.close_graph(
        workspace_id=workspace_id,
        graph_id=graph_id,
        code=CLOSE_GRAPH_DELETED[0],
        reason=CLOSE_GRAPH_DELETED[1],
    )


async def close_user_rooms_for_permission_change(
    hub: GraphRoomHub,
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

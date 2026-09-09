import asyncio
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, status
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from grafy_core.application.collaboration import CollaborationService
from grafy_core.application.identity import IdentityService
from grafy_core.domain.collaboration import CommandReceiptOutcome
from grafy_core.domain.errors import (
    CapabilityDeniedError,
    CollaborationCommandRejectedError,
    CollaborationHeadConflictError,
    CollaborationIdempotencyMismatchError,
    MissingCollaborativeHeadError,
    NotFoundError,
    UserDisabledError,
)
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceCapability,
)

from grafy_api.app_state import get_resources
from grafy_api.v1.routes.auth.dependencies import browser_actor
from grafy_api.v1.routes.auth.services import SESSION_COOKIE
from grafy_api.v1.routes.collaboration.dependencies import (
    AuthServiceWsDependency,
    CollaborationWsDependency,
    GraphRoomHubWsDependency,
    IdentityServiceWsDependency,
    IdentityUnitOfWorkFactoryWsDependency,
)
from grafy_api.realtime.hub import (
    CLOSE_ACCESS_REVOKED,
    CLOSE_PERMISSIONS_CHANGED,
    CLOSE_PROTOCOL_ERROR,
    GraphRoomHub,
    GraphRoomSession,
)
from grafy_api.realtime.protocol import (
    CLIENT_ROOM_MESSAGE_ADAPTER,
    CapabilitySnapshot,
    GraphCommandAcceptedMessage,
    GraphCommandReceiptMessage,
    GraphCommandRejectedMessage,
    GraphCommandSubmitMessage,
    PresenceUpdateSubmitMessage,
    RoomHeartbeatMessage,
    RoomReadyMessage,
    command_receipt_outcome,
)
from grafy_api.realtime.publish import actor_presentation_for
from grafy_api.graph_contracts import CollaborativeHeadResponse


logger = logging.getLogger(__name__)

router = APIRouter(tags=["collaboration"])


def _http_request_from_websocket(websocket: WebSocket) -> Request:
    """Build a GET Request view of the handshake for cookie/session helpers."""

    scope = dict(websocket.scope)
    scope["type"] = "http"
    scope["method"] = "GET"
    scope.setdefault("extensions", {})
    return Request(scope)


async def websocket_browser_actor(
    websocket: WebSocket,
    auth: AuthServiceWsDependency,
) -> ActorContext:
    """Resolve the browser actor for WebSocket admission.

    This dependency is the WebSocket counterpart of the HTTP ``browser_actor``
    seam: tests override it (or its ``auth_service_ws`` inner dependency) the
    same way they override HTTP dependencies, instead of production code
    reaching into ``app.dependency_overrides``.
    """

    request = _http_request_from_websocket(websocket)
    return await browser_actor(
        request,
        auth,
        request.cookies.get(SESSION_COOKIE),
    )


def _require_websocket_origin(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    public_origin = websocket.app.state.settings.public_origin
    if origin != public_origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin validation failed",
        )


@router.websocket("/workspaces/{workspace_id}/graphs/{graph_id}/room")
async def graph_room(
    websocket: WebSocket,
    workspace_id: UUID,
    graph_id: UUID,
    hub: GraphRoomHubWsDependency,
    collaboration: CollaborationWsDependency,
    identity: IdentityServiceWsDependency,
    uow_factory: IdentityUnitOfWorkFactoryWsDependency,
    actor: Annotated[ActorContext, Depends(websocket_browser_actor)],
) -> None:
    _require_websocket_origin(websocket)
    try:
        access = await identity.authorize(
            actor=actor,
            workspace_id=workspace_id,
            capability=WorkspaceCapability.JOIN_GRAPH_ROOM,
        )
        access.require(WorkspaceCapability.VIEW_GRAPH)
        presentation = await actor_presentation_for(uow_factory, actor)
    except HTTPException:
        raise
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except MissingCollaborativeHeadError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except CapabilityDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except UserDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        ) from exc

    session = GraphRoomSession(
        workspace_id=workspace_id,
        graph_id=graph_id,
        graph_room_session_id=hub.new_session_id(),
        actor_user_id=actor.user_id,
        credential_reference=actor.credential_reference,
        authorization_version=access.membership.authorization_version,
        actor_presentation=presentation,
        websocket=websocket,
    )
    await hub.join(session)
    try:
        head = await collaboration.get_head(
            actor=actor,
            workspace_id=workspace_id,
            graph_id=graph_id,
        )
    except NotFoundError as exc:
        await hub.leave(session)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except MissingCollaborativeHeadError as exc:
        await hub.leave(session)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except CapabilityDeniedError as exc:
        await hub.leave(session)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except UserDisabledError as exc:
        await hub.leave(session)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        ) from exc
    except Exception:
        await hub.leave(session)
        raise

    try:
        await websocket.accept()
        await hub.register_presence(session)
        participants = await hub.participants_for(
            workspace_id=workspace_id,
            graph_id=graph_id,
        )
        active_execution = await get_resources(
            websocket.app
        ).workbench.execution_manager.active_execution_summary(
            workspace_id,
            graph_id,
        )
        if active_execution is not None:
            active_execution = active_execution.model_copy(
                update={
                    "overlays_compatible": (
                        head.checkpoint_revision == active_execution.graph_revision
                    )
                }
            )
        ready = RoomReadyMessage(
            workspace_id=workspace_id,
            graph_id=graph_id,
            graph_room_session_id=session.graph_room_session_id,
            actor=presentation,
            capabilities=CapabilitySnapshot(
                capabilities=tuple(
                    sorted(access.capabilities, key=lambda item: item.value)
                ),
                authorization_version=access.membership.authorization_version,
            ),
            head=CollaborativeHeadResponse.from_head(head),
            participants=participants,
            active_execution=active_execution,
        )
        heartbeat_seconds = websocket.app.state.settings.graph_room_heartbeat_seconds
        await websocket.send_json(ready.model_dump(mode="json"))
        await hub.activate(session)
        while True:
            if heartbeat_seconds > 0:
                try:
                    raw = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=heartbeat_seconds,
                    )
                except TimeoutError:
                    still_open = await _revalidate_and_heartbeat(
                        websocket=websocket,
                        session=session,
                        actor=actor,
                        hub=hub,
                        identity=identity,
                    )
                    if not still_open:
                        return
                    continue
            else:
                raw = await websocket.receive_json()
            try:
                message = CLIENT_ROOM_MESSAGE_ADAPTER.validate_python(raw)
            except ValidationError:
                await hub.close_session(
                    session,
                    code=CLOSE_PROTOCOL_ERROR[0],
                    reason=CLOSE_PROTOCOL_ERROR[1],
                )
                return
            if isinstance(message, GraphCommandSubmitMessage):
                await _handle_command_submit(
                    session=session,
                    actor=actor,
                    collaboration=collaboration,
                    hub=hub,
                    message=message,
                )
            else:
                await _handle_presence_update(
                    session=session,
                    actor=actor,
                    hub=hub,
                    identity=identity,
                    message=message,
                )
    except WebSocketDisconnect:
        await hub.leave(session)
    except Exception:
        logger.exception(
            "graph_room_failed workspace_id=%s graph_id=%s graph_room_session_id=%s",
            workspace_id,
            graph_id,
            session.graph_room_session_id,
        )
        await hub.leave(session)


async def _revalidate_and_heartbeat(
    *,
    websocket: WebSocket,
    session: GraphRoomSession,
    actor: ActorContext,
    hub: GraphRoomHub,
    identity: IdentityService,
) -> bool:
    """Reauthorize membership and emit ``room.heartbeat``.

    Covers lost post-commit invalidation (auth tenancy design). Role or view
    changes close with the stable protocol reasons rather than updating
    capabilities in place.
    """

    if session.closed:
        return False
    try:
        access = await identity.authorize(
            actor=actor,
            workspace_id=session.workspace_id,
            capability=WorkspaceCapability.JOIN_GRAPH_ROOM,
        )
        access.require(WorkspaceCapability.VIEW_GRAPH)
    except (NotFoundError, CapabilityDeniedError, UserDisabledError):
        await hub.close_session(
            session,
            code=CLOSE_ACCESS_REVOKED[0],
            reason=CLOSE_ACCESS_REVOKED[1],
        )
        return False
    if access.membership.authorization_version != session.authorization_version:
        await hub.close_session(
            session,
            code=CLOSE_PERMISSIONS_CHANGED[0],
            reason=CLOSE_PERMISSIONS_CHANGED[1],
        )
        return False
    await hub.deliver_private(
        session,
        RoomHeartbeatMessage(
            authorization_version=access.membership.authorization_version,
        ),
    )
    return True


async def _handle_presence_update(
    *,
    session: GraphRoomSession,
    actor: ActorContext,
    hub: GraphRoomHub,
    identity: IdentityService,
    message: PresenceUpdateSubmitMessage,
) -> None:
    try:
        access = await identity.authorize(
            actor=actor,
            workspace_id=session.workspace_id,
            capability=WorkspaceCapability.PUBLISH_PRESENCE,
        )
        access.require(WorkspaceCapability.PUBLISH_PRESENCE)
    except CapabilityDeniedError:
        # Best-effort channel: lack of publish_presence drops the update only.
        return
    except (NotFoundError, UserDisabledError):
        await hub.close_session(
            session,
            code=CLOSE_ACCESS_REVOKED[0],
            reason=CLOSE_ACCESS_REVOKED[1],
        )
        return
    await hub.apply_presence_update(session, message)


async def _handle_command_submit(
    *,
    session: GraphRoomSession,
    actor: ActorContext,
    collaboration: CollaborationService,
    hub: GraphRoomHub,
    message: GraphCommandSubmitMessage,
) -> None:
    try:
        head, receipt = await collaboration.accept_command(
            actor=actor,
            workspace_id=session.workspace_id,
            graph_id=session.graph_id,
            command_id=message.command_id,
            observed_sequence=message.observed_sequence,
            observed_room_epoch=message.room_epoch,
            command=message.command,
        )
    except CapabilityDeniedError as exc:
        await _reject_command(session, hub, message, "forbidden", str(exc))
        return
    except NotFoundError as exc:
        await _reject_command(session, hub, message, "not_found", str(exc))
        return
    except MissingCollaborativeHeadError as exc:
        await _reject_command(session, hub, message, "missing_head", str(exc))
        return
    except CollaborationCommandRejectedError as exc:
        await _reject_command(session, hub, message, "command_rejected", str(exc))
        return
    except CollaborationHeadConflictError as exc:
        await hub.deliver_private(
            session,
            GraphCommandRejectedMessage(
                command_id=message.command_id,
                error_code="head_conflict",
                detail=str(exc),
                current_room_epoch=exc.room_epoch,
                current_sequence=exc.actual_sequence,
            ),
        )
        return
    except CollaborationIdempotencyMismatchError as exc:
        await _reject_command(session, hub, message, "idempotency_mismatch", str(exc))
        return

    deduplicated = receipt.outcome is CommandReceiptOutcome.IDEMPOTENT_REPLAY
    receipt_message = GraphCommandReceiptMessage(
        command_id=message.command_id,
        outcome=command_receipt_outcome(deduplicated=deduplicated),
        accepted_room_epoch=receipt.room_epoch,
        accepted_sequence=receipt.accepted_sequence,
        current_room_epoch=head.room_epoch,
        current_sequence=head.collaboration_sequence,
        deduplicated=deduplicated,
        requires_head_rehydration=receipt.room_epoch != head.room_epoch,
    )
    if deduplicated:
        # Design: receipt answers an idempotent retry and is never rebroadcast.
        await hub.deliver_private(session, receipt_message)
        return

    accepted = GraphCommandAcceptedMessage(
        command_id=message.command_id,
        room_epoch=receipt.room_epoch,
        sequence=receipt.accepted_sequence,
        actor=session.actor_presentation,
        graph_room_session_id=session.graph_room_session_id,
        command=message.command,
    )
    await hub.publish_accepted(
        workspace_id=session.workspace_id,
        graph_id=session.graph_id,
        accepted=accepted,
        receipt=receipt_message,
        receipt_session_id=session.graph_room_session_id,
    )


async def _reject_command(
    session: GraphRoomSession,
    hub: GraphRoomHub,
    message: GraphCommandSubmitMessage,
    error_code: str,
    detail: str,
) -> None:
    """Route a command rejection through the hub's single outbound sender.

    After activation the hub queue is the sole outbound interface; direct
    ``websocket.send_json`` writes are reserved for the pre-activation
    ``room.ready`` handshake. Routing rejections through ``deliver_private``
    preserves FIFO ordering, queue backpressure, and slow-consumer handling.
    """

    await hub.deliver_private(
        session,
        GraphCommandRejectedMessage(
            command_id=message.command_id,
            error_code=error_code,
            detail=detail,
        ),
    )

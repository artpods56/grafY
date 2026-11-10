"""The Project room: one WebSocket per participant (ADR 0020).

A Project is the collaborative document, so a Project is what a room is for. The
route keeps the shape the graph room earned and changes only its nouns:

* **Admission is authorization.** Origin, then ``join_project_room`` with
  ``view_project``, then the head. A Project of another Workspace is a 404, the same
  answer as one that was never opened.
* **The snapshot comes first.** The session registers with the hub, the head is read,
  ``room.ready`` is written straight to the socket, and only then is the session
  activated — so a command committed while the head was being read arrives after
  the head it moved past, never instead of it.
* **One writer after activation.** Everything the room sends goes through the hub's
  single sender task, which is what keeps fanout, private receipts and heartbeats in
  one FIFO and keeps a slow consumer bounded.
* **Edits and Runs share one room.** An accepted batch is fanned out and then handed
  to the Run service, which re-derives instance state and publishes
  ``instances.changed``. A Run is announced by the Run service itself, over the same
  hub, whether or not anyone is watching.

Nothing here runs a computation, holds the document, or refuses an edit because
something is computing.
"""

import asyncio
import contextlib
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
    MissingProjectHeadError,
    NotFoundError,
    UserDisabledError,
)
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceAccess,
    WorkspaceCapability,
)

from grafy_api.app_state import get_identity
from grafy_api.project_contracts import ProjectHeadResponse
from grafy_api.realtime.hub import (
    CLOSE_ACCESS_REVOKED,
    CLOSE_PERMISSIONS_CHANGED,
    CLOSE_PROTOCOL_ERROR,
    ProjectRoomHub,
    ProjectRoomSession,
)
from grafy_api.realtime.protocol import (
    CLIENT_ROOM_MESSAGE_ADAPTER,
    ActiveRunSummary,
    CapabilitySnapshot,
    InstanceStateEntry,
    PresenceUpdateSubmitMessage,
    ProjectCommandAcceptedMessage,
    ProjectCommandReceiptMessage,
    ProjectCommandRejectedMessage,
    ProjectCommandSubmitMessage,
    RoomHeartbeatMessage,
    RoomReadyMessage,
    command_receipt_outcome,
)
from grafy_api.realtime.publish import actor_presentation_for
from grafy_api.realtime.run_events import instance_state_entry, run_summary
from grafy_api.runs.ports import RunRejectedError
from grafy_api.runs.service import RunService
from grafy_api.v1.routes.auth.dependencies import browser_actor
from grafy_api.auth import SESSION_COOKIE
from grafy_api.v1.routes.collaboration.dependencies import (
    AuthServiceWsDependency,
    CollaborationWsDependency,
    IdentityServiceWsDependency,
    IdentityUnitOfWorkFactoryWsDependency,
    ProjectRoomHubWsDependency,
    RunServiceWsDependency,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["collaboration"])

REJECTION_DETAIL_MAX_LENGTH = 500


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

    This dependency is the WebSocket counterpart of the HTTP ``browser_actor`` seam:
    tests override it (or its ``auth_service_ws`` inner dependency) the same way they
    override HTTP dependencies, instead of production code reaching into
    ``app.dependency_overrides``.
    """

    request = _http_request_from_websocket(websocket)
    return await browser_actor(
        request,
        auth,
        request.cookies.get(SESSION_COOKIE),
    )


def _require_websocket_origin(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    public_origin = get_identity(websocket.app).public_origin
    if origin != public_origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin validation failed",
        )


@router.websocket("/workspaces/{workspace_id}/projects/{project_id}/room")
async def join_project_room(
    websocket: WebSocket,
    workspace_id: UUID,
    project_id: UUID,
    hub: ProjectRoomHubWsDependency,
    collaboration: CollaborationWsDependency,
    runs: RunServiceWsDependency,
    identity: IdentityServiceWsDependency,
    uow_factory: IdentityUnitOfWorkFactoryWsDependency,
    actor: Annotated[ActorContext, Depends(websocket_browser_actor)],
) -> None:
    _require_websocket_origin(websocket)
    try:
        access = await _authorize_room(identity, actor=actor, workspace_id=workspace_id)
        presentation = await actor_presentation_for(uow_factory, actor)
    except HTTPException:
        raise
    except NotFoundError as exc:
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

    session = ProjectRoomSession(
        workspace_id=workspace_id,
        project_id=project_id,
        project_room_session_id=hub.new_session_id(),
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
            project_id=project_id,
        )
    except (NotFoundError, MissingProjectHeadError) as exc:
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
            project_id=project_id,
        )

        ready = RoomReadyMessage(
            workspace_id=workspace_id,
            project_id=project_id,
            project_room_session_id=session.project_room_session_id,
            actor=presentation,
            capabilities=CapabilitySnapshot(
                capabilities=tuple(
                    sorted(access.capabilities, key=lambda item: item.value)
                ),
                authorization_version=access.membership.authorization_version,
            ),
            head=ProjectHeadResponse.from_head(head),
            participants=participants,
            active_runs=await _active_runs(runs, workspace_id, project_id, uow_factory),
            instances=await _instances(runs, workspace_id, project_id),
        )
        heartbeat_seconds = hub.heartbeat_seconds
        await websocket.send_json(ready.model_dump(mode="json"))
        await hub.activate(session)
        heartbeat_task: asyncio.Task[None] | None = None
        if heartbeat_seconds > 0:
            # A timer task, not a timeout around the receive: the ASGI receive is an
            # anyio checkpoint, and cancelling it from asyncio raises TypeError on the
            # way out instead of timing out, which killed the room on its first quiet
            # window. A timer also cannot be starved by a chatty client, so membership
            # revalidation happens on schedule however busy the socket is.
            heartbeat_task = asyncio.create_task(
                _heartbeat_loop(
                    websocket=websocket,
                    session=session,
                    actor=actor,
                    hub=hub,
                    identity=identity,
                    interval=heartbeat_seconds,
                )
            )
        try:
            while True:
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
                if isinstance(message, ProjectCommandSubmitMessage):
                    await _handle_command_submit(
                        session=session,
                        actor=actor,
                        collaboration=collaboration,
                        runs=runs,
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
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
    except WebSocketDisconnect:
        # The departure itself is the finally's job; this arm only says why.
        pass
    except Exception:
        logger.exception(
            "project_room_failed workspace_id=%s project_id=%s "
            "project_room_session_id=%s",
            workspace_id,
            project_id,
            session.project_room_session_id,
        )
    finally:
        await _depart_room(hub, session)


async def _depart_room(hub: ProjectRoomHub, session: ProjectRoomSession) -> None:
    """Leave the room, whatever ended it — including a cancelled room task.

    Cancellation is the normal way a WebSocket handler ends: an ASGI server cancels it
    when the peer goes away, and the test client cancels its session scope on exit. A
    departure written only in the `except` arms is therefore a leak with a schedule: the
    session stays registered, so its peers never receive ``presence.leave``, keep fanning
    out to a socket that is gone, and its sender task outlives that socket. The hub's
    shutdown is then the only thing that cleans up, and it inherits the wait.

    The bookkeeping therefore happens with no await in it at all, and only then does this
    await the part that needs to — the sender's stop and the close frame — shielded, so a
    cancellation that is already in flight cannot interrupt it halfway.
    """

    hub.leave_now(session)
    try:
        await asyncio.shield(hub.leave(session))
    except asyncio.CancelledError:
        logger.debug(
            "project_room_departure_cancelled workspace_id=%s project_id=%s "
            "project_room_session_id=%s",
            session.workspace_id,
            session.project_id,
            session.project_room_session_id,
        )


async def _authorize_room(
    identity: IdentityService,
    *,
    actor: ActorContext,
    workspace_id: UUID,
) -> WorkspaceAccess:
    """Membership for the room only: the document and the Run list come after it."""

    access = await identity.authorize(
        actor=actor,
        workspace_id=workspace_id,
        capability=WorkspaceCapability.JOIN_PROJECT_ROOM,
    )
    access.require(WorkspaceCapability.VIEW_PROJECT)
    return access


async def _active_runs(
    runs: RunService,
    workspace_id: UUID,
    project_id: UUID,
    uow_factory: IdentityUnitOfWorkFactoryWsDependency,
) -> tuple[ActiveRunSummary, ...]:
    """The Runs a joiner cannot see any other way: they started before it joined."""

    listed = await runs.list_runs(
        workspace_id=workspace_id,
        project_id=project_id,
        active_only=True,
    )
    summaries = []
    for run in listed:
        summaries.append(await run_summary(run, uow_factory))
    return tuple(summaries)


async def _instances(
    runs: RunService,
    workspace_id: UUID,
    project_id: UUID,
) -> tuple[InstanceStateEntry, ...]:
    """Instance state for every Graph of the head the joiner is about to load.

    A document this build cannot compute fingerprints for — it names an operator this
    deployment does not register — must not lock a participant out of the room that is
    the only way to repair it, so a failed derivation is logged and the room opens
    with no instances rather than not at all.
    """

    try:
        snapshots = await runs.instance_states(
            workspace_id=workspace_id,
            project_id=project_id,
        )
    except RunRejectedError:
        logger.exception(
            "project_room_instance_state_unavailable workspace_id=%s project_id=%s",
            workspace_id,
            project_id,
        )
        return ()
    return tuple(instance_state_entry(snapshot) for snapshot in snapshots)


async def _heartbeat_loop(
    *,
    websocket: WebSocket,
    session: ProjectRoomSession,
    actor: ActorContext,
    hub: ProjectRoomHub,
    identity: IdentityService,
    interval: float,
) -> None:
    """Keepalive and membership revalidation for a quiet-or-busy room.

    Returning here means the room is closed: the receive loop then ends on the closed
    socket the same way it ends on any disconnect.
    """

    while True:
        await asyncio.sleep(interval)
        still_open = await _revalidate_and_heartbeat(
            websocket=websocket,
            session=session,
            actor=actor,
            hub=hub,
            identity=identity,
        )
        if not still_open:
            return


async def _revalidate_and_heartbeat(
    *,
    websocket: WebSocket,
    session: ProjectRoomSession,
    actor: ActorContext,
    hub: ProjectRoomHub,
    identity: IdentityService,
) -> bool:
    """Reauthorize membership and emit ``room.heartbeat``.

    Covers lost post-commit invalidation (auth tenancy design). Role or view changes
    close with the stable protocol reasons rather than updating capabilities in place.
    """

    if session.closed:
        return False
    try:
        access = await _authorize_room(
            identity,
            actor=actor,
            workspace_id=session.workspace_id,
        )
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
    session: ProjectRoomSession,
    actor: ActorContext,
    hub: ProjectRoomHub,
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
    session: ProjectRoomSession,
    actor: ActorContext,
    collaboration: CollaborationService,
    runs: RunService,
    hub: ProjectRoomHub,
    message: ProjectCommandSubmitMessage,
) -> None:
    try:
        head, receipt = await collaboration.submit_commands(
            actor=actor,
            workspace_id=session.workspace_id,
            project_id=session.project_id,
            command_id=message.command_id,
            observed_sequence=message.observed_sequence,
            observed_room_epoch=message.room_epoch,
            commands=message.commands,
        )
    except CapabilityDeniedError as exc:
        await _reject_command(session, hub, message, "forbidden", str(exc))
        return
    except NotFoundError as exc:
        await _reject_command(session, hub, message, "not_found", str(exc))
        return
    except MissingProjectHeadError as exc:
        await _reject_command(session, hub, message, "missing_head", str(exc))
        return
    except CollaborationCommandRejectedError as exc:
        await _reject_command(
            session,
            hub,
            message,
            exc.error_code,
            str(exc),
        )
        return
    except CollaborationHeadConflictError as exc:
        await hub.deliver_private(
            session,
            ProjectCommandRejectedMessage(
                command_id=message.command_id,
                error_code="head_conflict",
                detail=_bounded_detail(str(exc)),
                current_room_epoch=exc.room_epoch,
                current_sequence=exc.actual_sequence,
            ),
        )
        return
    except CollaborationIdempotencyMismatchError as exc:
        await _reject_command(session, hub, message, "idempotency_mismatch", str(exc))
        return

    deduplicated = receipt.outcome is CommandReceiptOutcome.IDEMPOTENT_REPLAY
    receipt_message = ProjectCommandReceiptMessage(
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
        # Design: a receipt answers an idempotent retry and is never rebroadcast, and
        # a replay moved no document, so it owes no instance publish either.
        await hub.deliver_private(session, receipt_message)
        return

    accepted = ProjectCommandAcceptedMessage(
        command_id=message.command_id,
        room_epoch=receipt.room_epoch,
        sequence=receipt.accepted_sequence,
        actor=session.actor_presentation,
        project_room_session_id=session.project_room_session_id,
        commands=message.commands,
    )
    await hub.publish_accepted(
        workspace_id=session.workspace_id,
        project_id=session.project_id,
        accepted=accepted,
        receipt=receipt_message,
        receipt_session_id=session.project_room_session_id,
    )
    await _document_moved(runs, session)


async def _document_moved(runs: RunService, session: ProjectRoomSession) -> None:
    """Re-derive instance state after an accepted batch, and say what changed.

    An edit moves fingerprints, not computations: what is in flight keeps running and
    stores its result under the fingerprint it started with, while the instances it fed
    read as stale from here. A derivation this build cannot make — the batch named an
    operator it does not register — is logged and left to the next Run: the batch was
    accepted, was fanned out, and stays accepted.
    """

    try:
        await runs.project_changed(
            workspace_id=session.workspace_id,
            project_id=session.project_id,
            wait=False,
        )
    except Exception:
        logger.exception(
            "project_room_instance_publish_failed workspace_id=%s project_id=%s",
            session.workspace_id,
            session.project_id,
        )


async def _reject_command(
    session: ProjectRoomSession,
    hub: ProjectRoomHub,
    message: ProjectCommandSubmitMessage,
    error_code: str,
    detail: str,
) -> None:
    """Route a command rejection through the hub's single outbound sender.

    After activation the hub queue is the sole outbound interface; direct
    ``websocket.send_json`` writes are reserved for the pre-activation ``room.ready``
    handshake. Routing rejections through ``deliver_private`` preserves FIFO ordering,
    queue backpressure, and slow-consumer handling.
    """

    await hub.deliver_private(
        session,
        ProjectCommandRejectedMessage(
            command_id=message.command_id,
            error_code=error_code[:64],
            detail=_bounded_detail(detail),
        ),
    )


def _bounded_detail(detail: str) -> str:
    """A rejection detail the protocol model will accept."""

    return detail[:REJECTION_DETAIL_MAX_LENGTH] or "rejected"


__all__ = ["router", "websocket_browser_actor"]

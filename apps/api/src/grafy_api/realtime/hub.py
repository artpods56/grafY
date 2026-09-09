import asyncio
import logging
import time
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from fastapi import WebSocket
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect, WebSocketState

from grafy_api.realtime.protocol import (
    ActorPresentation,
    ExecutionActiveMessage,
    ExecutionClearedMessage,
    GraphCommandAcceptedMessage,
    GraphCommandReceiptMessage,
    PresenceJoinMessage,
    PresenceLeaveMessage,
    PresenceParticipant,
    PresenceUpdateMessage,
    PresenceUpdateSubmitMessage,
    RoomRehydrateMessage,
)


logger = logging.getLogger(__name__)

OUTBOUND_QUEUE_MAXSIZE = 64
PRESENCE_DROP_QUEUE_WATERMARK = 48

CLOSE_PERMISSIONS_CHANGED = (4003, "permissions_changed")
CLOSE_ACCESS_REVOKED = (4004, "access_revoked")
CLOSE_PROTOCOL_ERROR = (4008, "protocol_error")
CLOSE_SLOW_CONSUMER = (4009, "slow_consumer")
CLOSE_GRAPH_DELETED = (4010, "graph_deleted")

DEFAULT_PRESENCE_TTL_SECONDS = 5.0
DEFAULT_PRESENCE_MAX_UPDATES_PER_SECOND = 20.0


@dataclass(slots=True)
class GraphRoomSession:
    """Ephemeral WebSocket connection identity — not an authorization grant."""

    workspace_id: UUID
    graph_id: UUID
    graph_room_session_id: UUID
    actor_user_id: UUID
    credential_reference: str | None
    authorization_version: int
    actor_presentation: ActorPresentation
    websocket: WebSocket
    outbound: asyncio.Queue[BaseModel | None] = field(
        default_factory=lambda: asyncio.Queue(maxsize=OUTBOUND_QUEUE_MAXSIZE)
    )
    sender_task: asyncio.Task[None] | None = None
    closed: bool = False


@dataclass(slots=True)
class _PresenceEntry:
    participant: PresenceParticipant
    updated_at: float
    last_accept_at: float


@dataclass(slots=True)
class _RoomMember:
    """A registered room participant co-located with its ephemeral presence.

    Presence lives on the member so a delayed update cannot recreate it after
    the member has closed; TTL expiry clears presence, never membership.
    """

    session: GraphRoomSession
    presence: _PresenceEntry | None = None


class GraphRoomHub:
    """In-process hub keyed by (workspace_id, graph_id)."""

    def __init__(
        self,
        *,
        presence_ttl_seconds: float = DEFAULT_PRESENCE_TTL_SECONDS,
        presence_max_updates_per_second: float = DEFAULT_PRESENCE_MAX_UPDATES_PER_SECOND,
    ) -> None:
        self._rooms: dict[tuple[UUID, UUID], dict[UUID, _RoomMember]] = {}
        self._lock = asyncio.Lock()
        self._presence_ttl_seconds = presence_ttl_seconds
        self._presence_min_interval = (
            0.0
            if presence_max_updates_per_second <= 0
            else 1.0 / presence_max_updates_per_second
        )

    async def join(self, session: GraphRoomSession) -> None:
        """Register a session while keeping outbound delivery gated.

        Messages published after registration are buffered until ``activate``.
        This lets the room route take its authoritative head snapshot and send
        ``room.ready`` before any live event can reach the joining client.
        """

        key = (session.workspace_id, session.graph_id)
        async with self._lock:
            room = self._rooms.setdefault(key, {})
            room[session.graph_room_session_id] = _RoomMember(session=session)

    async def activate(self, session: GraphRoomSession) -> None:
        """Release buffered outbound messages for a registered session."""

        key = (session.workspace_id, session.graph_id)
        async with self._lock:
            room = self._rooms.get(key)
            member = (
                room.get(session.graph_room_session_id) if room is not None else None
            )
            if (
                session.closed
                or member is None
                or member.session is not session
                or session.sender_task is not None
            ):
                return
            session.sender_task = asyncio.create_task(self._sender_loop(session))

    async def leave(self, session: GraphRoomSession) -> None:
        await self._close_session(session, code=1000, reason="left")

    async def close_session(
        self,
        session: GraphRoomSession,
        *,
        code: int,
        reason: str,
    ) -> None:
        await self._close_session(session, code=code, reason=reason)

    def new_session_id(self) -> UUID:
        return uuid4()

    async def register_presence(self, session: GraphRoomSession) -> PresenceParticipant:
        """Add the session to ephemeral presence and fan out ``presence.join``."""

        now = time.monotonic()
        participant = PresenceParticipant(
            graph_room_session_id=session.graph_room_session_id,
            actor=session.actor_presentation,
            presence_sequence=0,
        )
        key = (session.workspace_id, session.graph_id)
        async with self._lock:
            removed, cleared = self._expire_locked(key, now)
            room = self._rooms.setdefault(key, {})
            member = room.setdefault(
                session.graph_room_session_id,
                _RoomMember(session=session),
            )
            member.presence = _PresenceEntry(
                participant=participant,
                updated_at=now,
                last_accept_at=0.0,
            )
            recipients = [
                peer.session
                for peer in room.values()
                if peer.session.graph_room_session_id != session.graph_room_session_id
                and not peer.session.closed
            ]
        await self._fanout_expiry(
            workspace_id=session.workspace_id,
            graph_id=session.graph_id,
            removed=removed,
            cleared=cleared,
        )
        join_message = PresenceJoinMessage(participant=participant)
        for peer in recipients:
            await self._enqueue_presence(peer, join_message)
        return participant

    async def participants_for(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> list[PresenceParticipant]:
        now = time.monotonic()
        key = (workspace_id, graph_id)
        async with self._lock:
            removed, cleared = self._expire_locked(key, now)
            room = self._rooms.get(key, {})
            participants = [
                member.presence.participant
                for member in room.values()
                if member.presence is not None
            ]
        await self._fanout_expiry(
            workspace_id=workspace_id,
            graph_id=graph_id,
            removed=removed,
            cleared=cleared,
        )
        return participants

    async def apply_presence_update(
        self,
        session: GraphRoomSession,
        message: PresenceUpdateSubmitMessage,
    ) -> PresenceParticipant | None:
        """Accept a rate-limited presence update and fan it out.

        Returns ``None`` when the update is dropped as stale or over budget.
        """

        now = time.monotonic()
        key = (session.workspace_id, session.graph_id)
        async with self._lock:
            removed, cleared = self._expire_locked(key, now)
            room = self._rooms.get(key)
            member = (
                room.get(session.graph_room_session_id) if room is not None else None
            )
            # A delayed update must match the exact open registered session; it
            # must never recreate presence for an already-closed member.
            if member is None or member.session is not session or session.closed:
                drop = True
                participant = None
                recipients: list[GraphRoomSession] = []
            else:
                entry = member.presence
                if entry is None:
                    entry = _PresenceEntry(
                        participant=PresenceParticipant(
                            graph_room_session_id=session.graph_room_session_id,
                            actor=session.actor_presentation,
                            presence_sequence=0,
                        ),
                        updated_at=now,
                        last_accept_at=0.0,
                    )
                    member.presence = entry
                if message.presence_sequence <= entry.participant.presence_sequence:
                    drop = True
                    participant = None
                    recipients = []
                elif (
                    self._presence_min_interval > 0
                    and entry.last_accept_at > 0
                    and (now - entry.last_accept_at) < self._presence_min_interval
                ):
                    drop = True
                    participant = None
                    recipients = []
                else:
                    drop = False
                    participant = PresenceParticipant(
                        graph_room_session_id=session.graph_room_session_id,
                        actor=session.actor_presentation,
                        presence_sequence=message.presence_sequence,
                        cursor=message.cursor,
                        selected_node_ids=message.selected_node_ids,
                        selected_edge_ids=message.selected_edge_ids,
                        activity=message.activity,
                        activity_target_ids=message.activity_target_ids,
                        transient_node_positions=message.transient_node_positions,
                    )
                    entry.participant = participant
                    entry.updated_at = now
                    entry.last_accept_at = now
                    recipients = [
                        peer.session
                        for peer in room.values()
                        if peer.session.graph_room_session_id
                        != session.graph_room_session_id
                        and not peer.session.closed
                    ]
        await self._fanout_expiry(
            workspace_id=session.workspace_id,
            graph_id=session.graph_id,
            removed=removed,
            cleared=cleared,
        )
        if drop or participant is None:
            return None
        update_message = PresenceUpdateMessage(participant=participant)
        for peer in recipients:
            await self._enqueue_presence(peer, update_message)
        return participant

    async def publish_accepted(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        accepted: GraphCommandAcceptedMessage,
        receipt: GraphCommandReceiptMessage | None = None,
        receipt_session_id: UUID | None = None,
    ) -> None:
        sessions = await self._sessions_for(workspace_id, graph_id)
        for session in sessions:
            await self._enqueue(session, accepted)
            if (
                receipt is not None
                and receipt_session_id is not None
                and session.graph_room_session_id == receipt_session_id
            ):
                await self._enqueue(session, receipt)

    async def deliver_private(
        self,
        session: GraphRoomSession,
        message: BaseModel,
    ) -> None:
        """Deliver a private message (e.g. idempotent receipt) without fanout."""

        await self._enqueue(session, message)

    async def publish_rehydrate(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        message: RoomRehydrateMessage,
    ) -> None:
        for session in await self._sessions_for(workspace_id, graph_id):
            await self._enqueue(session, message)

    async def publish_execution_active(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        message: ExecutionActiveMessage,
    ) -> None:
        for session in await self._sessions_for(workspace_id, graph_id):
            await self._enqueue(session, message)

    async def publish_execution_cleared(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        message: ExecutionClearedMessage,
    ) -> None:
        for session in await self._sessions_for(workspace_id, graph_id):
            await self._enqueue(session, message)

    async def close_graph(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        code: int = CLOSE_GRAPH_DELETED[0],
        reason: str = CLOSE_GRAPH_DELETED[1],
    ) -> None:
        for session in await self._sessions_for(workspace_id, graph_id):
            await self._close_session(session, code=code, reason=reason)

    async def close_workspace_user(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        code: int,
        reason: str,
    ) -> None:
        sessions = await self._sessions_for_workspace_user(workspace_id, user_id)
        for session in sessions:
            await self._close_session(session, code=code, reason=reason)

    async def shutdown(self) -> None:
        async with self._lock:
            sessions = [
                member.session
                for room in self._rooms.values()
                for member in room.values()
            ]
            self._rooms.clear()
        for session in sessions:
            await self._close_session(session, code=1001, reason="shutdown")

    async def _sessions_for(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> list[GraphRoomSession]:
        async with self._lock:
            room = self._rooms.get((workspace_id, graph_id), {})
            return [member.session for member in room.values()]

    async def _sessions_for_workspace_user(
        self,
        workspace_id: UUID,
        user_id: UUID,
    ) -> list[GraphRoomSession]:
        async with self._lock:
            matched: list[GraphRoomSession] = []
            for (room_workspace_id, _graph_id), room in self._rooms.items():
                if room_workspace_id != workspace_id:
                    continue
                for member in room.values():
                    if member.session.actor_user_id == user_id:
                        matched.append(member.session)
            return matched

    def _expire_locked(
        self,
        key: tuple[UUID, UUID],
        now: float,
    ) -> tuple[list[UUID], list[PresenceParticipant]]:
        """Clear stale cursor/activity fields; clear presence idle past 2× TTL.

        TTL expiry clears presence but never room membership, so a participant
        that stops updating stays registered until it closes.
        """

        room = self._rooms.get(key)
        if not room:
            return [], []
        removed: list[UUID] = []
        cleared: list[PresenceParticipant] = []
        ttl = self._presence_ttl_seconds
        remove_after = ttl * 2
        for session_id, member in list(room.items()):
            entry = member.presence
            if entry is None:
                continue
            age = now - entry.updated_at
            if age >= remove_after:
                member.presence = None
                removed.append(session_id)
                continue
            if age < ttl:
                continue
            participant = entry.participant
            if (
                participant.cursor is None
                and not participant.selected_node_ids
                and not participant.selected_edge_ids
                and participant.activity is None
                and not participant.activity_target_ids
                and not participant.transient_node_positions
            ):
                continue
            entry.participant = PresenceParticipant(
                graph_room_session_id=participant.graph_room_session_id,
                actor=participant.actor,
                presence_sequence=participant.presence_sequence,
            )
            cleared.append(entry.participant)
        return removed, cleared

    async def _fanout_expiry(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        removed: list[UUID],
        cleared: list[PresenceParticipant],
    ) -> None:
        if not removed and not cleared:
            return
        sessions = await self._sessions_for(workspace_id, graph_id)
        for session_id in removed:
            message = PresenceLeaveMessage(graph_room_session_id=session_id)
            for session in sessions:
                await self._enqueue_presence(session, message)
        for participant in cleared:
            message = PresenceUpdateMessage(participant=participant)
            for session in sessions:
                if session.graph_room_session_id == participant.graph_room_session_id:
                    continue
                await self._enqueue_presence(session, message)

    async def _enqueue(self, session: GraphRoomSession, message: BaseModel) -> None:
        if session.closed:
            return
        try:
            session.outbound.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning(
                "graph_room_slow_consumer workspace_id=%s graph_id=%s "
                "graph_room_session_id=%s",
                session.workspace_id,
                session.graph_id,
                session.graph_room_session_id,
            )
            await self._close_session(
                session,
                code=CLOSE_SLOW_CONSUMER[0],
                reason=CLOSE_SLOW_CONSUMER[1],
            )

    async def _enqueue_presence(
        self,
        session: GraphRoomSession,
        message: BaseModel,
    ) -> None:
        """Best-effort presence delivery; drop under backpressure before disconnect."""

        if session.closed:
            return
        if session.outbound.qsize() >= PRESENCE_DROP_QUEUE_WATERMARK:
            return
        try:
            session.outbound.put_nowait(message)
        except asyncio.QueueFull:
            return

    async def _sender_loop(self, session: GraphRoomSession) -> None:
        try:
            while True:
                message = await session.outbound.get()
                if message is None or session.closed:
                    return
                if session.websocket.application_state != WebSocketState.CONNECTED:
                    return
                await session.websocket.send_json(message.model_dump(mode="json"))
        except WebSocketDisconnect:
            return
        except Exception:
            logger.exception(
                "graph_room_sender_failed workspace_id=%s graph_id=%s "
                "graph_room_session_id=%s",
                session.workspace_id,
                session.graph_id,
                session.graph_room_session_id,
            )
            await self._close_session(
                session,
                code=CLOSE_PROTOCOL_ERROR[0],
                reason=CLOSE_PROTOCOL_ERROR[1],
            )

    async def _close_session(
        self,
        session: GraphRoomSession,
        *,
        code: int,
        reason: str,
    ) -> None:
        if session.closed:
            return
        session.closed = True
        key = (session.workspace_id, session.graph_id)
        leave_recipients: list[GraphRoomSession] = []
        had_presence = False
        async with self._lock:
            room = self._rooms.get(key)
            if room is not None:
                member = room.get(session.graph_room_session_id)
                had_presence = member is not None and member.presence is not None
                room.pop(session.graph_room_session_id, None)
                if had_presence:
                    leave_recipients = [
                        peer.session
                        for peer in room.values()
                        if not peer.session.closed
                    ]
                if not room:
                    self._rooms.pop(key, None)
        if had_presence:
            leave_message = PresenceLeaveMessage(
                graph_room_session_id=session.graph_room_session_id,
            )
            for peer in leave_recipients:
                await self._enqueue_presence(peer, leave_message)
        if (
            session.sender_task is not None
            and session.sender_task is not asyncio.current_task()
        ):
            session.sender_task.cancel()
        try:
            session.outbound.put_nowait(None)
        except asyncio.QueueFull:
            pass
        if session.websocket.application_state == WebSocketState.CONNECTED:
            try:
                await session.websocket.close(code=code, reason=reason[:123])
            except Exception:
                logger.debug(
                    "graph_room_close_failed workspace_id=%s graph_id=%s "
                    "graph_room_session_id=%s",
                    session.workspace_id,
                    session.graph_id,
                    session.graph_room_session_id,
                    exc_info=True,
                )

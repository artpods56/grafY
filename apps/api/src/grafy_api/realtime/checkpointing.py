"""Schedule immutable checkpoints in the process that owns the Project rooms."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple
from uuid import UUID

from grafy_core.application.collaboration import CollaborationService
from grafy_core.domain.collaboration import ProjectHead
from grafy_shared.config import RealtimeConfig

from grafy_api.realtime.hub import SENDER_STOP_TIMEOUT_SECONDS, ProjectRoomHub

logger = logging.getLogger(__name__)

RoomKey = tuple[UUID, UUID]
ScheduleTimer = Callable[[float, Callable[[], None]], asyncio.TimerHandle]


class _HeadPosition(NamedTuple):
    epoch: UUID
    sequence: int
    checkpoint_revision: int


@dataclass
class _PendingCheckpoint:
    # Only retain the position, since the transaction reads the actual document.
    position: _HeadPosition | None = None
    timer: asyncio.TimerHandle | None = None
    task: asyncio.Task[None] | None = None
    flush_requested: bool = False

    def cancel_timer(self) -> None:
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None


class ProjectAutoCheckpointer:
    def __init__(
        self,
        collaboration: CollaborationService,
        hub: ProjectRoomHub,
        settings: RealtimeConfig,
        *,
        schedule_timer: ScheduleTimer | None = None,
    ) -> None:
        self._collaboration = collaboration
        self._hub = hub
        self._idle_seconds = settings.graph_room_auto_checkpoint_idle_seconds
        self._max_commands = settings.graph_room_auto_checkpoint_max_commands
        self._schedule_timer = schedule_timer
        self._pending: dict[RoomKey, _PendingCheckpoint] = {}
        self._closed = False

    def note_head_advanced(self, head: ProjectHead) -> None:
        if self._closed or head.is_fully_checkpointed:
            return
        key = (head.workspace_id, head.project_id)
        pending = self._pending.setdefault(key, _PendingCheckpoint())
        current = pending.position
        if current is not None:
            if current.epoch == head.room_epoch:
                if current.sequence >= head.collaboration_sequence:
                    return
            elif current.checkpoint_revision >= head.checkpoint_revision:
                return
        pending.position = _HeadPosition(
            head.room_epoch, head.collaboration_sequence, head.checkpoint_revision
        )
        pending.cancel_timer()
        if (
            self._max_commands
            and head.collaboration_sequence - head.checkpoint_sequence
            >= self._max_commands
        ):
            self._flush(pending, key)
        elif self._idle_seconds > 0:
            schedule = self._schedule_timer or asyncio.get_running_loop().call_later
            pending.timer = schedule(
                self._idle_seconds, lambda: self._flush(pending, key)
            )

    def note_room_empty(self, workspace_id: UUID, project_id: UUID) -> None:
        key = (workspace_id, project_id)
        pending = self._pending.get(key)
        if pending is not None and not self._closed:
            self._flush(pending, key)

    def note_checkpointed(self, head: ProjectHead) -> None:
        key = (head.workspace_id, head.project_id)
        pending = self._pending.get(key)
        if pending is None or pending.position is None:
            return
        position = pending.position
        if (
            position.epoch == head.room_epoch
            and position.sequence <= head.checkpoint_sequence
        ):
            self.cancel(*key)

    def note_restored(self, head: ProjectHead) -> None:
        key = (head.workspace_id, head.project_id)
        pending = self._pending.get(key)
        if pending is None or pending.position is None:
            return
        position = pending.position
        if (
            position.epoch != head.room_epoch
            and position.checkpoint_revision < head.checkpoint_revision
        ):
            self.cancel(*key)

    def cancel(self, workspace_id: UUID, project_id: UUID) -> None:
        key = (workspace_id, project_id)
        pending = self._pending.get(key)
        if pending is None:
            return
        pending.cancel_timer()
        pending.position = None
        pending.flush_requested = False
        if pending.task is None:
            del self._pending[key]

    def _flush(self, pending: _PendingCheckpoint, key: RoomKey) -> None:
        pending.cancel_timer()
        if pending.position is None:
            return
        pending.flush_requested = True
        if pending.task is None:
            pending.task = asyncio.create_task(self._checkpoint(pending, key))

    async def _checkpoint(self, pending: _PendingCheckpoint, key: RoomKey) -> None:
        workspace_id, project_id = key
        try:
            while pending.flush_requested and pending.position is not None:
                position = pending.position
                pending.flush_requested = False
                try:
                    outcome = await self._collaboration.checkpoint_head_if_needed(
                        workspace_id=workspace_id, project_id=project_id
                    )
                    if outcome is None:
                        if pending.position == position:
                            self.cancel(*key)
                    else:
                        self.note_checkpointed(outcome.head)
                        await self._hub.publish_checkpointed(outcome.head)
                except Exception:
                    logger.exception(
                        "project_auto_checkpoint_failed workspace_id=%s project_id=%s",
                        workspace_id,
                        project_id,
                    )
        finally:
            pending.task = None
            if pending.position is None:
                del self._pending[key]

    async def shutdown(self) -> None:
        self._closed = True
        tasks: set[asyncio.Task[None]] = set()
        for key, pending in self._pending.items():
            self._flush(pending, key)
            if pending.task is not None:
                tasks.add(pending.task)
        if not tasks:
            return

        _, remaining = await asyncio.wait(tasks, timeout=SENDER_STOP_TIMEOUT_SECONDS)
        for task in remaining:
            task.cancel()
        if remaining:
            _, remaining = await asyncio.wait(
                remaining, timeout=SENDER_STOP_TIMEOUT_SECONDS
            )
        if remaining:
            logger.error(
                "project_auto_checkpoint_shutdown_timeout pending_tasks=%s",
                len(remaining),
            )
        for key in tuple(self._pending):
            self.cancel(*key)

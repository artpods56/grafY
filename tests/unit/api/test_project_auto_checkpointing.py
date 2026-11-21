import asyncio
from collections.abc import Callable
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

from grafy_api.realtime.checkpointing import ProjectAutoCheckpointer
from grafy_api.realtime.hub import ProjectRoomHub
from grafy_core.application.collaboration import CheckpointOutcome, CollaborationService
from grafy_core.domain.collaboration import ProjectHead, empty_project_document
from grafy_shared.config import RealtimeConfig


class ManualTimers:
    def __init__(self) -> None:
        self.handles: list[asyncio.TimerHandle] = []
        self.callbacks: list[Callable[[], None]] = []

    def schedule(
        self, delay: float, callback: Callable[[], None]
    ) -> asyncio.TimerHandle:
        loop = asyncio.get_running_loop()
        handle = asyncio.TimerHandle(loop.time() + delay, callback, (), loop)
        self.handles.append(handle)
        self.callbacks.append(callback)
        return handle

    def fire_latest(self) -> None:
        assert not self.handles[-1].cancelled()
        self.callbacks[-1]()


def head_at(sequence: int, *, checkpoint: int = 0) -> ProjectHead:
    return ProjectHead(
        workspace_id=uuid4(),
        project_id=uuid4(),
        room_epoch=uuid4(),
        collaboration_sequence=sequence,
        checkpoint_sequence=checkpoint,
        checkpoint_revision=checkpoint + 1,
        name="Project",
        document=empty_project_document("main", "Main"),
    )


async def test_idle_debounce_restarts_when_another_batch_is_accepted() -> None:
    service = AsyncMock(spec=CollaborationService)
    hub = AsyncMock(spec=ProjectRoomHub)
    timers = ManualTimers()
    coordinator = ProjectAutoCheckpointer(
        service, hub, RealtimeConfig(), schedule_timer=timers.schedule
    )
    head = head_at(1)
    coordinator.note_head_advanced(head)
    head.collaboration_sequence = 2
    coordinator.note_head_advanced(head)
    assert timers.handles[0].cancelled()
    service.checkpoint_head_if_needed.assert_not_awaited()

    finished = asyncio.Event()
    head.record_checkpoint(sequence=2, revision=2)
    service.checkpoint_head_if_needed.return_value = CheckpointOutcome(
        head=head, revision=2
    )
    hub.publish_checkpointed.side_effect = lambda _: finished.set()
    timers.fire_latest()
    await finished.wait()
    await coordinator.shutdown()

    service.checkpoint_head_if_needed.assert_awaited_once_with(
        workspace_id=head.workspace_id, project_id=head.project_id
    )
    hub.publish_checkpointed.assert_awaited_once_with(head)


async def test_threshold_and_empty_room_flushes_coalesce_while_checkpointing() -> None:
    service = AsyncMock(spec=CollaborationService)
    hub = AsyncMock(spec=ProjectRoomHub)
    coordinator = ProjectAutoCheckpointer(
        service,
        hub,
        RealtimeConfig(
            graph_room_auto_checkpoint_idle_seconds=0,
            graph_room_auto_checkpoint_max_commands=2,
        ),
    )
    started = asyncio.Event()
    release = asyncio.Event()
    published_twice = asyncio.Event()
    head = head_at(1)
    first_snapshot = replace(
        head, collaboration_sequence=2, checkpoint_sequence=2, checkpoint_revision=2
    )
    final_snapshot = replace(
        first_snapshot,
        collaboration_sequence=4,
        checkpoint_sequence=4,
        checkpoint_revision=3,
    )

    async def checkpoint(**_: object) -> CheckpointOutcome:
        if not started.is_set():
            started.set()
            await release.wait()
            return CheckpointOutcome(head=first_snapshot, revision=2)
        return CheckpointOutcome(head=final_snapshot, revision=3)

    def publish(snapshot: ProjectHead) -> None:
        if snapshot.checkpoint_revision == 3:
            published_twice.set()

    service.checkpoint_head_if_needed.side_effect = checkpoint
    hub.publish_checkpointed.side_effect = publish
    coordinator.note_head_advanced(head)
    head.collaboration_sequence = 2
    coordinator.note_head_advanced(head)
    await started.wait()

    for sequence in (3, 4):
        head.collaboration_sequence = sequence
        coordinator.note_head_advanced(head)
        coordinator.note_room_empty(head.workspace_id, head.project_id)

    assert service.checkpoint_head_if_needed.await_count == 1
    release.set()
    await published_twice.wait()
    await coordinator.shutdown()
    assert service.checkpoint_head_if_needed.await_count == 2


async def test_delete_restore_and_explicit_checkpoint_cancel_idle_checkpoint() -> None:
    service = AsyncMock(spec=CollaborationService)
    hub = AsyncMock(spec=ProjectRoomHub)
    timers = ManualTimers()
    coordinator = ProjectAutoCheckpointer(
        service, hub, RealtimeConfig(), schedule_timer=timers.schedule
    )
    deleted, restored, saved = (head_at(1) for _ in range(3))
    for head in (deleted, restored, saved):
        coordinator.note_head_advanced(head)

    coordinator.cancel(deleted.workspace_id, deleted.project_id)
    coordinator.note_restored(
        replace(restored, room_epoch=uuid4(), checkpoint_revision=2)
    )
    saved.record_checkpoint(sequence=1, revision=2)
    coordinator.note_checkpointed(saved)
    assert all(timer.cancelled() for timer in timers.handles)

    await coordinator.shutdown()
    service.checkpoint_head_if_needed.assert_not_awaited()


async def test_room_empty_and_shutdown_flush_pending_work_with_both_timers_disabled() -> (
    None
):
    service = AsyncMock(spec=CollaborationService)
    hub = AsyncMock(spec=ProjectRoomHub)
    coordinator = ProjectAutoCheckpointer(
        service,
        hub,
        RealtimeConfig(
            graph_room_auto_checkpoint_idle_seconds=0,
            graph_room_auto_checkpoint_max_commands=0,
        ),
    )
    room_departed, still_open = head_at(1), head_at(2)
    coordinator.note_head_advanced(room_departed)
    coordinator.note_head_advanced(still_open)
    awaitable_called = asyncio.Event()

    async def checkpoint(*, workspace_id: object, project_id: object) -> None:
        if (workspace_id, project_id) == (
            room_departed.workspace_id,
            room_departed.project_id,
        ):
            awaitable_called.set()

    service.checkpoint_head_if_needed.side_effect = checkpoint
    coordinator.note_room_empty(room_departed.workspace_id, room_departed.project_id)
    await awaitable_called.wait()
    await coordinator.shutdown()
    assert service.checkpoint_head_if_needed.await_count == 2
    assert not any(
        task.get_coro().__qualname__ == "ProjectAutoCheckpointer._checkpoint"
        for task in asyncio.all_tasks()
    )


async def test_restore_keeps_batches_already_committed_in_the_new_epoch() -> None:
    service = AsyncMock(spec=CollaborationService)
    service.checkpoint_head_if_needed.return_value = None
    timers = ManualTimers()
    coordinator = ProjectAutoCheckpointer(
        service,
        AsyncMock(spec=ProjectRoomHub),
        RealtimeConfig(),
        schedule_timer=timers.schedule,
    )
    previous = head_at(4)
    restored = replace(
        previous, room_epoch=uuid4(), collaboration_sequence=0, checkpoint_revision=3
    )
    current = replace(restored, collaboration_sequence=1)
    coordinator.note_head_advanced(current)
    coordinator.note_restored(restored)
    coordinator.note_head_advanced(previous)

    assert len(timers.handles) == 1
    assert not timers.handles[0].cancelled()
    await coordinator.shutdown()
    service.checkpoint_head_if_needed.assert_awaited_once_with(
        workspace_id=current.workspace_id, project_id=current.project_id
    )


async def test_failed_checkpoint_retries_without_another_edit() -> None:
    service = AsyncMock(spec=CollaborationService)
    hub = AsyncMock(spec=ProjectRoomHub)
    timers = ManualTimers()
    retry_scheduled = asyncio.Event()
    published = asyncio.Event()
    head = head_at(1)
    checkpointed = replace(head, checkpoint_sequence=1, checkpoint_revision=2)
    service.checkpoint_head_if_needed.side_effect = [
        RuntimeError("database unavailable"),
        CheckpointOutcome(head=checkpointed, revision=2),
    ]
    hub.publish_checkpointed.side_effect = lambda _: published.set()

    def schedule(delay: float, callback: Callable[[], None]) -> asyncio.TimerHandle:
        handle = timers.schedule(delay, callback)
        if len(timers.handles) == 2:
            retry_scheduled.set()
        return handle

    coordinator = ProjectAutoCheckpointer(
        service, hub, RealtimeConfig(), schedule_timer=schedule
    )
    coordinator.note_head_advanced(head)
    timers.fire_latest()
    await retry_scheduled.wait()
    timers.fire_latest()
    await published.wait()
    await coordinator.shutdown()

    assert service.checkpoint_head_if_needed.await_count == 2
    hub.publish_checkpointed.assert_awaited_once_with(checkpointed)

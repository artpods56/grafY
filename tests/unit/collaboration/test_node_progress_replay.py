"""In-memory ``node.progress`` replay on ``room.ready``.

The hub keeps a bounded buffer per project. A joiner receives only the frames
whose instances are still queued or running, oldest first. Finished work is
not written anywhere, and a refresh must not show it as still running.
"""

import json
from pathlib import Path
from uuid import UUID, uuid4

from grafy_api.realtime.hub import ProjectRoomHub
from grafy_api.realtime.protocol import (
    InstanceKeyEntry,
    InstanceStateEntry,
    InstanceStateName,
    InstancesChangedMessage,
    NodeProgressMessage,
    RoomReadyMessage,
    RunFinishedMessage,
)

_FRAMES_PER_INSTANCE = 20
_INSTANCES_PER_PROJECT = 128

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _key(project_id: UUID, node_id: str) -> InstanceKeyEntry:
    return InstanceKeyEntry(
        project_id=project_id,
        graph_id="graph",
        node_id=node_id,
    )


def _progress(
    project_id: UUID,
    node_id: str,
    *,
    sequence: int,
    computation_id: UUID,
    fingerprint: str = "fp",
    message: str = "Scanning",
) -> NodeProgressMessage:
    return NodeProgressMessage(
        instance=_key(project_id, node_id),
        fingerprint=fingerprint,
        computation_id=computation_id,
        sequence=sequence,
        message=message,
        current=sequence,
        total=30,
    )


def _state(
    project_id: UUID,
    node_id: str,
    state: InstanceStateName,
    *,
    fingerprint: str = "fp",
) -> InstanceStateEntry:
    return InstanceStateEntry(
        project_id=project_id,
        graph_id="graph",
        node_id=node_id,
        state=state,
        fingerprint=fingerprint,
    )


async def _publish(
    hub: ProjectRoomHub,
    workspace_id: UUID,
    project_id: UUID,
    message: NodeProgressMessage,
) -> None:
    await hub.publish_node_progress(
        workspace_id=workspace_id,
        project_id=project_id,
        message=message,
    )


async def test_room_ready_replays_only_the_active_instance_oldest_first() -> None:
    hub = ProjectRoomHub()
    workspace_id = uuid4()
    project_id = uuid4()
    other_project = uuid4()
    computation = uuid4()
    await _publish(
        hub,
        workspace_id,
        project_id,
        _progress(project_id, "ocr", sequence=1, computation_id=computation),
    )
    await _publish(
        hub,
        workspace_id,
        project_id,
        _progress(
            project_id,
            "ocr",
            sequence=2,
            computation_id=computation,
            message="Parsing",
        ),
    )
    await _publish(
        hub,
        workspace_id,
        other_project,
        _progress(other_project, "ocr", sequence=9, computation_id=uuid4()),
    )
    active = (
        _state(project_id, "ocr", "running"),
        _state(project_id, "done", "fresh"),
    )

    frames = await hub.snapshot_node_progress(
        workspace_id, project_id, active_instances=active
    )

    assert [frame.sequence for frame in frames] == [1, 2]
    assert [frame.message for frame in frames] == ["Scanning", "Parsing"]
    assert (
        await hub.snapshot_node_progress(
            workspace_id, other_project, active_instances=()
        )
        == ()
    )


async def test_a_new_computation_replaces_that_instance() -> None:
    hub = ProjectRoomHub()
    workspace_id = uuid4()
    project_id = uuid4()
    first = uuid4()
    second = uuid4()
    await _publish(
        hub,
        workspace_id,
        project_id,
        _progress(project_id, "ocr", sequence=1, computation_id=first),
    )
    await _publish(
        hub,
        workspace_id,
        project_id,
        _progress(
            project_id,
            "ocr",
            sequence=1,
            computation_id=second,
            fingerprint="next",
            message="Again",
        ),
    )

    frames = await hub.snapshot_node_progress(
        workspace_id,
        project_id,
        active_instances=(_state(project_id, "ocr", "queued", fingerprint="next"),),
    )

    assert [(frame.computation_id, frame.message) for frame in frames] == [
        (second, "Again")
    ]


async def test_the_buffer_is_bounded_per_instance_and_per_project() -> None:
    hub = ProjectRoomHub()
    workspace_id = uuid4()
    project_id = uuid4()
    computation = uuid4()
    for sequence in range(1, _FRAMES_PER_INSTANCE + 2):
        await _publish(
            hub,
            workspace_id,
            project_id,
            _progress(project_id, "ocr", sequence=sequence, computation_id=computation),
        )
    ocr = await hub.snapshot_node_progress(
        workspace_id,
        project_id,
        active_instances=(_state(project_id, "ocr", "running"),),
    )
    assert [frame.sequence for frame in ocr] == list(range(2, _FRAMES_PER_INSTANCE + 2))

    for index in range(_INSTANCES_PER_PROJECT + 1):
        await _publish(
            hub,
            workspace_id,
            project_id,
            _progress(
                project_id,
                f"n{index:03d}",
                sequence=1,
                computation_id=uuid4(),
                fingerprint=f"fp-{index}",
            ),
        )
    active = tuple(
        _state(project_id, f"n{index:03d}", "running", fingerprint=f"fp-{index}")
        for index in range(_INSTANCES_PER_PROJECT + 1)
    )
    crowded = await hub.snapshot_node_progress(
        workspace_id, project_id, active_instances=active
    )
    assert [frame.instance.node_id for frame in crowded] == [
        f"n{index:03d}" for index in range(1, _INSTANCES_PER_PROJECT + 1)
    ]


async def test_instances_changed_drops_one_node_and_keeps_the_other() -> None:
    hub = ProjectRoomHub()
    workspace_id = uuid4()
    project_id = uuid4()
    await _publish(
        hub,
        workspace_id,
        project_id,
        _progress(project_id, "ocr", sequence=1, computation_id=uuid4()),
    )
    await _publish(
        hub,
        workspace_id,
        project_id,
        _progress(
            project_id,
            "label",
            sequence=4,
            computation_id=uuid4(),
            fingerprint="label-fp",
            message="Reading",
        ),
    )
    await hub.publish_run_finished(
        workspace_id=workspace_id,
        project_id=project_id,
        message=RunFinishedMessage(run_id=uuid4(), status="succeeded"),
    )
    await hub.publish_instances_changed(
        workspace_id=workspace_id,
        project_id=project_id,
        message=InstancesChangedMessage(
            changed=(_state(project_id, "ocr", "fresh"),),
            removed=(),
            head_sequence=3,
        ),
    )

    frames = await hub.snapshot_node_progress(
        workspace_id,
        project_id,
        active_instances=(
            _state(project_id, "ocr", "fresh"),
            _state(project_id, "label", "running", fingerprint="label-fp"),
        ),
    )

    assert [frame.instance.node_id for frame in frames] == ["label"]


async def test_snapshot_prunes_a_removed_instance_and_a_stale_fingerprint() -> None:
    hub = ProjectRoomHub()
    workspace_id = uuid4()
    project_id = uuid4()
    await _publish(
        hub,
        workspace_id,
        project_id,
        _progress(project_id, "gone", sequence=1, computation_id=uuid4()),
    )
    await _publish(
        hub,
        workspace_id,
        project_id,
        _progress(
            project_id,
            "ocr",
            sequence=2,
            computation_id=uuid4(),
            fingerprint="old",
        ),
    )
    await hub.publish_instances_changed(
        workspace_id=workspace_id,
        project_id=project_id,
        message=InstancesChangedMessage(
            changed=(),
            removed=(_key(project_id, "gone"),),
            head_sequence=4,
        ),
    )

    first = await hub.snapshot_node_progress(
        workspace_id,
        project_id,
        active_instances=(_state(project_id, "ocr", "running", fingerprint="new"),),
    )
    second = await hub.snapshot_node_progress(
        workspace_id,
        project_id,
        active_instances=(
            _state(project_id, "gone", "running"),
            _state(project_id, "ocr", "running", fingerprint="old"),
        ),
    )

    assert first == ()
    assert second == ()


def test_room_ready_accepts_a_payload_that_omits_node_progress() -> None:
    payload = json.loads((FIXTURES / "project_room_ready.v1.json").read_text())
    ready = RoomReadyMessage.model_validate(payload)
    assert ready.node_progress == ()
    assert ready.model_dump(mode="json")["node_progress"] == []

    frame = _progress(ready.project_id, "first", sequence=1, computation_id=uuid4())
    with_progress = ready.model_copy(update={"node_progress": (frame,)})
    again = RoomReadyMessage.model_validate(with_progress.model_dump(mode="json"))
    assert again.node_progress[0].sequence == 1
    assert again.node_progress[0].instance.node_id == "first"

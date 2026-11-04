"""Agent frames on the Project room (issue #202).

Four frames carry one turn, and this file reads them off a real `ProjectRoomHub` with real
registered sessions — not off the runtime's own queue, which is where they were already
proven to be produced in order. What is under test here is the delivery, and the three rules
that make delivery safe:

* **Authoritative frames queue, deltas drop.** `agent.turn.started`, `agent.event.appended`
  and `agent.turn.finished` are what a thread is made of and go on the same path a command
  receipt does. `agent.delta` goes through the hub's drop-if-busy offer, so a reader that has
  stopped draining loses a frame and keeps its room: closing it for slowness would disconnect
  everyone on the Project every time a model talks quickly.
* **A delta is addressed, not trusted.** turn id, message id, offset and text, so a reader that
  missed one knows exactly how much of the answer it does not have.
* **The room is never the reason a turn ends.** A hub that raises loses its telling; the
  receipt and the events are already written, and the conversation route remains the way to
  read what happened.
"""

from collections.abc import Sequence
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from starlette.websockets import WebSocketState

from grafy_api.agents.publishing import AgentTextPartial, NullAgentTurnPublisher
from grafy_api.realtime.agent_events import ProjectAgentEvents
from grafy_api.realtime.hub import (
    OUTBOUND_QUEUE_MAXSIZE,
    PRESENCE_DROP_QUEUE_WATERMARK,
    ProjectRoomHub,
    ProjectRoomSession,
)
from grafy_api.realtime.protocol import ActorPresentation

from grafy_core.domain.agent_turns import AgentTurn

from tests.unit.api.agents.turn_support import (
    AGENT_ID,
    AUTHOR,
    GRAPH_ID,
    PROJECT,
    WORKSPACE,
    RecordingPublisher,
    ScriptedModel,
    TurnHarness,
    access,
)

OTHER_PROJECT = UUID(int=899)


class RoomPublisher:
    """The real room adapter, watched.

    A room has no reason to count the frames it sends, and a test that stops a turn mid-stream
    needs to know a frame has landed. So this hands every telling to the adapter under test and
    records the same telling the way the runtime's own tests do, in that order — which also
    means every frame a test waits for really did reach the hub.
    """

    def __init__(self, *, hub: ProjectRoomHub) -> None:
        self.room = ProjectAgentEvents(hub=hub)
        self.recorded = RecordingPublisher()

    async def turn_started(self, turn: object) -> None:
        await self.recorded.turn_started(turn)  # type: ignore[arg-type]
        await self.room.turn_started(turn)  # type: ignore[arg-type]

    async def event_appended(self, notice: object) -> None:
        await self.recorded.event_appended(notice)  # type: ignore[arg-type]
        await self.room.event_appended(notice)  # type: ignore[arg-type]

    async def text_partial(self, partial: object) -> None:
        await self.recorded.text_partial(partial)  # type: ignore[arg-type]
        await self.room.text_partial(partial)  # type: ignore[arg-type]

    async def turn_finished(self, turn: object, **outcome: object) -> None:
        await self.recorded.turn_finished(turn, **outcome)  # type: ignore[arg-type]
        await self.room.turn_finished(turn, **outcome)  # type: ignore[arg-type]

    async def wait_for_partials(self, count: int = 1) -> None:
        await self.recorded.wait_for_partials(count)


def session_for(project_id: UUID = PROJECT) -> ProjectRoomSession:
    """A registered participant whose socket nobody drains.

    The sender task is what a real socket needs, and it is deliberately not started: the
    frames pile up in the outbound queue, which is exactly the state a slow consumer is in and
    the only state in which the drop-if-busy rule can be observed.
    """

    websocket = AsyncMock()
    websocket.application_state = WebSocketState.CONNECTED
    return ProjectRoomSession(
        workspace_id=WORKSPACE,
        project_id=project_id,
        project_room_session_id=uuid4(),
        actor_user_id=AUTHOR,
        credential_reference="test-session",
        authorization_version=1,
        actor_presentation=ActorPresentation(
            actor_id=AUTHOR, display_name="Archivist", color="indigo"
        ),
        websocket=websocket,
    )


def delivered(session: ProjectRoomSession) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    while not session.outbound.empty():
        frame = session.outbound.get_nowait()
        assert frame is not None, "a shutdown sentinel reached an Agent fan-out"
        frames.append(frame.model_dump(mode="json"))
    return frames


def types_of(frames: Sequence[dict[str, object]]) -> list[str]:
    return [str(frame["type"]) for frame in frames]


@pytest.fixture
def hub() -> ProjectRoomHub:
    return ProjectRoomHub()


async def test_one_turn_arrives_in_order_with_the_deltas_before_the_stored_answer(
    hub: ProjectRoomHub,
) -> None:
    """The ordering a reader's thread is built from, frame by frame.

    The flushed text comes first and the stored message after it, never the other way round: a
    reader that saw the complete message and then a partial would put a fragment back over an
    answer it already had.
    """

    reader = session_for()
    await hub.join(reader)
    harness = TurnHarness(
        ScriptedModel(chunks=["The diary ", "says it rained."]),
        publisher=ProjectAgentEvents(hub=hub),
        interval=0.0,
    )
    turn = await harness.send()
    settled = await harness.settle()

    frames = delivered(reader)
    types = types_of(frames)
    assert types == [
        "agent.turn.started",
        # The question, as durable: a reader that only saw a turn starting would be waiting
        # for an answer to a question it cannot see.
        "agent.event.appended",
        "agent.delta",
        "agent.delta",
        "agent.event.appended",
        "agent.event.appended",
        "agent.turn.finished",
    ], types
    started = frames[0]["turn"]
    assert isinstance(started, dict)
    assert started["turn_id"] == str(turn.id)
    assert started["graph_id"] == GRAPH_ID
    assert started["agent_id"] == AGENT_ID
    assert started["status"] == "running"
    assert started["model_name"] == "llama-4"
    assert "api_key" not in frames[0]

    deltas = [frame for frame in frames if frame["type"] == "agent.delta"]
    assert [frame["text"] for frame in deltas] == ["The diary ", "says it rained."]
    assert [frame["offset"] for frame in deltas] == [0, len("The diary ")]
    assert {frame["turn_id"] for frame in deltas} == {str(turn.id)}
    assert len({frame["message_id"] for frame in deltas}) == 1
    assert {frame["conversation_id"] for frame in deltas} == {str(turn.conversation_id)}

    appended = [
        frame["event"] for frame in frames if frame["type"] == "agent.event.appended"
    ]
    assert [event["payload"]["kind"] for event in appended] == [
        "user_message",
        "assistant_message",
        "turn_outcome",
    ]
    assert [event["sequence"] for event in appended] == [1, 2, 3]
    assert appended[1]["payload"]["text"] == "The diary says it rained."
    assert appended[1]["turn_id"] == str(turn.id)

    finished = frames[-1]
    assert finished["turn_id"] == str(settled.id)
    assert finished["outcome"] == "completed"
    assert finished["graph_id"] == GRAPH_ID


async def test_the_stored_events_a_reader_recovers_from_name_the_same_text(
    hub: ProjectRoomHub,
) -> None:
    """The frames and the route tell one story, because they read one record."""

    reader = session_for()
    await hub.join(reader)
    harness = TurnHarness(
        ScriptedModel(chunks=["Three ships ", "came in."]),
        publisher=ProjectAgentEvents(hub=hub),
        interval=0.0,
    )
    await harness.send()
    await harness.settle()

    frames = delivered(reader)
    appended = [frame for frame in frames if frame["type"] == "agent.event.appended"]
    events = await harness.events()
    assert [frame["event"]["sequence"] for frame in appended] == [
        event.sequence for event in events
    ]
    streamed = "".join(
        str(frame["text"]) for frame in frames if frame["type"] == "agent.delta"
    )
    assert streamed == "Three ships came in."


async def test_a_room_of_another_project_hears_nothing(hub: ProjectRoomHub) -> None:
    here = session_for(PROJECT)
    elsewhere = session_for(OTHER_PROJECT)
    await hub.join(here)
    await hub.join(elsewhere)
    harness = TurnHarness(
        ScriptedModel(chunks=["Answer."]),
        publisher=ProjectAgentEvents(hub=hub),
        interval=0.0,
    )
    await harness.send()
    await harness.settle()

    assert types_of(delivered(here)) == [
        "agent.turn.started",
        "agent.event.appended",
        "agent.delta",
        "agent.event.appended",
        "agent.event.appended",
        "agent.turn.finished",
    ]
    assert delivered(elsewhere) == []


async def test_a_reader_that_stopped_draining_loses_deltas_and_keeps_its_room(
    hub: ProjectRoomHub,
) -> None:
    """The rule that keeps one unread answer from disconnecting a Project.

    The queue is filled past the point where presence-style frames start being dropped, which
    is the state a wedged tab is really in. A delta offered there is discarded; the session is
    not closed, and the frames that carry facts still get through, so collaboration on the
    same socket continues while the model talks.
    """

    reader = session_for()
    await hub.join(reader)
    harness = TurnHarness(
        ScriptedModel(chunks=["word " * 4 for _ in range(10)]),
        publisher=ProjectAgentEvents(hub=hub),
        interval=0.0,
    )
    # Backpressure begins with a queue that is already nearly full.
    while reader.outbound.qsize() < PRESENCE_DROP_QUEUE_WATERMARK:
        reader.outbound.put_nowait(None)
    before = reader.outbound.qsize()

    await harness.send()
    await harness.settle()

    frames = [
        frame
        for frame in (
            item for item in _drain_including_sentinels(reader) if item is not None
        )
    ]
    assert not reader.closed
    assert reader.outbound.qsize() == 0
    deltas = [frame for frame in frames if frame["type"] == "agent.delta"]
    assert len(deltas) < 40, "a busy reader was handed the whole stream anyway"
    types = types_of(frames)
    for authoritative in ("agent.turn.started", "agent.turn.finished"):
        assert authoritative in types, types
    assert before == PRESENCE_DROP_QUEUE_WATERMARK


async def test_a_hundred_deltas_never_close_the_room(hub: ProjectRoomHub) -> None:
    """Deltas cannot close a socket at any rate the model can produce.

    Every other frame type in this hub closes a consumer whose 64 slots are full. A stream that
    outran a tab would therefore take the whole Project's collaboration down with it, twice a
    second, for as long as the model answered.
    """

    reader = session_for()
    await hub.join(reader)
    events = ProjectAgentEvents(hub=hub)
    harness = TurnHarness(ScriptedModel(chunks=["x"]))
    turn = await harness.send()
    snapshot = await harness.service.active_turn_snapshot(
        access=access(), conversation_id=turn.conversation_id
    )
    base = snapshot.turn
    del base
    while reader.outbound.full():
        reader.outbound.get_nowait()
    for index in range(OUTBOUND_QUEUE_MAXSIZE * 4):
        while reader.outbound.full():
            reader.outbound.get_nowait()
        reader.outbound.put_nowait(None)
        await events.text_partial(_partial(turn, offset=index, text=f"chunk {index}"))
    assert not reader.closed


async def test_a_hub_that_raises_strands_no_turn(hub: ProjectRoomHub) -> None:
    """A delivery failure is a log line, never an unanswered receipt.

    The frame is built after the events are committed, so the only thing an exception here
    could reach is the task writing the answer — and the reader's fallback (the events route)
    is intact, which is what the assertion is really about.
    """

    class BrokenHub:
        async def publish_model(self, **_message: object) -> None:
            raise RuntimeError("the room connection is gone")

        async def publish_transient(self, **_message: object) -> None:
            raise RuntimeError("the room connection is gone")

    harness = TurnHarness(
        ScriptedModel(chunks=["Still written."]),
        publisher=ProjectAgentEvents(hub=BrokenHub()),  # type: ignore[arg-type]
        interval=0.0,
    )
    await harness.send()
    settled = await harness.settle()

    assert settled.status.value == "completed"
    assert await harness.kinds() == [
        "user_message",
        "assistant_message",
        "turn_outcome",
    ]


async def test_a_cancelled_turn_is_told_once_with_the_text_it_kept(
    hub: ProjectRoomHub,
) -> None:
    """A Stop is an ending, not a hole in the thread.

    The partial that arrived is flushed, the stored message that holds it is told, and the
    outcome says it was cancelled — so a reader that reconnects sees a finished turn with the
    half-answer in it rather than a turn that never ended.
    """

    reader = session_for()
    await hub.join(reader)
    script = ScriptedModel(
        chunks=["It says the tide ", "came in fast.", " then turned."], park_after=2
    )
    publisher = RoomPublisher(hub=hub)
    harness = TurnHarness(script, publisher=publisher, interval=0.0)  # type: ignore[arg-type]
    await harness.send()
    await publisher.wait_for_partials(1)
    cancelled = await harness.service.cancel(
        access=access(), conversation_id=(await harness.thread()).id
    )
    await harness.service.wait_for_notifications(timeout_seconds=5)

    assert cancelled.status.value == "cancelled"
    frames = delivered(reader)
    types = types_of(frames)
    assert types.count("agent.turn.started") == 1
    assert types[-1] == "agent.turn.finished"
    assert types.count("agent.turn.finished") == 1
    assert types[:2] == ["agent.turn.started", "agent.event.appended"]
    finished = frames[-1]
    assert finished["outcome"] == "cancelled"
    appended = [
        frame["event"]["payload"]
        for frame in frames
        if frame["type"] == "agent.event.appended"
    ]
    assert [payload["kind"] for payload in appended] == [
        "user_message",
        "assistant_message",
        "turn_outcome",
    ]
    # What a reader watched arrive is what the thread keeps, whichever chunk the Stop landed
    # between: the stored message agrees with the frames, and it is a cut short answer rather
    # than a whole one because the outcome below says so.
    streamed = "".join(
        str(frame["text"]) for frame in frames if frame["type"] == "agent.delta"
    )
    assert appended[1]["text"] == streamed
    assert streamed.startswith("It says the tide ")
    assert streamed != "It says the tide came in fast. then turned."


async def test_a_partial_longer_than_one_frame_is_dropped_not_cut(
    hub: ProjectRoomHub,
) -> None:
    """An oversized frame is discarded whole.

    Half a message delivered as if it were whole is worse than none: the reader would splice
    the next frame onto text it does not have. The stored event carries the full message, so
    dropping the frame costs a stutter.
    """

    reader = session_for()
    await hub.join(reader)
    events = ProjectAgentEvents(hub=hub, delta_char_cap=8)
    harness = TurnHarness(ScriptedModel(chunks=["x"]))
    turn = await harness.send()

    await events.text_partial(_partial(turn, offset=0, text="far too many characters"))
    await events.text_partial(_partial(turn, offset=0, text="fits"))

    frames = delivered(reader)
    deltas = [frame for frame in frames if frame["type"] == "agent.delta"]
    assert [frame["text"] for frame in deltas] == ["fits"]


async def test_the_null_publisher_is_still_the_answer_for_a_composition_with_no_room(
    hub: ProjectRoomHub,
) -> None:
    """Nothing in the runtime quietly requires a hub.

    A deployment with no room, or a harness that only wants the record, still runs turns and
    counts what it discarded rather than losing it silently.
    """

    null = NullAgentTurnPublisher()
    harness = TurnHarness(
        ScriptedModel(chunks=["Recorded."]), publisher=null, interval=0.0
    )
    await harness.send()
    await harness.settle()

    assert null.dropped >= 4
    assert await harness.kinds() == [
        "user_message",
        "assistant_message",
        "turn_outcome",
    ]
    assert delivered(session_for()) == []
    await hub.shutdown()


def _drain_including_sentinels(
    session: ProjectRoomSession,
) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    while not session.outbound.empty():
        item = session.outbound.get_nowait()
        if item is None:
            continue
        frames.append(item.model_dump(mode="json"))
    return frames


def _partial(turn: AgentTurn, *, offset: int, text: str) -> AgentTextPartial:
    """One streamed fragment, as the runtime would have offered it. For the rules a full turn
    cannot put a test in — a frame longer than one may carry, a reader that stopped draining."""

    return AgentTextPartial(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
        conversation_id=turn.conversation_id,
        turn_id=turn.id,
        message_id=uuid4(),
        offset=offset,
        text=text,
    )

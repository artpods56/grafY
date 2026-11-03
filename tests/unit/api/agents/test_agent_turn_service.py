"""The Agent turn runtime, driven by a scripted model (ADR 0021, issue #202).

These are the promises the routes and the room will stand on. No network, no clock: the
turn runs on pydantic-ai over a `FunctionModel` the test parks and releases, so "cancelled
before the first chunk" and "cancelled with one chunk in hand" are states the runtime is
placed in rather than races a test hopes to catch.

What each part is really about:

* **Streaming.** The first characters arrive in `PartStartEvent` and the rest as deltas, and
  what is stored is the run's whole final message — the transient partials only preview it.
* **Admission.** Receipt and user message are one fact. A retry is answered, a conflict is
  refused, and a conversation that is busy stays busy.
* **Ending.** Cancel, failure and restart each leave one outcome, keep the text that arrived,
  release the conversation, and hand back the client the turn opened.
* **Authority.** Nothing a subscriber does — broken, wedged, or absent — changes what the
  conversation ends up holding.
"""

import asyncio
import logging
from uuid import UUID

import pytest

from grafy_api.agents.models import AgentModelConfigurationError
from grafy_api.agents.publishing import AgentTurnSnapshot
from grafy_api.agents.turns import (
    INTERRUPTED_DETAIL,
    AgentTurnConflictError,
    AgentTurnRequestError,
    AgentTurnStoppingError,
    redact_agent_turn_error,
)
from grafy_core.domain.agent_conversations import (
    AgentConversationTurnOutcome,
    AssistantMessagePayload,
    TurnOutcomePayload,
    UserMessagePayload,
)
from grafy_core.domain.agent_turns import AgentTurnStatus
from grafy_core.domain.errors import CapabilityDeniedError, NotFoundError
from grafy_core.domain.identity import WorkspaceRole
from grafy_core.ports.agent_turns import AgentTurnBusyError
from tests.unit.api.agents.turn_support import (
    DIAL_KEY,
    DEFAULT_INTERVAL,
    INSTRUCTIONS,
    WORKSPACE,
    BrokenResolver,
    FakeClock,
    RecordingPublisher,
    ScriptedModel,
    ScriptedResolver,
    TurnHarness,
    access,
    agent,
    custom_agent_model,
    no_dangling_turns as no_dangling_turns,  # noqa: F401 - autouse fixture, imported to register
    other_workspace_access,
    stored_outcome,
    stored_text,
)


class APITimeout(RuntimeError):
    """Stands in for a provider SDK's own exception type, whose text we do not control."""


FAST = 0.0


async def test_one_turn_streams_and_stores_the_answer_with_its_outcome() -> None:
    harness = TurnHarness(
        ScriptedModel(chunks=["The diary ", "describes ", "the water."])
    )

    turn = await harness.send()
    settled = await harness.settle()

    assert turn.is_running and turn.id == settled.id
    assert settled.status is AgentTurnStatus.COMPLETED
    assert settled.finished_at is not None
    assert settled.model_name == "llama-4"
    assert settled.model_source == "deployment"
    assert settled.instructions == INSTRUCTIONS
    # The question the send admitted, the whole answer, and how the turn ended.
    assert await harness.kinds() == [
        "user_message",
        "assistant_message",
        "turn_outcome",
    ]
    events = await harness.events()
    assert isinstance(events[0].payload, UserMessagePayload)
    assert stored_text(events[0]) == "What did the diary say?"
    assert isinstance(events[1].payload, AssistantMessagePayload)
    assert stored_text(events[1]) == "The diary describes the water."
    assert events[0].turn_id == events[1].turn_id == turn.id
    outcome = events[2].payload
    assert isinstance(outcome, TurnOutcomePayload)
    assert outcome.outcome is AgentConversationTurnOutcome.COMPLETED
    assert outcome.detail is None
    # The receipt points at the event the send admitted rather than recounting it, and the
    # service holds on to nothing once the turn has ended.
    assert turn.user_message_sequence == events[0].sequence
    assert harness.service.running_turn_ids == ()


async def test_the_first_characters_of_a_message_are_part_of_the_message() -> None:
    """`PartStartEvent` carries text; a loop that only read deltas would lose its head."""

    harness = TurnHarness(
        ScriptedModel(chunks=["Hydro", "logy ", "of ", "the 1667 flood"]), interval=FAST
    )

    await harness.send()
    await harness.settle()

    events = await harness.events()
    assert stored_text(events[1]) == "Hydrology of the 1667 flood"
    # Every character, in order, once: the transient frames add up to the stored authority
    # rather than to the authority minus whatever arrived as a part rather than a delta.
    assert harness.publisher.streamed_text == "Hydrology of the 1667 flood"
    assert harness.publisher.partials[0].text == "Hydro"
    # The whole run's result is what is stored, even though it was never one of the frames.
    assert stored_text(events[1]) == "".join(
        chunk for chunk in ["Hydro", "logy ", "of ", "the 1667 flood"]
    )


async def test_a_single_part_answer_is_stored_and_published_once() -> None:
    harness = TurnHarness(ScriptedModel(chunks=["Nothing more to add."]), interval=FAST)

    await harness.send()
    await harness.settle()

    events = await harness.events()
    assert stored_text(events[1]) == "Nothing more to add."
    assert [partial.text for partial in harness.publisher.partials] == [
        "Nothing more to add."
    ]


async def test_a_partial_names_its_turn_and_message_and_tiles_the_answer_with_offsets() -> (
    None
):
    harness = TurnHarness(
        ScriptedModel(chunks=["one ", "two ", "three"]), interval=FAST
    )

    await harness.send()
    settled = await harness.settle()
    conversation = await harness.thread()

    partials = harness.publisher.partials
    assert partials, "a streaming turn must publish something"
    assert {partial.turn_id for partial in partials} == {settled.id}
    assert {partial.conversation_id for partial in partials} == {conversation.id}
    # One assistant message per turn until tool calls arrive, and every frame says which.
    assert len({partial.message_id for partial in partials}) == 1
    assert partials[0].offset == 0
    for previous, following in zip(partials, partials[1:]):
        assert following.offset == previous.next_offset
    # Every frame carries text a reader can place, and nothing is published after the
    # answer: the durable assistant message event is what ends a message.
    assert all(partial.text for partial in partials)
    assert partials[-1].next_offset == len("one two three")
    assert harness.publisher.streamed_text == "one two three"


async def test_text_inside_one_window_is_published_once() -> None:
    """The ~75 ms rule is about a clock, so the test moves that clock."""

    clock = FakeClock()
    harness = TurnHarness(
        ScriptedModel(chunks=["a", "b", "c"]), interval=DEFAULT_INTERVAL, clock=clock
    )

    await harness.send()
    await harness.settle()

    # The first characters go out at once — a reader waiting on an answer should see it
    # start — and everything that follows inside the window leaves as one frame.
    assert [partial.text for partial in harness.publisher.partials] == ["a", "bc"]
    assert [partial.offset for partial in harness.publisher.partials] == [0, 1]

    # The clock is what decides this, so the test moves it: with the window elapsed before
    # each chunk, the chunks stop sharing a frame, and nothing is published for a stream
    # that has run dry.
    spread = ScriptedModel(
        chunks=["x", "y", "z"], chunk_interval=DEFAULT_INTERVAL, clock=clock
    )
    later = TurnHarness(spread, interval=DEFAULT_INTERVAL, clock=clock)
    await later.send()
    await later.settle()
    assert [partial.text for partial in later.publisher.partials] == ["x", "y", "z"]
    assert [partial.offset for partial in later.publisher.partials] == [0, 1, 2]


async def test_the_second_turn_is_asked_with_the_first_ones_stored_history() -> None:
    harness = TurnHarness(ScriptedModel(chunks=["One source mentions a barge."]))

    await harness.send("What was in the harbour?")
    await harness.settle()
    harness.restart(ScriptedModel(chunks=["The barge was Dutch."]), interval=FAST)

    await harness.send("And where had it come from?", turn_id="client-2")
    await harness.settle()

    # Grafy's events are the only history there is: the stored question and answer, then the
    # new question, with the snapshot instructions beside them.
    assert harness.model.seen == [
        ("ModelRequest", [("user-prompt", "What was in the harbour?")]),
        ("ModelResponse", [("text", "One source mentions a barge.")]),
        ("ModelRequest", [("user-prompt", "And where had it come from?")]),
    ]
    assert harness.model.seen_instructions == [INSTRUCTIONS]
    assert await harness.kinds() == [
        "user_message",
        "assistant_message",
        "turn_outcome",
        "user_message",
        "assistant_message",
        "turn_outcome",
    ]


async def test_a_cancelled_partial_stays_in_history_and_is_labelled_as_cut_short() -> (
    None
):
    """Durable outcomes govern what the model is told: the text stays, and it is named."""

    first = ScriptedModel(chunks=["The archive lists ", "three ships"], park_after=1)
    harness = TurnHarness(first, interval=FAST)
    await harness.send("Which ships?")
    await harness.publisher.wait_for_partials()
    cancelled = await harness.service.cancel(
        access=access(), conversation_id=(await harness.thread()).id
    )
    assert cancelled.status is AgentTurnStatus.CANCELLED

    events = await harness.events()
    assert [
        stored_text(event) for event in events if event.payload.kind != "turn_outcome"
    ] == [
        "Which ships?",
        "The archive lists ",
    ]
    assert stored_outcome(events[-1]) is AgentConversationTurnOutcome.CANCELLED

    harness.restart(
        ScriptedModel(chunks=["Please repeat the question."]), interval=FAST
    )
    await harness.send("Sorry?", turn_id="client-2")
    await harness.settle()

    parts = [
        content
        for _, message_parts in harness.model.seen
        for _, content in message_parts
    ]
    assert "The archive lists " in parts
    # The label arrives as a system part of the request that carries the new question: the
    # provider's own view merges them, and what matters is that the model is told the text
    # above was cut short rather than that it arrived in a particular envelope.
    assert any(
        isinstance(content, str) and "cancelled before it finished" in content
        for content in parts
    )
    # The label is the rebuild's, never the stored event's: what arrived is one thing, and
    # whether that was the whole answer is the outcome's business.
    stored = await harness.events()
    assert all(
        "cancelled before it finished" not in str(event.payload) for event in stored
    )


async def test_the_snapshot_a_turn_runs_on_is_the_one_it_was_accepted_with() -> None:
    moving = ScriptedModel(chunks=["an answer"], park_after=0)
    harness = TurnHarness(moving)

    turn = await harness.send()
    await moving.parked.wait()
    # The canvas moves while the turn is in flight: renamed, re-instructed, re-pointed.
    await harness.edit_canvas(
        agent(
            instructions="Be exhaustive and cite every folio.",
            model=custom_agent_model(),
        )
    )
    moving.release()
    await harness.settle()

    assert turn.instructions == INSTRUCTIONS
    assert turn.model_name == "llama-4"
    assert moving.seen_instructions == [INSTRUCTIONS]

    # And the next turn is built from the canvas as it is now, and from the model choice it
    # carries now, which is the other half of the same snapshot rule.
    harness.resolver = ScriptedResolver(source="agent", model_name="gpt-5-mini")
    harness.restart(ScriptedModel(chunks=["later"]), interval=FAST)
    second = await harness.send("again", turn_id="client-2")
    await harness.settle()

    assert second.instructions == "Be exhaustive and cite every folio."
    assert second.model_source == "agent"
    assert second.model_name == "gpt-5-mini"


async def test_a_repeated_send_is_the_same_turn_with_one_call_and_one_event_set() -> (
    None
):
    model = ScriptedModel(chunks=["The answer."], park_after=0)
    harness = TurnHarness(model)

    first = await harness.send("What happened?")
    again = await harness.send("What happened?")

    assert again.id == first.id
    assert again.status is AgentTurnStatus.RUNNING
    assert model.calls == 0, "a replay must not ask the model anything"

    settled = await harness.settle()
    assert settled.id == first.id
    assert model.calls == 1
    assert await harness.kinds() == [
        "user_message",
        "assistant_message",
        "turn_outcome",
    ]

    # A retry that arrives after the turn finished is answered too, and still starts nothing.
    replay = await harness.send("What happened?")
    assert replay.id == first.id
    assert replay.status is AgentTurnStatus.COMPLETED
    assert model.calls == 1
    assert len(await harness.events()) == 3


async def test_the_same_turn_id_with_different_content_is_a_conflict_not_a_replay() -> (
    None
):
    model = ScriptedModel(chunks=["The answer."], park_after=0)
    harness = TurnHarness(model)

    accepted = await harness.send("What happened?")
    with pytest.raises(AgentTurnConflictError) as conflict:
        await harness.send("What happened? Be thorough.", turn_id="client-1")

    assert conflict.value.turn_id == accepted.id
    # The conflict names the turn that is stored, so a client can go and read what it
    # actually sent rather than guess which of its two bodies won.
    assert model.calls == 0
    # The refused message is nowhere: neither in history nor as a second receipt.
    assert await harness.kinds() == ["user_message"]
    assert stored_text((await harness.events())[0]) == "What happened?"
    await harness.settle()
    assert len(await harness.events()) == 3


async def test_a_send_of_the_same_id_to_another_conversation_is_its_own_turn() -> None:
    """The receipt key is per conversation: a reused id in a second thread is not a retry."""

    model = ScriptedModel(chunks=["answer"], park_after=0)
    harness = TurnHarness(model)
    first = await harness.send("First thread", turn_id="same-id")
    await harness.settle()
    other = await harness.other_thread()

    second = await harness.send_to(other.id, "Second thread", turn_id="same-id")
    await harness.settle_conversation(other.id)

    assert second.id != first.id
    assert second.conversation_id == other.id
    assert second.user_message_sequence == 1


async def test_one_turn_at_a_time_per_conversation() -> None:
    model = ScriptedModel(chunks=["A long answer"], park_after=0)
    harness = TurnHarness(model)

    first = await harness.send("First")
    assert first.is_running
    with pytest.raises(AgentTurnBusyError) as busy:
        await harness.send("Second thought", turn_id="client-2")

    assert busy.value.running_turn_id == first.id
    # The refusal wrote nothing at all: the second question is not in the history.
    assert await harness.kinds() == ["user_message"]
    await model.started.wait()
    assert model.calls == 1

    await harness.settle()
    # The conversation is free again, and asks in a turn of its own.
    harness.restart(ScriptedModel(chunks=["Second answer"]), interval=FAST)
    second = await harness.send("Second thought", turn_id="client-2")
    await harness.settle()
    assert second.id != first.id
    assert await harness.kinds() == [
        "user_message",
        "assistant_message",
        "turn_outcome",
        "user_message",
        "assistant_message",
        "turn_outcome",
    ]


async def test_two_conversations_of_one_agent_run_at_the_same_time() -> None:
    """One turn at a time *per conversation*, which is not one turn per Agent."""

    one = ScriptedModel(chunks=["first thread"], park_after=0)
    two = ScriptedModel(chunks=["second thread"])
    # Two scripts, one per turn: the same service cannot be asked twice which thread a
    # single script answers, and a shared script would let either turn look like the other.
    harness = TurnHarness([one, two], interval=FAST)
    first = await harness.send("One thread", turn_id="client-1")
    await one.started.wait()

    other = await harness.other_thread()
    second = await harness.send_to(other.id, "Other thread", turn_id="client-1")
    await harness.settle_conversation(other.id, release=False)

    # The same client turn id, the same Agent, and no refusal anywhere: the busy rule is
    # per conversation, so a second thread was never waiting on the first.
    assert second.is_running or second.status is AgentTurnStatus.COMPLETED
    assert first.is_running
    assert first.conversation_id != second.conversation_id
    assert one.calls == 1 and two.calls == 1
    await harness.settle()


async def test_cancelling_before_the_first_chunk_keeps_the_question_and_says_so() -> (
    None
):
    model = ScriptedModel(chunks=["never arrives"], park_after=0)
    harness = TurnHarness(model)
    await harness.send()
    await model.started.wait()

    cancelled = await harness.service.cancel(
        access=access(), conversation_id=(await harness.thread()).id
    )

    assert cancelled.status is AgentTurnStatus.CANCELLED
    assert cancelled.outcome_detail is None
    assert cancelled.finished_at is not None
    # Nothing had arrived, so there is no assistant message to keep. The question and the
    # record that the turn was stopped are the whole history.
    assert await harness.kinds() == ["user_message", "turn_outcome"]
    assert stored_outcome((await harness.events())[-1]) is (
        AgentConversationTurnOutcome.CANCELLED
    )
    # A turn that never got an answer still hands back what it opened, and frees the thread.
    assert model.closed == 1
    assert harness.service.running_turn_ids == ()


async def test_cancelling_mid_stream_keeps_what_arrived_and_closes_the_client() -> None:
    # Two chunks have arrived and the third never will: the turn is stopped with text in
    # hand rather than with nothing.
    model = ScriptedModel(chunks=["The river ", "rose by ", "two metres"], park_after=2)
    harness = TurnHarness(model, interval=FAST)
    await harness.send()
    await harness.publisher.wait_for_partials(2)

    cancelled = await harness.service.cancel(
        access=access(), conversation_id=(await harness.thread()).id
    )

    assert cancelled.status is AgentTurnStatus.CANCELLED
    events = await harness.events()
    assert await harness.kinds() == [
        "user_message",
        "assistant_message",
        "turn_outcome",
    ]
    assert stored_text(events[1]) == "The river rose by "
    assert stored_outcome(events[-1]) is AgentConversationTurnOutcome.CANCELLED
    assert model.closed == 1
    # What a reader watched arrive is what the thread keeps, so the streamed text and the
    # durable text agree even for a turn that never finished.
    assert harness.publisher.streamed_text == "The river rose by "


async def test_cancelling_is_idempotent_and_names_the_same_ending_twice() -> None:
    model = ScriptedModel(chunks=["half an answer"], park_after=0)
    harness = TurnHarness(model)
    await harness.send()
    await model.started.wait()
    conversation_id = (await harness.thread()).id

    first = await harness.service.cancel(
        access=access(), conversation_id=conversation_id
    )
    second = await harness.service.cancel(
        access=access(), conversation_id=conversation_id
    )

    assert first.status is second.status is AgentTurnStatus.CANCELLED
    assert first.finished_at == second.finished_at
    outcomes = await harness.outcome_events()
    assert len(outcomes) == 1
    assert model.closed == 1


async def test_a_stop_button_after_the_answer_rewrites_nothing() -> None:
    harness = TurnHarness(ScriptedModel(chunks=["done"]), interval=FAST)
    await harness.send()
    answered = await harness.settle()
    assert answered.status is AgentTurnStatus.COMPLETED

    again = await harness.service.cancel(
        access=access(), conversation_id=(await harness.thread()).id
    )

    assert again.id == answered.id
    assert again.status is AgentTurnStatus.COMPLETED
    assert len(await harness.outcome_events()) == 1


async def test_a_model_failure_is_stored_as_a_failure_without_giving_up_the_key() -> (
    None
):
    leak = RuntimeError(
        f"unauthorized: the key {DIAL_KEY} was refused by models.example"
    )
    harness = TurnHarness(
        ScriptedModel(chunks=["text that arrived first"], error=leak), interval=FAST
    )

    await harness.send()
    settled = await harness.settle()

    assert settled.status is AgentTurnStatus.FAILED
    assert DIAL_KEY not in (settled.outcome_detail or "")
    assert "[redacted]" in (settled.outcome_detail or "")
    events = await harness.events()
    outcome = events[-1].payload
    assert isinstance(outcome, TurnOutcomePayload)
    assert outcome.outcome is AgentConversationTurnOutcome.FAILED
    assert outcome.detail is not None and DIAL_KEY not in outcome.detail
    # What streamed before the failure is kept: the thread can show how far the Agent got,
    # and the outcome beside it says that was not the end of it.
    assert stored_text(events[1]) == "text that arrived first"
    assert harness.model.closed == 1
    # A failed turn releases its conversation, which is the point of recording the failure.
    assert harness.service.running_turn_ids == ()
    harness.restart(ScriptedModel(chunks=["asked again"]), interval=FAST)
    assert (await harness.send("and now?", turn_id="client-2")).is_running
    await harness.settle()


async def test_nothing_logged_about_a_failed_turn_carries_the_credential(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A provider SDK's own exception type: what matters here is only that its text carries
    # the credential this process dialled with.
    leak = APITimeout(f"no route to models.example with {DIAL_KEY}")
    harness = TurnHarness(ScriptedModel(chunks=[], error=leak))

    with caplog.at_level(logging.WARNING, logger="grafy_api.agents.turns"):
        await harness.send()
        await harness.settle()

    assert caplog.records, "a turn that failed has to be visible somewhere"
    assert DIAL_KEY not in caplog.text
    assert harness.model.closed == 1


async def test_a_publisher_that_throws_loses_frames_and_nothing_else() -> None:
    harness = TurnHarness(
        ScriptedModel(chunks=["The answer.", " With a tail."]),
        interval=FAST,
        publisher=RecordingPublisher(fail_partials=True),
    )

    await harness.send()
    settled = await harness.settle()

    assert settled.status is AgentTurnStatus.COMPLETED
    assert harness.publisher.partials == []
    events = await harness.events()
    assert stored_text(events[1]) == "The answer. With a tail."
    assert stored_outcome(events[-1]) is AgentConversationTurnOutcome.COMPLETED
    # The end of the turn is still told, on a publisher that can carry it: a broken frame is
    # not a reason to lose the fact that the answer is there now.
    await harness.publisher.wait_for_finished()
    assert [outcome for _, outcome, _ in harness.publisher.finished] == [
        AgentConversationTurnOutcome.COMPLETED
    ]


async def test_a_publisher_that_never_answers_does_not_hold_a_turn_up() -> None:
    block = asyncio.Event()
    harness = TurnHarness(
        ScriptedModel(chunks=["The answer."]),
        interval=FAST,
        publisher=RecordingPublisher(block=block),
    )

    await harness.send()
    settled = await harness.settle()

    # The turn is over and stored while nobody has heard about it yet.
    assert settled.status is AgentTurnStatus.COMPLETED
    assert harness.publisher.started == []
    events = await harness.events()
    assert stored_text(events[1]) == "The answer."

    block.set()
    await harness.service.wait_for_notifications()
    assert [turn.id for turn in harness.publisher.started] == [settled.id]


async def test_a_turn_whose_model_cannot_be_dialled_is_never_admitted() -> None:
    harness = TurnHarness(
        ScriptedModel(chunks=["unused"]),
        resolver=BrokenResolver(AgentModelConfigurationError("no default Agent model")),
    )

    with pytest.raises(AgentModelConfigurationError):
        await harness.send()

    assert await harness.events() == []
    assert harness.service.running_turn_ids == ()
    assert harness.model.calls == 0
    # The thread is not left busy by a send that never became a turn.
    harness.resolver = ScriptedResolver()
    harness.restart(ScriptedModel(chunks=["now it works"]), interval=FAST)
    assert (await harness.send("ask again", turn_id="client-2")).is_running
    await harness.settle()


async def test_an_agent_taken_off_the_canvas_answers_nothing_and_keeps_its_history() -> (
    None
):
    harness = TurnHarness(ScriptedModel(chunks=["An answer."]), interval=FAST)
    turn = await harness.send()
    await harness.settle()

    await harness.edit_canvas()

    # The history is still readable, because it is the record of what was asked and said.
    assert await harness.kinds() == [
        "user_message",
        "assistant_message",
        "turn_outcome",
    ]
    assert (
        await harness.service.get_turn(access=access(), turn_id=turn.id)
    ).status is (AgentTurnStatus.COMPLETED)
    # A fresh question has nobody to ask, and says who is missing.
    with pytest.raises(NotFoundError, match="Agent"):
        await harness.send("still there?", turn_id="client-2")
    assert len(await harness.events()) == 3
    assert harness.service.running_turn_ids == ()


async def test_a_retry_of_an_admitted_send_is_answered_after_the_agent_is_gone() -> (
    None
):
    """The receipt is the answer. It does not need the canvas to still have the Agent."""

    model = ScriptedModel(chunks=["answer"], park_after=0)
    harness = TurnHarness(model)
    turn = await harness.send("asked")
    await model.started.wait()
    await harness.edit_canvas()

    assert (await harness.send("asked")).id == turn.id
    await harness.settle()
    assert await harness.kinds() == [
        "user_message",
        "assistant_message",
        "turn_outcome",
    ]


async def test_sending_and_cancelling_need_start_run_and_reading_needs_view_project() -> (
    None
):
    model = ScriptedModel(chunks=["An answer."])
    harness = TurnHarness(model, interval=FAST)
    conversation_id = (await harness.thread()).id
    viewer = access(role=WorkspaceRole.VIEWER)

    with pytest.raises(CapabilityDeniedError) as denied_send:
        await harness.service.send(
            access=viewer,
            conversation_id=conversation_id,
            client_turn_id="client-1",
            text="hello",
        )
    assert denied_send.value.capability == "start_run"
    with pytest.raises(CapabilityDeniedError) as denied_cancel:
        await harness.service.cancel(access=viewer, conversation_id=conversation_id)
    assert denied_cancel.value.capability == "start_run"
    assert model.calls == 0
    assert await harness.events() == []

    turn = await harness.send()
    await harness.settle()

    # What a conversation's owner may read, anyone with view_project may read.
    assert (
        await harness.service.get_turn(access=viewer, turn_id=turn.id)
    ).id == turn.id
    listed = await harness.service.list_turns(
        access=viewer, conversation_id=conversation_id
    )
    assert [item.id for item in listed] == [turn.id]
    snapshot = await harness.service.active_turn_snapshot(
        access=viewer, conversation_id=conversation_id
    )
    assert snapshot is None


async def test_an_empty_message_is_refused_before_anything_is_written() -> None:
    harness = TurnHarness(ScriptedModel(chunks=["unused"]))

    with pytest.raises(AgentTurnRequestError):
        await harness.send("   ")

    assert await harness.events() == []
    assert harness.model.calls == 0


async def test_a_receipt_is_not_readable_across_workspaces_and_a_wrong_id_is_named() -> (
    None
):
    harness = TurnHarness(ScriptedModel(chunks=["An answer."]), interval=FAST)
    turn = await harness.send()
    await harness.settle()

    with pytest.raises(NotFoundError, match="Agent turn"):
        await harness.service.get_turn(access=other_workspace_access(), turn_id=turn.id)
    with pytest.raises(NotFoundError, match="Agent conversation"):
        await harness.send_to(UUID(int=4242), "hello")
    with pytest.raises(NotFoundError, match="Agent conversation"):
        await harness.service.list_turns(
            access=other_workspace_access(), conversation_id=(await harness.thread()).id
        )
    # A conversation whose turns another Workspace owns is not a list to be given.
    assert harness.service.running_turn_ids == ()
    assert turn.workspace_id == WORKSPACE


async def test_a_restart_marks_running_turns_interrupted_once_and_frees_the_thread() -> (
    None
):
    """A new process over the same database, with a turn that died with the old one."""

    model = ScriptedModel(chunks=["half an answer"], park_after=0)
    harness = TurnHarness(model, interval=FAST)
    turn = await harness.send()
    await model.started.wait()

    # A process that never saw that turn: no live task, only the receipt it inherits.
    restarted = harness.restart(ScriptedModel(chunks=["unused"]))
    interrupted = await restarted.recover_after_restart()

    assert [item.id for item in interrupted] == [turn.id]
    assert interrupted[0].status is AgentTurnStatus.INTERRUPTED
    assert interrupted[0].outcome_detail == INTERRUPTED_DETAIL
    # The question survived admission, so it is the history; the text died with the task.
    assert await harness.kinds() == ["user_message", "turn_outcome"]
    assert stored_outcome((await harness.events())[-1]) is (
        AgentConversationTurnOutcome.INTERRUPTED
    )

    # Exactly once, however often recovery runs.
    assert await restarted.recover_after_restart() == []
    assert len(await harness.events()) == 2

    # And the thread is usable again, which is the whole reason a restart is survivable.
    harness.restart(ScriptedModel(chunks=["after the restart"]), interval=FAST)
    await harness.send("are you there?", turn_id="client-2")
    assert (await harness.settle()).status is AgentTurnStatus.COMPLETED
    assert await harness.service.recover_after_restart() == []
    assert len(await harness.outcome_events()) == 2


async def test_recovery_does_not_touch_a_turn_that_ended_before_the_restart() -> None:
    harness = TurnHarness(ScriptedModel(chunks=["an answer"]), interval=FAST)
    await harness.send()
    await harness.settle()

    restarted = harness.restart(ScriptedModel(chunks=["unused"]))

    assert await restarted.recover_after_restart() == []
    assert len(await harness.outcome_events()) == 1


async def test_shutdown_stops_a_live_turn_records_it_and_closes_the_client() -> None:
    model = ScriptedModel(chunks=["streaming when the server stopped"], park_after=0)
    harness = TurnHarness(model, interval=FAST)
    await harness.send()
    await model.started.wait()

    await harness.service.close(timeout_seconds=5)

    settled = await harness.settle()
    assert settled.status is AgentTurnStatus.INTERRUPTED
    assert settled.outcome_detail == INTERRUPTED_DETAIL
    assert harness.service.running_turn_ids == ()
    assert (await harness.events())[-1].payload.kind == "turn_outcome"
    assert model.closed == 1
    # An owner that has stopped taking its turns back takes no new ones either.
    with pytest.raises(AgentTurnStoppingError):
        await harness.send("hello?", turn_id="client-2")


async def test_a_shutdown_wait_is_a_request_first_and_only_then_an_order() -> None:
    """A turn asked to stop writes its own ending, inside the shutdown's own patience."""

    model = ScriptedModel(chunks=["the last thing it said"], park_after=0)
    harness = TurnHarness(model, interval=FAST)
    await harness.send()
    await model.started.wait()

    # The turn is parked; a close with a generous deadline gets to keep the ending it asked
    # for rather than cancelling a task in the middle of a database write.
    await harness.service.close(timeout_seconds=5)
    assert harness.model.closed == 1
    outcomes = await harness.outcome_events()
    assert [stored_outcome(event) for event in outcomes] == [
        AgentConversationTurnOutcome.INTERRUPTED
    ]


async def test_a_running_turn_can_be_read_back_while_it_streams() -> None:
    model = ScriptedModel(chunks=["The first ", "part"], park_after=1)
    harness = TurnHarness(model, interval=FAST)
    turn = await harness.send()
    conversation_id = (await harness.thread()).id
    await harness.publisher.wait_for_partials()

    snapshot = await harness.service.active_turn_snapshot(
        access=access(), conversation_id=conversation_id
    )

    assert isinstance(snapshot, AgentTurnSnapshot)
    assert snapshot.turn.id == turn.id
    assert snapshot.turn.is_running
    assert snapshot.partial_text == "The first "
    # The offset says how far the frames got, which is exactly what a reader who joined late
    # needs to know before the durable message replaces all of it.
    assert snapshot.partial_offset == len("The first ")
    assert snapshot.partial_message_id == harness.publisher.partials[0].message_id

    model.release()
    await harness.settle()
    # A finished turn has no in-flight text and answers nothing rather than answering empty.
    assert (
        await harness.service.active_turn_snapshot(
            access=access(), conversation_id=conversation_id
        )
    ) is None


async def test_a_fork_continues_from_the_events_it_copied() -> None:
    """ "Continue from here" is a new conversation, and the model is told exactly that much."""

    harness = TurnHarness(
        ScriptedModel(chunks=["First answer.", " With a tail."]), interval=FAST
    )
    await harness.send("First question")
    await harness.settle()
    source = await harness.thread()

    forked = await harness.conversations.fork(
        workspace_id=WORKSPACE,
        conversation_id=source.id,
        at_sequence=2,
        author_user_id=source.author_user_id,
    )
    assert forked.source_conversation_id == source.id
    assert forked.last_sequence == 2

    continued = ScriptedModel(chunks=["Continued answer"])
    harness.restart(continued, interval=FAST)
    turn = await harness.send_to(forked.id, "Go on from there")
    await harness.settle_conversation(forked.id)

    assert continued.seen == [
        ("ModelRequest", [("user-prompt", "First question")]),
        ("ModelResponse", [("text", "First answer. With a tail.")]),
        ("ModelRequest", [("user-prompt", "Go on from there")]),
    ]
    assert turn.conversation_id == forked.id
    # The source keeps its own history and its own ending: a fork copies, it never trims.
    assert await harness.kinds() == [
        "user_message",
        "assistant_message",
        "turn_outcome",
    ]


async def test_a_turn_after_a_fork_does_not_see_history_the_fork_did_not_copy() -> None:
    harness = TurnHarness(ScriptedModel(chunks=["one", " two"]), interval=FAST)
    await harness.send("First question")
    await harness.settle()
    source = await harness.thread()

    forked = await harness.conversations.fork(
        workspace_id=WORKSPACE,
        conversation_id=source.id,
        at_sequence=1,
        author_user_id=source.author_user_id,
    )
    harness.restart(ScriptedModel(chunks=["later"]), interval=FAST)
    await harness.send_to(forked.id, "Only from the question")
    await harness.settle_conversation(forked.id)

    # What reached the model is one request carrying the question the fork kept and the
    # question just asked, and no answer anywhere: the reply the source conversation got at
    # sequence 2 stayed there. How the library groups two consecutive questions into request
    # parts is its own, and nothing here depends on it.
    assert harness.model.seen == [
        (
            "ModelRequest",
            [
                ("user-prompt", "First question"),
                ("user-prompt", "Only from the question"),
            ],
        )
    ]


async def test_redaction_names_the_endpoint_and_not_the_credential() -> None:
    assert (
        redact_agent_turn_error(f"bad key {DIAL_KEY} at models.example", [DIAL_KEY])
        == "bad key [redacted] at models.example"
    )
    # Something short enough to be an ordinary word is left alone rather than mangling the
    # account that is the only thing a reader will have to go on.
    assert redact_agent_turn_error("ab is not a secret", ["ab"]) == "ab is not a secret"
    assert len(redact_agent_turn_error("x" * 5_000)) == 2_000


async def test_the_system_note_about_a_cut_short_reply_is_not_stored_or_republished() -> (
    None
):
    """The label belongs to the model's view of the past, not to the durable record."""

    first = ScriptedModel(chunks=["cut off"], park_after=0)
    harness = TurnHarness(first, interval=FAST)
    await harness.send("asked")
    await first.started.wait()
    await harness.service.cancel(
        access=access(), conversation_id=(await harness.thread()).id
    )

    harness.restart(ScriptedModel(chunks=["next"], park_after=0), interval=FAST)
    await harness.send("and now?", turn_id="client-2")
    await harness.model.started.wait()

    told = [
        content
        for _, parts in harness.model.seen
        for _, content in parts
        if isinstance(content, str) and "cancelled before it finished" in content
    ]
    assert told, "the rebuild labels the text it knows was cut short"
    events = await harness.events()
    assert all(told[0] not in str(event.payload) for event in events)
    await harness.service.cancel(
        access=access(), conversation_id=(await harness.thread()).id
    )

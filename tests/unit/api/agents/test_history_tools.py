"""Tool calls and results in the stored history, and how a model is told about them."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from grafy_api.agents.history import history_messages
from grafy_core.artifacts import ArtifactRef
from grafy_core.domain.agent_conversations import (
    AgentConversationEvent,
    AgentConversationEventPayload,
    AgentConversationTurnOutcome,
    AssistantMessagePayload,
    ConfirmationRequestedPayload,
    ToolCallPayload,
    ToolResultArtifact,
    ToolResultPayload,
    TurnOutcomePayload,
    UserMessagePayload,
    event_payload_from_storage,
    event_payload_to_storage,
)

WORKSPACE = UUID("00000000-0000-4000-8000-000000000001")
CONVERSATION = UUID("00000000-0000-4000-8000-000000000002")
TURN = UUID("00000000-0000-4000-8000-000000000003")


def events(*payloads: AgentConversationEventPayload) -> list[AgentConversationEvent]:
    return [
        AgentConversationEvent(
            workspace_id=WORKSPACE,
            conversation_id=CONVERSATION,
            sequence=index,
            turn_id=TURN,
            payload=payload,
            created_at=datetime(2026, 11, 5, tzinfo=UTC),
        )
        for index, payload in enumerate(payloads, start=1)
    ]


def call(call_id: str, name: str = "read_text", **arguments: object):
    return ToolCallPayload(
        call_id=call_id, tool_id="t1", tool_name=name, arguments=arguments
    )


def result(call_id: str, text: str = "hello", name: str = "read_text"):
    return ToolResultPayload(
        call_id=call_id,
        tool_id="t1",
        tool_name=name,
        ok=True,
        fingerprint="f" * 64,
        model_view=text,
    )


def test_the_calls_of_one_response_and_their_results_are_one_message_each() -> None:
    messages = history_messages(
        events(
            UserMessagePayload(text="What do the two letters say?"),
            AssistantMessagePayload(text="Let me read them."),
            call("a", path="one"),
            call("b", path="two"),
            result("a", "dear sir"),
            result("b", "dear madam"),
            AssistantMessagePayload(text="They greet different people."),
            TurnOutcomePayload(outcome=AgentConversationTurnOutcome.COMPLETED),
        )
    )

    assert [type(message) for message in messages] == [
        ModelRequest,
        ModelResponse,
        ModelRequest,
        ModelResponse,
    ]
    asked, said, told, answered = messages
    assert isinstance(asked.parts[0], UserPromptPart)
    assert [type(part) for part in said.parts] == [TextPart, ToolCallPart, ToolCallPart]
    first = said.parts[1]
    assert isinstance(first, ToolCallPart)
    assert (first.tool_name, first.tool_call_id, first.args) == (
        "read_text",
        "a",
        {"path": "one"},
    )
    assert [
        part.tool_call_id for part in told.parts if isinstance(part, ToolReturnPart)
    ] == [
        "a",
        "b",
    ]
    assert [
        part.content for part in told.parts if isinstance(part, ToolReturnPart)
    ] == [
        "dear sir",
        "dear madam",
    ]
    assert isinstance(answered.parts[0], TextPart)


def test_a_failed_call_is_told_to_the_model_as_a_failure() -> None:
    failed = ToolResultPayload(
        call_id="a",
        tool_id="t1",
        tool_name="read_text",
        ok=False,
        error="the table has no such column",
    )

    messages = history_messages(
        events(UserMessagePayload(text="go"), call("a"), failed)
    )

    returned = messages[-1].parts[0]
    assert isinstance(returned, ToolReturnPart)
    assert returned.outcome == "failed"
    assert "the table has no such column" in str(returned.content)


def test_a_confirmation_adds_nothing_and_the_reply_follows_the_results() -> None:
    messages = history_messages(
        events(
            UserMessagePayload(text="go"),
            call("a"),
            result("a"),
            ConfirmationRequestedPayload(tool_calls=10, limit=10),
            TurnOutcomePayload(outcome=AgentConversationTurnOutcome.COMPLETED),
            UserMessagePayload(text="yes, carry on"),
        )
    )

    assert [type(message) for message in messages] == [
        ModelRequest,
        ModelResponse,
        ModelRequest,
        ModelRequest,
    ]
    assert isinstance(messages[-1].parts[0], UserPromptPart)


def test_a_turn_that_did_not_finish_is_still_labelled_after_its_tool_calls() -> None:
    messages = history_messages(
        events(
            UserMessagePayload(text="go"),
            call("a"),
            result("a"),
            TurnOutcomePayload(outcome=AgentConversationTurnOutcome.CANCELLED),
        )
    )

    assert isinstance(messages[-1].parts[0], SystemPromptPart)


def test_payloads_round_trip_through_storage() -> None:
    artifact = ArtifactRef(
        artifact_id=uuid4(), artifact_type="scalar.text", schema_version=1
    )
    payloads: list[AgentConversationEventPayload] = [
        call("a", path="one", count=3, nested={"k": [1, 2]}),
        ToolResultPayload(
            call_id="a",
            tool_id="t1",
            tool_name="read_text",
            ok=True,
            fingerprint="f" * 64,
            artifacts=(ToolResultArtifact(port="text", artifact=artifact),),
            model_view="hello",
        ),
        ConfirmationRequestedPayload(tool_calls=10, limit=10),
    ]

    for payload in payloads:
        assert event_payload_from_storage(event_payload_to_storage(payload)) == payload


def test_a_result_is_either_a_success_or_a_failure_not_both() -> None:
    artifact = ArtifactRef(
        artifact_id=uuid4(), artifact_type="scalar.text", schema_version=1
    )
    with pytest.raises(ValidationError):
        ToolResultPayload(
            call_id="a", tool_id="t", tool_name="n", ok=True, error="but it failed"
        )
    with pytest.raises(ValidationError):
        ToolResultPayload(
            call_id="a",
            tool_id="t",
            tool_name="n",
            ok=False,
            artifacts=(ToolResultArtifact(port="text", artifact=artifact),),
        )

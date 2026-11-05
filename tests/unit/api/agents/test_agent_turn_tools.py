"""A turn that calls tools (ADR 0021, issue #203).

The model is scripted round by round: a round is what it says when it is asked, and a tool
call ends a round, so the loop under test is the real one -- the run stops at the call,
Grafy executes it, and a new run resumes with the result. The toolbox is the real one over
fakes, so what is stored, announced and told back to the model is read from the durable
conversation and from what the scripted model was shown.
"""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from pydantic_ai.messages import ModelMessage, ToolReturnPart
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaThinkingPart,
    DeltaToolCall,
    FunctionModel,
)

from grafy_api.agents.toolbox import AgentToolbox
from grafy_api.agents.turns import MAX_AGENT_TURN_TOOL_CALLS
from grafy_api.runs.ports import ToolCallFailedError, ToolCallResult
from grafy_core.artifacts import ArtifactRef
from grafy_core.domain.agent_conversations import (
    AgentConversationTurnOutcome,
    ConfirmationRequestedPayload,
    ToolCallPayload,
    ToolResultPayload,
)
from grafy_core.domain.agent_turns import AgentTurnStatus
from grafy_core.domain.graph_documents import AgentToolLink, GraphOrigin
from tests.unit.api.agents.test_toolbox import (
    INTEGER,
    TEXT,
    FakeArtifacts,
    FakePorts,
    FakeViews,
)
from tests.unit.api.agents.turn_support import (
    GRAPH_ID,
    ScriptedModel,
    TurnHarness,
    agent as agent_with,
    no_dangling_turns as no_dangling_turns,  # noqa: F401 - autouse fixture
    stored_outcome,
)
from tests.unit.kernel.builders import make_node

type Say = str
type Call = tuple[str, dict[str, object]]


class Thought(str):
    """Something the model reasoned, which it does not say."""


type Round = Sequence[Say | Thought | Call]


@dataclass
class RoundsModel(ScriptedModel):
    """A model that answers round by round, and keeps what it was told each time."""

    rounds: Sequence[Round] = ()
    told: list[list[ModelMessage]] = field(default_factory=list)

    def model(self) -> FunctionModel:
        async def stream(messages: list[ModelMessage], info: AgentInfo):
            self.told.append(list(messages))
            self.started.set()
            index = len(self.told) - 1
            script = self.rounds[min(index, len(self.rounds) - 1)]
            for number, item in enumerate(script):
                if isinstance(item, Thought):
                    yield {number: DeltaThinkingPart(content=str(item))}
                elif isinstance(item, str):
                    yield item
                else:
                    name, arguments = item
                    yield {
                        number: DeltaToolCall(
                            name=name,
                            json_args=json.dumps(arguments),
                            tool_call_id=f"call-{index}-{number}",
                        )
                    }
            self.completed.set()

        return FunctionModel(stream_function=stream)


class Computation:
    """``RunService.call_tool`` as the toolbox sees it, held until a test lets it go."""

    def __init__(self) -> None:
        self.calls: list[list[GraphOrigin]] = []
        self.cancelled = 0
        self.hold: asyncio.Event | None = None
        self.entered = asyncio.Event()
        self.failure: Exception | None = None

    async def __call__(
        self, *, graph_id: str, node_id: str, arguments: Sequence[GraphOrigin]
    ) -> ToolCallResult:
        self.calls.append(list(arguments))
        self.entered.set()
        if self.hold is not None:
            try:
                await self.hold.wait()
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        if self.failure is not None:
            raise self.failure
        return ToolCallResult(
            fingerprint="f" * 64,
            outputs={
                "text": ArtifactRef.from_key(artifact_id=UUID(int=40), key=TEXT),
                "count": ArtifactRef.from_key(artifact_id=UUID(int=41), key=INTEGER),
            },
        )


def tool_link() -> AgentToolLink:
    return AgentToolLink(
        id="t1", node_id="search", name="search_letters", filled_ports=("query",)
    )


def harness(
    rounds: Sequence[Round], computation: Computation
) -> tuple[TurnHarness, RoundsModel]:
    model = RoundsModel(chunks=[], rounds=rounds)

    def toolbox_factory(workspace, project, graph, agent, document):
        del project
        return AgentToolbox.build(
            agent=agent,
            document=document,
            graph_id=graph,
            workspace_id=workspace,
            node_ports=FakePorts(),
            computation=computation,
            artifacts=FakeArtifacts(),
            views=FakeViews(),
        )

    configured = agent_with()
    configured = configured.model_copy(update={"tools": (tool_link(),)})
    return (
        TurnHarness(
            model,
            agents=[configured],
            nodes=[make_node("search")],
            toolbox_factory=toolbox_factory,
        ),
        model,
    )


def search(**arguments: object) -> Call:
    return ("search_letters", arguments)


async def test_a_turn_calls_a_tool_and_answers_from_the_result() -> None:
    computation = Computation()
    harness_, model = harness(
        [["Let me look. ", search(query="dear sir")], ["It says hello."]], computation
    )

    await harness_.send()
    turn = await harness_.settle()

    assert turn.status is AgentTurnStatus.COMPLETED
    # What was said, what was asked, what came back, what was concluded -- in that order.
    assert await harness_.kinds() == [
        "user_message",
        "assistant_message",
        "tool_call",
        "tool_result",
        "assistant_message",
        "turn_outcome",
    ]
    events = await harness_.events()
    call = events[2].payload
    result = events[3].payload
    assert isinstance(call, ToolCallPayload) and isinstance(result, ToolResultPayload)
    assert (call.tool_name, call.arguments) == ("search_letters", {"query": "dear sir"})
    assert (result.call_id, result.ok, result.fingerprint) == (
        call.call_id,
        True,
        "f" * 64,
    )
    assert [artifact.port for artifact in result.artifacts] == ["text", "count"]
    assert len(computation.calls) == 1
    # The model was told the result under the id it called with.
    returned = [
        part
        for message in model.told[1]
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert [(part.tool_call_id, part.content) for part in returned] == [
        (call.call_id, "seen: count,text")
    ]


async def test_the_calls_of_one_response_all_run_and_all_answer() -> None:
    computation = Computation()
    harness_, _ = harness(
        [[search(query="one"), search(query="two")], ["Both said hello."]], computation
    )

    await harness_.send()
    await harness_.settle()

    kinds = await harness_.kinds()
    assert kinds.count("tool_call") == 2
    assert kinds.count("tool_result") == 2
    assert len(computation.calls) == 2


async def test_a_failing_call_is_told_to_the_model_and_the_turn_goes_on() -> None:
    computation = Computation()
    computation.failure = ToolCallFailedError("the table has no such column")
    harness_, model = harness(
        [[search(query="dear sir")], ["That did not work, sorry."]], computation
    )

    await harness_.send()
    turn = await harness_.settle()

    assert turn.status is AgentTurnStatus.COMPLETED
    result = next(
        event.payload
        for event in await harness_.events()
        if isinstance(event.payload, ToolResultPayload)
    )
    assert not result.ok
    assert "no such column" in (result.error or "")
    (told,) = [
        part
        for message in model.told[1]
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert "no such column" in str(told.content)


async def test_a_call_with_bad_arguments_is_answered_without_computing() -> None:
    computation = Computation()
    harness_, _ = harness([[search(query=5)], ["Let me try again."]], computation)

    await harness_.send()
    await harness_.settle()

    assert computation.calls == []
    result = next(
        event.payload
        for event in await harness_.events()
        if isinstance(event.payload, ToolResultPayload)
    )
    assert not result.ok
    assert "must be a string" in (result.error or "")


async def test_a_turn_stops_and_asks_before_a_call_past_the_limit() -> None:
    computation = Computation()
    harness_, model = harness([[search(query="again")]], computation)

    await harness_.send()
    turn = await harness_.settle()

    # Ten calls ran, one per round; the eleventh was asked for and neither run nor stored.
    assert turn.status is AgentTurnStatus.COMPLETED
    kinds = await harness_.kinds()
    assert kinds.count("tool_call") == MAX_AGENT_TURN_TOOL_CALLS
    assert kinds.count("tool_result") == MAX_AGENT_TURN_TOOL_CALLS
    assert len(computation.calls) == MAX_AGENT_TURN_TOOL_CALLS
    assert len(model.told) == MAX_AGENT_TURN_TOOL_CALLS + 1
    events = await harness_.events()
    asked = [
        e.payload for e in events if isinstance(e.payload, ConfirmationRequestedPayload)
    ]
    assert [(a.tool_calls, a.limit) for a in asked] == [
        (MAX_AGENT_TURN_TOOL_CALLS, MAX_AGENT_TURN_TOOL_CALLS)
    ]
    assert kinds[-2:] == ["confirmation_requested", "turn_outcome"]
    assert stored_outcome(events[-1]) is AgentConversationTurnOutcome.COMPLETED


async def test_the_reply_to_a_confirmation_carries_on_from_the_results() -> None:
    computation = Computation()
    harness_, model = harness([[search(query="again")]], computation)
    await harness_.send()
    await harness_.settle()
    before = len(model.told)

    # The person says go on; the model answers from what it already has.
    model.rounds = [["Here is what I found."]]
    await harness_.send("Yes, carry on.", turn_id="client-2")
    await harness_.settle()

    told = model.told[before]
    returned = [
        part
        for message in told
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert len(returned) == MAX_AGENT_TURN_TOOL_CALLS
    assert (await harness_.kinds())[-2:] == ["assistant_message", "turn_outcome"]


async def test_cancelling_during_a_call_withdraws_it_and_stores_no_result() -> None:
    computation = Computation()
    computation.hold = asyncio.Event()
    harness_, _ = harness([[search(query="dear sir")]], computation)
    conversation = await harness_.thread()

    await harness_.send()
    await asyncio.wait_for(computation.entered.wait(), 5)
    await harness_.service.cancel(access=_access(), conversation_id=conversation.id)
    turn = await harness_.settle(release=False)

    assert turn.status is AgentTurnStatus.CANCELLED
    assert computation.cancelled == 1
    kinds = await harness_.kinds()
    assert "tool_result" not in kinds
    assert kinds[-1] == "turn_outcome"


async def test_an_agent_with_no_tools_never_asks_for_a_toolbox() -> None:
    asked: list[object] = []
    model = RoundsModel(chunks=[], rounds=[["Plain answer."]])
    harness_ = TurnHarness(
        model, toolbox_factory=lambda *args: asked.append(args) or None
    )

    await harness_.send()
    await harness_.settle()

    assert asked == []
    assert await harness_.kinds() == [
        "user_message",
        "assistant_message",
        "turn_outcome",
    ]


def _access():
    from tests.unit.api.agents.turn_support import access

    return access()


assert GRAPH_ID  # the Graph the tool's node lives on


async def test_thinking_is_stored_apart_from_the_answer_and_not_told_back() -> None:
    computation = Computation()
    harness_, _ = harness(
        [
            [Thought("The user wants letters. "), "Let me look. ", search(query="x")],
            [Thought("It found one."), "It says hello."],
        ],
        computation,
    )

    await harness_.send()
    turn = await harness_.settle()

    assert turn.status is AgentTurnStatus.COMPLETED
    # Each stretch of reasoning comes ahead of what the model did next with it.
    assert await harness_.kinds() == [
        "user_message",
        "assistant_thinking",
        "assistant_message",
        "tool_call",
        "tool_result",
        "assistant_thinking",
        "assistant_message",
        "turn_outcome",
    ]
    events = await harness_.events()
    thoughts = [
        event.payload.text
        for event in events
        if event.payload.kind == "assistant_thinking"
    ]
    messages = [
        event.payload.text
        for event in events
        if event.payload.kind == "assistant_message"
    ]
    assert thoughts == ["The user wants letters. ", "It found one."]
    assert messages == ["Let me look. ", "It says hello."]
    # Reasoning is not part of what the person is shown streaming as the reply.
    assert "letters" not in harness_.publisher.streamed_text

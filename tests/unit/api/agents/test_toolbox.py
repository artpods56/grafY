"""The toolbox: what a link offers a model, and what a call does (ADR 0021, issue #203)."""

from collections.abc import Mapping, Sequence
from uuid import UUID, uuid5

import pytest

from grafy_api.agents.toolbox import (
    CREATE_ARTIFACT_TOOL,
    MAX_CREATED_ARTIFACT_CHARS,
    AgentToolbox,
    JsonType,
    PortFacts,
)
from grafy_api.runs.ports import RunRejectedError, ToolCallFailedError, ToolCallResult
from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
from grafy_core.domain.agent_conversations import ToolCallPayload
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.graph_documents import (
    AgentToolLink,
    GraphAgent,
    GraphDocument,
    GraphNode,
    GraphOrigin,
)
from tests.unit.kernel.builders import make_node

WORKSPACE = UUID(int=1)
TEXT = ArtifactTypeKey("scalar.text", 1)
INTEGER = ArtifactTypeKey("scalar.integer", 1)
TABLE = ArtifactTypeKey("table.data", 1)


class FakePorts:
    """One operator, ``search``: inputs ``query`` (text), ``limit`` (integer, optional),
    ``rows`` (a table, which a model cannot write); outputs ``text`` and ``count``."""

    def __init__(self) -> None:
        self.inputs = [
            PortFacts("query", TEXT, description="What to look for"),
            PortFacts("limit", INTEGER, required=False),
            PortFacts("rows", TABLE),
        ]
        self.outputs = [PortFacts("text", TEXT), PortFacts("count", INTEGER)]

    def input_ports(self, node: GraphNode) -> Sequence[PortFacts] | None:
        return None if node.operator_id == "ghost" else self.inputs

    def output_ports(self, node: GraphNode) -> Sequence[PortFacts] | None:
        return None if node.operator_id == "ghost" else self.outputs

    def title(self, node: GraphNode) -> str:
        return "Search the letters"


class FakeArtifacts:
    """Content-addressed like the real seam: equal content, equal artifact id."""

    def __init__(self) -> None:
        self.writes: list[tuple[ArtifactTypeKey, str | int]] = []

    def json_type(self, key: ArtifactTypeKey) -> JsonType | None:
        return {TEXT: "string", INTEGER: "integer"}.get(key)

    async def ref_for(
        self, *, workspace_id: UUID, key: ArtifactTypeKey, value: str | int
    ) -> ArtifactRef:
        self.writes.append((key, value))
        return ArtifactRef.from_key(
            artifact_id=uuid5(workspace_id, f"{key.id}:{value!r}"), key=key
        )


class FakeComputation:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[GraphOrigin]]] = []
        self.raises: Exception | None = None

    async def __call__(
        self, *, graph_id: str, node_id: str, arguments: Sequence[GraphOrigin]
    ) -> ToolCallResult:
        self.calls.append((graph_id, node_id, list(arguments)))
        if self.raises is not None:
            raise self.raises
        text = ArtifactRef.from_key(artifact_id=UUID(int=10), key=TEXT)
        count = ArtifactRef.from_key(artifact_id=UUID(int=11), key=INTEGER)
        return ToolCallResult(
            fingerprint="f" * 64, outputs={"text": text, "count": count}
        )


class FakeViews:
    async def render(self, *, outputs: Mapping[str, ArtifactOutputValue]) -> str:
        return "seen: " + ",".join(sorted(outputs))


def build(
    *links: AgentToolLink,
    nodes: Sequence[GraphNode] = (),
    computation: FakeComputation | None = None,
    artifacts: FakeArtifacts | None = None,
) -> tuple[AgentToolbox, FakeComputation, FakeArtifacts]:
    computation = computation or FakeComputation()
    artifacts = artifacts or FakeArtifacts()
    toolbox = AgentToolbox.build(
        agent=GraphAgent(id="a", name="A", tools=tuple(links)),
        document=GraphDocument(nodes=tuple(nodes or (make_node("search"),))),
        graph_id="main",
        workspace_id=WORKSPACE,
        node_ports=FakePorts(),
        computation=computation,
        artifacts=artifacts,
        views=FakeViews(),
    )
    return toolbox, computation, artifacts


def link(**fields: object) -> AgentToolLink:
    base: dict[str, object] = {
        "id": "t1",
        "node_id": "search",
        "name": "search_letters",
        "filled_ports": ("query", "limit"),
    }
    return AgentToolLink.model_validate({**base, **fields})


def call(**arguments: object) -> ToolCallPayload:
    return ToolCallPayload(
        call_id="c1", tool_id="t1", tool_name="search_letters", arguments=arguments
    )


def test_a_link_becomes_a_tool_whose_schema_is_its_filled_ports() -> None:
    toolbox, _, _ = build(link())

    (tool,) = toolbox.tools
    assert tool.description == "Search the letters"
    assert tool.json_schema == {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for"},
            "limit": {"type": "integer", "description": "limit"},
        },
        "required": ["query"],
        "additionalProperties": False,
    }


def test_the_links_own_description_wins() -> None:
    toolbox, _, _ = build(link(description="Find a phrase in the correspondence"))

    assert toolbox.tools[0].description == "Find a phrase in the correspondence"


@pytest.mark.parametrize(
    ("fields", "nodes", "reason"),
    [
        ({"filled_ports": ("rows",)}, (), "cannot write in a call"),
        ({"filled_ports": ("nope",)}, (), "no input 'nope'"),
        ({"returned_ports": ("nope",)}, (), "no output 'nope'"),
        ({"node_id": "gone"}, (), "no longer on this Graph"),
        ({}, (make_node("search", operator_id="ghost"),), "does not have the node's"),
    ],
)
def test_a_link_the_toolbox_cannot_offer_says_why(fields, nodes, reason) -> None:
    toolbox, _, _ = build(link(**fields), nodes=nodes)

    assert toolbox.tools == ()
    (missing,) = toolbox.unavailable
    assert missing.tool_id == "t1"
    assert reason in missing.reason


async def test_a_call_computes_with_the_arguments_as_origins() -> None:
    toolbox, computation, artifacts = build(link())

    result = await toolbox.execute(call(query="dear sir", limit=3))

    assert result.ok
    assert (result.tool_id, result.tool_name, result.call_id) == (
        "t1",
        "search_letters",
        "c1",
    )
    assert result.fingerprint == "f" * 64
    assert [artifact.port for artifact in result.artifacts] == ["text", "count"]
    assert result.model_view == "seen: count,text"
    ((graph_id, node_id, origins),) = computation.calls
    assert (graph_id, node_id) == ("main", "search")
    assert {(o.to_port, o.to_node) for o in origins} == {
        ("query", "search"),
        ("limit", "search"),
    }
    assert artifacts.writes == [(TEXT, "dear sir"), (INTEGER, 3)]


async def test_equal_arguments_reach_the_kernel_as_equal_origins() -> None:
    toolbox, computation, _ = build(link())

    await toolbox.execute(call(query="dear sir"))
    await toolbox.execute(call(query="dear sir"))
    await toolbox.execute(call(query="dear madam"))

    first, second, third = (calls[2] for calls in computation.calls)
    assert first[0].value == second[0].value
    assert first[0].value != third[0].value


async def test_only_the_returned_ports_come_back() -> None:
    toolbox, _, _ = build(link(returned_ports=("count",)))

    result = await toolbox.execute(call(query="x"))

    assert [artifact.port for artifact in result.artifacts] == ["count"]
    assert result.model_view == "seen: count"


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({}, "Missing required argument 'query'"),
        ({"query": 5}, "'query' must be a string"),
        ({"query": "x", "limit": "3"}, "'limit' must be an integer"),
        ({"query": "x", "limit": True}, "'limit' must be an integer"),
        ({"query": "x", "extra": 1}, "Unknown argument(s): extra"),
    ],
)
async def test_bad_arguments_are_answered_and_never_computed(
    arguments, expected
) -> None:
    toolbox, computation, artifacts = build(link())

    result = await toolbox.execute(call(**arguments))

    assert not result.ok
    assert expected in (result.error or "")
    assert computation.calls == []
    assert artifacts.writes == []


async def test_an_unknown_tool_is_answered() -> None:
    toolbox, computation, _ = build(link())

    result = await toolbox.execute(
        ToolCallPayload(call_id="c9", tool_id="x", tool_name="burn_it_down")
    )

    assert not result.ok
    assert "no tool named 'burn_it_down'" in (result.error or "")
    assert computation.calls == []


@pytest.mark.parametrize(
    "failure",
    [
        ToolCallFailedError("the table has no such column"),
        RunRejectedError("unknown_operator", "this build has no such operator"),
    ],
)
async def test_a_failing_computation_is_answered_in_its_own_words(failure) -> None:
    computation = FakeComputation()
    computation.raises = failure
    toolbox, _, _ = build(link(), computation=computation)

    result = await toolbox.execute(call(query="x"))

    assert not result.ok
    assert str(failure) in (result.error or "")


async def test_cancellation_is_not_swallowed() -> None:
    import asyncio

    computation = FakeComputation()
    computation.raises = asyncio.CancelledError()
    toolbox, _, _ = build(link(), computation=computation)

    with pytest.raises(asyncio.CancelledError):
        await toolbox.execute(call(query="x"))


def create(**arguments: object) -> ToolCallPayload:
    return ToolCallPayload(
        call_id="c1",
        tool_id=CREATE_ARTIFACT_TOOL,
        tool_name=CREATE_ARTIFACT_TOOL,
        arguments=arguments,
    )


async def test_created_text_becomes_a_text_artifact_without_computing() -> None:
    toolbox, computation, artifacts = build()

    result = await toolbox.execute(create(content="<h1>Hi</h1>"))

    assert result.ok and computation.calls == []
    assert artifacts.writes == [(TEXT, "<h1>Hi</h1>")]
    assert [item.port for item in result.artifacts] == ["artifact"]
    # What was written is already in the call: the model is not told it twice.
    assert "<h1>" not in result.model_view


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"content": 1},
        {"content": "x", "title": "y"},
        {"content": "  "},
        {"content": "x" * (MAX_CREATED_ARTIFACT_CHARS + 1)},
    ],
)
async def test_created_text_that_cannot_be_saved_is_answered(arguments) -> None:
    toolbox, _, artifacts = build()

    result = await toolbox.execute(create(**arguments))

    assert not result.ok and result.error
    assert artifacts.writes == []


async def test_a_link_of_the_same_name_is_the_tool_called() -> None:
    toolbox, computation, artifacts = build(link(name=CREATE_ARTIFACT_TOOL))

    result = await toolbox.execute(create(query="x"))

    assert result.ok and len(computation.calls) == 1
    assert artifacts.writes == [(TEXT, "x")]

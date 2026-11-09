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
from grafy_core.artifact_contracts import HTML_PAGE
from grafy_core.artifacts import ArtifactObject, ArtifactRef, ArtifactTypeKey
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
    """Content-addressed like the real seam: equal content, equal artifact id.

    ``by_id`` is what a page may look up. ``pages`` records each page write.
    """

    def __init__(self) -> None:
        self.writes: list[tuple[ArtifactTypeKey, str | int]] = []
        self.pages: list[tuple[str, dict[str, ArtifactRef]]] = []
        self.by_id: dict[UUID, ArtifactObject] = {}

    def json_type(self, key: ArtifactTypeKey) -> JsonType | None:
        return {TEXT: "string", INTEGER: "integer"}.get(key)

    async def ref_for(
        self, *, workspace_id: UUID, key: ArtifactTypeKey, value: str | int
    ) -> ArtifactRef:
        self.writes.append((key, value))
        return ArtifactRef.from_key(
            artifact_id=uuid5(workspace_id, f"{key.id}:{value!r}"), key=key
        )

    async def page_for(
        self,
        *,
        workspace_id: UUID,
        html: str,
        sources: Mapping[str, ArtifactRef],
    ) -> ArtifactRef:
        named = dict(sources)
        self.pages.append((html, named))
        self.writes.append((HTML_PAGE.key, html))
        joined = "|".join(
            f"{name}:{ref.artifact_id}" for name, ref in sorted(named.items())
        )
        return ArtifactRef.from_key(
            artifact_id=uuid5(workspace_id, f"html.page:{html}:{joined}"),
            key=HTML_PAGE.key,
        )

    async def get_artifact(
        self, *, workspace_id: UUID, artifact_id: UUID
    ) -> ArtifactObject | None:
        del workspace_id
        return self.by_id.get(artifact_id)


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
    assert artifacts.pages == []
    assert [item.port for item in result.artifacts] == ["artifact"]
    # What was written is already in the call: the model is not told it twice.
    saved = result.artifacts[0].artifact
    assert isinstance(saved, ArtifactRef)
    assert f"Artifact id: {saved.artifact_id} (scalar.text)" in result.model_view
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
    assert artifacts.pages == []


def held(
    artifact_id: UUID,
    *,
    artifact_type: str = "scalar.text",
    schema_version: int = 1,
    content_type: str = "application/json",
    inline_payload: dict[str, object] | None = None,
) -> ArtifactObject:
    """One artifact a page's lookup can find. Inline when a payload is given."""

    if inline_payload is None and artifact_type == "scalar.text":
        inline_payload = {"value": "hello"}
    inline = inline_payload is not None
    return ArtifactObject(
        id=artifact_id,
        workspace_id=WORKSPACE,
        artifact_type=artifact_type,
        schema_version=schema_version,
        content_type=content_type,
        storage_backend="inline" if inline else "local",
        inline_payload=inline_payload,
        bucket=None if inline else "artifacts",
        object_key=None if inline else artifact_id.hex,
        byte_size=None if inline else 12,
    )


def _page(content: str, sources: object) -> ToolCallPayload:
    return create(content=content, sources=sources)


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        (None, "must be an object"),
        ("nope", "must be an object"),
        ([], "must be an object"),
        ({}, "at least one"),
        ({"1bad": str(UUID(int=2))}, "letter or underscore"),
        ({"has-dash": str(UUID(int=2))}, "letter or underscore"),
        ({"ok": 1}, "artifact id string"),
        ({"ok": True}, "artifact id string"),
        ({"ok": "not-a-uuid"}, "must be an artifact id"),
        (
            {f"s{n}": str(UUID(int=n + 1)) for n in range(17)},
            "at most 16",
        ),
        ({"missing": str(UUID(int=99))}, "does not have"),
    ],
)
async def test_a_page_with_bad_sources_writes_nothing(
    sources: object, expected: str
) -> None:
    toolbox, _, artifacts = build()

    result = await toolbox.execute(_page("<p>{{s0}}</p>", sources))

    assert not result.ok
    assert expected in (result.error or "")
    assert artifacts.writes == []
    assert artifacts.pages == []


async def test_an_allowed_id_this_workspace_does_not_have_writes_nothing() -> None:
    artifacts = FakeArtifacts()
    toolbox, _, _ = build(artifacts=artifacts)
    missing = UUID(int=99)
    toolbox.allow((ArtifactRef.from_key(artifact_id=missing, key=TEXT),))

    result = await toolbox.execute(_page("<p>{{gone}}</p>", {"gone": str(missing)}))

    assert not result.ok
    assert "does not have" in (result.error or "")
    assert artifacts.pages == []


async def test_a_page_refuses_an_artifact_that_was_not_offered() -> None:
    artifacts = FakeArtifacts()
    outsider = UUID(int=90)
    artifacts.by_id[outsider] = held(outsider)
    toolbox, _, _ = build(artifacts=artifacts)

    result = await toolbox.execute(_page("<p>{{nope}}</p>", {"nope": str(outsider)}))

    assert not result.ok
    assert "not connected" in (result.error or "")
    assert artifacts.pages == []


async def test_a_page_may_name_an_artifact_the_turn_allowed() -> None:
    artifacts = FakeArtifacts()
    connected = UUID(int=70)
    artifacts.by_id[connected] = held(connected, schema_version=2)
    toolbox, computation, _ = build(artifacts=artifacts)
    toolbox.allow((artifacts.by_id[connected].ref(),))

    result = await toolbox.execute(
        _page("<p>{{baptisms}}</p>", {"baptisms": str(connected)})
    )

    assert result.ok and computation.calls == []
    assert len(artifacts.pages) == 1
    html, sources = artifacts.pages[0]
    assert html == "<p>{{baptisms}}</p>"
    assert sources["baptisms"].artifact_id == connected
    assert sources["baptisms"].artifact_type == "scalar.text"
    assert sources["baptisms"].schema_version == 2
    saved = result.artifacts[0].artifact
    assert isinstance(saved, ArtifactRef)
    assert saved.artifact_type == "html.page"
    assert saved.schema_version == 1
    assert "<p>" not in result.model_view
    assert f"Artifact id: {saved.artifact_id} (html.page)" in result.model_view
    assert "baptisms (scalar.text)" in result.model_view


async def test_a_page_may_name_what_this_turn_returned() -> None:
    artifacts = FakeArtifacts()
    returned = UUID(int=10)
    artifacts.by_id[returned] = held(returned)
    toolbox, _, _ = build(link(), artifacts=artifacts)

    await toolbox.execute(call(query="dear sir"))
    result = await toolbox.execute(_page("<p>{{found}}</p>", {"found": str(returned)}))

    assert result.ok
    assert artifacts.pages[0][1]["found"].artifact_id == returned
    # The integer output came back too, and is allowed, but was not named.
    assert UUID(int=11) not in artifacts.pages[0][1]


async def test_a_page_reads_json_and_tables_and_refuses_a_file() -> None:
    artifacts = FakeArtifacts()
    table = UUID(int=13)
    document = UUID(int=14)
    scan = UUID(int=15)
    artifacts.by_id[table] = held(
        table,
        artifact_type="table.data",
        content_type="application/octet-stream",
        inline_payload=None,
    )
    artifacts.by_id[document] = held(
        document,
        artifact_type="file.geojson",
        content_type="application/geo+json; charset=utf-8",
        inline_payload=None,
    )
    artifacts.by_id[scan] = held(
        scan,
        artifact_type="file.pdf",
        content_type="application/pdf",
        inline_payload=None,
    )
    toolbox, _, _ = build(artifacts=artifacts)
    toolbox.allow(
        artifact.ref()
        for artifact in (
            artifacts.by_id[table],
            artifacts.by_id[document],
            artifacts.by_id[scan],
        )
    )

    written = await toolbox.execute(
        _page(
            "<p>{{census}}{{place}}</p>",
            {"census": str(table), "place": str(document)},
        )
    )
    refused = await toolbox.execute(_page("<p>{{scan}}</p>", {"scan": str(scan)}))

    assert written.ok
    assert artifacts.pages[0][1]["census"].artifact_type == "table.data"
    assert artifacts.pages[0][1]["place"].artifact_type == "file.geojson"
    assert "census (table.data)" in written.model_view
    assert not refused.ok
    assert "file.pdf@1" in (refused.error or "")
    assert "application/pdf" in (refused.error or "")
    assert len(artifacts.pages) == 1

"""What is connected to an Agent is read fresh for each turn (ADR 0021, issue #203)."""

from collections.abc import Sequence
from types import SimpleNamespace
from uuid import UUID

from grafy_api.agents.context import ContextBlock, instructions_with_context
from grafy_api.agents.project_tools import ProjectContextReader
from grafy_api.services.families import build_application_registry
from grafy_core.artifacts import ArtifactObject, ArtifactRef, ArtifactRefSequence
from grafy_core.domain.graph_documents import (
    AgentContextLink,
    GraphAgent,
    GraphDocument,
    GraphPresentationDocument,
    GraphPresentationViewer,
)
from grafy_core.kernel.results import StoredResult
from grafy_core.runtime.in_memory import InMemoryDataStore, InMemoryUnitOfWork
from tests.unit.api.agents.turn_support import (
    ScriptedModel,
    TurnHarness,
    agent as agent_with,
    no_dangling_turns as no_dangling_turns,  # noqa: F401 - autouse fixture
)
from tests.unit.kernel.builders import make_node

WORKSPACE = UUID(int=800)
PROJECT = UUID(int=802)


def test_instructions_carry_the_context_after_what_the_agent_was_told() -> None:
    blocks = [
        ContextBlock("The diary, output text", "The water rose on the third day.")
    ]

    told = instructions_with_context("Answer from the sources.", blocks)

    assert told is not None
    assert told.startswith("Answer from the sources.")
    assert "## The diary, output text\nThe water rose on the third day." in told


def test_no_context_leaves_the_instructions_as_they_were() -> None:
    assert instructions_with_context("Be brief.", []) == "Be brief."
    assert instructions_with_context("", []) is None


def test_context_alone_is_still_instructions() -> None:
    told = instructions_with_context("", [ContextBlock("A card", "hello")])

    assert told is not None and told.startswith("# Context connected to you")


class ScriptedReader:
    def __init__(self, blocks: Sequence[ContextBlock]) -> None:
        self.blocks = blocks
        self.calls = 0

    async def read(self, **_: object) -> Sequence[ContextBlock]:
        self.calls += 1
        return self.blocks


async def test_a_turn_tells_the_model_its_context_and_reads_it_for_that_turn() -> None:
    reader = ScriptedReader([ContextBlock("A card on the canvas", "dear sir")])
    link = AgentContextLink(id="c1", kind="card", card_id="artifact-viewer-card-1")
    model = ScriptedModel(chunks=["Understood."])
    harness = TurnHarness(
        model,
        agents=[agent_with().model_copy(update={"context": (link,)})],
        context_reader=reader,
    )

    await harness.send()
    await harness.settle()

    (told,) = model.seen_instructions
    assert told is not None and "## A card on the canvas\ndear sir" in told
    assert reader.calls == 1


async def test_an_agent_with_nothing_connected_never_asks_the_reader() -> None:
    reader = ScriptedReader([ContextBlock("never", "never")])
    harness = TurnHarness(ScriptedModel(chunks=["Hello."]), context_reader=reader)

    await harness.send()
    await harness.settle()

    assert reader.calls == 0


# --- The reader over the Run service and the artifact store ------------------


class FakeRuns:
    """``instance_result`` the way the Run service answers it."""

    def __init__(self) -> None:
        self.results: dict[str, StoredResult | None] = {}
        self.asked: list[str] = []

    async def instance_result(self, *, workspace_id, project_id, key):
        self.asked.append(key.node_id)
        result = self.results[key.node_id]
        state = SimpleNamespace(value="fresh" if result else "stale")
        return SimpleNamespace(state=state), result


def text_object(text: str) -> ArtifactObject:
    return ArtifactObject(
        workspace_id=WORKSPACE,
        artifact_type="scalar.text",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": text},
    )


async def reader_over(store: InMemoryDataStore, runs: FakeRuns) -> ProjectContextReader:
    return ProjectContextReader(
        runs=runs,  # type: ignore[arg-type]
        registry=build_application_registry(),
        unit_of_work_factory=lambda: InMemoryUnitOfWork(store),
        storage=None,  # type: ignore[arg-type]
    )


async def test_the_reader_tells_each_kind_what_it_holds_now() -> None:
    store = InMemoryDataStore()
    runs = FakeRuns()
    async with InMemoryUnitOfWork(store) as unit_of_work:
        node_text = text_object("from the node")
        card_text = text_object("from the card")
        library_text = text_object("from the Library")
        for artifact in (node_text, card_text, library_text):
            await unit_of_work.artifacts.add(artifact)
        await unit_of_work.commit()
    from datetime import UTC, datetime

    runs.results["reader"] = StoredResult(
        fingerprint="f" * 64,
        outputs={"text": node_text.ref()},
        created_at=datetime.now(UTC),
    )
    document = GraphDocument(
        nodes=(make_node("reader"),),
        presentation=GraphPresentationDocument(
            viewers=(
                GraphPresentationViewer.model_validate(
                    {
                        "id": "artifact-viewer-card-1",
                        "position": {"x": 0, "y": 0},
                        "artifact_ref": card_text.ref().model_dump(mode="json"),
                    }
                ),
            )
        ),
    )
    agent = GraphAgent(
        id="a",
        name="A",
        context=(
            AgentContextLink(
                id="c1", kind="node_output", node_id="reader", port="text"
            ),
            AgentContextLink(id="c2", kind="card", card_id="artifact-viewer-card-1"),
            AgentContextLink(
                id="c3", kind="library_item", library_item_id=library_text.id
            ),
        ),
    )

    blocks = await (await reader_over(store, runs)).read(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id="main",
        agent=agent,
        document=document,
    )

    assert [block.text for block in blocks] == [
        f"Artifact id: {node_text.id} (scalar.text)\nfrom the node",
        f"Artifact id: {card_text.id} (scalar.text)\nfrom the card",
        f"Artifact id: {library_text.id} (scalar.text)\nfrom the Library",
    ]
    assert [block.artifacts for block in blocks] == [
        (node_text.ref(),),
        (card_text.ref(),),
        (library_text.ref(),),
    ]
    assert runs.asked == ["reader"]


async def test_what_cannot_be_read_is_said_not_dropped() -> None:
    store = InMemoryDataStore()
    runs = FakeRuns()
    runs.results["reader"] = None
    document = GraphDocument(nodes=(make_node("reader"),))
    agent = GraphAgent(
        id="a",
        name="A",
        context=(
            AgentContextLink(
                id="c1", kind="node_output", node_id="reader", port="text"
            ),
            AgentContextLink(id="c2", kind="card", card_id="gone"),
            AgentContextLink(id="c3", kind="library_item", library_item_id=UUID(int=5)),
        ),
    )

    blocks = await (await reader_over(store, runs)).read(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id="main",
        agent=agent,
        document=document,
    )

    assert "no result to show yet" in blocks[0].text and "stale" in blocks[0].text
    assert blocks[0].artifacts == ()
    assert blocks[1].text == "[this card is gone]"
    assert blocks[1].artifacts == ()
    assert "no longer available" in blocks[2].text
    assert str(UUID(int=5)) in blocks[2].text
    assert blocks[2].artifacts == ()


async def test_one_unreadable_link_does_not_end_the_rest() -> None:
    store = InMemoryDataStore()
    runs = FakeRuns()  # no result entry for the node: instance_result raises KeyError
    document = GraphDocument(nodes=(make_node("reader"),))
    agent = GraphAgent(
        id="a",
        name="A",
        context=(
            AgentContextLink(
                id="c1", kind="node_output", node_id="reader", port="text"
            ),
            AgentContextLink(id="c2", kind="card", card_id="gone"),
        ),
    )

    blocks = await (await reader_over(store, runs)).read(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id="main",
        agent=agent,
        document=document,
    )

    assert blocks[0].text == "[could not be read]"
    assert blocks[0].artifacts == ()
    assert blocks[1].text == "[this card is gone]"
    assert blocks[1].artifacts == ()


async def test_a_node_output_sequence_is_flattened_onto_the_block() -> None:
    from datetime import UTC, datetime

    store = InMemoryDataStore()
    runs = FakeRuns()
    async with InMemoryUnitOfWork(store) as unit_of_work:
        first = text_object("letter a")
        second = text_object("letter b")
        for artifact in (first, second):
            await unit_of_work.artifacts.add(artifact)
        await unit_of_work.commit()
    sequence = ArtifactRefSequence(
        artifact_type="scalar.text",
        schema_version=1,
        item_refs=[first.ref(), second.ref()],
    )
    runs.results["reader"] = StoredResult(
        fingerprint="f" * 64,
        outputs={"letters": sequence},
        created_at=datetime.now(UTC),
    )
    document = GraphDocument(nodes=(make_node("reader"),))
    agent = GraphAgent(
        id="a",
        name="A",
        context=(
            AgentContextLink(
                id="c1", kind="node_output", node_id="reader", port="letters"
            ),
        ),
    )

    blocks = await (await reader_over(store, runs)).read(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id="main",
        agent=agent,
        document=document,
    )

    assert blocks[0].artifacts == (first.ref(), second.ref())
    assert str(first.id) in blocks[0].text
    assert str(second.id) in blocks[0].text
    assert "letter a" in blocks[0].text and "letter b" in blocks[0].text


async def test_a_card_sequence_is_flattened_onto_the_block() -> None:
    store = InMemoryDataStore()
    async with InMemoryUnitOfWork(store) as unit_of_work:
        first = text_object("one")
        second = text_object("two")
        for artifact in (first, second):
            await unit_of_work.artifacts.add(artifact)
        await unit_of_work.commit()
    sequence = ArtifactRefSequence(
        artifact_type="scalar.text",
        schema_version=1,
        item_refs=[first.ref(), second.ref()],
    )
    document = GraphDocument(
        presentation=GraphPresentationDocument(
            viewers=(
                GraphPresentationViewer.model_validate(
                    {
                        "id": "artifact-viewer-card-1",
                        "position": {"x": 0, "y": 0},
                        "artifact_ref": sequence.model_dump(mode="json"),
                    }
                ),
            )
        )
    )
    agent = GraphAgent(
        id="a",
        name="A",
        context=(
            AgentContextLink(id="c1", kind="card", card_id="artifact-viewer-card-1"),
        ),
    )

    blocks = await (await reader_over(store, FakeRuns())).read(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id="main",
        agent=agent,
        document=document,
    )

    assert blocks[0].artifacts == (first.ref(), second.ref())
    assert "one" in blocks[0].text and "two" in blocks[0].text
    assert str(first.id) in blocks[0].text and str(second.id) in blocks[0].text


_ = ArtifactRef  # the reader's seam is exercised with real artifact refs above

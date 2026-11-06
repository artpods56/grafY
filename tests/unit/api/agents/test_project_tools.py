"""The toolbox's seams over the real registry and an in-memory artifact store."""

import json
from io import BytesIO
from uuid import UUID

import pytest

from grafy_api.agents.project_tools import (
    MAX_VIEW_CHARS,
    ArtifactModelViews,
    ContentAddressedArguments,
    RegistryNodePorts,
)
from grafy_api.agents.toolbox import AgentToolbox
from grafy_api.services.families import build_application_registry
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
)
from grafy_core.domain.graph_documents import GraphAgent, GraphDocument
from grafy_core.runtime.in_memory import InMemoryDataStore, InMemoryUnitOfWork
from tests.unit.api.agents.test_toolbox import (
    FakeComputation,
    FakePorts,
    FakeViews,
    create,
)
from tests.unit.kernel.builders import make_node

WORKSPACE = UUID(int=900)
OTHER_WORKSPACE = UUID(int=901)
TEXT = ArtifactTypeKey("scalar.text", 1)
INTEGER = ArtifactTypeKey("scalar.integer", 1)


@pytest.fixture(scope="module")
def registry():
    return build_application_registry()


def arguments(registry, store: InMemoryDataStore) -> ContentAddressedArguments:
    return ContentAddressedArguments(
        registry=registry, unit_of_work_factory=lambda: InMemoryUnitOfWork(store)
    )


def test_ports_come_from_the_registered_operator(registry) -> None:
    ports = RegistryNodePorts(registry)
    node = make_node("ocr", operator_id="mistral.ocr.process")

    inputs = {port.name: port for port in ports.input_ports(node) or ()}
    outputs = {port.name: port for port in ports.output_ports(node) or ()}

    assert inputs["document_url"].artifact_type == TEXT
    assert inputs["image"].artifact_type == ArtifactTypeKey("image.raster", 1)
    assert {"markdown", "blocks", "regions"} <= set(outputs)
    assert ports.title(node) == "Mistral OCR"


def test_a_node_this_deployment_does_not_have_has_no_ports(registry) -> None:
    ports = RegistryNodePorts(registry)
    ghost = make_node("g", operator_id="no.such.operator")

    assert ports.input_ports(ghost) is None
    assert ports.output_ports(ghost) is None
    assert ports.title(ghost) == "no.such.operator"


def test_a_model_may_write_text_and_integers_and_nothing_richer(registry) -> None:
    written = arguments(registry, InMemoryDataStore())

    assert written.json_type(TEXT) == "string"
    assert written.json_type(INTEGER) == "integer"
    assert written.json_type(ArtifactTypeKey("table.data", 1)) is None
    assert written.json_type(ArtifactTypeKey("image.raster", 1)) is None


async def test_equal_content_is_one_artifact_and_stored_once(registry) -> None:
    store = InMemoryDataStore()
    written = arguments(registry, store)

    first = await written.ref_for(workspace_id=WORKSPACE, key=TEXT, value="dear sir")
    again = await written.ref_for(workspace_id=WORKSPACE, key=TEXT, value="dear sir")
    other = await written.ref_for(workspace_id=WORKSPACE, key=TEXT, value="dear madam")

    assert first == again
    assert first.artifact_id != other.artifact_id
    async with InMemoryUnitOfWork(store) as unit_of_work:
        stored = await unit_of_work.artifacts.get(WORKSPACE, first.artifact_id)
    assert stored is not None
    assert stored.inline_payload == {"value": "dear sir"}
    assert stored.storage_backend == "inline"
    assert first.content_hash == stored.sha256


async def test_the_type_and_the_workspace_are_part_of_the_address(registry) -> None:
    written = arguments(registry, InMemoryDataStore())

    as_text = await written.ref_for(workspace_id=WORKSPACE, key=TEXT, value=7)
    as_integer = await written.ref_for(workspace_id=WORKSPACE, key=INTEGER, value=7)
    elsewhere = await written.ref_for(
        workspace_id=OTHER_WORKSPACE, key=INTEGER, value=7
    )

    assert (
        len({as_text.artifact_id, as_integer.artifact_id, elsewhere.artifact_id}) == 3
    )


async def put(store: InMemoryDataStore, artifact: ArtifactObject) -> ArtifactRef:
    async with InMemoryUnitOfWork(store) as unit_of_work:
        await unit_of_work.artifacts.add(artifact)
        await unit_of_work.commit()
    return artifact.ref()


def inline(key: ArtifactTypeKey, payload: dict[str, object]) -> ArtifactObject:
    return ArtifactObject(
        workspace_id=WORKSPACE,
        artifact_type=key.id,
        schema_version=key.schema_version,
        content_type="application/json",
        storage_backend="inline",
        inline_payload=payload,
    )


class BytesStorage:
    """``load`` only. Model views read a bounded prefix and nothing else."""

    def __init__(self, files: dict[tuple[str, str], bytes]) -> None:
        self.files = files

    async def load(self, bucket: str, path: str) -> BytesIO:
        return BytesIO(self.files[(bucket, path)])


def views(
    registry, store: InMemoryDataStore, storage: object | None = None
) -> ArtifactModelViews:
    return ArtifactModelViews(
        registry=registry,
        unit_of_work_factory=lambda: InMemoryUnitOfWork(store),
        storage=storage,  # type: ignore[arg-type] - inline artifacts never reach storage
        workspace_id=WORKSPACE,
    )


async def test_a_model_is_shown_the_text_of_a_scalar(registry) -> None:
    store = InMemoryDataStore()
    ref = await put(store, inline(TEXT, {"value": "dear sir, the water rose"}))

    seen = await views(registry, store).render(outputs={"text": ref})

    assert seen == (
        f"text:\nArtifact id: {ref.artifact_id} (scalar.text)\ndear sir, the water rose"
    )


async def test_a_long_value_is_clipped_and_says_so(registry) -> None:
    store = InMemoryDataStore()
    ref = await put(store, inline(TEXT, {"value": "x" * 25_000}))

    seen = await views(registry, store).render(outputs={"text": ref})

    assert "5000 more characters" in seen
    assert f"Artifact id: {ref.artifact_id} (scalar.text)" in seen
    assert len(seen) < 21_000


async def test_a_table_is_shown_as_its_first_rows_with_the_total(registry) -> None:
    store = InMemoryDataStore()
    table = {
        "columns": [
            {"id": "year", "title": "Year", "value_type": "unknown"},
            {"id": "event", "title": "Event", "value_type": "unknown"},
        ],
        "rows": [{"year": 1600 + n, "event": f"flood {n}"} for n in range(30)],
    }
    ref = await put(store, inline(ArtifactTypeKey("table.data", 1), table))

    seen = await views(registry, store).render(outputs={"table": ref})

    lines = seen.splitlines()
    assert lines[1].startswith("Artifact id:") and "(table.data)" in lines[1]
    assert lines[2] == "year (Year) | event (Event)"
    assert lines[4] == "1600 | flood 0"
    assert lines[-1] == "(showing 20 of 30 rows)"


async def test_a_sequence_shows_its_first_items(registry) -> None:
    store = InMemoryDataStore()
    refs = [await put(store, inline(TEXT, {"value": f"letter {n}"})) for n in range(7)]
    sequence = ArtifactRefSequence(
        artifact_type="scalar.text", schema_version=1, item_refs=refs
    )

    seen = await views(registry, store).render(outputs={"letters": sequence})

    assert "7 items:" in seen
    assert seen.count("Artifact id:") == 5
    assert "\n  letter 0" in seen and "\n  letter 4" in seen and "letter 5" not in seen
    assert "... and 2 more not shown" in seen


async def test_what_a_model_cannot_read_is_described_not_dumped(registry) -> None:
    store = InMemoryDataStore()
    document = ArtifactObject(
        workspace_id=WORKSPACE,
        artifact_type="file.pdf",
        schema_version=1,
        content_type="application/pdf",
        storage_backend="local",
        bucket="artifacts",
        object_key="scan.pdf",
        byte_size=12,
    )
    ref = await put(store, document)

    seen = await views(registry, store).render(outputs={"image": ref})

    assert f"Artifact id: {ref.artifact_id} (file.pdf)" in seen
    assert "not shown to you" in seen
    assert "scan.pdf" not in seen


async def test_a_vanished_artifact_is_named_and_a_tool_with_no_outputs_says_so(
    registry,
) -> None:
    gone = ArtifactRef(
        artifact_id=UUID(int=1), artifact_type="scalar.text", schema_version=1
    )
    store = InMemoryDataStore()

    seen = await views(registry, store).render(outputs={"text": gone})
    assert f"Artifact id: {gone.artifact_id} (scalar.text)" in seen
    assert "no longer available" in seen
    assert (
        await views(registry, store).render(outputs={}) == "The tool returned nothing."
    )


async def test_markdown_is_shown_as_its_text(registry) -> None:
    store = InMemoryDataStore()
    ref = await put(
        store, inline(ArtifactTypeKey("text.markdown", 1), {"markdown": "## Hi"})
    )

    seen = await views(registry, store).render(outputs={"note": ref})

    assert seen.endswith("## Hi")
    assert "{" not in seen


async def test_inline_json_is_shown_compact_and_clipped(registry) -> None:
    store = InMemoryDataStore()
    small = await put(
        store,
        inline(
            ArtifactTypeKey("record.entry", 1),
            {"event": "flood", "year": 1667},
        ),
    )
    huge = await put(
        store,
        inline(
            ArtifactTypeKey("record.entry", 1),
            {"note": "x" * 25_000, "year": 1667},
        ),
    )

    shown = await views(registry, store).render(outputs={"row": small})
    clipped = await views(registry, store).render(outputs={"row": huge})

    assert shown.endswith('{"event":"flood","year":1667}')
    assert f"Artifact id: {small.artifact_id} (record.entry)" in shown
    # `note` sorts first and fills the view, so `year` is past the cut.
    assert '"note":"' in clipped
    assert "more characters" in clipped
    assert f"Artifact id: {huge.artifact_id} (record.entry)" in clipped
    assert len(clipped) < 21_000


def filed(
    content_type: str, body: bytes, *, bucket: str | None = "artifacts"
) -> ArtifactObject:
    return ArtifactObject(
        workspace_id=WORKSPACE,
        artifact_type="file.json",
        schema_version=1,
        content_type=content_type,
        storage_backend="s3",
        bucket=bucket,
        object_key=None if bucket is None else "one.json",
        byte_size=len(body),
    )


@pytest.mark.parametrize(
    "content_type",
    ["application/json; charset=utf-8", "application/geo+json"],
)
async def test_stored_json_is_shown_compact(registry, content_type: str) -> None:
    body = b'{"year":1667,"event":"flood"}'
    store = InMemoryDataStore()
    artifact = filed(content_type, body)
    ref = await put(store, artifact)
    storage = BytesStorage({("artifacts", "one.json"): body})

    seen = await views(registry, store, storage).render(outputs={"row": ref})

    assert seen.endswith('{"event":"flood","year":1667}')
    assert f"Artifact id: {ref.artifact_id} (file.json)" in seen


async def test_stored_json_that_is_too_long_is_clipped(registry) -> None:
    body = json.dumps({"note": "x" * (MAX_VIEW_CHARS * 4)}).encode()
    store = InMemoryDataStore()
    artifact = filed("application/json", body)
    ref = await put(store, artifact)
    storage = BytesStorage({("artifacts", "one.json"): body})

    seen = await views(registry, store, storage).render(outputs={"row": ref})

    assert "note" in seen
    assert "more characters" in seen
    assert f"Artifact id: {ref.artifact_id} (file.json)" in seen
    assert len(seen) < 21_000
    assert len(body) > len(seen)


async def test_stored_json_that_cannot_be_read_says_so(registry) -> None:
    store = InMemoryDataStore()
    broken = filed("application/json", b"not json")
    missing = filed("application/json", b"{}", bucket=None)
    broken_ref = await put(store, broken)
    missing_ref = await put(store, missing)
    storage = BytesStorage({("artifacts", "one.json"): b"not json"})

    broken_seen = await views(registry, store, storage).render(
        outputs={"row": broken_ref}
    )
    missing_seen = await views(registry, store, storage).render(
        outputs={"row": missing_ref}
    )

    assert "could not be read" in broken_seen
    assert "nothing stored" in missing_seen
    assert str(broken_ref.artifact_id) in broken_seen


async def test_create_artifact_writes_one_html_page(registry) -> None:
    store = InMemoryDataStore()
    addressed = arguments(registry, store)
    source = await addressed.ref_for(workspace_id=WORKSPACE, key=TEXT, value="risen")
    toolbox = AgentToolbox.build(
        agent=GraphAgent(id="a", name="A"),
        document=GraphDocument(nodes=(make_node("search"),)),
        graph_id="main",
        workspace_id=WORKSPACE,
        node_ports=FakePorts(),
        computation=FakeComputation(),
        artifacts=addressed,
        views=FakeViews(),
    )
    toolbox.allow((source,))
    html = "<p>{{baptisms}}</p>"
    call = create(content=html, sources={"baptisms": str(source.artifact_id)})

    result = await toolbox.execute(call)
    again = await toolbox.execute(call)

    assert result.ok
    page = result.artifacts[0].artifact
    assert isinstance(page, ArtifactRef)
    assert result.artifacts[0].port == "artifact"
    assert (page.artifact_type, page.schema_version) == ("html.page", 1)
    again_page = again.artifacts[0].artifact
    assert isinstance(again_page, ArtifactRef)
    assert again_page.artifact_id == page.artifact_id
    stored = store.artifacts[page.artifact_id]
    assert stored.inline_payload == {
        "html": html,
        "sources": {
            "baptisms": {
                "artifact_id": str(source.artifact_id),
                "artifact_type": "scalar.text",
                "schema_version": 1,
            }
        },
    }
    assert stored.content_type == "application/json"
    assert stored.storage_backend == "inline"
    assert stored.metadata == {"written_by": "agent_tool_call"}
    assert html not in result.model_view
    assert f"Artifact id: {page.artifact_id} (html.page)" in result.model_view
    assert "baptisms (scalar.text)" in result.model_view
    assert (
        sum(1 for item in store.artifacts.values() if item.artifact_type == "html.page")
        == 1
    )


async def test_equal_html_and_sources_are_one_artifact(registry) -> None:
    store = InMemoryDataStore()
    written = arguments(registry, store)
    baptism = await written.ref_for(workspace_id=WORKSPACE, key=TEXT, value="risen")
    census = await written.ref_for(workspace_id=WORKSPACE, key=TEXT, value="heads")
    html = "<p>{{baptisms}} {{census}}</p>"

    first = await written.page_for(
        workspace_id=WORKSPACE,
        html=html,
        sources={"baptisms": baptism, "census": census},
    )
    again = await written.page_for(
        workspace_id=WORKSPACE,
        html=html,
        sources={"census": census, "baptisms": baptism},
    )
    other_html = await written.page_for(
        workspace_id=WORKSPACE,
        html=html + " ",
        sources={"baptisms": baptism, "census": census},
    )
    other_source = await written.page_for(
        workspace_id=WORKSPACE,
        html=html,
        sources={"baptisms": census, "census": baptism},
    )

    assert first == again
    assert first.artifact_id != other_html.artifact_id
    assert first.artifact_id != other_source.artifact_id
    assert (
        sum(1 for item in store.artifacts.values() if item.artifact_type == "html.page")
        == 3
    )
    stored = store.artifacts[first.artifact_id]
    assert stored.inline_payload == {
        "html": html,
        "sources": {
            "baptisms": {
                "artifact_id": str(baptism.artifact_id),
                "artifact_type": "scalar.text",
                "schema_version": 1,
            },
            "census": {
                "artifact_id": str(census.artifact_id),
                "artifact_type": "scalar.text",
                "schema_version": 1,
            },
        },
    }


async def test_a_source_from_another_workspace_is_not_this_ones(registry) -> None:
    store = InMemoryDataStore()
    addressed = arguments(registry, store)
    elsewhere = await addressed.ref_for(
        workspace_id=OTHER_WORKSPACE, key=TEXT, value="nope"
    )
    toolbox = AgentToolbox.build(
        agent=GraphAgent(id="a", name="A"),
        document=GraphDocument(),
        graph_id="main",
        workspace_id=WORKSPACE,
        node_ports=FakePorts(),
        computation=FakeComputation(),
        artifacts=addressed,
        views=FakeViews(),
    )
    toolbox.allow((elsewhere,))

    result = await toolbox.execute(
        create(content="<p>{{x}}</p>", sources={"x": str(elsewhere.artifact_id)})
    )

    assert not result.ok
    assert "does not have" in (result.error or "")
    assert not any(
        item.artifact_type == "html.page" for item in store.artifacts.values()
    )

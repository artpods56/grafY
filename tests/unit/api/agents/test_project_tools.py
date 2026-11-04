"""The toolbox's seams over the real registry and an in-memory artifact store."""

from uuid import UUID

import pytest

from grafy_api.agents.project_tools import (
    ArtifactModelViews,
    ContentAddressedArguments,
    RegistryNodePorts,
)
from grafy_api.services.families import build_application_registry
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
)
from grafy_core.runtime.in_memory import InMemoryDataStore, InMemoryUnitOfWork
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


def views(registry, store: InMemoryDataStore) -> ArtifactModelViews:
    return ArtifactModelViews(
        registry=registry,
        unit_of_work_factory=lambda: InMemoryUnitOfWork(store),
        storage=None,  # type: ignore[arg-type] - inline artifacts never reach storage
        workspace_id=WORKSPACE,
    )


async def test_a_model_is_shown_the_text_of_a_scalar(registry) -> None:
    store = InMemoryDataStore()
    ref = await put(store, inline(TEXT, {"value": "dear sir, the water rose"}))

    seen = await views(registry, store).render(outputs={"text": ref})

    assert seen == "text:\ndear sir, the water rose"


async def test_a_long_value_is_clipped_and_says_so(registry) -> None:
    store = InMemoryDataStore()
    ref = await put(store, inline(TEXT, {"value": "x" * 25_000}))

    seen = await views(registry, store).render(outputs={"text": ref})

    assert "5000 more characters" in seen
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
    assert lines[1] == "Year | Event"
    assert lines[3] == "1600 | flood 0"
    assert lines[-1] == "(showing 20 of 30 rows)"


async def test_a_sequence_shows_its_first_items(registry) -> None:
    store = InMemoryDataStore()
    refs = [await put(store, inline(TEXT, {"value": f"letter {n}"})) for n in range(7)]
    sequence = ArtifactRefSequence(
        artifact_type="scalar.text", schema_version=1, item_refs=refs
    )

    seen = await views(registry, store).render(outputs={"letters": sequence})

    assert "7 items:" in seen
    assert "- letter 0" in seen and "- letter 4" in seen and "letter 5" not in seen
    assert "... and 2 more not shown" in seen


async def test_what_a_model_cannot_read_is_described_not_dumped(registry) -> None:
    store = InMemoryDataStore()
    ref = await put(
        store, inline(ArtifactTypeKey("image.raster", 1), {"pages": [], "blob": "..."})
    )

    seen = await views(registry, store).render(outputs={"image": ref})

    assert "not shown to you" in seen
    assert "blob" not in seen


async def test_a_vanished_artifact_is_named_and_a_tool_with_no_outputs_says_so(
    registry,
) -> None:
    gone = ArtifactRef(
        artifact_id=UUID(int=1), artifact_type="scalar.text", schema_version=1
    )
    store = InMemoryDataStore()

    assert "no longer available" in await views(registry, store).render(
        outputs={"text": gone}
    )
    assert (
        await views(registry, store).render(outputs={}) == "The tool returned nothing."
    )

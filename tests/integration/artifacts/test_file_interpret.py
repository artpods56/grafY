"""The visible file.interpret@1 node claims blob bytes as one chosen format.

Ingest stores bytes it cannot place in the extension table as ``file.blob@1``.
Each test seeds that exact artifact and then runs the visible node: a matching
format claim writes a new artifact, a disagreement fails, and the blob stays a
blob.
"""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from grafy_core.artifact_contracts import RASTER_IMAGE
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactTypeSpec,
    JsonObject,
)
from grafy_core.file_contracts import (
    BLOB_FILE,
    BUILTIN_FILE_FORMATS,
    CSV_FILE,
    JPEG_FILE,
)
from grafy_core.nodes import (
    ArtifactTypeVariable,
    NodeContractResolutionError,
    NodeExecutionContext,
    resolve_node_contracts,
)
from grafy_core.plugins import PluginRegistry
from grafy_core.ports.storage import SaveFileCommand
from grafy_core.runtime.execution import NodeRunError, NodeRuntime
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import (
    ArtifactWriterRegistry,
    OutputPersister,
    PersistedNodeOutput,
)
from grafy_core.runtime.resolvers import ResolverRegistry
from grafy_storage import LocalFileObjectStore
from grafy_workbench.file import FILES
from grafy_workbench.file.nodes import (
    FORMAT_ARTIFACT_TYPE_VARIABLE,
    InterpretFileInput,
    InterpretFileNode,
)
from grafy_workbench.image import IMAGES
from grafy_workbench.table import TABLES

TEST_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000969")
JPEG_BYTES = b"\xff\xd8\xff\xe0jpeg-bytes"
PNG_BYTES = b"\x89PNG\r\n\x1a\npng-bytes"


async def seed_blob_artifact(
    storage: LocalFileObjectStore,
    uow: InMemoryUnitOfWork,
    *,
    content: bytes,
    original_filename: str | None = "scan.unknown",
) -> ArtifactRef:
    """Persist the blob artifact and bytes ingest would have written."""

    stored = await storage.save(
        SaveFileCommand(
            bucket="artifacts",
            path=f"files/{BLOB_FILE.key.id}/{sha256(content).hexdigest()}",
            stream=BytesIO(content),
            content_type="application/octet-stream",
            metadata={"original_filename": original_filename},
            allow_overwrite=True,
        )
    )
    metadata: JsonObject = {}
    if original_filename is not None:
        metadata["original_filename"] = original_filename
    artifact = ArtifactObject(
        workspace_id=TEST_WORKSPACE_ID,
        artifact_type=BLOB_FILE.key.id,
        schema_version=BLOB_FILE.key.schema_version,
        content_type="application/octet-stream",
        bucket=stored.bucket,
        object_key=stored.path,
        byte_size=stored.byte_size,
        sha256=stored.sha256,
        metadata=metadata,
    )
    async with uow as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    return artifact.ref()


def node_context() -> NodeExecutionContext:
    return NodeExecutionContext(
        workspace_id=TEST_WORKSPACE_ID,
        node_id="interpret-file",
    )


def interpret_node(
    storage: LocalFileObjectStore,
    uow: InMemoryUnitOfWork,
) -> InterpretFileNode:
    return InterpretFileNode(
        storage=storage,
        uow=uow,
        bucket="artifacts",
        artifact_types=(*BUILTIN_FILE_FORMATS, RASTER_IMAGE),
    )


async def run_interpret(
    storage: LocalFileObjectStore,
    uow: InMemoryUnitOfWork,
    blob: ArtifactRef,
    artifact_types: tuple[ArtifactTypeSpec, ...] = (JPEG_FILE,),
) -> object:
    runtime = NodeRuntime(
        materializer=InputMaterializer(ResolverRegistry()),
        persister=OutputPersister(ArtifactWriterRegistry()),
    )
    return await runtime.run_node(
        interpret_node(storage, uow),
        node_context(),
        {"file": blob},
        artifact_type_bindings={
            FORMAT_ARTIFACT_TYPE_VARIABLE: spec.key for spec in artifact_types
        },
    )


@pytest.mark.asyncio
async def test_interpret_claims_blob_bytes_as_the_chosen_format(tmp_path: Path) -> None:
    storage = LocalFileObjectStore(tmp_path / "objects")
    uow = InMemoryUnitOfWork()
    blob = await seed_blob_artifact(storage, uow, content=JPEG_BYTES)

    output = await run_interpret(storage, uow, blob)

    assert isinstance(output, PersistedNodeOutput)
    claimed = output["file"]
    assert isinstance(claimed, ArtifactRef)
    assert claimed.key() == JPEG_FILE.key
    async with uow as entered:
        stored = await entered.artifacts.get(TEST_WORKSPACE_ID, claimed.artifact_id)
        blob_row = await entered.artifacts.get(TEST_WORKSPACE_ID, blob.artifact_id)
    assert stored is not None and stored.artifact_type == JPEG_FILE.key.id
    assert stored.metadata["original_filename"] == "scan.unknown"
    assert stored.metadata["confirmed_with"] == "magic"
    interpreted_from = cast(JsonObject, stored.metadata["interpreted_from"])
    assert interpreted_from["artifact_type"] == BLOB_FILE.key.id
    # The blob row keeps its own type and bytes.
    assert blob_row is not None and blob_row.ref() == blob
    reader = await storage.load(
        bucket=blob_row.bucket or "",
        path=blob_row.object_key or "",
    )
    try:
        assert reader.read() == JPEG_BYTES
    finally:
        reader.close()


@pytest.mark.asyncio
async def test_interpret_refuses_bytes_that_disagree_with_the_format(
    tmp_path: Path,
) -> None:
    storage = LocalFileObjectStore(tmp_path / "objects")
    uow = InMemoryUnitOfWork()
    blob = await seed_blob_artifact(storage, uow, content=PNG_BYTES)

    with pytest.raises(NodeRunError, match="file_format_mismatch"):
        _ = await run_interpret(storage, uow, blob, (JPEG_FILE,))


@pytest.mark.asyncio
async def test_interpret_trusts_a_format_whose_rule_cannot_confirm_bytes(
    tmp_path: Path,
) -> None:
    """CSV and TXT declare no magic, so the user's claim is the whole check."""

    storage = LocalFileObjectStore(tmp_path / "objects")
    uow = InMemoryUnitOfWork()
    blob = await seed_blob_artifact(storage, uow, content=PNG_BYTES)

    output = await run_interpret(storage, uow, blob, (CSV_FILE,))

    assert isinstance(output, PersistedNodeOutput)
    claimed = output["file"]
    assert isinstance(claimed, ArtifactRef)
    assert claimed.key() == CSV_FILE.key


@pytest.mark.asyncio
async def test_interpret_refuses_an_illegal_format_before_the_node_runs(
    tmp_path: Path,
) -> None:
    """A blob or a payload type is refused at contract resolution, not later."""

    storage = LocalFileObjectStore(tmp_path / "objects")
    uow = InMemoryUnitOfWork()
    blob = await seed_blob_artifact(storage, uow, content=JPEG_BYTES)

    for spec in (BLOB_FILE, RASTER_IMAGE):
        with pytest.raises(
            NodeContractResolutionError,
            match=f"cannot use {spec.key.id}@{spec.key.schema_version} as its format",
        ):
            _ = await run_interpret(storage, uow, blob, (spec,))


@pytest.mark.asyncio
async def test_interpret_without_a_bound_format_fails_closed(tmp_path: Path) -> None:
    storage = LocalFileObjectStore(tmp_path / "objects")
    uow = InMemoryUnitOfWork()
    blob = await seed_blob_artifact(storage, uow, content=JPEG_BYTES)

    with pytest.raises(ValueError, match="bindings: format"):
        _ = await run_interpret(storage, uow, blob, ())


def test_interpret_resolves_a_claimed_format_and_refuses_the_rest(
    tmp_path: Path,
) -> None:
    node = interpret_node(
        LocalFileObjectStore(tmp_path / "objects"),
        InMemoryUnitOfWork(),
    )

    for key in (BLOB_FILE.key, RASTER_IMAGE.key):
        with pytest.raises(
            NodeContractResolutionError,
            match=f"cannot use {key.id}@{key.schema_version}",
        ):
            _ = resolve_node_contracts(
                node,
                {FORMAT_ARTIFACT_TYPE_VARIABLE: key},
            )

    resolved = resolve_node_contracts(
        node,
        {FORMAT_ARTIFACT_TYPE_VARIABLE: JPEG_FILE.key},
    )
    assert resolved.output_contract.ports["file"].produces == JPEG_FILE.key


def test_interpret_declares_an_explicit_format_output_and_a_blob_input() -> None:
    registry = PluginRegistry()
    registry.install(FILES)
    registry.install(IMAGES)
    registry.install(TABLES)
    registry.freeze()

    registration = registry.node_registration("file.interpret", 1)
    node_class = registration.node_class
    assert registration.title == "Interpret file"
    file_input = node_class.input_contract.ports["file"]
    assert file_input.accepts == BLOB_FILE.key
    assert file_input.also_accepts == ()
    assert file_input.shape.value == "one"
    assert file_input.required is True
    file_output = node_class.output_contract.ports["file"]
    produces = file_output.produces
    assert isinstance(produces, ArtifactTypeVariable)
    assert produces.name == FORMAT_ARTIFACT_TYPE_VARIABLE
    assert file_output.shape.value == "one"

    # A typed node still never takes a blob.
    for operator_id, port_name in (
        ("image.decode", "files"),
        ("table.import", "file"),
    ):
        accepted = registry.node_registration(
            operator_id, 1
        ).node_class.input_contract.ports[port_name].accepted_types
        assert BLOB_FILE.key not in accepted
    assert InterpretFileInput.model_fields["file"].is_required()

from io import BytesIO
from pathlib import Path
from typing import Self, override
from uuid import UUID, uuid4

import pytest

from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRefSequence,
    ArtifactTypeKey,
    InMemoryUnitOfWork,
)
from grafy_core.ports.storage import SaveFileCommand, StoredObjectInfo
from grafy_core.domain.materialized_outputs import MaterializedNodeOutputs
from grafy_storage import LocalFileObjectStore
from grafy_api.artifact_availability import ArtifactAvailability, ArtifactReferenceError
from grafy_api.execution.materializations import MaterializationService
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_api.v1.routes.executions.services import RunResultPresenter


WORKSPACE_ID = UUID(int=42)


class RecordingUnitOfWork(InMemoryUnitOfWork):
    def __init__(self) -> None:
        super().__init__()
        self.entries = 0

    @override
    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.entries += 1
        return self


@pytest.mark.asyncio
async def test_materialization_resolves_sequence_once_and_preserves_repeated_order(
    tmp_path: Path,
) -> None:
    uow = RecordingUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    artifacts = [
        ArtifactObject(
            workspace_id=WORKSPACE_ID,
            artifact_type="scalar.text",
            schema_version=1,
            content_type="application/json",
            inline_payload={"text": str(index)},
        )
        for index in range(10)
    ]
    async with uow:
        for artifact in artifacts:
            await uow.artifacts.add(artifact)
        await uow.commit()
    uow.entries = 0
    refs = [artifact.ref() for artifact in reversed(artifacts)]
    refs.append(refs[0])
    sequence = ArtifactRefSequence.from_key(
        key=ArtifactTypeKey("scalar.text", 1), item_refs=refs
    )
    service = MaterializationService(uow, ArtifactAvailability(uow, storage), None)

    pins = {("source", f"port-{index}"): sequence for index in range(10)}
    pins[("source", "text")] = sequence
    outputs = await service.resolve_pinned_outputs(WORKSPACE_ID, pins)

    assert outputs == {"source": {port: sequence for _, port in pins}}
    assert outputs["source"]["text"] is sequence
    assert uow.entries == 1
    batch = await ArtifactAvailability(uow, storage).load(WORKSPACE_ID, refs)
    resolved = batch.resolve_refs(refs, context="Spatial references")
    assert [artifact.ref() for artifact in resolved] == refs
    assert uow.entries == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["missing", "foreign", "mismatch"])
async def test_exact_reference_failures_preserve_sequence_context(
    tmp_path: Path,
    invalid: str,
) -> None:
    uow = InMemoryUnitOfWork()
    artifact = ArtifactObject(
        workspace_id=uuid4() if invalid == "foreign" else WORKSPACE_ID,
        artifact_type="scalar.text",
        schema_version=1,
        content_type="application/json",
        inline_payload={"text": "hello"},
        sha256="a" * 64,
    )
    if invalid != "missing":
        async with uow:
            await uow.artifacts.add(artifact)
            await uow.commit()
    ref = artifact.ref()
    if invalid == "mismatch":
        ref = ref.model_copy(update={"content_hash": "b" * 64})
    sequence = ArtifactRefSequence.from_key(
        key=ArtifactTypeKey("scalar.text", 1), item_refs=[ref]
    )
    availability = ArtifactAvailability(uow, LocalFileObjectStore(tmp_path / "objects"))
    batch = await availability.load(WORKSPACE_ID, [sequence])
    reason = "does not match" if invalid == "mismatch" else "references missing"
    with pytest.raises(
        ArtifactReferenceError, match=f"Pinned output sequence item 0 {reason}"
    ) as error:
        batch.resolve_refs(sequence, context="Pinned output")
    assert error.value.reference == ref
    assert error.value.sequence_index == 0
    assert error.value.reason == ("mismatch" if invalid == "mismatch" else "missing")
    with pytest.raises(
        ArtifactReferenceError, match=f"Spatial layer {reason}"
    ) as spatial_error:
        batch.resolve_refs([ref], context="Spatial layer")
    assert spatial_error.value.sequence_index is None
    assert not await batch.is_accessible(sequence)


@pytest.mark.asyncio
async def test_availability_checks_presence_without_claiming_content_integrity(
    tmp_path: Path,
) -> None:
    uow = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    await storage.save(
        SaveFileCommand(
            bucket="artifacts",
            path="payload.bin",
            stream=BytesIO(b"different bytes"),
            content_type="application/octet-stream",
            metadata={},
        )
    )
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="test.binary",
        schema_version=1,
        content_type="application/octet-stream",
        bucket="artifacts",
        object_key="payload.bin",
        sha256="a" * 64,
    )
    async with uow:
        await uow.artifacts.add(artifact)
        await uow.commit()
    availability = ArtifactAvailability(uow, storage)
    batch = await availability.load(WORKSPACE_ID, [artifact.ref()])
    assert await batch.is_accessible(artifact.ref())
    await storage.delete("artifacts", "payload.bin")
    batch = await availability.load(WORKSPACE_ID, [artifact.ref()])
    assert not await batch.is_accessible(artifact.ref())


class CountingStorage(LocalFileObjectStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.stat_calls = 0

    @override
    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        self.stat_calls += 1
        return await super().stat(bucket, path)


@pytest.mark.asyncio
async def test_materialization_presentation_shares_rows_and_rechecks_next_operation(
    tmp_path: Path,
) -> None:
    uow = RecordingUnitOfWork()
    storage = CountingStorage(tmp_path / "objects")
    await storage.save(
        SaveFileCommand(
            bucket="artifacts",
            path="data.bin",
            stream=BytesIO(b"data"),
            content_type="application/octet-stream",
            metadata={},
        )
    )
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="test.binary",
        schema_version=1,
        content_type="application/octet-stream",
        bucket="artifacts",
        object_key="data.bin",
    )
    async with uow:
        await uow.artifacts.add(artifact)
        await uow.commit()
    graph_id = uuid4()
    outputs = [
        MaterializedNodeOutputs(
            workspace_id=WORKSPACE_ID,
            graph_id=graph_id,
            graph_revision=1,
            node_id=f"node-{index}",
            workflow_run_id=uuid4(),
            outputs={"first": artifact.ref(), "second": artifact.ref()},
        )
        for index in range(3)
    ]
    availability = ArtifactAvailability(uow, storage)
    reader = ArtifactService(uow, storage, availability=availability)
    presenter = RunResultPresenter(reader, availability)
    uow.entries = 0
    storage.stat_calls = 0
    try:
        response = await presenter.materializations_response(
            WORKSPACE_ID, graph_id, 1, outputs
        )
        assert len(response.node_runs) == 3
        assert all(len(node.outputs) == 2 for node in response.node_runs)
        assert all(
            port.artifacts[0].artifact_id == artifact.id
            for node in response.node_runs
            for port in node.outputs
        )
        assert uow.entries == 1
        assert storage.stat_calls == 1
        await storage.delete("artifacts", "data.bin")
        response = await presenter.materializations_response(
            WORKSPACE_ID, graph_id, 1, outputs
        )
        assert response.node_runs == []
        assert uow.entries == 2
        assert storage.stat_calls == 2
    finally:
        await reader.close()

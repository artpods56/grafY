from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.services.errors import WorkbenchOperationError
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_api.v1.routes.library.services import LibraryService
from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.artifacts import ArtifactObject
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.execution_history import (
    GraphExecution,
    GraphExecutionNodeResult,
)
from grafy_core.runtime.in_memory import InMemoryDataStore, InMemoryUnitOfWork
from grafy_storage import LocalFileObjectStore

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")
NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


@dataclass
class FakeGraph:
    name: str


class FakeSavedGraphs:
    """A saved graph service whose titles can be changed or deleted at will."""

    def __init__(self) -> None:
        self.names: dict[UUID, str] = {}

    def set_title(self, graph_id: UUID, name: str) -> None:
        self.names[graph_id] = name

    def delete(self, graph_id: UUID) -> None:
        self.names.pop(graph_id, None)

    async def get(self, workspace_id: UUID, graph_id: UUID) -> FakeGraph:
        del workspace_id
        name = self.names.get(graph_id)
        if name is None:
            raise NotFoundError("Saved graph", str(graph_id))
        return FakeGraph(name)


@dataclass(frozen=True)
class Seeded:
    artifact_id: UUID
    graph_id: UUID
    execution_id: UUID
    node_id: str


def _service(
    store: InMemoryDataStore,
    saved_graphs: FakeSavedGraphs,
    tmp_path: Path,
) -> tuple[LibraryService, ArtifactService]:
    unit_of_work = InMemoryUnitOfWork(store)
    storage = LocalFileObjectStore(tmp_path / "objects")
    availability = ArtifactAvailability(unit_of_work, storage)
    artifacts = ArtifactService(
        unit_of_work,
        storage,
        {},
        availability=availability,
    )
    service = LibraryService(
        unit_of_work,
        artifacts,
        {},
        saved_graphs=cast(SavedGraphService, saved_graphs),
    )
    return service, artifacts


async def _seed_run(
    store: InMemoryDataStore,
    *,
    graph_title: str = "Sales",
    node_id: str = "resize-1",
    revision: int = 4,
) -> Seeded:
    artifact_id = uuid4()
    graph_id = uuid4()
    execution_id = uuid4()
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="text.plain",
        schema_version=1,
        content_type="application/json",
        id=artifact_id,
        inline_payload={"text": "hello"},
        metadata={"download_name": "report.json"},
    )
    execution = GraphExecution(
        workspace_id=WORKSPACE_ID,
        execution_id=execution_id,
        graph_id=graph_id,
        graph_revision=revision,
        status="succeeded",
        requested_node_ids=(node_id,),
        created_at=NOW,
        started_at=NOW,
        finished_at=NOW,
    )
    result = GraphExecutionNodeResult(
        workspace_id=WORKSPACE_ID,
        execution_id=execution_id,
        node_id=node_id,
        position=0,
        status="succeeded",
        outputs={"result": artifact.ref()},
        completed_at=NOW,
    )
    unit_of_work = InMemoryUnitOfWork(store)
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    async with unit_of_work as entered:
        await entered.execution_history.add(execution)
        await entered.execution_history.add_node_result(result)
        await entered.commit()
    return Seeded(
        artifact_id=artifact_id,
        graph_id=graph_id,
        execution_id=execution_id,
        node_id=node_id,
    )


async def _seed_uploaded(store: InMemoryDataStore) -> UUID:
    artifact_id = uuid4()
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="file.csv",
        schema_version=1,
        content_type="text/csv",
        id=artifact_id,
        metadata={"download_name": "measurements.csv"},
    )
    unit_of_work = InMemoryUnitOfWork(store)
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    return artifact_id


async def _save_run(
    service: LibraryService,
    seeded: Seeded,
    *,
    node_title: str = "Resize",
) -> None:
    _ = await service.save_from_run(
        workspace_id=WORKSPACE_ID,
        artifact_id=seeded.artifact_id,
        execution_id=seeded.execution_id,
        node_id=seeded.node_id,
        node_title=node_title,
    )


@pytest.mark.asyncio
async def test_saving_a_run_artifact_writes_the_four_producing_facts(
    tmp_path: Path,
) -> None:
    store = InMemoryDataStore()
    seeded = await _seed_run(store)
    saved_graphs = FakeSavedGraphs()
    saved_graphs.set_title(seeded.graph_id, "Sales")
    service, artifacts = _service(store, saved_graphs, tmp_path)
    try:
        await _save_run(service, seeded)
        items = await service.list_items(WORKSPACE_ID)
    finally:
        await artifacts.close()

    assert len(items) == 1
    item = items[0]
    assert item.artifact.artifact_id == seeded.artifact_id
    assert item.provenance.source == "run"
    assert item.provenance.graph_id == seeded.graph_id
    assert item.provenance.graph_title == "Sales"
    assert item.provenance.node_id == seeded.node_id
    assert item.provenance.node_title == "Resize"
    assert item.provenance.graph_revision == 4
    assert item.provenance.execution_id == seeded.execution_id
    assert item.provenance.original_filename is None
    # The detail record carries the run id, its finish time, and the run link.
    assert item.run is not None
    assert item.run.execution_id == seeded.execution_id
    assert item.run.graph_id == seeded.graph_id
    assert item.run.finished_at == NOW


@pytest.mark.asyncio
async def test_renaming_or_deleting_the_producing_graph_leaves_the_line(
    tmp_path: Path,
) -> None:
    store = InMemoryDataStore()
    seeded = await _seed_run(store)
    saved_graphs = FakeSavedGraphs()
    saved_graphs.set_title(seeded.graph_id, "Sales")
    service, artifacts = _service(store, saved_graphs, tmp_path)
    try:
        await _save_run(service, seeded)

        saved_graphs.set_title(seeded.graph_id, "Renamed after the save")
        renamed = (await service.list_items(WORKSPACE_ID))[0]
        assert renamed.provenance.graph_title == "Sales"

        saved_graphs.delete(seeded.graph_id)
        deleted = (await service.list_items(WORKSPACE_ID))[0]
        assert deleted.provenance.graph_title == "Sales"
        assert deleted.provenance.node_title == "Resize"
        assert deleted.provenance.graph_revision == 4
    finally:
        await artifacts.close()


@pytest.mark.asyncio
async def test_saving_again_never_rewrites_the_birth_record(tmp_path: Path) -> None:
    store = InMemoryDataStore()
    seeded = await _seed_run(store)
    saved_graphs = FakeSavedGraphs()
    saved_graphs.set_title(seeded.graph_id, "Sales")
    service, artifacts = _service(store, saved_graphs, tmp_path)
    try:
        await _save_run(service, seeded)
        saved_graphs.set_title(seeded.graph_id, "Renamed")

        _ = await service.save_from_run(
            workspace_id=WORKSPACE_ID,
            artifact_id=seeded.artifact_id,
            execution_id=seeded.execution_id,
            node_id=seeded.node_id,
            node_title="A different title",
        )
        item = (await service.list_items(WORKSPACE_ID))[0]
    finally:
        await artifacts.close()

    assert item.provenance.graph_title == "Sales"
    assert item.provenance.node_title == "Resize"


@pytest.mark.asyncio
async def test_run_link_is_absent_once_the_run_is_gone(tmp_path: Path) -> None:
    store = InMemoryDataStore()
    seeded = await _seed_run(store)
    saved_graphs = FakeSavedGraphs()
    saved_graphs.set_title(seeded.graph_id, "Sales")
    service, artifacts = _service(store, saved_graphs, tmp_path)
    try:
        await _save_run(service, seeded)
        assert (await service.list_items(WORKSPACE_ID))[0].run is not None

        store.graph_executions.pop(seeded.execution_id)
        item = (await service.list_items(WORKSPACE_ID))[0]
    finally:
        await artifacts.close()

    assert item.run is None
    # The recorded run identity stays; only the live run link goes away.
    assert item.provenance.execution_id == seeded.execution_id


@pytest.mark.asyncio
async def test_an_uploaded_artifact_shows_the_filename_and_no_run_link(
    tmp_path: Path,
) -> None:
    store = InMemoryDataStore()
    artifact_id = await _seed_uploaded(store)
    service, artifacts = _service(store, FakeSavedGraphs(), tmp_path)
    try:
        saved = await service.save_uploaded(
            workspace_id=WORKSPACE_ID,
            artifact_id=artifact_id,
            original_filename="measurements.csv",
        )
        item = (await service.list_items(WORKSPACE_ID))[0]
    finally:
        await artifacts.close()

    assert saved.provenance.source == "upload"
    assert item.provenance.source == "upload"
    assert item.provenance.original_filename == "measurements.csv"
    assert item.provenance.graph_title is None
    assert item.provenance.node_title is None
    assert item.provenance.graph_revision is None
    assert item.provenance.execution_id is None
    assert item.run is None


@pytest.mark.asyncio
async def test_a_run_artifact_must_belong_to_the_named_node_and_run(
    tmp_path: Path,
) -> None:
    store = InMemoryDataStore()
    seeded = await _seed_run(store)
    saved_graphs = FakeSavedGraphs()
    saved_graphs.set_title(seeded.graph_id, "Sales")
    service, artifacts = _service(store, saved_graphs, tmp_path)
    try:
        with pytest.raises(WorkbenchOperationError):
            _ = await service.save_from_run(
                workspace_id=WORKSPACE_ID,
                artifact_id=seeded.artifact_id,
                execution_id=seeded.execution_id,
                node_id="some-other-node",
                node_title="Other",
            )
        with pytest.raises(NotFoundError):
            _ = await service.save_from_run(
                workspace_id=WORKSPACE_ID,
                artifact_id=seeded.artifact_id,
                execution_id=uuid4(),
                node_id=seeded.node_id,
                node_title="Resize",
            )
    finally:
        await artifacts.close()


@pytest.mark.asyncio
async def test_only_library_artifacts_are_listed(tmp_path: Path) -> None:
    store = InMemoryDataStore()
    seeded = await _seed_run(store)
    _ = await _seed_uploaded(store)
    saved_graphs = FakeSavedGraphs()
    saved_graphs.set_title(seeded.graph_id, "Sales")
    service, artifacts = _service(store, saved_graphs, tmp_path)
    try:
        assert await service.list_items(WORKSPACE_ID) == []
        await _save_run(service, seeded)
        items = await service.list_items(WORKSPACE_ID)
    finally:
        await artifacts.close()

    assert [item.artifact.artifact_id for item in items] == [seeded.artifact_id]

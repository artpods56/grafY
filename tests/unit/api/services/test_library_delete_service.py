"""What a Library artifact delete does to rows, bytes, and the references to it.

The HTTP tests cover the contract. These cover what the endpoint must get right
underneath it: the stored bytes go with the row, bytes another artifact shares
stay behind, and saved work that still names the artifact stops the delete
instead of leaving a dangling reference.

Two ways an artifact enters the Library, and the delete treats them differently.
An uploaded artifact is referenced by nothing but its own filing, so it deletes.
An artifact saved from a run is referenced by that run's recorded output, so it
refuses until the graph goes with it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_api.v1.routes.library.services import LibraryService
from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.artifacts import ArtifactObject, LibraryProvenance
from grafy_core.domain.errors import LibraryArtifactInUseError, NotFoundError
from grafy_core.domain.execution_history import (
    GraphExecution,
    GraphExecutionNodeResult,
)
from grafy_core.domain.library import LibraryFolder
from grafy_core.ports.storage import SaveFileCommand
from grafy_core.runtime.in_memory import InMemoryDataStore, InMemoryUnitOfWork
from grafy_storage import LocalFileObjectStore

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")
NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
BUCKET = "artifacts"
REPORT_BYTES = b"quarter,revenue\nQ1,120\n"


@dataclass
class FakeGraph:
    name: str


class FakeSavedGraphs:
    """Saved graphs whose held references can be stated outright."""

    def __init__(self) -> None:
        self.names: dict[UUID, str] = {}
        self._revisions: dict[UUID, set[UUID]] = {}

    def set_title(self, graph_id: UUID, name: str) -> None:
        self.names[graph_id] = name

    def hold_in_revision(self, graph_id: UUID, artifact_id: UUID) -> None:
        """Say a saved revision of ``graph_id`` names ``artifact_id``."""

        self._revisions.setdefault(artifact_id, set()).add(graph_id)

    async def titles_referencing_artifact(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> dict[UUID, str]:
        del workspace_id
        return {
            graph_id: self.names[graph_id]
            for graph_id in self._revisions.get(artifact_id, ())
            if graph_id in self.names
        }

    async def get(self, workspace_id: UUID, graph_id: UUID) -> FakeGraph:
        del workspace_id
        name = self.names.get(graph_id)
        if name is None:
            raise NotFoundError("Saved graph", str(graph_id))
        return FakeGraph(name)


@dataclass(frozen=True)
class Filed:
    """An artifact in the Library, with the object its row points at."""

    artifact_id: UUID
    object_key: str


@dataclass(frozen=True)
class RunFiled(Filed):
    graph_id: UUID


def _service(
    store: InMemoryDataStore,
    saved_graphs: FakeSavedGraphs,
    storage: LocalFileObjectStore,
) -> LibraryService:
    unit_of_work = InMemoryUnitOfWork(store)
    availability = ArtifactAvailability(unit_of_work, storage)
    artifacts = ArtifactService(
        unit_of_work,
        storage,
        {},
        availability=availability,
    )
    return LibraryService(
        unit_of_work,
        artifacts,
        {},
        saved_graphs=cast(SavedGraphService, saved_graphs),
        storage=storage,
    )


async def _store_report(
    storage: LocalFileObjectStore,
    object_key: str,
) -> tuple[int, str]:
    """Write the artifact's bytes for real, so a delete has something to release."""

    stored = await storage.save(
        SaveFileCommand(
            bucket=BUCKET,
            path=object_key,
            stream=BytesIO(REPORT_BYTES),
            content_type="text/csv",
            metadata={},
        )
    )
    return stored.byte_size, stored.sha256


async def _file_upload(
    store: InMemoryDataStore,
    storage: LocalFileObjectStore,
    *,
    artifact_id: UUID | None = None,
    object_key: str | None = None,
) -> Filed:
    """Put one stored artifact in the Library the way an upload does.

    Nothing but its own filing refers to it, which is what makes it deletable.
    """

    artifact_id = artifact_id or uuid4()
    object_key = object_key or f"artifacts/{artifact_id}.csv"
    byte_size, digest = await _store_report(storage, object_key)
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="file.csv",
        schema_version=1,
        content_type="text/csv",
        id=artifact_id,
        bucket=BUCKET,
        object_key=object_key,
        byte_size=byte_size,
        sha256=digest,
        metadata={"download_name": "report.csv"},
        library_provenance=LibraryProvenance(
            source="upload",
            saved_at=NOW,
            original_filename="report.csv",
        ),
    )
    async with InMemoryUnitOfWork(store) as unit_of_work:
        await unit_of_work.artifacts.add(artifact)
        await unit_of_work.commit()
    return Filed(artifact_id=artifact_id, object_key=object_key)


async def _file_run(
    store: InMemoryDataStore,
    storage: LocalFileObjectStore,
) -> RunFiled:
    """Put a run's output artifact in the Library and keep the recorded run.

    The recorded node output is the reference a saved revision does not have to
    carry, and it is enough on its own to refuse the delete.
    """

    graph_id = uuid4()
    execution_id = uuid4()
    node_id = "resize-1"
    filed = await _file_upload(store, storage)
    async with InMemoryUnitOfWork(store) as unit_of_work:
        await unit_of_work.execution_history.add(
            GraphExecution(
                workspace_id=WORKSPACE_ID,
                execution_id=execution_id,
                graph_id=graph_id,
                graph_revision=4,
                status="succeeded",
                requested_node_ids=(node_id,),
                created_at=NOW,
                started_at=NOW,
                finished_at=NOW,
            )
        )
        await unit_of_work.commit()
    async with InMemoryUnitOfWork(store) as unit_of_work:
        artifact = await unit_of_work.artifacts.get(WORKSPACE_ID, filed.artifact_id)
        assert artifact is not None
        await unit_of_work.execution_history.add_node_result(
            GraphExecutionNodeResult(
                workspace_id=WORKSPACE_ID,
                execution_id=execution_id,
                node_id=node_id,
                position=0,
                status="succeeded",
                outputs={"result": artifact.ref()},
                completed_at=NOW,
            )
        )
        await unit_of_work.commit()
    return RunFiled(
        artifact_id=filed.artifact_id,
        object_key=filed.object_key,
        graph_id=graph_id,
    )


async def _placements(store: InMemoryDataStore) -> dict[UUID, UUID]:
    async with InMemoryUnitOfWork(store) as unit_of_work:
        return await unit_of_work.library_folders.placements(WORKSPACE_ID)


@pytest.mark.asyncio
async def test_deleting_a_library_artifact_removes_its_row_and_its_bytes(
    tmp_path: Path,
) -> None:
    store = InMemoryDataStore()
    storage = LocalFileObjectStore(tmp_path / "objects")
    filed = await _file_upload(store, storage)
    folder_id = uuid4()
    async with InMemoryUnitOfWork(store) as unit_of_work:
        await unit_of_work.library_folders.add(
            LibraryFolder(workspace_id=WORKSPACE_ID, name="Reports", id=folder_id)
        )
        await unit_of_work.library_folders.place(
            workspace_id=WORKSPACE_ID,
            artifact_ids=[filed.artifact_id],
            folder_id=folder_id,
        )
        await unit_of_work.commit()
    service = _service(store, FakeSavedGraphs(), storage)

    await service.delete_artifact(
        workspace_id=WORKSPACE_ID,
        artifact_id=filed.artifact_id,
    )

    assert await service.list_items(WORKSPACE_ID) == []
    assert await storage.stat(BUCKET, filed.object_key) is None
    # The filing goes with the row, so nothing is left pointing at a folder.
    assert filed.artifact_id not in await _placements(store)
    async with InMemoryUnitOfWork(store) as unit_of_work:
        remaining = await unit_of_work.artifacts.get(WORKSPACE_ID, filed.artifact_id)
    assert remaining is None


@pytest.mark.asyncio
async def test_deleting_a_library_artifact_keeps_bytes_another_artifact_shares(
    tmp_path: Path,
) -> None:
    """Stored content is addressed by digest, so a second row can own the object."""

    store = InMemoryDataStore()
    storage = LocalFileObjectStore(tmp_path / "objects")
    filed = await _file_upload(store, storage)
    twin_id = uuid4()
    async with InMemoryUnitOfWork(store) as unit_of_work:
        await unit_of_work.artifacts.add(
            ArtifactObject(
                workspace_id=WORKSPACE_ID,
                artifact_type="file.csv",
                schema_version=1,
                content_type="text/csv",
                id=twin_id,
                bucket=BUCKET,
                object_key=filed.object_key,
                byte_size=len(REPORT_BYTES),
                sha256=sha256(REPORT_BYTES).hexdigest(),
                metadata={"download_name": "report-copy.csv"},
            )
        )
        await unit_of_work.commit()
    service = _service(store, FakeSavedGraphs(), storage)

    await service.delete_artifact(
        workspace_id=WORKSPACE_ID,
        artifact_id=filed.artifact_id,
    )

    assert await storage.stat(BUCKET, filed.object_key) is not None


@pytest.mark.asyncio
async def test_deleting_an_artifact_only_a_saved_revision_names_is_refused(
    tmp_path: Path,
) -> None:
    """A graph that holds the artifact in a revision refuses the delete by name."""

    store = InMemoryDataStore()
    storage = LocalFileObjectStore(tmp_path / "objects")
    filed = await _file_upload(store, storage)
    holder_id = uuid4()
    saved_graphs = FakeSavedGraphs()
    saved_graphs.set_title(holder_id, "Field study")
    saved_graphs.hold_in_revision(holder_id, filed.artifact_id)
    service = _service(store, saved_graphs, storage)

    with pytest.raises(LibraryArtifactInUseError) as refused:
        await service.delete_artifact(
            workspace_id=WORKSPACE_ID,
            artifact_id=filed.artifact_id,
        )

    assert refused.value.graph_ids == (holder_id,)
    assert refused.value.graph_titles == ("Field study",)
    assert "Field study" in refused.value.public_message
    assert await storage.stat(BUCKET, filed.object_key) is not None
    assert len(await service.list_items(WORKSPACE_ID)) == 1


@pytest.mark.asyncio
async def test_deleting_an_artifact_a_recorded_run_produced_is_refused(
    tmp_path: Path,
) -> None:
    """The run that made the artifact holds it even when no revision names it."""

    store = InMemoryDataStore()
    storage = LocalFileObjectStore(tmp_path / "objects")
    run = await _file_run(store, storage)
    saved_graphs = FakeSavedGraphs()
    saved_graphs.set_title(run.graph_id, "Sales")
    service = _service(store, saved_graphs, storage)

    with pytest.raises(LibraryArtifactInUseError) as refused:
        await service.delete_artifact(
            workspace_id=WORKSPACE_ID,
            artifact_id=run.artifact_id,
        )

    assert refused.value.graph_ids == (run.graph_id,)
    assert refused.value.graph_titles == ("Sales",)
    assert await storage.stat(BUCKET, run.object_key) is not None
    assert len(await service.list_items(WORKSPACE_ID)) == 1


@pytest.mark.asyncio
async def test_every_graph_holding_the_artifact_is_named_in_one_refusal(
    tmp_path: Path,
) -> None:
    """References from both places merge, and the listing is sorted by name."""

    store = InMemoryDataStore()
    storage = LocalFileObjectStore(tmp_path / "objects")
    run = await _file_run(store, storage)
    revision_holder = uuid4()
    saved_graphs = FakeSavedGraphs()
    saved_graphs.set_title(run.graph_id, "Sales")
    saved_graphs.set_title(revision_holder, "Field study")
    saved_graphs.hold_in_revision(revision_holder, run.artifact_id)
    service = _service(store, saved_graphs, storage)

    with pytest.raises(LibraryArtifactInUseError) as refused:
        await service.delete_artifact(
            workspace_id=WORKSPACE_ID,
            artifact_id=run.artifact_id,
        )

    assert refused.value.graph_ids == (revision_holder, run.graph_id)
    assert refused.value.graph_titles == ("Field study", "Sales")

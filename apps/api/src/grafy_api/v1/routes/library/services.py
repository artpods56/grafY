from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRefSequence,
    ArtifactTypeSpec,
    LibraryProvenance,
)
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.errors import (
    LibraryArtifactInUseError,
    NotFoundError,
)
from grafy_core.ports.materialized_outputs import WorkbenchUnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort

from grafy_api.services.errors import WorkbenchOperationError
from grafy_api.v1.routes.artifacts.services import ArtifactService

from .items import LibraryItem, LibraryRun
from .models import LibraryItemResponse


def _output_artifact_ids(outputs: Mapping[str, ArtifactOutputValue]) -> set[UUID]:
    artifact_ids: set[UUID] = set()
    for output in outputs.values():
        if isinstance(output, ArtifactRefSequence):
            artifact_ids.update(ref.artifact_id for ref in output.item_refs)
        else:
            artifact_ids.add(output.artifact_id)
    return artifact_ids


class LibraryService:
    """Save artifacts into a Workspace Library and read the Library back.

    A Library artifact is an ordinary artifact row carrying a provenance
    snapshot. Saving records how the artifact came to be and nothing else: it
    moves no bytes and creates no second record.
    """

    def __init__(
        self,
        unit_of_work: WorkbenchUnitOfWorkPort,
        artifacts: ArtifactService,
        artifact_types: Mapping[tuple[str, int], ArtifactTypeSpec],
        saved_graphs: SavedGraphService | None = None,
        storage: FileStoragePort | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._artifacts = artifacts
        self._artifact_types = artifact_types
        self._saved_graphs = saved_graphs
        self._storage = storage

    def _artifact_name(self, artifact: ArtifactObject) -> str:
        for key in ("download_name", "source_name"):
            value = artifact.metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        spec = self._artifact_types.get(
            (artifact.artifact_type, artifact.schema_version)
        )
        if spec is not None:
            return spec.title
        return f"{artifact.artifact_type}@{artifact.schema_version}"

    # [TODO] performance is shit here because of the run lookups, think how we can track whats the provenance of an artifact easier
    async def list_items(self, workspace_id: UUID) -> list[LibraryItemResponse]:
        items: list[LibraryItem] = []
        async with self._unit_of_work as unit_of_work:
            artifacts = await unit_of_work.artifacts.list_library(workspace_id)
            placements = await unit_of_work.library_folders.placements(workspace_id)
            for artifact in artifacts:
                provenance = artifact.library_provenance
                if provenance is None:
                    continue
                items.append(
                    LibraryItem(
                        artifact=artifact,
                        provenance=provenance,
                        run=await self._retained_run(
                            unit_of_work, artifact, provenance
                        ),
                    )
                )
        items.sort(
            key=lambda item: (item.provenance.saved_at, str(item.artifact.id)),
            reverse=True,
        )
        return [
            self._present(item, folder_id=placements.get(item.artifact.id))
            for item in items
        ]

    # [TODO] do we really need this?
    @staticmethod
    async def _retained_run(
        unit_of_work: WorkbenchUnitOfWorkPort,
        artifact: ArtifactObject,
        provenance: LibraryProvenance,
    ) -> LibraryRun | None:
        if provenance.source != "run" or provenance.execution_id is None:
            return None
        detail = await unit_of_work.execution_history.get(
            artifact.workspace_id,
            provenance.execution_id,
        )
        if detail is None:
            return None
        return LibraryRun(
            execution_id=detail.execution.execution_id,
            graph_id=detail.execution.graph_id,
            finished_at=detail.execution.finished_at,
        )

    async def save_from_run(
        self,
        *,
        workspace_id: UUID,
        artifact_id: UUID,
        execution_id: UUID,
        node_id: str,
        node_title: str,
        name: str,
    ) -> LibraryItemResponse:
        async with self._unit_of_work as unit_of_work:
            detail = await unit_of_work.execution_history.get(
                workspace_id,
                execution_id,
            )
        if detail is None:
            raise NotFoundError("Graph execution", str(execution_id))

        node_result = next(
            (result for result in detail.node_results if result.node_id == node_id),
            None,
        )
        if node_result is None:
            raise WorkbenchOperationError(
                f"Execution {execution_id} has no node result {node_id!r}"
            )
        if artifact_id not in _output_artifact_ids(node_result.outputs):
            raise WorkbenchOperationError(
                f"Artifact {artifact_id} is not an output of node {node_id!r} "
                f"in execution {execution_id}"
            )
        if self._saved_graphs is None:
            raise RuntimeError(
                "Saved graph context is not configured for Library provenance"
            )
        graph = await self._saved_graphs.get(workspace_id, detail.execution.graph_id)
        graph_title = graph.name

        provenance = LibraryProvenance.from_run(
            saved_at=datetime.now(UTC),
            graph_id=detail.execution.graph_id,
            graph_title=graph_title,
            node_id=node_id,
            node_title=node_title,
            graph_revision=detail.execution.graph_revision,
            execution_id=execution_id,
            name=name,
        )
        return await self._record(
            workspace_id,
            artifact_id,
            provenance,
            LibraryRun(
                execution_id=execution_id,
                graph_id=detail.execution.graph_id,
                finished_at=detail.execution.finished_at,
            ),
        )

    async def save_uploaded(
        self,
        *,
        workspace_id: UUID,
        artifact_id: UUID,
        original_filename: str,
    ) -> LibraryItemResponse:
        provenance = LibraryProvenance.from_upload(
            saved_at=datetime.now(UTC),
            original_filename=original_filename,
        )
        return await self._record(workspace_id, artifact_id, provenance, None)

    # [TODO] theres something wrong with the check being made in this uow, theres a race condition on two concurent saves
    async def _record(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
        provenance: LibraryProvenance,
        run: LibraryRun | None,
    ) -> LibraryItemResponse:
        async with self._unit_of_work as unit_of_work:
            artifact = await unit_of_work.artifacts.get(workspace_id, artifact_id)
            if artifact is None:
                raise NotFoundError("Artifact", str(artifact_id))
            if artifact.library_provenance is not None:
                # Provenance is a birth record; re-saving never rewrites it, and
                # the folder it already sits in is not moved either.
                placements = await unit_of_work.library_folders.placements(
                    workspace_id,
                )
                return self._present(
                    LibraryItem(
                        artifact=artifact,
                        provenance=artifact.library_provenance,
                        run=await self._retained_run(
                            unit_of_work,
                            artifact,
                            artifact.library_provenance,
                        ),
                    ),
                    folder_id=placements.get(artifact_id),
                )
            artifact.library_provenance = provenance
            await unit_of_work.commit()
        return self._present(
            LibraryItem(artifact=artifact, provenance=provenance, run=run)
        )

    async def delete_artifact(
        self,
        *,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> None:
        """Delete one Library artifact: its filing, its row, then its stored bytes.

        Saved work keeps the artifact alive. A saved graph revision that names it,
        or a recorded run that produced it, outlives the moment it was made, so the
        delete is refused with ``LibraryArtifactInUseError`` while either exists and
        names the graphs that hold it.

        The filing and the row go together in one transaction. The bytes follow
        after that transaction commits, because storage sits outside the database
        and an object cannot be un-deleted: a failed delete leaves content nobody
        reaches rather than a row pointing at bytes that are gone.

        A graph saved between the reference check and the delete is not caught here.
        The two live in different stores and the workbench transaction does not span
        saved graphs, so the check is the last one made before the rows go, not a
        lock held across both.
        """

        if self._saved_graphs is None:
            raise RuntimeError(
                "Saved graph context is not configured for Library deletion"
            )
        saved_graphs = self._saved_graphs
        async with self._unit_of_work as unit_of_work:
            artifact = await unit_of_work.artifacts.get(workspace_id, artifact_id)
            if artifact is None or artifact.library_provenance is None:
                raise NotFoundError("Library artifact", str(artifact_id))
            run_graph_ids = (
                await unit_of_work.execution_history.graph_ids_with_artifact_output(
                    workspace_id,
                    artifact_id,
                )
            )
        referencing = await self._referencing_graphs(
            saved_graphs,
            workspace_id,
            artifact_id,
            run_graph_ids,
        )
        if referencing:
            raise LibraryArtifactInUseError(
                artifact_id=artifact_id,
                graph_ids=[graph_id for graph_id, _ in referencing],
                graph_titles=[title for _, title in referencing],
            )

        async with self._unit_of_work as unit_of_work:
            stored = await unit_of_work.artifacts.get(workspace_id, artifact_id)
            if stored is None or stored.library_provenance is None:
                raise NotFoundError("Library artifact", str(artifact_id))
            # Content is addressed by digest, so an identical artifact saved twice
            # is two rows over one object. The object stays while another row still
            # names it, and only content nothing else uses is released.
            shared = await unit_of_work.artifacts.count_artifacts_sharing_object(
                workspace_id,
                bucket=stored.bucket or "",
                object_key=stored.object_key or "",
                except_artifact_id=artifact_id,
            )
            # SQL drops the placement with the artifact through the foreign key;
            # unfileing here is what makes an in-memory store do the same.
            await unit_of_work.library_folders.place(workspace_id, [artifact_id], None)
            await unit_of_work.artifacts.remove(workspace_id, stored)
            await unit_of_work.commit()
        if shared == 0:
            await self._delete_stored_object(stored)

    async def _referencing_graphs(
        self,
        saved_graphs: SavedGraphService,
        workspace_id: UUID,
        artifact_id: UUID,
        run_graph_ids: list[UUID],
    ) -> list[tuple[UUID, str]]:
        """Every graph that holds the artifact, each with the name to show for it.

        A saved revision comes back named from the lookup that found it; a graph only
        the recorded runs point at needs a read of its own.
        """

        titles = dict(
            await saved_graphs.titles_referencing_artifact(workspace_id, artifact_id)
        )
        for graph_id in run_graph_ids:
            if graph_id not in titles:
                titles[graph_id] = await self._graph_title(
                    saved_graphs, workspace_id, graph_id
                )
        return sorted(
            titles.items(), key=lambda item: (item[1].casefold(), str(item[0]))
        )

    async def _graph_title(
        self,
        saved_graphs: SavedGraphService,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> str:
        """Name a graph a recorded run points at.

        A history row outlives its graph only in theory, since deleting a graph
        removes its history with it. Should one be left behind, the refusal names the
        identity it has rather than turning into a not-found.
        """

        try:
            graph = await saved_graphs.get(workspace_id, graph_id)
        except NotFoundError:
            return f"graph {graph_id}"
        return graph.name

    async def _delete_stored_object(self, artifact: ArtifactObject) -> None:
        """Release the object the artifact row names.

        A missing object is not a failure: the row is already gone, which is the
        state the caller asked for. A table artifact keeps its manifest and chunks
        under further keys, and only this one object is released, so its remaining
        objects stay in storage unreferenced rather than taking a row with them.
        """

        if (
            self._storage is None
            or artifact.bucket is None
            or artifact.object_key is None
        ):
            return
        try:
            await self._storage.delete(artifact.bucket, artifact.object_key)
        except FileNotFoundError:
            return

    def _present(
        self,
        item: LibraryItem,
        *,
        folder_id: UUID | None = None,
    ) -> LibraryItemResponse:
        return LibraryItemResponse.from_item(
            item,
            name=item.provenance.name or self._artifact_name(item.artifact),
            download_formats=self._artifacts.export_formats(item.artifact),
            folder_id=folder_id,
        )


__all__ = ["LibraryService"]

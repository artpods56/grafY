from collections.abc import Mapping
from dataclasses import dataclass
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
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.execution_history import GraphExecutionDetail
from grafy_core.ports.materialized_outputs import WorkbenchUnitOfWorkPort

from grafy_api.services.errors import WorkbenchOperationError
from grafy_api.v1.routes.artifacts.models import (
    ArtifactExportFormatResponse,
    ArtifactSummaryResponse,
)
from grafy_api.v1.routes.artifacts.services import ArtifactService

from .models import (
    LibraryItemResponse,
    LibraryProvenanceResponse,
    LibraryRunResponse,
)


@dataclass(frozen=True, slots=True)
class LibraryRun:
    execution_id: UUID
    graph_id: UUID
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class LibraryItem:
    artifact: ArtifactObject
    provenance: LibraryProvenance
    run: LibraryRun | None


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
    ) -> None:
        self._unit_of_work = unit_of_work
        self._artifacts = artifacts
        self._artifact_types = artifact_types
        self._saved_graphs = saved_graphs

    async def list_items(self, workspace_id: UUID) -> list[LibraryItemResponse]:
        items: list[LibraryItem] = []
        async with self._unit_of_work as unit_of_work:
            artifacts = await unit_of_work.artifacts.list_library(workspace_id)
            for artifact in artifacts:
                provenance = artifact.library_provenance
                if provenance is None:
                    continue
                items.append(
                    LibraryItem(
                        artifact=artifact,
                        provenance=provenance,
                        run=await self._retained_run(unit_of_work, artifact, provenance),
                    )
                )
        items.sort(
            key=lambda item: (item.provenance.saved_at, str(item.artifact.id)),
            reverse=True,
        )
        return [self._present(item) for item in items]

    async def _retained_run(
        self,
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
    ) -> LibraryItemResponse:
        detail = await self._load_execution(workspace_id, execution_id)
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
        graph_title = await self._graph_title(workspace_id, detail.execution.graph_id)
        provenance = LibraryProvenance.from_run(
            saved_at=datetime.now(UTC),
            graph_id=detail.execution.graph_id,
            graph_title=graph_title,
            node_id=node_id,
            node_title=node_title,
            graph_revision=detail.execution.graph_revision,
            execution_id=execution_id,
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
                # Provenance is a birth record; re-saving never rewrites it.
                return self._present(
                    LibraryItem(
                        artifact=artifact,
                        provenance=artifact.library_provenance,
                        run=await self._retained_run(
                            unit_of_work,
                            artifact,
                            artifact.library_provenance,
                        ),
                    )
                )
            artifact.library_provenance = provenance
            await unit_of_work.commit()
        return self._present(
            LibraryItem(artifact=artifact, provenance=provenance, run=run)
        )

    async def _load_execution(
        self,
        workspace_id: UUID,
        execution_id: UUID,
    ) -> GraphExecutionDetail:
        async with self._unit_of_work as unit_of_work:
            detail = await unit_of_work.execution_history.get(
                workspace_id,
                execution_id,
            )
        if detail is None:
            raise NotFoundError("Graph execution", str(execution_id))
        return detail

    async def _graph_title(self, workspace_id: UUID, graph_id: UUID) -> str:
        if self._saved_graphs is None:
            raise RuntimeError(
                "Saved graph context is not configured for Library provenance"
            )
        graph = await self._saved_graphs.get(workspace_id, graph_id)
        return graph.name

    def _present(self, item: LibraryItem) -> LibraryItemResponse:
        return LibraryItemResponse(
            artifact=self._artifact_summary(item.artifact),
            name=self._artifact_name(item.artifact),
            provenance=LibraryProvenanceResponse.from_provenance(item.provenance),
            run=(
                None
                if item.run is None
                else LibraryRunResponse(
                    execution_id=item.run.execution_id,
                    graph_id=item.run.graph_id,
                    finished_at=item.run.finished_at,
                )
            ),
        )

    def _artifact_summary(self, artifact: ArtifactObject) -> ArtifactSummaryResponse:
        return ArtifactSummaryResponse(
            artifact_id=artifact.id,
            artifact_type=artifact.artifact_type,
            schema_version=artifact.schema_version,
            content_type=artifact.content_type,
            byte_size=artifact.byte_size,
            sha256=artifact.sha256,
            content_url=f"./artifacts/{artifact.id}/content",
            download_formats=[
                ArtifactExportFormatResponse.from_export_format(export_format)
                for export_format in self._artifacts.export_formats(artifact)
            ],
            metadata=artifact.metadata,
        )

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


__all__ = ["LibraryItem", "LibraryRun", "LibraryService"]

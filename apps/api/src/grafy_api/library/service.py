from datetime import UTC, datetime
from collections.abc import Mapping
from uuid import UUID

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeSpec,
    LibraryProvenance,
)
from grafy_core.domain.errors import LibraryArtifactInUseError, NotFoundError
from grafy_core.kernel.expansion import expand_graph
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.project import ProjectDocumentError
from grafy_core.ports.library import LibraryUnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort

from grafy_api.artifacts.models import (
    ArtifactExportFormatResponse,
    ArtifactSummaryResponse,
)
from grafy_api.artifacts.content import ArtifactContentService
from grafy_api.services.errors import WorkbenchOperationError
from grafy_api.library.items import LibraryItem
from grafy_api.library.models import LibraryItemResponse, LibraryProvenanceResponse


class LibraryService:
    """Save exact node results or uploads without changing the source result."""

    def __init__(
        self,
        uow: LibraryUnitOfWorkPort,
        artifacts: ArtifactContentService,
        artifact_types: Mapping[tuple[str, int], ArtifactTypeSpec],
        storage: FileStoragePort | None = None,
    ) -> None:
        self._uow = uow
        self._artifacts = artifacts
        self._artifact_types = artifact_types
        self._storage = storage

    async def list_items(self, workspace_id: UUID) -> list[LibraryItemResponse]:
        async with self._uow as uow:
            artifacts = await uow.artifacts.list_library(workspace_id)
            placements = await uow.library_folders.placements(workspace_id)
        items = [
            LibraryItem(artifact, artifact.library_provenance)
            for artifact in artifacts
            if artifact.library_provenance is not None
        ]
        items.sort(
            key=lambda item: (item.provenance.saved_at, str(item.artifact.id)),
            reverse=True,
        )
        return [
            self._present(item, folder_id=placements.get(item.artifact.id))
            for item in items
        ]

    async def save_from_instance(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        result_fingerprint: str,
        output_port: str,
        name: str,
        call_path: tuple[str, ...] = (),
        map_index: int | None = None,
        item_index: int | None = None,
    ) -> LibraryItemResponse:
        key = InstanceKey(str(project_id), graph_id, call_path, node_id, map_index)
        async with self._uow as uow:
            head = await uow.collaboration.get_head(workspace_id, project_id)
            if head is None:
                raise NotFoundError("Project", str(project_id))
            try:
                graph = head.document.get_graph(graph_id)
            except ProjectDocumentError as exc:
                raise NotFoundError("Graph", graph_id) from exc
            instance = None
            for root in head.document.graphs:
                expanded = expand_graph(
                    head.document, root.id, project_id=str(project_id)
                )
                instance = expanded.instances.get(key)
                if instance is not None:
                    break
            if instance is None:
                raise NotFoundError("Node instance", node_id)
            result = await uow.results.get_result(workspace_id, result_fingerprint)
            if result is None:
                raise NotFoundError("Node result", result_fingerprint)
            output = result.outputs.get(output_port)
            if isinstance(output, ArtifactRefSequence):
                if item_index is None or item_index >= len(output.item_refs):
                    raise WorkbenchOperationError(
                        "Select an existing sequence item to save"
                    )
                selected = output.item_refs[item_index]
            elif isinstance(output, ArtifactRef):
                if item_index is not None:
                    raise WorkbenchOperationError(
                        "A scalar output has no sequence item"
                    )
                selected = output
            else:
                raise WorkbenchOperationError(f"Result has no output {output_port!r}")
            artifact = await uow.artifacts.get(workspace_id, selected.artifact_id)
            if artifact is None or artifact.ref() != selected:
                raise NotFoundError("Result artifact", str(selected.artifact_id))
            provenance = LibraryProvenance.from_instance(
                saved_at=datetime.now(UTC),
                project_id=project_id,
                project_title=head.name,
                graph_id=graph_id,
                graph_title=graph.name,
                node_id=node_id,
                node_title=instance.node.operator_id,
                call_path=call_path,
                map_index=map_index,
                result_fingerprint=result.fingerprint,
                output_port=output_port,
                item_index=item_index,
                name=name,
            )
        return await self._record(workspace_id, selected.artifact_id, provenance)

    async def save_uploaded(
        self, *, workspace_id: UUID, artifact_id: UUID, original_filename: str
    ) -> LibraryItemResponse:
        return await self._record(
            workspace_id,
            artifact_id,
            LibraryProvenance.from_upload(
                saved_at=datetime.now(UTC), original_filename=original_filename
            ),
        )

    async def _record(
        self, workspace_id: UUID, artifact_id: UUID, provenance: LibraryProvenance
    ) -> LibraryItemResponse:
        async with self._uow as uow:
            artifact = await uow.artifacts.get(workspace_id, artifact_id)
            if artifact is None:
                raise NotFoundError("Artifact", str(artifact_id))
            placements = await uow.library_folders.placements(workspace_id)
            if artifact.library_provenance is None:
                artifact.library_provenance = provenance
                await uow.commit()
            return self._present(
                LibraryItem(artifact, artifact.library_provenance),
                folder_id=placements.get(artifact_id),
            )

    async def delete_artifact(self, *, workspace_id: UUID, artifact_id: UUID) -> None:
        async with self._uow as uow:
            artifact = await uow.artifacts.get(workspace_id, artifact_id)
            if artifact is None or artifact.library_provenance is None:
                raise NotFoundError("Library artifact", str(artifact_id))
            titles = await uow.projects.titles_referencing_artifact(
                workspace_id, artifact_id
            )
            retained = await uow.results.artifact_is_referenced(
                workspace_id, artifact_id
            )
            if titles or retained:
                raise LibraryArtifactInUseError(
                    artifact_id=artifact_id,
                    project_ids=list(titles),
                    project_titles=list(titles.values()),
                    retained_result=retained,
                )
            shared = await uow.artifacts.count_artifacts_sharing_object(
                workspace_id,
                bucket=artifact.bucket or "",
                object_key=artifact.object_key or "",
                except_artifact_id=artifact_id,
            )
            await uow.library_folders.place(workspace_id, [artifact_id], None)
            await uow.artifacts.remove(workspace_id, artifact)
            await uow.commit()
        if shared == 0 and (
            self._storage is not None
            and artifact.bucket is not None
            and artifact.object_key is not None
        ):
            try:
                await self._storage.delete(artifact.bucket, artifact.object_key)
            except FileNotFoundError:
                pass

    def _present(
        self, item: LibraryItem, *, folder_id: UUID | None = None
    ) -> LibraryItemResponse:
        artifact = item.artifact
        name = item.provenance.name
        if not name:
            for key in ("download_name", "source_name"):
                value = artifact.metadata.get(key)
                if isinstance(value, str) and value.strip():
                    name = value.strip()
                    break
            else:
                spec = self._artifact_types.get(
                    (artifact.artifact_type, artifact.schema_version)
                )
                name = (
                    spec.title
                    if spec
                    else f"{artifact.artifact_type}@{artifact.schema_version}"
                )
        return LibraryItemResponse(
            artifact=ArtifactSummaryResponse(
                artifact_id=artifact.id,
                artifact_type=artifact.artifact_type,
                schema_version=artifact.schema_version,
                content_type=artifact.content_type,
                byte_size=artifact.byte_size,
                sha256=artifact.sha256,
                content_url=f"./artifacts/{artifact.id}/content",
                download_formats=[
                    ArtifactExportFormatResponse(
                        format=export_format.format,
                        content_type=export_format.content_type,
                        filename=export_format.filename,
                    )
                    for export_format in self._artifacts.export_formats(artifact)
                ],
                metadata=artifact.metadata,
            ),
            name=name,
            provenance=LibraryProvenanceResponse.model_validate(
                item.provenance.model_dump()
            ),
            folder_id=folder_id,
        )

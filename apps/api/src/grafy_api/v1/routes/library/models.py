from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from grafy_core.artifacts import ArtifactExportFormat, LibraryProvenance
from grafy_core.domain.library import LibraryFolder
from pydantic import Field, StringConstraints

from grafy_api.v1.models import ApiResponse
from grafy_api.v1.routes.artifacts.models import (
    ArtifactExportFormatResponse,
    ArtifactSummaryResponse,
)

from .items import LibraryItem, LibraryRun

BoundedNodeId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
BoundedFilename = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
# The domain trims and bounds a folder name too; this only rejects a request the
# service could never satisfy, before it opens a transaction.
BoundedFolderName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]


class LibraryProvenanceResponse(ApiResponse):
    """The birth record frozen when the artifact entered the Library."""

    source: Literal["run", "upload"]
    saved_at: datetime
    graph_id: UUID | None = None
    graph_title: str | None = None
    node_id: str | None = None
    node_title: str | None = None
    graph_revision: int | None = None
    execution_id: UUID | None = None
    original_filename: str | None = None

    @classmethod
    def from_provenance(cls, provenance: LibraryProvenance) -> "LibraryProvenanceResponse":
        return cls(
            source=provenance.source,
            saved_at=provenance.saved_at,
            graph_id=provenance.graph_id,
            graph_title=provenance.graph_title,
            node_id=provenance.node_id,
            node_title=provenance.node_title,
            graph_revision=provenance.graph_revision,
            execution_id=provenance.execution_id,
            original_filename=provenance.original_filename,
        )


class LibraryRunResponse(ApiResponse):
    """The retained run behind a run-sourced Library item.

    Present only while execution history still holds the run, which is exactly
    when the item can link back to it.
    """

    execution_id: UUID
    graph_id: UUID
    finished_at: datetime | None = None

    @classmethod
    def from_run(cls, run: LibraryRun) -> Self:
        return cls(
            execution_id=run.execution_id,
            graph_id=run.graph_id,
            finished_at=run.finished_at,
        )


class LibraryItemResponse(ApiResponse):
    artifact: ArtifactSummaryResponse
    name: str
    provenance: LibraryProvenanceResponse
    run: LibraryRunResponse | None = None
    folder_id: UUID | None = None

    @classmethod
    def from_item(
        cls,
        item: LibraryItem,
        *,
        name: str,
        download_formats: list[ArtifactExportFormat],
        folder_id: UUID | None = None,
    ) -> Self:
        return cls(
            artifact=ArtifactSummaryResponse.from_artifact(
                item.artifact,
                download_formats=[
                    ArtifactExportFormatResponse.from_export_format(export_format)
                    for export_format in download_formats
                ],
            ),
            name=name,
            provenance=LibraryProvenanceResponse.from_provenance(item.provenance),
            run=None if item.run is None else LibraryRunResponse.from_run(item.run),
            folder_id=folder_id,
        )


class LibraryListResponse(ApiResponse):
    items: list[LibraryItemResponse]


class SaveRunArtifactRequest(ApiResponse):
    artifact_id: UUID
    execution_id: UUID
    node_id: BoundedNodeId
    node_title: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
    ]


class SaveUploadedArtifactRequest(ApiResponse):
    artifact_id: UUID
    original_filename: BoundedFilename


class LibraryFolderResponse(ApiResponse):
    """One row of the Library tree. ``parent_id`` of ``null`` is the root."""

    folder_id: UUID
    workspace_id: UUID
    parent_id: UUID | None
    name: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_folder(cls, folder: LibraryFolder) -> Self:
        return cls(
            folder_id=folder.id,
            workspace_id=folder.workspace_id,
            parent_id=folder.parent_id,
            name=folder.name,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )


class LibraryFolderListResponse(ApiResponse):
    folders: list[LibraryFolderResponse]


class CreateLibraryFolderRequest(ApiResponse):
    """Make a folder. ``parent_id: null`` makes it a root folder."""

    name: BoundedFolderName
    parent_id: UUID | None


class RenameLibraryFolderRequest(ApiResponse):
    name: BoundedFolderName


class MoveLibraryFolderRequest(ApiResponse):
    """Move a folder. ``parent_id: null`` moves it to the root."""

    parent_id: UUID | None


class MoveLibraryArtifactsRequest(ApiResponse):
    """File every listed artifact in ``folder_id``, or unfile them when null."""

    artifact_ids: list[UUID] = Field(min_length=1, max_length=200)
    folder_id: UUID | None


__all__ = [
    "CreateLibraryFolderRequest",
    "LibraryFolderListResponse",
    "LibraryFolderResponse",
    "LibraryItemResponse",
    "LibraryListResponse",
    "LibraryProvenanceResponse",
    "LibraryRunResponse",
    "MoveLibraryArtifactsRequest",
    "MoveLibraryFolderRequest",
    "RenameLibraryFolderRequest",
    "SaveRunArtifactRequest",
    "SaveUploadedArtifactRequest",
]

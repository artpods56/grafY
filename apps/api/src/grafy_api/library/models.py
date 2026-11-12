from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from grafy_core.artifacts import LibraryProvenance
from grafy_core.domain.library import LibraryFolder
from pydantic import Field, StringConstraints

from grafy_api.v1.models import ApiResponse
from grafy_api.artifacts.models import ArtifactSummaryResponse

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
BoundedLibraryName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]


class LibraryProvenanceResponse(LibraryProvenance):
    pass


class LibraryItemResponse(ApiResponse):
    artifact: ArtifactSummaryResponse
    name: str
    provenance: LibraryProvenanceResponse
    folder_id: UUID | None = None


class LibraryListResponse(ApiResponse):
    items: list[LibraryItemResponse]


class SaveInstanceArtifactRequest(ApiResponse):
    project_id: UUID
    graph_id: BoundedNodeId
    call_path: tuple[BoundedNodeId, ...] = ()
    node_id: BoundedNodeId
    map_index: int | None = Field(default=None, ge=0)
    result_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_port: BoundedNodeId
    item_index: int | None = Field(default=None, ge=0)
    name: BoundedLibraryName


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
    "MoveLibraryArtifactsRequest",
    "MoveLibraryFolderRequest",
    "RenameLibraryFolderRequest",
    "SaveInstanceArtifactRequest",
    "SaveUploadedArtifactRequest",
]

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from grafy_core.artifacts import LibraryProvenance
from pydantic import StringConstraints

from grafy_api.v1.models import ApiResponse
from grafy_api.v1.routes.artifacts.models import ArtifactSummaryResponse

BoundedNodeId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
BoundedFilename = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
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


class LibraryItemResponse(ApiResponse):
    artifact: ArtifactSummaryResponse
    name: str
    provenance: LibraryProvenanceResponse
    run: LibraryRunResponse | None = None


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


__all__ = [
    "LibraryItemResponse",
    "LibraryListResponse",
    "LibraryProvenanceResponse",
    "LibraryRunResponse",
    "SaveRunArtifactRequest",
    "SaveUploadedArtifactRequest",
]

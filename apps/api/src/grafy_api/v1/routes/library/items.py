from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from grafy_core.artifacts import ArtifactObject, LibraryProvenance


@dataclass(frozen=True, slots=True)
class LibraryRun:
    """The retained run behind a run-sourced Library artifact, if history still holds it."""

    execution_id: UUID
    graph_id: UUID
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class LibraryItem:
    """A Library artifact plus the optional live run link for HTTP presentation."""

    artifact: ArtifactObject
    provenance: LibraryProvenance
    run: LibraryRun | None


__all__ = ["LibraryItem", "LibraryRun"]

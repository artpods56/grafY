from dataclasses import dataclass

from grafy_core.artifacts import ArtifactObject, LibraryProvenance


@dataclass(frozen=True, slots=True)
class LibraryItem:
    artifact: ArtifactObject
    provenance: LibraryProvenance

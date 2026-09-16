"""Read one persisted file artifact's encoded bytes.

Ingest never interprets a ``file.*`` artifact, so the visible decode and import
nodes own that step and read the bytes themselves. This module is that single
read: resolve the exact reference, open the stored object, and return the bytes
with the original filename ingest recorded.
"""

from dataclasses import dataclass
from uuid import UUID

from grafy_core.artifacts import ArtifactRef
from grafy_core.domain.errors import NotFoundError
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort


class FileArtifactError(RuntimeError):
    """A file artifact reference could not be read back as stored bytes."""


@dataclass(frozen=True, slots=True)
class FileArtifactContent:
    content: bytes
    original_filename: str | None


async def load_file_artifact(
    *,
    storage: FileStoragePort,
    uow: UnitOfWorkPort,
    workspace_id: UUID,
    ref: ArtifactRef,
) -> FileArtifactContent:
    async with uow as entered:
        artifact = await entered.artifacts.get(workspace_id, ref.artifact_id)
    if artifact is None:
        raise NotFoundError("Artifact", str(ref.artifact_id))
    if artifact.ref() != ref:
        raise FileArtifactError(
            f"Artifact {ref.artifact_id} does not match the declared reference "
            f"{ref.artifact_type}@{ref.schema_version}"
        )
    if artifact.bucket is None or artifact.object_key is None:
        raise FileArtifactError(
            f"File artifact {ref.artifact_id} "
            f"({ref.artifact_type}@{ref.schema_version}) has no stored object"
        )
    try:
        stream = await storage.load(
            bucket=artifact.bucket,
            path=artifact.object_key,
        )
    except Exception as exc:
        raise FileArtifactError(
            f"Failed to load file artifact {ref.artifact_id} "
            f"({ref.artifact_type}@{ref.schema_version}) from "
            f"{artifact.bucket}/{artifact.object_key}"
        ) from exc
    try:
        content = stream.read()
    finally:
        stream.close()
    if artifact.byte_size is not None and len(content) != artifact.byte_size:
        raise FileArtifactError(
            f"File artifact {ref.artifact_id} contains {len(content)} bytes, "
            f"expected {artifact.byte_size}"
        )
    recorded_name = artifact.metadata.get("original_filename")
    return FileArtifactContent(
        content=content,
        original_filename=(
            recorded_name
            if isinstance(recorded_name, str) and recorded_name.strip() != ""
            else None
        ),
    )


__all__ = [
    "FileArtifactContent",
    "FileArtifactError",
    "load_file_artifact",
]

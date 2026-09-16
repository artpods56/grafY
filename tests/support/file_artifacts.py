"""Seed persisted ``file.*`` artifacts for node-level tests.

Ingest stores the bytes and never interprets them, so a test that exercises a
decode or import node seeds the exact artifact and object ingest would have
written and then runs the visible node.
"""

from hashlib import sha256
from io import BytesIO
from uuid import UUID

from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactTypeSpec,
    JsonObject,
)
from grafy_core.ports.storage import FileStoragePort, SaveFileCommand
from grafy_core.runtime.in_memory import InMemoryUnitOfWork


async def seed_file_artifact(
    storage: FileStoragePort,
    unit_of_work: InMemoryUnitOfWork,
    *,
    workspace_id: UUID,
    spec: ArtifactTypeSpec,
    content: bytes,
    original_filename: str | None = None,
    content_type: str = "application/octet-stream",
    bucket: str = "artifacts",
) -> ArtifactRef:
    """Persist one file artifact and its bytes, returning its exact reference."""

    stored = await storage.save(
        SaveFileCommand(
            bucket=bucket,
            path=f"files/{spec.key.id}/{sha256(content).hexdigest()}",
            stream=BytesIO(content),
            content_type=content_type,
            metadata={},
            allow_overwrite=True,
        )
    )
    metadata: JsonObject = {}
    if original_filename is not None:
        metadata["original_filename"] = original_filename
    artifact = ArtifactObject(
        workspace_id=workspace_id,
        artifact_type=spec.key.id,
        schema_version=spec.key.schema_version,
        content_type=content_type,
        bucket=stored.bucket,
        object_key=stored.path,
        byte_size=stored.byte_size,
        sha256=stored.sha256,
        metadata=metadata,
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    return artifact.ref()


__all__ = ["seed_file_artifact"]

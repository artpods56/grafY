from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from grafy_core.artifact_contracts import RASTER_IMAGE, RasterImageContent
from grafy_core.nodes import NodeExecutionContext
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.storage import (
    FileStreamProtocol,
    SaveFileCommand,
    StoredFile,
    StoredObjectInfo,
)
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import ArtifactWriteContext

from grafy_workbench.image import IMAGES
from grafy_workbench.image.nodes import RasterImageOutputWriter

TEST_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


class RecordingFileStorage:
    def __init__(self) -> None:
        self.saved_command: SaveFileCommand | None = None
        self.saved_content: bytes | None = None

    async def save(self, command: SaveFileCommand) -> StoredFile:
        content = command.stream.read()
        content_hash = sha256(content).hexdigest()
        self.saved_command = command
        self.saved_content = content
        return StoredFile(
            bucket=command.bucket,
            path=command.path,
            etag=None,
            version_id=None,
            byte_size=len(content),
            sha256=content_hash,
        )

    async def move(
        self,
        bucket: str,
        source_path: str,
        destination_path: str,
    ) -> None:
        raise AssertionError(
            f"Unexpected move from {bucket}/{source_path} to {destination_path}"
        )

    async def load(self, bucket: str, path: str) -> FileStreamProtocol:
        raise AssertionError(f"Unexpected load from {bucket}/{path}")

    async def open_chunks(self, bucket: str, path: str) -> FileStreamProtocol:
        return await self.load(bucket, path)

    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        raise AssertionError(f"Unexpected stat for {bucket}/{path}")

    async def load_range(
        self,
        bucket: str,
        path: str,
        start: int,
        end_exclusive: int,
    ) -> bytes:
        raise AssertionError(
            f"Unexpected range load for {bucket}/{path} at {start}:{end_exclusive}"
        )

    async def delete(self, bucket: str, path: str) -> None:
        raise AssertionError(f"Unexpected delete for {bucket}/{path}")


@pytest.mark.asyncio
async def test_raster_writer_preserves_storage_layout_and_metadata() -> None:
    content = b"generated-image"
    content_hash = sha256(content).hexdigest()
    uow = InMemoryUnitOfWork()
    storage = RecordingFileStorage()
    writer = RasterImageOutputWriter(
        storage=storage,
        uow=uow,
        bucket="artifacts",
    )

    ref = await writer.write(
        RasterImageContent(
            content=content,
            content_type="image/png",
            filename="generated.png",
        ),
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=TEST_WORKSPACE_ID,
                node_id="generated_image",
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )

    assert ref.key() == RASTER_IMAGE.key
    assert storage.saved_content == content
    assert storage.saved_command is not None
    assert storage.saved_command.path == (
        f"workspaces/{TEST_WORKSPACE_ID}/image.raster/v1/{content_hash}.png"
    )
    assert storage.saved_command.metadata == {
        "original_filename": "generated.png",
        "artifact_kind": "image.raster",
        "sha256": content_hash,
        "job_id": "generated_image",
    }
    async with uow as entered:
        artifact = await entered.artifacts.get(TEST_WORKSPACE_ID, ref.artifact_id)
    assert artifact is not None
    assert artifact.object_key == storage.saved_command.path
    assert artifact.metadata == {
        "producer_node_id": "generated_image",
        "original_filename": "generated.png",
        "content_hash": content_hash,
        "storage_byte_size": len(content),
        "storage_sha256": content_hash,
    }


def test_image_plugin_owns_the_raster_type_and_writer(tmp_path: Path) -> None:
    registry = PluginRegistry()
    registry.install(IMAGES)
    context = PluginRuntimeContext(
        workspace=tmp_path,
        storage=RecordingFileStorage(),
        uow=InMemoryUnitOfWork(),
        bucket="artifacts",
    )

    assert registry.artifact_types == (RASTER_IMAGE,)
    writers = registry.build_writers(context)
    assert len(writers) == 1
    assert writers[0].artifact_type == RASTER_IMAGE.key

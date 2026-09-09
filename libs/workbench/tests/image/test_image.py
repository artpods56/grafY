from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest

from grafy_core.artifact_contracts import RASTER_IMAGE, RasterImageContent
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.domain.staged_uploads import StagedUpload
from grafy_core.nodes import NodeExecutionContext
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.storage import (
    FileStreamProtocol,
    SaveFileCommand,
    StoredFile,
    StoredObjectInfo,
)
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import ArtifactWriteContext
from grafy_workbench.image import IMAGES
from grafy_workbench.image.nodes import (
    ImageUploadError,
    RasterImageOutputWriter,
    UploadImagesNode,
)


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


async def seed_staged_upload(
    unit_of_work: InMemoryUnitOfWork,
    *,
    workspace_id: UUID,
    upload_key: str,
    filename: str,
    byte_size: int,
) -> None:
    async with unit_of_work as entered:
        await entered.staged_uploads.add(
            StagedUpload(
                workspace_id=workspace_id,
                upload_key=upload_key,
                original_filename=filename,
                byte_size=byte_size,
            )
        )
        await entered.commit()


@pytest.mark.asyncio
async def test_upload_preserves_order_content_and_declared_filenames(
    tmp_path: Path,
) -> None:
    uploads_dir = tmp_path / "uploads"
    workspace_dir = uploads_dir / str(TEST_WORKSPACE_ID)
    workspace_dir.mkdir(parents=True)
    first = workspace_dir / "first.png"
    second = workspace_dir / "second.jpg"
    first.write_bytes(b"first-image")
    second.write_bytes(b"second-image")
    uow = InMemoryUnitOfWork()
    for path in (first, second):
        await seed_staged_upload(
            uow,
            workspace_id=TEST_WORKSPACE_ID,
            upload_key=path.name,
            filename=path.name,
            byte_size=path.stat().st_size,
        )

    output = await UploadImagesNode(uploads_dir=uploads_dir, unit_of_work=uow).run(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="upload"),
        UploadImagesNode.config_contract.model.model_validate(
            {
                "uploads": [
                    {
                        "upload_key": second.name,
                        "filename": "page-002.jpg",
                        "byte_size": second.stat().st_size,
                    },
                    {
                        "upload_key": first.name,
                        "filename": "page-001.png",
                        "byte_size": first.stat().st_size,
                    },
                ]
            }
        ),
        UploadImagesNode.input_contract.model.model_validate({}),
    )

    assert output.images == [
        RasterImageContent(
            content=b"second-image",
            content_type="image/jpeg",
            filename="page-002.jpg",
        ),
        RasterImageContent(
            content=b"first-image",
            content_type="image/png",
            filename="page-001.png",
        ),
    ]


@pytest.mark.asyncio
async def test_upload_rejects_keys_outside_the_upload_root(tmp_path: Path) -> None:
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    node = UploadImagesNode(
        uploads_dir=uploads_dir,
        unit_of_work=InMemoryUnitOfWork(),
    )

    with pytest.raises(ImageUploadError, match="opaque relative name"):
        await node.run(
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="upload"),
            node.config_contract.model.model_validate(
                {
                    "uploads": [
                        {
                            "upload_key": "../outside.png",
                            "filename": "outside.png",
                            "byte_size": 1,
                        }
                    ]
                }
            ),
            node.input_contract.model.model_validate({}),
        )


@pytest.mark.asyncio
async def test_upload_fails_closed_when_file_exists_without_db_row(
    tmp_path: Path,
) -> None:
    uploads_dir = tmp_path / "uploads"
    staged = uploads_dir / str(TEST_WORKSPACE_ID) / "page.png"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"image")
    node = UploadImagesNode(
        uploads_dir=uploads_dir,
        unit_of_work=InMemoryUnitOfWork(),
    )

    with pytest.raises(ImageUploadError, match="was not found in workspace"):
        await node.run(
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="upload"),
            node.config_contract.model.model_validate(
                {
                    "uploads": [
                        {
                            "upload_key": "page.png",
                            "filename": "page.png",
                            "byte_size": staged.stat().st_size,
                        }
                    ]
                }
            ),
            node.input_contract.model.model_validate({}),
        )


@pytest.mark.asyncio
async def test_upload_fails_closed_for_row_in_another_workspace(
    tmp_path: Path,
) -> None:
    uploads_dir = tmp_path / "uploads"
    staged = uploads_dir / str(TEST_WORKSPACE_ID) / "page.png"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"image")
    other_workspace = UUID("00000000-0000-0000-0000-000000000902")
    uow = InMemoryUnitOfWork()
    await seed_staged_upload(
        uow,
        workspace_id=other_workspace,
        upload_key="page.png",
        filename="page.png",
        byte_size=staged.stat().st_size,
    )

    with pytest.raises(ImageUploadError, match="was not found in workspace"):
        await UploadImagesNode(uploads_dir=uploads_dir, unit_of_work=uow).run(
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="upload"),
            UploadImagesNode.config_contract.model.model_validate(
                {
                    "uploads": [
                        {
                            "upload_key": "page.png",
                            "filename": "page.png",
                            "byte_size": staged.stat().st_size,
                        }
                    ]
                }
            ),
            UploadImagesNode.input_contract.model.model_validate({}),
        )


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
        uploads_dir=tmp_path / "uploads",
        storage=RecordingFileStorage(),
        uow=InMemoryUnitOfWork(),
        bucket="artifacts",
    )

    assert registry.artifact_types == (RASTER_IMAGE,)
    writers = registry.build_writers(context)
    assert len(writers) == 1
    assert writers[0].artifact_type == RASTER_IMAGE.key

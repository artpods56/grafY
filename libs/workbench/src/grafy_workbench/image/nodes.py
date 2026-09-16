from hashlib import sha256
from io import BytesIO
from typing import Annotated, final, override

from grafy_core.artifact_contracts import (
    RASTER_IMAGE,
    RasterImageContent,
    RasterImageContentType,
)
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
    JsonObject,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.file_artifacts import load_file_artifact
from grafy_core.file_contracts import (
    BMP_FILE,
    JPEG_FILE,
    PNG_FILE,
    TIFF_FILE,
    WEBP_FILE,
)
from grafy_core.nodes import InPort, Node, NodeExecutionContext, OutPort
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileMetadata, FileStoragePort, SaveFileCommand
from grafy_core.runtime.persistence import (
    ArtifactOutputWriter,
    ArtifactWriteContext,
)
from pydantic import Field

from grafy_workbench.image.declaration import IMAGES

IMAGES.register_artifact_type(RASTER_IMAGE)


@final
class RasterImageOutputWriter(ArtifactOutputWriter):
    artifact_type = RASTER_IMAGE.key

    def __init__(
        self,
        *,
        storage: FileStoragePort,
        uow: UnitOfWorkPort,
        bucket: str,
        storage_backend: str = "local",
    ) -> None:
        self._storage = storage
        self._uow = uow
        self._bucket = bucket
        self._storage_backend = storage_backend

    @override
    async def write(
        self,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef:
        image = RasterImageContent.model_validate(value)
        content_hash = sha256(image.content).hexdigest()
        storage_path = (
            f"workspaces/{context.node_context.workspace_id}/"
            f"{self.artifact_type.id}/v{self.artifact_type.schema_version}/"
            f"{content_hash}{self._suffix_for(image.content_type)}"
        )
        file_metadata: FileMetadata = {
            "original_filename": image.filename,
            "artifact_kind": self.artifact_type.id,
            "sha256": content_hash,
        }
        if context.node_context.node_id is not None:
            file_metadata["job_id"] = context.node_context.node_id

        try:
            stored_file = await self._storage.save(
                SaveFileCommand(
                    bucket=self._bucket,
                    path=storage_path,
                    stream=BytesIO(image.content),
                    content_type=image.content_type,
                    metadata=file_metadata,
                    allow_overwrite=True,
                )
            )
        except Exception as exc:
            node_id = context.node_context.node_id or "<unknown>"
            raise RuntimeError(
                f"Failed to persist raster image output for node {node_id!r} "
                f"at {self._bucket}/{storage_path}"
            ) from exc

        provenance: JsonObject = {
            input_name: [
                {
                    "artifact_id": str(ref.artifact_id),
                    "artifact_type": ref.artifact_type,
                    "schema_version": ref.schema_version,
                }
                for ref in refs
            ]
            for input_name, refs in context.provenance.refs_by_input.items()
        }
        metadata: JsonObject = {
            "producer_node_id": context.node_context.node_id,
            "original_filename": image.filename,
            "content_hash": content_hash,
            "storage_byte_size": stored_file.byte_size,
            "storage_sha256": stored_file.sha256,
        }
        if provenance:
            metadata["provenance"] = provenance
        metadata.update(context.metadata)
        artifact = ArtifactObject(
            workspace_id=context.node_context.workspace_id,
            artifact_type=self.artifact_type.id,
            schema_version=self.artifact_type.schema_version,
            content_type=image.content_type,
            storage_backend=self._storage_backend,
            bucket=stored_file.bucket,
            object_key=stored_file.path,
            byte_size=stored_file.byte_size,
            sha256=stored_file.sha256,
            metadata=metadata,
        )
        async with self._uow as uow:
            await uow.artifacts.add(artifact)
            await uow.commit()
        return artifact.ref()

    def _suffix_for(self, content_type: RasterImageContentType) -> str:
        suffixes: dict[RasterImageContentType, str] = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "image/tiff": ".tiff",
            "image/bmp": ".bmp",
        }
        return suffixes[content_type]


IMAGES.register_writer(
    lambda context: RasterImageOutputWriter(
        storage=context.storage,
        uow=context.uow,
        bucket=context.bucket,
        storage_backend=context.storage_backend,
    )
)


class ImageDecodeError(RuntimeError):
    pass


_IMAGE_FILE_CONTENT_TYPES: dict[str, RasterImageContentType] = {
    PNG_FILE.key.id: "image/png",
    JPEG_FILE.key.id: "image/jpeg",
    WEBP_FILE.key.id: "image/webp",
    TIFF_FILE.key.id: "image/tiff",
    BMP_FILE.key.id: "image/bmp",
}


class ImageDecodeInput(NodeInput):
    files: Annotated[
        ArtifactRefSequence,
        InPort(
            PNG_FILE,
            also_accepts=(JPEG_FILE, WEBP_FILE, TIFF_FILE, BMP_FILE),
        ),
        Field(description="Ordered image file artifacts to decode."),
    ]


class ImageDecodeOutput(NodeOutput):
    images: Annotated[
        list[RasterImageContent],
        OutPort(RASTER_IMAGE),
        Field(description="Decoded raster images in input order."),
    ]


@IMAGES.node(
    operator_id="image.decode",
    version=1,
    title="Decode images",
    factory=lambda context: DecodeImagesNode(
        storage=context.storage,
        uow=context.uow,
    ),
)
@final
class DecodeImagesNode(Node[NodeConfig, ImageDecodeInput, ImageDecodeOutput]):
    """Decode one ordered batch of persisted image file artifacts."""

    def __init__(self, *, storage: FileStoragePort, uow: UnitOfWorkPort) -> None:
        self._storage = storage
        self._uow = uow

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NodeConfig,
        inputs: ImageDecodeInput,
        /,
    ) -> ImageDecodeOutput:
        images: list[RasterImageContent] = []
        for ref in inputs.files.item_refs:
            content_type = _IMAGE_FILE_CONTENT_TYPES.get(ref.artifact_type)
            if content_type is None:
                raise ImageDecodeError(
                    f"Image decode does not accept {ref.artifact_type}@"
                    f"{ref.schema_version} for artifact {ref.artifact_id}"
                )
            file = await load_file_artifact(
                storage=self._storage,
                uow=self._uow,
                workspace_id=context.workspace_id,
                ref=ref,
            )
            images.append(
                RasterImageContent(
                    content=file.content,
                    content_type=content_type,
                    filename=file.original_filename,
                )
            )
        return ImageDecodeOutput(images=images)

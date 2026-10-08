from typing import Annotated, final, override

from grafy_core.artifact_contracts import (
    RASTER_IMAGE,
    RasterImageContent,
    RasterImageContentType,
)
from grafy_core.artifacts import ArtifactRefSequence, NodeConfig, NodeInput, NodeOutput
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
from grafy_core.ports.storage import FileStoragePort
from pydantic import Field

from grafy_plugin_image.declaration import IMAGES


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

from io import BytesIO
from pathlib import PurePosixPath
from typing import Annotated, Literal, final, override
import zlib

from PIL import Image, ImageDraw, ImageFont

from grafy_core.artifact_contracts import (
    IMAGE_REGIONS,
    RASTER_IMAGE,
    ImageRegionSet,
    RasterImageContent,
    RasterImageContentType,
)
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
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
from grafy_core.nodes import (
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    UserFacingNodeError,
)
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


class DrawRegionsError(UserFacingNodeError):
    pass


_KIND_COLORS: dict[str, tuple[int, int, int]] = {
    "text": (59, 130, 246),
    "title": (239, 68, 68),
    "header": (168, 85, 247),
    "footer": (168, 85, 247),
    "table": (34, 197, 94),
    "image": (249, 115, 22),
    "caption": (234, 179, 8),
    "list": (20, 184, 166),
    "equation": (236, 72, 153),
    "code": (100, 116, 139),
    "aside_text": (14, 165, 233),
    "references": (132, 204, 22),
    "signature": (217, 70, 239),
}
_FALLBACK = (
    (59, 130, 246),
    (239, 68, 68),
    (34, 197, 94),
    (249, 115, 22),
    (168, 85, 247),
    (20, 184, 166),
)


class DrawRegionsConfig(NodeConfig):
    line_width: int = Field(
        default=3, ge=1, le=50, description="Box outline width in output pixels."
    )
    fill_opacity: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Opacity of the translucent box fill. 0 draws outlines only.",
    )
    label_text: Literal["kind", "label", "none"] = Field(
        default="kind",
        description="Text drawn above each box: the region kind, its label, or nothing.",
    )


class DrawRegionsInput(NodeInput):
    image: Annotated[
        ArtifactRef,
        InPort(RASTER_IMAGE),
        Field(description="Raster image to draw on."),
    ]
    regions: Annotated[
        ImageRegionSet,
        InPort(IMAGE_REGIONS),
        Field(
            description="Boxes to draw, scaled from their coordinate space to the image size."
        ),
    ]


class DrawRegionsOutput(NodeOutput):
    image: Annotated[
        RasterImageContent,
        OutPort(RASTER_IMAGE),
        Field(description="PNG copy of the input image with regions drawn on top."),
    ]


def render_regions(
    image: Image.Image, regions: ImageRegionSet, config: DrawRegionsConfig
) -> bytes:
    base = image.convert("RGBA")
    overlay = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default(size=max(10, round(min(image.size) / 60)))
    sx = image.width / regions.width
    sy = image.height / regions.height
    for region in regions.regions:
        left = region.x0 * sx
        top = region.y0 * sy
        if left >= image.width or top >= image.height:
            continue
        left = max(0, min(left, image.width - 1))
        top = max(0, min(top, image.height - 1))
        right = max(0, min(region.x1 * sx, image.width - 1))
        bottom = max(0, min(region.y1 * sy, image.height - 1))
        rgb = _KIND_COLORS.get(region.kind)
        if rgb is None:
            rgb = _FALLBACK[zlib.crc32(region.kind.encode()) % len(_FALLBACK)]
        box = (left, top, right, bottom)
        if config.fill_opacity > 0:
            draw.rectangle(box, fill=(*rgb, round(config.fill_opacity * 255)))
        draw.rectangle(box, outline=(*rgb, 255), width=config.line_width)
        text = None
        if config.label_text == "kind":
            text = region.kind
        elif config.label_text == "label":
            text = region.label
        if text:
            if len(text) > 60:
                text = text[:59] + "…"
            text_left, text_top, text_right, text_bottom = draw.textbbox(
                (0, 0), text, font=font
            )
            text_width = text_right - text_left
            text_height = text_bottom - text_top
            y = top - text_height - 2
            if y < 0:
                y = top
            draw.rectangle(
                (left, y, left + text_width + 2, y + text_height + 2),
                fill=(*rgb, 255),
            )
            draw.text(
                (left + 1 - text_left, y + 1 - text_top),
                text,
                font=font,
                fill=(255, 255, 255, 255),
            )
    result = Image.alpha_composite(base, overlay)
    if "A" not in image.getbands():
        result = result.convert("RGB")
    output = BytesIO()
    result.save(output, format="PNG")
    return output.getvalue()


@IMAGES.node(
    operator_id="image.draw_regions",
    version=1,
    title="Draw regions",
    factory=lambda context: DrawRegionsNode(storage=context.storage, uow=context.uow),
)
@final
class DrawRegionsNode(Node[DrawRegionsConfig, DrawRegionsInput, DrawRegionsOutput]):
    """Draw bounding boxes from a region set onto a raster image."""

    def __init__(self, *, storage: FileStoragePort, uow: UnitOfWorkPort) -> None:
        self._storage = storage
        self._uow = uow

    async def _load_image(
        self, context: NodeExecutionContext, ref: ArtifactRef
    ) -> tuple[Image.Image, ArtifactObject]:
        if ref.key() != RASTER_IMAGE.key:
            raise DrawRegionsError(
                f"Expected image.raster@1 for artifact {ref.artifact_id}, "
                f"got {ref.artifact_type}@{ref.schema_version}"
            )
        try:
            async with self._uow as uow:
                artifact = await uow.artifacts.get(
                    context.workspace_id, ref.artifact_id
                )
        except Exception as exc:
            raise DrawRegionsError(
                f"Failed to look up artifact {ref.artifact_id}"
            ) from exc
        if artifact is None:
            raise DrawRegionsError(f"Raster artifact {ref.artifact_id} was not found")
        if artifact.workspace_id != context.workspace_id or artifact.ref() != ref:
            raise DrawRegionsError(
                f"Repository returned a different workspace or ref for artifact {ref.artifact_id}"
            )
        if artifact.bucket is None or artifact.object_key is None:
            raise DrawRegionsError(f"Artifact {ref.artifact_id} has no storage object")
        try:
            stream = await self._storage.load(
                bucket=artifact.bucket, path=artifact.object_key
            )
            try:
                data = stream.read()
            finally:
                stream.close()
            with Image.open(BytesIO(data)) as image:
                return image.copy(), artifact
        except Exception as exc:
            raise DrawRegionsError(
                f"Failed to load artifact {ref.artifact_id} as a raster image"
            ) from exc

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: DrawRegionsConfig,
        inputs: DrawRegionsInput,
        /,
    ) -> DrawRegionsOutput:
        image, artifact = await self._load_image(context, inputs.image)
        filename = "regions.png"
        name = artifact.metadata.get("original_filename")
        if isinstance(name, str) and name:
            filename = f"{PurePosixPath(name).stem}-regions.png"
        return DrawRegionsOutput(
            image=RasterImageContent(
                content=render_regions(image, inputs.regions, config),
                content_type="image/png",
                filename=filename,
            )
        )

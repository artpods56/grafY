from io import BytesIO
from pathlib import PurePosixPath
from typing import Annotated, Literal, final, override
import zlib

from PIL import Image, ImageDraw, ImageFont

from grafy_core.artifact_contracts import IMAGE_REGIONS, ImageRegionSet
from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.documents import (
    BmpFile,
    JpegFile,
    PngFile,
    RasterImage,
    TiffFile,
    WebpFile,
)
from grafy_core.nodes import Node, NodeExecutionContext, UserFacingNodeError
from grafy_core.runtime.artifact_values import inline_model_artifact
from pydantic import Field, StrictStr, field_validator

from grafy_plugin_image.declaration import IMAGES


IMAGES.register(inline_model_artifact(IMAGE_REGIONS, ImageRegionSet))

_HANDLE_READ_LIMIT = 256 * 1024 * 1024
_IMAGE_FILES = (PngFile, JpegFile, WebpFile, TiffFile, BmpFile)


class ImageDecodeError(RuntimeError):
    pass


class ImageDecodeInput(NodeInput):
    files: Annotated[
        list[PngFile | JpegFile | WebpFile | TiffFile | BmpFile],
        Field(
            title="Image files", description="Ordered image file artifacts to decode."
        ),
    ]


class ImageDecodeOutput(NodeOutput):
    images: Annotated[
        list[RasterImage],
        Field(title="Images", description="Decoded raster images in input order."),
    ]


@IMAGES.node(
    operator_id="image.decode",
    version=1,
    title="Read images",
)
@final
class DecodeImagesNode(Node[NodeConfig, ImageDecodeInput, ImageDecodeOutput]):
    """Turns image files into pictures on the canvas."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NodeConfig,
        inputs: ImageDecodeInput,
        /,
    ) -> ImageDecodeOutput:
        del context
        images: list[RasterImage] = []
        for image_file in inputs.files:
            if type(image_file) not in _IMAGE_FILES:
                label = image_file.filename or "this file"
                raise ImageDecodeError(f"Image decode does not accept {label}")
            content = await image_file.read(max_bytes=_HANDLE_READ_LIMIT)
            images.append(
                RasterImage.from_content(
                    content,
                    content_type=type(image_file).media_type,
                    filename=image_file.filename,
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


def _normalize_kinds(value: str | None) -> str | None:
    if value is None:
        return None
    parts: list[str] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            raise ValueError(
                "kinds must be comma-separated region kinds, such as table,title"
            )
        if part not in parts:
            parts.append(part)
    return ",".join(parts)


class DrawRegionsConfig(NodeConfig):
    page: int = Field(
        default=0,
        ge=0,
        description="Page whose boxes to draw. A single image is page 0.",
    )
    kinds: StrictStr | None = Field(
        default=None,
        description=(
            "Comma-separated region kinds to draw, such as table,title. "
            "Unset draws every kind."
        ),
    )

    _validate_kinds = field_validator("kinds")(_normalize_kinds)

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
        RasterImage,
        Field(title="Image", description="Raster image to draw on."),
    ]
    regions: Annotated[
        ImageRegionSet,
        Field(
            title="Boxes",
            description="Boxes to draw, scaled from their coordinate space to the image size.",
        ),
    ]


class DrawRegionsOutput(NodeOutput):
    image: Annotated[
        RasterImage,
        Field(
            title="Image",
            description="PNG copy of the input image with regions drawn on top.",
        ),
    ]


def render_regions(
    image: Image.Image, regions: ImageRegionSet, config: DrawRegionsConfig
) -> bytes:
    page = regions.page(config.page)
    if page is None:
        raise DrawRegionsError(
            f"Region set has no page {config.page}; available pages: "
            + ", ".join(str(page.index) for page in regions.pages)
        )
    base = image.convert("RGBA")
    overlay = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default(size=max(10, round(min(image.size) / 60)))
    sx = image.width / page.width
    sy = image.height / page.height
    kinds = set(config.kinds.split(",")) if config.kinds is not None else None
    for region in regions.regions:
        if region.page != config.page or (
            kinds is not None and region.kind not in kinds
        ):
            continue
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


async def _open_image(image: RasterImage) -> Image.Image:
    label = image.filename or "this image"
    try:
        data = await image.read(max_bytes=_HANDLE_READ_LIMIT)
        with Image.open(BytesIO(data)) as opened:
            return opened.copy()
    except Exception as exc:
        raise DrawRegionsError(f"Failed to read {label} as a raster image") from exc


@IMAGES.node(
    operator_id="image.draw_regions",
    version=1,
    title="Draw boxes",
)
@final
class DrawRegionsNode(Node[DrawRegionsConfig, DrawRegionsInput, DrawRegionsOutput]):
    """Draws the boxes from a reading onto the page."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: DrawRegionsConfig,
        inputs: DrawRegionsInput,
        /,
    ) -> DrawRegionsOutput:
        del context
        image = await _open_image(inputs.image)
        filename = "regions.png"
        if inputs.image.filename:
            filename = f"{PurePosixPath(inputs.image.filename).stem}-regions.png"
        return DrawRegionsOutput(
            image=RasterImage.from_content(
                render_regions(image, inputs.regions, config),
                content_type="image/png",
                filename=filename,
            )
        )


class CropRegionsConfig(NodeConfig):
    page: int = Field(
        default=0,
        ge=0,
        description="Page whose boxes to crop. A single image is page 0.",
    )
    kinds: StrictStr | None = Field(
        default="image",
        description=(
            "Comma-separated region kinds to crop, such as image,table. "
            "Unset crops every kind."
        ),
    )
    _validate_kinds = field_validator("kinds")(_normalize_kinds)
    padding: int = Field(
        default=0,
        ge=0,
        le=500,
        description="Extra pixels kept around each box, in output pixels.",
    )


class CropRegionsInput(NodeInput):
    image: Annotated[RasterImage, Field(title="Image")]
    regions: Annotated[ImageRegionSet, Field(title="Boxes")]


class CropRegionsOutput(NodeOutput):
    crops: Annotated[
        list[RasterImage],
        Field(description="One PNG per matching box, in region order."),
    ]


@IMAGES.node(
    operator_id="image.crop_regions",
    version=1,
    title="Crop boxes",
)
@final
class CropRegionsNode(Node[CropRegionsConfig, CropRegionsInput, CropRegionsOutput]):
    """Cuts out each box as its own picture."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: CropRegionsConfig,
        inputs: CropRegionsInput,
        /,
    ) -> CropRegionsOutput:
        del context
        page = inputs.regions.page(config.page)
        if page is None:
            raise DrawRegionsError(
                f"Region set has no page {config.page}; available pages: "
                + ", ".join(str(page.index) for page in inputs.regions.pages)
            )
        image = await _open_image(inputs.image)
        if image.mode not in ("RGB", "RGBA"):
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            image = image.convert("RGBA" if has_alpha else "RGB")
        stem = "region"
        if inputs.image.filename:
            stem = PurePosixPath(inputs.image.filename).stem
        sx = image.width / page.width
        sy = image.height / page.height
        kinds = set(config.kinds.split(",")) if config.kinds is not None else None
        crops: list[RasterImage] = []
        for region in inputs.regions.regions:
            if region.page != config.page or (
                kinds is not None and region.kind not in kinds
            ):
                continue
            left = max(0, min(round(region.x0 * sx) - config.padding, image.width))
            top = max(0, min(round(region.y0 * sy) - config.padding, image.height))
            right = max(0, min(round(region.x1 * sx) + config.padding, image.width))
            bottom = max(0, min(round(region.y1 * sy) + config.padding, image.height))
            if right <= left or bottom <= top:
                continue
            output = BytesIO()
            image.crop((left, top, right, bottom)).save(output, format="PNG")
            crops.append(
                RasterImage.from_content(
                    output.getvalue(),
                    content_type="image/png",
                    filename=f"{stem}-{region.kind}-{len(crops)}.png",
                )
            )
        return CropRegionsOutput(crops=crops)

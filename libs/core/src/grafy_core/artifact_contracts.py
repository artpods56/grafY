from typing import Literal, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBytes,
    StrictInt,
    StrictStr,
    model_validator,
)

from grafy_core.artifacts import (
    ArtifactExportFormat,
    ArtifactBundleContract,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
)


RasterImageContentType = Literal[
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/tiff",
    "image/bmp",
]


class RasterImageContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: StrictBytes = Field(min_length=1)
    content_type: RasterImageContentType
    filename: StrictStr | None = Field(default=None, min_length=1)


RASTER_IMAGE = ArtifactTypeSpec(
    key=ArtifactTypeKey("image.raster", 1),
    title="Raster image",
    bundle=ArtifactBundleContract(format="binary-file", version=1),
)


class ImageRegion(BaseModel):
    """One axis-aligned box in its region set's pixel coordinate space."""

    model_config = ConfigDict(extra="forbid")

    x0: float = Field(ge=0)
    y0: float = Field(ge=0)
    x1: float = Field(ge=0)
    y1: float = Field(ge=0)
    kind: StrictStr = Field(min_length=1, max_length=64)
    label: StrictStr | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_corners(self) -> Self:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("region bottom-right corner must not precede top-left")
        return self


class ImageRegionSet(BaseModel):
    """Boxes measured against one page or image of the given pixel size.

    Consumers scale boxes from ``width`` x ``height`` to the raster they draw on.
    """

    model_config = ConfigDict(extra="forbid")

    width: StrictInt = Field(gt=0)
    height: StrictInt = Field(gt=0)
    page_index: StrictInt | None = Field(default=None, ge=0)
    regions: list[ImageRegion]


# Owned by the Image family. It lives here so a Plugin that produces regions
# carries the same exact contract as the Image Plugin that draws them.
IMAGE_REGIONS = ArtifactTypeSpec(
    key=ArtifactTypeKey("image.regions", 1),
    title="Image regions",
    payload_schema=cast(JsonObject, ImageRegionSet.model_json_schema()),
)


class IntegerValuePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: StrictInt


INTEGER_VALUE = ArtifactTypeSpec(
    key=ArtifactTypeKey("scalar.integer", 1),
    title="Integer value",
    payload_schema=cast(JsonObject, IntegerValuePayload.model_json_schema()),
    materialized_json_type="integer",
)


class TextValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: StrictStr


TextValuePayload = TextValue


TEXT_VALUE = ArtifactTypeSpec(
    key=ArtifactTypeKey("scalar.text", 1),
    title="Text value",
    payload_schema=cast(JsonObject, TextValuePayload.model_json_schema()),
    materialized_json_type="string",
    export_formats=(
        ArtifactExportFormat(
            format="txt",
            content_type="text/plain; charset=utf-8",
            filename="text.txt",
        ),
    ),
)


class MarkdownValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown: StrictStr


# Owned by the Text family. It lives here so a Plugin that reads or writes
# Markdown carries the same exact contract as a release dependency.
MARKDOWN = ArtifactTypeSpec(
    key=ArtifactTypeKey("text.markdown", 1),
    title="Markdown",
    payload_schema=cast(JsonObject, MarkdownValue.model_json_schema()),
    export_formats=(
        ArtifactExportFormat(
            format="txt",
            content_type="text/plain; charset=utf-8",
            filename="markdown.txt",
        ),
    ),
)


__all__ = [
    "IMAGE_REGIONS",
    "INTEGER_VALUE",
    "MARKDOWN",
    "MarkdownValue",
    "RASTER_IMAGE",
    "TEXT_VALUE",
    "ImageRegion",
    "ImageRegionSet",
    "IntegerValuePayload",
    "RasterImageContent",
    "RasterImageContentType",
    "TextValue",
    "TextValuePayload",
]

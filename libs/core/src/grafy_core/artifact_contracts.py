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


class ImagePage(BaseModel):
    """Pixel size of one page or image that regions are measured against."""

    model_config = ConfigDict(extra="forbid")

    index: StrictInt = Field(ge=0)
    width: StrictInt = Field(gt=0)
    height: StrictInt = Field(gt=0)


class ImageRegion(BaseModel):
    """One axis-aligned box in its region set's pixel coordinate space."""

    model_config = ConfigDict(extra="forbid")

    page: StrictInt = Field(default=0, ge=0)
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
    """Boxes for one or more pages.

    Each box belongs to ``page``; consumers scale boxes from that page's
    ``width`` x ``height`` to the raster they draw on.
    """

    model_config = ConfigDict(extra="forbid")

    pages: list[ImagePage] = Field(min_length=1)
    regions: list[ImageRegion]

    @model_validator(mode="after")
    def validate_pages(self) -> Self:
        indexes = {page.index for page in self.pages}
        if len(indexes) != len(self.pages):
            raise ValueError("region set page indexes must be unique")
        for region in self.regions:
            if region.page not in indexes:
                raise ValueError(
                    f"region page {region.page} is not declared in the region set"
                )
        return self

    def page(self, index: int) -> ImagePage | None:
        return next((page for page in self.pages if page.index == index), None)


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
    "ImagePage",
    "ImageRegion",
    "ImageRegionSet",
    "IntegerValuePayload",
    "RasterImageContent",
    "RasterImageContentType",
    "TextValue",
    "TextValuePayload",
]

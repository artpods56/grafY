import re
from typing import Literal, Self, cast
from uuid import UUID

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


# A name the model picks for one source. The page's template uses it as a
# Mustache key, so it has to be an identifier.
HTML_PAGE_SOURCE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_HTML_PAGE_SOURCES = 16


class HtmlPageSource(BaseModel):
    """One artifact a page reads, stored as the server looked it up."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID
    artifact_type: StrictStr = Field(min_length=1)
    schema_version: StrictInt = Field(ge=1)


class HtmlPage(BaseModel):
    """An HTML Mustache template and the artifacts it reads.

    ``sources`` is never empty. A template with nothing to read is text.
    The names are chosen per page and the targets are whatever those artifacts
    are, so this type declares no artifact-reference field.
    """

    model_config = ConfigDict(extra="forbid")

    html: StrictStr
    sources: dict[str, HtmlPageSource] = Field(
        min_length=1, max_length=MAX_HTML_PAGE_SOURCES
    )

    @model_validator(mode="after")
    def validate_source_names(self) -> Self:
        for name in self.sources:
            if HTML_PAGE_SOURCE_NAME.fullmatch(name) is None:
                raise ValueError(
                    f"HTML page source name {name!r} must start with a letter or "
                    "underscore and contain only letters, digits and underscores"
                )
        return self


# Owned by the Text family, next to Markdown. A page is a template plus the
# exact artifacts it reads. Re-running a node does not move those ids.
HTML_PAGE = ArtifactTypeSpec(
    key=ArtifactTypeKey("html.page", 1),
    title="HTML page",
    payload_schema=cast(JsonObject, HtmlPage.model_json_schema()),
)


__all__ = [
    "HTML_PAGE",
    "HTML_PAGE_SOURCE_NAME",
    "IMAGE_REGIONS",
    "INTEGER_VALUE",
    "MARKDOWN",
    "MAX_HTML_PAGE_SOURCES",
    "HtmlPage",
    "HtmlPageSource",
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

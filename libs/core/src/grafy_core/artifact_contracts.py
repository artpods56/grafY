from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StrictBytes, StrictInt, StrictStr

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
    "INTEGER_VALUE",
    "MARKDOWN",
    "MarkdownValue",
    "RASTER_IMAGE",
    "TEXT_VALUE",
    "IntegerValuePayload",
    "RasterImageContent",
    "RasterImageContentType",
    "TextValue",
    "TextValuePayload",
]

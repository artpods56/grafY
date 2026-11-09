"""The Parse chunk shape, for both inline results and downloaded result documents.

A block's `type` and `confidence` stay plain strings so a new provider value cannot
fail a run. Coordinates must be finite because NaN and Infinity are not valid JSON
in a stored artifact.
"""

from pydantic import BaseModel, Field, TypeAdapter


class ParseBoundingBox(BaseModel):
    left: float = Field(allow_inf_nan=False)
    top: float = Field(allow_inf_nan=False)
    width: float = Field(allow_inf_nan=False)
    height: float = Field(allow_inf_nan=False)
    page: int
    original_page: int | None = None


class ParseBlockConfidence(BaseModel):
    parse_confidence: float | None = Field(default=None, allow_inf_nan=False)


class ParseBlock(BaseModel):
    type: str
    content: str
    bbox: ParseBoundingBox
    confidence: str | None = None
    granular_confidence: ParseBlockConfidence | None = None


class ParseChunk(BaseModel):
    content: str
    blocks: list[ParseBlock]


ParseChunkList = TypeAdapter(list[ParseChunk])

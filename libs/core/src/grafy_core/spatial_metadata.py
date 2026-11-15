"""Stored and producer-side projection and feature metadata contracts."""

from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from grafy_core.spatial_bounds import Bounds, GeoBounds, validated_bounds


class GeoFeatureCollectionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["geo.feature_collection"]
    crs: Literal["EPSG:4326"] = "EPSG:4326"
    source_name: StrictStr = Field(min_length=1)
    bounds: GeoBounds | None


class GeoVectorProjectionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["pmtiles"]
    bucket: StrictStr = Field(min_length=1)
    object_key: StrictStr = Field(min_length=1)
    content_type: Literal["application/vnd.pmtiles"]
    byte_size: StrictInt = Field(ge=1)
    sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    min_zoom: StrictInt = Field(ge=0, le=22)
    max_zoom: StrictInt = Field(ge=0, le=22)
    source_layer: StrictStr = Field(min_length=1)
    bounds: GeoBounds | None
    compiler: StrictStr = Field(min_length=1)

    @model_validator(mode="after")
    def validate_zoom_range(self) -> Self:
        if self.min_zoom > self.max_zoom:
            raise ValueError("min_zoom must not exceed max_zoom")
        return self


class GeoRasterProjectionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["xyz"]
    bucket: StrictStr = Field(min_length=1)
    prefix: StrictStr = Field(min_length=1)
    extension: Literal["png"]
    content_type: Literal["image/png"]
    min_zoom: StrictInt = Field(ge=0, le=22)
    max_zoom: StrictInt = Field(ge=0, le=22)
    tile_size: Literal[256]
    bounds: GeoBounds
    source_crs: StrictStr = Field(min_length=1)
    width: StrictInt = Field(ge=1)
    height: StrictInt = Field(ge=1)
    band_count: StrictInt = Field(ge=1)
    compiler: StrictStr = Field(min_length=1)

    @model_validator(mode="after")
    def validate_zoom_range(self) -> Self:
        if self.min_zoom > self.max_zoom:
            raise ValueError("min_zoom must not exceed max_zoom")
        return self


class VectorProjectionMetadata(GeoVectorProjectionMetadata):
    kind: Literal["pmtiles"] = "pmtiles"
    content_type: Literal["application/vnd.pmtiles"] = "application/vnd.pmtiles"
    bounds: Bounds | None

    @field_validator("bounds")
    @classmethod
    def validate_bounds(cls, value: Bounds | None) -> Bounds | None:
        return validated_bounds(value, field_name="vector projection bounds")


class RasterProjectionMetadata(GeoRasterProjectionMetadata):
    kind: Literal["xyz"] = "xyz"
    extension: Literal["png"] = "png"
    content_type: Literal["image/png"] = "image/png"
    tile_size: Literal[256] = 256
    bounds: Bounds

    @field_validator("bounds")
    @classmethod
    def validate_bounds(cls, value: Bounds) -> Bounds:
        validated = validated_bounds(value, field_name="raster projection bounds")
        if validated is None:
            raise ValueError("raster projection bounds are required")
        return validated


type GeoPropertyValueType = Literal[
    "text",
    "integer",
    "number",
    "boolean",
    "null",
    "mixed",
    "unknown",
]


class GeoFeaturePropertyMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(min_length=1, max_length=255)
    title: StrictStr = Field(min_length=1, max_length=1_024)
    value_type: GeoPropertyValueType


class GeoStoredFeatureCollectionMetadata(GeoFeatureCollectionMetadata):
    kind: Literal["geo.feature_collection"] = "geo.feature_collection"
    bounds: Bounds | None
    property_fields: list[GeoFeaturePropertyMetadata] = Field(
        default_factory=list[GeoFeaturePropertyMetadata],
    )

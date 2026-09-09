"""Producer-neutral stored spatial payloads shared by API readers and GIS writers."""

import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from grafy_core.artifacts import JsonObject


type GeoBounds = tuple[float, float, float, float]


class GeoFeatureCollectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["FeatureCollection"] = "FeatureCollection"
    crs: Literal["EPSG:4326"] = "EPSG:4326"
    features: list[JsonObject]
    source_name: StrictStr = Field(min_length=1)
    bounds: GeoBounds | None

    def canonical_json_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


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

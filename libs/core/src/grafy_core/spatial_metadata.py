"""Stored and producer-side feature metadata contracts."""

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
)

from grafy_core.spatial_bounds import Bounds, GeoBounds


class GeoFeatureCollectionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["geo.feature_collection"]
    crs: Literal["EPSG:4326"] = "EPSG:4326"
    source_name: StrictStr = Field(min_length=1)
    bounds: GeoBounds | None


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

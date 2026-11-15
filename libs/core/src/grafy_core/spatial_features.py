"""GeoJSON feature collection payloads and recursive geometry validation."""

import json
import math
from typing import Literal, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    field_validator,
    model_validator,
)

from grafy_core.artifacts import JsonObject
from grafy_core.spatial_bounds import Bounds, GeoBounds


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


class GeoFeatureCollection(GeoFeatureCollectionPayload):
    """An exact, canonical WGS84 GeoJSON FeatureCollection."""

    source_name: StrictStr = Field(min_length=1, max_length=1_024)
    bounds: Bounds | None

    @model_validator(mode="after")
    def validate_features(self) -> Self:
        observed: list[tuple[float, float]] = []
        for feature_index, feature in enumerate(self.features):
            if feature.get("type") != "Feature":
                raise ValueError(f"Feature {feature_index} must have type 'Feature'")
            geometry = feature.get("geometry")
            if geometry is None:
                continue
            if not isinstance(geometry, dict):
                raise ValueError(
                    f"Feature {feature_index} geometry must be an object or null"
                )
            _validate_geometry(cast(JsonObject, geometry), feature_index, observed)

        calculated: Bounds | None = None
        if observed:
            longitudes = [position[0] for position in observed]
            latitudes = [position[1] for position in observed]
            calculated = (
                min(longitudes),
                min(latitudes),
                max(longitudes),
                max(latitudes),
            )
        if self.bounds != calculated:
            raise ValueError("GeoJSON bounds do not match its feature coordinates")
        return self

    @field_validator("source_name")
    @classmethod
    def validate_source_name(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("source_name must not have surrounding whitespace")
        return value

    @classmethod
    def from_geojson_bytes(
        cls, content: bytes, source_name: str
    ) -> "GeoFeatureCollection":
        try:
            raw = _UploadedFeatureCollection.model_validate_json(content)
        except Exception as exc:
            raise ValueError(
                f"{source_name!r} is not a valid GeoJSON FeatureCollection"
            ) from exc
        return cls.from_features(raw.features, source_name)

    @classmethod
    def from_features(
        cls,
        features: list[JsonObject],
        source_name: str,
    ) -> "GeoFeatureCollection":
        coordinates: list[tuple[float, float]] = []
        for feature_index, feature in enumerate(features):
            geometry = feature.get("geometry")
            if isinstance(geometry, dict):
                _validate_geometry(
                    cast(JsonObject, geometry), feature_index, coordinates
                )
        calculated: Bounds | None = None
        if coordinates:
            longitudes = [position[0] for position in coordinates]
            latitudes = [position[1] for position in coordinates]
            calculated = (
                min(longitudes),
                min(latitudes),
                max(longitudes),
                max(latitudes),
            )
        return cls(
            features=features,
            source_name=source_name,
            bounds=calculated,
        )


class _UploadedFeatureCollection(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["FeatureCollection"]
    features: list[JsonObject]


def _validate_geometry(
    geometry: JsonObject,
    feature_index: int,
    observed: list[tuple[float, float]],
) -> None:
    geometry_type = geometry.get("type")
    allowed = {
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
        "GeometryCollection",
    }
    if geometry_type not in allowed:
        raise ValueError(
            f"Feature {feature_index} has unsupported geometry type {geometry_type!r}"
        )
    if geometry_type == "GeometryCollection":
        geometries = geometry.get("geometries")
        if not isinstance(geometries, list):
            raise ValueError(
                f"Feature {feature_index} GeometryCollection requires geometries"
            )
        for child in cast(list[object], geometries):
            if not isinstance(child, dict):
                raise ValueError(
                    f"Feature {feature_index} contains a non-object geometry"
                )
            _validate_geometry(cast(JsonObject, child), feature_index, observed)
        return

    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        raise ValueError(f"Feature {feature_index} geometry requires coordinates")
    _collect_positions(cast(list[object], coordinates), feature_index, observed)


def _collect_positions(
    value: list[object],
    feature_index: int,
    observed: list[tuple[float, float]],
) -> None:
    first = value[0] if value else None
    second = value[1] if len(value) > 1 else None
    if (
        isinstance(first, int | float)
        and not isinstance(first, bool)
        and isinstance(second, int | float)
        and not isinstance(second, bool)
    ):
        longitude = float(first)
        latitude = float(second)
        if not math.isfinite(longitude) or not math.isfinite(latitude):
            raise ValueError(f"Feature {feature_index} coordinates must be finite")
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError(
                f"Feature {feature_index} coordinates are outside WGS84 longitude/latitude ranges"
            )
        observed.append((longitude, latitude))
        return

    if not value:
        raise ValueError(f"Feature {feature_index} contains an empty coordinate array")
    for child in value:
        if not isinstance(child, list):
            raise ValueError(f"Feature {feature_index} has malformed coordinates")
        _collect_positions(cast(list[object], child), feature_index, observed)

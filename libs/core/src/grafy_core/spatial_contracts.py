"""Producer-neutral stored spatial payloads shared by API readers and GIS writers."""

import json
import math
from ipaddress import ip_address
from typing import Annotated, Literal, Self, cast

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StrictBool,
    StrictFloat,
    field_validator,
    model_validator,
)

from grafy_core.artifacts import ArtifactRef, JsonObject


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


HexColor = Annotated[StrictStr, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


RasterResampling = Literal["linear", "nearest"]


class GeoFillStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    color: HexColor = "#2563eb"
    opacity: float = Field(default=0.45, ge=0.0, le=1.0)


class GeoLineStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    color: HexColor = "#1d4ed8"
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    width: float = Field(default=1.5, ge=0.0, le=64.0)


class GeoPointStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    color: HexColor = "#dc2626"
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    radius: float = Field(default=5.0, ge=0.0, le=128.0)
    stroke_color: HexColor = "#ffffff"
    stroke_width: float = Field(default=1.0, ge=0.0, le=32.0)


type GeoCategoryValue = StrictStr | StrictInt | StrictFloat | StrictBool


class GeoPointCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z][A-Za-z0-9_-]*$",
    )
    title: StrictStr = Field(min_length=1, max_length=1_024)
    values: list[GeoCategoryValue] = Field(min_length=1, max_length=128)
    point: GeoPointStyle = Field(default_factory=GeoPointStyle)
    min_zoom: StrictInt = Field(default=0, ge=0, le=24)
    max_zoom: StrictInt = Field(default=22, ge=0, le=24)

    @field_validator("id", "title")
    @classmethod
    def validate_non_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("values must not have surrounding whitespace")
        return value

    @model_validator(mode="after")
    def validate_category(self) -> Self:
        if self.min_zoom > self.max_zoom:
            raise ValueError("min_zoom must not exceed max_zoom")
        typed_values = [(type(value), value) for value in self.values]
        if len(typed_values) != len(set(typed_values)):
            raise ValueError("category values must be unique")
        return self


class GeoLabelStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property: StrictStr = Field(min_length=1, max_length=1_024)
    color: HexColor = "#111827"
    size: float = Field(default=12.0, ge=6.0, le=72.0)
    halo_color: HexColor = "#ffffff"
    halo_width: float = Field(default=1.0, ge=0.0, le=16.0)

    @field_validator("property")
    @classmethod
    def validate_property(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("label property must not have surrounding whitespace")
        return value


class GeoVectorStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["vector"] = "vector"
    fill: GeoFillStyle = Field(default_factory=GeoFillStyle)
    line: GeoLineStyle = Field(default_factory=GeoLineStyle)
    outline: GeoLineStyle = Field(default_factory=GeoLineStyle)
    point: GeoPointStyle = Field(default_factory=GeoPointStyle)
    label: GeoLabelStyle | None = None


class GeoCategorizedPointStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["categorized_points"] = "categorized_points"
    category_property: StrictStr = Field(min_length=1, max_length=1_024)
    categories: list[GeoPointCategory] = Field(min_length=1, max_length=128)
    label: GeoLabelStyle | None = None

    @field_validator("category_property")
    @classmethod
    def validate_category_property(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("category property must not have surrounding whitespace")
        return value

    @model_validator(mode="after")
    def validate_categories(self) -> Self:
        category_ids = [category.id for category in self.categories]
        if len(category_ids) != len(set(category_ids)):
            raise ValueError("category ids must be unique")
        observed_values: set[tuple[type[object], object]] = set()
        for category in self.categories:
            for value in category.values:
                key = (type(value), value)
                if key in observed_values:
                    raise ValueError(
                        "category values must not appear in multiple categories"
                    )
                observed_values.add(key)
        return self


GeoFeatureStyle = Annotated[
    GeoVectorStyle | GeoCategorizedPointStyle,
    Field(discriminator="kind"),
]


class GeoRasterStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["raster"] = "raster"
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    brightness_min: float = Field(default=0.0, ge=0.0, le=1.0)
    brightness_max: float = Field(default=1.0, ge=0.0, le=1.0)
    contrast: float = Field(default=0.0, ge=-1.0, le=1.0)
    saturation: float = Field(default=0.0, ge=-1.0, le=1.0)
    hue: float = Field(default=0.0, ge=0.0, le=359.0)
    resampling: RasterResampling = "linear"

    @model_validator(mode="after")
    def validate_brightness_range(self) -> Self:
        if self.brightness_min > self.brightness_max:
            raise ValueError("brightness_min must not exceed brightness_max")
        return self


GeoLayerStyle = Annotated[
    GeoVectorStyle | GeoCategorizedPointStyle | GeoRasterStyle,
    Field(discriminator="kind"),
]


Bounds = Annotated[
    tuple[
        Annotated[
            float,
            Field(
                title="West longitude",
                json_schema_extra={"minimum": -180.0, "maximum": 180.0},
            ),
        ],
        Annotated[
            float,
            Field(
                title="South latitude",
                json_schema_extra={"minimum": -90.0, "maximum": 90.0},
            ),
        ],
        Annotated[
            float,
            Field(
                title="East longitude",
                json_schema_extra={"minimum": -180.0, "maximum": 180.0},
            ),
        ],
        Annotated[
            float,
            Field(
                title="North latitude",
                json_schema_extra={"minimum": -90.0, "maximum": 90.0},
            ),
        ],
    ],
    Field(
        description=(
            "WGS84 bounds ordered as west longitude, south latitude, east "
            "longitude, north latitude."
        )
    ),
]


WmsVersion = Literal["1.1.1", "1.3.0"]


WmsImageFormat = Literal["image/png", "image/jpeg"]


BasemapKind = Literal["openstreetmap", "none"]


def validated_public_service_url(
    value: AnyHttpUrl,
    *,
    service_name: str,
) -> AnyHttpUrl:
    if value.username is not None or value.password is not None:
        raise ValueError(f"{service_name} URL must not contain embedded credentials")
    if value.query is not None:
        raise ValueError(
            f"{service_name} URL must be a query-free service endpoint; request "
            "parameters are derived from typed configuration"
        )
    host = value.host
    if host is None:
        raise ValueError(f"{service_name} URL must include a host")
    normalized_host = host.rstrip(".").lower()
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        raise ValueError(f"{service_name} URL must not target localhost")
    try:
        literal_address = ip_address(normalized_host)
    except ValueError:
        return value
    if not literal_address.is_global:
        raise ValueError(
            f"{service_name} URL must not target a private, loopback, link-local, "
            "reserved, multicast, or unspecified address"
        )
    return value


def _validated_bounds(value: Bounds | None, *, field_name: str) -> Bounds | None:
    if value is None:
        return None
    if not all(math.isfinite(coordinate) for coordinate in value):
        raise ValueError(f"{field_name} coordinates must be finite")
    west, south, east, north = value
    if not -180 <= west <= 180 or not -180 <= east <= 180:
        raise ValueError(f"{field_name} longitudes must be within [-180, 180]")
    if not -90 <= south <= 90 or not -90 <= north <= 90:
        raise ValueError(f"{field_name} latitudes must be within [-90, 90]")
    if west > east or south > north:
        raise ValueError(f"{field_name} must be ordered west, south, east, north")
    return value


def _validate_ref(
    ref: ArtifactRef,
    *,
    artifact_type: str,
    schema_version: int,
    field_name: str,
) -> None:
    if ref.artifact_type != artifact_type or ref.schema_version != schema_version:
        raise ValueError(
            f"{field_name} must reference {artifact_type}@{schema_version}, got "
            f"{ref.artifact_type}@{ref.schema_version}"
        )


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

        calculated = _bounds(observed)
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
        return cls(
            features=features,
            source_name=source_name,
            bounds=_bounds(coordinates),
        )


class _UploadedFeatureCollection(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["FeatureCollection"]
    features: list[JsonObject]


class GeoFeatureArtifactSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["feature_collection"] = "feature_collection"
    artifact: ArtifactRef

    @model_validator(mode="after")
    def validate_artifact(self) -> Self:
        _validate_ref(
            self.artifact,
            artifact_type="geo.feature_collection",
            schema_version=1,
            field_name="feature source artifact",
        )
        return self


class GeoRasterArtifactSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["raster_scan"] = "raster_scan"
    artifact: ArtifactRef

    @model_validator(mode="after")
    def validate_artifact(self) -> Self:
        _validate_ref(
            self.artifact,
            artifact_type="geo.raster_scan",
            schema_version=1,
            field_name="raster source artifact",
        )
        return self


class GeoWmsSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["wms"] = "wms"
    url: AnyHttpUrl
    layer: StrictStr = Field(min_length=1, max_length=1_024)
    version: WmsVersion = "1.3.0"
    format: WmsImageFormat = "image/png"
    bounds: Bounds
    attribution: StrictStr = Field(min_length=1, max_length=4_096)
    style_name: StrictStr | None = Field(default=None, max_length=1_024)

    @field_validator("layer", "attribution", "style_name")
    @classmethod
    def validate_non_whitespace(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("values must not have surrounding whitespace")
        return value

    @field_validator("bounds")
    @classmethod
    def validate_bounds(cls, value: Bounds) -> Bounds:
        validated = _validated_bounds(value, field_name="WMS bounds")
        if validated is None:
            raise ValueError("WMS bounds are required")
        return validated

    @model_validator(mode="after")
    def reject_embedded_credentials(self) -> Self:
        validated_public_service_url(self.url, service_name="WMS")
        return self


GeoLayerSource = Annotated[
    GeoFeatureArtifactSource | GeoRasterArtifactSource | GeoWmsSource,
    Field(discriminator="kind"),
]


class GeoMapLayer(BaseModel):
    """Lightweight display instructions for one vector, raster, or WMS source."""

    model_config = ConfigDict(extra="forbid")

    title: StrictStr = Field(min_length=1, max_length=1_024)
    visible: bool = True
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    min_zoom: StrictInt = Field(default=0, ge=0, le=24)
    max_zoom: StrictInt = Field(default=22, ge=0, le=24)
    source: GeoLayerSource
    style: GeoLayerStyle

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("title must not have surrounding whitespace")
        return value

    @model_validator(mode="after")
    def validate_source_and_style(self) -> Self:
        if self.min_zoom > self.max_zoom:
            raise ValueError("min_zoom must not exceed max_zoom")
        if self.source.kind == "feature_collection" and self.style.kind not in {
            "vector",
            "categorized_points",
        }:
            raise ValueError("Feature collection sources require vector style")
        if self.style.kind == "categorized_points":
            for category in self.style.categories:
                if max(self.min_zoom, category.min_zoom) > min(
                    self.max_zoom,
                    category.max_zoom,
                ):
                    raise ValueError(
                        f"Category {category.id!r} zoom range does not overlap "
                        "the layer zoom range"
                    )
        if self.source.kind in {"raster_scan", "wms"} and self.style.kind != "raster":
            raise ValueError("Raster scan and WMS sources require raster style")
        return self


class GeoMapDocument(BaseModel):
    """An ordered composition of lightweight geo.map_layer artifact references."""

    model_config = ConfigDict(extra="forbid")

    layers: list[ArtifactRef] = Field(min_length=1)
    basemap: BasemapKind = "openstreetmap"
    initial_bounds: Bounds | None = None

    @field_validator("initial_bounds")
    @classmethod
    def validate_initial_bounds(cls, value: Bounds | None) -> Bounds | None:
        return _validated_bounds(value, field_name="initial_bounds")

    @model_validator(mode="after")
    def validate_layer_refs(self) -> Self:
        seen: set[object] = set()
        for layer in self.layers:
            _validate_ref(
                layer,
                artifact_type="geo.map_layer",
                schema_version=1,
                field_name="map document layer",
            )
            if layer.artifact_id in seen:
                raise ValueError("Geo map document layer references must be unique")
            seen.add(layer.artifact_id)
        return self


class VectorProjectionMetadata(GeoVectorProjectionMetadata):
    kind: Literal["pmtiles"] = "pmtiles"
    content_type: Literal["application/vnd.pmtiles"] = "application/vnd.pmtiles"
    bounds: Bounds | None

    @field_validator("bounds")
    @classmethod
    def validate_bounds(cls, value: Bounds | None) -> Bounds | None:
        return _validated_bounds(value, field_name="vector projection bounds")


class RasterProjectionMetadata(GeoRasterProjectionMetadata):
    kind: Literal["xyz"] = "xyz"
    extension: Literal["png"] = "png"
    content_type: Literal["image/png"] = "image/png"
    tile_size: Literal[256] = 256
    bounds: Bounds

    @field_validator("bounds")
    @classmethod
    def validate_bounds(cls, value: Bounds) -> Bounds:
        validated = _validated_bounds(value, field_name="raster projection bounds")
        if validated is None:
            raise ValueError("raster projection bounds are required")
        return validated


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


def _bounds(coordinates: list[tuple[float, float]]) -> Bounds | None:
    if not coordinates:
        return None
    longitudes = [position[0] for position in coordinates]
    latitudes = [position[1] for position in coordinates]
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


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

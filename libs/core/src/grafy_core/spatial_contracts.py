"""Producer-neutral stored spatial payloads shared by API readers and GIS writers."""

import json
from typing import Annotated, Literal, Self

from pydantic import (
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

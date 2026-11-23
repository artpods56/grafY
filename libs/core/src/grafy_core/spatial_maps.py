"""Map source and document composition: layers, sources, and basemaps."""

from typing import Annotated, Literal, Self

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from grafy_core.artifacts import ArtifactRef
from grafy_core.egress import validated_public_destination
from grafy_core.spatial_bounds import Bounds, validated_bounds
from grafy_core.spatial_styles import GeoLayerStyle

WmsVersion = Literal["1.1.1", "1.3.0"]


WmsImageFormat = Literal["image/png", "image/jpeg"]


BasemapKind = Literal["openstreetmap", "none"]


MAX_RASTER_MOSAIC_SOURCES = 64
RASTER_SOURCE_ARTIFACT_TYPES = ("file.tiff",)


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
    """One georeferenced TIFF read on demand by the tiler.

    The ``raster_scan`` discriminator is the stored name of this source shape in
    geo.map_layer payloads; the retired geo.raster_scan artifact type is gone and
    only file.tiff@1 satisfies it.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["raster_scan"] = "raster_scan"
    artifact: ArtifactRef

    @model_validator(mode="after")
    def validate_artifact(self) -> Self:
        ref = self.artifact
        if (
            ref.artifact_type not in RASTER_SOURCE_ARTIFACT_TYPES
            or ref.schema_version != 1
        ):
            raise ValueError(
                "raster source artifact must reference file.tiff@1, got "
                f"{ref.artifact_type}@{ref.schema_version}"
            )
        return self


class GeoRasterMosaicSource(BaseModel):
    """Georeferenced rasters stacked bottom to top and composited by the tiler."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["raster_mosaic"] = "raster_mosaic"
    artifacts: list[ArtifactRef] = Field(
        min_length=1, max_length=MAX_RASTER_MOSAIC_SOURCES
    )

    @model_validator(mode="after")
    def validate_artifacts(self) -> Self:
        seen: set[object] = set()
        for artifact in self.artifacts:
            if (
                artifact.artifact_type not in RASTER_SOURCE_ARTIFACT_TYPES
                or artifact.schema_version != 1
            ):
                raise ValueError(
                    "raster mosaic source artifact must reference file.tiff@1, "
                    f"got {artifact.artifact_type}@{artifact.schema_version}"
                )
            if artifact.artifact_id in seen:
                raise ValueError(
                    "Raster mosaic source artifact references must be unique"
                )
            seen.add(artifact.artifact_id)
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
        validated = validated_bounds(value, field_name="WMS bounds")
        if validated is None:
            raise ValueError("WMS bounds are required")
        return validated

    @model_validator(mode="after")
    def reject_non_public_endpoint(self) -> Self:
        validated_public_destination(self.url, service_name="WMS")
        return self


GeoLayerSource = Annotated[
    GeoFeatureArtifactSource
    | GeoRasterArtifactSource
    | GeoRasterMosaicSource
    | GeoWmsSource,
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
        if (
            self.source.kind in {"raster_scan", "raster_mosaic", "wms"}
            and self.style.kind != "raster"
        ):
            raise ValueError(
                "Raster, raster mosaic and WMS sources require raster style"
            )
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
        return validated_bounds(value, field_name="initial_bounds")

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

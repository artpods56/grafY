"""GIS producer input and compatibility imports for shared spatial contracts."""

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBytes,
    StrictStr,
    field_validator,
)

from grafy_core.spatial_contracts import (
    BasemapKind as BasemapKind,
    Bounds as Bounds,
    GeoCategorizedPointStyle as GeoCategorizedPointStyle,
    GeoCategoryValue as GeoCategoryValue,
    GeoFeatureArtifactSource as GeoFeatureArtifactSource,
    GeoFeatureCollection as GeoFeatureCollection,
    GeoFeatureCollectionPayload as GeoFeatureCollectionPayload,
    GeoFeatureStyle as GeoFeatureStyle,
    GeoFillStyle as GeoFillStyle,
    GeoLabelStyle as GeoLabelStyle,
    GeoLayerSource as GeoLayerSource,
    GeoLayerStyle as GeoLayerStyle,
    GeoLineStyle as GeoLineStyle,
    GeoMapDocument as GeoMapDocument,
    GeoMapLayer as GeoMapLayer,
    GeoPointCategory as GeoPointCategory,
    GeoPointStyle as GeoPointStyle,
    GeoRasterArtifactSource as GeoRasterArtifactSource,
    GeoRasterProjectionMetadata as GeoRasterProjectionMetadata,
    GeoRasterStyle as GeoRasterStyle,
    GeoVectorProjectionMetadata as GeoVectorProjectionMetadata,
    GeoVectorStyle as GeoVectorStyle,
    GeoWmsSource as GeoWmsSource,
    HexColor as HexColor,
    RasterProjectionMetadata as RasterProjectionMetadata,
    RasterResampling as RasterResampling,
    VectorProjectionMetadata as VectorProjectionMetadata,
    WmsImageFormat as WmsImageFormat,
    WmsVersion as WmsVersion,
    validated_public_service_url as validated_public_service_url,
)


class GeoRasterScan(BaseModel):
    """A georeferenced GeoTIFF upload normalized to COG during persistence."""

    model_config = ConfigDict(extra="forbid")

    content: StrictBytes = Field(min_length=1)
    filename: StrictStr = Field(min_length=1, max_length=1_024)
    source_name: StrictStr = Field(min_length=1, max_length=1_024)

    @field_validator("filename", "source_name")
    @classmethod
    def validate_non_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("values must not have surrounding whitespace")
        return value

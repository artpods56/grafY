from typing import cast

from grafy_core.artifacts import (
    ArtifactBundleContract,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
)

from grafy_core.spatial_contracts import (
    GeoMapDocument,
    GeoMapLayer,
)


GEO_FEATURE_COLLECTION = ArtifactTypeSpec(
    key=ArtifactTypeKey("geo.feature_collection", 1),
    title="GeoJSON feature collection",
    bundle=ArtifactBundleContract(format="object-set", version=1),
)

GEO_RASTER_SCAN = ArtifactTypeSpec(
    key=ArtifactTypeKey("geo.raster_scan", 1),
    title="Georeferenced raster scan",
    bundle=ArtifactBundleContract(format="object-set", version=1),
)

GEO_MAP_LAYER = ArtifactTypeSpec(
    key=ArtifactTypeKey("geo.map_layer", 1),
    title="Map layer",
    payload_schema=cast(JsonObject, GeoMapLayer.model_json_schema()),
)

GEO_MAP_DOCUMENT = ArtifactTypeSpec(
    key=ArtifactTypeKey("geo.map_document", 1),
    title="Map document",
    payload_schema=cast(JsonObject, GeoMapDocument.model_json_schema()),
)

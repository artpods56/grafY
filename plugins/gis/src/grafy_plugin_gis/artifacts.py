from typing import cast

from grafy_core.artifacts import (
    ArtifactBundleContract,
    ArtifactPreviewKind,
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
    preview_kind=ArtifactPreviewKind.MAP,
)

GEO_MAP_LAYER = ArtifactTypeSpec(
    key=ArtifactTypeKey("geo.map_layer", 1),
    title="Map layer",
    payload_schema=cast(JsonObject, GeoMapLayer.model_json_schema()),
    preview_kind=ArtifactPreviewKind.MAP,
)

GEO_MAP_DOCUMENT = ArtifactTypeSpec(
    key=ArtifactTypeKey("geo.map_document", 1),
    title="Map document",
    payload_schema=cast(JsonObject, GeoMapDocument.model_json_schema()),
    preview_kind=ArtifactPreviewKind.MAP,
)

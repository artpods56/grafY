from grafy_core.runtime.artifact_values import inline_model_artifact
from grafy_core.spatial_contracts import GeoMapDocument, GeoMapLayer

from grafy_plugin_gis import (  # noqa: F401
    nodes,  # registers the gis.* operators on GIS
)
from grafy_plugin_gis.artifacts import GEO_MAP_DOCUMENT, GEO_MAP_LAYER
from grafy_plugin_gis.declaration import GIS
from grafy_plugin_gis.persistence import (
    feature_collection_artifact,
    raster_scan_artifact,
)


GIS.register(feature_collection_artifact())
GIS.register(raster_scan_artifact())
GIS.register(inline_model_artifact(GEO_MAP_LAYER, GeoMapLayer))
GIS.register(inline_model_artifact(GEO_MAP_DOCUMENT, GeoMapDocument))


__all__ = ["GIS"]

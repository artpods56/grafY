from grafy_core.runtime.artifact_values import inline_model_artifact
from grafy_core.spatial_contracts import GeoMapDocument, GeoMapLayer

from grafy_plugin_gis import (  # noqa: F401
    nodes,  # registers the gis.* operators on GIS
)
from grafy_plugin_gis.artifacts import (
    GEO_FEATURE_COLLECTION,
    GEO_MAP_DOCUMENT,
    GEO_MAP_LAYER,
    GEO_RASTER_SCAN,
)
from grafy_plugin_gis.declaration import GIS
from grafy_plugin_gis.persistence import (
    FeatureCollectionOutputWriter,
    FeatureCollectionResolver,
    RasterScanOutputWriter,
    RasterScanResolver,
)


GIS.register_artifact_type(GEO_FEATURE_COLLECTION)
GIS.register_resolver(
    lambda context: FeatureCollectionResolver(uow=context.uow, storage=context.storage)
)
GIS.register_writer(
    lambda context: FeatureCollectionOutputWriter(
        storage=context.storage,
        uow=context.uow,
        bucket=context.bucket,
        storage_backend=context.storage_backend,
    )
)
GIS.register_artifact_type(GEO_RASTER_SCAN)
GIS.register_resolver(
    lambda context: RasterScanResolver(uow=context.uow, storage=context.storage)
)
GIS.register_writer(
    lambda context: RasterScanOutputWriter(
        storage=context.storage,
        uow=context.uow,
        bucket=context.bucket,
        storage_backend=context.storage_backend,
    )
)
GIS.register(inline_model_artifact(GEO_MAP_LAYER, GeoMapLayer))
GIS.register(inline_model_artifact(GEO_MAP_DOCUMENT, GeoMapDocument))


__all__ = ["GIS"]

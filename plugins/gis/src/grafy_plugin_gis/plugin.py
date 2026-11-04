from grafy_core.artifacts import Artifact
from grafy_core.runtime.persistence import (
    InlineModelOutputWriter,
)
from grafy_core.runtime.resolvers import InlineModelResolver

from grafy_plugin_gis import nodes
from grafy_plugin_gis.artifacts import (
    GEO_FEATURE_COLLECTION,
    GEO_MAP_DOCUMENT,
    GEO_MAP_LAYER,
    GEO_RASTER_SCAN,
)
from grafy_plugin_gis.declaration import GIS
from grafy_core.spatial_contracts import GeoMapDocument, GeoMapLayer
from grafy_plugin_gis.persistence import (
    FeatureCollectionOutputWriter,
    FeatureCollectionResolver,
    RasterScanOutputWriter,
    RasterScanResolver,
)


_NODE_MODULES = (nodes,)


GIS.register(
    Artifact(
        spec=GEO_FEATURE_COLLECTION,
        resolver=lambda context: FeatureCollectionResolver(
            uow=context.uow, storage=context.storage
        ),
        writer=lambda context: FeatureCollectionOutputWriter(
            storage=context.storage,
            uow=context.uow,
            bucket=context.bucket,
            storage_backend=context.storage_backend,
        ),
    )
)
GIS.register(
    Artifact(
        spec=GEO_RASTER_SCAN,
        resolver=lambda context: RasterScanResolver(
            uow=context.uow, storage=context.storage
        ),
        writer=lambda context: RasterScanOutputWriter(
            storage=context.storage,
            uow=context.uow,
            bucket=context.bucket,
            storage_backend=context.storage_backend,
        ),
    )
)
GIS.register(
    Artifact(
        spec=GEO_MAP_LAYER,
        resolver=lambda context: InlineModelResolver[GeoMapLayer](
            source=GEO_MAP_LAYER.key, target=GeoMapLayer, uow=context.uow
        ),
        writer=lambda context: InlineModelOutputWriter(
            artifact_type=GEO_MAP_LAYER.key, model=GeoMapLayer, uow=context.uow
        ),
    )
)
GIS.register(
    Artifact(
        spec=GEO_MAP_DOCUMENT,
        resolver=lambda context: InlineModelResolver[GeoMapDocument](
            source=GEO_MAP_DOCUMENT.key, target=GeoMapDocument, uow=context.uow
        ),
        writer=lambda context: InlineModelOutputWriter(
            artifact_type=GEO_MAP_DOCUMENT.key, model=GeoMapDocument, uow=context.uow
        ),
    )
)


__all__ = ["GIS"]

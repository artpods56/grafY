from collections.abc import Sequence
from hashlib import sha256
from uuid import UUID

from grafy_core.artifact_collections import (
    JSON_COLLECTIONS_STORAGE_FORMAT,
    load_json_collections_page,
)
from grafy_core.artifacts import ArtifactObject
from grafy_core.egress import validated_public_destination
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.spatial_storage import load_feature_collection
from grafy_shared.config.tiler import TilerConfig

from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.services.errors import (
    ArtifactContentUnavailableError,
    WorkbenchOperationError,
)

from grafy_api.artifacts.errors import (
    ArtifactResponseTooLargeError,
    GeoRasterTileNotFoundError,
)
from grafy_api.artifacts.geo import (
    GEO_FEATURE_COLLECTION_ARTIFACT_TYPE,
    GEO_MAP_LAYER_ARTIFACT_TYPE,
    RASTER_SOURCE_TYPES,
    bounds_union,
    feature_count,
    load_mosaic_infos,
    resolve_exact_artifacts,
)
from grafy_api.artifacts.geo_tiff import (
    TIFF_ARTIFACT_TYPE,
    bounds_intersect_tile,
    fit_min_zoom,
    load_geo_tiff,
    require_raster_tiler,
    tiff_title,
)
from grafy_api.artifacts.images import (
    ImageProxyError,
    TiffSource,
    TilerPort,
)
from grafy_api.artifacts.models import (
    GeoExactFeatureResponse,
    GeoFeatureCollectionPayload,
    GeoFeatureManifestMetadata,
    GeoMapLayerPayload,
    GeoRasterTileJsonResponse,
)
from grafy_api.artifacts.wms import GeoTileRead, WmsTileClient


# The browser parses and draws a feature collection whole, so the map only
# takes one it can hold comfortably. Larger collections need tiles.
GEO_FEATURE_DRAW_MAX_BYTES = 16 * 1_024 * 1_024


def _in_xyz_grid(z: int, x: int, y: int) -> bool:
    return 0 <= z <= 24 and 0 <= x < (1 << z) and 0 <= y < (1 << z)


class ArtifactGeoTileService:
    def __init__(
        self,
        uow: UnitOfWorkPort,
        storage: FileStoragePort,
        *,
        availability: ArtifactAvailability,
        wms: WmsTileClient,
        tiler: TilerPort | None = None,
        tiler_config: TilerConfig | None = None,
    ) -> None:
        self._uow = uow
        self._storage = storage
        self._availability = availability
        self._wms = wms
        self._tiler = tiler
        self._tiler_config = tiler_config

    async def get(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactObject | None:
        async with self._uow as uow:
            return await uow.artifacts.get(workspace_id, artifact_id)

    async def load_exact_feature(
        self,
        artifact: ArtifactObject,
        feature_index: int,
    ) -> GeoExactFeatureResponse | None:
        if (
            artifact.artifact_type != GEO_FEATURE_COLLECTION_ARTIFACT_TYPE
            or artifact.schema_version != 1
            or artifact.metadata.get("storage_format")
            != JSON_COLLECTIONS_STORAGE_FORMAT
        ):
            raise WorkbenchOperationError(
                f"Artifact {artifact.id} is not a projected "
                "geo.feature_collection@1 artifact"
            )
        count = feature_count(artifact)
        if feature_index >= count:
            return None
        try:
            page = await load_json_collections_page(
                artifact,
                self._storage,
                offset=feature_index,
                limit=1,
            )
            if len(page.collections) != 1 or page.collections[0].id != "features":
                raise ValueError(
                    "Geo feature collection manifest must contain one "
                    "'features' collection"
                )
            features = page.collections[0].items
            if len(features) != 1 or features[0].get("type") != "Feature":
                raise ValueError(
                    f"Feature collection artifact {artifact.id} has invalid feature "
                    f"at index {feature_index}"
                )
            return GeoExactFeatureResponse(
                source_artifact_id=artifact.id,
                feature_index=feature_index,
                feature=features[0],
            )
        except ArtifactContentUnavailableError:
            raise
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not load feature {feature_index} from artifact {artifact.id}"
            ) from exc

    async def load_feature_geojson(self, artifact: ArtifactObject) -> bytes:
        """The stored features of one collection, as the GeoJSON a map draws."""
        if (
            artifact.artifact_type != GEO_FEATURE_COLLECTION_ARTIFACT_TYPE
            or artifact.schema_version != 1
            or artifact.metadata.get("storage_format")
            != JSON_COLLECTIONS_STORAGE_FORMAT
        ):
            raise WorkbenchOperationError(
                f"Artifact {artifact.id} is not a geo.feature_collection@1 artifact"
            )
        # The stored byte size is the canonical GeoJSON's, so an oversized
        # collection is refused before a chunk is read.
        if (
            artifact.byte_size is not None
            and artifact.byte_size > GEO_FEATURE_DRAW_MAX_BYTES
        ):
            raise ArtifactResponseTooLargeError(
                artifact_id=artifact.id,
                byte_size=artifact.byte_size,
                max_byte_size=GEO_FEATURE_DRAW_MAX_BYTES,
            )
        try:
            loaded = await load_feature_collection(
                artifact,
                self._storage,
                feature_count=feature_count(artifact),
                metadata_type=GeoFeatureManifestMetadata,
                payload_type=GeoFeatureCollectionPayload,
            )
        except ArtifactContentUnavailableError:
            raise
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not load the features of artifact {artifact.id}"
            ) from exc
        return loaded.content

    async def load_raster_tilejson(
        self,
        artifact: ArtifactObject,
        *,
        workspace_id: UUID,
    ) -> GeoRasterTileJsonResponse:
        if artifact.schema_version != 1:
            raise WorkbenchOperationError(
                f"Artifact {artifact.id} is not a supported raster source"
            )
        tile_url = (
            f"/v1/workspaces/{artifact.workspace_id}/artifacts/{artifact.id}"
            "/geo/raster/{z}/{x}/{y}.png"
        )
        if artifact.artifact_type == TIFF_ARTIFACT_TYPE:
            tiler = require_raster_tiler(self._tiler, self._tiler_config)
            info = await load_geo_tiff(artifact, tiler)
            return GeoRasterTileJsonResponse(
                name=tiff_title(artifact),
                tiles=[tile_url],
                bounds=info.bounds,
                minzoom=info.min_zoom,
                maxzoom=info.max_zoom,
            )
        if artifact.artifact_type != GEO_MAP_LAYER_ARTIFACT_TYPE:
            raise WorkbenchOperationError(
                f"Artifact {artifact.id} is not a supported raster source"
            )
        layer = GeoMapLayerPayload.model_validate(artifact.inline_payload)
        if layer.source.kind == "feature_collection":
            raise WorkbenchOperationError(
                f"Map layer artifact {artifact.id} is not a raster layer"
            )
        if layer.source.kind == "raster_mosaic":
            tiler = require_raster_tiler(self._tiler, self._tiler_config)
            infos = await load_mosaic_infos(
                self._availability,
                layer.source.artifacts,
                tiler,
                context=f"Map layer artifact {artifact.id}",
                workspace_id=workspace_id,
            )
            bounds = bounds_union([info.bounds for info in infos])
            assert bounds is not None
            # The union can be wider than any one sheet, so fit it as a whole.
            natural_min_zoom = min(fit_min_zoom(bounds), *(i.min_zoom for i in infos))
            natural_max_zoom = max(info.max_zoom for info in infos)
            minzoom = max(layer.min_zoom, natural_min_zoom)
            return GeoRasterTileJsonResponse(
                name=layer.title,
                tiles=[tile_url],
                bounds=bounds,
                minzoom=minzoom,
                maxzoom=max(minzoom, min(layer.max_zoom, natural_max_zoom)),
            )
        if layer.source.kind == "raster_scan":
            source_artifact = (
                await resolve_exact_artifacts(
                    self._availability,
                    [layer.source.artifact],
                    expected_type=RASTER_SOURCE_TYPES,
                    context=f"Map layer artifact {artifact.id}",
                    workspace_id=workspace_id,
                )
            )[0]
            tiler = require_raster_tiler(self._tiler, self._tiler_config)
            info = await load_geo_tiff(source_artifact, tiler)
            minzoom = max(layer.min_zoom, info.min_zoom)
            return GeoRasterTileJsonResponse(
                name=layer.title,
                tiles=[tile_url],
                bounds=info.bounds,
                minzoom=minzoom,
                maxzoom=max(minzoom, min(layer.max_zoom, info.max_zoom)),
            )
        _ = validated_public_destination(layer.source.url, service_name="WMS")
        return GeoRasterTileJsonResponse(
            name=layer.title,
            tiles=[tile_url],
            bounds=layer.source.bounds,
            minzoom=layer.min_zoom,
            maxzoom=layer.max_zoom,
            attribution=layer.source.attribution,
        )

    async def load_raster_tile(
        self,
        artifact: ArtifactObject,
        *,
        workspace_id: UUID,
        z: int,
        x: int,
        y: int,
    ) -> GeoTileRead | None:
        """Render one XYZ tile from stored sources, on demand."""
        if artifact.schema_version != 1:
            raise WorkbenchOperationError(
                f"Artifact {artifact.id} is not a supported raster source"
            )
        try:
            if artifact.artifact_type == TIFF_ARTIFACT_TYPE:
                tiler = require_raster_tiler(self._tiler, self._tiler_config)
                info = await load_geo_tiff(artifact, tiler)
                return await _render_geo_tile(tiler, info.source, z=z, x=x, y=y)
            if artifact.artifact_type != GEO_MAP_LAYER_ARTIFACT_TYPE:
                raise WorkbenchOperationError(
                    f"Artifact {artifact.id} is not a supported raster source"
                )
            layer = GeoMapLayerPayload.model_validate(artifact.inline_payload)
            if z < layer.min_zoom or z > layer.max_zoom:
                raise GeoRasterTileNotFoundError("Raster tile not found")
            if layer.source.kind == "feature_collection":
                raise WorkbenchOperationError(
                    f"Map layer artifact {artifact.id} is not a raster layer"
                )
            if layer.source.kind == "raster_mosaic":
                if not _in_xyz_grid(z, x, y):
                    return None
                tiler = require_raster_tiler(self._tiler, self._tiler_config)
                infos = await load_mosaic_infos(
                    self._availability,
                    layer.source.artifacts,
                    tiler,
                    context=f"Map layer artifact {artifact.id}",
                    workspace_id=workspace_id,
                )
                overlapping = [
                    info.source
                    for info in infos
                    if bounds_intersect_tile(info.bounds, z=z, x=x, y=y)
                ]
                if not overlapping:
                    return None
                if len(overlapping) == 1:
                    return await _render_geo_tile(tiler, overlapping[0], z=z, x=x, y=y)
                return await _render_geo_mosaic_tile(tiler, overlapping, z=z, x=x, y=y)
            if layer.source.kind == "raster_scan":
                source_artifact = (
                    await resolve_exact_artifacts(
                        self._availability,
                        [layer.source.artifact],
                        expected_type=RASTER_SOURCE_TYPES,
                        context=f"Map layer artifact {artifact.id}",
                        workspace_id=workspace_id,
                    )
                )[0]
                tiler = require_raster_tiler(self._tiler, self._tiler_config)
                info = await load_geo_tiff(source_artifact, tiler)
                return await _render_geo_tile(tiler, info.source, z=z, x=x, y=y)
            if not _in_xyz_grid(z, x, y):
                raise GeoRasterTileNotFoundError("Raster tile not found")
            return await self._wms.fetch_tile(layer.source, z=z, x=x, y=y)
        except (ImageProxyError, WorkbenchOperationError):
            raise
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not load raster tile {z}/{x}/{y} for artifact {artifact.id}"
            ) from exc


async def _render_geo_tile(
    tiler: TilerPort, source: TiffSource, *, z: int, x: int, y: int
) -> GeoTileRead | None:
    if not _in_xyz_grid(z, x, y):
        return None
    try:
        tile = await tiler.geo_tile(source, z=z, x=x, y=y, extension="png")
    except ImageProxyError as exc:
        if exc.status == 404:
            return None
        raise
    return GeoTileRead(
        content=tile.body,
        content_type=tile.content_type,
        etag=f'"{sha256(tile.body).hexdigest()}"',
    )


async def _render_geo_mosaic_tile(
    tiler: TilerPort, sources: Sequence[TiffSource], *, z: int, x: int, y: int
) -> GeoTileRead | None:
    try:
        tile = await tiler.geo_mosaic_tile(sources, z=z, x=x, y=y, extension="png")
    except ImageProxyError as exc:
        if exc.status == 404:
            return None
        raise
    return GeoTileRead(
        content=tile.body,
        content_type=tile.content_type,
        etag=f'"{sha256(tile.body).hexdigest()}"',
    )


__all__ = [
    "ArtifactGeoTileService",
    "GEO_FEATURE_DRAW_MAX_BYTES",
]

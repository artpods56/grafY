from dataclasses import dataclass
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

from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.services.errors import (
    ArtifactContentUnavailableError,
    WorkbenchOperationError,
)

from grafy_api.artifacts.errors import (
    ArtifactResponseTooLargeError,
    GeoRangeNotSatisfiableError,
)
from grafy_api.artifacts.geo import (
    GEO_FEATURE_COLLECTION_ARTIFACT_TYPE,
    GEO_MAP_LAYER_ARTIFACT_TYPE,
    GEO_RASTER_SCAN_ARTIFACT_TYPE,
    feature_count,
    resolve_exact_artifacts,
    source_name,
)
from grafy_api.artifacts.models import (
    GeoExactFeatureResponse,
    GeoMapLayerPayload,
    GeoRasterProjectionMetadata,
    GeoRasterTileJsonResponse,
    GeoVectorProjectionMetadata,
)
from grafy_api.artifacts.wms import GeoTileRead, WmsTileClient


PMTILES_RESPONSE_MAX_BYTES = 16 * 1_024 * 1_024
IMMUTABLE_CACHE_CONTROL = "private, max-age=31536000, immutable"


@dataclass(frozen=True, slots=True)
class GeoArchiveRead:
    content: bytes
    status_code: int
    total_size: int
    start: int
    end_exclusive: int
    etag: str
    content_type: str


def _single_byte_range(value: str, total_size: int) -> tuple[int, int]:
    if not value.startswith("bytes=") or "," in value:
        raise ValueError("Only one bytes range is supported")
    range_value = value.removeprefix("bytes=").strip()
    if "-" not in range_value:
        raise ValueError("Byte range must contain a hyphen")
    start_text, end_text = range_value.split("-", 1)
    if start_text == "":
        if not end_text.isdigit():
            raise ValueError("Byte suffix length must be an integer")
        suffix_length = int(end_text)
        if suffix_length < 1 or total_size == 0:
            raise ValueError("Byte suffix length must be positive")
        start = max(0, total_size - suffix_length)
        return start, total_size
    if not start_text.isdigit():
        raise ValueError("Byte range start must be an integer")
    start = int(start_text)
    if start >= total_size:
        raise ValueError("Byte range starts beyond the stored object")
    if end_text == "":
        return start, total_size
    if not end_text.isdigit():
        raise ValueError("Byte range end must be an integer")
    end_inclusive = int(end_text)
    if end_inclusive < start:
        raise ValueError("Byte range end precedes its start")
    return start, min(total_size, end_inclusive + 1)


class ArtifactGeoTileService:
    def __init__(
        self,
        uow: UnitOfWorkPort,
        storage: FileStoragePort,
        *,
        availability: ArtifactAvailability,
        wms: WmsTileClient,
    ) -> None:
        self._uow = uow
        self._storage = storage
        self._availability = availability
        self._wms = wms

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

    async def load_vector_archive(
        self,
        artifact: ArtifactObject,
        range_header: str | None,
    ) -> GeoArchiveRead:
        if (
            artifact.artifact_type != GEO_FEATURE_COLLECTION_ARTIFACT_TYPE
            or artifact.schema_version != 1
        ):
            raise WorkbenchOperationError(
                f"Artifact {artifact.id} is not a geo.feature_collection@1 artifact"
            )
        projection_value = artifact.metadata.get("vector_projection")
        if projection_value is None and feature_count(artifact) == 0:
            raise WorkbenchOperationError(
                f"Feature collection artifact {artifact.id} is empty and has no "
                "vector projection"
            )
        try:
            projection = GeoVectorProjectionMetadata.model_validate(projection_value)
            info = await self._storage.stat(
                projection.bucket,
                projection.object_key,
            )
            if info is None:
                raise FileNotFoundError(
                    f"Stored PMTiles object does not exist: "
                    f"{projection.bucket}/{projection.object_key}"
                )
            if info.byte_size != projection.byte_size:
                raise ValueError(
                    f"Stored PMTiles object has {info.byte_size} bytes, expected "
                    f"{projection.byte_size}"
                )
            if info.etag is not None:
                etag = info.etag if info.etag.startswith('"') else f'"{info.etag}"'
            else:
                etag = f'"{projection.sha256}"'
            start = 0
            end_exclusive = info.byte_size
            status_code = 200
            if range_header is not None:
                try:
                    start, end_exclusive = _single_byte_range(
                        range_header,
                        info.byte_size,
                    )
                except ValueError as exc:
                    raise GeoRangeNotSatisfiableError(
                        total_size=info.byte_size,
                        etag=etag,
                    ) from exc
                status_code = 206
            response_byte_size = end_exclusive - start
            if response_byte_size > PMTILES_RESPONSE_MAX_BYTES:
                if range_header is not None:
                    raise GeoRangeNotSatisfiableError(
                        total_size=info.byte_size,
                        etag=etag,
                        reason=(
                            f"Requested PMTiles byte range contains "
                            f"{response_byte_size} bytes, exceeding the "
                            f"{PMTILES_RESPONSE_MAX_BYTES}-byte range limit"
                        ),
                    )
                raise ArtifactResponseTooLargeError(
                    artifact_id=artifact.id,
                    byte_size=response_byte_size,
                    max_byte_size=PMTILES_RESPONSE_MAX_BYTES,
                )
            content = await self._storage.load_range(
                projection.bucket,
                projection.object_key,
                start,
                end_exclusive,
            )
            if len(content) != end_exclusive - start:
                raise ValueError(
                    f"Stored PMTiles range returned {len(content)} bytes, expected "
                    f"{end_exclusive - start}"
                )
            if status_code == 200 and sha256(content).hexdigest() != projection.sha256:
                raise ValueError(
                    f"Stored PMTiles object does not match projection SHA-256 "
                    f"for artifact {artifact.id}"
                )
            return GeoArchiveRead(
                content=content,
                status_code=status_code,
                total_size=info.byte_size,
                start=start,
                end_exclusive=end_exclusive,
                etag=etag,
                content_type=projection.content_type,
            )
        except GeoRangeNotSatisfiableError:
            raise
        except WorkbenchOperationError:
            raise
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not load PMTiles projection for artifact {artifact.id}"
            ) from exc

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
        if artifact.artifact_type == GEO_RASTER_SCAN_ARTIFACT_TYPE:
            projection = GeoRasterProjectionMetadata.model_validate(
                artifact.metadata.get("raster_projection")
            )
            return GeoRasterTileJsonResponse(
                name=source_name(artifact),
                tiles=[
                    f"/v1/workspaces/{artifact.workspace_id}/artifacts/{artifact.id}/geo/raster/{{z}}/{{x}}/{{y}}.png"
                ],
                bounds=projection.bounds,
                minzoom=projection.min_zoom,
                maxzoom=projection.max_zoom,
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
        if layer.source.kind == "raster_scan":
            source_artifact = (
                await resolve_exact_artifacts(
                    self._availability,
                    [layer.source.artifact],
                    expected_type=GEO_RASTER_SCAN_ARTIFACT_TYPE,
                    context=f"Map layer artifact {artifact.id}",
                    workspace_id=workspace_id,
                )
            )[0]
            projection = GeoRasterProjectionMetadata.model_validate(
                source_artifact.metadata.get("raster_projection")
            )
            return GeoRasterTileJsonResponse(
                name=layer.title,
                tiles=[
                    f"/v1/workspaces/{artifact.workspace_id}/artifacts/{artifact.id}/geo/raster/{{z}}/{{x}}/{{y}}.png"
                ],
                bounds=projection.bounds,
                minzoom=max(layer.min_zoom, projection.min_zoom),
                maxzoom=min(layer.max_zoom, projection.max_zoom),
            )
        _ = validated_public_destination(layer.source.url, service_name="WMS")
        return GeoRasterTileJsonResponse(
            name=layer.title,
            tiles=[
                f"/v1/workspaces/{artifact.workspace_id}/artifacts/{artifact.id}/geo/raster/{{z}}/{{x}}/{{y}}.png"
            ],
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
        if z < 0 or z > 24 or x < 0 or y < 0 or x >= (1 << z) or y >= (1 << z):
            return None
        try:
            if artifact.artifact_type == GEO_RASTER_SCAN_ARTIFACT_TYPE:
                projection = GeoRasterProjectionMetadata.model_validate(
                    artifact.metadata.get("raster_projection")
                )
            else:
                if artifact.artifact_type != GEO_MAP_LAYER_ARTIFACT_TYPE:
                    raise WorkbenchOperationError(
                        f"Artifact {artifact.id} is not a supported raster source"
                    )
                layer = GeoMapLayerPayload.model_validate(artifact.inline_payload)
                if z < layer.min_zoom or z > layer.max_zoom:
                    return None
                if layer.source.kind == "feature_collection":
                    raise WorkbenchOperationError(
                        f"Map layer artifact {artifact.id} is not a raster layer"
                    )
                if layer.source.kind != "raster_scan":
                    return await self._wms.fetch_tile(layer.source, z=z, x=x, y=y)
                source_artifact = (
                    await resolve_exact_artifacts(
                        self._availability,
                        [layer.source.artifact],
                        expected_type=GEO_RASTER_SCAN_ARTIFACT_TYPE,
                        context=f"Map layer artifact {artifact.id}",
                        workspace_id=workspace_id,
                    )
                )[0]
                projection = GeoRasterProjectionMetadata.model_validate(
                    source_artifact.metadata.get("raster_projection")
                )
            if z < projection.min_zoom or z > projection.max_zoom:
                return None
            object_key = f"{projection.prefix}/{z}/{x}/{y}.{projection.extension}"
            info = await self._storage.stat(projection.bucket, object_key)
            if info is None:
                return None
            content = await self._storage.load_range(
                projection.bucket,
                object_key,
                0,
                info.byte_size,
            )
            if len(content) != info.byte_size:
                raise ValueError(
                    f"Raster tile {projection.bucket}/{object_key} returned "
                    f"{len(content)} bytes, expected {info.byte_size}"
                )
            etag = info.etag
            if etag is None:
                etag = f'"{sha256(content).hexdigest()}"'
            elif not etag.startswith('"'):
                etag = f'"{etag}"'
            return GeoTileRead(
                content=content,
                content_type=projection.content_type,
                etag=etag,
            )
        except (ArtifactContentUnavailableError, WorkbenchOperationError):
            raise
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not load raster tile {z}/{x}/{y} for artifact {artifact.id}"
            ) from exc


__all__ = [
    "ArtifactGeoTileService",
    "GeoArchiveRead",
    "IMMUTABLE_CACHE_CONTROL",
    "PMTILES_RESPONSE_MAX_BYTES",
]

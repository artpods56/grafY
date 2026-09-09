import asyncio
import ipaddress
import json
import re
import socket
import ssl
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import cast
from uuid import UUID

import httpx
import truststore

from grafy_core.artifact_collections import (
    JSON_COLLECTIONS_STORAGE_FORMAT,
    load_json_collections_page,
)
from grafy_core.artifacts import (
    ArtifactExportFormat,
    ArtifactObject,
    ArtifactRef,
    ArtifactTypeSpec,
    UnitOfWorkPort,
)
from grafy_core.table_contracts import (
    TABLE_DATA,
    TablePage,
    TableValue,
)
from grafy_core.runtime.table_storage import (
    iter_table_csv,
    load_table_artifact,
    load_table_page,
)
from grafy_core.ports.storage import (
    FileStoragePort,
    FileStreamProtocol,
    StoredObjectInfo,
)

from grafy_api.artifact_availability import ArtifactAvailability, ArtifactReferenceError

from grafy_api.services.errors import (
    ArtifactContentUnavailableError,
    WorkbenchOperationError,
)

from .models import (
    ArtifactExactMatchRow,
    GeoArtifactRefPayload,
    GeoBounds,
    GeoCategorizedPointStyle,
    GeoExactFeatureResponse,
    GeoFeatureCollectionPayload,
    GeoFeatureQueryResponse,
    GeoFeatureManifestMetadata,
    GeoMapDocumentPayload,
    GeoMapLayerPayload,
    GeoPropertyFieldResponse,
    GeoRasterProjectionMetadata,
    GeoRasterRenderSourceResponse,
    GeoRasterStyle,
    GeoRasterTileJsonResponse,
    GeoRenderLayerResponse,
    GeoRenderResponse,
    GeoVectorProjectionMetadata,
    GeoVectorRenderSourceResponse,
    GeoVectorStyle,
    GeoWmsSourcePayload,
    TableExactMatchGroup,
)


GEO_FEATURE_COLLECTION_ARTIFACT_TYPE = "geo.feature_collection"
GEO_RASTER_SCAN_ARTIFACT_TYPE = "geo.raster_scan"
GEO_MAP_LAYER_ARTIFACT_TYPE = "geo.map_layer"
GEO_MAP_DOCUMENT_ARTIFACT_TYPE = "geo.map_document"
WMS_RESPONSE_BYTE_BUDGET = 5 * 1_024 * 1_024
ARTIFACT_RESPONSE_CHUNK_SIZE = 1 * 1_024 * 1_024
BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES = 64 * 1_024 * 1_024
PMTILES_RESPONSE_MAX_BYTES = 16 * 1_024 * 1_024
IMMUTABLE_CACHE_CONTROL = "private, max-age=31536000, immutable"
TABLE_INTERACTION_ROW_LIMIT = 250_000
GEO_INTERACTION_FEATURE_LIMIT = 250_000


@dataclass(frozen=True, slots=True)
class GeoArchiveRead:
    content: bytes
    status_code: int
    total_size: int
    start: int
    end_exclusive: int
    etag: str
    content_type: str


@dataclass(frozen=True, slots=True)
class GeoTileRead:
    content: bytes
    content_type: str
    etag: str | None


@dataclass(frozen=True, slots=True)
class ArtifactContentRead:
    body: bytes | FileStreamProtocol | Callable[[], AsyncIterator[bytes]]
    content_length: int | None

    async def chunks(self) -> AsyncIterator[bytes]:
        body = self.body
        if isinstance(body, bytes):
            if body:
                yield body
            return
        if isinstance(body, Callable):
            async for chunk in body():
                if chunk:
                    yield chunk
            return
        try:
            while chunk := await asyncio.to_thread(
                body.read,
                ARTIFACT_RESPONSE_CHUNK_SIZE,
            ):
                yield chunk
        finally:
            await asyncio.to_thread(body.close)


@dataclass(frozen=True, slots=True)
class TableQueryPage:
    page: TablePage
    row_indices: list[int]
    highlighted_row_indices: list[int]


_CANONICAL_INTEGER = re.compile(r"^-?(0|[1-9]\d*)$")


def _interaction_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _CANONICAL_INTEGER.fullmatch(value):
        return int(value)
    return None


def _interaction_values_equal(left: object, right: object) -> bool:
    if type(left) is type(right):
        return left == right
    left_int = _interaction_int(left)
    right_int = _interaction_int(right)
    return left_int is not None and left_int == right_int


def _table_row_matches_group(
    row: dict[str, TableValue],
    group: TableExactMatchGroup,
) -> bool:
    return any(
        all(
            _interaction_values_equal(row[field_name], expected)
            for field_name, expected in candidate.values.items()
        )
        for candidate in group.rows
    )


def _geo_feature_matches(
    feature: dict[str, object],
    candidate: ArtifactExactMatchRow,
) -> bool:
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        return False
    typed_properties = cast(dict[str, object], properties)
    return all(
        field_name in typed_properties
        and _interaction_values_equal(typed_properties[field_name], expected)
        for field_name, expected in candidate.values.items()
    )


def _coordinate_bounds(coordinates: object) -> GeoBounds | None:
    if not isinstance(coordinates, list):
        return None
    values = cast(list[object], coordinates)
    if (
        len(values) >= 2
        and isinstance(values[0], int | float)
        and not isinstance(values[0], bool)
        and isinstance(values[1], int | float)
        and not isinstance(values[1], bool)
    ):
        longitude = float(values[0])
        latitude = float(values[1])
        return (longitude, latitude, longitude, latitude)
    nested = [
        bounds for value in values if (bounds := _coordinate_bounds(value)) is not None
    ]
    return _bounds_union(nested)


def _geometry_bounds(geometry: object) -> GeoBounds | None:
    if not isinstance(geometry, dict):
        return None
    typed_geometry = cast(dict[str, object], geometry)
    if typed_geometry.get("type") == "GeometryCollection":
        geometries = typed_geometry.get("geometries")
        if not isinstance(geometries, list):
            return None
        typed_geometries = cast(list[object], geometries)
        return _bounds_union(
            [
                bounds
                for value in typed_geometries
                if (bounds := _geometry_bounds(value)) is not None
            ]
        )
    return _coordinate_bounds(typed_geometry.get("coordinates"))


class GeoRangeNotSatisfiableError(ValueError):
    def __init__(
        self,
        *,
        total_size: int,
        etag: str,
        reason: str | None = None,
    ) -> None:
        super().__init__(
            reason or f"Requested byte range is not satisfiable for {total_size} bytes"
        )
        self.total_size = total_size
        self.etag = etag


class ArtifactResponseTooLargeError(WorkbenchOperationError):
    def __init__(
        self,
        *,
        artifact_id: UUID,
        byte_size: int,
        max_byte_size: int,
    ) -> None:
        super().__init__(
            f"Artifact {artifact_id} requires a {byte_size}-byte buffered "
            f"response, exceeding the {max_byte_size}-byte response limit"
        )
        self.byte_size = byte_size
        self.max_byte_size = max_byte_size


def _verify_artifact_content(artifact: ArtifactObject, content: bytes) -> None:
    if artifact.byte_size is not None and len(content) != artifact.byte_size:
        raise ValueError(
            f"Artifact {artifact.id} contains {len(content)} bytes, expected "
            f"{artifact.byte_size}"
        )
    if artifact.sha256 is not None:
        observed_sha256 = sha256(content).hexdigest()
        if observed_sha256 != artifact.sha256:
            raise ValueError(
                f"Artifact {artifact.id} has SHA-256 {observed_sha256}, "
                f"expected {artifact.sha256}"
            )


def _etag(info: StoredObjectInfo, fallback_sha256: str) -> str:
    if info.etag is not None:
        return info.etag if info.etag.startswith('"') else f'"{info.etag}"'
    return f'"{fallback_sha256}"'


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


def _bounds_union(
    bounds_values: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float] | None:
    if not bounds_values:
        return None
    return (
        min(bounds[0] for bounds in bounds_values),
        min(bounds[1] for bounds in bounds_values),
        max(bounds[2] for bounds in bounds_values),
        max(bounds[3] for bounds in bounds_values),
    )


def _valid_tile_coordinates(z: int, x: int, y: int) -> bool:
    if z < 0 or z > 24 or x < 0 or y < 0:
        return False
    dimension = 1 << z
    return x < dimension and y < dimension


def _web_mercator_tile_bounds(
    z: int, x: int, y: int
) -> tuple[float, float, float, float]:
    extent = 20_037_508.342789244
    span = extent * 2 / (1 << z)
    west = -extent + x * span
    east = west + span
    north = extent - y * span
    south = north - span
    return west, south, east, north


def _validate_public_wms_url(source: GeoWmsSourcePayload) -> None:
    host = source.url.host
    if host is None:
        raise ValueError("WMS URL does not have a host")
    normalized_host = host.rstrip(".").lower()
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        raise ValueError("WMS URL must not target localhost")
    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        return
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        raise ValueError("WMS URL must target a public address")


class ArtifactService:
    """Loads persisted artifacts for HTTP content, table, and spatial views."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkPort,
        storage: FileStoragePort,
        artifact_types: Mapping[tuple[str, int], ArtifactTypeSpec] | None = None,
        *,
        availability: ArtifactAvailability,
    ) -> None:
        self._availability = availability
        self._unit_of_work = unit_of_work
        self._storage = storage
        self._artifact_types = artifact_types or {}
        self._wms_client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
            http2=False,
            trust_env=False,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        )

    def export_formats(self, artifact: ArtifactObject) -> list[ArtifactExportFormat]:
        """Formats this artifact can be downloaded as.

        `json` is available for any JSON-representable artifact (inline payload
        or `application/json` content); additional formats come from the type's
        `export_formats` declaration.
        """

        formats: list[ArtifactExportFormat] = []
        if self._artifact_is_json(artifact):
            formats.append(
                ArtifactExportFormat(
                    format="json",
                    content_type="application/json",
                    filename="artifact.json",
                )
            )
        spec = self._artifact_types.get(
            (artifact.artifact_type, artifact.schema_version)
        )
        if spec is not None:
            formats.extend(spec.export_formats)
        return formats

    def _artifact_is_json(self, artifact: ArtifactObject) -> bool:
        if artifact.inline_payload is not None:
            return True
        return artifact.content_type == "application/json"

    async def close(self) -> None:
        await self._wms_client.aclose()

    async def get(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactObject | None:
        async with self._unit_of_work as unit_of_work:
            return await unit_of_work.artifacts.get(workspace_id, artifact_id)

    async def load_content(self, artifact: ArtifactObject) -> bytes:
        if (
            artifact.artifact_type == TABLE_DATA.key.id
            and artifact.schema_version == TABLE_DATA.key.schema_version
        ):
            try:
                table = await load_table_artifact(artifact, self._storage)
            except Exception as exc:
                raise ArtifactContentUnavailableError(
                    f"Could not load complete table artifact {artifact.id}"
                ) from exc
            return table.model_dump_json().encode("utf-8")
        if (
            artifact.artifact_type == GEO_FEATURE_COLLECTION_ARTIFACT_TYPE
            and artifact.schema_version == 1
            and artifact.metadata.get("storage_format")
            == JSON_COLLECTIONS_STORAGE_FORMAT
        ):
            feature_count = self._feature_count(artifact)
            try:
                page = await load_json_collections_page(
                    artifact,
                    self._storage,
                    offset=0,
                    limit=max(1, feature_count),
                )
                metadata = GeoFeatureManifestMetadata.model_validate(page.metadata)
                if len(page.collections) != 1 or page.collections[0].id != "features":
                    raise ValueError(
                        "Geo feature collection manifest must contain one "
                        "'features' collection"
                    )
                collection = page.collections[0]
                if len(collection.items) != collection.total_items:
                    raise ValueError("Geo feature collection page is incomplete")
                payload = GeoFeatureCollectionPayload(
                    features=collection.items,
                    source_name=metadata.source_name,
                    bounds=metadata.bounds,
                )
                content = json.dumps(
                    payload.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                _verify_artifact_content(artifact, content)
                return content
            except ArtifactContentUnavailableError:
                raise
            except Exception as exc:
                raise ArtifactContentUnavailableError(
                    f"Could not reconstruct complete feature artifact {artifact.id}"
                ) from exc
        return await self._load_stored_content(artifact)

    async def open_content(self, artifact: ArtifactObject) -> ArtifactContentRead:
        streams_stored_payload_directly = (
            artifact.inline_payload is None
            and not (
                artifact.artifact_type == TABLE_DATA.key.id
                and artifact.schema_version == TABLE_DATA.key.schema_version
            )
            and not (
                artifact.artifact_type == GEO_FEATURE_COLLECTION_ARTIFACT_TYPE
                and artifact.schema_version == 1
                and artifact.metadata.get("storage_format")
                == JSON_COLLECTIONS_STORAGE_FORMAT
            )
        )
        if streams_stored_payload_directly:
            if artifact.bucket is None or artifact.object_key is None:
                raise ArtifactContentUnavailableError(
                    f"Artifact {artifact.id} has no stored payload"
                )
            try:
                stored = await self._storage.stat(
                    bucket=artifact.bucket,
                    path=artifact.object_key,
                )
            except Exception as exc:
                raise ArtifactContentUnavailableError(
                    f"Could not inspect artifact {artifact.id} at "
                    f"{artifact.bucket}/{artifact.object_key}"
                ) from exc
            if stored is None:
                raise ArtifactContentUnavailableError(
                    f"Artifact {artifact.id} is missing from "
                    f"{artifact.bucket}/{artifact.object_key}"
                )
            if (
                artifact.byte_size is not None
                and stored.byte_size != artifact.byte_size
            ):
                raise ArtifactContentUnavailableError(
                    f"Artifact {artifact.id} contains {stored.byte_size} bytes, "
                    f"expected {artifact.byte_size}"
                )
            return ArtifactContentRead(
                body=await self._open_stored_content(artifact),
                content_length=stored.byte_size,
            )
        if (
            artifact.byte_size is not None
            and artifact.byte_size > BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES
        ):
            raise ArtifactResponseTooLargeError(
                artifact_id=artifact.id,
                byte_size=artifact.byte_size,
                max_byte_size=BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES,
            )
        content = await self.load_content(artifact)
        if len(content) > BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES:
            raise ArtifactResponseTooLargeError(
                artifact_id=artifact.id,
                byte_size=len(content),
                max_byte_size=BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES,
            )
        return ArtifactContentRead(body=content, content_length=len(content))

    async def load_download(
        self,
        artifact: ArtifactObject,
        format: str,
    ) -> tuple[ArtifactContentRead, str]:
        """Render the artifact into a download format.

        Returns a chunked content read and its content type. Raises
        `WorkbenchOperationError` for an unsupported format and
        `ArtifactContentUnavailableError` when content cannot be opened.
        """

        supported = [entry.format for entry in self.export_formats(artifact)]
        if format not in supported:
            raise WorkbenchOperationError(
                f"Artifact {artifact.id} does not support download format "
                f"{format!r}; supported: {supported or 'none'}"
            )
        if format == "json":
            return await self.open_content(artifact), "application/json"
        if format == "txt":
            if (
                artifact.byte_size is not None
                and artifact.byte_size > BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES
            ):
                raise ArtifactResponseTooLargeError(
                    artifact_id=artifact.id,
                    byte_size=artifact.byte_size,
                    max_byte_size=BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES,
                )
            text = self._text_value(artifact)
            if text is None:
                raise WorkbenchOperationError(
                    f"Artifact {artifact.id} cannot be downloaded as bare text"
                )
            content = text.encode("utf-8")
            if len(content) > BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES:
                raise ArtifactResponseTooLargeError(
                    artifact_id=artifact.id,
                    byte_size=len(content),
                    max_byte_size=BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES,
                )
            return (
                ArtifactContentRead(body=content, content_length=len(content)),
                "text/plain; charset=utf-8",
            )
        if format == "csv":
            if (
                artifact.artifact_type != TABLE_DATA.key.id
                or artifact.schema_version != TABLE_DATA.key.schema_version
            ):
                raise WorkbenchOperationError(
                    f"Artifact {artifact.id} is not a table.data@1 artifact"
                )
            return (
                ArtifactContentRead(
                    body=lambda: iter_table_csv(artifact, self._storage),
                    content_length=None,
                ),
                "text/csv; charset=utf-8",
            )
        raise WorkbenchOperationError(
            f"Artifact {artifact.id} does not support download format {format!r}"
        )

    def _text_value(self, artifact: ArtifactObject) -> str | None:
        if artifact.inline_payload is None:
            return None
        payload = artifact.inline_payload
        if isinstance(payload.get("value"), str):
            return cast(str, payload["value"])
        if isinstance(payload.get("markdown"), str):
            return cast(str, payload["markdown"])
        return None

    async def _load_stored_content(self, artifact: ArtifactObject) -> bytes:
        if artifact.inline_payload is not None:
            return (
                json.dumps(
                    artifact.inline_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            ).encode("utf-8")
        stream = await self._open_stored_content(artifact)
        try:
            return stream.read()
        finally:
            stream.close()

    async def _open_stored_content(
        self,
        artifact: ArtifactObject,
    ) -> FileStreamProtocol:
        if artifact.bucket is None or artifact.object_key is None:
            raise ArtifactContentUnavailableError(
                f"Artifact {artifact.id} has no stored payload"
            )
        try:
            return await self._storage.load(
                bucket=artifact.bucket,
                path=artifact.object_key,
            )
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not load artifact {artifact.id} from "
                f"{artifact.bucket}/{artifact.object_key}"
            ) from exc

    def _feature_count(self, artifact: ArtifactObject) -> int:
        feature_count = artifact.metadata.get("feature_count")
        if (
            not isinstance(feature_count, int)
            or isinstance(feature_count, bool)
            or feature_count < 0
        ):
            raise ArtifactContentUnavailableError(
                f"Feature collection artifact {artifact.id} has invalid "
                "feature_count metadata"
            )
        return feature_count

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
        feature_count = self._feature_count(artifact)
        if feature_index >= feature_count:
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

    async def query_geo_features(
        self,
        artifact: ArtifactObject,
        rows: list[ArtifactExactMatchRow],
        *,
        workspace_id: UUID,
    ) -> GeoFeatureQueryResponse:
        descriptor = await self.load_geo_render(artifact, workspace_id=workspace_id)
        source_ids = list(
            dict.fromkeys(
                layer.source.artifact_id
                for layer in descriptor.layers
                if layer.source.kind == "vector"
            )
        )
        if not source_ids:
            return GeoFeatureQueryResponse(
                artifact_id=artifact.id,
                bounds=None,
                matched_feature_count=0,
                source_artifact_ids=[],
            )
        async with self._unit_of_work as unit_of_work:
            source_artifacts = await unit_of_work.artifacts.get_many(
                workspace_id,
                source_ids,
            )
        total_features = 0
        ordered_sources: list[ArtifactObject] = []
        for source_id in source_ids:
            source_artifact = source_artifacts.get(source_id)
            if (
                source_artifact is None
                or source_artifact.artifact_type != GEO_FEATURE_COLLECTION_ARTIFACT_TYPE
                or source_artifact.schema_version != 1
            ):
                raise ArtifactContentUnavailableError(
                    f"Geo render artifact {artifact.id} references invalid "
                    f"feature source {source_id}"
                )
            total_features += self._feature_count(source_artifact)
            ordered_sources.append(source_artifact)
        if total_features > GEO_INTERACTION_FEATURE_LIMIT:
            raise WorkbenchOperationError(
                f"Linked map focus supports at most "
                f"{GEO_INTERACTION_FEATURE_LIMIT} source features; artifact "
                f"{artifact.id} resolves to {total_features}"
            )

        matched_bounds: list[GeoBounds] = []
        matched_feature_count = 0
        try:
            for source_artifact in ordered_sources:
                feature_count = self._feature_count(source_artifact)
                page = await load_json_collections_page(
                    source_artifact,
                    self._storage,
                    offset=0,
                    limit=max(1, feature_count),
                )
                if len(page.collections) != 1 or page.collections[0].id != "features":
                    raise ValueError(
                        "Geo feature collection manifest must contain one "
                        "'features' collection"
                    )
                for feature in page.collections[0].items:
                    if not any(_geo_feature_matches(feature, row) for row in rows):
                        continue
                    matched_feature_count += 1
                    bounds = _geometry_bounds(feature.get("geometry"))
                    if bounds is not None:
                        matched_bounds.append(bounds)
        except (ArtifactContentUnavailableError, WorkbenchOperationError):
            raise
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not query linked features for geo artifact {artifact.id}"
            ) from exc
        return GeoFeatureQueryResponse(
            artifact_id=artifact.id,
            bounds=_bounds_union(matched_bounds),
            matched_feature_count=matched_feature_count,
            source_artifact_ids=source_ids,
        )

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
        if projection_value is None and self._feature_count(artifact) == 0:
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
            etag = _etag(info, projection.sha256)
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

    async def load_geo_render(
        self,
        artifact: ArtifactObject,
        *,
        workspace_id: UUID,
    ) -> GeoRenderResponse:
        if artifact.schema_version != 1:
            raise WorkbenchOperationError(
                f"Artifact {artifact.id} is not a supported geo artifact"
            )
        try:
            if artifact.artifact_type == GEO_FEATURE_COLLECTION_ARTIFACT_TYPE:
                layer = self._feature_render_layer(
                    artifact,
                    layer_id=str(artifact.id),
                    title=self._source_name(artifact),
                    visible=True,
                    opacity=1.0,
                    min_zoom=0,
                    max_zoom=22,
                    style=GeoVectorStyle.default(),
                )
                layers = [] if layer is None else [layer]
                return GeoRenderResponse(
                    artifact_id=artifact.id,
                    kind="feature_collection",
                    basemap="openstreetmap",
                    initial_bounds=None if layer is None else layer.source.bounds,
                    layers=layers,
                )
            if artifact.artifact_type == GEO_RASTER_SCAN_ARTIFACT_TYPE:
                layer = self._raster_render_layer(
                    artifact,
                    layer_id=str(artifact.id),
                    title=self._source_name(artifact),
                    visible=True,
                    opacity=1.0,
                    min_zoom=0,
                    max_zoom=22,
                    style=GeoRasterStyle.default(),
                )
                return GeoRenderResponse(
                    artifact_id=artifact.id,
                    kind="raster_scan",
                    basemap="openstreetmap",
                    initial_bounds=layer.source.bounds,
                    layers=[layer],
                )
            if artifact.artifact_type == GEO_MAP_LAYER_ARTIFACT_TYPE:
                layer = await self._resolve_render_layer(
                    artifact,
                    workspace_id=workspace_id,
                )
                layers = [] if layer is None else [layer]
                return GeoRenderResponse(
                    artifact_id=artifact.id,
                    kind="map_layer",
                    basemap="openstreetmap",
                    initial_bounds=None if layer is None else layer.source.bounds,
                    layers=layers,
                )
            if artifact.artifact_type == GEO_MAP_DOCUMENT_ARTIFACT_TYPE:
                document = GeoMapDocumentPayload.model_validate(artifact.inline_payload)
                layer_artifacts = await self._get_exact_artifacts(
                    document.layers,
                    expected_type=GEO_MAP_LAYER_ARTIFACT_TYPE,
                    context=f"Map document artifact {artifact.id}",
                    workspace_id=workspace_id,
                )
                layers: list[GeoRenderLayerResponse] = []
                for layer_artifact in layer_artifacts:
                    layer = await self._resolve_render_layer(
                        layer_artifact,
                        workspace_id=workspace_id,
                    )
                    if layer is not None:
                        layers.append(layer)
                effective_bounds = document.initial_bounds
                if effective_bounds is None:
                    layer_bounds = [
                        layer.source.bounds
                        for layer in layers
                        if layer.source.bounds is not None
                    ]
                    effective_bounds = _bounds_union(layer_bounds)
                return GeoRenderResponse(
                    artifact_id=artifact.id,
                    kind="map_document",
                    basemap=document.basemap,
                    initial_bounds=effective_bounds,
                    layers=layers,
                )
        except (ArtifactContentUnavailableError, WorkbenchOperationError):
            raise
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not build render descriptor for artifact {artifact.id}"
            ) from exc
        raise WorkbenchOperationError(
            f"Artifact {artifact.id} is not a supported geo artifact"
        )

    def _source_name(self, artifact: ArtifactObject) -> str:
        source_name = artifact.metadata.get("source_name")
        if not isinstance(source_name, str) or source_name.strip() == "":
            raise ArtifactContentUnavailableError(
                f"Geo source artifact {artifact.id} has invalid source_name metadata"
            )
        return source_name

    def _feature_fields(
        self,
        artifact: ArtifactObject,
    ) -> list[GeoPropertyFieldResponse]:
        value = artifact.metadata.get("property_fields", [])
        if not isinstance(value, list):
            raise ArtifactContentUnavailableError(
                f"Geo source artifact {artifact.id} has invalid "
                "property_fields metadata"
            )
        try:
            return [
                GeoPropertyFieldResponse.model_validate(field)
                for field in cast(list[object], value)
            ]
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Geo source artifact {artifact.id} has invalid "
                "property_fields metadata"
            ) from exc

    def _feature_render_layer(
        self,
        artifact: ArtifactObject,
        *,
        layer_id: str,
        title: str,
        visible: bool,
        opacity: float,
        min_zoom: int,
        max_zoom: int,
        style: GeoVectorStyle | GeoCategorizedPointStyle,
    ) -> GeoRenderLayerResponse | None:
        projection_value = artifact.metadata.get("vector_projection")
        if projection_value is None and self._feature_count(artifact) == 0:
            return None
        projection = GeoVectorProjectionMetadata.model_validate(projection_value)
        return GeoRenderLayerResponse(
            id=layer_id,
            title=title,
            visible=visible,
            opacity=opacity,
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            source=GeoVectorRenderSourceResponse(
                artifact_id=artifact.id,
                archive_url=(
                    f"/v1/workspaces/{artifact.workspace_id}/artifacts/{artifact.id}/geo/vector.pmtiles"
                ),
                source_layer=projection.source_layer,
                bounds=projection.bounds,
                min_zoom=projection.min_zoom,
                max_zoom=projection.max_zoom,
                fields=self._feature_fields(artifact),
            ),
            style=style,
        )

    def _raster_render_layer(
        self,
        artifact: ArtifactObject,
        *,
        layer_id: str,
        title: str,
        visible: bool,
        opacity: float,
        min_zoom: int,
        max_zoom: int,
        style: GeoRasterStyle,
    ) -> GeoRenderLayerResponse:
        projection = GeoRasterProjectionMetadata.model_validate(
            artifact.metadata.get("raster_projection")
        )
        return GeoRenderLayerResponse(
            id=layer_id,
            title=title,
            visible=visible,
            opacity=opacity,
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            source=GeoRasterRenderSourceResponse(
                artifact_id=artifact.id,
                tilejson_url=(
                    f"/v1/workspaces/{artifact.workspace_id}/artifacts/{artifact.id}/geo/raster/tilejson.json"
                ),
                bounds=projection.bounds,
            ),
            style=style,
        )

    async def _resolve_render_layer(
        self,
        layer_artifact: ArtifactObject,
        *,
        workspace_id: UUID,
    ) -> GeoRenderLayerResponse | None:
        if (
            layer_artifact.artifact_type != GEO_MAP_LAYER_ARTIFACT_TYPE
            or layer_artifact.schema_version != 1
        ):
            raise ArtifactContentUnavailableError(
                f"Artifact {layer_artifact.id} is not a geo.map_layer@1 artifact"
            )
        layer = GeoMapLayerPayload.model_validate(layer_artifact.inline_payload)
        if layer.source.kind == "feature_collection":
            source_artifact = (
                await self._get_exact_artifacts(
                    [layer.source.artifact],
                    expected_type=GEO_FEATURE_COLLECTION_ARTIFACT_TYPE,
                    context=f"Map layer artifact {layer_artifact.id}",
                    workspace_id=workspace_id,
                )
            )[0]
            if layer.style.kind == "raster":
                raise ValueError("Feature collection layer has non-vector style")
            return self._feature_render_layer(
                source_artifact,
                layer_id=str(layer_artifact.id),
                title=layer.title,
                visible=layer.visible,
                opacity=layer.opacity,
                min_zoom=layer.min_zoom,
                max_zoom=layer.max_zoom,
                style=layer.style,
            )
        if layer.source.kind == "raster_scan":
            source_artifact = (
                await self._get_exact_artifacts(
                    [layer.source.artifact],
                    expected_type=GEO_RASTER_SCAN_ARTIFACT_TYPE,
                    context=f"Map layer artifact {layer_artifact.id}",
                    workspace_id=workspace_id,
                )
            )[0]
            if layer.style.kind != "raster":
                raise ValueError("Raster scan layer has non-raster style")
            return self._raster_render_layer(
                source_artifact,
                layer_id=str(layer_artifact.id),
                title=layer.title,
                visible=layer.visible,
                opacity=layer.opacity,
                min_zoom=layer.min_zoom,
                max_zoom=layer.max_zoom,
                style=layer.style,
            )
        if layer.style.kind != "raster":
            raise ValueError("WMS layer has non-raster style")
        _validate_public_wms_url(layer.source)
        return GeoRenderLayerResponse(
            id=str(layer_artifact.id),
            title=layer.title,
            visible=layer.visible,
            opacity=layer.opacity,
            min_zoom=layer.min_zoom,
            max_zoom=layer.max_zoom,
            source=GeoRasterRenderSourceResponse(
                artifact_id=None,
                tilejson_url=(
                    f"/v1/workspaces/{layer_artifact.workspace_id}/artifacts/{layer_artifact.id}/geo/raster/tilejson.json"
                ),
                bounds=layer.source.bounds,
                attribution=layer.source.attribution,
            ),
            style=layer.style,
        )

    async def _get_exact_artifacts(
        self,
        refs: list[GeoArtifactRefPayload],
        *,
        expected_type: str,
        context: str,
        workspace_id: UUID,
    ) -> list[ArtifactObject]:
        for ref in refs:
            if ref.artifact_type != expected_type or ref.schema_version != 1:
                raise ArtifactContentUnavailableError(
                    f"{context} references {ref.artifact_type}@{ref.schema_version}, "
                    f"expected {expected_type}@1"
                )
        exact_refs = [
            ArtifactRef(
                artifact_id=ref.artifact_id,
                artifact_type=ref.artifact_type,
                schema_version=ref.schema_version,
                content_hash=ref.content_hash,
            )
            for ref in refs
        ]
        batch = await self._availability.load(workspace_id, exact_refs)
        try:
            return list(batch.resolve_refs(exact_refs, context=context))
        except ArtifactReferenceError as exc:
            if exc.reason == "missing":
                raise ArtifactContentUnavailableError(str(exc)) from exc
            raise ArtifactContentUnavailableError(
                f"{context} reference for artifact {exc.reference.artifact_id} does not "
                "match the repository artifact"
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
                name=self._source_name(artifact),
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
                await self._get_exact_artifacts(
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
        _validate_public_wms_url(layer.source)
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
        if not _valid_tile_coordinates(z, x, y):
            return None
        try:
            if artifact.artifact_type == GEO_RASTER_SCAN_ARTIFACT_TYPE:
                projection = GeoRasterProjectionMetadata.model_validate(
                    artifact.metadata.get("raster_projection")
                )
                return await self._load_stored_raster_tile(projection, z=z, x=x, y=y)
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
            if layer.source.kind == "raster_scan":
                source_artifact = (
                    await self._get_exact_artifacts(
                        [layer.source.artifact],
                        expected_type=GEO_RASTER_SCAN_ARTIFACT_TYPE,
                        context=f"Map layer artifact {artifact.id}",
                        workspace_id=workspace_id,
                    )
                )[0]
                projection = GeoRasterProjectionMetadata.model_validate(
                    source_artifact.metadata.get("raster_projection")
                )
                return await self._load_stored_raster_tile(
                    projection,
                    z=z,
                    x=x,
                    y=y,
                )
            return await self._load_wms_tile(layer.source, z=z, x=x, y=y)
        except (ArtifactContentUnavailableError, WorkbenchOperationError):
            raise
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not load raster tile {z}/{x}/{y} for artifact {artifact.id}"
            ) from exc

    async def _load_stored_raster_tile(
        self,
        projection: GeoRasterProjectionMetadata,
        *,
        z: int,
        x: int,
        y: int,
    ) -> GeoTileRead | None:
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

    async def _load_wms_tile(
        self,
        source: GeoWmsSourcePayload,
        *,
        z: int,
        x: int,
        y: int,
    ) -> GeoTileRead:
        _validate_public_wms_url(source)
        host = source.url.host
        if host is None:
            raise ArtifactContentUnavailableError("WMS URL does not have a host")
        port = source.url.port
        if port is None:
            port = 443 if source.url.scheme == "https" else 80
        try:
            addresses = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(
                    host,
                    port,
                    type=socket.SOCK_STREAM,
                ),
                timeout=3.0,
            )
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not resolve WMS host {host!r}"
            ) from exc
        if not addresses:
            raise ArtifactContentUnavailableError(
                f"WMS host {host!r} resolved to no addresses"
            )
        resolved_addresses: list[str] = []
        for address_info in addresses:
            resolved_address = ipaddress.ip_address(
                address_info[4][0].split("%", maxsplit=1)[0]
            )
            if not resolved_address.is_global:
                raise ArtifactContentUnavailableError(
                    f"WMS host {host!r} resolved to non-public address "
                    f"{resolved_address}"
                )
            normalized_address = str(resolved_address)
            if normalized_address not in resolved_addresses:
                resolved_addresses.append(normalized_address)
        west, south, east, north = _web_mercator_tile_bounds(z, x, y)
        parameters = {
            "service": "WMS",
            "request": "GetMap",
            "version": source.version,
            "layers": source.layer,
            "styles": source.style_name or "",
            "format": source.format,
            "transparent": "true",
            "width": "256",
            "height": "256",
            "bbox": f"{west},{south},{east},{north}",
        }
        if source.version == "1.3.0":
            parameters["crs"] = "EPSG:3857"
        else:
            parameters["srs"] = "EPSG:3857"
        service_request_url = httpx.URL(str(source.url))
        try:
            for address_index, resolved_address in enumerate(resolved_addresses):
                pinned_url = service_request_url.copy_with(host=resolved_address)
                try:
                    chunks: list[bytes] = []
                    byte_size = 0
                    async with self._wms_client.stream(
                        "GET",
                        pinned_url,
                        params=parameters,
                        headers={
                            "Accept": source.format,
                            "Connection": "close",
                            "Host": service_request_url.netloc.decode("ascii"),
                        },
                        extensions={
                            "sni_hostname": service_request_url.raw_host.decode("ascii")
                        },
                    ) as response:
                        if response.status_code < 200 or response.status_code >= 300:
                            raise ValueError(
                                f"WMS returned HTTP {response.status_code}"
                            )
                        response_type = (
                            response.headers.get("content-type", "")
                            .split(";", 1)[0]
                            .strip()
                            .lower()
                        )
                        if response_type != source.format:
                            raise ValueError(
                                f"WMS returned {response_type or 'no content type'}, "
                                f"expected {source.format}"
                            )
                        async for chunk in response.aiter_bytes():
                            byte_size += len(chunk)
                            if byte_size > WMS_RESPONSE_BYTE_BUDGET:
                                raise ValueError(
                                    f"WMS tile exceeds {WMS_RESPONSE_BYTE_BUDGET} bytes"
                                )
                            chunks.append(chunk)
                    return GeoTileRead(
                        content=b"".join(chunks),
                        content_type=source.format,
                        etag=None,
                    )
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    if address_index == len(resolved_addresses) - 1:
                        raise
            raise RuntimeError(f"WMS host {host!r} had no usable public address")
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not fetch WMS layer {source.layer!r} from "
                f"{source.url.host} for tile {z}/{x}/{y}"
            ) from exc

    async def load_table_page(
        self,
        artifact: ArtifactObject,
        *,
        offset: int,
        limit: int,
    ) -> TablePage:
        if (
            artifact.artifact_type != TABLE_DATA.key.id
            or artifact.schema_version != TABLE_DATA.key.schema_version
        ):
            raise WorkbenchOperationError(
                f"Artifact {artifact.id} is not a table.data@1 artifact"
            )
        try:
            return await load_table_page(
                artifact,
                self._storage,
                offset=offset,
                limit=limit,
            )
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not load table page at offset {offset} for artifact "
                f"{artifact.id}"
            ) from exc

    async def load_table_cell(
        self,
        artifact: ArtifactObject,
        *,
        row_index: int,
        column_id: str,
    ) -> TableValue:
        page = await self.load_table_page(artifact, offset=row_index, limit=1)
        if row_index >= page.total_rows:
            raise WorkbenchOperationError(
                f"Table artifact {artifact.id} has no row {row_index}"
            )
        column_ids = {column.id for column in page.columns}
        if column_id not in column_ids:
            raise WorkbenchOperationError(
                f"Table artifact {artifact.id} has no column {column_id!r}"
            )
        return page.rows[0][column_id]

    async def load_table_query_page(
        self,
        artifact: ArtifactObject,
        *,
        filter_groups: list[TableExactMatchGroup],
        highlight_groups: list[TableExactMatchGroup],
        offset: int,
        limit: int,
    ) -> TableQueryPage:
        if (
            artifact.artifact_type != TABLE_DATA.key.id
            or artifact.schema_version != TABLE_DATA.key.schema_version
        ):
            raise WorkbenchOperationError(
                f"Artifact {artifact.id} is not a table.data@1 artifact"
            )
        row_count = artifact.metadata.get("row_count")
        if (
            not isinstance(row_count, int)
            or isinstance(row_count, bool)
            or row_count < 0
        ):
            raise ArtifactContentUnavailableError(
                f"Table artifact {artifact.id} has invalid row_count metadata"
            )
        if row_count > TABLE_INTERACTION_ROW_LIMIT:
            raise WorkbenchOperationError(
                f"Linked table filtering supports at most "
                f"{TABLE_INTERACTION_ROW_LIMIT} rows; artifact {artifact.id} "
                f"contains {row_count}"
            )
        try:
            table = await load_table_artifact(artifact, self._storage)
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not load table artifact {artifact.id} for linked filtering"
            ) from exc

        column_ids = {column.id for column in table.columns}
        requested_fields = {
            field_name
            for group in [*filter_groups, *highlight_groups]
            for candidate in group.rows
            for field_name in candidate.values
        }
        missing_fields = sorted(requested_fields - column_ids)
        if missing_fields:
            raise WorkbenchOperationError(
                f"Table artifact {artifact.id} has no linked field(s) "
                f"{missing_fields!r}"
            )

        matched: list[tuple[int, dict[str, TableValue]]] = []
        highlighted_indices: set[int] = set()
        for row_index, row in enumerate(table.rows):
            if filter_groups and not all(
                _table_row_matches_group(row, group) for group in filter_groups
            ):
                continue
            matched.append((row_index, row))
            if highlight_groups and any(
                _table_row_matches_group(row, group) for group in highlight_groups
            ):
                highlighted_indices.add(row_index)

        effective_offset = min(offset, len(matched))
        selected = matched[effective_offset : effective_offset + limit]
        selected_indices = [row_index for row_index, _ in selected]
        return TableQueryPage(
            page=TablePage(
                columns=table.columns,
                rows=[row for _, row in selected],
                offset=effective_offset,
                total_rows=len(matched),
            ),
            row_indices=selected_indices,
            highlighted_row_indices=[
                row_index
                for row_index in selected_indices
                if row_index in highlighted_indices
            ],
        )


__all__ = [
    "ArtifactResponseTooLargeError",
    "BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES",
    "ArtifactService",
    "GeoArchiveRead",
    "GeoRangeNotSatisfiableError",
    "PMTILES_RESPONSE_MAX_BYTES",
    "GeoTileRead",
    "IMMUTABLE_CACHE_CONTROL",
]

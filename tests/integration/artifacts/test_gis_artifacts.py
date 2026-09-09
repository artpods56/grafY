import asyncio
import json
import socket
from collections.abc import Iterator
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from grafy_core.artifact_collections import (
    JSON_COLLECTIONS_STORAGE_FORMAT,
    JsonCollection,
    JsonCollectionsManifest,
    save_json_collections,
)
from grafy_core.artifacts import ArtifactObject, ArtifactTypeKey, JsonObject
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.ports.storage import (
    FileStoragePort,
    FileStreamProtocol,
    SaveFileCommand,
    StoredFile,
    StoredObjectInfo,
)

from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceAccess,
    WorkspaceCapability,
    WorkspaceMembership,
    WorkspaceRole,
)

from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.v1.routes.artifacts import services as artifact_services
from grafy_api.v1.routes.artifacts.dependencies import artifact_service
from grafy_api.v1.routes.artifacts.models import (
    ArtifactExactMatchRow,
    GeoFeatureQueryRequest,
)
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_api.v1.routes.artifacts.views import router as artifacts_router
from grafy_api.v1.routes.auth.dependencies import (
    browser_actor,
    identity_service,
    workspace_actor,
)
from grafy_storage import LocalFileObjectStore

from tests.support.clients import GrafyApi


FEATURE_KEY = ArtifactTypeKey("geo.feature_collection", 1)
RASTER_KEY = ArtifactTypeKey("geo.raster_scan", 1)
LAYER_KEY = ArtifactTypeKey("geo.map_layer", 1)
DOCUMENT_KEY = ArtifactTypeKey("geo.map_document", 1)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")
TEST_USER_ID = UUID(int=1)


def test_json_collections_manifest_accepts_legacy_storage_format() -> None:
    manifest = JsonCollectionsManifest.model_validate(
        {
            "format": "notarius.json-collections.chunked.v1",
            "total_items": 0,
            "collections": [],
        }
    )

    assert manifest.format == "notarius.json-collections.chunked.v1"


class _AllowAllIdentityService:
    async def authorize(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        capability: WorkspaceCapability,
    ) -> WorkspaceAccess:
        del capability
        return WorkspaceAccess(
            actor=actor,
            workspace_id=workspace_id,
            membership=WorkspaceMembership(
                workspace_id=workspace_id,
                user_id=actor.user_id,
                role=WorkspaceRole.OWNER,
            ),
        )


class TrackingStorage(FileStoragePort):
    def __init__(self, storage: FileStoragePort) -> None:
        self._storage = storage
        self.loaded_paths: list[str] = []
        self.range_requests: list[tuple[str, int, int]] = []

    async def save(self, command: SaveFileCommand) -> StoredFile:
        return await self._storage.save(command)

    async def move(
        self,
        bucket: str,
        source_path: str,
        destination_path: str,
    ) -> None:
        await self._storage.move(bucket, source_path, destination_path)

    async def load(self, bucket: str, path: str) -> FileStreamProtocol:
        self.loaded_paths.append(path)
        return await self._storage.load(bucket, path)

    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        return await self._storage.stat(bucket, path)

    async def load_range(
        self,
        bucket: str,
        path: str,
        start: int,
        end_exclusive: int,
    ) -> bytes:
        self.range_requests.append((path, start, end_exclusive))
        return await self._storage.load_range(bucket, path, start, end_exclusive)

    async def delete(self, bucket: str, path: str) -> None:
        await self._storage.delete(bucket, path)


@pytest.fixture
def geo_artifact_client(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, InMemoryUnitOfWork, TrackingStorage]]:
    unit_of_work = InMemoryUnitOfWork()
    storage = TrackingStorage(LocalFileObjectStore(tmp_path / "objects"))
    application = FastAPI()
    service = ArtifactService(
        unit_of_work, storage, availability=ArtifactAvailability(unit_of_work, storage)
    )
    application.dependency_overrides[artifact_service] = lambda: service
    application.dependency_overrides[identity_service] = (
        lambda: _AllowAllIdentityService()
    )
    application.dependency_overrides[browser_actor] = lambda: ActorContext(
        user_id=TEST_USER_ID,
        credential_reference="test-session",
    )
    application.dependency_overrides[workspace_actor] = lambda: ActorContext(
        user_id=TEST_USER_ID,
        credential_reference="test-session",
    )
    application.include_router(artifacts_router, prefix="/v1")
    with TestClient(application) as client:
        yield client, unit_of_work, storage
    asyncio.run(service.close())


def _point_feature(index: int, x: float, y: float) -> JsonObject:
    return cast(
        JsonObject,
        {
            "type": "Feature",
            "id": index,
            "properties": {"name": f"point-{index}"},
            "geometry": {"type": "Point", "coordinates": [x, y]},
        },
    )


def _vector_style(color: str = "#2563eb") -> JsonObject:
    return cast(
        JsonObject,
        {
            "kind": "vector",
            "fill": {"enabled": True, "color": color, "opacity": 0.4},
            "line": {
                "enabled": True,
                "color": color,
                "opacity": 1.0,
                "width": 2.0,
            },
            "outline": {
                "enabled": True,
                "color": "#111827",
                "opacity": 0.8,
                "width": 1.0,
            },
            "point": {
                "enabled": True,
                "color": "#dc2626",
                "opacity": 0.9,
                "radius": 7.0,
                "stroke_color": "#ffffff",
                "stroke_width": 1.5,
            },
            "label": {
                "property": "name",
                "color": "#111827",
                "size": 12.0,
                "halo_color": "#ffffff",
                "halo_width": 1.0,
            },
        },
    )


def _categorized_point_style() -> JsonObject:
    return cast(
        JsonObject,
        {
            "kind": "categorized_points",
            "category_property": "type",
            "categories": [
                {
                    "id": "cities",
                    "title": "Cities and towns",
                    "values": [1, 2, 3],
                    "point": {
                        "enabled": True,
                        "color": "#b91c1c",
                        "opacity": 1.0,
                        "radius": 7.0,
                        "stroke_color": "#ffffff",
                        "stroke_width": 1.0,
                    },
                    "min_zoom": 6,
                    "max_zoom": 22,
                },
                {
                    "id": "villages",
                    "title": "Villages",
                    "values": [5, 7, 8, 9, 10],
                    "point": {
                        "enabled": True,
                        "color": "#d6a700",
                        "opacity": 0.85,
                        "radius": 4.0,
                        "stroke_color": "#ffffff",
                        "stroke_width": 1.0,
                    },
                    "min_zoom": 10,
                    "max_zoom": 22,
                },
            ],
            "label": {
                "property": "name",
                "color": "#111827",
                "size": 12.0,
                "halo_color": "#ffffff",
                "halo_width": 1.0,
            },
        },
    )


def _raster_style() -> JsonObject:
    return cast(
        JsonObject,
        {
            "kind": "raster",
            "opacity": 0.75,
            "brightness_min": 0.1,
            "brightness_max": 0.9,
            "contrast": 0.2,
            "saturation": -0.1,
            "hue": 5.0,
            "resampling": "linear",
        },
    )


async def _add_artifact(
    unit_of_work: InMemoryUnitOfWork,
    artifact: ArtifactObject,
) -> ArtifactObject:
    async with unit_of_work as uow:
        await uow.artifacts.add(artifact)
        await uow.commit()
    return artifact


async def _feature_artifact(
    unit_of_work: InMemoryUnitOfWork,
    storage: TrackingStorage,
    *,
    source_name: str,
    features: list[JsonObject],
    bounds: tuple[float, float, float, float] | None,
    pmtiles: bytes | None = b"PMTiles fixture bytes",
) -> ArtifactObject:
    stored = await save_json_collections(
        storage,
        bucket="test",
        artifact_type=FEATURE_KEY,
        collections=[JsonCollection(id="features", items=features)],
        metadata=cast(
            JsonObject,
            {
                "kind": "geo.feature_collection",
                "crs": "EPSG:4326",
                "source_name": source_name,
                "bounds": bounds,
            },
        ),
        node_id="features",
        workspace_id=WORKSPACE_ID,
    )
    logical_payload = {
        "type": "FeatureCollection",
        "crs": "EPSG:4326",
        "features": features,
        "source_name": source_name,
        "bounds": bounds,
    }
    logical_content = json.dumps(
        logical_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    metadata: JsonObject = {
        "storage_format": JSON_COLLECTIONS_STORAGE_FORMAT,
        "source_name": source_name,
        "feature_count": len(features),
        "manifest_byte_size": stored.manifest_byte_size,
        "manifest_sha256": stored.manifest_sha256,
    }
    if features:
        metadata["property_fields"] = [
            {"id": "name", "title": "name", "value_type": "text"}
        ]
    if bounds is not None:
        metadata["bounds"] = list(bounds)
    if pmtiles is not None:
        projection_hash = sha256(pmtiles).hexdigest()
        projection = await storage.save(
            SaveFileCommand(
                bucket="test",
                path=f"projections/{projection_hash}.pmtiles",
                stream=BytesIO(pmtiles),
                content_type="application/vnd.pmtiles",
                metadata={"sha256": projection_hash},
                allow_overwrite=True,
            )
        )
        metadata["vector_projection"] = {
            "kind": "pmtiles",
            "bucket": projection.bucket,
            "object_key": projection.path,
            "content_type": "application/vnd.pmtiles",
            "byte_size": projection.byte_size,
            "sha256": projection.sha256,
            "min_zoom": 0,
            "max_zoom": 14,
            "source_layer": "features",
            "bounds": bounds,
            "compiler": "fixture",
        }
    return await _add_artifact(
        unit_of_work,
        ArtifactObject(
            workspace_id=WORKSPACE_ID,
            artifact_type=FEATURE_KEY.id,
            schema_version=1,
            content_type="application/geo+json",
            bucket=stored.bucket,
            object_key=stored.manifest_path,
            byte_size=len(logical_content),
            sha256=sha256(logical_content).hexdigest(),
            metadata=metadata,
        ),
    )


async def _raster_artifact(
    unit_of_work: InMemoryUnitOfWork,
    storage: TrackingStorage,
) -> ArtifactObject:
    cog = b"canonical-cog"
    stored_cog = await storage.save(
        SaveFileCommand(
            bucket="test",
            path="geo.raster_scan/v1/source.tif",
            stream=BytesIO(cog),
            content_type="image/tiff",
            metadata={},
            allow_overwrite=True,
        )
    )
    tile_prefix = "geo.raster_scan/v1/projections/source/xyz"
    await storage.save(
        SaveFileCommand(
            bucket="test",
            path=f"{tile_prefix}/2/2/1.png",
            stream=BytesIO(b"png-tile"),
            content_type="image/png",
            metadata={},
            allow_overwrite=True,
        )
    )
    return await _add_artifact(
        unit_of_work,
        ArtifactObject(
            workspace_id=WORKSPACE_ID,
            artifact_type=RASTER_KEY.id,
            schema_version=1,
            content_type=("image/tiff; application=geotiff; profile=cloud-optimized"),
            bucket=stored_cog.bucket,
            object_key=stored_cog.path,
            byte_size=stored_cog.byte_size,
            sha256=stored_cog.sha256,
            metadata={
                "source_name": "Historical scan",
                "original_filename": "scan.tif",
                "raster_projection": {
                    "kind": "xyz",
                    "bucket": "test",
                    "prefix": tile_prefix,
                    "extension": "png",
                    "content_type": "image/png",
                    "min_zoom": 2,
                    "max_zoom": 6,
                    "tile_size": 256,
                    "bounds": [10.0, 10.0, 20.0, 20.0],
                    "source_crs": "EPSG:3857",
                    "width": 1024,
                    "height": 768,
                    "band_count": 4,
                    "compiler": "fixture",
                },
            },
        ),
    )


async def _inline_artifact(
    unit_of_work: InMemoryUnitOfWork,
    key: ArtifactTypeKey,
    payload: JsonObject,
) -> ArtifactObject:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return await _add_artifact(
        unit_of_work,
        ArtifactObject(
            workspace_id=WORKSPACE_ID,
            artifact_type=key.id,
            schema_version=key.schema_version,
            content_type="application/json",
            storage_backend="inline",
            inline_payload=payload,
            byte_size=len(content),
            sha256=sha256(content).hexdigest(),
        ),
    )


def _ref(artifact: ArtifactObject) -> JsonObject:
    return cast(JsonObject, artifact.ref().model_dump(mode="json"))


def test_vector_render_archive_ranges_and_exact_feature_are_bounded(
    geo_artifact_client: tuple[TestClient, InMemoryUnitOfWork, TrackingStorage],
) -> None:
    client, unit_of_work, storage = geo_artifact_client
    api = GrafyApi(client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts
    features = [
        _point_feature(index, float(index), float(index)) for index in range(65)
    ]
    artifact = asyncio.run(
        _feature_artifact(
            unit_of_work,
            storage,
            source_name="Observation points",
            features=features,
            bounds=(0.0, 0.0, 64.0, 64.0),
        )
    )

    render = artifacts.geo_render(artifact.id)
    assert render.status_code == 200
    descriptor = render.json()
    assert descriptor["kind"] == "feature_collection"
    assert descriptor["initial_bounds"] == [0.0, 0.0, 64.0, 64.0]
    assert descriptor["layers"][0]["source"] == {
        "kind": "vector",
        "artifact_id": str(artifact.id),
        "archive_url": f"/v1/workspaces/00000000-0000-0000-0000-000000000007/artifacts/{artifact.id}/geo/vector.pmtiles",
        "source_layer": "features",
        "bounds": [0.0, 0.0, 64.0, 64.0],
        "min_zoom": 0,
        "max_zoom": 14,
        "fields": [{"id": "name", "title": "name", "value_type": "text"}],
    }

    full = artifacts.geo_vector_pmtiles(artifact.id)
    partial = artifacts.geo_vector_pmtiles(
        artifact.id,
        headers={"Range": "bytes=2-7"},
    )
    suffix = artifacts.geo_vector_pmtiles(
        artifact.id,
        headers={"Range": "bytes=-4"},
    )
    invalid = artifacts.geo_vector_pmtiles(
        artifact.id,
        headers={"Range": "bytes=999-1000"},
    )
    assert full.status_code == 200
    assert full.content == b"PMTiles fixture bytes"
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-length"] == str(len(full.content))
    assert full.headers["cache-control"].endswith("immutable")
    assert partial.status_code == 206
    assert partial.content == b"Tiles "
    assert partial.headers["content-range"] == (f"bytes 2-7/{len(full.content)}")
    assert suffix.status_code == 206
    assert suffix.content == b"ytes"
    assert invalid.status_code == 416
    assert invalid.headers["content-range"] == f"bytes */{len(full.content)}"
    projection_path = storage.range_requests[0][0]
    assert storage.range_requests == [
        (projection_path, 0, len(full.content)),
        (projection_path, 2, 8),
        (projection_path, len(full.content) - 4, len(full.content)),
    ]

    storage.loaded_paths.clear()
    exact = artifacts.geo_exact_feature(artifact.id, 55)
    assert exact.status_code == 200
    assert exact.json()["feature_index"] == 55
    assert exact.json()["feature"]["properties"]["name"] == "point-55"
    assert len(storage.loaded_paths) == 2
    assert sum("/chunks/" in path for path in storage.loaded_paths) == 1
    assert artifacts.geo_exact_feature(artifact.id, 65).status_code == 404

    query = artifacts.query_geo_features(
        artifact.id,
        GeoFeatureQueryRequest(
            rows=[
                ArtifactExactMatchRow(values={"name": "point-55"}),
                ArtifactExactMatchRow(values={"name": "point-2"}),
            ]
        ),
    )
    assert query.status_code == 200
    assert query.json() == {
        "artifact_id": str(artifact.id),
        "bounds": [2.0, 2.0, 55.0, 55.0],
        "matched_feature_count": 2,
        "source_artifact_ids": [str(artifact.id)],
    }

    missing = artifacts.query_geo_features(
        artifact.id,
        GeoFeatureQueryRequest(
            rows=[ArtifactExactMatchRow(values={"name": "not-present"})]
        ),
    )
    assert missing.status_code == 200
    assert missing.json()["bounds"] is None
    assert missing.json()["matched_feature_count"] == 0


def test_vector_archive_rejects_oversized_buffered_responses_before_loading(
    geo_artifact_client: tuple[TestClient, InMemoryUnitOfWork, TrackingStorage],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, unit_of_work, storage = geo_artifact_client
    api = GrafyApi(client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts
    artifact = asyncio.run(
        _feature_artifact(
            unit_of_work,
            storage,
            source_name="Observation points",
            features=[_point_feature(0, 0.0, 0.0)],
            bounds=(0.0, 0.0, 0.0, 0.0),
        )
    )
    monkeypatch.setattr(artifact_services, "PMTILES_RESPONSE_MAX_BYTES", 8)

    full = artifacts.geo_vector_pmtiles(artifact.id)
    oversized_range = artifacts.geo_vector_pmtiles(
        artifact.id,
        headers={"Range": "bytes=0-8"},
    )

    assert full.status_code == 413
    assert str(artifact.id) in full.json()["detail"]
    assert "8-byte response limit" in full.json()["detail"]
    assert oversized_range.status_code == 416
    assert oversized_range.headers["content-range"] == "bytes */21"
    assert "9 bytes" in oversized_range.json()["detail"]
    assert "8-byte range limit" in oversized_range.json()["detail"]
    assert storage.range_requests == []


def test_empty_feature_collection_has_clear_non_renderable_descriptor(
    geo_artifact_client: tuple[TestClient, InMemoryUnitOfWork, TrackingStorage],
) -> None:
    client, unit_of_work, storage = geo_artifact_client
    api = GrafyApi(client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts
    artifact = asyncio.run(
        _feature_artifact(
            unit_of_work,
            storage,
            source_name="Empty source",
            features=[],
            bounds=None,
            pmtiles=None,
        )
    )

    response = artifacts.geo_render(artifact.id)

    assert response.status_code == 200
    assert response.json()["layers"] == []
    assert response.json()["initial_bounds"] is None
    archive = artifacts.geo_vector_pmtiles(artifact.id)
    assert archive.status_code == 400
    assert "empty" in archive.json()["detail"]


def test_map_document_resolves_ordered_vector_raster_and_wms_layers(
    geo_artifact_client: tuple[TestClient, InMemoryUnitOfWork, TrackingStorage],
) -> None:
    client, unit_of_work, storage = geo_artifact_client
    api = GrafyApi(client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts
    first_source = asyncio.run(
        _feature_artifact(
            unit_of_work,
            storage,
            source_name="First points",
            features=[_point_feature(1, -5.0, -4.0)],
            bounds=(-5.0, -4.0, -5.0, -4.0),
        )
    )
    second_source = asyncio.run(
        _feature_artifact(
            unit_of_work,
            storage,
            source_name="Second points",
            features=[_point_feature(2, 5.0, 6.0)],
            bounds=(5.0, 6.0, 5.0, 6.0),
        )
    )
    raster_source = asyncio.run(_raster_artifact(unit_of_work, storage))
    first_layer = asyncio.run(
        _inline_artifact(
            unit_of_work,
            LAYER_KEY,
            {
                "title": "First observations",
                "visible": True,
                "opacity": 0.8,
                "min_zoom": 1,
                "max_zoom": 18,
                "source": {
                    "kind": "feature_collection",
                    "artifact": _ref(first_source),
                },
                "style": _vector_style("#22c55e"),
            },
        )
    )
    raster_layer = asyncio.run(
        _inline_artifact(
            unit_of_work,
            LAYER_KEY,
            {
                "title": "Historical scan",
                "visible": True,
                "opacity": 0.55,
                "min_zoom": 2,
                "max_zoom": 12,
                "source": {
                    "kind": "raster_scan",
                    "artifact": _ref(raster_source),
                },
                "style": _raster_style(),
            },
        )
    )
    second_layer = asyncio.run(
        _inline_artifact(
            unit_of_work,
            LAYER_KEY,
            {
                "title": "Second observations",
                "visible": False,
                "opacity": 1.0,
                "min_zoom": 0,
                "max_zoom": 22,
                "source": {
                    "kind": "feature_collection",
                    "artifact": _ref(second_source),
                },
                "style": _categorized_point_style(),
            },
        )
    )
    wms_layer = asyncio.run(
        _inline_artifact(
            unit_of_work,
            LAYER_KEY,
            {
                "title": "Atlas Fontium",
                "visible": True,
                "opacity": 0.7,
                "min_zoom": 3,
                "max_zoom": 16,
                "source": {
                    "kind": "wms",
                    "url": "https://atlasfontium.pl/geoserver/wms",
                    "layer": "atlas:historical",
                    "version": "1.3.0",
                    "format": "image/png",
                    "bounds": [-10.0, -8.0, 30.0, 25.0],
                    "attribution": "Atlas Fontium",
                    "style_name": None,
                },
                "style": _raster_style(),
            },
        )
    )
    document = asyncio.run(
        _inline_artifact(
            unit_of_work,
            DOCUMENT_KEY,
            {
                "layers": [
                    _ref(first_layer),
                    _ref(raster_layer),
                    _ref(second_layer),
                    _ref(wms_layer),
                ],
                "basemap": "openstreetmap",
                "initial_bounds": None,
            },
        )
    )

    response = artifacts.geo_render(document.id)

    assert response.status_code == 200
    descriptor = response.json()
    assert descriptor["kind"] == "map_document"
    assert descriptor["initial_bounds"] == [-10.0, -8.0, 30.0, 25.0]
    assert [layer["title"] for layer in descriptor["layers"]] == [
        "First observations",
        "Historical scan",
        "Second observations",
        "Atlas Fontium",
    ]
    assert descriptor["layers"][0]["style"]["point"]["radius"] == 7.0
    assert descriptor["layers"][1]["source"]["kind"] == "raster"
    assert descriptor["layers"][2]["style"]["kind"] == "categorized_points"
    assert descriptor["layers"][2]["style"]["categories"][1]["min_zoom"] == 10
    assert descriptor["layers"][3]["source"]["artifact_id"] is None
    assert descriptor["layers"][3]["source"]["attribution"] == "Atlas Fontium"

    # The `url` query param is not declared by the route (it must be ignored),
    # so the typed client cannot express this request; use the raw client.
    tilejson = client.get(
        f"/v1/workspaces/00000000-0000-0000-0000-000000000007/artifacts/{wms_layer.id}/geo/raster/tilejson.json",
        params={"url": "http://127.0.0.1/private"},
    )
    assert tilejson.status_code == 200
    assert tilejson.json()["tiles"] == [
        f"/api/v1/workspaces/00000000-0000-0000-0000-000000000007/artifacts/{wms_layer.id}/geo/raster/"
        "{z}/{x}/{y}.png"
    ]


async def test_wms_tile_pins_validated_address_against_dns_rebinding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dns_lookups: list[str] = []
    requests: list[httpx.Request] = []
    destinations: list[str] = []

    def rebind_host(
        host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[object, object, object, str, tuple[str, int]]]:
        dns_lookups.append(host)
        address = "93.184.216.34" if len(dns_lookups) == 1 else "127.0.0.1"
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, port),
            )
        ]

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        destination = request.url.host
        if destination == "maps.example.com":
            destination = str(
                socket.getaddrinfo(
                    destination,
                    request.url.port or 443,
                    type=socket.SOCK_STREAM,
                )[0][4][0]
            )
        destinations.append(destination)
        return httpx.Response(
            200,
            content=b"png-tile",
            headers={"Content-Type": "image/png"},
        )

    monkeypatch.setattr(socket, "getaddrinfo", rebind_host)
    unit_of_work = InMemoryUnitOfWork()
    storage = TrackingStorage(LocalFileObjectStore(tmp_path / "objects"))
    service = ArtifactService(
        unit_of_work, storage, availability=ArtifactAvailability(unit_of_work, storage)
    )
    production_client = cast(httpx.AsyncClient, getattr(service, "_wms_client"))
    await production_client.aclose()
    monkeypatch.setattr(
        service,
        "_wms_client",
        httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    try:
        wms_layer = await _inline_artifact(
            unit_of_work,
            LAYER_KEY,
            {
                "title": "Public WMS",
                "visible": True,
                "opacity": 1.0,
                "min_zoom": 0,
                "max_zoom": 22,
                "source": {
                    "kind": "wms",
                    "url": "https://maps.example.com/wms",
                    "layer": "public",
                    "version": "1.3.0",
                    "format": "image/png",
                    "bounds": [0.0, 0.0, 1.0, 1.0],
                    "attribution": "Public",
                    "style_name": None,
                },
                "style": _raster_style(),
            },
        )

        tile = await service.load_raster_tile(
            wms_layer,
            workspace_id=WORKSPACE_ID,
            z=0,
            x=0,
            y=0,
        )
    finally:
        await service.close()

    assert tile is not None
    assert tile.content == b"png-tile"
    assert dns_lookups == ["maps.example.com"]
    assert destinations == ["93.184.216.34"]
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "maps.example.com"
    assert requests[0].headers["connection"] == "close"
    assert requests[0].extensions["sni_hostname"] == "maps.example.com"


def test_raster_tilejson_and_tiles_read_only_precomputed_xyz_objects(
    geo_artifact_client: tuple[TestClient, InMemoryUnitOfWork, TrackingStorage],
) -> None:
    client, unit_of_work, storage = geo_artifact_client
    api = GrafyApi(client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts
    raster = asyncio.run(_raster_artifact(unit_of_work, storage))
    storage.loaded_paths.clear()
    storage.range_requests.clear()

    tilejson = artifacts.raster_tilejson(raster.id)
    tile = artifacts.raster_tile(raster.id, z=2, x=2, y=1)
    blank = artifacts.raster_tile(raster.id, z=2, x=1, y=1)

    assert tilejson.status_code == 200
    assert tilejson.json()["minzoom"] == 2
    assert tilejson.json()["maxzoom"] == 6
    assert tilejson.json()["bounds"] == [10.0, 10.0, 20.0, 20.0]
    assert tilejson.json()["tiles"] == [
        f"/api/v1/workspaces/00000000-0000-0000-0000-000000000007/artifacts/{raster.id}/geo/raster/{{z}}/{{x}}/{{y}}.png"
    ]
    assert tile.status_code == 200
    assert tile.content == b"png-tile"
    assert tile.headers["content-type"] == "image/png"
    assert tile.headers["cache-control"].endswith("immutable")
    assert blank.status_code == 404
    assert storage.loaded_paths == []
    assert storage.range_requests == [
        ("geo.raster_scan/v1/projections/source/xyz/2/2/1.png", 0, 8)
    ]


def test_render_rejects_stale_refs_and_private_wms_hosts(
    geo_artifact_client: tuple[TestClient, InMemoryUnitOfWork, TrackingStorage],
) -> None:
    client, unit_of_work, storage = geo_artifact_client
    api = GrafyApi(client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts
    source = asyncio.run(
        _feature_artifact(
            unit_of_work,
            storage,
            source_name="Points",
            features=[_point_feature(1, 1.0, 1.0)],
            bounds=(1.0, 1.0, 1.0, 1.0),
        )
    )
    stale_ref = _ref(source)
    stale_ref["content_hash"] = "0" * 64
    stale_layer = asyncio.run(
        _inline_artifact(
            unit_of_work,
            LAYER_KEY,
            {
                "title": "Stale",
                "visible": True,
                "opacity": 1.0,
                "min_zoom": 0,
                "max_zoom": 22,
                "source": {
                    "kind": "feature_collection",
                    "artifact": stale_ref,
                },
                "style": _vector_style(),
            },
        )
    )
    private_wms = asyncio.run(
        _inline_artifact(
            unit_of_work,
            LAYER_KEY,
            {
                "title": "Private WMS",
                "visible": True,
                "opacity": 1.0,
                "min_zoom": 0,
                "max_zoom": 22,
                "source": {
                    "kind": "wms",
                    "url": "http://127.0.0.1/wms",
                    "layer": "private",
                    "version": "1.3.0",
                    "format": "image/png",
                    "bounds": [0.0, 0.0, 1.0, 1.0],
                    "attribution": "Private",
                    "style_name": None,
                },
                "style": _raster_style(),
            },
        )
    )

    stale = artifacts.geo_render(stale_layer.id)
    private = artifacts.geo_render(private_wms.id)

    assert stale.status_code == 500
    assert "does not match" in stale.json()["detail"]
    assert private.status_code == 500
    assert "render descriptor" in private.json()["detail"]


def test_geo_page_route_is_removed(
    geo_artifact_client: tuple[TestClient, InMemoryUnitOfWork, TrackingStorage],
) -> None:
    client, _, _ = geo_artifact_client

    response = client.get(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/artifacts/00000000-0000-0000-0000-000000000000/geo/page"
    )

    assert response.status_code == 404

import json
import math
import socket
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx
import grafy_plugin_gis.wfs as wfs_module
import pytest
from pydantic import ValidationError

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence, ArtifactTypeSpec
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.domain.staged_uploads import StagedUpload
from grafy_core.nodes import NodeExecutionContext
from grafy_core.table_contracts import (
    TABLE_DATA,
    Table,
    TableColumn,
    TableValueType,
)
from grafy_workbench.table import TABLES
from grafy_core.plugins import (
    NodeHttpEgressInput,
    PluginRegistry,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.object_set_bundle import (
    PORTABLE_BUNDLE_METADATA_KEY,
    PortableArtifactBundleMetadata,
)
from grafy_core.runtime.persistence import ArtifactWriteContext
from grafy_storage import LocalFileObjectStore
from grafy_plugin_gis.artifacts import (
    GEO_FEATURE_COLLECTION,
    GEO_MAP_DOCUMENT,
    GEO_MAP_LAYER,
    GEO_RASTER_SCAN,
)
from grafy_plugin_gis.gdal import GdalCli, GdalError
from grafy_plugin_gis.models import (
    GeoCategorizedPointStyle,
    GeoFeatureArtifactSource,
    GeoFeatureCollection,
    GeoMapLayer,
    GeoRasterStyle,
    GeoVectorStyle,
    RasterProjectionMetadata,
    VectorProjectionMetadata,
)
from grafy_plugin_gis.nodes import (
    ComposeMapConfig,
    ComposeMapInput,
    GeoFeaturesToTableConfig,
    GeoFeaturesToTableError,
    GeoFeaturesToTableInput,
    GeoJsonUploadConfig,
    GeoJsonUploadError,
    GeoJsonUploadInput,
    GeoJsonUploadItem,
    GeoTiffUploadConfig,
    GeoTiffUploadInput,
    GeoTiffUploadItem,
    ImportGeoJsonNode,
    ImportGeoTiffNode,
    ImportWfsNode,
    RasterLayerConfig,
    RasterLayerInput,
    TableToGeoFeaturesConfig,
    TableToGeoFeaturesError,
    TableToGeoFeaturesInput,
    VectorLayerConfig,
    VectorLayerInput,
    WfsImportConfig,
    WfsImportInput,
    WFS_IMPORT_MAX_FEATURES,
    WmsLayerConfig,
    WmsLayerInput,
    build_raster_layer,
    build_vector_layer,
    build_wms_layer,
    compose_map,
    geo_features_to_table,
    table_to_geo_features,
)
from grafy_plugin_gis.plugin import GIS
from grafy_plugin_gis.persistence import (
    FeatureCollectionOutputWriter,
    FeatureCollectionResolver,
    RasterScanOutputWriter,
    RasterScanResolver,
)
from grafy_plugin_gis.wfs import WfsClient, WfsImportError


TEST_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


def feature_collection(*coordinates: tuple[float, float]) -> bytes:
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": index,
                    "properties": {"name": f"place-{index}"},
                    "geometry": {"type": "Point", "coordinates": list(position)},
                }
                for index, position in enumerate(coordinates)
            ],
        }
    ).encode("utf-8")


def artifact_ref(artifact_type: ArtifactTypeSpec) -> ArtifactRef:
    return ArtifactRef.from_key(artifact_id=uuid4(), key=artifact_type.key)


async def seed_staged_upload(
    unit_of_work: InMemoryUnitOfWork,
    *,
    workspace_id: UUID,
    upload_key: str,
    filename: str,
    byte_size: int,
) -> None:
    async with unit_of_work as entered:
        await entered.staged_uploads.add(
            StagedUpload(
                workspace_id=workspace_id,
                upload_key=upload_key,
                original_filename=filename,
                byte_size=byte_size,
            )
        )
        await entered.commit()


async def import_geojson(
    uploads_dir: Path,
    *,
    filename: str,
    content: bytes,
) -> GeoFeatureCollection:
    workspace_uploads = uploads_dir / str(TEST_WORKSPACE_ID)
    workspace_uploads.mkdir(parents=True, exist_ok=True)
    upload_key = f"staged-{filename}"
    (workspace_uploads / upload_key).write_bytes(content)
    uow = InMemoryUnitOfWork()
    await seed_staged_upload(
        uow,
        workspace_id=TEST_WORKSPACE_ID,
        upload_key=upload_key,
        filename=filename,
        byte_size=len(content),
    )
    result = await ImportGeoJsonNode(uploads_dir, unit_of_work=uow).run(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="import"),
        GeoJsonUploadConfig(
            uploads=[
                GeoJsonUploadItem(
                    upload_key=upload_key,
                    filename=filename,
                    byte_size=len(content),
                )
            ]
        ),
        GeoJsonUploadInput(),
    )
    return result.features


def write_geotiff(path: Path) -> bytes:
    subprocess.run(
        [
            "gdal_create",
            "-of",
            "GTiff",
            "-outsize",
            "64",
            "64",
            "-bands",
            "3",
            "-burn",
            "100",
            "-burn",
            "150",
            "-burn",
            "200",
            "-a_srs",
            "EPSG:4326",
            "-a_ullr",
            "13",
            "53",
            "14",
            "52",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return path.read_bytes()


def test_gis_registers_exact_sources_lightweight_layers_and_documents() -> None:
    registry = PluginRegistry()
    registry.install(TABLES)
    registry.install(GIS)
    registry.freeze()

    assert GIS.slug == "external.gis"
    assert {artifact.key for artifact in GIS.artifact_types} == {
        GEO_FEATURE_COLLECTION.key,
        GEO_RASTER_SCAN.key,
        GEO_MAP_LAYER.key,
        GEO_MAP_DOCUMENT.key,
    }
    assert (
        registry.node_registration("gis.geojson.upload", 1)
        .node_class.output_contract.ports["features"]
        .produces
        == GEO_FEATURE_COLLECTION.key
    )
    assert (
        registry.node_registration("gis.geotiff.upload", 1)
        .node_class.output_contract.ports["raster"]
        .produces
        == GEO_RASTER_SCAN.key
    )
    vector_source = registry.node_registration(
        "gis.map.vector_layer", 1
    ).node_class.input_contract.ports["features"]
    assert vector_source.accepts == GEO_FEATURE_COLLECTION.key
    assert vector_source.preserves_ref_container is True
    compose_layers = registry.node_registration(
        "gis.map.compose", 1
    ).node_class.input_contract.ports["layers"]
    assert compose_layers.accepts == GEO_MAP_LAYER.key
    assert compose_layers.shape.value == "many"
    assert compose_layers.preserves_ref_container is True
    table_input = registry.node_registration(
        "gis.table.to_features", 1
    ).node_class.input_contract.ports["table"]
    assert table_input.accepts == TABLE_DATA.key
    feature_table_output = registry.node_registration(
        "gis.features.to_table", 1
    ).node_class.output_contract.ports["table"]
    assert feature_table_output.produces == TABLE_DATA.key


def test_wfs_import_declares_its_configured_http_egress_contract() -> None:
    registry = PluginRegistry()
    registry.install(GIS)

    registration = registry.node_registration("gis.wfs.import", 1)

    assert registration.required_capabilities == (
        PluginRuntimeCapability.NETWORK_EGRESS,
    )
    assert registration.http_egress is not None
    assert registration.http_egress.configured_inputs == (
        NodeHttpEgressInput(config_field="service_url"),
    )
    assert registration.http_egress.dynamic_destinations is False


def test_bounds_config_schemas_describe_fixed_wgs84_positions() -> None:
    expected_positions = [
        {
            "type": "number",
            "title": "West longitude",
            "minimum": -180.0,
            "maximum": 180.0,
        },
        {
            "type": "number",
            "title": "South latitude",
            "minimum": -90.0,
            "maximum": 90.0,
        },
        {
            "type": "number",
            "title": "East longitude",
            "minimum": -180.0,
            "maximum": 180.0,
        },
        {
            "type": "number",
            "title": "North latitude",
            "minimum": -90.0,
            "maximum": 90.0,
        },
    ]
    description = (
        "WGS84 bounds ordered as west longitude, south latitude, east longitude, "
        "north latitude."
    )

    wms_schema = WmsLayerConfig.model_json_schema()
    compose_schema = ComposeMapConfig.model_json_schema()
    wfs_schema = WfsImportConfig.model_json_schema()
    wms_bounds = wms_schema["properties"]["bounds"]
    compose_bounds = compose_schema["properties"]["initial_bounds"]
    wfs_bounds = wfs_schema["properties"]["bbox"]
    fixed_bounds_schemas = [
        wms_bounds,
        compose_bounds["anyOf"][0],
        wfs_bounds["anyOf"][0],
    ]

    for bounds_schema in fixed_bounds_schemas:
        assert bounds_schema["type"] == "array"
        assert bounds_schema["minItems"] == 4
        assert bounds_schema["maxItems"] == 4
        assert bounds_schema["prefixItems"] == expected_positions
        assert bounds_schema["description"] == description

    assert "anyOf" not in wms_bounds
    assert "bounds" in wms_schema["required"]
    assert compose_bounds["anyOf"][1] == {"type": "null"}
    assert compose_bounds["default"] is None
    assert "initial_bounds" not in compose_schema.get("required", [])
    assert wfs_bounds["anyOf"][1] == {"type": "null"}
    assert wfs_bounds["default"] is None
    assert "bbox" not in wfs_schema.get("required", [])


@pytest.mark.asyncio
async def test_features_to_table_preserves_ids_properties_and_exact_wkt() -> None:
    collection = GeoFeatureCollection.from_features(
        [
            {
                "type": "Feature",
                "id": "symbol.1",
                "properties": {
                    "transcription": "Choczeń",
                    "type": 9,
                    "metadata": {"reference": "Narodzicze"},
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [27.89543, 51.48218],
                },
            },
            {
                "type": "Feature",
                "id": "symbol.2",
                "properties": {
                    "transcription": "Other",
                    "type": 7,
                    "metadata": None,
                },
                "geometry": None,
            },
        ],
        "Chrzanowski symbols",
    )

    result = await geo_features_to_table(
        GeoFeaturesToTableConfig(),
        GeoFeaturesToTableInput(features=collection),
    )

    assert [column.id for column in result.table.columns] == [
        "feature_id",
        "transcription",
        "type",
        "metadata",
        "geometry_wkt",
    ]
    assert [column.value_type for column in result.table.columns] == [
        TableValueType.TEXT,
        TableValueType.TEXT,
        TableValueType.INTEGER,
        TableValueType.JSON,
        TableValueType.TEXT,
    ]
    assert result.table.rows[0] == {
        "feature_id": "symbol.1",
        "transcription": "Choczeń",
        "type": 9,
        "metadata": {"reference": "Narodzicze"},
        "geometry_wkt": "POINT (27.89543 51.48218)",
    }
    assert result.table.rows[1]["metadata"] is None
    assert result.table.rows[1]["geometry_wkt"] is None

    round_trip = await table_to_geo_features(
        TableToGeoFeaturesConfig(
            geometry_column="geometry_wkt",
            source_crs="EPSG:4326",
            feature_id_column="feature_id",
            source_name="Filtered symbols",
        ),
        TableToGeoFeaturesInput(table=result.table),
    )
    assert round_trip.features.features == collection.features


@pytest.mark.asyncio
async def test_features_to_table_reports_reserved_property_collision() -> None:
    collection = GeoFeatureCollection.from_features(
        [
            {
                "type": "Feature",
                "properties": {"geometry_wkt": "source value"},
                "geometry": {"type": "Point", "coordinates": [20.0, 50.0]},
            }
        ],
        "Colliding source",
    )

    with pytest.raises(GeoFeaturesToTableError, match="choose different column names"):
        await geo_features_to_table(
            GeoFeaturesToTableConfig(),
            GeoFeaturesToTableInput(features=collection),
        )


@pytest.mark.asyncio
async def test_table_to_features_keeps_exact_wkt_and_normalizes_to_wgs84() -> None:
    table = Table(
        columns=[
            TableColumn(id="column_1", title="wkt", value_type=TableValueType.TEXT),
            TableColumn(
                id="column_2", title="objectid", value_type=TableValueType.INTEGER
            ),
            TableColumn(id="column_3", title="name", value_type=TableValueType.TEXT),
        ],
        rows=[
            {
                "column_1": (
                    "MULTIPOLYGON (((0 0, 27829.87269831839 20, "
                    "55659.74539663678 0, 83489.61809495518 -20, "
                    "111319.49079327357 0, 111319.49079327357 111325.1428663851, "
                    "0 111325.1428663851, 0 0)))"
                ),
                "column_2": 274,
                "column_3": "sample county",
            }
        ],
    )

    result = await table_to_geo_features(
        TableToGeoFeaturesConfig(
            geometry_column="wkt",
            source_crs="EPSG:3857",
            feature_id_column="objectid",
            source_name="Counties",
        ),
        TableToGeoFeaturesInput(table=table),
    )

    feature = result.features.features[0]
    assert feature["id"] == 274
    assert feature["properties"] == {"column_3": "sample county"}
    geometry = feature["geometry"]
    assert isinstance(geometry, dict)
    assert geometry["type"] == "MultiPolygon"
    coordinates = cast(list[object], geometry["coordinates"])
    ring = cast(list[object], cast(list[object], coordinates[0])[0])
    assert len(ring) == 8
    assert result.features.crs == "EPSG:4326"
    assert result.features.source_name == "Counties"
    assert result.features.bounds is not None
    assert all(
        math.isclose(actual, expected, abs_tol=0.0002)
        for actual, expected in zip(result.features.bounds, (0.0, -0.00018, 1.0, 1.0))
    )

    with pytest.raises(ValidationError, match="simplify_tolerance"):
        TableToGeoFeaturesConfig.model_validate(
            {
                "geometry_column": "wkt",
                "source_crs": "EPSG:3857",
                "simplify_tolerance": 250,
            }
        )


@pytest.mark.asyncio
async def test_table_wkt_error_identifies_row_and_column() -> None:
    table = Table(
        columns=[
            TableColumn(id="geometry", title="wkt", value_type=TableValueType.TEXT)
        ],
        rows=[{"geometry": "not valid wkt"}],
    )

    with pytest.raises(
        TableToGeoFeaturesError,
        match="table row 0, geometry column 'wkt'",
    ):
        await table_to_geo_features(
            TableToGeoFeaturesConfig(
                geometry_column="wkt",
                source_crs="EPSG:4326",
            ),
            TableToGeoFeaturesInput(table=table),
        )


@pytest.mark.asyncio
async def test_geojson_upload_validates_exact_wgs84_source(tmp_path: Path) -> None:
    collection = await import_geojson(
        tmp_path / "uploads",
        filename="cities.geojson",
        content=feature_collection((13.405, 52.52), (2.3522, 48.8566)),
    )
    assert collection.bounds == (2.3522, 48.8566, 13.405, 52.52)

    with pytest.raises(GeoJsonUploadError, match="outside WGS84"):
        await import_geojson(
            tmp_path / "other-uploads",
            filename="projected.geojson",
            content=feature_collection((4_000_000, 5_000_000)),
        )


@pytest.mark.asyncio
async def test_geojson_upload_fails_closed_without_db_row(tmp_path: Path) -> None:
    uploads_dir = tmp_path / "uploads"
    workspace_uploads = uploads_dir / str(TEST_WORKSPACE_ID)
    workspace_uploads.mkdir(parents=True)
    content = feature_collection((13.405, 52.52))
    upload_key = "orphan.geojson"
    (workspace_uploads / upload_key).write_bytes(content)

    with pytest.raises(GeoJsonUploadError, match="was not found in workspace"):
        await ImportGeoJsonNode(
            uploads_dir,
            unit_of_work=InMemoryUnitOfWork(),
        ).run(
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="import"),
            GeoJsonUploadConfig(
                uploads=[
                    GeoJsonUploadItem(
                        upload_key=upload_key,
                        filename="orphan.geojson",
                        byte_size=len(content),
                    )
                ]
            ),
            GeoJsonUploadInput(),
        )


@pytest.mark.asyncio
async def test_builds_typed_vector_raster_and_wms_layers() -> None:
    features_ref = artifact_ref(GEO_FEATURE_COLLECTION)
    raster_ref = artifact_ref(GEO_RASTER_SCAN)

    vector = await build_vector_layer(
        VectorLayerConfig(
            title="Cities",
            opacity=0.75,
            style=GeoVectorStyle.model_validate(
                {
                    "point": {"color": "#ef4444", "radius": 8},
                    "label": {"property": "name"},
                }
            ),
        ),
        VectorLayerInput(features=features_ref),
    )
    categorized = await build_vector_layer(
        VectorLayerConfig(
            title="Historical symbols",
            style=GeoCategorizedPointStyle.model_validate(
                {
                    "category_property": "type",
                    "categories": [
                        {
                            "id": "cities",
                            "title": "Cities and towns",
                            "values": [1, 2, 3],
                            "point": {"color": "#b91c1c", "radius": 7},
                            "min_zoom": 6,
                        },
                        {
                            "id": "villages",
                            "title": "Villages",
                            "values": [5, 7, 8, 9, 10],
                            "point": {"color": "#d6a700", "radius": 4},
                            "min_zoom": 10,
                        },
                    ],
                    "label": {"property": "transcription"},
                }
            ),
        ),
        VectorLayerInput(features=features_ref),
    )
    raster = await build_raster_layer(
        RasterLayerConfig(
            title="Historical scan",
            opacity=0.6,
            style=GeoRasterStyle(contrast=0.25, resampling="nearest"),
        ),
        RasterLayerInput(raster=raster_ref),
    )
    wms = await build_wms_layer(
        WmsLayerConfig.model_validate(
            {
                "title": "Atlas Fontium",
                "url": "https://data.atlasfontium.pl/geoserver/ows",
                "layer": "geonode:a__54_map_1822_mosaicked_P1nn",
                "bounds": (20.9515, 52.1942, 21.0711, 52.2788),
                "attribution": "Atlas Fontium",
                "style": GeoRasterStyle(opacity=0.8, saturation=-0.2),
            }
        ),
        WmsLayerInput(),
    )

    assert vector.layer.source.kind == "feature_collection"
    assert vector.layer.style.kind == "vector"
    assert vector.layer.style.point.radius == 8
    assert categorized.layer.source.kind == "feature_collection"
    assert categorized.layer.style.kind == "categorized_points"
    assert categorized.layer.style.category_property == "type"
    assert categorized.layer.style.categories[1].min_zoom == 10
    assert raster.layer.source.kind == "raster_scan"
    assert raster.layer.style.kind == "raster"
    assert raster.layer.style.resampling == "nearest"
    assert wms.layer.source.kind == "wms"
    assert wms.layer.source.layer.startswith("geonode:")

    with pytest.raises(ValidationError, match="require vector style"):
        GeoMapLayer(
            title="Invalid",
            source=GeoFeatureArtifactSource(artifact=features_ref),
            style=GeoRasterStyle(),
        )
    with pytest.raises(
        ValidationError,
        match="category values must not appear in multiple categories",
    ):
        GeoCategorizedPointStyle.model_validate(
            {
                "category_property": "type",
                "categories": [
                    {"id": "first", "title": "First", "values": [1, 2]},
                    {"id": "second", "title": "Second", "values": [2, 3]},
                ],
            }
        )
    with pytest.raises(ValidationError, match="query-free service endpoint"):
        WmsLayerConfig.model_validate(
            {
                "title": "Secret URL",
                "url": "https://example.com/wms?token=secret",
                "layer": "example",
                "bounds": (0, 0, 1, 1),
                "attribution": "Example",
            }
        )
    with pytest.raises(ValidationError, match="must not target"):
        WmsLayerConfig.model_validate(
            {
                "title": "Private service",
                "url": "http://127.0.0.1/wms",
                "layer": "example",
                "bounds": (0, 0, 1, 1),
                "attribution": "Example",
            }
        )


@pytest.mark.asyncio
async def test_compose_map_preserves_ordered_layer_refs() -> None:
    first = artifact_ref(GEO_MAP_LAYER)
    second = artifact_ref(GEO_MAP_LAYER)
    sequence = ArtifactRefSequence.from_key(
        key=GEO_MAP_LAYER.key,
        item_refs=[first, second],
    )

    result = await compose_map(
        ComposeMapConfig(
            basemap="openstreetmap",
            initial_bounds=(13.0, 52.0, 14.0, 53.0),
        ),
        ComposeMapInput(layers=sequence),
    )
    assert result.map.layers == [first, second]
    assert result.map.initial_bounds == (13.0, 52.0, 14.0, 53.0)

    with pytest.raises(ValidationError, match="requires an ordered"):
        ComposeMapInput(
            layers=ArtifactRefSequence(
                artifact_type=GEO_MAP_LAYER.key.id,
                schema_version=GEO_MAP_LAYER.key.schema_version,
                item_refs=[first],
                ordered=False,
            )
        )


@pytest.mark.asyncio
async def test_wfs_import_default_page_limit_rejects_oversized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_page_limit = 16 * 1024 * 1024
    config = WfsImportConfig.model_validate(
        {
            "service_url": "https://example.com/geoserver/ows",
            "type_name": "geonode:large",
            "source_name": "Large",
            "page_size": 1,
            "max_features": 1,
        }
    )
    validated_config = WfsImportConfig.model_validate(config.model_dump())

    assert config.max_page_bytes == default_page_limit
    assert validated_config.max_page_bytes == default_page_limit

    def resolve_public_host(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[object, object, object, str, tuple[str, int]]]:
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("93.184.216.34", port),
            )
        ]

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (default_page_limit + 1))

    monkeypatch.setattr(socket, "getaddrinfo", resolve_public_host)

    node = ImportWfsNode(WfsClient(transport=httpx.MockTransport(respond)))
    with pytest.raises(
        WfsImportError,
        match=rf"geonode:large.*{default_page_limit}-byte page limit",
    ):
        await node.run(
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="wfs"),
            config,
            WfsImportInput(),
        )


@pytest.mark.parametrize(
    ("max_features", "message"),
    [
        (None, "unbounded WFS imports are not supported"),
        (WFS_IMPORT_MAX_FEATURES + 1, "first-release limit of 10000"),
    ],
)
def test_wfs_import_requires_a_bounded_total_feature_limit(
    max_features: int | None,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        WfsImportConfig.model_validate(
            {
                "service_url": "https://example.com/geoserver/ows",
                "type_name": "geonode:large",
                "source_name": "Large",
                "max_features": max_features,
            }
        )


@pytest.mark.asyncio
async def test_wfs_import_routes_through_the_broker_without_guest_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[httpx.URL] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(request.url)
        payload = json.loads(feature_collection([(13.4, 52.5)]))
        payload["numberMatched"] = 1
        payload["numberReturned"] = 1
        return httpx.Response(200, json=payload)

    monkeypatch.setenv("GRAFY_PLUGIN_PROXY", "http://127.0.0.1:3128")

    def fail_if_resolving(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("broker mode must not resolve DNS in the guest")

    monkeypatch.setattr(socket, "getaddrinfo", fail_if_resolving)

    node = ImportWfsNode(WfsClient(transport=httpx.MockTransport(respond)))
    result = await node.run(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="wfs"),
        WfsImportConfig.model_validate(
            {
                "service_url": "https://example.com/geoserver/ows",
                "type_name": "geonode:roads",
                "source_name": "Roads",
                "max_features": 1,
            }
        ),
        WfsImportInput(),
    )

    assert len(result.features.features) == 1
    assert len(requested) == 1
    assert requested[0].raw_host == b"example.com"
    assert requested[0].path == "/geoserver/ows"
    assert requested[0].params["startIndex"] == "0"


@pytest.mark.asyncio
async def test_wfs_import_fetches_bounded_epsg4326_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starts: list[int] = []

    def resolve_public_host(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[object, object, object, str, tuple[str, int]]]:
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("93.184.216.34", port),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", resolve_public_host)

    def respond(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        start_index = int(params["startIndex"])
        starts.append(start_index)
        assert params["service"] == "WFS"
        assert params["version"] == "2.0.0"
        assert params["srsName"] == "EPSG:4326"
        assert params["outputFormat"] == "application/json"
        assert params["sortBy"] == "id"
        coordinates = (
            [(13.4, 52.5), (13.5, 52.6)] if start_index == 0 else [(13.6, 52.7)]
        )
        payload = json.loads(feature_collection(*coordinates))
        payload["numberMatched"] = 3
        payload["numberReturned"] = len(coordinates)
        return httpx.Response(200, json=payload)

    node = ImportWfsNode(WfsClient(transport=httpx.MockTransport(respond)))
    result = await node.run(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="wfs"),
        WfsImportConfig.model_validate(
            {
                "service_url": "https://example.com/geoserver/ows",
                "type_name": "geonode:miejscowosci",
                "source_name": "Miejscowości",
                "sort_by": "id",
                "page_size": 2,
                "max_features": 3,
            }
        ),
        WfsImportInput(),
    )

    assert starts == [0, 2]
    assert len(result.features.features) == 3
    assert result.features.bounds == (13.4, 52.5, 13.6, 52.7)

    with pytest.raises(ValidationError, match="must not target"):
        WfsImportConfig.model_validate(
            {
                "service_url": "http://192.168.1.50/wfs",
                "type_name": "private:features",
                "source_name": "Private",
            }
        )
    with pytest.raises(WfsImportError, match="Rejected WFS.*127.0.0.1"):
        await WfsClient().fetch_feature_collection(
            service_url="http://127.0.0.1/wfs",
            type_name="private:features",
            source_name="Private",
            page_size=10,
            max_features=10,
            max_page_bytes=1_024,
            timeout_seconds=1,
            bbox=None,
        )


@pytest.mark.asyncio
async def test_wfs_import_pins_validated_address_against_dns_rebinding(
    monkeypatch: pytest.MonkeyPatch,
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
        if destination == "example.com":
            destination = str(
                socket.getaddrinfo(
                    destination,
                    request.url.port or 443,
                    type=socket.SOCK_STREAM,
                )[0][4][0]
            )
        destinations.append(destination)
        return httpx.Response(200, content=feature_collection((13.4, 52.5)))

    monkeypatch.setattr(socket, "getaddrinfo", rebind_host)

    result = await WfsClient(
        transport=httpx.MockTransport(respond)
    ).fetch_feature_collection(
        service_url="https://example.com/geoserver/ows",
        type_name="geonode:public",
        source_name="Public",
        page_size=1,
        max_features=1,
        max_page_bytes=1_024,
        timeout_seconds=1,
        bbox=None,
    )

    assert len(result.features) == 1
    assert dns_lookups == ["example.com"]
    assert destinations == ["93.184.216.34"]
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "example.com"
    assert requests[0].extensions["sni_hostname"] == "example.com"


@pytest.mark.asyncio
async def test_wfs_import_rejects_cumulative_page_bytes_before_appending_next_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starts: list[int] = []
    pages: dict[int, bytes] = {}
    for start_index, coordinates in {
        0: [(13.4, 52.5)],
        1: [(13.6, 52.7)],
    }.items():
        payload = json.loads(feature_collection(*coordinates))
        payload["numberMatched"] = 3
        payload["numberReturned"] = 1
        pages[start_index] = json.dumps(payload).encode("utf-8")
    cumulative_limit = len(pages[0]) + len(pages[1]) - 1

    def resolve_public_host(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[object, object, object, str, tuple[str, int]]]:
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("93.184.216.34", port),
            )
        ]

    def respond(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        start_index = int(params["startIndex"])
        starts.append(start_index)
        return httpx.Response(200, content=pages[start_index])

    monkeypatch.setattr(socket, "getaddrinfo", resolve_public_host)
    monkeypatch.setattr(
        wfs_module,
        "WFS_IMPORT_TOTAL_RESPONSE_MAX_BYTES",
        cumulative_limit,
    )

    with pytest.raises(
        WfsImportError,
        match=(
            rf"geonode:miejscowosci.*startIndex=1.*cumulative response limit of "
            rf"{cumulative_limit} bytes.*received {cumulative_limit + 1}"
        ),
    ):
        await WfsClient(
            transport=httpx.MockTransport(respond)
        ).fetch_feature_collection(
            service_url="https://example.com/geoserver/ows",
            type_name="geonode:miejscowosci",
            source_name="Miejscowości",
            page_size=1,
            max_features=3,
            max_page_bytes=max(len(page) for page in pages.values()),
            timeout_seconds=1,
            bbox=None,
        )

    assert starts == [0, 1]


@pytest.mark.asyncio
async def test_wfs_import_rejects_hostname_resolving_to_any_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def resolve_private_host(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[object, object, object, str, tuple[str, int]]]:
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("93.184.216.34", port),
            ),
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("10.0.0.8", port),
            ),
        ]

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=feature_collection((13.4, 52.5)))

    monkeypatch.setattr(socket, "getaddrinfo", resolve_private_host)

    with pytest.raises(
        WfsImportError,
        match=r"example\.com.*geonode:private.*startIndex=0.*10\.0\.0\.8",
    ):
        await WfsClient(
            transport=httpx.MockTransport(respond)
        ).fetch_feature_collection(
            service_url="https://example.com/geoserver/ows",
            type_name="geonode:private",
            source_name="Private",
            page_size=1,
            max_features=1,
            max_page_bytes=1_024,
            timeout_seconds=1,
            bbox=None,
        )

    assert requests == []


@pytest.mark.asyncio
async def test_wfs_import_rejects_oversized_page_with_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.loads(feature_collection((13.4, 52.5)))
    payload["features"][0]["properties"]["large"] = "x" * 2_000

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    def resolve_public_host(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[object, object, object, str, tuple[str, int]]]:
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("93.184.216.34", port),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", resolve_public_host)

    node = ImportWfsNode(WfsClient(transport=httpx.MockTransport(respond)))
    with pytest.raises(
        WfsImportError,
        match=r"example.com.*geonode:large.*1024-byte page limit",
    ):
        await node.run(
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="wfs"),
            WfsImportConfig.model_validate(
                {
                    "service_url": "https://example.com/geoserver/ows",
                    "type_name": "geonode:large",
                    "source_name": "Large",
                    "page_size": 1,
                    "max_features": 1,
                    "max_page_bytes": 1_024,
                }
            ),
            WfsImportInput(),
        )


@pytest.mark.asyncio
async def test_geotiff_upload_and_raster_persistence_produce_cog_and_xyz_tiles(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    workspace_uploads = uploads / str(TEST_WORKSPACE_ID)
    workspace_uploads.mkdir(parents=True)
    source_content = write_geotiff(workspace_uploads / "source.tif")
    staged_path = workspace_uploads / "staged-raster"
    staged_path.write_bytes(source_content)
    unit_of_work = InMemoryUnitOfWork()
    await seed_staged_upload(
        unit_of_work,
        workspace_id=TEST_WORKSPACE_ID,
        upload_key="staged-raster",
        filename="historical-map.tif",
        byte_size=len(source_content),
    )
    upload = await ImportGeoTiffNode(uploads, unit_of_work=unit_of_work).run(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="upload"),
        GeoTiffUploadConfig(
            uploads=[
                GeoTiffUploadItem(
                    upload_key="staged-raster",
                    filename="historical-map.tif",
                    byte_size=len(source_content),
                )
            ],
            source_name="Historical map",
        ),
        GeoTiffUploadInput(),
    )
    object_root = tmp_path / "objects"
    storage = LocalFileObjectStore(object_root)
    writer = RasterScanOutputWriter(
        storage=storage,
        uow=unit_of_work,
        bucket="test",
        storage_backend="local",
    )
    ref = await writer.write(
        upload.raster,
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=TEST_WORKSPACE_ID,
                node_id="raster",
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )
    async with unit_of_work as uow:
        artifact = await uow.artifacts.get(TEST_WORKSPACE_ID, ref.artifact_id)
    assert artifact is not None
    assert artifact.content_type == (
        "image/tiff; application=geotiff; profile=cloud-optimized"
    )
    assert artifact.bucket == "test"
    assert artifact.object_key is not None
    assert artifact.workspace_id == TEST_WORKSPACE_ID
    assert artifact.object_key.startswith(
        f"workspaces/{TEST_WORKSPACE_ID}/geo.raster_scan/v1/"
    )
    projection = RasterProjectionMetadata.model_validate(
        artifact.metadata["raster_projection"]
    )
    assert projection.kind == "xyz"
    assert projection.bounds == (13.0, 52.0, 14.0, 53.0)
    assert projection.source_crs == "EPSG:4326"
    assert projection.min_zoom <= projection.max_zoom
    assert list((object_root / "test" / projection.prefix).rglob("*.png"))
    portable = PortableArtifactBundleMetadata.model_validate(
        artifact.metadata[PORTABLE_BUNDLE_METADATA_KEY]
    )
    assert portable.files[0].object_key == artifact.object_key
    assert {reference.path for reference in portable.references} == {
        ("raster_projection", "bucket"),
        ("raster_projection", "prefix"),
    }
    assert len(portable.files) > 1

    cog_path = object_root / "test" / artifact.object_key
    info = subprocess.run(
        ["gdalinfo", "-json", str(cog_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(info.stdout)["metadata"]["IMAGE_STRUCTURE"]["LAYOUT"] == "COG"
    resolved = await RasterScanResolver(
        uow=unit_of_work,
        storage=storage,
    ).resolve(ref, TEST_WORKSPACE_ID)
    assert resolved.filename == "historical-map.tif"
    assert sha256(resolved.content).hexdigest() == artifact.sha256


@pytest.mark.asyncio
async def test_feature_collection_storage_keeps_exact_source_and_pmtiles_sidecar(
    tmp_path: Path,
) -> None:
    collection = GeoFeatureCollection.from_geojson_bytes(
        feature_collection((13.405, 52.52)),
        "cities.geojson",
    )
    unit_of_work = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    writer = FeatureCollectionOutputWriter(
        storage=storage,
        uow=unit_of_work,
        bucket="test",
        storage_backend="local",
    )
    ref = await writer.write(
        collection,
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=TEST_WORKSPACE_ID,
                node_id="import",
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )
    resolver = FeatureCollectionResolver(
        uow=unit_of_work,
        storage=storage,
    )

    assert await resolver.resolve(ref, TEST_WORKSPACE_ID) == collection
    async with unit_of_work as uow:
        artifact = await uow.artifacts.get(TEST_WORKSPACE_ID, ref.artifact_id)
    assert artifact is not None
    assert artifact.inline_payload is None
    assert artifact.content_type == "application/geo+json"
    assert artifact.workspace_id == TEST_WORKSPACE_ID
    assert artifact.object_key is not None
    assert artifact.object_key.startswith(
        f"workspaces/{TEST_WORKSPACE_ID}/geo.feature_collection/v1/"
    )
    assert artifact.metadata["property_fields"] == [
        {"id": "name", "title": "name", "value_type": "text"}
    ]
    projection = VectorProjectionMetadata.model_validate(
        artifact.metadata["vector_projection"]
    )
    assert projection.source_layer == "features"
    assert (
        await storage.load_range(
            projection.bucket,
            projection.object_key,
            0,
            7,
        )
        == b"PMTiles"
    )
    portable = PortableArtifactBundleMetadata.model_validate(
        artifact.metadata[PORTABLE_BUNDLE_METADATA_KEY]
    )
    assert projection.object_key in {file.object_key for file in portable.files}
    assert {reference.path for reference in portable.references} == {
        ("vector_projection", "bucket"),
        ("vector_projection", "object_key"),
    }


@pytest.mark.asyncio
async def test_empty_feature_source_is_exact_without_invalid_pmtiles(
    tmp_path: Path,
) -> None:
    collection = GeoFeatureCollection(
        features=[],
        source_name="Empty",
        bounds=None,
    )
    unit_of_work = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    ref = await FeatureCollectionOutputWriter(
        storage=storage,
        uow=unit_of_work,
        bucket="test",
        storage_backend="local",
    ).write(
        collection,
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=TEST_WORKSPACE_ID,
                node_id="empty",
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )

    async with unit_of_work as uow:
        artifact = await uow.artifacts.get(TEST_WORKSPACE_ID, ref.artifact_id)
    assert artifact is not None
    assert artifact.metadata["feature_count"] == 0
    assert "vector_projection" not in artifact.metadata
    portable = PortableArtifactBundleMetadata.model_validate(
        artifact.metadata[PORTABLE_BUNDLE_METADATA_KEY]
    )
    assert portable.references == ()
    assert len(portable.files) == 1


@pytest.mark.asyncio
async def test_missing_gdal_driver_error_preserves_source_and_node_context(
    tmp_path: Path,
) -> None:
    collection = GeoFeatureCollection.from_geojson_bytes(
        feature_collection((13.405, 52.52)),
        "cities.geojson",
    )
    writer = FeatureCollectionOutputWriter(
        storage=LocalFileObjectStore(tmp_path / "objects"),
        uow=InMemoryUnitOfWork(),
        bucket="test",
        storage_backend="local",
        gdal=GdalCli(ogr2ogr="missing-grafy-ogr2ogr"),
    )

    with pytest.raises(
        RuntimeError,
        match=r"PMTiles.*cities.geojson.*node 'feature-node'",
    ) as error:
        await writer.write(
            collection,
            ArtifactWriteContext(
                node_context=NodeExecutionContext(
                    workspace_id=TEST_WORKSPACE_ID,
                    node_id="feature-node",
                ),
                provenance=MaterializationProvenance(refs_by_input={}),
            ),
        )
    assert isinstance(error.value.__cause__, GdalError)

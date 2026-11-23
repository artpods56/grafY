"""The replacement file nodes turn a persisted file.* artifact into a value.

Ingest writes the bytes and never interprets them, so each test seeds the exact
`file.*` artifact the upload path produces and then runs the visible node.
"""

import json
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from grafy_core.artifact_contracts import RASTER_IMAGE
from grafy_core.artifacts import (
    ArtifactObject,
)
from grafy_core.documents import FILE_ARTIFACTS
from grafy_core.file_contracts import (
    BMP_FILE,
    CSV_FILE,
    GEOJSON_FILE,
    JPEG_FILE,
    JSON_FILE,
    PNG_FILE,
    TIFF_FILE,
    WEBP_FILE,
    XLSX_FILE,
)
from grafy_core.nodes import NodeExecutionContext
from grafy_core.plugins import PluginRegistry
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.artifact_values import ArtifactValues
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.resolvers import ArtifactContractError
from grafy_core.table_contracts import TABLE_DATA
from grafy_plugin_gis.artifacts import (
    GEO_FEATURE_COLLECTION,
    GEO_MAP_LAYER,
)
from grafy_plugin_gis.nodes import (
    GeoJsonParseError,
    GeoJsonParseInput,
    ParseGeoJsonNode,
)
from grafy_plugin_gis.plugin import GIS
from grafy_storage import LocalFileObjectStore
from grafy_plugin_image import IMAGES
from grafy_workbench.image import IMAGES as IMAGE_ARTIFACTS
from grafy_plugin_table import TABLES
from grafy_workbench.table import TABLES as TABLE_ARTIFACTS
from grafy_plugin_table.nodes import (
    ImportTableNode,
    TableFileImportError,
    TableImportConfig,
    TableImportInput,
)
from openpyxl import Workbook

from tests.support.file_artifacts import seed_file_artifact

TEST_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000930")


def feature_collection_bytes(*coordinates: tuple[float, float]) -> bytes:
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


def workbook_bytes(
    *,
    sheets: dict[str, list[list[object]]],
    active: str,
) -> bytes:
    workbook = Workbook()
    empty = workbook.active
    assert empty is not None
    workbook.remove(empty)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    workbook.active = workbook.sheetnames.index(active)
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def node_context() -> NodeExecutionContext:
    return NodeExecutionContext(
        workspace_id=TEST_WORKSPACE_ID,
        node_id="replacement-file-node",
    )


def file_values(storage: FileStoragePort, uow: InMemoryUnitOfWork) -> ArtifactValues:
    """The declarations the runtime uses to turn a seeded file artifact into a value."""

    return ArtifactValues(
        FILE_ARTIFACTS,
        uow=uow,
        storage=storage,
        bucket="artifacts",
        storage_backend="local",
    )


@pytest.mark.asyncio
async def test_table_import_dispatches_on_the_declared_format_not_the_filename(
    tmp_path: Path,
) -> None:
    storage = LocalFileObjectStore(tmp_path / "objects")
    uow = InMemoryUnitOfWork()
    csv_ref = await seed_file_artifact(
        storage,
        uow,
        workspace_id=TEST_WORKSPACE_ID,
        spec=CSV_FILE,
        content=b"name,population\nBelynichi,10\n",
        original_filename="places.xlsx",
    )
    xlsx_ref = await seed_file_artifact(
        storage,
        uow,
        workspace_id=TEST_WORKSPACE_ID,
        spec=XLSX_FILE,
        content=workbook_bytes(
            sheets={"Places": [["name", "population"], ["Belynichi", 10]]},
            active="Places",
        ),
        original_filename="places.csv",
    )
    node = ImportTableNode()
    csv_document = await file_values(storage, uow).resolve(csv_ref, TEST_WORKSPACE_ID)
    xlsx_document = await file_values(storage, uow).resolve(xlsx_ref, TEST_WORKSPACE_ID)

    csv_output = await node.run(
        node_context(),
        node.config_contract.model.model_validate({}),
        TableImportInput(file=csv_document),
    )
    xlsx_output = await node.run(
        node_context(),
        node.config_contract.model.model_validate({}),
        TableImportInput(file=xlsx_document),
    )

    assert [column.title for column in csv_output.table.columns] == [
        "name",
        "population",
    ]
    assert csv_output.table.rows == [
        {"column_1": "Belynichi", "column_2": "10"},
    ]
    assert [column.title for column in xlsx_output.table.columns] == [
        "name",
        "population",
    ]
    assert xlsx_output.table.rows == [
        {"column_1": "Belynichi", "column_2": 10},
    ]


@pytest.mark.asyncio
async def test_table_import_applies_delimiter_header_and_empty_row_parameters(
    tmp_path: Path,
) -> None:
    storage = LocalFileObjectStore(tmp_path / "objects")
    uow = InMemoryUnitOfWork()
    ref = await seed_file_artifact(
        storage,
        uow,
        workspace_id=TEST_WORKSPACE_ID,
        spec=CSV_FILE,
        content=b"Places of the region\nname;population\nBelynichi;10\n;\n",
    )
    node = ImportTableNode()
    document = await file_values(storage, uow).resolve(ref, TEST_WORKSPACE_ID)

    default_output = await node.run(
        node_context(),
        node.config_contract.model.model_validate({}),
        TableImportInput(file=document),
    )
    configured_output = await node.run(
        node_context(),
        TableImportConfig(delimiter=";", header_row=2, skip_empty_rows=True),
        TableImportInput(file=document),
    )
    kept_output = await node.run(
        node_context(),
        TableImportConfig(delimiter=";", header_row=2, skip_empty_rows=False),
        TableImportInput(file=document),
    )

    assert default_output.table.columns[0].title == "Places of the region"
    assert [column.title for column in configured_output.table.columns] == [
        "name",
        "population",
    ]
    assert configured_output.table.rows == [
        {"column_1": "Belynichi", "column_2": "10"},
    ]
    assert kept_output.table.rows == [
        {"column_1": "Belynichi", "column_2": "10"},
        {"column_1": "", "column_2": ""},
    ]


@pytest.mark.asyncio
async def test_table_import_selects_the_named_sheet_and_rejects_a_zip_without_one(
    tmp_path: Path,
) -> None:
    storage = LocalFileObjectStore(tmp_path / "objects")
    uow = InMemoryUnitOfWork()
    ref = await seed_file_artifact(
        storage,
        uow,
        workspace_id=TEST_WORKSPACE_ID,
        spec=XLSX_FILE,
        content=workbook_bytes(
            sheets={
                "Ignored": [["ignored_header"], ["ignored_row"]],
                "Places": [["name", "population"], ["Belynichi", 10]],
            },
            active="Ignored",
        ),
    )
    broken_ref = await seed_file_artifact(
        storage,
        uow,
        workspace_id=TEST_WORKSPACE_ID,
        spec=XLSX_FILE,
        content=b"PK\x03\x04not-a-workbook",
    )
    node = ImportTableNode()
    document = await file_values(storage, uow).resolve(ref, TEST_WORKSPACE_ID)
    broken_document = await file_values(storage, uow).resolve(
        broken_ref, TEST_WORKSPACE_ID
    )

    active = await node.run(
        node_context(),
        TableImportConfig(),
        TableImportInput(file=document),
    )
    selected = await node.run(
        node_context(),
        TableImportConfig(sheet_name="Places"),
        TableImportInput(file=document),
    )
    assert [column.title for column in active.table.columns] == ["ignored_header"]
    assert active.table.rows == [{"column_1": "ignored_row"}]
    assert selected.table.rows == [{"column_1": "Belynichi", "column_2": 10}]

    with pytest.raises(TableFileImportError, match="no worksheet named 'Missing'"):
        _ = await node.run(
            node_context(),
            TableImportConfig(sheet_name="Missing"),
            TableImportInput(file=document),
        )
    with pytest.raises(TableFileImportError, match="not a readable XLSX workbook"):
        _ = await node.run(
            node_context(),
            TableImportConfig(),
            TableImportInput(file=broken_document),
        )


@pytest.mark.asyncio
async def test_geojson_parse_accepts_both_declared_container_types(
    tmp_path: Path,
) -> None:
    storage = LocalFileObjectStore(tmp_path / "objects")
    uow = InMemoryUnitOfWork()
    geojson_ref = await seed_file_artifact(
        storage,
        uow,
        workspace_id=TEST_WORKSPACE_ID,
        spec=GEOJSON_FILE,
        content=feature_collection_bytes((13.405, 52.52), (2.3522, 48.8566)),
        original_filename="cities.geojson",
    )
    json_ref = await seed_file_artifact(
        storage,
        uow,
        workspace_id=TEST_WORKSPACE_ID,
        spec=JSON_FILE,
        content=feature_collection_bytes((13.405, 52.52)),
        original_filename="cities.json",
    )
    node = ParseGeoJsonNode()
    geojson_document = await file_values(storage, uow).resolve(
        geojson_ref, TEST_WORKSPACE_ID
    )
    json_document = await file_values(storage, uow).resolve(json_ref, TEST_WORKSPACE_ID)

    geojson = await node.run(
        node_context(),
        node.config_contract.model.model_validate({}),
        GeoJsonParseInput(file=geojson_document),
    )
    plain_json = await node.run(
        node_context(),
        node.config_contract.model.model_validate({}),
        GeoJsonParseInput(file=json_document),
    )

    assert geojson.features.source_name == "cities.geojson"
    assert geojson.features.bounds == (2.3522, 48.8566, 13.405, 52.52)
    assert plain_json.features.source_name == "cities.json"
    assert plain_json.features.bounds == (13.405, 52.52, 13.405, 52.52)


@pytest.mark.asyncio
async def test_geojson_parse_validates_the_document_shape_at_run_time(
    tmp_path: Path,
) -> None:
    storage = LocalFileObjectStore(tmp_path / "objects")
    uow = InMemoryUnitOfWork()
    array_ref = await seed_file_artifact(
        storage,
        uow,
        workspace_id=TEST_WORKSPACE_ID,
        spec=JSON_FILE,
        content=b"[1, 2, 3]",
        original_filename="numbers.json",
    )
    projected_ref = await seed_file_artifact(
        storage,
        uow,
        workspace_id=TEST_WORKSPACE_ID,
        spec=GEOJSON_FILE,
        content=feature_collection_bytes((4_000_000.0, 5_000_000.0)),
        original_filename="projected.geojson",
    )
    node = ParseGeoJsonNode()
    array_document = await file_values(storage, uow).resolve(
        array_ref, TEST_WORKSPACE_ID
    )
    projected_document = await file_values(storage, uow).resolve(
        projected_ref, TEST_WORKSPACE_ID
    )

    with pytest.raises(GeoJsonParseError, match="not a valid GeoJSON"):
        _ = await node.run(
            node_context(),
            node.config_contract.model.model_validate({}),
            GeoJsonParseInput(file=array_document),
        )
    with pytest.raises(GeoJsonParseError, match="outside WGS84"):
        _ = await node.run(
            node_context(),
            node.config_contract.model.model_validate({}),
            GeoJsonParseInput(file=projected_document),
        )


@pytest.mark.asyncio
async def test_a_tiff_map_source_is_read_from_the_object_it_already_used(
    tmp_path: Path,
) -> None:
    """A georeferenced TIFF is a map source as stored, with no conversion step."""
    storage = LocalFileObjectStore(tmp_path / "objects")
    uow = InMemoryUnitOfWork()
    original = await seed_file_artifact(
        storage,
        uow,
        workspace_id=TEST_WORKSPACE_ID,
        spec=TIFF_FILE,
        content=b"II*\x00geotiff-bytes",
        original_filename="scan.tif",
    )
    values = file_values(storage, uow)

    resolved = await values.resolve(original, TEST_WORKSPACE_ID)

    assert resolved.filename == "scan.tif"
    assert await resolved.read(max_bytes=64) == b"II*\x00geotiff-bytes"


@pytest.mark.asyncio
async def test_file_artifact_reader_fails_closed_without_stored_bytes() -> None:
    storage = LocalFileObjectStore(Path("/tmp/grafy-missing-store"))
    uow = InMemoryUnitOfWork()
    artifact = ArtifactObject(
        workspace_id=TEST_WORKSPACE_ID,
        artifact_type=CSV_FILE.key.id,
        schema_version=CSV_FILE.key.schema_version,
        content_type="text/csv",
    )
    async with uow as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()

    with pytest.raises(ArtifactContractError, match="has no stored object"):
        await file_values(storage, uow).resolve(artifact.ref(), TEST_WORKSPACE_ID)


def test_replacement_nodes_declare_their_catalog_contracts() -> None:
    registry = PluginRegistry()
    registry.install(IMAGE_ARTIFACTS)
    registry.install(TABLE_ARTIFACTS)
    registry.install(IMAGES)
    registry.install(TABLES)
    registry.install(GIS)
    registry.freeze()

    import_table = registry.node_registration("table.import", 1)
    table_file = import_table.node_class.input_contract.ports["file"]
    assert table_file.accepts == CSV_FILE.key
    assert table_file.also_accepts == (XLSX_FILE.key,)
    assert table_file.shape.value == "one"
    # The port carries the materialized file, never the reference it came from.
    assert table_file.preserves_ref_container is False
    assert (
        import_table.node_class.output_contract.ports["table"].produces
        == TABLE_DATA.key
    )
    assert list(import_table.node_class.config_contract.model.model_fields) == [
        "delimiter",
        "header_row",
        "sheet_name",
        "skip_empty_rows",
    ]
    assert import_table.required_capabilities == ()

    parse_geojson = registry.node_registration("gis.geojson.parse", 1)
    geojson_file = parse_geojson.node_class.input_contract.ports["file"]
    assert geojson_file.accepts == GEOJSON_FILE.key
    assert geojson_file.also_accepts == (JSON_FILE.key,)
    assert geojson_file.shape.value == "one"
    assert (
        parse_geojson.node_class.output_contract.ports["features"].produces
        == GEO_FEATURE_COLLECTION.key
    )
    assert parse_geojson.required_capabilities == ()

    raster_layer = registry.node_registration("gis.map.raster_layer", 1)
    raster_source = raster_layer.node_class.input_contract.ports["raster"]
    assert raster_source.accepts == TIFF_FILE.key
    assert raster_source.also_accepts == ()
    assert raster_source.shape.value == "one"
    assert (
        raster_layer.node_class.output_contract.ports["layer"].produces
        == GEO_MAP_LAYER.key
    )
    assert raster_layer.required_capabilities == ()

    assert {spec.key for spec in IMAGES.artifact_type_dependencies} == {
        RASTER_IMAGE.key,
        PNG_FILE.key,
        JPEG_FILE.key,
        WEBP_FILE.key,
        TIFF_FILE.key,
        BMP_FILE.key,
    }
    assert {spec.key for spec in TABLES.artifact_type_dependencies} == {
        TABLE_DATA.key,
        CSV_FILE.key,
        XLSX_FILE.key,
    }
    assert {spec.key for spec in GIS.artifact_type_dependencies} == {
        TABLE_DATA.key,
        GEOJSON_FILE.key,
        JSON_FILE.key,
        TIFF_FILE.key,
    }

from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from grafy_api.catalog import CatalogSnapshot
from grafy_api.execution.errors import GraphExecutionError
from grafy_api.execution.requests import RunNodeRequest, RunOriginRequest, RunRequest
from grafy_api.services.composition import build_workbench_components
from grafy_api.v1.routes.catalog.models import NodeRegistryResponse
from grafy_core.artifacts import ArtifactObject
from grafy_core.domain.collaboration import GraphCommand
from grafy_core.domain.materialized_outputs import MaterializedNodeOutputs
from grafy_core.domain.graph_documents import GraphDocument
from grafy_core.ports.storage import SaveFileCommand
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_plugin_gis.gdal import GdalCli, RasterCogCompilation, RasterTileCompilation
from grafy_storage import LocalFileObjectStore

WORKSPACE_ID = UUID(int=7)


def test_static_registry_supplies_the_catalog(
    tmp_path: Path,
) -> None:
    components = build_workbench_components(workspace=tmp_path)
    catalog = NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(components.plugin_registry, []),
        components.run_graph,
    )
    nodes = {node.operator_id: node for node in catalog.nodes}
    assert nodes["gis.raster_scan.import"].origin == "builtin"
    assert (
        nodes["llm.openai_compatible.chat_completion"].secret_inputs[0].name
        == "api_key"
    )
    assert not any(key.startswith(("sql.", "python.")) for key in nodes)
    assert {"geo.raster_scan", "geo.map_layer", "geo.map_document"} <= {
        artifact.key.id for artifact in catalog.artifact_types
    }
    assert {plugin.entry_kind for plugin in catalog.plugins} == {"plugin", "module"}
    assert {plugin.origin for plugin in catalog.plugins} == {"builtin", "module"}
    assert "graph.module" in {plugin.slug for plugin in catalog.plugins}
    assert {node.plugin_slug for node in nodes.values()} <= {
        plugin.slug for plugin in catalog.plugins
    }


def _stored_node(**overrides: object) -> dict[str, object]:
    node: dict[str, object] = {
        "id": "scan",
        "kind": "builtin",
        "operator_id": "gis.raster_scan.import",
        "operator_version": 1,
        "config": {"source_name": "Scan"},
        "position": {"x": 10, "y": 20},
    }
    node.update(overrides)
    return node


@pytest.mark.parametrize(
    "node",
    [
        _stored_node(kind="plugin"),
        _stored_node(
            plugin_release_pin={
                "scope": "workspace",
                "slug": "external.gis",
                "revision": 99,
            }
        ),
        _stored_node(
            plugin_release={
                "scope": "system",
                "slug": "external.gis",
                "revision": 99,
            }
        ),
    ],
)
def test_stored_checkpoint_rejects_plugin_node_identity(
    node: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        GraphDocument.model_validate({"schema_version": 7, "nodes": [node]})


def test_recovered_run_request_rejects_the_plugin_node_kind() -> None:
    with pytest.raises(ValidationError, match="kind"):
        RunRequest.model_validate(
            {
                "nodes": [
                    {
                        "id": "scan",
                        "kind": "plugin",
                        "operator_id": "gis.raster_scan.import",
                        "operator_version": 1,
                    }
                ]
            }
        )


def test_recovered_run_request_carries_no_plugin_identity() -> None:
    request = RunRequest.model_validate(
        {
            "nodes": [
                {
                    "id": "scan",
                    "kind": "builtin",
                    "operator_id": "gis.raster_scan.import",
                    "operator_version": 1,
                    "plugin_release": {
                        "scope": "system",
                        "slug": "external.gis",
                        "revision": 99,
                    },
                }
            ]
        }
    )
    node = request.model_dump()["nodes"][0]
    assert node["kind"] == "builtin"
    assert "plugin_release" not in node
    assert "plugin_release_pin" not in node


def test_stale_release_update_command_is_rejected() -> None:
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        TypeAdapter(GraphCommand).validate_python(
            {
                "kind": "update_node_plugin_release",
                "node_id": "scan",
                "plugin_release_pin": {
                    "scope": "system",
                    "slug": "external.gis",
                    "revision": 2,
                },
                "expected_plugin_release_pin": {
                    "scope": "system",
                    "slug": "external.gis",
                    "revision": 1,
                },
            }
        )


@pytest.mark.parametrize(
    "operator", ["python.transform", "python.inspect", "sql.query"]
)
async def test_unavailable_operator_names_node_and_operator(
    tmp_path: Path, operator: str
) -> None:
    components = build_workbench_components(workspace=tmp_path)
    try:
        with pytest.raises(GraphExecutionError, match=f"legacy.*{operator}"):
            await components.run_graph.run(
                WORKSPACE_ID,
                RunRequest(
                    nodes=[
                        RunNodeRequest(
                            kind="builtin",
                            id="legacy",
                            operator_id=operator,
                            operator_version=1,
                        )
                    ]
                ),
            )
    finally:
        await components.artifacts.close()


async def test_registered_raster_import_persists_tiles_and_cache_uses_build_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native_calls: list[str] = []

    def normalize(
        _self: GdalCli, source: Path, destination: Path
    ) -> RasterCogCompilation:
        assert source.read_bytes() == b"II\x2a\x00source"
        native_calls.append("normalize")
        destination.write_bytes(b"II\x2a\x00cog")
        return RasterCogCompilation(
            destination=destination,
            compiler_version="3.8.0",
            native_crs="EPSG:4326",
            bounds_wgs84=(-10, -10, 10, 10),
            width=256,
            height=256,
            bands=3,
        )

    def tile(_self: GdalCli, source: Path, destination: Path) -> RasterTileCompilation:
        assert source.read_bytes() == b"II\x2a\x00cog"
        native_calls.append("tile")
        path = destination / "0" / "0" / "0.png"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"png-tile")
        return RasterTileCompilation(
            compiler_version="3.8.0",
            min_zoom=0,
            max_zoom=0,
            tile_count=1,
        )

    monkeypatch.setattr(GdalCli, "normalize_geotiff_to_cog", normalize)
    monkeypatch.setattr(GdalCli, "tile_raster_to_xyz", tile)
    uow = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    stored = await storage.save(
        SaveFileCommand(
            bucket="artifacts",
            path="scan.tif",
            content_type="image/tiff",
            stream=BytesIO(b"II\x2a\x00source"),
            metadata={},
        )
    )
    upload = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="file.tiff",
        schema_version=1,
        content_type="image/tiff",
        bucket=stored.bucket,
        object_key=stored.path,
        sha256=stored.sha256,
        byte_size=stored.byte_size,
        metadata={"original_filename": "scan.tif"},
    )
    async with uow:
        await uow.artifacts.add(upload)
        await uow.commit()
    request = RunRequest.model_validate(
        {
            "nodes": [
                {
                    "id": "scan",
                    "kind": "builtin",
                    "operator_id": "gis.raster_scan.import",
                    "operator_version": 1,
                    "config": {"source_name": "Scan"},
                }
            ],
            "origins": [
                RunOriginRequest(
                    to_node="scan", to_port="file", value=upload.ref()
                ).model_dump()
            ],
        }
    )
    components = build_workbench_components(
        workspace=tmp_path,
        unit_of_work=uow,
        storage=storage,
        build_digest="a" * 64,
    )
    next_build = build_workbench_components(
        workspace=tmp_path,
        unit_of_work=uow,
        storage=storage,
        build_digest="b" * 64,
    )
    try:
        first = await components.run_graph.run(WORKSPACE_ID, request)
        assert first.node_results[0].status == "succeeded", first.node_results[0].error
        ref = first.node_results[0].outputs["raster"]
        artifact = await components.artifacts.get(WORKSPACE_ID, ref.artifact_id)
        assert artifact is not None
        assert artifact.artifact_type == "geo.raster_scan"
        assert artifact.metadata["implementation"] == {
            "kind": "builtin",
            "build_digest": "a" * 64,
        }
        read = await components.artifacts.load_raster_tile(
            artifact,
            workspace_id=WORKSPACE_ID,
            z=0,
            x=0,
            y=0,
        )
        assert read is not None and read.content == b"png-tile"
        second = await components.run_graph.run(WORKSPACE_ID, request)
        assert second.node_results[0].outputs["raster"] == ref
        assert native_calls == ["normalize", "tile"]
        materialized = MaterializedNodeOutputs(
            workspace_id=WORKSPACE_ID,
            graph_id=uuid4(),
            graph_revision=1,
            node_id="scan",
            workflow_run_id=first.workflow_run_id,
            outputs={"raster": ref},
        )
        async with uow:
            await uow.materialized_outputs.upsert(materialized)
            await uow.commit()
        await components.materializations.validate_latest_pins(
            WORKSPACE_ID,
            materialized.graph_id,
            1,
            {("scan", "raster"): ref},
        )
        with pytest.raises(GraphExecutionError, match="no accessible materialized"):
            await next_build.materializations.validate_latest_pins(
                WORKSPACE_ID,
                materialized.graph_id,
                1,
                {("scan", "raster"): ref},
            )
        third = await next_build.run_graph.run(WORKSPACE_ID, request)
        assert third.node_results[0].status == "succeeded"
        assert native_calls == ["normalize", "tile", "normalize", "tile"]
        assert third.node_results[0].outputs["raster"] != ref
        # Historical artifacts remain readable even when their outputs are stale.
        historical = await next_build.artifacts.get(WORKSPACE_ID, ref.artifact_id)
        assert historical is not None
        old_tile = await next_build.artifacts.load_raster_tile(
            historical,
            workspace_id=WORKSPACE_ID,
            z=0,
            x=0,
            y=0,
        )
        assert old_tile is not None and old_tile.content == b"png-tile"
    finally:
        await components.artifacts.close()
        await next_build.artifacts.close()

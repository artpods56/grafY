from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from grafy_api.catalog import CatalogSnapshot
from grafy_api.services.composition import build_workbench_components
from grafy_api.v1.routes.catalog.models import NodeRegistryResponse
from grafy_core.domain.graph_documents import GraphDocument

WORKSPACE_ID = UUID(int=7)


def test_static_registry_supplies_the_catalog(
    tmp_path: Path,
) -> None:
    components = build_workbench_components(
        workspace=tmp_path, unit_of_work=InMemoryUnitOfWork()
    )
    catalog = NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(components.plugin_registry),
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
    assert {plugin.origin for plugin in catalog.plugins} == {"builtin"}
    assert not any(
        slug.startswith("graph.") for slug in {p.slug for p in catalog.plugins}
    )
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

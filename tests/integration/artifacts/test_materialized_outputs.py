import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete

from grafy_core.artifacts import ArtifactObject, ArtifactRef, ArtifactRefSequence
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.domain.materialized_outputs import MaterializedNodeOutputs
from grafy_core.domain.saved_graphs import SavedGraphDocument
from grafy_persistence import schema
from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import (
    SqlAlchemySavedGraphUnitOfWork,
    SqlAlchemyUnitOfWork,
)
from grafy_storage import LocalFileObjectStore

from grafy_api.services.composition import build_workbench_components
from grafy_api.settings import Settings
from grafy_api.v1.models import (
    ArtifactTypeBindingModel,
    ArtifactTypeKeyResponse,
)
from grafy_api.v1.routes.auth.dependencies import browser_actor, workspace_actor
from grafy_api.v1.routes.executions.models import (
    GraphMaterializationsResponse,
    RunPortOutputResponse,
    RunResponse,
)
from grafy_api.execution.requests import (
    PinnedOutputRequest,
    RunEdgeRequest,
    RunNodeRequest as UnpinnedRunNodeRequest,
    RunRequest,
)
from grafy_api.v1.routes.saved_graphs.models import (
    CreateSavedGraphRequest,
    GraphPointModel,
    SavedGraphEdgeModel,
    SavedGraphInputPlugModel,
    SavedGraphNodeModel,
    SavedGraphResponse,
    UpdateSavedGraphRequest,
)
from grafy_api.v1.routes.saved_graphs.dependencies import saved_graph_service
from tests.support.clients import GrafyApi
from tests.support.identity import browser_actor_override
from tests.support.system_plugins import (
    SelectedSystemPluginDeployment,
    build_selected_system_plugin_deployment,
    pin_selected_system_nodes,
    selected_system_run_node as RunNodeRequest,
)
from tests.support.workbench import workbench_dependency_overrides
from tests.testkit import (
    client_with_overrides,
    create_db_url,
    db,
    seed_shared_workspace,
)


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")

# Every durable-API client authenticates through the shared test actor.
_OVERRIDES = {
    browser_actor: browser_actor_override,
    workspace_actor: browser_actor_override,
}


@dataclass(frozen=True, slots=True)
class DurableApiFixture:
    settings: Settings
    database_url: str
    deployment: SelectedSystemPluginDeployment


async def _delete_artifact(database_url: str, artifact_id: UUID) -> None:
    async with db(database_url) as database:
        async with database.engine.begin() as connection:
            await connection.execute(
                delete(schema.artifact_objects).where(
                    schema.artifact_objects.c.id == artifact_id
                )
            )


async def _persist_partially_accessible_materialization(
    database_url: str,
    graph_id: UUID,
    graph_revision: int,
) -> None:
    accessible = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="scalar.integer",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 13},
    )
    missing = ArtifactRef(
        artifact_id=UUID("00000000-0000-0000-0000-000000000999"),
        artifact_type="scalar.integer",
        schema_version=1,
    )
    async with db(database_url) as database:
        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            await unit_of_work.artifacts.add(accessible)
            await unit_of_work.materialized_outputs.upsert(
                MaterializedNodeOutputs(
                    workspace_id=WORKSPACE_ID,
                    graph_id=graph_id,
                    graph_revision=graph_revision,
                    node_id="add",
                    workflow_run_id=UUID("00000000-0000-0000-0000-000000000998"),
                    outputs={
                        "accessible": accessible.ref(),
                        "missing": missing,
                    },
                )
            )
            await unit_of_work.commit()


@pytest.fixture
def durable_api(tmp_path: Path) -> DurableApiFixture:
    database_url = create_db_url(tmp_path, "materializations.sqlite3")
    deployment = build_selected_system_plugin_deployment()

    async def prepare() -> None:
        async with db(database_url) as database:
            await seed_shared_workspace(database)
            async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
                for release in deployment.releases:
                    await unit_of_work.plugin_releases.add(release.release)
                    await unit_of_work.plugin_releases.add_installation(
                        release.installation
                    )
                for selection in deployment.selections:
                    await unit_of_work.plugin_releases.add_selection(selection)
                await unit_of_work.commit()

    asyncio.run(prepare())
    return DurableApiFixture(
        settings=Settings(
            workspace=tmp_path / "workbench",
            database_url=SecretStr(database_url),
        ),
        database_url=database_url,
        deployment=deployment,
    )


@contextmanager
def _durable_client(fixture: DurableApiFixture) -> Iterator[TestClient]:
    database = create_database(fixture.database_url)
    deployment = fixture.deployment
    saved_graphs = SavedGraphService(
        lambda: SqlAlchemySavedGraphUnitOfWork(database.sessions),
        deployment.registry,
    )
    storage = LocalFileObjectStore(fixture.settings.workspace / "objects")
    plugin_releases = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        storage,
        bucket=fixture.settings.storage_bucket,
    )
    components = build_workbench_components(
        plugin_registry=deployment.registry,
        workspace=fixture.settings.workspace,
        unit_of_work=SqlAlchemyUnitOfWork(database.sessions),
        storage=storage,
        storage_backend=fixture.settings.storage_backend,
        bucket=fixture.settings.storage_bucket,
        saved_graphs=saved_graphs,
        plugin_releases=plugin_releases,
    )
    overrides = {
        **_OVERRIDES,
        **workbench_dependency_overrides(components),
        saved_graph_service: lambda: saved_graphs,
    }
    try:
        with client_with_overrides(
            settings=fixture.settings,
            overrides=overrides,
        ) as client:
            yield client
    finally:
        asyncio.run(components.execution_manager.shutdown())
        asyncio.run(components.artifacts.close())
        asyncio.run(database.dispose())


def _graph_payload(expected_revision: int | None = None) -> dict[str, object]:
    nodes: list[tuple[str, str, dict[str, object]]] = [
        ("nine", "arithmetic.number", {"value": 9}),
        ("four", "arithmetic.number", {"value": 4}),
        ("add", "arithmetic.add", {}),
        ("multiply", "arithmetic.multiply", {}),
    ]
    edges = _edges()
    node_models = [
        SavedGraphNodeModel(
            kind="builtin",
            id=node_id,
            operator_id=operator_id,
            operator_version=1,
            config=config,
            position=GraphPointModel(x=float(index * 200), y=20.0),
        )
        for index, (node_id, operator_id, config) in enumerate(nodes)
    ]
    edge_models = [
        SavedGraphEdgeModel.model_validate({"id": f"edge-{index}", **edge})
        for index, edge in enumerate(edges, start=1)
    ]
    serialized_nodes: list[dict[str, object]] = []
    for node in node_models:
        serialized = node.model_dump(mode="json")
        serialized["plugin_release_pin"] = serialized.pop("plugin_release")
        serialized_nodes.append(serialized)
    document = SavedGraphDocument.model_validate(
        {
            "nodes": serialized_nodes,
            "edges": [edge.model_dump(mode="json") for edge in edge_models],
        }
    )
    payload = CreateSavedGraphRequest(
        name="Durable arithmetic graph",
        document=document,
    ).model_dump(mode="json")
    if expected_revision is None:
        return payload
    return UpdateSavedGraphRequest(
        **payload,
        expected_revision=expected_revision,
    ).model_dump(mode="json")


def _edges() -> list[dict[str, object]]:
    return [
        {
            "from_node": "nine",
            "from_port": "value",
            "to_node": "add",
            "to_port": "left",
        },
        {
            "from_node": "four",
            "from_port": "value",
            "to_node": "add",
            "to_port": "right",
        },
        {
            "from_node": "add",
            "from_port": "result",
            "to_node": "multiply",
            "to_port": "left",
        },
        {
            "from_node": "add",
            "from_port": "result",
            "to_node": "multiply",
            "to_port": "right",
        },
    ]


def _collect_graph_payload() -> dict[str, object]:
    nodes = [
        SavedGraphNodeModel(
            kind="builtin",
            id="first",
            operator_id="text.input",
            operator_version=1,
            config={"text": "first"},
            position=GraphPointModel(x=0.0, y=0.0),
        ),
        SavedGraphNodeModel(
            kind="builtin",
            id="sequence-input",
            operator_id="text.input",
            operator_version=1,
            config={"text": "second|third"},
            position=GraphPointModel(x=200.0, y=0.0),
        ),
        SavedGraphNodeModel(
            kind="builtin",
            id="split",
            operator_id="text.split",
            operator_version=1,
            config={"separator": "|"},
            position=GraphPointModel(x=400.0, y=0.0),
        ),
        SavedGraphNodeModel(
            kind="builtin",
            id="collect",
            operator_id="sequence.collect",
            operator_version=1,
            config={},
            position=GraphPointModel(x=600.0, y=0.0),
            artifact_type_bindings=[
                ArtifactTypeBindingModel(
                    variable="T",
                    artifact_type=ArtifactTypeKeyResponse(
                        id="scalar.text",
                        schema_version=1,
                    ),
                )
            ],
            input_plugs=[
                SavedGraphInputPlugModel(id="sequence-plug", port="items"),
                SavedGraphInputPlugModel(id="first-plug", port="items"),
            ],
        ),
    ]
    edges = [
        SavedGraphEdgeModel(
            id="first-edge",
            from_node="first",
            from_port="text",
            to_node="collect",
            to_port="items",
            to_plug="first-plug",
        ),
        SavedGraphEdgeModel(
            id="sequence-input-edge",
            from_node="sequence-input",
            from_port="text",
            to_node="split",
            to_port="text",
        ),
        SavedGraphEdgeModel(
            id="sequence-edge",
            from_node="split",
            from_port="parts",
            to_node="collect",
            to_port="items",
            to_plug="sequence-plug",
        ),
    ]
    serialized_nodes: list[dict[str, object]] = []
    for node in nodes:
        serialized = node.model_dump(mode="json")
        serialized["plugin_release_pin"] = serialized.pop("plugin_release")
        serialized_nodes.append(serialized)
    return CreateSavedGraphRequest(
        name="Durable collect graph",
        document=SavedGraphDocument.model_validate(
            {
                "nodes": serialized_nodes,
                "edges": [edge.model_dump(mode="json") for edge in edges],
            }
        ),
    ).model_dump(mode="json")


def _collect_run_payload(graph: SavedGraphResponse) -> dict[str, object]:
    graph_payload = _collect_graph_payload()
    document = cast(dict[str, object], graph_payload["document"])
    nodes = cast(list[dict[str, object]], document["nodes"])
    edges = cast(list[dict[str, object]], document["edges"])
    return RunRequest(
        nodes=pin_selected_system_nodes(
            [UnpinnedRunNodeRequest.model_validate(node) for node in nodes]
        ),
        edges=[RunEdgeRequest.model_validate(edge) for edge in edges],
        graph_id=graph.id,
        graph_revision=graph.revision,
    ).model_dump(mode="json")


def _full_run_payload(graph_id: str, graph_revision: int) -> dict[str, object]:
    return RunRequest(
        nodes=[
            RunNodeRequest(
                kind="builtin",
                id="nine",
                operator_id="arithmetic.number",
                operator_version=1,
                config={"value": 9},
            ),
            RunNodeRequest(
                kind="builtin",
                id="four",
                operator_id="arithmetic.number",
                operator_version=1,
                config={"value": 4},
            ),
            RunNodeRequest(
                kind="builtin",
                id="add",
                operator_id="arithmetic.add",
                operator_version=1,
                config={},
            ),
            RunNodeRequest(
                kind="builtin",
                id="multiply",
                operator_id="arithmetic.multiply",
                operator_version=1,
                config={},
            ),
        ],
        edges=[RunEdgeRequest.model_validate(edge) for edge in _edges()],
        graph_id=UUID(graph_id),
        graph_revision=graph_revision,
    ).model_dump(mode="json")


def _downstream_run_payload(
    graph_id: str,
    graph_revision: int,
    *,
    pinned_value: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = RunRequest(
        nodes=[
            RunNodeRequest(
                kind="builtin",
                id="multiply",
                operator_id="arithmetic.multiply",
                operator_version=1,
                config={},
            )
        ],
        edges=[RunEdgeRequest.model_validate(edge) for edge in _edges()[2:]],
        graph_id=UUID(graph_id),
        graph_revision=graph_revision,
    )
    if pinned_value is not None:
        payload.pinned_outputs = [
            PinnedOutputRequest.model_validate(
                {
                    "from_node": "add",
                    "from_port": "result",
                    "value": pinned_value,
                }
            )
        ]
    return payload.model_dump(mode="json")


def _output(run: RunResponse, node_id: str) -> RunPortOutputResponse:
    node_run = next(item for item in run.node_runs if item.node_id == node_id)
    return node_run.outputs[0]


@pytest.mark.parametrize(
    ("graph_context", "message"),
    [
        (
            {"graph_id": "00000000-0000-0000-0000-000000000001"},
            "graph_id and graph_revision must be provided together",
        ),
        (
            {"graph_revision": 1},
            "graph_id and graph_revision must be provided together",
        ),
        (
            {"secret_graph_id": "00000000-0000-0000-0000-000000000001"},
            "secret_graph_id and secret_graph_revision must be provided together",
        ),
        (
            {"secret_graph_revision": 1},
            "secret_graph_id and secret_graph_revision must be provided together",
        ),
    ],
)
def test_run_graph_context_requires_id_and_revision_together(
    durable_api: DurableApiFixture,
    graph_context: dict[str, object],
    message: str,
) -> None:
    with _durable_client(durable_api) as client:
        # Half-declared graph contexts are rejected by RunRequest's own model
        # validator, so they cannot be expressed client-side; use the raw body.
        response = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json={"nodes": [], "edges": [], **graph_context},
        )

    assert response.status_code == 422
    assert message in str(response.json())


def test_run_graph_contexts_must_identify_same_saved_revision(
    durable_api: DurableApiFixture,
) -> None:
    with _durable_client(durable_api) as client:
        # Mismatched secret-graph revisions are rejected by RunRequest's own
        # model validator, so they cannot be expressed client-side; raw body.
        response = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json={
                "nodes": [],
                "edges": [],
                "graph_id": "00000000-0000-0000-0000-000000000001",
                "graph_revision": 1,
                "secret_graph_id": "00000000-0000-0000-0000-000000000001",
                "secret_graph_revision": 2,
            },
        )

    assert response.status_code == 422
    assert "must identify the same saved graph revision" in str(response.json())


def test_materialization_context_validates_graph_revision_and_fragment(
    durable_api: DurableApiFixture,
) -> None:
    missing_graph_id = "00000000-0000-0000-0000-000000000404"
    with _durable_client(durable_api) as client:
        missing = client.get(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{missing_graph_id}/materializations",
            params={"graph_revision": 1},
        )
        graph = SavedGraphResponse.model_validate(
            client.post(
                "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
                json=_graph_payload(),
            ).json()
        )
        missing_revision = client.get(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph.id}/materializations",
            params={"graph_revision": graph.revision + 1},
        )
        rogue = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="builtin",
                        id="rogue-node",
                        operator_id="arithmetic.number",
                        operator_version=1,
                        config={"value": 99},
                    )
                ],
                edges=[],
                graph_id=graph.id,
                graph_revision=graph.revision,
            ).model_dump(mode="json"),
        )

    assert missing.status_code == 404
    assert missing_revision.status_code == 404
    assert rogue.status_code == 422
    assert "does not belong to saved graph" in rogue.json()["detail"]


def test_graph_context_run_rejects_omitted_saved_incoming_edge(
    durable_api: DurableApiFixture,
) -> None:
    with _durable_client(durable_api) as client:
        graph = SavedGraphResponse.model_validate(
            client.post(
                "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
                json=_graph_payload(),
            ).json()
        )
        payload = _full_run_payload(str(graph.id), graph.revision)
        payload["edges"] = _edges()[:1] + _edges()[2:]

        response = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs", json=payload
        )
        materializations = client.get(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph.id}/materializations",
            params={"graph_revision": graph.revision},
        )

    assert response.status_code == 422
    assert "1 missing and 0 unexpected or duplicated" in response.json()["detail"]
    assert materializations.status_code == 200
    assert (
        GraphMaterializationsResponse.model_validate(materializations.json()).node_runs
        == []
    )


def test_graph_context_run_rejects_duplicated_saved_incoming_edge(
    durable_api: DurableApiFixture,
) -> None:
    with _durable_client(durable_api) as client:
        graph = SavedGraphResponse.model_validate(
            client.post(
                "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
                json=_graph_payload(),
            ).json()
        )
        payload = _full_run_payload(str(graph.id), graph.revision)
        payload["edges"] = [*_edges(), _edges()[1]]

        response = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs", json=payload
        )
        materializations = client.get(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph.id}/materializations",
            params={"graph_revision": graph.revision},
        )

    assert response.status_code == 422
    assert "0 missing and 1 unexpected or duplicated" in response.json()["detail"]
    assert materializations.status_code == 200
    assert (
        GraphMaterializationsResponse.model_validate(materializations.json()).node_runs
        == []
    )


def test_saved_collect_fragment_matches_ordered_plugs_and_edge_targets(
    durable_api: DurableApiFixture,
) -> None:
    with _durable_client(durable_api) as client:
        created = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
            json=_collect_graph_payload(),
        )
        assert created.status_code == 201
        graph = SavedGraphResponse.model_validate(created.json())

        matching_run = _collect_run_payload(graph)
        matching = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=matching_run,
        )
        assert matching.status_code == 200
        assert RunResponse.model_validate(matching.json()).status == "succeeded"

        reordered_run = deepcopy(matching_run)
        reordered_nodes = cast(
            list[dict[str, object]],
            reordered_run["nodes"],
        )
        collect_node = next(node for node in reordered_nodes if node["id"] == "collect")
        input_plugs = cast(
            list[dict[str, object]],
            collect_node["input_plugs"],
        )
        input_plugs.reverse()
        reordered = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=reordered_run,
        )

        retargeted_run = deepcopy(matching_run)
        retargeted_edges = cast(
            list[dict[str, object]],
            retargeted_run["edges"],
        )
        collect_edges = [
            edge for edge in retargeted_edges if edge["to_node"] == "collect"
        ]
        collect_edges[0]["to_plug"], collect_edges[1]["to_plug"] = (
            collect_edges[1]["to_plug"],
            collect_edges[0]["to_plug"],
        )
        retargeted = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=retargeted_run,
        )

    assert reordered.status_code == 422
    assert "does not match saved graph" in reordered.json()["detail"]
    assert retargeted.status_code == 422
    assert (
        "Run edges do not match the saved incoming edges" in retargeted.json()["detail"]
    )


def test_fresh_app_runs_collect_only_from_persisted_scalar_and_sequence_pins(
    durable_api: DurableApiFixture,
) -> None:
    with _durable_client(durable_api) as client:
        graph = SavedGraphResponse.model_validate(
            client.post(
                "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
                json=_collect_graph_payload(),
            ).json()
        )
        full_run = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=_collect_run_payload(graph),
        )
        assert full_run.status_code == 200

    with _durable_client(durable_api) as fresh_client:
        materializations_response = fresh_client.get(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph.id}/materializations",
            params={"graph_revision": graph.revision},
        )
        assert materializations_response.status_code == 200
        materializations = GraphMaterializationsResponse.model_validate(
            materializations_response.json()
        )
        first_run = next(
            node_run
            for node_run in materializations.node_runs
            if node_run.node_id == "first"
        )
        split_run = next(
            node_run
            for node_run in materializations.node_runs
            if node_run.node_id == "split"
        )
        first_value = first_run.outputs[0].value
        split_value = split_run.outputs[0].value
        assert isinstance(first_value, ArtifactRef)
        assert isinstance(split_value, ArtifactRefSequence)

        graph_payload = _collect_graph_payload()
        document = cast(dict[str, object], graph_payload["document"])
        collect_node = next(
            node
            for node in cast(list[dict[str, object]], document["nodes"])
            if node["id"] == "collect"
        )
        incoming_edges = [
            edge
            for edge in cast(list[dict[str, object]], document["edges"])
            if edge["to_node"] == "collect"
        ]
        selected_run = fresh_client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=RunRequest(
                nodes=pin_selected_system_nodes(
                    [UnpinnedRunNodeRequest.model_validate(collect_node)]
                ),
                edges=[RunEdgeRequest.model_validate(edge) for edge in incoming_edges],
                pinned_outputs=[
                    PinnedOutputRequest(
                        from_node="first",
                        from_port="text",
                        value=first_value,
                    ),
                    PinnedOutputRequest(
                        from_node="split",
                        from_port="parts",
                        value=split_value,
                    ),
                ],
                graph_id=graph.id,
                graph_revision=graph.revision,
            ).model_dump(mode="json"),
        )

        assert selected_run.status_code == 200
        selected_result = RunResponse.model_validate(selected_run.json())
        collected = _output(selected_result, "collect")
        assert isinstance(collected.value, ArtifactRefSequence)
        api = GrafyApi(fresh_client)
        artifacts = api.workspace(WORKSPACE_ID).artifacts
        assert [
            artifacts.content(artifact.artifact_id).json()["value"]
            for artifact in collected.artifacts
        ] == ["second", "third", "first"]


def test_full_run_persists_outputs_and_fresh_app_reuses_them_for_downstream_run(
    durable_api: DurableApiFixture,
) -> None:
    with _durable_client(durable_api) as client:
        created = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
            json=_graph_payload(),
        )
        assert created.status_code == 201
        graph = SavedGraphResponse.model_validate(created.json())

        full_run = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=_full_run_payload(str(graph.id), graph.revision),
        )
        assert full_run.status_code == 200
        assert RunResponse.model_validate(full_run.json()).status == "succeeded"

        materializations = client.get(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph.id}/materializations",
            params={"graph_revision": graph.revision},
        )
        assert materializations.status_code == 200
        materialized = GraphMaterializationsResponse.model_validate(
            materializations.json()
        )
        assert {node_run.node_id for node_run in materialized.node_runs} == {
            "nine",
            "four",
            "add",
            "multiply",
        }

    with _durable_client(durable_api) as fresh_client:
        reloaded = fresh_client.get(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph.id}/materializations",
            params={"graph_revision": graph.revision},
        )
        assert reloaded.status_code == 200
        reloaded_result = GraphMaterializationsResponse.model_validate(reloaded.json())
        assert len(reloaded_result.node_runs) == 4
        add_run = next(
            node_run
            for node_run in reloaded_result.node_runs
            if node_run.node_id == "add"
        )
        persisted_value = add_run.outputs[0].value

        downstream = fresh_client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=_downstream_run_payload(
                str(graph.id),
                graph.revision,
                pinned_value=persisted_value.model_dump(mode="json"),
            ),
        )
        assert downstream.status_code == 200
        downstream_result = RunResponse.model_validate(downstream.json())
        assert downstream_result.status == "succeeded"
        assert _output(downstream_result, "multiply").artifacts[0].text == "169"


def test_graph_update_carries_compatible_materializations_to_new_revision(
    durable_api: DurableApiFixture,
) -> None:
    with _durable_client(durable_api) as client:
        created = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
            json=_graph_payload(),
        )
        assert created.status_code == 201
        graph = SavedGraphResponse.model_validate(created.json())

        full_run = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=_full_run_payload(str(graph.id), graph.revision),
        )
        assert full_run.status_code == 200

        moved_payload = _graph_payload(expected_revision=graph.revision)
        document = cast(dict[str, object], moved_payload["document"])
        nodes = cast(list[dict[str, object]], document["nodes"])
        nodes[0] = {
            **nodes[0],
            "position": {"x": 40, "y": 80},
        }
        updated = client.put(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph.id}",
            json=moved_payload,
        )
        assert updated.status_code == 200
        next_graph = SavedGraphResponse.model_validate(updated.json())
        assert next_graph.revision == graph.revision + 1

        previous = client.get(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph.id}/materializations",
            params={"graph_revision": graph.revision},
        )
        carried = client.get(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph.id}/materializations",
            params={"graph_revision": next_graph.revision},
        )

    assert previous.status_code == 200
    assert carried.status_code == 200
    previous_ids = {
        node_run.node_id
        for node_run in GraphMaterializationsResponse.model_validate(
            previous.json()
        ).node_runs
    }
    carried_ids = {
        node_run.node_id
        for node_run in GraphMaterializationsResponse.model_validate(
            carried.json()
        ).node_runs
    }
    assert previous_ids == {"nine", "four", "add", "multiply"}
    assert carried_ids == previous_ids


def test_downstream_run_without_materialization_returns_dependency_guidance(
    durable_api: DurableApiFixture,
) -> None:
    with _durable_client(durable_api) as client:
        graph = SavedGraphResponse.model_validate(
            client.post(
                "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
                json=_graph_payload(),
            ).json()
        )
        standalone = RunResponse.model_validate(
            client.post(
                "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
                json=RunRequest(
                    nodes=[
                        RunNodeRequest(
                            kind="builtin",
                            id="standalone",
                            operator_id="arithmetic.number",
                            operator_version=1,
                            config={"value": 5},
                        )
                    ],
                    edges=[],
                ).model_dump(mode="json"),
            ).json()
        )
        unrelated_value = _output(standalone, "standalone").value

        response = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=_downstream_run_payload(
                str(graph.id),
                graph.revision,
                pinned_value=unrelated_value.model_dump(mode="json"),
            ),
        )

    assert response.status_code == 422
    assert "Run with dependencies" in response.json()["detail"]


def test_inaccessible_artifact_is_filtered_and_blocks_downstream_reuse(
    durable_api: DurableApiFixture,
) -> None:
    with _durable_client(durable_api) as client:
        graph = SavedGraphResponse.model_validate(
            client.post(
                "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
                json=_graph_payload(),
            ).json()
        )
        full_run = RunResponse.model_validate(
            client.post(
                "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
                json=_full_run_payload(str(graph.id), graph.revision),
            ).json()
        )
        add_value = _output(full_run, "add").value
        assert isinstance(add_value, ArtifactRef)
        artifact_id = add_value.artifact_id
        pinned_value = add_value.model_dump(mode="json")

    asyncio.run(_delete_artifact(durable_api.database_url, artifact_id))

    with _durable_client(durable_api) as client:
        materializations = client.get(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph.id}/materializations",
            params={"graph_revision": graph.revision},
        )
        materialized = GraphMaterializationsResponse.model_validate(
            materializations.json()
        )
        visible_nodes = {node_run.node_id for node_run in materialized.node_runs}
        assert "add" not in visible_nodes

        downstream = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=_downstream_run_payload(
                str(graph.id),
                graph.revision,
                pinned_value=pinned_value,
            ),
        )

    assert downstream.status_code == 422
    assert "no accessible materialized artifact" in downstream.json()["detail"]
    assert "Run with dependencies" in downstream.json()["detail"]


def test_materialization_response_keeps_accessible_sibling_ports(
    durable_api: DurableApiFixture,
) -> None:
    with _durable_client(durable_api) as client:
        graph = SavedGraphResponse.model_validate(
            client.post(
                "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
                json=_graph_payload(),
            ).json()
        )

    asyncio.run(
        _persist_partially_accessible_materialization(
            durable_api.database_url,
            graph.id,
            graph.revision,
        )
    )

    with _durable_client(durable_api) as client:
        response = client.get(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph.id}/materializations",
            params={"graph_revision": graph.revision},
        )

    assert response.status_code == 200
    materializations = GraphMaterializationsResponse.model_validate(response.json())
    node_run = next(
        item for item in materializations.node_runs if item.node_id == "add"
    )
    assert [output.port for output in node_run.outputs] == ["accessible"]


def test_saved_run_rejects_pin_that_is_not_the_latest_materialization(
    durable_api: DurableApiFixture,
) -> None:
    with _durable_client(durable_api) as client:
        graph = SavedGraphResponse.model_validate(
            client.post(
                "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
                json=_graph_payload(),
            ).json()
        )
        persisted = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=_full_run_payload(str(graph.id), graph.revision),
        )
        assert persisted.status_code == 200

        alternate = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="builtin",
                        id="eight",
                        operator_id="arithmetic.number",
                        operator_version=1,
                        config={"value": 8},
                    ),
                    RunNodeRequest(
                        kind="builtin",
                        id="three",
                        operator_id="arithmetic.number",
                        operator_version=1,
                        config={"value": 3},
                    ),
                    RunNodeRequest(
                        kind="builtin",
                        id="add",
                        operator_id="arithmetic.add",
                        operator_version=1,
                        config={},
                    ),
                ],
                edges=[
                    RunEdgeRequest(
                        from_node="eight",
                        from_port="value",
                        to_node="add",
                        to_port="left",
                    ),
                    RunEdgeRequest(
                        from_node="three",
                        from_port="value",
                        to_node="add",
                        to_port="right",
                    ),
                ],
            ).model_dump(mode="json"),
        )
        assert alternate.status_code == 200
        alternate_result = RunResponse.model_validate(alternate.json())
        pinned_value = _output(alternate_result, "add").value
        assert isinstance(pinned_value, ArtifactRef)

        downstream = client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=_downstream_run_payload(
                str(graph.id),
                graph.revision,
                pinned_value=pinned_value.model_dump(mode="json"),
            ),
        )

    assert downstream.status_code == 422
    assert "is not the latest materialized output" in downstream.json()["detail"]

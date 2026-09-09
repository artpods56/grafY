import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from grafy_core.application.graph_creation import stage_checkpointed_graph
from grafy_core.domain.execution_history import GraphExecution
from grafy_core.domain.saved_graphs import SavedGraph, SavedGraphDocument
from grafy_persistence.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

from tests.support.identity import browser_actor_override
from grafy_api.v1.routes.auth.dependencies import browser_actor, workspace_actor
from grafy_api.v1.routes.executions.models import RunExecutionResponse
from grafy_api.execution.requests import RunRequest
from tests.support.system_plugins import (
    selected_system_run_node as RunNodeRequest,
)
from tests.support.clients import GrafyApi
from grafy_api.graph_contracts import (
    CreateSavedGraphRequest,
    GraphPointModel,
    SavedGraphNodeModel,
    SavedGraphResponse,
    UpdateSavedGraphRequest,
)
from grafy_api.settings import Settings

from tests.testkit import (
    client_with_overrides,
    create_db_url,
    db,
    seed_shared_workspace,
)


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")


def _saved_text_graph_nodes(text: str) -> list[SavedGraphNodeModel]:
    return [
        SavedGraphNodeModel(
            kind="builtin",
            id="text",
            operator_id="text.input",
            operator_version=1,
            config={"text": text},
            position=GraphPointModel(x=0, y=0),
        )
    ]


def _create_text_graph_request(name: str, text: str) -> CreateSavedGraphRequest:
    node = _saved_text_graph_nodes(text)[0].model_dump(mode="json")
    node["plugin_release_pin"] = node.pop("plugin_release")
    return CreateSavedGraphRequest(
        name=name,
        document=SavedGraphDocument.model_validate({"nodes": [node]}),
    )


def _update_text_graph_request(
    name: str, text: str, *, expected_revision: int
) -> UpdateSavedGraphRequest:
    node = _saved_text_graph_nodes(text)[0].model_dump(mode="json")
    node["plugin_release_pin"] = node.pop("plugin_release")
    return UpdateSavedGraphRequest(
        name=name,
        expected_revision=expected_revision,
        document=SavedGraphDocument.model_validate({"nodes": [node]}),
    )


def _start_saved_text_execution(
    client: TestClient,
    graph: SavedGraphResponse,
) -> RunExecutionResponse:
    api = GrafyApi(client)
    executions = api.workspace(WORKSPACE_ID).executions
    started = executions.start_execution_ok(
        RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="text",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "remember this"},
                )
            ],
            edges=[],
            scope="selected-with-dependencies",
            graph_id=graph.id,
            graph_revision=graph.revision,
        )
    )
    for _ in range(100):
        current = executions.get_execution_ok(started.execution_id)
        if current.status in {"cancelled", "succeeded", "failed"}:
            return current
    raise AssertionError("Execution did not reach a terminal status")


def test_saved_graph_execution_endpoint_runs_the_full_checkpointed_graph(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    created = api.workspace(WORKSPACE_ID).graphs.create_ok(
        _create_text_graph_request("HTTP execution", "through the saved graph")
    )

    response = builtin_client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/graphs/{created.id}/executions",
        json={"expected_revision": created.revision},
        headers={"Idempotency-Key": "saved-graph-http-1"},
    )

    assert response.status_code == 202
    started = RunExecutionResponse.model_validate(response.json())
    current = started
    for _ in range(100):
        current = api.workspace(WORKSPACE_ID).executions.get_execution_ok(
            started.execution_id
        )
        if current.status in {"cancelled", "succeeded", "failed"}:
            break
    assert current.status == "succeeded"
    assert current.result is not None
    assert [(node.node_id, node.status) for node in current.result.node_runs] == [
        ("text", "succeeded")
    ]

    history = api.workspace(WORKSPACE_ID).executions.get_graph_execution_ok(
        created.id,
        started.execution_id,
    )
    assert history.graph_revision == created.revision
    assert history.scope == "all"
    assert history.requested_node_ids == ["text"]


def test_saved_graph_execution_endpoint_rejects_a_stale_revision(
    builtin_client: TestClient,
) -> None:
    graphs = GrafyApi(builtin_client).workspace(WORKSPACE_ID).graphs
    created = graphs.create_ok(_create_text_graph_request("Stale", "revision one"))
    updated = graphs.update_ok(
        created.id,
        _update_text_graph_request(
            "Stale",
            "revision two",
            expected_revision=created.revision,
        ),
    )

    response = builtin_client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/graphs/{updated.id}/executions",
        json={"expected_revision": created.revision},
        headers={"Idempotency-Key": "new-stale-execution"},
    )

    assert response.status_code == 409
    assert "current revision is 2" in response.json()["detail"]


def test_saved_graph_execution_endpoint_replays_an_idempotent_start(
    builtin_client: TestClient,
) -> None:
    created = (
        GrafyApi(builtin_client)
        .workspace(WORKSPACE_ID)
        .graphs.create_ok(_create_text_graph_request("Idempotent", "once"))
    )
    path = f"/v1/workspaces/{WORKSPACE_ID}/graphs/{created.id}/executions"
    headers = {"Idempotency-Key": "saved-graph-idempotency-1"}

    first = builtin_client.post(
        path,
        json={"expected_revision": created.revision},
        headers=headers,
    )
    replay = builtin_client.post(
        path,
        json={"expected_revision": created.revision},
        headers=headers,
    )

    assert first.status_code == 202
    assert replay.status_code == 202
    assert replay.json()["execution_id"] == first.json()["execution_id"]


def test_saved_graph_execution_endpoint_replays_after_the_graph_advances(
    builtin_client: TestClient,
) -> None:
    graphs = GrafyApi(builtin_client).workspace(WORKSPACE_ID).graphs
    created = graphs.create_ok(
        _create_text_graph_request("Idempotent revision", "revision one")
    )
    path = f"/v1/workspaces/{WORKSPACE_ID}/graphs/{created.id}/executions"
    headers = {"Idempotency-Key": "saved-graph-revision-retry"}
    original = builtin_client.post(
        path,
        json={"expected_revision": created.revision},
        headers=headers,
    )
    updated = graphs.update_ok(
        created.id,
        _update_text_graph_request(
            "Idempotent revision",
            "revision two",
            expected_revision=created.revision,
        ),
    )

    retry = builtin_client.post(
        path,
        json={"expected_revision": created.revision},
        headers=headers,
    )

    assert updated.revision == 2
    assert original.status_code == 202
    assert retry.status_code == 202
    assert retry.json()["execution_id"] == original.json()["execution_id"]


def test_saved_graph_execution_endpoint_rejects_a_reused_key_for_a_new_identity(
    builtin_client: TestClient,
) -> None:
    graphs = GrafyApi(builtin_client).workspace(WORKSPACE_ID).graphs
    first = graphs.create_ok(_create_text_graph_request("First graph", "first"))
    second = graphs.create_ok(_create_text_graph_request("Second graph", "second"))
    headers = {"Idempotency-Key": "saved-graph-identity-conflict"}
    original = builtin_client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/graphs/{first.id}/executions",
        json={"expected_revision": first.revision},
        headers=headers,
    )
    updated = graphs.update_ok(
        first.id,
        _update_text_graph_request(
            "First graph",
            "updated",
            expected_revision=first.revision,
        ),
    )

    different_revision = builtin_client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/graphs/{first.id}/executions",
        json={"expected_revision": updated.revision},
        headers=headers,
    )
    different_graph = builtin_client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/graphs/{second.id}/executions",
        json={"expected_revision": second.revision},
        headers=headers,
    )

    assert original.status_code == 202
    original_execution_id = original.json()["execution_id"]
    for response in (different_revision, different_graph):
        assert response.status_code == 409
        assert response.json()["detail"]["error_code"] == (
            "execution_idempotency_conflict"
        )
        assert response.json()["detail"]["execution_id"] == original_execution_id


def test_saved_graph_execution_history_lists_filters_and_renders_artifacts(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    executions = api.workspace(WORKSPACE_ID).executions
    graphs = api.workspace(WORKSPACE_ID).graphs
    created_response = graphs.create(
        _create_text_graph_request("History", "remember this")
    )
    assert created_response.status_code == 201
    graph = SavedGraphResponse.model_validate(created_response.json())

    first = _start_saved_text_execution(builtin_client, graph)
    assert first.status == "succeeded"

    listing = executions.list_graph_executions_ok(graph.id)
    assert len(listing.items) == 1
    summary = listing.items[0]
    assert summary.execution_id == first.execution_id
    assert summary.graph_revision == graph.revision
    assert summary.scope == "selected-with-dependencies"
    assert summary.status == "succeeded"
    assert summary.requested_node_ids == ["text"]
    assert summary.node_count == 1
    assert summary.artifact_count == 1
    assert summary.started_at is not None
    assert summary.finished_at is not None
    assert summary.workflow_run_id is not None

    detail = executions.get_graph_execution_ok(graph.id, first.execution_id)
    assert [(result.node_id, result.status) for result in detail.node_results] == [
        ("text", "succeeded")
    ]
    output = detail.node_results[0].outputs[0]
    assert output.port == "text"
    assert output.artifacts[0].text == '"remember this"'

    succeeded = executions.list_graph_executions_ok(
        graph.id, status="succeeded", node_id="text"
    )
    assert len(succeeded.items) == 1
    no_match = executions.list_graph_executions_ok(
        graph.id, status="failed", node_id="missing"
    )
    assert no_match.items == []
    # Values the route rejects (whitespace node filter, undecodable cursor)
    # are deliberate boundary probes; keep them on the raw client.
    assert (
        builtin_client.get(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph.id}/executions",
            params={"node_id": "   "},
        ).status_code
        == 422
    )
    assert (
        builtin_client.get(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph.id}/executions",
            params={"cursor": "not-a-cursor"},
        ).status_code
        == 422
    )
    assert (
        executions.get_graph_execution(uuid4(), first.execution_id).status_code == 404
    )

    updated_response = api.workspace(WORKSPACE_ID).graphs.update(
        graph.id,
        _update_text_graph_request(
            "History r2", "remember this", expected_revision=graph.revision
        ),
    )
    assert updated_response.status_code == 200
    updated_graph = SavedGraphResponse.model_validate(updated_response.json())
    assert updated_graph.revision == 2

    second = _start_saved_text_execution(builtin_client, updated_graph)
    assert second.status == "succeeded"
    revision_one = executions.list_graph_executions_ok(graph.id, graph_revision=1)
    assert [item.execution_id for item in revision_one.items] == [first.execution_id]
    revision_two = executions.list_graph_executions_ok(graph.id, graph_revision=2)
    assert [item.execution_id for item in revision_two.items] == [second.execution_id]
    all_revisions = executions.list_graph_executions_ok(graph.id)
    assert {item.graph_revision for item in all_revisions.items} == {1, 2}
    first_page = executions.list_graph_executions_ok(graph.id, limit=1)
    assert len(first_page.items) == 1
    assert first_page.next_cursor is not None
    second_page = executions.list_graph_executions_ok(
        graph.id, limit=1, cursor=first_page.next_cursor
    )
    assert len(second_page.items) == 1
    assert second_page.items[0].execution_id != first_page.items[0].execution_id


def test_saved_graph_execution_is_not_accepted_without_its_revision(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    executions = api.workspace(WORKSPACE_ID).executions
    response = executions.start_execution(
        RunRequest(
            nodes=[],
            edges=[],
            graph_id=uuid4(),
            graph_revision=1,
        )
    )

    assert response.status_code == 404
    assert "Saved graph revision" in response.json()["detail"]


def test_duplicate_saved_node_ids_become_a_browsable_failed_execution(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    executions = api.workspace(WORKSPACE_ID).executions
    graphs = api.workspace(WORKSPACE_ID).graphs
    created_response = graphs.create(
        _create_text_graph_request("Invalid history", "duplicate")
    )
    assert created_response.status_code == 201
    graph = SavedGraphResponse.model_validate(created_response.json())
    duplicate_node = RunNodeRequest(
        kind="builtin",
        id="text",
        operator_id="text.input",
        operator_version=1,
        config={"text": "duplicate"},
    )

    execution = executions.start_execution_ok(
        RunRequest(
            nodes=[duplicate_node, duplicate_node],
            edges=[],
            scope="all",
            graph_id=graph.id,
            graph_revision=graph.revision,
        )
    )
    for _ in range(100):
        execution = executions.get_execution_ok(execution.execution_id)
        if execution.status == "failed":
            break
    assert execution.status == "failed"
    assert execution.error is not None
    assert "Duplicate node ids" in execution.error

    detail = executions.get_graph_execution_ok(graph.id, execution.execution_id)
    assert detail.status == "failed"
    assert detail.requested_node_ids == ["text"]
    assert detail.node_results == []
    assert detail.error is not None
    assert "Duplicate node ids" in detail.error


async def _seed_active_execution(database_url: str) -> tuple[UUID, UUID]:
    async with db(database_url) as database:
        await seed_shared_workspace(database)
        graph = SavedGraph(
            workspace_id=WORKSPACE_ID,
            created_by_user_id=None,
            name="Interrupted",
            document=SavedGraphDocument(),
        )
        execution_id = uuid4()
        started_at = datetime.now(UTC)
        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            await stage_checkpointed_graph(
                graph,
                graphs=unit_of_work.graphs,
                collaboration=unit_of_work.collaboration,
                collaboration_sequence=1,
            )
            # An active (running) execution is its own uniqueness record; the
            # partial unique index on graph_executions carries the invariant.
            await unit_of_work.execution_history.add(
                GraphExecution(
                    workspace_id=WORKSPACE_ID,
                    execution_id=execution_id,
                    graph_id=graph.id,
                    graph_revision=graph.revision,
                    status="running",
                    requested_node_ids=(),
                    created_at=started_at,
                    started_at=started_at,
                )
            )
            await unit_of_work.commit()
        return graph.id, execution_id


def test_application_startup_marks_stale_active_execution_failed(
    tmp_path: Path,
) -> None:
    database_url = create_db_url(tmp_path, "recovery.sqlite3")
    graph_id, execution_id = asyncio.run(_seed_active_execution(database_url))
    with client_with_overrides(
        settings=Settings(
            workspace=tmp_path / "workbench",
            database_url=SecretStr(database_url),
        ),
        overrides={
            browser_actor: browser_actor_override,
            workspace_actor: browser_actor_override,
        },
    ) as client:
        api = GrafyApi(client)
        executions = api.workspace(WORKSPACE_ID).executions
        detail = executions.get_graph_execution_ok(graph_id, execution_id)

    assert detail.status == "failed"
    assert detail.finished_at is not None
    assert detail.error is not None
    assert "API process stopped" in detail.error


def test_conflicting_start_reports_existing_execution_without_leaking(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "conflict.sqlite3"
    database_url = create_db_url(tmp_path, "conflict.sqlite3")
    graph_id, execution_id = asyncio.run(_seed_active_execution(database_url))
    with client_with_overrides(
        settings=Settings(
            workspace=tmp_path / "workbench",
            database_url=SecretStr(database_url),
        ),
        overrides={
            browser_actor: browser_actor_override,
            workspace_actor: browser_actor_override,
        },
    ) as client:
        # Boot-time recovery already failed the seeded execution; restore it
        # to running so the database-level uniqueness invariant is exercised.
        with create_engine(f"sqlite:///{database_path}").begin() as connection:
            connection.execute(
                text(
                    "UPDATE graph_executions SET status = 'running' "
                    "WHERE execution_id = :execution_id"
                ),
                {"execution_id": execution_id.hex},
            )
        api = GrafyApi(client)
        executions = api.workspace(WORKSPACE_ID).executions
        response = executions.start_execution(
            RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="builtin",
                        id="text",
                        operator_id="text.input",
                        operator_version=1,
                        config={"text": "conflict"},
                    )
                ],
                edges=[],
                scope="all",
                graph_id=graph_id,
                graph_revision=1,
            )
        )

    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["error_code"] == "active_execution"
    # The conflict identifies the existing execution for this graph only; it
    # must not disclose executions from other workspaces.
    assert body["execution_id"] == str(execution_id)
    assert body["graph_id"] == str(graph_id)
    assert body["workspace_id"] == str(WORKSPACE_ID)

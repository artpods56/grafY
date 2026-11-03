"""A database holding one saved graph, for transient-activity tests."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from grafy_core.domain.saved_graphs import GraphDocument
from grafy_persistence import schema
from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000001201")
GRAPH_ID = UUID("00000000-0000-0000-0000-000000001202")
EXECUTION_ID = UUID("00000000-0000-0000-0000-000000001203")
ROOM_EPOCH = UUID("00000000-0000-0000-0000-000000001205")
WORKFLOW_RUN_ID = UUID("00000000-0000-0000-0000-000000001206")
ARTIFACT_ID = UUID("00000000-0000-0000-0000-000000001208")


NOW = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)


def _graph_document() -> GraphDocument:
    return GraphDocument.model_validate(
        {
            "nodes": [
                {
                    "kind": "builtin",
                    "id": "known",
                    "operator_id": "text.concat",
                    "operator_version": 1,
                    "config": {"separator": " | "},
                    "position": {"x": 12, "y": 34},
                    "layout": {"width": 320},
                },
                {
                    "kind": "builtin",
                    "id": "second",
                    "operator_id": "text.concat",
                    "operator_version": 1,
                    "config": {"separator": ""},
                    "position": {"x": 56, "y": 78},
                },
                {
                    "kind": "module",
                    "id": "module-input",
                    "operator_id": "module.input",
                    "operator_version": 1,
                    "config": {},
                    "position": {"x": 0, "y": 0},
                },
                {
                    "kind": "module",
                    "id": "module-call",
                    "operator_id": "graph.module.call",
                    "operator_version": 2,
                    "config": {},
                    "position": {"x": 1, "y": 1},
                },
            ],
            "edges": [],
        }
    )


def _run_request() -> dict[str, object]:
    document = _graph_document().model_dump(mode="json")
    nodes = document["nodes"]
    assert isinstance(nodes, list)
    run_nodes: list[dict[str, object]] = []
    for node in cast(list[object], nodes):
        assert isinstance(node, dict)
        run_nodes.append(
            {
                "kind": node["kind"],
                "id": node["id"],
                "operator_id": node["operator_id"],
                "operator_version": node["operator_version"],
                "config": node["config"],
            }
        )
    return {"nodes": run_nodes, "edges": [], "scope": "all"}


@pytest.fixture
async def activity_database(
    tmp_path: Path,
) -> AsyncIterator[Database]:
    database = create_database(f"sqlite+aiosqlite:///{tmp_path / 'activity.sqlite3'}")
    document = _graph_document()
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            schema.workspaces.insert().values(
                id=WORKSPACE_ID,
                slug="activity",
                name="Activity",
                kind="shared",
                created_at=NOW,
                updated_at=NOW,
            )
        )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.commit()
    async with database.engine.begin() as connection:
        await connection.execute(
            schema.saved_graphs.insert().values(
                id=GRAPH_ID,
                workspace_id=WORKSPACE_ID,
                name="Activity graph",
                document=document,
                revision=7,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await connection.execute(
            schema.saved_graph_revisions.insert().values(
                workspace_id=WORKSPACE_ID,
                graph_id=GRAPH_ID,
                revision=7,
                name="Activity graph",
                document=document,
                created_at=NOW,
            )
        )
        await connection.execute(
            schema.collaborative_graph_heads.insert().values(
                workspace_id=WORKSPACE_ID,
                graph_id=GRAPH_ID,
                room_epoch=ROOM_EPOCH,
                collaboration_sequence=11,
                checkpoint_sequence=9,
                checkpoint_revision=7,
                name="Activity graph",
                document=document,
                updated_at=NOW,
            )
        )
        await connection.execute(
            schema.graph_executions.insert().values(
                workspace_id=WORKSPACE_ID,
                execution_id=EXECUTION_ID,
                graph_id=GRAPH_ID,
                graph_revision=7,
                status="cancelled",
                scope="all",
                submitted_request=_run_request(),
                created_at=NOW,
                finished_at=NOW,
            )
        )
        await connection.execute(
            schema.artifact_objects.insert().values(
                id=ARTIFACT_ID,
                workspace_id=WORKSPACE_ID,
                artifact_type="text",
                schema_version=1,
                content_type="text/plain",
                storage_backend="inline",
                inline_payload={"text": "activity"},
                metadata={"source": "test"},
            )
        )
        await connection.execute(
            schema.invocation_cache_entries.insert().values(
                workspace_id=WORKSPACE_ID,
                key_sha256="f" * 64,
                generation=UUID("00000000-0000-0000-0000-000000001207"),
                outputs={},
                created_at=NOW,
            )
        )
        await connection.execute(
            schema.materialized_node_outputs.insert().values(
                workspace_id=WORKSPACE_ID,
                graph_id=GRAPH_ID,
                graph_revision=7,
                node_id="known",
                workflow_run_id=WORKFLOW_RUN_ID,
                outputs={},
                materialized_at=NOW,
            )
        )
    try:
        yield database
    finally:
        await database.dispose()

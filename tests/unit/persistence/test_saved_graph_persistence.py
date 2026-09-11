import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
from grafy_core.domain.errors import ConcurrentWriteError
from grafy_core.domain.saved_graphs import (
    GraphFolder,
    GraphOrganization,
    GraphPoint,
    GraphPresentationDocument,
    GraphPresentationViewer,
    SavedGraph,
    SavedGraphArtifactTypeBinding,
    SavedGraphConversion,
    SavedGraphDocument,
    SavedGraphEdge,
    SavedGraphInputPlug,
    SavedGraphNode,
    SavedGraphProjection,
    SavedGraphRevision,
    UserGraphState,
)

from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemySavedGraphUnitOfWork


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database_path = tmp_path / "nested" / "saved-graphs.sqlite3"
    created = create_database(f"sqlite+aiosqlite:///{database_path}")
    async with created.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            text(
                "INSERT INTO workspaces "
                "(id, slug, name, kind, created_at, updated_at) "
                "VALUES (:id, 'team', 'Team', 'shared', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": WORKSPACE_ID.hex},
        )
        await connection.execute(
            text(
                "INSERT INTO workspaces "
                "(id, slug, name, kind, created_at, updated_at) "
                "VALUES (:id, 'other', 'Other', 'shared', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": OTHER_WORKSPACE_ID.hex},
        )
        await connection.execute(
            text(
                "INSERT INTO users "
                "(id, active, email_verified, created_at, updated_at) "
                "VALUES (:id, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": USER_ID.hex},
        )
    try:
        yield created
    finally:
        await created.dispose()


def _document(label: str = "draft") -> SavedGraphDocument:
    return SavedGraphDocument(
        nodes=(
            SavedGraphNode(
                kind="builtin",
                id="source",
                operator_id="text.source",
                operator_version=1,
                config={"text": label},
                position=GraphPoint(x=12.5, y=24.75),
            ),
            SavedGraphNode(
                kind="builtin",
                id="target",
                operator_id="text.target",
                operator_version=2,
                config={"optional": True},
                position=GraphPoint(x=310.0, y=24.75),
                input_plugs=(SavedGraphInputPlug(id="primary-value", port="value"),),
            ),
        ),
        edges=(
            SavedGraphEdge(
                id="source-to-target",
                from_node="source",
                from_port="result",
                to_node="target",
                to_port="value",
                to_plug="primary-value",
                collection_mode="map",
                projection=SavedGraphProjection(path=("payload", "text")),
                conversion_path=(
                    SavedGraphConversion(
                        id="example.text.normalize",
                        version=2,
                    ),
                ),
                route_offset=GraphPoint(x=4.0, y=-8.0),
            ),
        ),
    )


def _graph(
    graph_id: UUID,
    *,
    name: str,
    updated_at: datetime,
) -> SavedGraph:
    return SavedGraph(
        workspace_id=WORKSPACE_ID,
        id=graph_id,
        name=name,
        document=_document(name),
        created_at=updated_at,
        updated_at=updated_at,
    )


@pytest.mark.asyncio
async def test_graph_organization_and_user_state_round_trip_separately(
    database: Database,
) -> None:
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        name="Organized graph",
        document=_document(),
    )
    folder = GraphFolder(workspace_id=WORKSPACE_ID, name="Research")
    organization = GraphOrganization(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        folder_id=folder.id,
    )
    organization.archive(
        archived_at=datetime(2026, 8, 11, 8, 0, tzinfo=UTC),
    )
    state = UserGraphState(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        user_id=USER_ID,
        starred=True,
        last_opened_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
    )

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(graph)
        await unit_of_work.graphs.add_folder(folder)
        await unit_of_work.graphs.save_organization(organization)
        await unit_of_work.graphs.save_user_state(state)
        await unit_of_work.commit()

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        loaded_organization = await unit_of_work.graphs.get_organization(
            workspace_id=WORKSPACE_ID,
            graph_id=graph.id,
        )
        loaded_state = await unit_of_work.graphs.get_user_state(
            workspace_id=WORKSPACE_ID,
            graph_id=graph.id,
            user_id=USER_ID,
        )

    assert loaded_organization is not None
    assert loaded_organization.folder_id == folder.id
    assert loaded_organization.is_archived
    assert loaded_state is not None
    assert loaded_state.starred is True
    assert loaded_state.last_opened_at == datetime(2026, 8, 11, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_database_rejects_cross_workspace_folder_assignment(
    database: Database,
) -> None:
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        name="Tenant-scoped graph",
        document=SavedGraphDocument(),
    )
    foreign_folder = GraphFolder(
        workspace_id=OTHER_WORKSPACE_ID,
        name="Foreign",
    )

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(graph)
        await unit_of_work.graphs.add_folder(foreign_folder)
        await unit_of_work.commit()

    with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
        async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
            await unit_of_work.graphs.save_organization(
                GraphOrganization(
                    workspace_id=WORKSPACE_ID,
                    graph_id=graph.id,
                    folder_id=foreign_folder.id,
                )
            )
            await unit_of_work.commit()


@pytest.mark.asyncio
async def test_file_backed_sqlite_round_trips_saved_graph_in_a_fresh_session(
    database: Database,
) -> None:
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        id=UUID("00000000-0000-0000-0000-000000000101"),
        name="Round trip",
        document=_document(),
        created_at=datetime(2026, 7, 14, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 14, 8, 30, tzinfo=UTC),
    )

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(graph)
        await unit_of_work.commit()

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        loaded = await unit_of_work.graphs.get(WORKSPACE_ID, graph.id)

    assert loaded is not None
    assert loaded is not graph
    assert loaded.id == graph.id
    assert loaded.name == graph.name
    assert loaded.document == graph.document
    assert loaded.revision == 1
    assert loaded.created_at == graph.created_at
    assert loaded.updated_at == graph.updated_at
    assert loaded.created_at.tzinfo is UTC
    assert loaded.updated_at.tzinfo is UTC


@pytest.mark.asyncio
async def test_file_backed_sqlite_round_trips_an_artifact_card_reference(
    database: Database,
) -> None:
    reference = ArtifactRef.from_key(
        artifact_id=UUID("00000000-0000-0000-0000-0000000000bb"),
        key=ArtifactTypeKey("table.data", 1),
        content_hash="c" * 64,
    )
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        id=UUID("00000000-0000-0000-0000-000000000103"),
        name="Card graph",
        document=SavedGraphDocument(
            presentation=GraphPresentationDocument(
                viewers=(
                    GraphPresentationViewer(
                        id="artifact-viewer-card",
                        position=GraphPoint(x=5.0, y=6.0),
                        artifact_ref=reference,
                    ),
                ),
            ),
        ),
        created_at=datetime(2026, 7, 14, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 14, 8, 30, tzinfo=UTC),
    )

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(graph)
        await unit_of_work.commit()

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        loaded = await unit_of_work.graphs.get(WORKSPACE_ID, graph.id)

    assert loaded is not None
    assert loaded.document.presentation.viewers[0].artifact_ref == reference
    assert loaded.document.schema_version == 6


@pytest.mark.asyncio
async def test_sql_json_loads_then_updates_current_documents_in_a_fresh_session(
    database: Database,
) -> None:
    graph_id = UUID("00000000-0000-0000-0000-000000000102")
    stored_time = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
    stored_storage_time = stored_time.replace(tzinfo=None).isoformat(" ")
    stored_document = {
        "schema_version": 6,
        "nodes": [
            {
                "kind": "builtin",
                "id": "source",
                "operator_id": "text.input",
                "operator_version": 1,
                "config": {"text": "stored"},
                "position": {"x": 0.0, "y": 0.0},
            },
            {
                "kind": "builtin",
                "id": "collect",
                "operator_id": "sequence.collect",
                "operator_version": 1,
                "config": {},
                "position": {"x": 200.0, "y": 0.0},
            },
        ],
        "edges": [
            {
                "id": "source-to-collect",
                "from_node": "source",
                "from_port": "text",
                "to_node": "collect",
                "to_port": "items",
                "conversion": {
                    "id": "example.text.normalize",
                    "version": 2,
                },
            }
        ],
    }
    async with database.engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO saved_graphs "
                "(workspace_id, id, name, document, revision, created_at, updated_at) "
                "VALUES (:workspace_id, :id, :name, :document, :revision, :created_at, :updated_at)"
            ),
            {
                "id": graph_id.hex,
                "workspace_id": WORKSPACE_ID.hex,
                "name": "Stored graph",
                "document": json.dumps(stored_document),
                "revision": 1,
                "created_at": stored_storage_time,
                "updated_at": stored_storage_time,
            },
        )

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        loaded = await unit_of_work.graphs.get(WORKSPACE_ID, graph_id)
        assert loaded is not None
        assert loaded.document.schema_version == 6
        assert loaded.document.edges[0].conversion_path == (
            SavedGraphConversion(id="example.text.normalize", version=2),
        )

        source, collect = loaded.document.nodes
        bound_collect = collect.model_copy(
            update={
                "artifact_type_bindings": (
                    SavedGraphArtifactTypeBinding(
                        variable="T",
                        artifact_type=ArtifactTypeKey("scalar.text", 1),
                    ),
                )
            }
        )
        loaded.replace(
            name="Updated graph",
            document=SavedGraphDocument(
                nodes=(source, bound_collect),
                edges=loaded.document.edges,
            ),
            expected_revision=1,
        )
        await unit_of_work.commit()

    async with database.engine.connect() as connection:
        raw_document = await connection.scalar(
            text("SELECT document FROM saved_graphs WHERE id = :id"),
            {"id": graph_id.hex},
        )
    assert isinstance(raw_document, str)
    stored_document = json.loads(raw_document)
    assert stored_document["schema_version"] == 6
    assert "conversion" not in stored_document["edges"][0]
    assert stored_document["edges"][0]["conversion_path"] == [
        {"id": "example.text.normalize", "version": 2}
    ]

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        reloaded = await unit_of_work.graphs.get(WORKSPACE_ID, graph_id)

    assert reloaded is not None
    assert reloaded.name == "Updated graph"
    assert reloaded.revision == 2
    assert reloaded.document.schema_version == 6
    assert reloaded.document.nodes[1].artifact_type_binding_map() == {
        "T": ArtifactTypeKey("scalar.text", 1)
    }


@pytest.mark.asyncio
async def test_update_persists_new_document_and_revision(database: Database) -> None:
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID, name="Original", document=SavedGraphDocument()
    )
    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(graph)
        await unit_of_work.commit()

    replacement = _document("replacement")
    replacement_time = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        loaded = await unit_of_work.graphs.get(WORKSPACE_ID, graph.id)
        assert loaded is not None
        loaded.replace(
            name="Replacement",
            document=replacement,
            expected_revision=1,
            updated_at=replacement_time,
        )
        await unit_of_work.commit()

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        reloaded = await unit_of_work.graphs.get(WORKSPACE_ID, graph.id)

    assert reloaded is not None
    assert reloaded.name == "Replacement"
    assert reloaded.document == replacement
    assert reloaded.revision == 2
    assert reloaded.updated_at == replacement_time


@pytest.mark.asyncio
async def test_revision_snapshots_round_trip_and_preserve_old_documents(
    database: Database,
) -> None:
    original_document = _document("original")
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        name="Original",
        document=original_document,
        created_at=datetime(2026, 7, 14, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 14, 8, 0, tzinfo=UTC),
    )
    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(graph)
        await unit_of_work.graphs.add_revision(graph.snapshot())
        await unit_of_work.commit()

    replacement_document = _document("replacement")
    replacement_time = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        loaded = await unit_of_work.graphs.get(WORKSPACE_ID, graph.id)
        assert loaded is not None
        loaded.replace(
            name="Replacement",
            document=replacement_document,
            expected_revision=1,
            updated_at=replacement_time,
        )
        await unit_of_work.graphs.add_revision(loaded.snapshot())
        await unit_of_work.commit()

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        first = await unit_of_work.graphs.get_revision(WORKSPACE_ID, graph.id, 1)
        second = await unit_of_work.graphs.get_revision(WORKSPACE_ID, graph.id, 2)
        listed = await unit_of_work.graphs.list_revisions(WORKSPACE_ID, graph.id)

    assert first == SavedGraphRevision(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        revision=1,
        name="Original",
        document=original_document,
        created_at=datetime(2026, 7, 14, 8, 0, tzinfo=UTC),
    )
    assert second == SavedGraphRevision(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
        revision=2,
        name="Replacement",
        document=replacement_document,
        created_at=replacement_time,
    )
    assert listed == [second, first]


@pytest.mark.asyncio
async def test_delete_removes_saved_graph(database: Database) -> None:
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID, name="Disposable", document=SavedGraphDocument()
    )
    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(graph)
        await unit_of_work.graphs.add_revision(graph.snapshot())
        await unit_of_work.commit()

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        loaded = await unit_of_work.graphs.get(WORKSPACE_ID, graph.id)
        assert loaded is not None
        await unit_of_work.graphs.remove(WORKSPACE_ID, loaded)
        await unit_of_work.commit()

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        assert await unit_of_work.graphs.get(WORKSPACE_ID, graph.id) is None
        assert await unit_of_work.graphs.get_revision(WORKSPACE_ID, graph.id, 1) is None


@pytest.mark.asyncio
async def test_rollback_discards_pending_insert(database: Database) -> None:
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID, name="Rolled back", document=SavedGraphDocument()
    )

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(graph)
        await unit_of_work.rollback()

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        assert await unit_of_work.graphs.get(WORKSPACE_ID, graph.id) is None


@pytest.mark.asyncio
async def test_list_orders_by_updated_at_descending_then_id_ascending(
    database: Database,
) -> None:
    older_time = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
    newest_time = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
    higher_tie_id = _graph(
        UUID("00000000-0000-0000-0000-000000000003"),
        name="Higher tie id",
        updated_at=older_time,
    )
    newest = _graph(
        UUID("00000000-0000-0000-0000-000000000009"),
        name="Newest",
        updated_at=newest_time,
    )
    lower_tie_id = _graph(
        UUID("00000000-0000-0000-0000-000000000001"),
        name="Lower tie id",
        updated_at=older_time,
    )

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(higher_tie_id)
        await unit_of_work.graphs.add(newest)
        await unit_of_work.graphs.add(lower_tie_id)
        await unit_of_work.commit()

    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        listed = await unit_of_work.graphs.list(WORKSPACE_ID)

    assert [graph.id for graph in listed] == [
        newest.id,
        lower_tie_id.id,
        higher_tie_id.id,
    ]


@pytest.mark.asyncio
async def test_concurrent_session_update_raises_concurrent_write_error(
    database: Database,
) -> None:
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID, name="Original", document=SavedGraphDocument()
    )
    async with SqlAlchemySavedGraphUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(graph)
        await unit_of_work.commit()

    first_uow = SqlAlchemySavedGraphUnitOfWork(database.sessions)
    second_uow = SqlAlchemySavedGraphUnitOfWork(database.sessions)
    async with first_uow as first, second_uow as second:
        first_graph = await first.graphs.get(WORKSPACE_ID, graph.id)
        second_graph = await second.graphs.get(WORKSPACE_ID, graph.id)
        assert first_graph is not None
        assert second_graph is not None
        first_graph.replace(
            name="First",
            document=SavedGraphDocument(),
            expected_revision=1,
        )
        second_graph.replace(
            name="Second",
            document=SavedGraphDocument(),
            expected_revision=1,
        )

        await first.commit()
        with pytest.raises(ConcurrentWriteError):
            await second.commit()

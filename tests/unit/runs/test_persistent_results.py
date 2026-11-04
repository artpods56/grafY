"""``PersistentResultStore`` and ``RepositoryProjectDocuments`` over real SQL.

The adapters are exercised through ``SqlAlchemyUnitOfWork`` against the shared
``database`` fixture (SQLite, plus PostgreSQL when ``GRAFY_TEST_POSTGRES_URL`` is
configured), each store call opening and committing its own session. A fresh
store over a fresh unit of work stands in for a restart.
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from grafy_api.runs.persistence import (
    PersistentResultStore,
    RepositoryProjectDocuments,
)
from grafy_core.artifacts import ArtifactRef
from grafy_core.domain.collaboration import ProjectHead
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.graph_documents import (
    GraphDocument,
    GraphNode,
    GraphPoint,
)
from grafy_core.domain.projects import Project
from grafy_core.domain.runs import Run, RunStatus
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.project import GraphDefinition, ProjectDocument
from grafy_core.kernel.results import FailureRecord
from grafy_persistence import schema
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.support.persistence import (
    WORKSPACE_ONE,
    WORKSPACE_TWO,
)
from tests.support.persistence import (
    database as _database_fixture,
)

database = _database_fixture

PROJECT_ID = UUID("00000000-0000-0000-0000-0000000000c1")
T1 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
T2 = datetime(2026, 9, 1, 11, 0, tzinfo=UTC)


def _store(database: Database, workspace_id: UUID) -> PersistentResultStore:
    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(database.sessions)

    return PersistentResultStore(workspace_id=workspace_id, uow_factory=factory)


def _documents(database: Database) -> RepositoryProjectDocuments:
    return RepositoryProjectDocuments(
        uow_factory=lambda: SqlAlchemyUnitOfWork(database.sessions)
    )


def _ref(artifact_id: UUID) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        artifact_type="scalar.text",
        schema_version=1,
    )


def _key(*, call_path: tuple[str, ...] = ()) -> InstanceKey:
    return InstanceKey(
        project_id=str(PROJECT_ID),
        graph_id="root",
        call_path=call_path,
        node_id="node-1",
    )


async def _seed_project(database: Database, workspace_id: UUID = WORKSPACE_ONE) -> None:
    async with SqlAlchemyUnitOfWork(database.sessions) as uow:
        await uow.projects.add(
            Project(
                workspace_id=workspace_id,
                name="Pipeline",
                id=PROJECT_ID,
                created_at=T1,
                updated_at=T1,
            )
        )
        await uow.commit()


@pytest.mark.asyncio
async def test_store_writes_through_its_own_transaction_and_reads_after_restart(
    database: Database,
) -> None:
    await _seed_project(database)
    fingerprint = "a" * 64
    key = _key()
    store = _store(database, WORKSPACE_ONE)
    stored = await store.put_result(fingerprint, {"out": _ref(uuid4())})
    await store.record_success(key, fingerprint)

    # A restart: a new store over a new unit of work and a new session.
    restarted = _store(database, WORKSPACE_ONE)
    reloaded = await restarted.get_result(fingerprint)
    assert reloaded is not None
    assert reloaded.created_at == stored.created_at
    assert [ref.artifact_id for ref in reloaded.outputs.values()] == [  # type: ignore[union-attr]
        ref.artifact_id
        for ref in stored.outputs.values()  # type: ignore[union-attr]
    ]
    pointer = await restarted.get_pointer(key)
    assert pointer is not None
    assert pointer.last_result_fingerprint == fingerprint
    assert pointer.last_failure is None
    # Append-once holds across the restart too.
    again = await restarted.put_result(fingerprint, {"out": _ref(uuid4())})
    assert again.created_at == stored.created_at


@pytest.mark.asyncio
async def test_concurrent_appends_on_one_fingerprint_keep_a_single_original(
    database: Database,
) -> None:
    fingerprint = "b" * 64
    first = _store(database, WORKSPACE_ONE)
    second = _store(database, WORKSPACE_ONE)
    gate = asyncio.Event()
    artifact_one, artifact_two = uuid4(), uuid4()

    async def put(store: PersistentResultStore, artifact_id: UUID):
        await gate.wait()
        return await store.put_result(fingerprint, {"out": _ref(artifact_id)})

    one = asyncio.create_task(put(first, artifact_one))
    two = asyncio.create_task(put(second, artifact_two))
    gate.set()
    winner, loser = await asyncio.gather(one, two)
    assert winner.created_at == loser.created_at
    assert [ref.artifact_id for ref in winner.outputs.values()] == [  # type: ignore[union-attr]
        ref.artifact_id
        for ref in loser.outputs.values()  # type: ignore[union-attr]
    ]
    async with database.sessions() as session:
        rows = await session.scalar(
            select(func.count())
            .select_from(schema.node_results)
            .where(schema.node_results.c.fingerprint == fingerprint)
        )
        assert rows == 1


@pytest.mark.asyncio
async def test_record_success_requires_a_stored_result(database: Database) -> None:
    await _seed_project(database)
    store = _store(database, WORKSPACE_ONE)
    with pytest.raises(KeyError):
        await store.record_success(_key(), "c" * 64)


@pytest.mark.asyncio
async def test_failure_keeps_the_stale_result_across_a_restart(
    database: Database,
) -> None:
    await _seed_project(database)
    good, bad = "d" * 64, "e" * 64
    key = _key()
    store = _store(database, WORKSPACE_ONE)
    await store.put_result(good, {"out": _ref(uuid4())})
    await store.record_success(key, good)
    await store.record_failure(
        key, FailureRecord(fingerprint=bad, message="boom", failed_at=T1)
    )

    restarted = _store(database, WORKSPACE_ONE)
    pointer = await restarted.get_pointer(key)
    assert pointer is not None
    assert pointer.last_result_fingerprint == good
    assert pointer.last_failure is not None
    assert pointer.last_failure.message == "boom"

    await restarted.put_result(bad, {"out": _ref(uuid4())})
    await restarted.record_success(key, bad)
    pointer = await restarted.get_pointer(key)
    assert pointer is not None
    assert pointer.last_result_fingerprint == bad
    assert pointer.last_failure is None


@pytest.mark.asyncio
async def test_two_workspaces_share_neither_results_nor_pointers(
    database: Database,
) -> None:
    await _seed_project(database, WORKSPACE_ONE)
    fingerprint = "f" * 64
    key = _key()
    one = _store(database, WORKSPACE_ONE)
    two = _store(database, WORKSPACE_TWO)
    stored_one = await one.put_result(fingerprint, {"out": _ref(uuid4())})
    stored_two = await two.put_result(fingerprint, {"out": _ref(uuid4())})
    one_again = await one.get_result(fingerprint)
    two_again = await two.get_result(fingerprint)
    assert one_again is not None and two_again is not None
    assert one_again.created_at == stored_one.created_at
    assert two_again.created_at == stored_two.created_at
    assert (
        list(one_again.outputs.values())[0].artifact_id
        != list(  # type: ignore[union-attr]
            two_again.outputs.values()
        )[0].artifact_id
    )  # type: ignore[union-attr]
    await one.record_success(key, fingerprint)
    # The pointer row belongs to Workspace one's project; Workspace two, which
    # never had this project at all, reads nothing.
    assert await two.get_pointer(key) is None
    assert await two.get_result(fingerprint) is not None


@pytest.mark.asyncio
async def test_restart_interrupts_running_runs_without_disturbing_results(
    database: Database,
) -> None:
    await _seed_project(database)
    fingerprint = "0" * 64
    key = _key()
    store = _store(database, WORKSPACE_ONE)
    stored = await store.put_result(fingerprint, {"out": _ref(uuid4())})
    await store.record_success(key, fingerprint)
    run = Run(
        workspace_id=WORKSPACE_ONE,
        project_id=PROJECT_ID,
        graph_id="root",
        targets=(),
        started_by_user_id=None,
        created_at=T1,
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as uow:
        await uow.runs.add(run)
        await uow.commit()

    # Startup sweep on a fresh unit of work.
    async with SqlAlchemyUnitOfWork(database.sessions) as uow:
        interrupted = await uow.runs.interrupt_unfinished(at=T2, error="restarted")
        await uow.commit()
    assert [item.id for item in interrupted] == [run.id]

    restarted = _store(database, WORKSPACE_ONE)
    reloaded = await restarted.get_result(fingerprint)
    assert reloaded is not None and reloaded.created_at == stored.created_at
    pointer = await restarted.get_pointer(key)
    assert pointer is not None and pointer.last_result_fingerprint == fingerprint
    async with SqlAlchemyUnitOfWork(database.sessions) as uow:
        stored_run = await uow.runs.get(WORKSPACE_ONE, PROJECT_ID, run.id)
    assert stored_run is not None and stored_run.status is RunStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_head_document_reads_the_live_project_document(
    database: Database,
) -> None:
    await _seed_project(database)
    document = ProjectDocument(
        graphs=(
            GraphDefinition(
                id="root",
                name="Root",
                document=GraphDocument(
                    nodes=(
                        GraphNode(
                            kind="builtin",
                            id="node-1",
                            operator_id="text.source",
                            operator_version=1,
                            position=GraphPoint(x=0.0, y=0.0),
                        ),
                    ),
                    edges=(),
                ),
            ),
        )
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as uow:
        await uow.collaboration.add_head(
            ProjectHead(
                workspace_id=WORKSPACE_ONE,
                project_id=PROJECT_ID,
                room_epoch=uuid4(),
                collaboration_sequence=0,
                checkpoint_sequence=0,
                checkpoint_revision=1,
                name="Pipeline",
                document=document,
                updated_at=T1,
            )
        )
        await uow.commit()

    source = _documents(database)
    loaded = await source.head_document(WORKSPACE_ONE, PROJECT_ID)
    assert loaded == document
    assert loaded.get_graph("root").name == "Root"


@pytest.mark.asyncio
async def test_head_document_of_an_unknown_project_or_workspace_is_not_found(
    database: Database,
) -> None:
    source = _documents(database)
    with pytest.raises(NotFoundError) as raised:
        await source.head_document(WORKSPACE_ONE, PROJECT_ID)
    assert raised.value.resource == "Project"
    await _seed_project(database, WORKSPACE_ONE)
    # Scoped to the Workspace pair: Workspace two cannot read the head row
    # that exists under Workspace one.
    with pytest.raises(NotFoundError):
        await source.head_document(WORKSPACE_TWO, PROJECT_ID)

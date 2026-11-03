"""Run and result-store persistence (ADR 0020, issue #195).

Runs on the shared ``database`` fixture: every test executes against SQLite and,
when ``GRAFY_TEST_POSTGRES_URL`` names an empty disposable database, against
PostgreSQL in a per-test schema.
"""

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence, ArtifactTypeKey
from grafy_core.domain.runs import Run, RunStatus, RunTarget
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.results import FailureRecord
from grafy_persistence import schema
from grafy_persistence.adapters.repositories import (
    SqlResultStoreRepository,
    SqlRunRepository,
)
from grafy_persistence.adapters.repositories.runs import instance_digest
from grafy_persistence.database import Database
from tests.support.persistence import database as _base_database_fixture

base_database = _base_database_fixture

WORKSPACE_ONE = UUID("00000000-0000-0000-0000-000000000001")
WORKSPACE_TWO = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
ARTIFACT_ONE = UUID("00000000-0000-0000-0000-0000000000a1")
ARTIFACT_TWO = UUID("00000000-0000-0000-0000-0000000000a2")
ARTIFACT_THREE = UUID("00000000-0000-0000-0000-0000000000a3")
PROJECT_ID = UUID("00000000-0000-0000-0000-0000000000b1")

T1 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
T2 = datetime(2026, 9, 1, 11, 0, tzinfo=UTC)
T3 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
async def database(base_database: Database) -> AsyncIterator[Database]:
    async with base_database.engine.begin() as connection:
        await connection.execute(
            insert(schema.users).values(
                id=USER_ID,
                active=True,
                email_verified=False,
                display_name="Ada",
                created_at=T1,
                updated_at=T1,
            )
        )
    yield base_database


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ref(artifact_id: UUID) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        artifact_type="scalar.text",
        schema_version=1,
    )


def _sequence(
    item_ids: list[UUID], *, metadata: dict[str, object] | None = None
) -> ArtifactRefSequence:
    return ArtifactRefSequence.from_key(
        key=ArtifactTypeKey("scalar.text", 1),
        item_refs=[_ref(artifact_id) for artifact_id in item_ids],
        metadata=metadata,
    )


def _key(
    *,
    project_id: UUID = PROJECT_ID,
    graph_id: str = "root",
    call_path: tuple[str, ...] = (),
    node_id: str = "node-1",
    map_index: int | None = None,
) -> InstanceKey:
    return InstanceKey(
        project_id=str(project_id),
        graph_id=graph_id,
        call_path=call_path,
        node_id=node_id,
        map_index=map_index,
    )


def _run(
    *,
    workspace_id: UUID = WORKSPACE_ONE,
    project_id: UUID = PROJECT_ID,
    created_at: datetime = T1,
    targets: tuple[RunTarget, ...] = (RunTarget(node_id="node-1"),),
) -> Run:
    return Run(
        workspace_id=workspace_id,
        project_id=project_id,
        graph_id="root",
        targets=targets,
        started_by_user_id=USER_ID,
        created_at=created_at,
    )


async def _seed_project(
    database: Database,
    workspace_id: UUID,
    project_id: UUID,
) -> None:
    async with database.sessions.begin() as session:
        await session.execute(
            insert(schema.projects).values(
                id=project_id,
                workspace_id=workspace_id,
                created_by_user_id=USER_ID,
                name="Pipeline",
                created_at=T1,
                updated_at=T1,
            )
        )


# --- node_results ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_result_is_appended_once_and_the_original_is_returned(
    database: Database,
) -> None:
    fingerprint = _fingerprint("fp-append")
    async with database.sessions.begin() as session:
        results = SqlResultStoreRepository(session)
        first = await results.put_result_if_absent(
            WORKSPACE_ONE, fingerprint, {"out": _ref(ARTIFACT_ONE)}, created_at=T1
        )
        second = await results.put_result_if_absent(
            WORKSPACE_ONE, fingerprint, {"out": _ref(ARTIFACT_TWO)}, created_at=T3
        )
    assert first.created_at == T1
    assert second.fingerprint == first.fingerprint
    assert second.created_at == T1
    assert [value.artifact_id for value in second.outputs.values()] == [ARTIFACT_ONE]
    async with database.sessions() as session:
        stored = await SqlResultStoreRepository(session).get_result(
            WORKSPACE_ONE, fingerprint
        )
    assert stored is not None
    assert stored.created_at == T1
    assert list(stored.outputs)[0] == "out"
    assert stored.outputs["out"].artifact_id == ARTIFACT_ONE  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_the_same_fingerprint_in_two_workspaces_never_shares_a_result(
    database: Database,
) -> None:
    fingerprint = _fingerprint("fp-shared-key")
    async with database.sessions.begin() as session:
        results = SqlResultStoreRepository(session)
        one = await results.put_result_if_absent(
            WORKSPACE_ONE, fingerprint, {"out": _ref(ARTIFACT_ONE)}, created_at=T1
        )
        two = await results.put_result_if_absent(
            WORKSPACE_TWO, fingerprint, {"out": _ref(ARTIFACT_TWO)}, created_at=T2
        )
        assert (await results.get_result(WORKSPACE_ONE, fingerprint)).outputs[
            "out"
        ].artifact_id == ARTIFACT_ONE  # type: ignore[union-attr]
        assert (await results.get_result(WORKSPACE_TWO, fingerprint)).outputs[
            "out"
        ].artifact_id == ARTIFACT_TWO  # type: ignore[union-attr]
    assert one.created_at == T1 and two.created_at == T2


# --- instance_pointers ------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_instance_keys_round_trip_as_separate_pointers(
    database: Database,
) -> None:
    await _seed_project(database, WORKSPACE_ONE, PROJECT_ID)
    keys = {
        "root": _key(),
        "one-call": _key(call_path=("call-a",)),
        "two-calls": _key(call_path=("call-a", "call-b")),
        "map-0": _key(map_index=0),
        "map-1": _key(map_index=1),
    }
    digests = {instance_digest(key) for key in keys.values()}
    assert len(digests) == len(keys)
    fingerprints = {name: _fingerprint(name) for name in keys}
    async with database.sessions.begin() as session:
        results = SqlResultStoreRepository(session)
        for name, key in keys.items():
            await results.put_result_if_absent(
                WORKSPACE_ONE,
                fingerprints[name],
                {"out": _ref(ARTIFACT_ONE)},
                created_at=T1,
            )
            await results.set_success_pointer(WORKSPACE_ONE, key, fingerprints[name])
    async with database.sessions() as session:
        pointers = await SqlResultStoreRepository(session).list_pointers(
            WORKSPACE_ONE, PROJECT_ID
        )
    assert set(pointers) == set(keys.values())
    for name, key in keys.items():
        pointer = pointers[key]
        assert pointer.last_result_fingerprint == fingerprints[name]
        assert pointer.last_failure is None
    async with database.sessions() as session:
        results = SqlResultStoreRepository(session)
        for name, key in keys.items():
            pointer = await results.get_pointer(WORKSPACE_ONE, key)
            assert pointer is not None
            assert pointer.last_result_fingerprint == fingerprints[name]
        # A key of another Workspace with the same coordinates reads as absent.
        assert (await results.get_pointer(WORKSPACE_TWO, keys["root"])) is None


@pytest.mark.asyncio
async def test_failure_preserves_the_last_result_and_success_clears_the_failure(
    database: Database,
) -> None:
    await _seed_project(database, WORKSPACE_ONE, PROJECT_ID)
    key = _key()
    good = _fingerprint("good")
    bad = _fingerprint("bad")
    async with database.sessions.begin() as session:
        results = SqlResultStoreRepository(session)
        await results.put_result_if_absent(
            WORKSPACE_ONE, good, {"out": _ref(ARTIFACT_ONE)}, created_at=T1
        )
        await results.set_success_pointer(WORKSPACE_ONE, key, good)
        assert (
            await results.get_pointer(WORKSPACE_ONE, key)
        ).last_result_fingerprint == good  # type: ignore[union-attr]

        await results.set_failure_pointer(
            WORKSPACE_ONE,
            key,
            FailureRecord(fingerprint=bad, message="boom", failed_at=T2),
        )
    async with database.sessions() as session:
        pointer = await SqlResultStoreRepository(session).get_pointer(
            WORKSPACE_ONE, key
        )
    assert pointer is not None
    assert pointer.last_result_fingerprint == good
    assert pointer.last_failure == FailureRecord(
        fingerprint=bad, message="boom", failed_at=T2
    )
    async with database.sessions.begin() as session:
        results = SqlResultStoreRepository(session)
        await results.set_failure_pointer(
            WORKSPACE_ONE,
            key,
            FailureRecord(fingerprint=bad, message="boom again", failed_at=T3),
        )
        await results.put_result_if_absent(
            WORKSPACE_ONE, bad, {"out": _ref(ARTIFACT_TWO)}, created_at=T3
        )
        await results.set_success_pointer(WORKSPACE_ONE, key, bad)
    async with database.sessions() as session:
        pointer = await SqlResultStoreRepository(session).get_pointer(
            WORKSPACE_ONE, key
        )
    assert pointer is not None
    assert pointer.last_result_fingerprint == bad
    assert pointer.last_failure is None


# --- project_runs ------------------------------------------------------------


@pytest.mark.asyncio
async def test_runs_list_newest_first_and_active_only_within_one_workspace(
    database: Database,
) -> None:
    other_project = UUID("00000000-0000-0000-0000-0000000000b2")
    await _seed_project(database, WORKSPACE_ONE, PROJECT_ID)
    await _seed_project(database, WORKSPACE_TWO, other_project)
    running_first = _run(created_at=T1, targets=())
    finished = _run(created_at=T2)
    finished.finish(RunStatus.FAILED, error="node exploded", at=T3)
    running_last = _run(created_at=T3)
    async with database.sessions.begin() as session:
        runs = SqlRunRepository(session)
        for run in (running_first, finished, running_last):
            await runs.add(run)
        # The same Run identity in another Workspace is a different lookup.
        elsewhere = _run(workspace_id=WORKSPACE_TWO, project_id=other_project)
        await runs.add(elsewhere)
    async with database.sessions() as session:
        runs = SqlRunRepository(session)
        listed = await runs.list_for_project(WORKSPACE_ONE, PROJECT_ID)
        assert [run.id for run in listed] == [
            running_last.id,
            finished.id,
            running_first.id,
        ]
        active = await runs.list_for_project(
            WORKSPACE_ONE, PROJECT_ID, active_only=True
        )
        assert [run.id for run in active] == [running_last.id, running_first.id]
        capped = await runs.list_for_project(
            WORKSPACE_ONE, PROJECT_ID, active_only=True, limit=1
        )
        assert [run.id for run in capped] == [running_last.id]
        assert await runs.get(WORKSPACE_ONE, PROJECT_ID, elsewhere.id) is None
        assert await runs.get(WORKSPACE_TWO, other_project, running_first.id) is None
        other_listed = await runs.list_for_project(WORKSPACE_TWO, other_project)
        assert [run.id for run in other_listed] == [elsewhere.id]
        # Full round trip of the run's own facts.
        loaded = await runs.get(WORKSPACE_ONE, PROJECT_ID, running_first.id)
    assert loaded is not None
    assert loaded.targets == ()
    assert loaded.graph_id == "root"
    assert loaded.started_by_user_id == USER_ID
    assert loaded.status is RunStatus.RUNNING
    loaded_finished = next(run for run in listed if run.id == finished.id)
    assert loaded_finished.status is RunStatus.FAILED
    assert loaded_finished.finished_at == T3
    assert loaded_finished.error == "node exploded"


@pytest.mark.asyncio
async def test_save_transitions_only_the_run_of_the_scoped_identity(
    database: Database,
) -> None:
    other_project = UUID("00000000-0000-0000-0000-0000000000b2")
    await _seed_project(database, WORKSPACE_ONE, PROJECT_ID)
    await _seed_project(database, WORKSPACE_TWO, other_project)
    run = _run(created_at=T1)
    async with database.sessions.begin() as session:
        await SqlRunRepository(session).add(run)
    # A finished Run of an unrelated identity claiming this row's id must not
    # touch the row: the UPDATE is scoped to workspace, project and id together.
    impostor = _run(workspace_id=WORKSPACE_TWO, project_id=other_project)
    impostor.id = run.id
    impostor.finish(RunStatus.CANCELLED, error="not this one", at=T2)
    async with database.sessions.begin() as session:
        await SqlRunRepository(session).save(impostor)
    async with database.sessions() as session:
        stored = await SqlRunRepository(session).get(WORKSPACE_ONE, PROJECT_ID, run.id)
    assert stored is not None
    assert stored.status is RunStatus.RUNNING
    assert stored.finished_at is None and stored.error is None
    # The owner's own transition persists status, finish stamp and error.
    run.finish(RunStatus.SUCCEEDED, at=T3)
    async with database.sessions.begin() as session:
        await SqlRunRepository(session).save(run)
    async with database.sessions() as session:
        stored = await SqlRunRepository(session).get(WORKSPACE_ONE, PROJECT_ID, run.id)
    assert stored is not None
    assert stored.status is RunStatus.SUCCEEDED
    assert stored.finished_at == T3
    assert stored.error is None


@pytest.mark.asyncio
async def test_interrupt_unfinished_marks_running_runs_and_leaves_results_untouched(
    database: Database,
) -> None:
    project_two = UUID("00000000-0000-0000-0000-0000000000b3")
    await _seed_project(database, WORKSPACE_ONE, PROJECT_ID)
    await _seed_project(database, WORKSPACE_TWO, project_two)
    running = _run(created_at=T1)
    finished = _run(created_at=T2)
    finished.finish(RunStatus.SUCCEEDED, at=T2)
    foreign_running = _run(workspace_id=WORKSPACE_TWO, project_id=project_two)
    fingerprint = _fingerprint("survivor")
    key = _key()
    async with database.sessions.begin() as session:
        runs = SqlRunRepository(session)
        for run in (running, finished, foreign_running):
            await runs.add(run)
        results = SqlResultStoreRepository(session)
        await results.put_result_if_absent(
            WORKSPACE_ONE, fingerprint, {"out": _ref(ARTIFACT_ONE)}, created_at=T1
        )
        await results.set_success_pointer(WORKSPACE_ONE, key, fingerprint)
    async with database.sessions.begin() as session:
        interrupted = await SqlRunRepository(session).interrupt_unfinished(
            at=T3, error="api restarted"
        )
    assert {run.id for run in interrupted} == {running.id, foreign_running.id}
    for run in interrupted:
        assert run.status is RunStatus.INTERRUPTED
        assert run.finished_at == T3
        assert run.error == "api restarted"
    async with database.sessions() as session:
        runs = SqlRunRepository(session)
        stored_running = await runs.get(WORKSPACE_ONE, PROJECT_ID, running.id)
        stored_finished = await runs.get(WORKSPACE_ONE, PROJECT_ID, finished.id)
        assert stored_running is not None and stored_running.status is (
            RunStatus.INTERRUPTED
        )
        assert stored_finished is not None and stored_finished.status is (
            RunStatus.SUCCEEDED
        )
        assert stored_finished.finished_at == T2
        assert (
            await runs.list_for_project(WORKSPACE_ONE, PROJECT_ID, active_only=True)
            == []
        )
        # A second pass has nothing left to interrupt.
        assert await runs.interrupt_unfinished(at=T3, error="again") == []
        # Results and pointers survive the interruption sweep untouched.
        results = SqlResultStoreRepository(session)
        stored = await results.get_result(WORKSPACE_ONE, fingerprint)
        assert stored is not None and stored.created_at == T1
        pointer = await results.get_pointer(WORKSPACE_ONE, key)
        assert pointer.last_result_fingerprint == fingerprint  # type: ignore[union-attr]
        assert pointer.last_failure is None  # type: ignore[union-attr]


# --- lifecycle and reference guards ----------------------------------------------


@pytest.mark.asyncio
async def test_project_deletion_cascades_pointers_and_runs_but_results_survive(
    database: Database,
) -> None:
    await _seed_project(database, WORKSPACE_ONE, PROJECT_ID)
    run = _run()
    fingerprint = _fingerprint("persist-through-deletion")
    key = _key()
    async with database.sessions.begin() as session:
        await SqlRunRepository(session).add(run)
        results = SqlResultStoreRepository(session)
        await results.put_result_if_absent(
            WORKSPACE_ONE, fingerprint, {"out": _ref(ARTIFACT_ONE)}, created_at=T1
        )
        await results.set_success_pointer(WORKSPACE_ONE, key, fingerprint)
    async with database.sessions.begin() as session:
        await session.execute(
            schema.projects.delete().where(
                schema.projects.c.workspace_id == WORKSPACE_ONE,
                schema.projects.c.id == PROJECT_ID,
            )
        )
    async with database.sessions() as session:
        assert (
            await SqlRunRepository(session).get(WORKSPACE_ONE, PROJECT_ID, run.id)
            is None
        )
        assert (
            await SqlResultStoreRepository(session).list_pointers(
                WORKSPACE_ONE, PROJECT_ID
            )
        ) == {}
        stored = await SqlResultStoreRepository(session).get_result(
            WORKSPACE_ONE, fingerprint
        )
        assert stored is not None
        assert stored.outputs["out"].artifact_id == ARTIFACT_ONE  # type: ignore[union-attr]
        rows = await session.scalar(
            select(func.count()).select_from(schema.node_results)
        )
        assert rows == 1


@pytest.mark.asyncio
async def test_artifact_reference_check_covers_scalars_sequence_items_and_workspaces(
    database: Database,
) -> None:
    async with database.sessions.begin() as session:
        results = SqlResultStoreRepository(session)
        await results.put_result_if_absent(
            WORKSPACE_ONE,
            _fingerprint("scalar-ref"),
            {"out": _ref(ARTIFACT_ONE)},
            created_at=T1,
        )
        await results.put_result_if_absent(
            WORKSPACE_ONE,
            _fingerprint("sequence-ref"),
            {"items": _sequence([ARTIFACT_TWO, ARTIFACT_THREE])},
            created_at=T1,
        )
    async with database.sessions() as session:
        results = SqlResultStoreRepository(session)
        assert await results.artifact_is_referenced(WORKSPACE_ONE, ARTIFACT_ONE)
        assert await results.artifact_is_referenced(WORKSPACE_ONE, ARTIFACT_TWO)
        assert await results.artifact_is_referenced(WORKSPACE_ONE, ARTIFACT_THREE)
        assert not await results.artifact_is_referenced(WORKSPACE_ONE, uuid4())
        # Another Workspace holds no results naming these artifacts, even
        # though the same fingerprints exist in the first one.
        assert not await results.artifact_is_referenced(WORKSPACE_TWO, ARTIFACT_ONE)


@pytest.mark.asyncio
async def test_metadata_text_naming_an_artifact_is_not_a_reference(
    database: Database,
) -> None:
    unrelated = ARTIFACT_ONE
    named_in_metadata = str(unrelated)
    async with database.sessions.begin() as session:
        await SqlResultStoreRepository(session).put_result_if_absent(
            WORKSPACE_ONE,
            _fingerprint("metadata-lookalike"),
            {
                "items": _sequence(
                    [ARTIFACT_TWO], metadata={"notes": f"mentions {named_in_metadata}"}
                )
            },
            created_at=T1,
        )
    async with database.sessions() as session:
        results = SqlResultStoreRepository(session)
        # The SQL candidate prefilter matches this row's text; the typed check
        # is what refuses to call it a reference.
        assert not await results.artifact_is_referenced(WORKSPACE_ONE, unrelated)
        assert await results.artifact_is_referenced(WORKSPACE_ONE, ARTIFACT_TWO)

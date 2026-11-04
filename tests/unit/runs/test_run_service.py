"""The Run service: demand, results and instance state over the kernel scheduler.

ADR 0020 says a Run is a demand for targets to become fresh, that any number of
Runs are active in one Project, that cancelling withdraws one demand rather than
stopping work, that an edit leaves the instance stale while the computation stores
what it produced under the fingerprint it started with, and that a restart
interrupts unfinished Runs without disturbing stored results. Every claim is
checked here against the real scheduler, planner, fingerprint function and an
in-memory result store, with only the four seams the service is built on faked.

The fake runner moves only on events and the fake events land in a queue, so no
test here waits on a clock: each one says which moment of a computation it is
standing at.
"""

import asyncio
from pathlib import Path

import pytest

from grafy_api.runs.ports import RunNotFoundError, RunRejectedError
from grafy_api.runs.service import RunService
from grafy_core.domain.runs import RunStatus, RunTarget
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.state import InstanceState
from tests.unit.kernel.builders import make_key
from tests.unit.runs.fakes import (
    OTHER_PROJECT_ID,
    OTHER_WORKSPACE_ID,
    PROJECT_ID,
    SECRET_OPERATOR,
    USER_ID,
    VALUE_OPERATOR,
    WORKSPACE_ID,
    FakeComputationRunnerFactory,
    FakeProjectDocumentSource,
    FakeResultStoreFactory,
    FakeRunEvents,
    FakeRunner,
    FakeSecretRevisionResolver,
    FakeUnitOfWorkFactory,
    RunServiceHarness,
    build_catalog,
    caller_graph,
    child_graph,
    document,
    edge,
    facts_factory,
    graph,
    harness,
    input_node,
    main_graph,
    never_node,
    node_ids,
    output_node,
    run_row,
    side_graph,
    value_node,
)

GRAPH = "main"


def target(node_id: str, call_path: tuple[str, ...] = ()) -> RunTarget:
    return RunTarget(node_id=node_id, call_path=call_path)


def key_of(node_id: str, graph_id: str = GRAPH) -> InstanceKey:
    return make_key(node_id, project_id=str(PROJECT_ID), graph_id=graph_id)


def graph_of(*, refresh: dict[str, int] | None = None, value: int = 1):
    return graph(
        GRAPH,
        [input_node("in", "x"), never_node("keep"), output_node("out", "r")],
        [edge("in", "keep"), edge("keep", "out")],
        refresh=refresh,
    )


# --- A Run is a demand, recorded and announced -------------------------------


async def test_a_run_is_recorded_announced_and_waits_for_its_own_computation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))

    run = await service.start(targets=[target("value")])
    started = await service.started()
    await service.running("value")

    assert started.id == run.id
    assert run.status is RunStatus.RUNNING
    assert started.graph_id == GRAPH
    assert started.targets == (target("value"),)
    assert started.started_by_user_id == USER_ID
    assert service.runner.calls == ["value"]
    # Nothing has finished, so nothing has been saved and no outcome was announced.
    # The one announcement that did follow the start is the state the computation
    # moved to: the room was told it was running without being asked.
    assert service.rows.saved == []
    assert service.events.kinds() == ["run_started", "instances_changed"]

    finished = await service.complete("value")

    assert finished.id == run.id
    assert finished.status is RunStatus.SUCCEEDED
    assert finished.finished_at is not None
    assert finished.error is None
    assert service.rows.saved == [run.id]
    stored = await service.service.get_run(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        run_id=run.id,
    )
    assert stored.status is RunStatus.SUCCEEDED
    await service.close()


async def test_no_targets_means_the_whole_graph_that_was_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(
        tmp_path,
        monkeypatch,
        project=document(main_graph(), side_graph("lonely")),
    )

    run = await service.start()
    await service.started()
    await service.running("value")

    # ``side`` is another definition in the same Project, and an instance of it is
    # not part of a Run that named ``main``. ``sink`` is part of it but sits behind
    # ``value``, so it waits rather than being started and then corrected.
    assert run.targets == ()
    assert service.runner.calls == ["value"]
    assert service.state_of(await service.states(GRAPH), "sink") is InstanceState.QUEUED

    service.release("value")
    await service.running("sink")
    assert (await service.complete("sink")).status is RunStatus.SUCCEEDED
    assert service.runner.calls == ["value", "sink"]
    await service.close()


# --- Many Runs in one Project ------------------------------------------------


async def test_two_runs_in_one_project_are_both_active_and_both_announced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(
        tmp_path,
        monkeypatch,
        project=document(main_graph(), side_graph()),
    )

    first = await service.start(targets=[target("value")])
    await service.started()
    second = await service.start(graph_id="side", targets=[target("solo")])
    await service.started()
    await service.running("solo")

    active = await service.service.list_runs(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        active_only=True,
    )

    assert {run.id for run in active} == {first.id, second.id}
    assert all(run.status is RunStatus.RUNNING for run in active)
    assert service.events.kinds().count("run_started") == 2
    # One Project, one concurrency budget: the second Run joined the scheduler the
    # first one built instead of opening a second one beside it.
    assert service.builder.built == [(WORKSPACE_ID, PROJECT_ID)]

    service.release("value")
    assert await service.finished(first.id)
    service.release("solo")
    assert (await service.finished(second.id)).status is RunStatus.SUCCEEDED
    assert service.runner.calls == ["value", "solo"]
    assert (
        await service.service.list_runs(
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            active_only=True,
        )
        == []
    )
    await service.close()


async def test_cancelling_one_run_keeps_the_computation_another_run_still_needs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(
        tmp_path,
        monkeypatch,
        project=document(
            graph(
                GRAPH,
                # Two nodes that compute different things: two Run demands over one
                # of them, and a second one only the first Run needs.
                [value_node("only_a", value=1), value_node("shared", value=2)],
            )
        ),
    )

    both = await service.start(targets=[target("only_a"), target("shared")])
    await service.started()
    shared_only = await service.start(targets=[target("shared")])
    await service.started()
    await service.running("only_a", "shared")
    # The second Run joined the computation already running rather than starting a
    # second attempt at the same fingerprint.
    assert service.runner.calls == ["only_a", "shared"]

    cancelled = await service.service.cancel(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        run_id=both.id,
    )

    assert cancelled.status is RunStatus.CANCELLED
    assert cancelled.finished_at is not None
    # The computation only this Run demanded went with the demand; the one the
    # other Run still needs is untouched and still running.
    assert service.runner.cancelled == ["only_a"]
    assert service.runner.calls == ["only_a", "shared"]
    assert (await service.finished(both.id)).status is RunStatus.CANCELLED

    finished = await service.complete("shared", run_id=shared_only.id)

    assert finished.id == shared_only.id
    assert finished.status is RunStatus.SUCCEEDED
    pointer = await service.store.get_pointer(key_of("shared"))
    assert pointer is not None
    assert pointer.last_result_fingerprint == _fingerprint_of(service, "shared")
    await service.close()


async def test_cancelling_a_finished_run_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))
    run = await service.start(targets=[target("value")])
    await service.started()
    await service.complete("value")

    again = await service.service.cancel(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        run_id=run.id,
    )

    assert again.status is RunStatus.SUCCEEDED
    assert service.events.kinds().count("run_finished") == 1
    assert service.runner.cancelled == []
    await service.close()


async def test_a_run_that_was_never_started_cannot_be_cancelled_or_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))

    for read in (
        service.service.get_run(
            workspace_id=WORKSPACE_ID, project_id=PROJECT_ID, run_id=PROJECT_ID
        ),
        service.service.cancel(
            workspace_id=WORKSPACE_ID, project_id=PROJECT_ID, run_id=PROJECT_ID
        ),
    ):
        with pytest.raises(RunNotFoundError):
            await read

    with pytest.raises(RunNotFoundError):
        await service.service.get_run(
            workspace_id=OTHER_WORKSPACE_ID,
            project_id=PROJECT_ID,
            run_id=PROJECT_ID,
        )
    await service.close()


async def test_a_run_of_one_project_is_not_another_project_s_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(
        tmp_path,
        monkeypatch,
        project=document(main_graph()),
        other_project=document(side_graph()),
    )
    run = await service.start()
    await service.started()

    with pytest.raises(RunNotFoundError):
        await service.service.get_run(
            workspace_id=WORKSPACE_ID,
            project_id=OTHER_PROJECT_ID,
            run_id=run.id,
        )
    assert (
        await service.service.list_runs(
            workspace_id=WORKSPACE_ID,
            project_id=OTHER_PROJECT_ID,
        )
        == []
    )
    await service.complete("value", "sink")
    await service.close()


# --- An edit while a Run is out ----------------------------------------------


async def test_an_edit_during_a_run_leaves_the_instance_stale_and_the_result_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph(value=1)))

    run = await service.start(targets=[target("sink")])
    await service.started()
    await service.running("value")
    computed_for = _fingerprint_of(service, "value")
    assert run.targets == (target("sink"),)

    # A collaborator moves the node the computation is busy with. The Run asked for
    # ``sink``, so its plan stands, and what ``value`` produces still belongs to
    # the fingerprint it was computed under.
    service.documents.edit(document(main_graph(value=2)))
    service.release("value")
    await service.running("sink")
    finished = await service.complete("sink")

    assert finished.id == run.id
    assert finished.status is RunStatus.SUCCEEDED
    stored = await service.store.get_result(computed_for)
    assert stored is not None

    states = await service.states(GRAPH)
    value = next(snapshot for snapshot in states if snapshot.key.node_id == "value")
    assert value.state is InstanceState.STALE
    assert value.fingerprint != computed_for
    # The document moved on, yet the instance still points at what it last produced.
    assert value.last_result_fingerprint == computed_for
    assert service.state_of(states, "sink") is InstanceState.STALE

    snapshot, result = await service.service.instance_result(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        key=value.key,
    )
    assert snapshot.state is InstanceState.STALE
    assert result is not None
    assert result.fingerprint == computed_for
    await service.close()


async def test_the_run_after_an_edit_demands_the_new_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph(value=1)))
    first = await service.start(targets=[target("value")])
    await service.started()
    await service.running("value")
    computed_for = _fingerprint_of(service, "value")
    await service.complete("value")
    assert service.state_of(await service.states(GRAPH), "value") is InstanceState.FRESH

    service.documents.edit(document(main_graph(value=2)))
    await service.service.project_changed(
        workspace_id=WORKSPACE_ID, project_id=PROJECT_ID
    )

    # The edit alone did not run anything; it only made the instance stale.
    assert service.runner.calls == ["value"]
    assert service.state_of(await service.states(GRAPH), "value") is InstanceState.STALE

    service.reset_runner()
    second = await service.start(targets=[target("value")])
    await service.running("value")

    assert second.id != first.id
    assert service.runner.calls == ["value"]
    # What it is busy computing is the edited node's own fingerprint, not the one the
    # earlier Run stored under.
    assert _fingerprint_of(service, "value") != computed_for
    finished = await service.complete("value", run_id=second.id)
    assert finished.status is RunStatus.SUCCEEDED
    assert service.state_of(await service.states(GRAPH), "value") is InstanceState.FRESH
    await service.close()


# --- Instance state and results ----------------------------------------------


async def test_a_computation_in_flight_is_published_before_anything_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(
        tmp_path, monkeypatch, project=document(main_graph()), concurrency=1
    )

    mark = service.mark()
    await service.start()
    published = await service.published(after=mark)

    # One computation is holding still and the other waits on it, and the room was
    # told both without anyone asking, before either of them had anything to show.
    assert published.state_of("value") is InstanceState.RUNNING
    assert published.state_of("sink") is InstanceState.QUEUED
    assert "run_finished" not in service.events.kinds()[mark:]
    await service.running("value")

    assert (await service.complete("value", "sink")).status is RunStatus.SUCCEEDED
    await service.close()


async def test_an_instance_the_edit_removed_is_published_as_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))
    await service.start()
    await service.complete("value", "sink")
    before = service.mark()

    service.documents.edit(document(main_graph(with_sink=False)))
    await service.service.project_changed(
        workspace_id=WORKSPACE_ID, project_id=PROJECT_ID
    )

    published = await service.published(after=before)
    # What left the document is named by key. What did not move is not repeated: the
    # instance that stayed fresh is not in the delta, and the room already holds it.
    assert [key.node_id for key in published.removed] == ["sink"]
    assert published.changed == ()
    await service.close()


async def test_a_document_that_did_not_move_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))
    await service.start()
    await service.complete("value", "sink")
    before = len(service.events.published())

    await service.service.project_changed(
        workspace_id=WORKSPACE_ID, project_id=PROJECT_ID
    )

    assert len(service.events.published()) == before
    await service.close()


async def test_instance_states_are_read_through_the_workspace_that_owns_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))
    await service.start()
    await service.complete("value", "sink")

    states = await service.states()
    other = await service.service.instance_states(
        workspace_id=OTHER_WORKSPACE_ID,
        project_id=PROJECT_ID,
    )

    assert {snapshot.state for snapshot in states} == {InstanceState.FRESH}
    # Another Workspace has its own result store, so the same document reads there
    # as nothing having ever run.
    assert {snapshot.state for snapshot in other} == {InstanceState.STALE}
    assert set(service.store_factory.stores) == {WORKSPACE_ID, OTHER_WORKSPACE_ID}
    await service.close()


async def test_an_instance_the_project_does_not_hold_has_no_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))

    with pytest.raises(RunRejectedError) as raised:
        await service.service.instance_result(
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            key=key_of("nowhere"),  # type: ignore[arg-type]
        )

    assert raised.value.code == "unknown_target"
    await service.close()


# --- Failure -----------------------------------------------------------------


async def test_a_failing_computation_fails_the_run_and_the_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))
    service.runner.fail_with("value", "the sandbox refused to start")

    run = await service.start(targets=[target("value")])
    await service.started()
    finished = await service.complete("value")

    assert finished.id == run.id
    assert finished.status is RunStatus.FAILED
    assert finished.error == "the sandbox refused to start"
    states = await service.states(GRAPH)
    failed = next(snapshot for snapshot in states if snapshot.key.node_id == "value")
    assert failed.state is InstanceState.FAILED
    assert failed.error == "the sandbox refused to start"
    # A failure belongs to the instance, never to the result store: nothing was
    # appended, so a rerun is a retry rather than a cache hit.
    assert await service.store.get_result(failed.fingerprint) is None
    await service.close()


async def test_a_run_whose_upstream_failed_reports_the_message_and_ran_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))
    service.runner.fail_with("value", "no upstream value")

    await service.start()
    await service.started()
    finished = await service.complete("value")

    assert finished.status is RunStatus.FAILED
    assert "no upstream value" in (finished.error or "")
    assert service.runner.calls == ["value"]
    states = await service.states(GRAPH)
    # The downstream computation was skipped rather than run against a missing
    # input, and a skip is not a failure of that instance's own.
    assert service.state_of(states, "sink") is InstanceState.STALE
    await service.close()


async def test_a_rerun_after_a_failure_replaces_the_pointer_of_a_later_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))
    service.runner.fail_with("value", "the provider was down")
    await service.start(targets=[target("value")])
    await service.started()
    failed = await service.complete("value")
    assert failed.status is RunStatus.FAILED
    assert (
        service.state_of(await service.states(GRAPH), "value") is InstanceState.FAILED
    )

    outcome, result = await service.service.instance_result(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        key=key_of("value"),  # type: ignore[arg-type]
    )
    assert outcome.state is InstanceState.FAILED
    assert result is None

    service.runner.failures.clear()
    retry = await service.start(targets=[target("value")])
    assert (await service.complete("value", run_id=retry.id)).id == retry.id

    assert service.state_of(await service.states(GRAPH), "value") is InstanceState.FRESH
    await service.close()


# --- Fresh targets -----------------------------------------------------------


async def test_a_run_over_what_is_already_fresh_finishes_without_computing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))
    first = await service.start()
    await service.started()
    await service.complete("value", "sink")
    computed = list(service.runner.calls)

    mark = service.mark()
    second = await service.start()
    started = await service.started(after=mark)
    finished = await service.finished(after=mark)

    assert second.id != first.id
    # A Run that asked for what already held is still a Run: recorded, announced and
    # answered with a status, in the same call that started it.
    assert second.status is RunStatus.SUCCEEDED
    assert started.id == second.id and started.status is RunStatus.SUCCEEDED
    assert finished.id == second.id and finished.status is RunStatus.SUCCEEDED
    assert finished.error is None
    assert service.runner.calls == computed
    assert service.rows.added == [first.id, second.id]
    assert service.rows.saved == [first.id, second.id]
    await service.close()


async def test_a_run_whose_targets_are_a_fresh_frontier_runs_only_what_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))
    await service.start(targets=[target("value")])
    await service.started()
    await service.complete("value")

    run = await service.start(targets=[target("sink")])
    await service.running("sink")

    # ``value`` is fresh, so only ``sink`` is demanded and the store is what feeds
    # the plan's closure instead of a second computation.
    assert service.runner.calls == ["value", "sink"]
    assert (await service.complete("sink", run_id=run.id)).id == run.id
    await service.close()


# --- What a Run refuses ------------------------------------------------------


async def test_a_graph_the_project_does_not_hold_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))

    with pytest.raises(RunRejectedError) as raised:
        await service.start(graph_id="nowhere")

    assert raised.value.code == "unknown_graph"
    assert service.rows.added == []
    await service.close()


async def test_a_target_that_is_not_an_instance_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))

    with pytest.raises(RunRejectedError) as raised:
        await service.start(targets=[target("nowhere")])

    assert raised.value.code == "unknown_target"
    assert service.rows.added == []
    assert service.runner.calls == []
    await service.close()


async def test_an_operator_this_build_does_not_register_rejects_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This deployment never registered ``test.never``, so a document naming it has
    # nothing trustworthy to fingerprint and the Run must say so.
    service = harness(
        tmp_path,
        monkeypatch,
        project=document(graph(GRAPH, [value_node("v"), never_node("gone")])),
        registers=(VALUE_OPERATOR, SECRET_OPERATOR),
    )

    with pytest.raises(RunRejectedError) as raised:
        await service.start()

    assert raised.value.code == "unknown_operator"
    # Nothing was demanded on the strength of an operator nobody registered: no
    # row, no computation, no announcement to take back.
    assert service.rows.added == []
    assert service.runner.calls == []
    assert service.events.recorded == []
    await service.close()


async def test_a_boundary_node_is_reusable_where_a_registered_node_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ADR half that says a Graph boundary passes its input straight through.

    ``EXACT`` is what that claim has to mean for a boundary, and the way to see it
    is an explicit refresh: a node whose result is reused does not move.
    """
    service = harness(tmp_path, monkeypatch, project=document(graph_of()))

    run = await service.start()
    await service.started()
    await service.running("in")
    # The non-reusing node waits for the input that reaches it, and the output that
    # reads the non-reusing node waits for that.
    assert service.runner.calls == ["in"]
    service.release("in")
    await service.running("keep")
    service.release("keep")
    assert (await service.complete("out", run_id=run.id)).status is RunStatus.SUCCEEDED
    assert service.runner.calls == ["in", "keep", "out"]

    # An explicit refresh is a document command, so it reaches a Run as an edit of
    # the generations. Only what does not reuse its result moves with it.
    service.documents.edit(document(graph_of(refresh={"in": 1, "keep": 1})))
    service.reset_runner()
    refreshed = await service.start()
    await service.running("keep")

    assert refreshed.status is RunStatus.RUNNING
    assert service.runner.calls == ["keep"]
    service.release("keep")
    await service.running("out")
    finished = await service.complete("out", run_id=refreshed.id)
    assert finished.status is RunStatus.SUCCEEDED
    await service.close()


# --- Two calls of one Graph --------------------------------------------------


async def test_two_calls_of_one_graph_with_one_value_compute_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = FakeSecretRevisionResolver({"api_key": "revision-1"})
    service = harness(
        tmp_path,
        monkeypatch,
        project=document(
            caller_graph("call-a", "call-b", mark="one-value"), child_graph()
        ),
        secrets=secrets,
    )

    run = await service.start()
    await service.started()
    await service.running("in")
    service.release("in")
    await service.running("f")
    service.release("f")
    await service.complete("out", "seen-by-call-a")

    assert service.runner.calls == ["in", "f", "out", "seen-by-call-a"]
    # One node, one secret revision and one value reached by two call paths is one
    # computation, whose single result serves both instances.
    # Both call paths read the same secret under one identity, and that is the only
    # identity this document declares: a second call path adds no second reading.
    assert {(call[0], call[1], call[2], call[3]) for call in secrets.calls} == {
        (str(PROJECT_ID), "child", "f", "api_key")
    }
    states = await service.states()
    callees = [
        snapshot
        for snapshot in states
        if snapshot.key.node_id == "f" and snapshot.key.call_path
    ]
    assert {snapshot.key.call_path for snapshot in callees} == {
        ("call-a",),
        ("call-b",),
    }
    assert {snapshot.state for snapshot in callees} == {InstanceState.FRESH}
    assert len({snapshot.fingerprint for snapshot in callees}) == 1
    assert run.graph_id == GRAPH
    await service.close()


# --- Restart -----------------------------------------------------------------


async def test_close_leaves_an_unfinished_run_running_for_the_next_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))
    run = await service.start()
    await service.started()
    await service.running("value")

    await service.close()

    # Nobody watched the computation end, so the row says what is true: it was
    # running. Claiming a finish here would be an invention.
    assert run.status is RunStatus.RUNNING
    assert service.runner.cancelled == ["value"]
    assert "run_finished" not in service.events.kinds()
    assert service.events.kinds().count("run_started") == 1


async def test_a_restart_interrupts_the_unfinished_and_keeps_the_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))
    done_before = await service.start(targets=[target("value")])
    await service.started()
    await service.complete("value")
    abandoned = run_row()
    service.rows.insert(abandoned)
    await service.close()

    restart = service.restart()
    interrupted = await restart.service.recover_after_restart()

    assert [run.id for run in interrupted] == [abandoned.id]
    assert interrupted[0].status is RunStatus.INTERRUPTED
    assert interrupted[0].error
    stored = await restart.service.get_run(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        run_id=abandoned.id,
    )
    assert stored.status is RunStatus.INTERRUPTED
    # What the previous owner stored survived it, so its work is still fresh and a
    # Run started here resumes from that frontier instead of repeating it.
    assert service.state_of(await restart.states(), "value") is InstanceState.FRESH
    resumed = await restart.start(targets=[target("value")])
    assert resumed.status is RunStatus.SUCCEEDED
    assert restart.runner.calls == []
    assert done_before.status is RunStatus.SUCCEEDED
    await restart.close()


async def test_recovery_leaves_finished_runs_and_their_records_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))
    await service.start()
    await service.started()
    await service.complete("value", "sink")

    restart = service.restart()
    assert await restart.service.recover_after_restart() == []
    runs = await restart.service.list_runs(
        workspace_id=WORKSPACE_ID, project_id=PROJECT_ID
    )

    assert [run.status for run in runs] == [RunStatus.SUCCEEDED]
    assert service.state_of(await restart.states(), "sink") is InstanceState.FRESH
    await restart.close()


# --- Reading Runs ------------------------------------------------------------


async def test_list_runs_narrows_to_the_active_ones_and_respects_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))
    first = await service.start(targets=[target("value")])
    await service.started()
    second = await service.start(targets=[target("sink")])
    await service.started()

    everything = await service.service.list_runs(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
    )
    active = await service.service.list_runs(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        active_only=True,
    )
    one = await service.service.list_runs(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        limit=1,
    )

    assert {run.id for run in everything} == {first.id, second.id}
    assert {run.id for run in active} == {first.id, second.id}
    assert len(one) == 1
    assert one[0].id in {first.id, second.id}
    await service.complete("value", run_id=first.id)
    await service.complete("sink", run_id=second.id)
    assert (
        await service.service.list_runs(
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            active_only=True,
        )
        == []
    )
    await service.close()


def test_the_concurrency_budget_must_be_at_least_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)

    for concurrency in (0, -1):
        with pytest.raises(ValueError, match="concurrency"):
            RunService(
                documents=FakeProjectDocumentSource(document(main_graph())),
                uow_factory=FakeUnitOfWorkFactory(),
                result_store_factory=FakeResultStoreFactory(),
                facts=facts_factory(catalog),
                runners=FakeComputationRunnerFactory(FakeRunner()),
                events=FakeRunEvents(),
                concurrency=concurrency,
            )


async def test_a_project_that_was_never_run_reads_as_stale_without_a_scheduler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(tmp_path, monkeypatch, project=document(main_graph()))

    states = await service.states()

    assert node_ids(states) == {"value", "sink"}
    assert {snapshot.state for snapshot in states} == {InstanceState.STALE}
    assert service.builder.built == []
    assert service.events.recorded == []
    await service.close()


# --- Helpers -----------------------------------------------------------------


def _fingerprint_of(service: RunServiceHarness, node_id: str) -> str:
    """The fingerprint the last computation of ``node_id`` was run for."""
    for request in reversed(service.runner.requests):
        if request.instance.key.node_id == node_id:
            return request.fingerprint
    raise AssertionError(f"no computation for node {node_id!r} was run")


async def test_concurrent_cancels_finish_and_announce_the_run_once(
    tmp_path, monkeypatch
):
    import asyncio

    service = harness(tmp_path, monkeypatch, project=document(main_graph()))
    run = await service.start()
    await service.running("value")
    saving = asyncio.Event()
    second_read = asyncio.Event()
    release_save = asyncio.Event()
    original_save = service.rows.save
    original_get = service.rows.get

    async def blocked_save(row):
        saving.set()
        await release_save.wait()
        await original_save(row)

    async def observed_get(*arguments):
        if saving.is_set():
            second_read.set()
        return await original_get(*arguments)

    monkeypatch.setattr(service.rows, "save", blocked_save)
    monkeypatch.setattr(service.rows, "get", observed_get)
    first = asyncio.create_task(
        service.service.cancel(
            workspace_id=WORKSPACE_ID, project_id=PROJECT_ID, run_id=run.id
        )
    )
    await saving.wait()
    second = asyncio.create_task(
        service.service.cancel(
            workspace_id=WORKSPACE_ID, project_id=PROJECT_ID, run_id=run.id
        )
    )
    await second_read.wait()
    release_save.set()
    replies = await asyncio.gather(first, second)
    assert [reply.status for reply in replies] == [
        RunStatus.CANCELLED,
        RunStatus.CANCELLED,
    ]
    assert service.rows.saved == [run.id]
    assert service.events.kinds().count("run_finished") == 1
    await service.close()


async def test_room_cancellation_does_not_cancel_queued_derivation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness(
        tmp_path, monkeypatch, project=document(main_graph()), concurrency=1
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    cancelled = asyncio.Event()

    async def derive(_runtime):
        entered.set()
        try:
            await release.wait()
            finished.set()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(service.service, "_publish", derive)

    async def room():
        await service.service.project_changed(
            workspace_id=WORKSPACE_ID, project_id=PROJECT_ID, wait=False
        )
        await asyncio.Event().wait()

    caller = asyncio.create_task(room())
    try:
        await entered.wait()
        caller.cancel()
        await asyncio.gather(caller, return_exceptions=True)
        assert not cancelled.is_set()
        release.set()
        await finished.wait()
    finally:
        release.set()
        caller.cancel()
        await asyncio.gather(caller, return_exceptions=True)
        await service.close()

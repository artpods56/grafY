"""Ready-set scheduler behaviour under a fake runner that only moves on events.

Every wait here is an ``asyncio.Event`` wait: a computation starts when its
record is dispatched and stops holding still when the test sets its release
event, so the tests below say exactly which moment of a Run they observe and
never give a racing scheduler a head start with a sleep. The only timers are
the hang guards in the ``_started``, ``_wait_run`` and ``_cancel`` helpers,
which turn a scheduler that stops dispatching into a failed test.
"""

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from uuid import UUID

import pytest

from grafy_core.artifacts import ArtifactRef
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.kernel.fingerprints import compute_fingerprints
from grafy_core.kernel.instances import ExpandedInstance, InstanceKey
from grafy_core.kernel.lifecycle import ComputationState
from grafy_core.kernel.memory_results import InMemoryResultStore
from grafy_core.kernel.scheduler import (
    ComputationPlan,
    ComputationRequest,
    RunPlan,
    RunResult,
    Scheduler,
    build_scheduler,
)
from grafy_core.kernel.state import InstanceState, derive_instance_state
from tests.unit.kernel.builders import (
    DEFAULT_GRAPH_ID,
    DEFAULT_PROJECT_ID,
    FakeFacts,
    expand_document,
    make_edge,
    make_key,
    make_node,
)

#: Turns a scheduler that stops dispatching into a failed test, never a wedged one.
HANG_GUARD_SECONDS = 10


def _key(node_id: str) -> InstanceKey:
    return make_key(node_id, project_id=DEFAULT_PROJECT_ID, graph_id=DEFAULT_GRAPH_ID)


def _instance(node_id: str) -> ExpandedInstance:
    return ExpandedInstance(
        key=_key(node_id),
        node=make_node(node_id),
        connections=(),
        origins=(),
    )


def _outputs(mark: str) -> dict[str, ArtifactOutputValue]:
    return {
        "value": ArtifactRef(
            artifact_id=UUID("00000000-0000-0000-0000-000000000901"),
            artifact_type="scalar.integer",
            schema_version=1,
            content_hash=mark * 64,
        )
    }


def _content_hash(
    outputs: Mapping[str, ArtifactOutputValue],
    port: str = "value",
) -> str | None:
    value = outputs[port]
    assert isinstance(value, ArtifactRef)
    return value.content_hash


def plan_from(
    dependencies: Mapping[str, Sequence[str]],
    *,
    instances: Mapping[str, Sequence[InstanceKey]] | None = None,
    representatives: Mapping[str, ExpandedInstance] | None = None,
) -> RunPlan:
    """Build a ``RunPlan`` from ``{fingerprint: upstream fingerprints}``.

    Fingerprints are short names here; a computation's instances default to one
    named after its fingerprint, so ``depends_on`` and ``upstream_fingerprints``
    stay consistent without a document behind them.
    """
    owned = instances or {}
    chosen = representatives or {}
    computations: dict[str, ComputationPlan] = {}
    for fingerprint, depends_on in dependencies.items():
        keys = tuple(owned.get(fingerprint, (_key(fingerprint),)))
        computations[fingerprint] = ComputationPlan(
            fingerprint=fingerprint,
            representative=chosen.get(fingerprint, _instance(keys[0].node_id)),
            instances=keys,
            depends_on=frozenset(depends_on),
            upstream_fingerprints={
                owned.get(dependency, (_key(dependency),))[0]: dependency
                for dependency in depends_on
            },
        )
    targets: list[InstanceKey] = []
    for computation in computations.values():
        targets.extend(key for key in computation.instances if key not in targets)
    return RunPlan(targets=tuple(targets), computations=computations)


class FakeRunner:
    """``ComputationRunner`` stand-in: each call starts, then waits to be released.

    Attempt number two of one fingerprint gets its own pair of events, so a
    retried computation is observable separately from the attempt that failed.
    """

    def __init__(self, *, failing: Iterable[str] = ()) -> None:
        self.failing: set[str] = set(failing)
        self.calls: list[str] = []
        self.requests: list[ComputationRequest] = []
        self.cancelled: list[str] = []
        self._started: dict[tuple[str, int], asyncio.Event] = {}
        self._release: dict[tuple[str, int], asyncio.Event] = {}

    def started(self, fingerprint: str, attempt: int = 0) -> asyncio.Event:
        return self._started.setdefault((fingerprint, attempt), asyncio.Event())

    def release(self, fingerprint: str, attempt: int = 0) -> asyncio.Event:
        return self._release.setdefault((fingerprint, attempt), asyncio.Event())

    def is_started(self, fingerprint: str, attempt: int = 0) -> bool:
        return self.started(fingerprint, attempt).is_set()

    async def __call__(
        self,
        request: ComputationRequest,
    ) -> Mapping[str, ArtifactOutputValue]:
        fingerprint = request.fingerprint
        attempt = self.calls.count(fingerprint)
        self.calls.append(fingerprint)
        self.requests.append(request)
        self.started(fingerprint, attempt).set()
        try:
            await self.release(fingerprint, attempt).wait()
        except asyncio.CancelledError:
            self.cancelled.append(fingerprint)
            raise
        if fingerprint in self.failing:
            raise RuntimeError(f"{fingerprint} could not compute")
        return _outputs(fingerprint)


async def _await_event(event: asyncio.Event) -> None:
    async with asyncio.timeout(HANG_GUARD_SECONDS):
        await event.wait()


async def _started(runner: FakeRunner, fingerprint: str, attempt: int = 0) -> None:
    await _await_event(runner.started(fingerprint, attempt))


async def _wait_run(scheduler: Scheduler, run_id: str) -> RunResult:
    async with asyncio.timeout(HANG_GUARD_SECONDS):
        return await scheduler.wait(run_id)


async def _cancel(scheduler: Scheduler, run_id: str) -> None:
    """Withdrawing a Run ends once its runners observed the cancellation."""
    async with asyncio.timeout(HANG_GUARD_SECONDS):
        await scheduler.cancel(run_id)


# 1. Independent branches and the concurrency budget.


async def test_independent_branches_of_one_plan_run_concurrently() -> None:
    runner = FakeRunner()
    scheduler = build_scheduler(
        store=InMemoryResultStore(), runner=runner, concurrency=2
    )

    await scheduler.submit("run-1", plan_from({"A": [], "B": []}))

    await _started(runner, "A")
    await _started(runner, "B")
    # Both are holding still, so neither has been able to finish first.
    assert runner.calls == ["A", "B"]
    assert scheduler.in_flight("A") == "running"
    assert scheduler.in_flight("B") == "running"

    runner.release("A").set()
    runner.release("B").set()
    result = await _wait_run(scheduler, "run-1")

    assert result.status == "succeeded"
    assert dict(result.computations) == {
        "A": ComputationState.SUCCEEDED,
        "B": ComputationState.SUCCEEDED,
    }


async def test_a_budget_of_one_keeps_the_second_branch_queued() -> None:
    runner = FakeRunner()
    scheduler = build_scheduler(
        store=InMemoryResultStore(), runner=runner, concurrency=1
    )

    await scheduler.submit("run-1", plan_from({"A": [], "B": []}))

    await _started(runner, "A")
    assert scheduler.in_flight("B") == "queued"
    assert not runner.is_started("B")

    runner.release("A").set()
    await _started(runner, "B")
    assert scheduler.in_flight("A") is None
    assert scheduler.in_flight("B") == "running"

    runner.release("B").set()
    result = await _wait_run(scheduler, "run-1")

    assert runner.calls == ["A", "B"]
    assert result.status == "succeeded"


# 2. A diamond joins.


async def test_a_diamond_runs_its_join_only_after_both_branches() -> None:
    runner = FakeRunner()
    scheduler = build_scheduler(
        store=InMemoryResultStore(), runner=runner, concurrency=2
    )

    await scheduler.submit(
        "run-1",
        plan_from({"A": [], "B": ["A"], "C": ["A"], "D": ["B", "C"]}),
    )

    await _started(runner, "A")
    assert runner.calls == ["A"]
    assert scheduler.in_flight("B") == "queued"
    assert scheduler.in_flight("D") == "queued"

    runner.release("A").set()
    await _started(runner, "B")
    await _started(runner, "C")
    assert set(runner.calls) == {"A", "B", "C"}
    assert not runner.is_started("D")
    assert scheduler.in_flight("D") == "queued"

    runner.release("B").set()
    runner.release("C").set()
    await _started(runner, "D")
    assert not runner.is_started("D", 1)

    runner.release("D").set()
    result = await _wait_run(scheduler, "run-1")

    assert runner.calls[0] == "A"
    assert set(runner.calls[1:3]) == {"B", "C"}
    assert runner.calls[3] == "D"
    # The join is asked for by fingerprint, with its representative and upstreams.
    join_request = next(
        request for request in runner.requests if request.fingerprint == "D"
    )
    assert join_request.instance.key == _key("D")
    assert join_request.upstream_fingerprints == {_key("B"): "B", _key("C"): "C"}
    assert result.status == "succeeded"
    assert dict(result.computations) == {
        "A": ComputationState.SUCCEEDED,
        "B": ComputationState.SUCCEEDED,
        "C": ComputationState.SUCCEEDED,
        "D": ComputationState.SUCCEEDED,
    }


# 3. Failure and skip propagation.


async def test_a_failure_skips_every_dependent_and_fails_the_run() -> None:
    store = InMemoryResultStore()
    runner = FakeRunner(failing=["A"])
    scheduler = build_scheduler(store=store, runner=runner, concurrency=2)

    await scheduler.submit(
        "run-1",
        plan_from({"A": [], "B": ["A"], "C": ["A"], "D": ["B", "C"], "E": []}),
    )

    await _started(runner, "A")
    await _started(runner, "E")
    runner.release("A").set()
    runner.release("E").set()
    result = await _wait_run(scheduler, "run-1")

    assert runner.calls == ["A", "E"]
    assert result.status == "failed"
    assert dict(result.computations) == {
        "A": ComputationState.FAILED,
        "B": ComputationState.SKIPPED,
        "C": ComputationState.SKIPPED,
        "D": ComputationState.SKIPPED,
        "E": ComputationState.SUCCEEDED,
    }
    assert dict(result.failures) == {"A": "A could not compute"}

    failed_pointer = await store.get_pointer(_key("A"))
    assert failed_pointer is not None
    assert failed_pointer.last_result_fingerprint is None
    assert failed_pointer.last_failure is not None
    assert failed_pointer.last_failure.fingerprint == "A"
    assert failed_pointer.last_failure.message == "A could not compute"
    # A failure is never a result: nothing is stored under any of these.
    for fingerprint in ("A", "B", "C", "D"):
        assert await store.get_result(fingerprint) is None
    assert await store.get_result("E") is not None
    for fingerprint in ("B", "C", "D"):
        assert await store.get_pointer(_key(fingerprint)) is None


# 4. Two Runs sharing one computation.


async def test_two_runs_share_one_computation_and_the_runner_runs_once() -> None:
    runner = FakeRunner()
    scheduler = build_scheduler(
        store=InMemoryResultStore(), runner=runner, concurrency=2
    )

    await scheduler.submit("run-1", plan_from({"X": [], "Y": ["X"]}))
    await _started(runner, "X")
    await scheduler.submit("run-2", plan_from({"X": []}))

    # The second Run joined the attempt already running instead of starting its own.
    assert scheduler.in_flight("X") == "running"
    assert not runner.is_started("X", 1)

    runner.release("X").set()
    await _started(runner, "Y")
    assert runner.calls.count("X") == 1
    runner.release("Y").set()

    first = await _wait_run(scheduler, "run-1")
    second = await _wait_run(scheduler, "run-2")

    assert runner.calls.count("X") == 1
    assert first.status == "succeeded"
    assert dict(first.computations) == {
        "X": ComputationState.SUCCEEDED,
        "Y": ComputationState.SUCCEEDED,
    }
    assert second.status == "succeeded"
    assert dict(second.computations) == {"X": ComputationState.SUCCEEDED}


# 5. Cancellation is ref-counted by demand.


async def test_cancelling_one_run_leaves_another_runs_demand_alone() -> None:
    store = InMemoryResultStore()
    runner = FakeRunner()
    scheduler = build_scheduler(store=store, runner=runner, concurrency=2)

    await scheduler.submit("run-1", plan_from({"X": [], "Y": []}))
    await _started(runner, "X")
    await scheduler.submit("run-2", plan_from({"X": []}))
    await _started(runner, "Y")

    await _cancel(scheduler, "run-1")

    # X is still what Run 2 asked for, so it keeps running; Y was only Run 1's.
    assert scheduler.in_flight("X") == "running"
    assert scheduler.in_flight("Y") is None
    assert runner.cancelled == ["Y"]
    assert "X" not in runner.cancelled

    runner.release("X").set()
    first = await _wait_run(scheduler, "run-1")
    second = await _wait_run(scheduler, "run-2")

    assert runner.calls.count("X") == 1
    assert first.status == "cancelled"
    assert dict(first.computations) == {
        "X": ComputationState.SUCCEEDED,
        "Y": ComputationState.CANCELLED,
    }
    assert second.status == "succeeded"
    assert dict(second.computations) == {"X": ComputationState.SUCCEEDED}
    pointer = await store.get_pointer(_key("X"))
    assert pointer is not None
    assert pointer.last_result_fingerprint == "X"


# 6. Withdrawing the only demand cancels and frees the budget.


async def test_cancelling_the_only_demander_cancels_its_work_and_frees_the_budget() -> (
    None
):
    runner = FakeRunner()
    scheduler = build_scheduler(
        store=InMemoryResultStore(), runner=runner, concurrency=1
    )

    await scheduler.submit("run-1", plan_from({"X": [], "Y": ["X"]}))
    await _started(runner, "X")
    await scheduler.submit("run-2", plan_from({"Z": []}))
    assert scheduler.in_flight("Z") == "queued"
    assert not runner.is_started("Z")

    await _cancel(scheduler, "run-1")

    assert runner.cancelled == ["X"]
    assert scheduler.in_flight("Y") is None
    # The withdrawn Run handed its one slot to the Run still waiting.
    await _started(runner, "Z")

    runner.release("Z").set()
    first = await _wait_run(scheduler, "run-1")
    second = await _wait_run(scheduler, "run-2")

    assert first.status == "cancelled"
    assert dict(first.computations) == {
        "X": ComputationState.CANCELLED,
        "Y": ComputationState.CANCELLED,
    }
    assert second.status == "succeeded"
    assert dict(second.computations) == {"Z": ComputationState.SUCCEEDED}


# 7. An edit while a computation runs.


def _fingerprints(value: int) -> dict[InstanceKey, str]:
    """Fingerprint a two-node document whose root carries ``value``.

    The second node reads the first, so changing the root's configuration moves
    the root fingerprint as well as everything downstream of it.
    """
    return compute_fingerprints(
        expand_document(
            [make_node("n1", config={"value": value}), make_node("n2")],
            [make_edge("e1", "n1", "n2")],
        ),
        FakeFacts(),
    )


async def test_an_edit_during_a_computation_leaves_the_instance_stale() -> None:
    store = InMemoryResultStore()
    runner = FakeRunner()
    scheduler = build_scheduler(store=store, runner=runner, concurrency=1)

    before = _fingerprints(value=1)
    after = _fingerprints(value=2)
    first_key, second_key = _key("n1"), _key("n2")
    first_fingerprint = before[first_key]
    second_fingerprint = before[second_key]
    edited_fingerprint = after[first_key]
    assert edited_fingerprint != first_fingerprint

    await scheduler.submit(
        "run-1",
        plan_from(
            {first_fingerprint: [], second_fingerprint: [first_fingerprint]},
            instances={
                first_fingerprint: [first_key],
                second_fingerprint: [second_key],
            },
            representatives={
                first_fingerprint: _instance("n1"),
                second_fingerprint: _instance("n2"),
            },
        ),
    )

    await _started(runner, first_fingerprint)

    running = await derive_instance_state(
        instance=first_key,
        fingerprint=first_fingerprint,
        store=store,
        in_flight=scheduler,
    )
    queued = await derive_instance_state(
        instance=second_key,
        fingerprint=second_fingerprint,
        store=store,
        in_flight=scheduler,
    )
    assert running is InstanceState.RUNNING
    assert queued is InstanceState.QUEUED

    # The document moves on while the root is still out computing.
    runner.release(first_fingerprint).set()
    await _started(runner, second_fingerprint)
    runner.release(second_fingerprint).set()
    result = await _wait_run(scheduler, "run-1")

    assert result.status == "succeeded"
    # The result stays filed under the fingerprint the run started with...
    pointer = await store.get_pointer(first_key)
    assert pointer is not None
    assert pointer.last_result_fingerprint == first_fingerprint
    # ...so the current document reads as stale while the old one reads fresh.
    fresh = await derive_instance_state(
        instance=first_key,
        fingerprint=first_fingerprint,
        store=store,
        in_flight=scheduler,
    )
    stale = await derive_instance_state(
        instance=first_key,
        fingerprint=edited_fingerprint,
        store=store,
        in_flight=scheduler,
    )
    assert fresh is InstanceState.FRESH
    assert stale is InstanceState.STALE


# 8. A rerun retries.


async def test_a_failed_computation_is_retried_by_a_new_run() -> None:
    store = InMemoryResultStore()
    runner = FakeRunner(failing=["A"])
    scheduler = build_scheduler(store=store, runner=runner, concurrency=1)

    await scheduler.submit("run-1", plan_from({"A": []}))
    await _started(runner, "A")
    runner.release("A").set()
    first = await _wait_run(scheduler, "run-1")
    assert first.status == "failed"
    assert dict(first.computations) == {"A": ComputationState.FAILED}

    runner.failing.discard("A")
    # The retry needs no holding: this test is about it being attempted again.
    runner.release("A", 1).set()
    await scheduler.submit("run-2", plan_from({"A": []}))

    await _started(runner, "A", 1)
    second = await _wait_run(scheduler, "run-2")

    assert runner.calls == ["A", "A"]
    assert second.status == "succeeded"
    assert dict(second.computations) == {"A": ComputationState.SUCCEEDED}
    # The retried Run's answer does not rewrite the Run that failed.
    again = await _wait_run(scheduler, "run-1")
    assert again.status == "failed"
    assert dict(again.computations) == {"A": ComputationState.FAILED}
    assert dict(again.failures) == {"A": "A could not compute"}
    pointer = await store.get_pointer(_key("A"))
    assert pointer is not None
    assert pointer.last_result_fingerprint == "A"
    assert pointer.last_failure is None


async def test_a_new_run_replaces_a_failed_attempt_another_run_still_holds() -> None:
    """A terminal attempt is not what a later Run is asking for.

    Run 1 holds its failed record open while its other computation is still out,
    so Run 2 must start a fresh attempt rather than join the failure it can see.
    """
    store = InMemoryResultStore()
    runner = FakeRunner(failing=["A"])
    scheduler = build_scheduler(store=store, runner=runner, concurrency=2)

    # Run 1 asks for three roots with two slots, so C can only start once A is
    # over: seeing C start is how this test knows the failure has been recorded.
    await scheduler.submit("run-1", plan_from({"A": [], "B": [], "C": []}))
    await _started(runner, "A")
    await _started(runner, "B")
    runner.release("A").set()
    await _started(runner, "C")
    assert scheduler.in_flight("B") == "running"

    runner.failing.discard("A")
    runner.release("A", 1).set()
    await scheduler.submit("run-2", plan_from({"A": []}))

    # Run 2 does not join the failure Run 1 still holds: it queues a fresh attempt.
    assert scheduler.in_flight("A") == "queued"
    assert not runner.is_started("A", 1)

    # A slot opens when C finishes.
    runner.release("C").set()
    await _started(runner, "A", 1)
    assert runner.calls.count("A") == 2

    runner.release("B").set()
    first = await _wait_run(scheduler, "run-1")
    second = await _wait_run(scheduler, "run-2")

    assert first.status == "failed"
    assert dict(first.computations) == {
        "A": ComputationState.FAILED,
        "B": ComputationState.SUCCEEDED,
        "C": ComputationState.SUCCEEDED,
    }
    assert second.status == "succeeded"
    assert dict(second.computations) == {"A": ComputationState.SUCCEEDED}
    pointer = await store.get_pointer(_key("A"))
    assert pointer is not None
    assert pointer.last_result_fingerprint == "A"


# 9. A stored fingerprint is already what the Run asked for.


async def test_a_stored_fingerprint_is_reported_succeeded_and_never_runs() -> None:
    store = InMemoryResultStore()
    await store.put_result("S", _outputs("ss"))
    runner = FakeRunner()
    scheduler = build_scheduler(store=store, runner=runner, concurrency=2)

    await scheduler.submit("run-1", plan_from({"S": [], "T": ["S"]}))

    await _started(runner, "T")
    runner.release("T").set()
    result = await _wait_run(scheduler, "run-1")

    assert runner.calls == ["T"]
    assert scheduler.in_flight("S") is None
    assert result.status == "succeeded"
    assert dict(result.computations) == {
        "S": ComputationState.SUCCEEDED,
        "T": ComputationState.SUCCEEDED,
    }
    stored = await store.get_result("S")
    assert stored is not None
    # Still the value put there before the Run, so nothing recomputed it.
    assert _content_hash(stored.outputs) == "ss" * 64


# 10. Two instances of one fingerprint share the attempt.


async def test_two_instances_of_one_fingerprint_both_point_at_the_result() -> None:
    store = InMemoryResultStore()
    runner = FakeRunner()
    scheduler = build_scheduler(store=store, runner=runner, concurrency=1)
    caller = _key("call-a")
    callee = _key("call-b")

    await scheduler.submit(
        "run-1",
        plan_from({"F": []}, instances={"F": [caller, callee]}),
    )

    await _started(runner, "F")
    runner.release("F").set()
    result = await _wait_run(scheduler, "run-1")

    assert runner.calls == ["F"]
    assert result.status == "succeeded"
    for instance in (caller, callee):
        pointer = await store.get_pointer(instance)
        assert pointer is not None
        assert pointer.last_result_fingerprint == "F"


# 11. What a scheduler refuses.


async def test_a_duplicate_run_id_is_rejected() -> None:
    runner = FakeRunner()
    scheduler = build_scheduler(
        store=InMemoryResultStore(), runner=runner, concurrency=1
    )
    await scheduler.submit("run-1", plan_from({"A": []}))
    await _started(runner, "A")

    with pytest.raises(ValueError, match="run-1"):
        await scheduler.submit("run-1", plan_from({"B": []}))

    assert scheduler.in_flight("B") is None
    runner.release("A").set()
    assert (await _wait_run(scheduler, "run-1")).status == "succeeded"


async def test_a_plan_must_be_closed_under_its_dependencies() -> None:
    runner = FakeRunner()
    scheduler = build_scheduler(
        store=InMemoryResultStore(), runner=runner, concurrency=1
    )

    with pytest.raises(ValueError, match="closed under its dependencies"):
        await scheduler.submit("run-1", plan_from({"B": ["MISSING"]}))

    assert scheduler.in_flight("B") is None
    with pytest.raises(KeyError):
        await _wait_run(scheduler, "run-1")
    assert runner.calls == []


@pytest.mark.parametrize("concurrency", [0, -1])
async def test_the_concurrency_budget_must_be_at_least_one(concurrency: int) -> None:
    runner = FakeRunner()
    with pytest.raises(ValueError, match="concurrency"):
        build_scheduler(
            store=InMemoryResultStore(),
            runner=runner,
            concurrency=concurrency,
        )


async def test_waiting_for_an_unknown_run_raises() -> None:
    scheduler = build_scheduler(
        store=InMemoryResultStore(),
        runner=FakeRunner(),
        concurrency=1,
    )

    with pytest.raises(KeyError):
        await scheduler.wait("nobody-here")


async def test_cancelling_an_unknown_run_is_a_no_op() -> None:
    scheduler = build_scheduler(
        store=InMemoryResultStore(),
        runner=FakeRunner(),
        concurrency=1,
    )

    assert await scheduler.cancel("nobody-here") is None


# 12. Withdrawing a Run that is already over.


async def test_cancelling_a_finished_run_keeps_its_result() -> None:
    runner = FakeRunner()
    scheduler = build_scheduler(
        store=InMemoryResultStore(), runner=runner, concurrency=1
    )
    await scheduler.submit("run-1", plan_from({"A": []}))
    await _started(runner, "A")
    runner.release("A").set()
    finished = await _wait_run(scheduler, "run-1")

    await _cancel(scheduler, "run-1")
    after = await _wait_run(scheduler, "run-1")

    assert finished.status == "succeeded"
    assert after == finished
    assert runner.cancelled == []

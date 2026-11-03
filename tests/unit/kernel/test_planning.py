"""Run planning: the stale part of the upstream closure of the targets.

Every freshness here comes from a real ``InMemoryResultStore``: an instance is
fresh exactly when ``put_result`` has stored its current fingerprint, exactly
as the scheduler will leave it after a successful computation. The
integration tests drive the real scheduler with a runner that returns its
outputs immediately, so no test here sleeps: the runner resolves under
default asyncio scheduling and ``scheduler.wait`` answers when the last
computation reaches a terminal state.
"""

import asyncio
from collections.abc import Mapping, Sequence
from uuid import UUID

import pytest

from grafy_core.artifacts import ArtifactRef
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.kernel.fingerprints import compute_fingerprints
from grafy_core.kernel.instances import ExpandedGraph, InstanceKey
from grafy_core.kernel.memory_results import InMemoryResultStore
from grafy_core.kernel.planning import plan_run
from grafy_core.kernel.scheduler import (
    ComputationRequest,
    RunPlan,
    RunResult,
    Scheduler,
    build_scheduler,
)
from grafy_core.domain.saved_graphs import GraphNode
from tests.unit.kernel.builders import (
    ExpandedGraphBuilder,
    FakeFacts,
    make_key,
    make_node,
)

#: Turns a scheduler that stops dispatching into a failed test, never a wedged one.
HANG_GUARD_SECONDS = 10


def _outputs(mark: str) -> dict[str, ArtifactOutputValue]:
    return {
        "value": ArtifactRef(
            artifact_id=UUID("00000000-0000-0000-0000-000000000901"),
            artifact_type="scalar.integer",
            schema_version=1,
            content_hash=mark * 64,
        )
    }


def _fingerprints(graph: ExpandedGraph) -> dict[InstanceKey, str]:
    return compute_fingerprints(graph, FakeFacts())


def _value_node(node_id: str, value: int) -> GraphNode:
    # Distinct config per node: unconnected nodes must not share a fingerprint.
    return make_node(node_id, config={"value": value})


def _chain(*, b_value: int = 2) -> tuple[ExpandedGraphBuilder, dict[str, InstanceKey]]:
    """A -> B -> C -> D with a settable config on B."""
    builder = ExpandedGraphBuilder()
    keys = {
        "a": builder.add_instance(_value_node("a", 1)),
        "b": builder.add_instance(_value_node("b", b_value)),
        "c": builder.add_instance(_value_node("c", 3)),
        "d": builder.add_instance(_value_node("d", 4)),
    }
    builder.connect(keys["a"], keys["b"])
    builder.connect(keys["b"], keys["c"])
    builder.connect(keys["c"], keys["d"])
    return builder, keys


def _diamond() -> tuple[ExpandedGraphBuilder, dict[str, InstanceKey]]:
    """A -> (B, C) -> D."""
    builder = ExpandedGraphBuilder()
    keys = {
        name: builder.add_instance(_value_node(name, index))
        for name, index in (("a", 1), ("b", 2), ("c", 3), ("d", 4))
    }
    builder.connect(keys["a"], keys["b"])
    builder.connect(keys["a"], keys["c"])
    builder.connect(keys["b"], keys["d"])
    builder.connect(keys["c"], keys["d"])
    return builder, keys


def _shared_inner() -> tuple[ExpandedGraphBuilder, dict[str, InstanceKey]]:
    """One source feeding the same node content at two call paths."""
    builder = ExpandedGraphBuilder()
    source = builder.add_instance(_value_node("source", 7))
    shared = make_node("inner", operator_id="test.arithmetic.add", config={"left": 0})
    first = builder.add_instance(shared, call_path=("call-a",))
    second = builder.add_instance(shared, call_path=("call-b",))
    builder.connect(source, first)
    builder.connect(source, second)
    return builder, {"source": source, "first": first, "second": second}


async def _plan(
    graph: ExpandedGraph,
    targets: Sequence[InstanceKey],
    store: InMemoryResultStore,
    fingerprints: Mapping[InstanceKey, str] | None = None,
) -> RunPlan:
    return await plan_run(
        graph=graph,
        fingerprints=_fingerprints(graph) if fingerprints is None else fingerprints,
        targets=targets,
        store=store,
    )


# 1. Nothing is fresh: the whole upstream closure is planned.


async def test_a_fresh_graph_plans_the_whole_chain_upstream_of_the_target() -> None:
    builder, keys = _chain()
    graph = builder.build()
    prints = _fingerprints(graph)
    store = InMemoryResultStore()

    plan = await _plan(graph, [keys["d"]], store)

    assert plan.targets == (keys["d"],)
    assert list(plan.computations) == [
        prints[keys["a"]],
        prints[keys["b"]],
        prints[keys["c"]],
        prints[keys["d"]],
    ]
    assert plan.computations[prints[keys["a"]]].depends_on == frozenset()
    assert plan.computations[prints[keys["b"]]].depends_on == frozenset(
        {prints[keys["a"]]}
    )
    assert plan.computations[prints[keys["c"]]].depends_on == frozenset(
        {prints[keys["b"]]}
    )
    assert plan.computations[prints[keys["d"]]].depends_on == frozenset(
        {prints[keys["c"]]}
    )
    for name in ("a", "b", "c", "d"):
        computation = plan.computations[prints[keys[name]]]
        assert computation.instances == (keys[name],)
        assert computation.representative.key == keys[name]


async def test_a_diamond_plans_four_and_the_join_depends_on_both_branches() -> None:
    builder, keys = _diamond()
    graph = builder.build()
    prints = _fingerprints(graph)

    plan = await _plan(graph, [keys["d"]], InMemoryResultStore())

    assert set(plan.computations) == {
        prints[keys[name]] for name in ("a", "b", "c", "d")
    }
    assert plan.computations[prints[keys["d"]]].depends_on == frozenset(
        {prints[keys["b"]], prints[keys["c"]]}
    )


# 2. Freshness cuts the walk.


async def test_a_fresh_root_is_not_planned_and_the_stale_it_up_keeps_no_edge() -> None:
    builder, keys = _diamond()
    graph = builder.build()
    prints = _fingerprints(graph)
    store = InMemoryResultStore()
    await store.put_result(prints[keys["a"]], _outputs("aa"))

    plan = await _plan(graph, [keys["d"]], store)

    assert set(plan.computations) == {prints[keys[name]] for name in ("b", "c", "d")}
    # A is fresh, so it is no computation to wait on...
    assert plan.computations[prints[keys["b"]]].depends_on == frozenset()
    assert plan.computations[prints[keys["c"]]].depends_on == frozenset()
    # ...but the runner is still told which fingerprint B reads.
    assert plan.computations[prints[keys["b"]]].upstream_fingerprints == {
        keys["a"]: prints[keys["a"]]
    }


async def test_a_fresh_instance_in_the_middle_stops_the_walk_from_reaching_above() -> (
    None
):
    builder, keys = _chain()
    graph = builder.build()
    prints = _fingerprints(graph)
    store = InMemoryResultStore()
    # Only B's fingerprint is stored: A never even enters the walk.
    await store.put_result(prints[keys["b"]], _outputs("bb"))

    plan = await _plan(graph, [keys["c"]], store)

    assert list(plan.computations) == [prints[keys["c"]]]
    assert plan.computations[prints[keys["c"]]].depends_on == frozenset()
    assert plan.computations[prints[keys["c"]]].upstream_fingerprints == {
        keys["b"]: prints[keys["b"]]
    }


async def test_a_fresh_target_yields_an_empty_plan() -> None:
    builder, keys = _chain()
    graph = builder.build()
    prints = _fingerprints(graph)
    store = InMemoryResultStore()
    await store.put_result(prints[keys["d"]], _outputs("dd"))

    plan = await _plan(graph, [keys["d"]], store)

    assert plan.computations == {}
    assert plan.targets == (keys["d"],)


async def test_a_branch_upstream_of_no_target_is_never_planned() -> None:
    builder, keys = _chain()
    side = builder.add_instance(_value_node("e", 5))
    side_feeder = builder.add_instance(_value_node("f", 6))
    builder.connect(side_feeder, side)
    graph = builder.build()

    plan = await _plan(graph, [keys["d"]], InMemoryResultStore())

    planned = {
        key
        for computation in plan.computations.values()
        for key in computation.instances
    }
    assert side not in planned
    assert side_feeder not in planned


# 3. One fingerprint, one computation, every instance that shares it.


async def test_depends_on_covers_the_connections_of_every_instance_of_a_computation() -> (
    None
):
    """``depends_on`` is read over all members, not just the representative.

    Real digests make this unreachable - equal fingerprints already carry
    equal upstream fingerprints - so the map below is handcrafted: two members
    share one fingerprint while reading two different stale upstreams. A
    planner that looked only at the representative would miss the second edge.
    """
    builder = ExpandedGraphBuilder()
    left = builder.add_instance(_value_node("left", 1))
    right = builder.add_instance(_value_node("right", 2))
    shared = make_node("inner", operator_id="test.arithmetic.add", config={"left": 0})
    first = builder.add_instance(shared, node_id="inner-one")
    second = builder.add_instance(shared, node_id="inner-two")
    builder.connect(left, first)
    builder.connect(right, second)
    graph = builder.build()

    prints = {left: "L", right: "R", first: "M", second: "M"}

    plan = await _plan(graph, [first, second], InMemoryResultStore(), prints)

    inner = plan.computations["M"]
    assert inner.instances == (first, second)
    assert inner.depends_on == frozenset({"L", "R"})
    # upstream_fingerprints stays the representative's own view.
    assert inner.upstream_fingerprints == {left: "L"}


async def test_two_instances_with_one_content_and_one_upstream_share_a_computation() -> (
    None
):
    builder, keys = _shared_inner()
    graph = builder.build()
    prints = _fingerprints(graph)
    assert prints[keys["first"]] == prints[keys["second"]]

    plan = await _plan(
        graph, [keys["first"], keys["second"]], InMemoryResultStore(), prints
    )

    inner = plan.computations[prints[keys["first"]]]
    assert inner.fingerprint == prints[keys["first"]]
    # Every instance of the graph with this fingerprint, in graph.order order.
    assert inner.instances == (keys["first"], keys["second"])
    assert graph.order.index(inner.instances[0]) < graph.order.index(inner.instances[1])
    assert inner.representative.key == keys["first"]
    assert inner.depends_on == frozenset({prints[keys["source"]]})
    assert list(plan.computations) == [prints[keys["source"]], prints[keys["first"]]]


# 4. What a planner refuses.


async def test_a_target_that_is_not_in_the_graph_is_rejected() -> None:
    builder, _ = _chain()
    graph = builder.build()
    outside = make_key("outside")

    with pytest.raises(ValueError, match="outside"):
        await _plan(graph, [outside], InMemoryResultStore())


async def test_a_target_without_a_fingerprint_is_rejected() -> None:
    builder, keys = _chain()
    graph = builder.build()
    prints = _fingerprints(graph)
    del prints[keys["d"]]

    with pytest.raises(ValueError, match="fingerprint"):
        await _plan(graph, [keys["d"]], InMemoryResultStore(), prints)


async def test_a_reached_instance_without_a_fingerprint_is_rejected() -> None:
    builder, keys = _chain()
    graph = builder.build()
    prints = _fingerprints(graph)
    del prints[keys["b"]]

    with pytest.raises(ValueError, match="b"):
        await _plan(graph, [keys["d"]], InMemoryResultStore(), prints)


# 5. Targets keep their order, without repeats.


async def test_duplicated_targets_are_deduped_keeping_first_occurrence() -> None:
    builder, keys = _diamond()
    graph = builder.build()

    plan = await _plan(
        graph,
        [keys["d"], keys["b"], keys["d"], keys["c"], keys["b"]],
        InMemoryResultStore(),
    )

    assert plan.targets == (keys["d"], keys["b"], keys["c"])


# 6. Integration with the real scheduler.


class RecordingRunner:
    """``ComputationRunner`` that answers at once and records every call.

    Returning immediately is enough to order the work: the scheduler starts a
    computation in a task, and a dependent only becomes ready after the
    dispatch that follows its success, so the call log is topological.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.requests: list[ComputationRequest] = []

    async def __call__(
        self, request: ComputationRequest
    ) -> Mapping[str, ArtifactOutputValue]:
        self.calls.append(request.fingerprint)
        self.requests.append(request)
        return _outputs(request.fingerprint[:8])


async def _wait_run(scheduler: Scheduler, run_id: str) -> RunResult:
    async with asyncio.timeout(HANG_GUARD_SECONDS):
        return await scheduler.wait(run_id)


async def test_a_run_makes_its_plan_empty_the_second_time() -> None:
    builder, keys = _chain()
    graph = builder.build()
    prints = _fingerprints(graph)
    store = InMemoryResultStore()
    runner = RecordingRunner()
    scheduler = build_scheduler(store=store, runner=runner, concurrency=1)

    plan = await _plan(graph, [keys["d"]], store)
    await scheduler.submit("run-1", plan)
    result = await _wait_run(scheduler, "run-1")

    assert result.status == "succeeded"
    assert runner.calls == [
        prints[keys["a"]],
        prints[keys["b"]],
        prints[keys["c"]],
        prints[keys["d"]],
    ]

    again = await _plan(graph, [keys["d"]], store)
    assert again.computations == {}
    assert again.targets == (keys["d"],)


async def test_an_edit_mid_chain_reruns_only_the_change_and_what_reads_it() -> None:
    builder, keys = _chain()
    graph = builder.build()
    store = InMemoryResultStore()
    runner = RecordingRunner()
    scheduler = build_scheduler(store=store, runner=runner, concurrency=1)

    before = _fingerprints(graph)
    await scheduler.submit("run-1", await _plan(graph, [keys["d"]], store, before))
    assert (await _wait_run(scheduler, "run-1")).status == "succeeded"
    assert runner.calls == [before[keys[name]] for name in ("a", "b", "c", "d")]

    # The document moves on: B carries a new config, everything else stays.
    edited_builder, edited = _chain(b_value=22)
    edited_graph = edited_builder.build()
    after = _fingerprints(edited_graph)
    assert after[edited["a"]] == before[keys["a"]]
    assert after[edited["b"]] != before[keys["b"]]

    runner.calls.clear()
    plan = await _plan(edited_graph, [edited["d"]], store, after)
    assert set(plan.computations) == {after[edited[name]] for name in ("b", "c", "d")}

    await scheduler.submit("run-2", plan)
    result = await _wait_run(scheduler, "run-2")

    assert result.status == "succeeded"
    # A is fresh under the new document too: the runner never sees it again.
    assert runner.calls == [after[edited[name]] for name in ("b", "c", "d")]
    assert before[keys["a"]] not in runner.calls


async def test_shared_content_runs_once_and_every_instance_points_at_the_result() -> (
    None
):
    builder, keys = _shared_inner()
    graph = builder.build()
    prints = _fingerprints(graph)
    inner_fingerprint = prints[keys["first"]]
    store = InMemoryResultStore()
    runner = RecordingRunner()
    scheduler = build_scheduler(store=store, runner=runner, concurrency=2)

    plan = await _plan(graph, [keys["first"], keys["second"]], store, prints)
    await scheduler.submit("run-1", plan)
    result = await _wait_run(scheduler, "run-1")

    assert result.status == "succeeded"
    # One computation for two instances: the runner is asked once.
    assert runner.calls.count(inner_fingerprint) == 1
    assert len(runner.calls) == 2  # the shared source, then the shared inner
    for instance in (keys["first"], keys["second"]):
        pointer = await store.get_pointer(instance)
        assert pointer is not None
        assert pointer.last_result_fingerprint == inner_fingerprint

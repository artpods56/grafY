"""Instance expansion of a Project Graph with call nodes inlined (issue #194).

Every Project below is hand-built from the ``SavedGraph*`` value types via the
kernel test builders, so a test moves exactly one thing: one edge, one origin,
one disabled flag, one callee config. The end-to-end cases pin the ADR 0020
claim that two calls of one Graph fed with the same inputs share one
computation: expansion, ``compute_fingerprints``, ``plan_run`` and the
scheduler run for real against ``InMemoryResultStore`` and a fake runner that
logs every call. No I/O, no clocks, no sleeps.
"""

from collections.abc import Mapping, Sequence

import pytest

from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.saved_graphs import (
    SavedGraphDocument,
    SavedGraphEdge,
    SavedGraphNode,
    SavedGraphOrigin,
)
from grafy_core.kernel.expansion import ExpansionError, expand_graph
from grafy_core.kernel.fingerprints import compute_fingerprints
from grafy_core.kernel.instances import ExpandedGraph, InstanceKey
from grafy_core.kernel.memory_results import InMemoryResultStore
from grafy_core.kernel.planning import plan_run
from grafy_core.kernel.project import (
    CALL_NODE_KIND,
    GRAPH_BOUNDARY_PORT,
    GRAPH_INPUT_OPERATOR_ID,
    GRAPH_OUTPUT_OPERATOR_ID,
    GraphDefinition,
    ProjectDocument,
    ProjectDocumentError,
    UnknownGraphError,
)
from grafy_core.kernel.scheduler import ComputationRequest, RunPlan, build_scheduler
from tests.unit.kernel.builders import (
    FakeFacts,
    make_artifact,
    make_edge,
    make_node,
    make_origin,
)

PROJECT = "proj"


def key(
    graph_id: str,
    node_id: str,
    call_path: Sequence[str] = (),
) -> InstanceKey:
    return InstanceKey(PROJECT, graph_id, tuple(call_path), node_id)


def input_node(node_id: str, public_name: str) -> SavedGraphNode:
    return make_node(
        node_id,
        operator_id=GRAPH_INPUT_OPERATOR_ID,
        config={"public_name": public_name},
    )


def output_node(node_id: str, public_name: str) -> SavedGraphNode:
    return make_node(
        node_id,
        operator_id=GRAPH_OUTPUT_OPERATOR_ID,
        config={"public_name": public_name},
    )


def call_node(node_id: str, callee: str) -> SavedGraphNode:
    return make_node(node_id, kind=CALL_NODE_KIND, operator_id=callee)


def graph(
    graph_id: str,
    nodes: Sequence[SavedGraphNode],
    edges: Sequence[SavedGraphEdge] = (),
    origins: Sequence[SavedGraphOrigin] = (),
    refresh: Mapping[str, int] | None = None,
) -> GraphDefinition:
    return GraphDefinition(
        id=graph_id,
        name=f"Graph {graph_id}",
        document=SavedGraphDocument(
            nodes=tuple(nodes),
            edges=tuple(edges),
            origins=tuple(origins),
        ),
        refresh_generations=dict(refresh or {}),
    )


def double_graph(
    *,
    f_config: Mapping[str, object] | None = None,
    f_position: tuple[float, float] = (0.0, 0.0),
    default_origin: bool = False,
    refresh: Mapping[str, int] | None = None,
) -> GraphDefinition:
    """The reusable callee: input ``x`` -> node ``f`` -> output ``r``."""
    return graph(
        "double",
        [
            input_node("gin", "x"),
            make_node(
                "f",
                operator_id="dbl.f",
                config={"mult": 2} if f_config is None else dict(f_config),
                position=f_position,
            ),
            output_node("gout", "r"),
        ],
        [make_edge("e-in", "gin", "f"), make_edge("e-out", "f", "gout")],
        [make_origin("od", "gin")] if default_origin else (),
        refresh,
    )


def expand_double_first(
    main: GraphDefinition,
    *extra_graphs: GraphDefinition,
    target: str = "main",
) -> ExpandedGraph:
    project = ProjectDocument(graphs=(main, double_graph(), *extra_graphs))
    return expand_graph(project, target, project_id=PROJECT)


# 1. A plain Graph without calls expands to the document itself.


def test_plain_graph_matches_the_document() -> None:
    origin = make_origin("o1", "t", to_port="base")
    edge = make_edge("e1", "s", "t")
    main = graph("main", [make_node("s"), make_node("t")], [edge], [origin])

    expanded = expand_double_first(main)

    assert expanded.project_id == PROJECT
    assert expanded.graph_id == "main"
    assert set(expanded.instances) == {key("main", "s"), key("main", "t")}
    assert expanded.order == (key("main", "s"), key("main", "t"))
    assert list(expanded.instances) == list(expanded.order)
    target = expanded.instances[key("main", "t")]
    assert [(c.source, c.edge) for c in target.connections] == [
        (key("main", "s"), edge)
    ]
    assert target.origins == (origin,)
    assert expanded.instances[key("main", "s")].node is main.document.nodes[0]


# 2. One call: callee instances sit one path deeper and both interface edges
#    are rewired onto the boundary instances.


def test_one_call_inlines_the_callee_and_rewires_both_edges() -> None:
    main = graph(
        "main",
        [make_node("s"), call_node("c", "double"), make_node("sink")],
        [
            make_edge("e-in", "s", "c", to_port="x"),
            make_edge("e-out", "c", "sink", from_port="r"),
        ],
    )
    project = ProjectDocument(graphs=(main, double_graph()))

    expanded = expand_graph(project, "main", project_id=PROJECT)

    assert set(expanded.instances) == {
        key("main", "s"),
        key("main", "sink"),
        key("double", "gin", ("c",)),
        key("double", "f", ("c",)),
        key("double", "gout", ("c",)),
    }
    # The call node itself never becomes an instance.
    assert not any(k.node_id == "c" for k in expanded.instances)

    fed_input = expanded.instances[key("double", "gin", ("c",))]
    (incoming,) = fed_input.connections
    assert incoming.source == key("main", "s")
    assert incoming.edge.id == "e-in"
    assert incoming.edge.from_node == "s"
    # The stored edge keeps its written endpoints; only the call-side port is
    # rewritten. ``Connection.source`` is the authoritative upstream.
    assert incoming.edge.to_node == "c"
    assert incoming.edge.to_port == GRAPH_BOUNDARY_PORT
    assert incoming.edge.to_plug is None

    feeds_output = expanded.instances[key("main", "sink")]
    (outgoing,) = feeds_output.connections
    assert outgoing.source == key("double", "gout", ("c",))
    assert outgoing.edge.id == "e-out"
    assert outgoing.edge.from_node == "c"
    assert outgoing.edge.from_port == GRAPH_BOUNDARY_PORT
    assert outgoing.edge.to_node == "sink"

    # The callee's interior keeps its own edges, and the document is untouched.
    interior = expanded.instances[key("double", "f", ("c",))]
    assert [c.source for c in interior.connections] == [key("double", "gin", ("c",))]
    assert main.document.edges[1].from_port == "r"
    assert double_graph().document == double_graph().document


# 3. The same callee called twice gets two call paths and two instance sets.


def test_same_callee_twice_gets_two_call_paths() -> None:
    main = graph(
        "main",
        [make_node("s"), call_node("c1", "double"), call_node("c2", "double")],
        [
            make_edge("e1", "s", "c1", to_port="x"),
            make_edge("e2", "s", "c2", to_port="x"),
        ],
    )

    expanded = expand_double_first(main)

    for call_id in ("c1", "c2"):
        for node_id in ("gin", "f", "gout"):
            assert key("double", node_id, (call_id,)) in expanded.instances
    assert not any(k.node_id in ("c1", "c2") for k in expanded.instances)
    assert key("double", "f", ("c1",)) != key("double", "f", ("c2",))


# 4. Nested calls: A calls B calls C puts C's nodes two paths deep.


def test_nested_calls_extend_the_call_path() -> None:
    a = graph("a", [make_node("top"), call_node("cb", "b")])
    b = graph("b", [make_node("mid"), call_node("cc", "c")])
    c = graph("c", [make_node("z")])

    expanded = expand_graph(ProjectDocument(graphs=(a, b, c)), "a", project_id=PROJECT)

    assert set(expanded.instances) == {
        key("a", "top"),
        key("b", "mid", ("cb",)),
        key("c", "z", ("cb", "cc")),
    }


# 5. A caller origin on a call port lands, rewritten, on the callee boundary.


def test_caller_origin_on_a_call_port_reaches_the_boundary() -> None:
    origin = make_origin("o1", "c", to_port="x")
    main = graph("main", [call_node("c", "double")], [], [origin])

    expanded = expand_double_first(main)

    boundary = expanded.instances[key("double", "gin", ("c",))]
    (placed,) = boundary.origins
    assert placed.id == "o1"
    assert placed.to_node == "gin"
    assert placed.to_port == GRAPH_BOUNDARY_PORT
    assert placed.to_plug is None
    assert placed.value == origin.value


# 6. Caller supply beats the callee default: kept when nothing arrives,
#    dropped when an edge or an origin arrives.


def test_callee_default_origin_is_kept_when_the_caller_supplies_nothing() -> None:
    main = graph("main", [call_node("c", "double")])
    project = ProjectDocument(graphs=(main, double_graph(default_origin=True)))

    expanded = expand_graph(project, "main", project_id=PROJECT)

    boundary = expanded.instances[key("double", "gin", ("c",))]
    (default,) = boundary.origins
    assert default.id == "od"


def test_callee_default_origin_is_dropped_when_the_caller_feeds_an_edge() -> None:
    main = graph(
        "main",
        [make_node("s"), call_node("c", "double")],
        [make_edge("e1", "s", "c", to_port="x")],
    )
    project = ProjectDocument(graphs=(main, double_graph(default_origin=True)))

    expanded = expand_graph(project, "main", project_id=PROJECT)

    boundary = expanded.instances[key("double", "gin", ("c",))]
    assert boundary.origins == ()
    assert [c.source for c in boundary.connections] == [key("main", "s")]


def test_callee_default_origin_is_replaced_by_a_caller_origin() -> None:
    origin = make_origin("o1", "c", to_port="x")
    main = graph("main", [call_node("c", "double")], [], [origin])
    project = ProjectDocument(graphs=(main, double_graph(default_origin=True)))

    expanded = expand_graph(project, "main", project_id=PROJECT)

    boundary = expanded.instances[key("double", "gin", ("c",))]
    assert [placed.id for placed in boundary.origins] == ["o1"]


# 7. A disabled edge neither connects a boundary nor supplies its port.


def test_disabled_edge_is_dropped_and_does_not_supply_the_port() -> None:
    main = graph(
        "main",
        [make_node("s"), call_node("c", "double")],
        [make_edge("e1", "s", "c", to_port="x", enabled=False)],
    )
    project = ProjectDocument(graphs=(main, double_graph(default_origin=True)))

    expanded = expand_graph(project, "main", project_id=PROJECT)

    boundary = expanded.instances[key("double", "gin", ("c",))]
    assert boundary.connections == ()
    assert [default.id for default in boundary.origins] == ["od"]


# 8. Connections a call interface cannot satisfy are skipped, not raised.


def test_edges_onto_unknown_call_ports_are_skipped() -> None:
    main = graph(
        "main",
        [make_node("s"), call_node("c", "double"), make_node("sink")],
        [
            make_edge("e-bad-in", "s", "c", to_port="nope"),
            make_edge("e-bad-out", "c", "sink", from_port="nope"),
        ],
    )

    expanded = expand_double_first(main)

    assert expanded.instances[key("double", "gin", ("c",))].connections == ()
    assert expanded.instances[key("main", "sink")].connections == ()


# 9. Refresh generations follow the Graph each node lives in.


def test_refresh_generations_propagate_per_graph() -> None:
    main = graph(
        "main",
        [make_node("f"), call_node("c", "double")],
        refresh={"f": 5},
    )
    project = ProjectDocument(graphs=(main, double_graph(refresh={"f": 3})))

    expanded = expand_graph(project, "main", project_id=PROJECT)

    assert expanded.instances[key("main", "f")].refresh_generation == 5
    assert expanded.instances[key("double", "f", ("c",))].refresh_generation == 3
    assert expanded.instances[key("double", "gin", ("c",))].refresh_generation == 0


# 10. The order is a valid topological order and it is deterministic.


def _rich_main() -> GraphDefinition:
    return graph(
        "main",
        [
            make_node("s"),
            call_node("c1", "double"),
            call_node("c2", "double"),
            make_node("join"),
        ],
        [
            make_edge("e1", "s", "c1", to_port="x"),
            make_edge("e2", "s", "c2", to_port="x"),
            make_edge("e3", "c1", "join", from_port="r", to_port="a"),
            make_edge("e4", "c2", "join", from_port="r", to_port="b"),
        ],
    )


def test_topological_order_is_valid_and_deterministic() -> None:
    expanded_a = expand_double_first(_rich_main())
    expanded_b = expand_double_first(_rich_main())

    assert expanded_a.order == expanded_b.order
    position = {
        instance_key: index for index, instance_key in enumerate(expanded_a.order)
    }
    for instance_key in expanded_a.order:
        for connection in expanded_a.instances[instance_key].connections:
            assert position[connection.source] < position[instance_key]


# 11. Cycles and unknown targets raise the named errors.


def test_cycle_among_instances_raises_expansion_error() -> None:
    looped = graph(
        "looped",
        [make_node("a"), make_node("b")],
        [make_edge("e1", "a", "b"), make_edge("e2", "b", "a")],
    )

    with pytest.raises(ExpansionError) as excinfo:
        expand_graph(ProjectDocument(graphs=(looped,)), "looped", project_id=PROJECT)

    message = str(excinfo.value)
    assert "node='a'" in message
    assert isinstance(excinfo.value, ProjectDocumentError)


def test_unknown_graph_raises_unknown_graph_error() -> None:
    with pytest.raises(UnknownGraphError):
        expand_graph(ProjectDocument(graphs=()), "ghost", project_id=PROJECT)


# 12. A call feeding a call chains boundary to boundary.


def test_call_to_call_chain_connects_boundary_to_boundary() -> None:
    main = graph(
        "main",
        [
            make_node("s"),
            call_node("c1", "double"),
            call_node("c2", "double"),
            make_node("sink"),
        ],
        [
            make_edge("e1", "s", "c1", to_port="x"),
            make_edge("e-chain", "c1", "c2", from_port="r", to_port="x"),
            make_edge("e2", "c2", "sink", from_port="r"),
        ],
    )

    expanded = expand_double_first(main)

    (chained,) = expanded.instances[key("double", "gin", ("c2",))].connections
    assert chained.source == key("double", "gout", ("c1",))
    assert chained.edge.id == "e-chain"
    assert chained.edge.from_port == GRAPH_BOUNDARY_PORT
    assert chained.edge.to_port == GRAPH_BOUNDARY_PORT
    assert chained.edge.to_plug is None
    assert [c.source for c in expanded.instances[key("main", "sink")].connections] == [
        key("double", "gout", ("c2",))
    ]


# 13. Expanding the callee itself as the root keeps its call paths empty.


def test_expanding_the_callee_as_a_root_keeps_empty_call_paths() -> None:
    project = ProjectDocument(graphs=(double_graph(default_origin=True),))

    expanded = expand_graph(project, "double", project_id=PROJECT)

    assert set(expanded.instances) == {
        key("double", "gin"),
        key("double", "f"),
        key("double", "gout"),
    }
    boundary = expanded.instances[key("double", "gin")]
    assert boundary.connections == ()
    assert [default.id for default in boundary.origins] == ["od"]
    assert [c.source for c in expanded.instances[key("double", "f")].connections] == [
        key("double", "gin")
    ]


# End-to-end: one computation per fingerprint (the ADR 0020 reuse proof).


class RecordingRunner:
    """Instant ``ComputationRunner`` stand-in that logs every invocation."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(
        self, request: ComputationRequest
    ) -> Mapping[str, ArtifactOutputValue]:
        self.calls.append((request.instance.node.id, request.fingerprint))
        return {"value": make_artifact(content_hash=request.fingerprint)}

    @property
    def nodes(self) -> list[str]:
        return [node_id for node_id, _ in self.calls]


async def _run_join(
    project: ProjectDocument,
    targets: Sequence[InstanceKey],
) -> tuple[RunPlan, dict[InstanceKey, str], RecordingRunner, InMemoryResultStore]:
    expanded = expand_graph(project, "main", project_id=PROJECT)
    fingerprints = compute_fingerprints(expanded, FakeFacts())
    store = InMemoryResultStore()
    plan = await plan_run(
        graph=expanded,
        fingerprints=fingerprints,
        targets=tuple(targets),
        store=store,
    )
    runner = RecordingRunner()
    scheduler = build_scheduler(store=store, runner=runner, concurrency=4)
    await scheduler.submit("run-1", plan)
    result = await scheduler.wait("run-1")
    assert result.status == "succeeded"
    return plan, fingerprints, runner, store


def _e2e_project(*, double: GraphDefinition | None = None) -> ProjectDocument:
    return ProjectDocument(
        graphs=(_rich_main(), double if double is not None else double_graph())
    )


async def test_two_equal_calls_compute_once_and_share_the_result() -> None:
    plan, fingerprints, runner, store = await _run_join(
        _e2e_project(), [key("main", "join")]
    )

    first = key("double", "f", ("c1",))
    second = key("double", "f", ("c2",))
    assert fingerprints[first] == fingerprints[second]
    assert len(fingerprints) == 8

    # Eight instances, five distinct fingerprints: the plan holds exactly one
    # computation per fingerprint, and the ``f`` computation owns both calls.
    assert len(plan.computations) == 5
    assert plan.computations[fingerprints[first]].instances == (first, second)
    # The runner ran exactly once per distinct fingerprint, in chain order:
    # the source, one shared input boundary, one shared ``f``, one shared
    # output boundary, the join.
    assert runner.nodes == ["s", "gin", "f", "gout", "join"]
    assert len(runner.calls) == 5

    for instance_key in (first, second):
        pointer = await store.get_pointer(instance_key)
        assert pointer is not None
        assert pointer.last_result_fingerprint == fingerprints[instance_key]


async def test_different_sources_compute_the_callee_twice() -> None:
    main = graph(
        "main",
        [
            make_node("s1", config={"v": 1}),
            make_node("s2", config={"v": 2}),
            call_node("c1", "double"),
            call_node("c2", "double"),
            make_node("join"),
        ],
        [
            make_edge("e1", "s1", "c1", to_port="x"),
            make_edge("e2", "s2", "c2", to_port="x"),
            make_edge("e3", "c1", "join", from_port="r", to_port="a"),
            make_edge("e4", "c2", "join", from_port="r", to_port="b"),
        ],
    )

    _, fingerprints, runner, _ = await _run_join(
        ProjectDocument(graphs=(main, double_graph())), [key("main", "join")]
    )

    first = key("double", "f", ("c1",))
    second = key("double", "f", ("c2",))
    assert fingerprints[first] != fingerprints[second]
    assert runner.nodes.count("f") == 2
    assert len(runner.calls) == 9


async def test_changing_the_callee_moves_calls_and_downstream_only() -> None:
    _, before, _, _ = await _run_join(_e2e_project(), [key("main", "join")])
    changed = double_graph(f_config={"mult": 3})
    after = compute_fingerprints(
        expand_graph(_e2e_project(double=changed), "main", project_id=PROJECT),
        FakeFacts(),
    )

    assert after[key("main", "s")] == before[key("main", "s")]
    assert after[key("double", "gin", ("c1",))] == before[key("double", "gin", ("c1",))]
    for moved in (
        key("double", "f", ("c1",)),
        key("double", "f", ("c2",)),
        key("double", "gout", ("c1",)),
        key("double", "gout", ("c2",)),
        key("main", "join"),
    ):
        assert after[moved] != before[moved]
    # The two calls still agree with each other after the change.
    assert after[key("double", "f", ("c1",))] == after[key("double", "f", ("c2",))]


async def test_an_uncalled_sibling_graph_moves_nothing() -> None:
    project = _e2e_project()
    before = compute_fingerprints(
        expand_graph(project, "main", project_id=PROJECT), FakeFacts()
    )
    with_sibling = project.add_graph(
        graph("unrelated", [make_node("z", config={"deep": True})])
    )
    after = compute_fingerprints(
        expand_graph(with_sibling, "main", project_id=PROJECT), FakeFacts()
    )

    assert after == before


def test_node_positions_do_not_enter_fingerprints() -> None:
    before = compute_fingerprints(
        expand_graph(_e2e_project(), "main", project_id=PROJECT), FakeFacts()
    )
    moved = compute_fingerprints(
        expand_graph(
            _e2e_project(double=double_graph(f_position=(402.5, -17.25))),
            "main",
            project_id=PROJECT,
        ),
        FakeFacts(),
    )

    assert moved == before

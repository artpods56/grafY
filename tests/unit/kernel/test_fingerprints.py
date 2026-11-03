"""Node fingerprints (ADR 0020): every input moves a digest, nothing else does.

A fingerprint wrongly left unchanged serves a stale result as fresh, so each
case here names one input and demands that the instance's digest moves, plus
every descendant's through the upstream contribution. The other half is
equally load-bearing: canvas layout, ids, routing, the instance key and
unrelated instances must never move a digest, or nothing is ever reusable and
two calls of the same Graph stop sharing one computation.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

import pytest

from grafy_core.artifacts import ArtifactRef
from grafy_core.domain.saved_graphs import (
    GraphEdge,
    GraphNode,
    GraphOrigin,
)
from grafy_core.kernel.fingerprints import compute_fingerprints
from grafy_core.kernel.instances import Connection, ExpandedGraph, InstanceKey
from grafy_core.plugins import NodeCachePolicy
from tests.unit.kernel.builders import (
    ARTIFACT_ID_ONE,
    ARTIFACT_ID_TWO,
    ExpandedGraphBuilder,
    FakeFacts,
    expand_document,
    make_artifact,
    make_bindings,
    make_conversions,
    make_edge,
    make_key,
    make_layout,
    make_node,
    make_origin,
    make_plugs,
    make_point,
    make_projection,
)

FINGERPRINT_SHAPE = re.compile(r"\A[0-9a-f]{64}\Z")

# Known answers for `test_the_digest_scheme_has_a_known_answer`. Changing one is
# a deliberate re-fingerprinting of every stored result, never a refactor.
UNFED_NODE_FINGERPRINT = (
    "1f64f3952ae202d12e926ab8b24bbd7a473ae505631098c2bc5b7f31fec29ebd"
)
FED_NODE_FINGERPRINT = (
    "517297f4e2ae1a9262aec5297d0bc0825abfc85d88c17f60d94706396116a3e9"
)

SOURCE = "source"
TARGET = "target"
DOWNSTREAM = "downstream"

TARGET_PLUGS = (("in", "value"), ("alt", "value"), ("spare", "value"))


@dataclass(frozen=True, slots=True)
class Scenario:
    """One hand-built graph plus the deployment facts it is fingerprinted under."""

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...] = ()
    origins: tuple[GraphOrigin, ...] = ()
    facts: FakeFacts = field(default_factory=FakeFacts)
    refresh: Mapping[str, int] = MappingProxyType({})
    project_id: str = "project-1"
    graph_id: str = "graph-1"
    call_path: tuple[str, ...] = ()

    def graph(self) -> ExpandedGraph:
        return expand_document(
            self.nodes,
            self.edges,
            self.origins,
            project_id=self.project_id,
            graph_id=self.graph_id,
            call_path=self.call_path,
            refresh_generations=self.refresh,
        )

    def fingerprints(self) -> dict[str, str]:
        return {
            key.node_id: fingerprint
            for key, fingerprint in compute_fingerprints(
                self.graph(), self.facts
            ).items()
        }

    def node(self, node_id: str) -> GraphNode:
        return next(node for node in self.nodes if node.id == node_id)

    def edge(self, edge_id: str) -> GraphEdge:
        return next(edge for edge in self.edges if edge.id == edge_id)

    def origin(self, origin_id: str) -> GraphOrigin:
        return next(origin for origin in self.origins if origin.id == origin_id)

    def with_node(self, node_id: str, **changes: object) -> "Scenario":
        updated = self.node(node_id).model_copy(update=changes)
        return replace(
            self,
            nodes=tuple(updated if node.id == node_id else node for node in self.nodes),
        )

    def with_edge(self, edge_id: str, **changes: object) -> "Scenario":
        updated = self.edge(edge_id).model_copy(update=changes)
        return replace(
            self,
            edges=tuple(updated if edge.id == edge_id else edge for edge in self.edges),
        )

    def with_origin(self, origin_id: str, **changes: object) -> "Scenario":
        updated = self.origin(origin_id).model_copy(update=changes)
        return replace(
            self,
            origins=tuple(
                updated if origin.id == origin_id else origin for origin in self.origins
            ),
        )

    def with_facts(self, facts: FakeFacts) -> "Scenario":
        return replace(self, facts=facts)

    def with_refresh(self, node_id: str, generation: int) -> "Scenario":
        return replace(self, refresh={**self.refresh, node_id: generation})


SOURCE_AND_DESCENDANTS = frozenset({SOURCE, TARGET, DOWNSTREAM})
TARGET_AND_DESCENDANTS = frozenset({TARGET, DOWNSTREAM})


def _unchanged(scenario: Scenario) -> Scenario:
    """Precondition for a case that needs no shared setup beyond the chain."""
    return scenario


def _chain() -> Scenario:
    """``source -> target -> downstream``, the smallest graph with a descendant."""
    return Scenario(
        nodes=(
            make_node(
                SOURCE,
                operator_id="value.integer",
                config={"value": 1},
                position=(0.0, 0.0),
            ),
            make_node(
                TARGET,
                operator_id="test.arithmetic.add",
                config={"left": 0},
                plugs=TARGET_PLUGS,
                position=(120.0, 0.0),
            ),
            make_node(
                DOWNSTREAM,
                operator_id="test.arithmetic.multiply",
                config={},
                position=(240.0, 0.0),
            ),
        ),
        edges=(
            make_edge(
                "e-source-target",
                SOURCE,
                TARGET,
                to_port="value",
                to_plug="in",
            ),
            make_edge("e-target-downstream", TARGET, DOWNSTREAM, to_port="value"),
        ),
    )


@dataclass(frozen=True, slots=True)
class Invalidation:
    """One input, the instances its change must move, and a shared precondition."""

    case: str
    setup: Callable[[Scenario], Scenario]
    mutate: Callable[[Scenario], Scenario]
    changed: frozenset[str]


def _with_edge_conversion(scenario: Scenario, *steps: tuple[str, int]) -> Scenario:
    return scenario.with_edge(
        "e-source-target", conversion_path=make_conversions(*steps)
    )


def _with_lower_conversion(scenario: Scenario) -> Scenario:
    return _with_edge_conversion(scenario, ("text.to.lower", 1))


INVALIDATIONS: tuple[Invalidation, ...] = (
    # Node identity, at the root: everything downstream moves with it.
    Invalidation(
        case="operator id",
        setup=_unchanged,
        mutate=lambda s: s.with_node(SOURCE, operator_id="value.text"),
        changed=SOURCE_AND_DESCENDANTS,
    ),
    Invalidation(
        case="operator version",
        setup=_unchanged,
        mutate=lambda s: s.with_node(SOURCE, operator_version=2),
        changed=SOURCE_AND_DESCENDANTS,
    ),
    Invalidation(
        case="node kind",
        setup=_unchanged,
        mutate=lambda s: s.with_node(SOURCE, kind="module"),
        changed=SOURCE_AND_DESCENDANTS,
    ),
    Invalidation(
        case="config value",
        setup=_unchanged,
        mutate=lambda s: s.with_node(SOURCE, config={"value": 2}),
        changed=SOURCE_AND_DESCENDANTS,
    ),
    Invalidation(
        case="config key set",
        setup=_unchanged,
        mutate=lambda s: s.with_node(SOURCE, config={"value": 1, "label": "x"}),
        changed=SOURCE_AND_DESCENDANTS,
    ),
    Invalidation(
        case="implementation digest",
        setup=_unchanged,
        mutate=lambda s: s.with_facts(
            s.facts.with_implementation("value.integer", "b" * 64)
        ),
        changed=SOURCE_AND_DESCENDANTS,
    ),
    Invalidation(
        case="secret revision added",
        setup=_unchanged,
        mutate=lambda s: s.with_facts(
            s.facts.with_secrets(SOURCE, {"api_key": "rev-1"})
        ),
        changed=SOURCE_AND_DESCENDANTS,
    ),
    Invalidation(
        case="secret revision rotated",
        setup=lambda s: s.with_facts(
            s.facts.with_secrets(SOURCE, {"api_key": "rev-1"})
        ),
        mutate=lambda s: s.with_facts(
            s.facts.with_secrets(SOURCE, {"api_key": "rev-2"})
        ),
        changed=SOURCE_AND_DESCENDANTS,
    ),
    Invalidation(
        case="secret name added",
        setup=lambda s: s.with_facts(
            s.facts.with_secrets(SOURCE, {"api_key": "rev-1"})
        ),
        mutate=lambda s: s.with_facts(
            s.facts.with_secrets(SOURCE, {"api_key": "rev-1", "token": "t-1"})
        ),
        changed=SOURCE_AND_DESCENDANTS,
    ),
    Invalidation(
        case="artifact type binding variable",
        setup=lambda s: s.with_node(
            SOURCE, artifact_type_bindings=make_bindings(("payload", "table.row", 1))
        ),
        mutate=lambda s: s.with_node(
            SOURCE, artifact_type_bindings=make_bindings(("other", "table.row", 1))
        ),
        changed=SOURCE_AND_DESCENDANTS,
    ),
    Invalidation(
        case="artifact type binding type id",
        setup=lambda s: s.with_node(
            SOURCE, artifact_type_bindings=make_bindings(("payload", "table.row", 1))
        ),
        mutate=lambda s: s.with_node(
            SOURCE, artifact_type_bindings=make_bindings(("payload", "table.column", 1))
        ),
        changed=SOURCE_AND_DESCENDANTS,
    ),
    Invalidation(
        case="artifact type binding schema version",
        setup=lambda s: s.with_node(
            SOURCE, artifact_type_bindings=make_bindings(("payload", "table.row", 1))
        ),
        mutate=lambda s: s.with_node(
            SOURCE, artifact_type_bindings=make_bindings(("payload", "table.row", 2))
        ),
        changed=SOURCE_AND_DESCENDANTS,
    ),
    Invalidation(
        case="artifact type binding order",
        setup=lambda s: s.with_node(
            SOURCE,
            artifact_type_bindings=make_bindings(
                ("first", "table.row", 1),
                ("second", "table.row", 1),
            ),
        ),
        mutate=lambda s: s.with_node(
            SOURCE,
            artifact_type_bindings=make_bindings(
                ("second", "table.row", 1),
                ("first", "table.row", 1),
            ),
        ),
        changed=SOURCE_AND_DESCENDANTS,
    ),
    Invalidation(
        case="refresh generation of a NEVER node",
        setup=lambda s: s.with_facts(
            s.facts.with_cache_policy(SOURCE, NodeCachePolicy.NEVER)
        ),
        mutate=lambda s: s.with_refresh(SOURCE, 3),
        changed=SOURCE_AND_DESCENDANTS,
    ),
    # Node identity, at the middle: the root it does not read stays put.
    Invalidation(
        case="own config at the middle",
        setup=_unchanged,
        mutate=lambda s: s.with_node(TARGET, config={"left": 5}),
        changed=TARGET_AND_DESCENDANTS,
    ),
    Invalidation(
        case="own operator id at the middle",
        setup=_unchanged,
        mutate=lambda s: s.with_node(TARGET, operator_id="test.arithmetic.subtract"),
        changed=TARGET_AND_DESCENDANTS,
    ),
    # Transport, on the edge into the middle.
    Invalidation(
        case="connection from_port",
        setup=_unchanged,
        mutate=lambda s: s.with_edge("e-source-target", from_port="preview"),
        changed=TARGET_AND_DESCENDANTS,
    ),
    Invalidation(
        case="connection to_plug",
        setup=_unchanged,
        mutate=lambda s: s.with_edge("e-source-target", to_plug="alt"),
        changed=TARGET_AND_DESCENDANTS,
    ),
    Invalidation(
        case="connection collection mode",
        setup=_unchanged,
        mutate=lambda s: s.with_edge("e-source-target", collection_mode="map"),
        changed=TARGET_AND_DESCENDANTS,
    ),
    Invalidation(
        case="connection projection",
        setup=_unchanged,
        mutate=lambda s: s.with_edge(
            "e-source-target",
            projection=make_projection(("payload", "amount")),
        ),
        changed=TARGET_AND_DESCENDANTS,
    ),
    Invalidation(
        case="connection conversion id",
        setup=_with_lower_conversion,
        mutate=lambda s: _with_edge_conversion(s, ("text.to.upper", 1)),
        changed=TARGET_AND_DESCENDANTS,
    ),
    Invalidation(
        case="connection conversion version",
        setup=_with_lower_conversion,
        mutate=lambda s: _with_edge_conversion(s, ("text.to.lower", 2)),
        changed=TARGET_AND_DESCENDANTS,
    ),
    # Transport, on the edge into the leaf: only the leaf moves.
    Invalidation(
        case="to_port of the last connection",
        setup=_unchanged,
        mutate=lambda s: s.with_edge("e-target-downstream", to_port="payload"),
        changed=frozenset({DOWNSTREAM}),
    ),
)


@pytest.mark.parametrize(
    "invalidation",
    [pytest.param(case, id=case.case) for case in INVALIDATIONS],
)
def test_each_fingerprint_input_moves_its_instance_and_every_descendant(
    invalidation: Invalidation,
) -> None:
    base = invalidation.setup(_chain())
    before = base.fingerprints()
    after = invalidation.mutate(base).fingerprints()

    assert set(after) == set(before)
    for node_id, fingerprint in after.items():
        if node_id in invalidation.changed:
            assert fingerprint != before[node_id], (
                f"{invalidation.case} left {node_id} alone"
            )
        else:
            assert fingerprint == before[node_id], (
                f"{invalidation.case} moved unrelated {node_id}"
            )


def _branching() -> Scenario:
    """``root`` feeds a ``left`` and a ``right`` branch; only ``left`` joins ``join``."""
    return Scenario(
        nodes=(
            make_node("root", operator_id="value.integer", config={"value": 1}),
            make_node("left", operator_id="test.arithmetic.add", config={"left": 0}),
            make_node("right", operator_id="test.arithmetic.add", config={"left": 0}),
            make_node("join", operator_id="test.arithmetic.multiply", config={}),
        ),
        edges=(
            make_edge("e-root-left", "root", "left", to_port="value"),
            make_edge("e-root-right", "root", "right", to_port="value"),
            make_edge("e-left-join", "left", "join", to_port="value"),
        ),
    )


def test_a_sibling_branch_change_moves_only_its_own_descendants() -> None:
    base = _branching()
    before = base.fingerprints()
    after = base.with_node("left", config={"left": 9}).fingerprints()

    assert after["left"] != before["left"]
    assert after["join"] != before["join"]
    assert after["right"] == before["right"]
    assert after["root"] == before["root"]


def test_an_upstream_change_reaches_the_whole_chain_and_nothing_above_it() -> None:
    base = _chain()
    before = base.fingerprints()
    after = base.with_node(SOURCE, config={"value": 42}).fingerprints()

    assert after[SOURCE] != before[SOURCE]
    assert after[TARGET] != before[TARGET]
    assert after[DOWNSTREAM] != before[DOWNSTREAM]

    # The middle's own change leaves the root, which cannot see it, untouched.
    middle = base.with_node(TARGET, config={"left": 8}).fingerprints()
    assert middle[SOURCE] == before[SOURCE]
    assert middle[TARGET] != before[TARGET]
    assert middle[DOWNSTREAM] != before[DOWNSTREAM]


def test_feeding_a_different_input_plug_moves_the_node() -> None:
    base = _chain()
    before = base.fingerprints()

    assert (
        base.with_edge("e-source-target", to_plug="alt").fingerprints()[TARGET]
        != (before[TARGET])
    )


def test_the_node_order_of_its_input_plugs_is_part_of_the_digest() -> None:
    """Two fed plugs, the same connections: only the node's own order moved."""
    base = Scenario(
        nodes=(
            make_node("one", operator_id="value.integer", config={"value": 1}),
            make_node("two", operator_id="value.integer", config={"value": 2}),
            make_node(
                "target",
                operator_id="test.arithmetic.add",
                config={},
                plugs=(("p1", "value"), ("p2", "value")),
            ),
        ),
        edges=(
            make_edge("e-one", "one", "target", to_port="value", to_plug="p1"),
            make_edge("e-two", "two", "target", to_port="value", to_plug="p2"),
        ),
    )
    before = base.fingerprints()
    reordered = base.with_node(
        "target",
        input_plugs=make_plugs(("p2", "value"), ("p1", "value")),
    )

    assert reordered.fingerprints()["target"] != before["target"]
    assert reordered.fingerprints()["one"] == before["one"]


def test_adding_a_connection_moves_the_node_it_feeds() -> None:
    base = _chain()
    with_extra = replace(
        base,
        nodes=(
            *base.nodes,
            make_node("extra", operator_id="value.integer", config={"value": 3}),
        ),
        edges=(
            *base.edges,
            make_edge("e-extra-target", "extra", TARGET, to_port="alt"),
        ),
    )

    before = base.fingerprints()
    after = with_extra.fingerprints()

    assert after[TARGET] != before[TARGET]
    assert after[DOWNSTREAM] != before[DOWNSTREAM]
    assert after[SOURCE] == before[SOURCE]


def test_removing_a_connection_moves_the_node_it_used_to_feed() -> None:
    base = replace(
        _chain(),
        nodes=(
            *_chain().nodes,
            make_node("extra", operator_id="value.integer", config={"value": 3}),
        ),
        edges=(
            *_chain().edges,
            make_edge("e-extra-target", "extra", TARGET, to_port="alt"),
        ),
    )
    before = base.fingerprints()
    after = replace(
        base,
        edges=tuple(edge for edge in base.edges if edge.id != "e-extra-target"),
    ).fingerprints()

    assert after[TARGET] != before[TARGET]
    assert after[DOWNSTREAM] != before[DOWNSTREAM]
    assert after[SOURCE] == before[SOURCE]


def test_the_order_of_two_connections_on_one_port_is_execution_meaning() -> None:
    """An unplugged variadic port keeps document order, so swapping means swapping."""
    one = make_node("one", operator_id="value.integer", config={"value": 1})
    two = make_node("two", operator_id="value.integer", config={"value": 2})
    target = make_node(
        "target",
        operator_id="test.collect.members",
        config={},
        plugs=(("a", "value"), ("b", "value")),
    )
    first = make_edge("e-first", "one", "target", to_port="items")
    second = make_edge("e-second", "two", "target", to_port="items")

    forward = expand_document((one, two, target), (first, second))
    swapped = expand_document((one, two, target), (second, first))
    facts = FakeFacts()

    forward_prints = compute_fingerprints(forward, facts)
    swapped_prints = compute_fingerprints(swapped, facts)
    forward_by_id = {key.node_id: value for key, value in forward_prints.items()}
    swapped_by_id = {key.node_id: value for key, value in swapped_prints.items()}

    assert forward_by_id["target"] != swapped_by_id["target"]
    assert forward_by_id["one"] == swapped_by_id["one"]
    assert forward_by_id["two"] == swapped_by_id["two"]


def _crossed_call_boundary(
    *,
    crossing_plug: str,
    via_origin: bool,
) -> ExpandedGraph:
    """One callee boundary instance fed under one caller-side input plug.

    A caller's edge into a call node lands on the callee's boundary node with
    the *caller's* plug id, which that node does not list among its own, so the
    active-plug section of the digest cannot see it: the transport entry has to.
    """
    builder = ExpandedGraphBuilder()
    boundary = builder.add_instance(
        make_node("boundary", operator_id="boundary.input", config={}),
        call_path=("call-1",),
    )
    if via_origin:
        builder.attach_origin(
            boundary,
            make_origin(
                "o-crossing",
                "boundary",
                to_port="value",
                to_plug=crossing_plug,
            ),
        )
        return builder.build()
    upstream = builder.add_instance(
        make_node("outer-source", operator_id="value.integer", config={"value": 1}),
    )
    builder.connect(upstream, boundary, to_port="value", to_plug=crossing_plug)
    return builder.build()


@pytest.mark.parametrize("via_origin", [False, True], ids=["connection", "origin"])
def test_a_crossing_plug_the_node_does_not_own_is_still_transport(
    via_origin: bool,
) -> None:
    facts = FakeFacts()
    first = compute_fingerprints(
        _crossed_call_boundary(crossing_plug="caller-plug-a", via_origin=via_origin),
        facts,
    )
    second = compute_fingerprints(
        _crossed_call_boundary(crossing_plug="caller-plug-b", via_origin=via_origin),
        facts,
    )

    assert set(first) == set(second)
    assert first != second


def test_the_digest_keeps_the_connection_order_it_was_given() -> None:
    """Expansion ordered the connections; the digest must not order them again."""

    def build(written_order: tuple[str, str]) -> ExpandedGraph:
        builder = ExpandedGraphBuilder()
        sources = {
            node_id: builder.add_instance(
                make_node(node_id, operator_id="value.integer", config={"value": index})
            )
            for index, node_id in enumerate(("one", "two"))
        }
        target = builder.add_instance(
            make_node("target", operator_id="test.collect.members", config={}),
        )
        for node_id in written_order:
            builder.connect(
                sources[node_id],
                target,
                to_port="zeta" if node_id == "one" else "alpha",
            )
        return builder.build()

    facts = FakeFacts()
    written = compute_fingerprints(build(("one", "two")), facts)
    reversed_ = compute_fingerprints(build(("two", "one")), facts)
    written_target = next(
        value for key, value in written.items() if key.node_id == "target"
    )
    reversed_target = next(
        value for key, value in reversed_.items() if key.node_id == "target"
    )

    assert written_target != reversed_target


ORIGIN_TARGET = "held"
ORIGIN_CONSUMER = "consumer"
ORIGIN_ID = "o-held"


def _origin_scenario() -> Scenario:
    """``held`` keeps an artifact on an input and feeds ``consumer``."""
    return Scenario(
        nodes=(
            make_node(
                ORIGIN_TARGET,
                operator_id="value.loader",
                config={},
                plugs=(("in", "value"), ("alt", "value")),
            ),
            make_node(ORIGIN_CONSUMER, operator_id="test.arithmetic.add", config={}),
        ),
        edges=(make_edge("e-held", ORIGIN_TARGET, ORIGIN_CONSUMER, to_port="value"),),
        origins=(make_origin(ORIGIN_ID, ORIGIN_TARGET, to_port="value"),),
    )


ORIGIN_AND_CONSUMER = frozenset({ORIGIN_TARGET, ORIGIN_CONSUMER})


def _with_origin_conversion(scenario: Scenario) -> Scenario:
    return scenario.with_origin(
        ORIGIN_ID,
        conversion_path=make_conversions(("text.to.lower", 1)),
    )


ORIGIN_INVALIDATIONS: tuple[Invalidation, ...] = (
    Invalidation(
        case="origin artifact id",
        setup=_unchanged,
        mutate=lambda s: s.with_origin(
            ORIGIN_ID,
            value=make_artifact(ARTIFACT_ID_TWO),
        ),
        changed=ORIGIN_AND_CONSUMER,
    ),
    Invalidation(
        case="origin artifact type",
        setup=_unchanged,
        mutate=lambda s: s.with_origin(
            ORIGIN_ID,
            value=make_artifact(ARTIFACT_ID_ONE, artifact_type="scalar.text"),
        ),
        changed=ORIGIN_AND_CONSUMER,
    ),
    Invalidation(
        case="origin artifact schema version",
        setup=_unchanged,
        mutate=lambda s: s.with_origin(
            ORIGIN_ID,
            value=make_artifact(ARTIFACT_ID_ONE, schema_version=2),
        ),
        changed=ORIGIN_AND_CONSUMER,
    ),
    Invalidation(
        case="origin artifact content hash",
        setup=_unchanged,
        mutate=lambda s: s.with_origin(
            ORIGIN_ID,
            value=make_artifact(ARTIFACT_ID_ONE, content_hash="c" * 64),
        ),
        changed=ORIGIN_AND_CONSUMER,
    ),
    Invalidation(
        case="origin to_port",
        setup=_unchanged,
        mutate=lambda s: s.with_origin(ORIGIN_ID, to_port="other"),
        changed=ORIGIN_AND_CONSUMER,
    ),
    Invalidation(
        case="origin to_plug",
        setup=_unchanged,
        mutate=lambda s: s.with_origin(ORIGIN_ID, to_plug="alt"),
        changed=ORIGIN_AND_CONSUMER,
    ),
    Invalidation(
        case="origin collection mode",
        setup=_unchanged,
        mutate=lambda s: s.with_origin(ORIGIN_ID, collection_mode="map"),
        changed=ORIGIN_AND_CONSUMER,
    ),
    Invalidation(
        case="origin conversion id",
        setup=_with_origin_conversion,
        mutate=lambda s: s.with_origin(
            ORIGIN_ID,
            conversion_path=make_conversions(("text.to.upper", 1)),
        ),
        changed=ORIGIN_AND_CONSUMER,
    ),
    Invalidation(
        case="origin conversion version",
        setup=_with_origin_conversion,
        mutate=lambda s: s.with_origin(
            ORIGIN_ID,
            conversion_path=make_conversions(("text.to.lower", 2)),
        ),
        changed=ORIGIN_AND_CONSUMER,
    ),
)


@pytest.mark.parametrize(
    "invalidation",
    [pytest.param(case, id=case.case) for case in ORIGIN_INVALIDATIONS],
)
def test_each_origin_input_moves_the_node_it_feeds_and_downstream(
    invalidation: Invalidation,
) -> None:
    base = invalidation.setup(_origin_scenario())
    before = base.fingerprints()
    after = invalidation.mutate(base).fingerprints()

    assert set(after) == set(before)
    for node_id, fingerprint in after.items():
        if node_id in invalidation.changed:
            assert fingerprint != before[node_id], (
                f"{invalidation.case} left {node_id} alone"
            )
        else:
            assert fingerprint == before[node_id], (
                f"{invalidation.case} moved unrelated {node_id}"
            )


def test_adding_an_origin_moves_the_node_it_feeds() -> None:
    base = replace(_origin_scenario(), origins=())
    before = base.fingerprints()
    after = replace(
        base,
        origins=(make_origin(ORIGIN_ID, ORIGIN_TARGET, to_port="value"),),
    ).fingerprints()

    assert after[ORIGIN_TARGET] != before[ORIGIN_TARGET]
    assert after[ORIGIN_CONSUMER] != before[ORIGIN_CONSUMER]


def test_removing_an_origin_moves_the_node_it_used_to_feed() -> None:
    base = _origin_scenario()
    before = base.fingerprints()
    after = replace(base, origins=()).fingerprints()

    assert after[ORIGIN_TARGET] != before[ORIGIN_TARGET]
    assert after[ORIGIN_CONSUMER] != before[ORIGIN_CONSUMER]


def test_an_origin_id_never_enters_a_fingerprint() -> None:
    base = _origin_scenario()

    assert base.with_origin(ORIGIN_ID, id="o-renamed").fingerprints() == (
        base.fingerprints()
    )


def test_origins_are_fingerprinted_in_slot_order_not_document_order() -> None:
    base = Scenario(
        nodes=(
            make_node(
                "target",
                operator_id="test.collect.members",
                config={},
                plugs=(("first", "value"), ("second", "other")),
            ),
        ),
        origins=(
            make_origin("o-second", "target", to_port="other", to_plug="second"),
            make_origin("o-first", "target", to_port="value", to_plug="first"),
        ),
    )
    document_order = compute_fingerprints(base.graph(), base.facts)
    other_document_order = compute_fingerprints(
        replace(base, origins=tuple(reversed(base.origins))).graph(),
        base.facts,
    )

    assert document_order == other_document_order


def test_two_origins_on_one_slot_keep_the_order_they_were_written_in() -> None:
    base = Scenario(
        nodes=(make_node("target", operator_id="test.collect.members", config={}),),
        origins=(
            make_origin(
                "o-one",
                "target",
                to_port="items",
                value=make_artifact(ARTIFACT_ID_ONE),
            ),
            make_origin(
                "o-two",
                "target",
                to_port="items",
                value=make_artifact(ARTIFACT_ID_TWO),
            ),
        ),
    )
    forward = compute_fingerprints(base.graph(), base.facts)
    swapped = compute_fingerprints(
        replace(
            base,
            origins=(
                base.origin("o-two"),
                base.origin("o-one"),
            ),
        ).graph(),
        base.facts,
    )

    assert list(forward.values()) != list(swapped.values())


def test_canvas_position_and_layout_never_enter_a_fingerprint() -> None:
    base = _chain()
    before = base.fingerprints()
    moved = base.with_node(SOURCE, position=make_point(1_240.0, -880.0))
    resized = moved.with_node(TARGET, layout=make_layout(512.0))

    assert resized.fingerprints() == before


@pytest.mark.parametrize(
    ("edge_id", "changes"),
    [
        pytest.param(
            "e-source-target",
            {"id": "e-renamed"},
            id="edge id on the first connection",
        ),
        pytest.param(
            "e-target-downstream",
            {"id": "another-id"},
            id="edge id on the last connection",
        ),
        pytest.param(
            "e-source-target",
            {"route_offset": make_point(40.0, -18.0)},
            id="route offset on the first connection",
        ),
        pytest.param(
            "e-target-downstream",
            {"route_offset": make_point(40.0, -18.0)},
            id="route offset on the last connection",
        ),
        pytest.param(
            "e-source-target",
            {"enabled": True},
            id="the enabled flag as it already stands",
        ),
    ],
)
def test_edge_identity_and_routing_never_enter_a_fingerprint(
    edge_id: str,
    changes: Mapping[str, object],
) -> None:
    base = _chain()

    assert base.with_edge(edge_id, **changes).fingerprints() == base.fingerprints()


def test_the_instance_key_never_enters_a_fingerprint() -> None:
    """The same content under another project, graph, call path or map index."""
    base = _chain()
    before = base.fingerprints()

    elsewhere = replace(
        base,
        project_id="project-2",
        graph_id="graph-9",
        call_path=("call-node-1", "call-node-2"),
    )
    assert elsewhere.fingerprints() == before


def test_map_index_never_enters_a_fingerprint() -> None:
    node = make_node("body", operator_id="test.arithmetic.add", config={"left": 1})
    builder = ExpandedGraphBuilder()
    plain = builder.add_instance(node)
    keyed = builder.add_instance(node, map_index=3)

    fingerprints = compute_fingerprints(builder.build(), FakeFacts())

    assert plain != keyed
    assert fingerprints[plain] == fingerprints[keyed]


def test_renaming_the_nodes_of_a_chain_keeps_every_fingerprint() -> None:
    """Same content and same wiring under different node ids and instance keys."""
    original = _chain().fingerprints()
    names = {"source": "a", "target": "b", "downstream": "c"}
    renamed_nodes = tuple(
        node.model_copy(update={"id": names[node.id]}) for node in _chain().nodes
    )
    renamed_edges = tuple(
        edge.model_copy(
            update={
                "id": f"renamed-{index}",
                "from_node": names[edge.from_node],
                "to_node": names[edge.to_node],
            }
        )
        for index, edge in enumerate(_chain().edges)
    )
    after = compute_fingerprints(
        expand_document(renamed_nodes, renamed_edges),
        FakeFacts(),
    )

    assert {key.node_id: value for key, value in after.items()} == {
        "a": original[SOURCE],
        "b": original[TARGET],
        "c": original[DOWNSTREAM],
    }


def test_the_enabled_flag_of_an_already_expanded_connection_is_not_digested() -> None:
    """Expansion decides what is a connection; the digest reads the connection set.

    A disabled edge never reaches an instance as a connection, so the flag that
    kept it out is not itself a fingerprint input.
    """
    graph = _chain().graph()
    muted = ExpandedGraph(
        project_id=graph.project_id,
        graph_id=graph.graph_id,
        instances={
            key: replace(
                instance,
                connections=tuple(
                    replace(
                        connection,
                        edge=connection.edge.model_copy(update={"enabled": False}),
                    )
                    for connection in instance.connections
                ),
            )
            for key, instance in graph.instances.items()
        },
        order=graph.order,
    )

    assert compute_fingerprints(muted, FakeFacts()) == compute_fingerprints(
        graph, FakeFacts()
    )


def test_another_operators_implementation_digest_does_not_move_a_node() -> None:
    base = _chain()
    before = base.fingerprints()
    after = base.with_facts(
        base.facts.with_implementation("unrelated.operator", "d" * 64)
    ).fingerprints()

    assert after == before


def test_another_instance_implementation_digest_moves_only_its_own_branch() -> None:
    base = _branching()
    before = base.fingerprints()
    after = base.with_facts(
        base.facts.with_implementation("test.arithmetic.add", "e" * 64)
    ).fingerprints()

    # Both branch heads run that operator, so both move (together, since they
    # are twins); the root runs something else and stays. The join moves with
    # its upstream, which is exactly the transitivity the digest is for.
    assert after["left"] != before["left"]
    assert after["right"] != before["right"]
    assert after["left"] == after["right"]
    assert after["root"] == before["root"]
    assert after["join"] != before["join"]


def test_another_instances_secret_revisions_do_not_move_this_one() -> None:
    base = _branching()
    before = base.fingerprints()
    after = base.with_facts(
        base.facts.with_secrets("right", {"api_key": "rev-1"})
    ).fingerprints()

    assert after["right"] != before["right"]
    assert after["root"] == before["root"]
    assert after["left"] == before["left"]
    assert after["join"] == before["join"]


def test_refresh_generation_of_an_exact_cache_node_never_enters_a_fingerprint() -> None:
    base = _chain()
    before = base.fingerprints()

    assert base.with_refresh(SOURCE, 7).fingerprints() == before
    assert (
        base.with_node(DOWNSTREAM, config={"k": 1})
        .with_refresh(SOURCE, 7)
        .fingerprints()[SOURCE]
        == before[SOURCE]
    )


def test_an_empty_secret_table_is_the_same_as_no_secret_table() -> None:
    base = _chain()

    assert (
        base.with_facts(base.facts.with_secrets(SOURCE, {})).fingerprints()
        == base.fingerprints()
    )


def test_an_unconnected_node_elsewhere_does_not_move_the_chain() -> None:
    base = _chain()
    before = base.fingerprints()
    after = replace(
        base,
        nodes=(
            *base.nodes,
            make_node("elsewhere", operator_id="value.integer", config={"value": 8}),
        ),
    ).fingerprints()

    assert {node_id: after[node_id] for node_id in before} == before


def test_a_spare_input_plug_nothing_feeds_does_not_move_the_node() -> None:
    base = _chain()
    before = base.fingerprints()
    with_spare = base.with_node(
        TARGET,
        input_plugs=make_plugs(
            ("in", "value"),
            ("alt", "value"),
            ("spare", "value"),
            ("spare-2", "value"),
        ),
    )

    assert with_spare.fingerprints() == before


def test_a_fingerprint_is_deterministic_and_hexadecimal() -> None:
    base = _chain()
    first = base.fingerprints()
    second = compute_fingerprints(base.graph(), base.facts)

    assert first == {key.node_id: value for key, value in second.items()}
    assert len(set(first.values())) == len(first)
    for fingerprint in first.values():
        assert FINGERPRINT_SHAPE.match(fingerprint) is not None


def test_configuration_key_order_is_not_part_of_a_fingerprint() -> None:
    base = replace(_chain(), edges=(), origins=())
    written = base.with_node(
        SOURCE,
        config={"value": 1, "nested": {"a": 1, "b": [1, 2]}, "label": "x"},
    )
    reordered = base.with_node(
        SOURCE,
        config={"label": "x", "nested": {"b": [1, 2], "a": 1}, "value": 1},
    )

    assert reordered.fingerprints() == written.fingerprints()


def test_a_connection_whose_source_is_not_in_the_graph_is_rejected() -> None:
    builder = ExpandedGraphBuilder()
    target = builder.add_instance(make_node("target"))
    builder.add_connection(
        target,
        Connection(
            source=make_key("ghost"),
            edge=make_edge("e-ghost", "ghost", "target", to_port="value"),
        ),
    )

    with pytest.raises(ValueError) as error:
        compute_fingerprints(builder.build(), FakeFacts())

    message = str(error.value)
    assert "target" in message
    assert "not an instance" in message
    assert "ghost" in message


def test_a_connection_whose_source_sits_later_in_the_order_is_rejected() -> None:
    builder = ExpandedGraphBuilder()
    source = builder.add_instance(make_node("source"))
    target = builder.add_instance(make_node("target"))
    builder.connect(source, target)

    with pytest.raises(ValueError) as error:
        compute_fingerprints(builder.build(order=[target, source]), FakeFacts())

    message = str(error.value)
    assert "target" in message
    assert "source" in message
    assert "graph.order" in message


def test_an_order_that_names_an_unknown_instance_is_rejected() -> None:
    builder = ExpandedGraphBuilder()
    builder.add_instance(make_node("target"))

    with pytest.raises(ValueError) as error:
        compute_fingerprints(builder.build(order=[make_key("nowhere")]), FakeFacts())

    assert "nowhere" in str(error.value)


def test_two_instances_at_different_call_paths_with_one_upstream_share_a_digest() -> (
    None
):
    """The single-flight precondition: one content, one upstream, one computation."""
    builder = ExpandedGraphBuilder()
    upstream = builder.add_instance(
        make_node("source", operator_id="value.integer", config={"value": 7})
    )
    shared = make_node("inner", operator_id="test.arithmetic.add", config={"left": 0})
    first = builder.add_instance(shared, call_path=("call-a",))
    second = builder.add_instance(shared, call_path=("call-b",))
    builder.connect(upstream, first)
    builder.connect(upstream, second)

    fingerprints = compute_fingerprints(builder.build(), FakeFacts())

    assert first != second
    assert fingerprints[first] == fingerprints[second]
    assert fingerprints[first] != fingerprints[upstream]


def test_the_same_node_at_two_call_paths_divides_when_its_input_divides() -> None:
    """Sharing is by fingerprint only: a different upstream separates the two."""
    builder = ExpandedGraphBuilder()
    shared = make_node("inner", operator_id="test.arithmetic.add", config={"left": 0})
    left_upstream = builder.add_instance(
        make_node("left-source", operator_id="value.integer", config={"value": 1})
    )
    right_upstream = builder.add_instance(
        make_node("right-source", operator_id="value.integer", config={"value": 2})
    )
    first = builder.add_instance(shared, call_path=("call-a",))
    second = builder.add_instance(shared, call_path=("call-b",))
    builder.connect(left_upstream, first)
    builder.connect(right_upstream, second)

    fingerprints = compute_fingerprints(builder.build(), FakeFacts())

    assert fingerprints[first] != fingerprints[second]


def test_the_same_origin_at_two_call_paths_shares_a_digest() -> None:
    builder = ExpandedGraphBuilder()
    shared = make_node(
        "held",
        operator_id="value.loader",
        config={},
        plugs=(("in", "value"),),
    )
    first = builder.add_instance(shared, call_path=("call-a",))
    second = builder.add_instance(shared, call_path=("call-b",))
    origin = make_origin("o-held", "held", to_port="value", to_plug="in")
    builder.attach_origin(first, origin)
    builder.attach_origin(second, origin)

    fingerprints = compute_fingerprints(builder.build(), FakeFacts())

    assert len(set(fingerprints.values())) == 1


def test_the_digest_scheme_has_a_known_answer() -> None:
    """One fixed graph, one fixed digest: the scheme cannot drift unnoticed.

    Moving the scheme means no stored result is ever served again, so it has to
    be a decision rather than a side effect of an edit. The two unpinned nodes
    differ in position and layout alone and still share a digest, which pins
    the exclusion list next to the inclusion list.
    """
    facts = (
        FakeFacts()
        .with_implementation("test.arithmetic.add", "b" * 64)
        .with_secrets("target", {"api_key": "rev-1"})
        .with_cache_policy("target", NodeCachePolicy.NEVER)
    )
    unfed = expand_document(
        (
            make_node(
                "lone",
                operator_id="value.integer",
                config={"value": 1},
                position=(30.0, 40.0),
                width=288.0,
            ),
        ),
    )
    fed = expand_document(
        (
            make_node(
                "source",
                operator_id="value.integer",
                config={"value": 1},
                position=(0.0, 0.0),
            ),
            make_node(
                "target",
                operator_id="test.arithmetic.add",
                config={"left": 0, "mode": "strict"},
                plugs=(("in", "value"), ("spare", "value")),
                bindings=(("left", "scalar.integer", 1),),
                position=(120.0, 0.0),
                width=320.0,
            ),
        ),
        (
            make_edge(
                "e-source-target",
                "source",
                "target",
                from_port="result",
                to_port="value",
                to_plug="in",
                collection_mode="map",
                projection=("payload", "amount"),
                conversion=(("text.to.lower", 3),),
                route_offset=(12.0, -6.0),
            ),
        ),
        (
            make_origin(
                "o-target",
                "target",
                to_port="extra",
                value=make_artifact(content_hash="c" * 64),
            ),
        ),
        refresh_generations={"target": 4},
    )

    assert {
        key.node_id: value for key, value in compute_fingerprints(unfed, facts).items()
    } == {"lone": UNFED_NODE_FINGERPRINT}
    assert {
        key.node_id: value for key, value in compute_fingerprints(fed, facts).items()
    } == {"source": UNFED_NODE_FINGERPRINT, "target": FED_NODE_FINGERPRINT}


def test_the_builder_vocabulary_matches_the_pinned_models() -> None:
    """The builders hand the pinned types values of the pinned shape."""
    node: GraphNode = make_node(
        SOURCE,
        plugs=TARGET_PLUGS,
        bindings=(("payload", "table.row", 1),),
    )
    edge: GraphEdge = make_edge(
        "e-shape",
        SOURCE,
        TARGET,
        projection=("payload",),
        conversion=(("text.to.lower", 1),),
    )
    origin: GraphOrigin = make_origin(
        "o-shape",
        TARGET,
        value=make_artifact(ARTIFACT_ID_ONE),
    )
    key: InstanceKey = make_key(SOURCE, call_path=("call-a",), map_index=2)
    artifact: ArtifactRef = make_artifact(ARTIFACT_ID_ONE)

    assert node.id == SOURCE
    assert edge.to_port == "value"
    assert origin.to_plug is None
    assert key.sort_key[0] == "project-1"
    assert artifact.artifact_type == "scalar.integer"

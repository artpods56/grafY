"""A tool call is the node's instance with arguments on some inputs (ADR 0021).

The kernel half of the claim is small and exact: arguments replace whatever fed
their slot and nothing else, the call is fingerprinted like any instance (so equal
arguments share a result and different ones do not), and the plan for it records
no instance.
"""

import pytest

from grafy_core.kernel.fingerprints import compute_fingerprints
from grafy_core.kernel.tool_calls import (
    UnknownToolInstanceError,
    with_arguments,
    without_pointer,
)
from tests.unit.kernel.builders import (
    FakeFacts,
    expand_document,
    make_artifact,
    make_edge,
    make_key,
    make_node,
    make_origin,
)
from grafy_core.kernel.scheduler import ComputationPlan, RunPlan


def _graph():
    """``source`` and ``other`` feed ``tool`` on ports ``value`` and ``extra``."""
    return expand_document(
        [make_node("source"), make_node("other"), make_node("tool")],
        [
            make_edge("e1", "source", "tool", to_port="value"),
            make_edge("e2", "other", "tool", to_port="extra"),
        ],
    )


def _argument(mark: int, *, port: str = "value"):
    return make_origin(
        f"arg-{port}",
        "tool",
        to_port=port,
        value=make_artifact(content_hash=f"hash-{mark}"),
    )


def test_an_argument_replaces_what_fed_its_slot_and_nothing_else() -> None:
    graph = _graph()
    tool = make_key("tool")

    called = with_arguments(graph, tool, [_argument(1)])

    instance = called.instances[tool]
    assert [c.edge.to_port for c in instance.connections] == ["extra"]
    assert [o.to_port for o in instance.origins] == ["value"]
    # The instance the document holds is left as it was.
    assert [c.edge.to_port for c in graph.instances[tool].connections] == [
        "extra",
        "value",
    ]
    assert called.order == graph.order


def test_an_argument_replaces_an_origin_the_document_held() -> None:
    held = make_origin(
        "held", "tool", to_port="value", value=make_artifact(content_hash="hash-7")
    )
    graph = expand_document([make_node("tool")], [], [held])
    tool = make_key("tool")

    called = with_arguments(graph, tool, [_argument(8)])

    assert [o.id for o in called.instances[tool].origins] == ["arg-value"]


def test_equal_arguments_share_a_fingerprint_and_different_ones_do_not() -> None:
    facts = FakeFacts()
    tool = make_key("tool")

    same_a = compute_fingerprints(with_arguments(_graph(), tool, [_argument(1)]), facts)
    same_b = compute_fingerprints(with_arguments(_graph(), tool, [_argument(1)]), facts)
    other = compute_fingerprints(with_arguments(_graph(), tool, [_argument(2)]), facts)
    wired = compute_fingerprints(_graph(), facts)

    assert same_a[tool] == same_b[tool]
    assert other[tool] != same_a[tool]
    assert wired[tool] != same_a[tool]


def test_an_instance_the_graph_does_not_hold_is_refused() -> None:
    with pytest.raises(UnknownToolInstanceError):
        with_arguments(_graph(), make_key("ghost"), [_argument(1)])


def test_the_plan_for_a_call_records_no_instance_for_the_call_alone() -> None:
    tool = make_key("tool")
    source = make_key("source")
    graph = _graph()
    representative = graph.instances[tool]

    def plan_for(key, fingerprint):
        return ComputationPlan(
            fingerprint=fingerprint,
            representative=graph.instances[key],
            instances=(key,),
            depends_on=frozenset(),
            upstream_fingerprints={},
        )

    plan = RunPlan(
        targets=(tool,),
        computations={"call": plan_for(tool, "call"), "up": plan_for(source, "up")},
    )

    trimmed = without_pointer(plan, "call")

    assert trimmed.computations["call"].instances == ()
    assert trimmed.computations["call"].representative is representative
    assert trimmed.computations["up"].instances == (source,)
    # An unknown fingerprint changes nothing.
    assert without_pointer(plan, "absent").computations == plan.computations

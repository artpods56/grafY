"""The Project document: Graphs, their interfaces, and the calls between them.

Every document here is hand-built from the ``SavedGraph*`` value types so a test
moves exactly one thing: one public name, one call node, one refresh generation.
The rules under test are ADR 0020's: the call relation is acyclic, a Graph with
callers cannot be removed, and an interface change surfaces at its call sites as
a connection issue rather than a rejected edit. No I/O, no clocks, no sleeps.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from pydantic import ValidationError

from grafy_core.domain.saved_graphs import SavedGraphDocument, SavedGraphNode
from grafy_core.kernel.project import (
    CALL_NODE_KIND,
    GRAPH_ARTIFACT_TYPE_VARIABLE,
    GRAPH_BOUNDARY_PORT,
    GRAPH_INPUT_OPERATOR_ID,
    GRAPH_OUTPUT_OPERATOR_ID,
    CallSite,
    CallSiteIssue,
    DuplicateGraphError,
    GraphCallCycleError,
    GraphDefinition,
    GraphHasCallersError,
    MissingCalleeError,
    ProjectDocument,
    ProjectDocumentError,
    UnknownGraphError,
    call_site_issues,
    graph_interface,
)
from tests.unit.kernel.builders import make_edge, make_node, make_origin

# Graph and node builders


def input_node(
    node_id: str = "in-a",
    public_name: str = "value",
    *,
    required: bool | None = None,
    description: str | None = None,
    bound_type: tuple[str, int] | None = None,
    config: Mapping[str, object] | None = None,
) -> SavedGraphNode:
    node_config: dict[str, object] = {"public_name": public_name}
    if required is not None:
        node_config["required"] = required
    if description is not None:
        node_config["description"] = description
    if config is not None:
        node_config.update(config)
    return make_node(
        node_id,
        operator_id=GRAPH_INPUT_OPERATOR_ID,
        operator_version=1,
        config=node_config,
        bindings=()
        if bound_type is None
        else [(GRAPH_ARTIFACT_TYPE_VARIABLE, *bound_type)],
        position=(0.0, 0.0),
    )


def output_node(
    node_id: str = "out-a",
    public_name: str = "result",
    *,
    description: str | None = None,
    bound_type: tuple[str, int] | None = None,
    config: Mapping[str, object] | None = None,
) -> SavedGraphNode:
    node_config: dict[str, object] = {"public_name": public_name}
    if description is not None:
        node_config["description"] = description
    if config is not None:
        node_config.update(config)
    return make_node(
        node_id,
        operator_id=GRAPH_OUTPUT_OPERATOR_ID,
        operator_version=1,
        config=node_config,
        bindings=()
        if bound_type is None
        else [(GRAPH_ARTIFACT_TYPE_VARIABLE, *bound_type)],
        position=(100.0, 0.0),
    )


def call_node(
    node_id: str,
    callee: str,
    *,
    operator_version: int = 1,
    position: tuple[float, float] = (0.0, 100.0),
) -> SavedGraphNode:
    return make_node(
        node_id,
        kind=CALL_NODE_KIND,
        operator_id=callee,
        operator_version=operator_version,
        position=position,
    )


def leaf(node_id: str = "leaf") -> SavedGraphNode:
    return make_node(node_id)


def make_document(
    *nodes: SavedGraphNode,
    edges: Sequence[Any] = (),
    origins: Sequence[Any] = (),
) -> SavedGraphDocument:
    return SavedGraphDocument(
        nodes=tuple(nodes), edges=tuple(edges), origins=tuple(origins)
    )


def make_graph(
    graph_id: str = "g1",
    *nodes: SavedGraphNode,
    name: str | None = None,
    edges: Sequence[Any] = (),
    origins: Sequence[Any] = (),
    refresh_generations: Mapping[str, int] | None = None,
) -> GraphDefinition:
    return GraphDefinition(
        id=graph_id,
        name=graph_id if name is None else name,
        document=make_document(*nodes, edges=edges, origins=origins),
        refresh_generations=dict(refresh_generations or {}),
    )


def simple_graph(graph_id: str = "g1", **kwargs: Any) -> GraphDefinition:
    """A Graph with one input, one leaf, one output: the callable shape."""
    return make_graph(
        graph_id,
        input_node(f"{graph_id}-in", "value"),
        leaf(f"{graph_id}-leaf"),
        output_node(f"{graph_id}-out", "result"),
        **kwargs,
    )


def caller_graph(
    graph_id: str, callee: str, *, node_id: str = "call"
) -> GraphDefinition:
    return make_graph(
        graph_id,
        input_node(f"{graph_id}-in", "value"),
        call_node(node_id, callee),
        output_node(f"{graph_id}-out", "result"),
    )


# GraphDefinition


def test_graph_name_is_stripped_and_bounded() -> None:
    graph = make_graph(name="  Prep  ")
    assert graph.name == "Prep"

    with pytest.raises(ValidationError):
        make_graph(name="   ")
    with pytest.raises(ValidationError):
        make_graph(name="n" * 161)


def test_graph_rejects_missing_and_bad_public_name() -> None:
    with pytest.raises(ValidationError, match="public_name"):
        make_graph("g1", make_node("in-a", operator_id=GRAPH_INPUT_OPERATOR_ID))
    for bad in ("Value", "9value", "value-one", ""):
        with pytest.raises(ValidationError, match="public_name"):
            make_graph("g1", input_node("in-a", bad))


def test_graph_rejects_duplicate_public_name_per_direction_only() -> None:
    with pytest.raises(ValidationError, match="input 'value' twice"):
        make_graph("g1", input_node("in-a", "value"), input_node("in-b", "value"))
    # The same name on the two sides is one pipe through the Graph, not a clash.
    graph = make_graph("g1", input_node("in-a", "value"), output_node("out-a", "value"))
    assert graph.interface.input_names == frozenset({"value"})
    assert graph.interface.output_names == frozenset({"value"})


def test_graph_rejects_boundary_node_that_is_not_a_builtin() -> None:
    with pytest.raises(ValidationError, match="builtin"):
        make_graph(
            "g1",
            make_node(
                "in-a",
                kind=CALL_NODE_KIND,
                operator_id=GRAPH_INPUT_OPERATOR_ID,
                config={"public_name": "value"},
            ),
        )


def test_graph_rejects_unknown_boundary_config_key() -> None:
    with pytest.raises(ValidationError, match="unknown config keys"):
        make_graph("g1", input_node("in-a", "value", config={"colour": "red"}))


def test_graph_rejects_required_on_an_output_boundary_node() -> None:
    with pytest.raises(ValidationError, match="must not\\s+declare required"):
        make_graph("g1", output_node("out-a", "result", config={"required": False}))


def test_graph_refresh_generations_must_name_a_node_and_be_non_negative() -> None:
    graph = simple_graph("g1", refresh_generations={"g1-leaf": 3})
    assert graph.refresh_generations == {"g1-leaf": 3}

    with pytest.raises(ValidationError, match="unknown node"):
        simple_graph("g1", refresh_generations={"ghost": 1})
    with pytest.raises(ValidationError, match="greater than or equal"):
        simple_graph("g1", refresh_generations={"g1-leaf": -1})


def test_graph_refresh_generations_serializes_as_a_plain_dict() -> None:
    graph = simple_graph("g1", refresh_generations={"g1-leaf": 2})
    assert graph.model_dump()["refresh_generations"] == {"g1-leaf": 2}


# graph_interface


def test_graph_interface_keeps_document_order() -> None:
    graph = make_graph(
        "g1",
        input_node("in-b", "beta"),
        input_node("in-a", "alpha"),
        output_node("out-b", "second"),
        output_node("out-a", "first"),
    )
    interface = graph_interface(graph)
    assert [port.name for port in interface.inputs] == ["beta", "alpha"]
    assert [port.name for port in interface.outputs] == ["second", "first"]


def test_graph_interface_reads_required_description_and_type_binding() -> None:
    graph = make_graph(
        "g1",
        input_node("in-1", "one", bound_type=("scalar.integer", 1)),
        input_node("in-2", "two", required=False, description="optional"),
        output_node("out-1", "got", bound_type=("table.frame", 3)),
        output_node("out-2", "loose"),
    )
    interface = graph_interface(graph)
    one, two = interface.inputs
    assert one.required is True
    assert one.description is None
    assert one.artifact_type is not None
    assert (one.artifact_type.id, one.artifact_type.schema_version) == (
        "scalar.integer",
        1,
    )
    assert two.required is False
    assert two.description == "optional"
    # Outputs are always required, bound or not.
    assert [port.required for port in interface.outputs] == [True, True]
    assert [port.artifact_type for port in interface.outputs] == [
        interface.outputs[0].artifact_type,
        None,
    ]


def test_graph_interface_ignores_plain_nodes() -> None:
    interface = graph_interface(simple_graph("g1"))
    assert [port.name for port in interface.inputs] == ["value"]
    assert [port.name for port in interface.outputs] == ["result"]
    # The boundary node's own port inside its Graph is the one value pin.
    assert GRAPH_BOUNDARY_PORT == "value"


# ProjectDocument validation


def test_project_rejects_duplicate_graph_id() -> None:
    with pytest.raises(ValidationError, match="appears twice"):
        ProjectDocument(graphs=(simple_graph("g1"), simple_graph("g1", name="Other")))
    with pytest.raises(DuplicateGraphError, match="appears twice"):
        ProjectDocument(graphs=(simple_graph("g1"),)).add_graph(
            simple_graph("g1", name="Other")
        )


def test_project_rejects_duplicate_name_differing_only_in_case() -> None:
    first = simple_graph("g1", name="Daily load")
    second = simple_graph("g2", name="daily LOAD")
    with pytest.raises(ValidationError, match="is used by both"):
        ProjectDocument(graphs=(first, second))
    with pytest.raises(DuplicateGraphError, match="is used by both"):
        ProjectDocument(graphs=(first,)).add_graph(second)
    with pytest.raises(DuplicateGraphError):
        ProjectDocument(
            graphs=(first, simple_graph("g2", name="Nightly"))
        ).rename_graph("g2", " daily load ")


def test_project_rejects_a_call_to_a_graph_it_does_not_hold() -> None:
    with pytest.raises(ValidationError, match="calls unknown graph 'gone'"):
        ProjectDocument(graphs=(caller_graph("g1", "gone"),))
    with pytest.raises(
        MissingCalleeError, match="Graph g1 node call calls unknown graph 'gone'"
    ):
        ProjectDocument(graphs=()).add_graph(caller_graph("g1", "gone"))


def test_project_rejects_a_self_call() -> None:
    with pytest.raises(ValidationError, match="Graph call cycle: g1 -> g1"):
        ProjectDocument(graphs=(make_graph("g1", call_node("call", "g1")),))
    with pytest.raises(GraphCallCycleError, match="g1 -> g1"):
        ProjectDocument().add_graph(make_graph("g1", call_node("call", "g1")))


def test_project_rejects_a_two_graph_cycle() -> None:
    a_to_b = caller_graph("a", "b")
    b_to_a = caller_graph("b", "a")
    with pytest.raises(ValidationError, match="a -> b -> a"):
        ProjectDocument(graphs=(a_to_b, b_to_a))
    # The same loop reached one edit at a time: the command is refused, not
    # applied and reported.
    chain = ProjectDocument(graphs=(a_to_b, simple_graph("b")))
    with pytest.raises(GraphCallCycleError, match="a -> b -> a"):
        chain.replace_graph_document("b", make_document(call_node("call", "a")))


def test_project_rejects_a_three_graph_cycle() -> None:
    chain = ProjectDocument(
        graphs=(
            caller_graph("a", "b"),
            make_graph("b", call_node("call", "c")),
            simple_graph("c"),
        )
    )
    with pytest.raises(GraphCallCycleError, match="a -> b -> c -> a"):
        chain.replace_graph_document("c", make_document(call_node("call", "a")))


def test_project_allows_a_diamond_of_calls() -> None:
    project = ProjectDocument(
        graphs=(
            make_graph("a", call_node("call-b", "b"), call_node("call-c", "c")),
            make_graph("b", call_node("call-d", "d")),
            make_graph("c", call_node("call-d", "d")),
            simple_graph("d"),
        )
    )
    assert project.callees_of("a") == ("b", "c")
    assert project.callers_of("d") == (
        CallSite(graph_id="b", node_id="call-d"),
        CallSite(graph_id="c", node_id="call-d"),
    )


def test_project_rejects_a_call_node_at_the_wrong_version() -> None:
    graph = make_graph("g1", call_node("call", "callee", operator_version=2))
    with pytest.raises(ValidationError, match="operator_version 1"):
        ProjectDocument(graphs=(graph, simple_graph("callee")))
    with pytest.raises(ProjectDocumentError, match="must use operator_version 1"):
        ProjectDocument(graphs=(simple_graph("callee"),)).add_graph(graph)


# Mutations


def test_add_graph_leaves_the_original_alone() -> None:
    empty = ProjectDocument()
    with_callee = empty.add_graph(simple_graph("g2"))
    assert [graph.id for graph in empty.graphs] == []
    assert [graph.id for graph in with_callee.graphs] == ["g2"]

    with_caller = with_callee.add_graph(caller_graph("g1", "g2"))
    assert [graph.id for graph in with_callee.graphs] == ["g2"]
    assert [graph.id for graph in with_caller.graphs] == ["g2", "g1"]
    assert with_caller.get_graph("g1").name == "g1"
    # A caller cannot be placed before the Graph it calls exists.
    with pytest.raises(MissingCalleeError):
        empty.add_graph(caller_graph("g3", "g2"))


def test_rename_graph_keeps_everything_else() -> None:
    original = simple_graph("g1", refresh_generations={"g1-leaf": 4})
    project = ProjectDocument(graphs=(original,))
    renamed = project.rename_graph("g1", "  Daily load  ")
    assert renamed.get_graph("g1").name == "Daily load"
    assert renamed.get_graph("g1").document is original.document
    assert renamed.get_graph("g1").refresh_generations == {"g1-leaf": 4}
    assert project.get_graph("g1").name == "g1"
    with pytest.raises(UnknownGraphError):
        renamed.rename_graph("ghost", "Anything")


def test_replace_graph_document_drops_generations_for_removed_nodes() -> None:
    project = ProjectDocument(
        graphs=(simple_graph("g1", refresh_generations={"g1-leaf": 2, "g1-in": 5}),)
    )
    replacement = make_document(input_node("g1-in", "value"), leaf("other"))
    updated = project.replace_graph_document("g1", replacement)
    assert updated.get_graph("g1").refresh_generations == {"g1-in": 5}
    assert project.get_graph("g1").refresh_generations == {"g1-leaf": 2, "g1-in": 5}


def test_replace_graph_document_that_would_close_a_cycle_is_refused() -> None:
    clean = ProjectDocument(
        graphs=(
            caller_graph("a", "b"),
            make_graph("b", call_node("call", "c")),
            simple_graph("c"),
        )
    )
    with pytest.raises(GraphCallCycleError, match="a -> b -> c -> a"):
        clean.replace_graph_document("c", make_document(call_node("call", "a")))
    # The refused edit left nothing behind: the chain still reads as it did.
    assert clean.callees_of("c") == ()
    with pytest.raises(UnknownGraphError):
        clean.replace_graph_document("ghost", make_document(leaf()))


def test_set_refresh_generation_moves_one_number() -> None:
    project = ProjectDocument(graphs=(simple_graph("g1"),))
    bumped = project.set_refresh_generation("g1", "g1-leaf", 1)
    assert bumped.get_graph("g1").refresh_generations == {"g1-leaf": 1}
    assert project.get_graph("g1").refresh_generations == {}
    again = bumped.set_refresh_generation("g1", "g1-leaf", 2)
    assert again.get_graph("g1").refresh_generations == {"g1-leaf": 2}
    assert bumped.get_graph("g1").refresh_generations == {"g1-leaf": 1}

    with pytest.raises(UnknownGraphError):
        project.set_refresh_generation("ghost", "g1-leaf", 1)
    with pytest.raises(ProjectDocumentError, match="has no node 'ghost'"):
        project.set_refresh_generation("g1", "ghost", 1)
    with pytest.raises(ProjectDocumentError, match="must not be negative"):
        project.set_refresh_generation("g1", "g1-leaf", -1)
    with pytest.raises(ProjectDocumentError, match="must be an integer"):
        project.set_refresh_generation("g1", "g1-leaf", True)  # type: ignore[arg-type]


def test_remove_graph_is_refused_while_a_caller_holds_it() -> None:
    project = ProjectDocument(
        graphs=(caller_graph("a", "b", node_id="call-b"), simple_graph("b"))
    )
    with pytest.raises(GraphHasCallersError) as raised:
        project.remove_graph("b")
    assert raised.value.callers == (CallSite(graph_id="a", node_id="call-b"),)
    assert "a/call-b" in str(raised.value)

    # The way out is to drop the call node first, then removal stands.
    caller = project.get_graph("a")
    unhooked = project.replace_graph_document(
        "a",
        make_document(
            input_node("a-in", "value"),
            output_node("a-out", "result"),
        ),
    )
    assert caller.document.nodes[1].kind == CALL_NODE_KIND
    removed = unhooked.remove_graph("b")
    assert [graph.id for graph in removed.graphs] == ["a"]


def test_remove_graph_of_a_caller_loses_nothing_but_its_own_call() -> None:
    project = ProjectDocument(
        graphs=(
            make_graph("a", call_node("call-b", "b")),
            simple_graph("b"),
        )
    )
    removed = project.remove_graph("a")
    assert [graph.id for graph in removed.graphs] == ["b"]


def test_get_graph_and_lookups_answer_for_the_current_document() -> None:
    project = ProjectDocument(
        graphs=(
            make_graph("a", call_node("call-b", "b"), call_node("call-b2", "b")),
            make_graph("b", call_node("call-c", "c")),
            simple_graph("c"),
        )
    )
    assert project.get_graph("b").id == "b"
    with pytest.raises(UnknownGraphError, match="no graph 'ghost'"):
        project.get_graph("ghost")
    # Two calls of one Graph report the callee once, both callers separately.
    assert project.callees_of("a") == ("b",)
    assert project.callers_of("b") == (
        CallSite(graph_id="a", node_id="call-b"),
        CallSite(graph_id="a", node_id="call-b2"),
    )
    assert project.callers_of("a") == ()
    assert project.callees_of("c") == ()
    with pytest.raises(UnknownGraphError):
        project.callers_of("ghost")
    with pytest.raises(UnknownGraphError):
        project.callees_of("ghost")


# call_site_issues


def connected_caller() -> ProjectDocument:
    """A call of a Graph whose interface is ``value`` in, ``result`` out."""
    return ProjectDocument(
        graphs=(
            make_graph(
                "a",
                input_node("a-in", "seed"),
                call_node("call", "b"),
                output_node("a-out", "result"),
                edges=(
                    make_edge(
                        "e-in", "a-in", "call", from_port="value", to_port="value"
                    ),
                    make_edge(
                        "e-out", "call", "a-out", from_port="result", to_port="value"
                    ),
                ),
            ),
            simple_graph("b"),
        )
    )


def test_call_site_issues_is_clean_when_the_interface_matches() -> None:
    issues = call_site_issues(connected_caller())
    assert issues == ()


def test_call_site_issues_reports_an_unknown_input_port_from_an_edge() -> None:
    project = connected_caller()
    broken = project.replace_graph_document(
        "b",
        make_document(
            input_node("b-in", "other"),
            leaf("b-leaf"),
            output_node("b-out", "result"),
        ),
    )
    assert call_site_issues(broken) == (
        CallSiteIssue(
            graph_id="a",
            node_id="call",
            edge_id=None,
            origin_id=None,
            kind="missing_required_input",
            port="other",
        ),
        CallSiteIssue(
            graph_id="a",
            node_id="call",
            edge_id="e-in",
            origin_id=None,
            kind="unknown_input_port",
            port="value",
        ),
    )


def test_call_site_issues_reports_an_unknown_input_port_from_an_origin() -> None:
    project = ProjectDocument(
        graphs=(
            make_graph(
                "a",
                call_node("call", "b"),
                origins=(make_origin("o-1", "call", to_port="gone"),),
            ),
            simple_graph("b"),
        )
    )
    issues = call_site_issues(project)
    assert (
        CallSiteIssue(
            graph_id="a",
            node_id="call",
            edge_id=None,
            origin_id="o-1",
            kind="unknown_input_port",
            port="gone",
        )
        in issues
    )


def test_call_site_issues_reports_an_unknown_output_port() -> None:
    project = connected_caller()
    broken = project.replace_graph_document(
        "b",
        make_document(
            input_node("b-in", "value"),
            leaf("b-leaf"),
            output_node("b-out", "answer"),
        ),
    )
    assert call_site_issues(broken) == (
        CallSiteIssue(
            graph_id="a",
            node_id="call",
            edge_id="e-out",
            origin_id=None,
            kind="unknown_output_port",
            port="result",
        ),
    )


def test_call_site_issues_reports_a_missing_required_input() -> None:
    project = ProjectDocument(
        graphs=(
            make_graph("a", call_node("call", "b")),
            make_graph(
                "b",
                input_node("b-in", "needed"),
                input_node("b-opt", "spare", required=False),
                leaf("b-leaf"),
                output_node("b-out", "result"),
            ),
        )
    )
    assert call_site_issues(project) == (
        CallSiteIssue(
            graph_id="a",
            node_id="call",
            edge_id=None,
            origin_id=None,
            kind="missing_required_input",
            port="needed",
        ),
    )


def test_call_site_issues_ignores_disabled_edges_but_keeps_the_gap() -> None:
    project = ProjectDocument(
        graphs=(
            make_graph(
                "a",
                input_node("a-in", "seed"),
                call_node("call", "b"),
                edges=(
                    make_edge("e-off", "a-in", "call", to_port="nope", enabled=False),
                ),
            ),
            simple_graph("b"),
        )
    )
    assert call_site_issues(project) == (
        CallSiteIssue(
            graph_id="a",
            node_id="call",
            edge_id=None,
            origin_id=None,
            kind="missing_required_input",
            port="value",
        ),
    )


def test_call_site_issues_is_ordered_by_call_site_then_port() -> None:
    project = ProjectDocument(
        graphs=(
            make_graph(
                "z",
                call_node("call-2", "b"),
                call_node("call-1", "b"),
            ),
            make_graph(
                "b", input_node("b-in", "needed"), output_node("b-out", "result")
            ),
        )
    )
    issues = call_site_issues(project)
    assert [
        (issue.graph_id, issue.node_id, issue.kind, issue.port) for issue in issues
    ] == [
        ("z", "call-1", "missing_required_input", "needed"),
        ("z", "call-2", "missing_required_input", "needed"),
    ]
    assert call_site_issues(ProjectDocument(graphs=project.graphs)) == issues


# Storage shape


def test_project_round_trips_through_json() -> None:
    project = ProjectDocument(
        graphs=(
            make_graph(
                "a",
                input_node("a-in", "seed", bound_type=("scalar.integer", 1)),
                call_node("call", "b"),
                output_node("a-out", "result", description="the one"),
                edges=(
                    make_edge(
                        "e-in", "a-in", "call", from_port="value", to_port="value"
                    ),
                    make_edge(
                        "e-out", "call", "a-out", from_port="result", to_port="value"
                    ),
                ),
                refresh_generations={"call": 3},
            ),
            simple_graph("b", name="Callee"),
        )
    )
    dumped = project.model_dump(mode="json")
    assert isinstance(dumped["graphs"][0]["refresh_generations"], dict)
    assert dumped["graphs"][0]["refresh_generations"] == {"call": 3}
    assert dumped["graphs"][0]["document"]["nodes"][1]["kind"] == CALL_NODE_KIND
    restored = ProjectDocument.model_validate(dumped)
    assert restored == project
    assert call_site_issues(restored) == call_site_issues(project)


def test_a_call_node_is_an_ordinary_saved_graph_node() -> None:
    node = SavedGraphNode.model_validate(
        {
            "kind": CALL_NODE_KIND,
            "id": "call",
            "operator_id": "b",
            "operator_version": 1,
            "position": {"x": 0, "y": 0},
        }
    )
    assert node.kind == CALL_NODE_KIND
    assert node.config == {}

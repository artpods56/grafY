from datetime import UTC, datetime
from uuid import UUID

import pytest

from grafy_core.artifacts import ArtifactRef
from grafy_core.domain.materialized_outputs import (
    MaterializedNodeOutputs,
    materializations_for_compatible_nodes,
)
from grafy_core.domain.saved_graphs import (
    GraphPoint,
    SavedGraphConversion,
    SavedGraphDocument,
    SavedGraphEdge,
    SavedGraphInputPlug,
    SavedGraphNode,
    SavedGraphNodeLayout,
    SavedGraphProjection,
)


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")
GRAPH_ID = UUID("00000000-0000-0000-0000-000000000101")


def _node(
    node_id: str,
    *,
    config: dict[str, object] | None = None,
    x: float = 0,
) -> SavedGraphNode:
    return SavedGraphNode(
        kind="builtin",
        id=node_id,
        operator_id="arithmetic.number",
        operator_version=1,
        config=config or {"value": 1},
        position=GraphPoint(x=x, y=0),
    )


def _edge(edge_id: str, source: str, target: str) -> SavedGraphEdge:
    return SavedGraphEdge(
        id=edge_id,
        from_node=source,
        from_port="result",
        to_node=target,
        to_port="value",
    )


def _materialization(node_id: str, revision: int = 1) -> MaterializedNodeOutputs:
    return MaterializedNodeOutputs(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        graph_revision=revision,
        node_id=node_id,
        workflow_run_id=UUID("00000000-0000-0000-0000-000000000201"),
        outputs={
            "result": ArtifactRef(
                artifact_id=UUID("00000000-0000-0000-0000-000000000301"),
                artifact_type="scalar.integer",
                schema_version=1,
            )
        },
        materialized_at=datetime(2026, 8, 8, 10, 0, tzinfo=UTC),
    )


def test_carry_forward_keeps_unchanged_nodes_across_position_edits() -> None:
    previous = SavedGraphDocument(
        nodes=(_node("source"), _node("target", x=120)),
        edges=(_edge("e1", "source", "target"),),
    )
    next_document = SavedGraphDocument(
        nodes=(
            _node("source", x=40).model_copy(
                update={"layout": SavedGraphNodeLayout(width=300, body_height=120)}
            ),
            _node("target", x=200),
        ),
        edges=(
            _edge("renamed-edge", "source", "target").model_copy(
                update={"route_offset": GraphPoint(x=20, y=50)}
            ),
        ),
    )

    carried = materializations_for_compatible_nodes(
        previous_document=previous,
        next_document=next_document,
        previous_materializations=[
            _materialization("source"),
            _materialization("target"),
        ],
        next_revision=2,
    )

    assert {item.node_id for item in carried} == {"source", "target"}
    assert all(item.graph_revision == 2 for item in carried)


@pytest.mark.parametrize("has_source_materialization", [True, False])
def test_carry_forward_drops_changed_node_and_all_descendants(
    has_source_materialization: bool,
) -> None:
    previous = SavedGraphDocument(
        nodes=(
            _node("source"),
            _node("target"),
            _node("downstream"),
            _node("unrelated"),
        ),
        edges=(
            _edge("e1", "source", "target"),
            _edge("e2", "target", "downstream"),
        ),
    )
    next_document = SavedGraphDocument(
        nodes=(
            _node("source", config={"value": 9}),
            _node("target"),
            _node("downstream"),
            _node("unrelated"),
        ),
        edges=(
            _edge("e1", "source", "target"),
            _edge("e2", "target", "downstream"),
        ),
    )

    previous_materializations = [
        _materialization("target"),
        _materialization("downstream"),
        _materialization("unrelated"),
    ]
    if has_source_materialization:
        previous_materializations.append(_materialization("source"))

    carried = materializations_for_compatible_nodes(
        previous_document=previous,
        next_document=next_document,
        previous_materializations=previous_materializations,
        next_revision=2,
    )

    assert [item.node_id for item in carried] == ["unrelated"]
    assert all(item.graph_revision == 1 for item in previous_materializations)


@pytest.mark.parametrize(
    ("previous_config", "next_config"),
    [
        pytest.param({"value": 1}, {"value": True}, id="integer-to-boolean"),
        pytest.param({"value": 1}, {"value": 1.0}, id="integer-to-float"),
        pytest.param(
            {"values": [{"value": 1}]},
            {"values": [{"value": True}]},
            id="nested-integer-to-boolean",
        ),
    ],
)
def test_configuration_json_type_change_invalidates_descendants(
    previous_config: dict[str, object],
    next_config: dict[str, object],
) -> None:
    previous = SavedGraphDocument(
        nodes=(
            _node("source", config=previous_config),
            _node("target"),
            _node("downstream"),
        ),
        edges=(
            _edge("e1", "source", "target"),
            _edge("e2", "target", "downstream"),
        ),
    )
    next_document = SavedGraphDocument(
        nodes=(
            _node("source", config=next_config),
            previous.nodes[1],
            previous.nodes[2],
        ),
        edges=previous.edges,
    )

    carried = materializations_for_compatible_nodes(
        previous_document=previous,
        next_document=next_document,
        previous_materializations=[
            _materialization(node.id) for node in previous.nodes
        ],
        next_revision=2,
    )

    assert carried == []


def test_configuration_key_order_preserves_materializations() -> None:
    previous = SavedGraphDocument(
        nodes=(_node("source", config={"value": 1, "options": {"a": 2, "b": 3}}),),
        edges=(),
    )
    next_document = SavedGraphDocument(
        nodes=(_node("source", config={"options": {"b": 3, "a": 2}, "value": 1}),),
        edges=(),
    )

    carried = materializations_for_compatible_nodes(
        previous_document=previous,
        next_document=next_document,
        previous_materializations=[_materialization("source")],
        next_revision=2,
    )

    assert [item.node_id for item in carried] == ["source"]


@pytest.mark.parametrize(
    "changed_edge",
    [
        pytest.param(None, id="removed"),
        pytest.param(
            _edge("e1", "other", "target"),
            id="rewired",
        ),
        pytest.param(
            _edge("e1", "source", "target").model_copy(update={"enabled": False}),
            id="disabled",
        ),
        pytest.param(
            _edge("e1", "source", "target").model_copy(
                update={"projection": SavedGraphProjection(path=("value",))}
            ),
            id="projection",
        ),
        pytest.param(
            _edge("e1", "source", "target").model_copy(
                update={
                    "conversion_path": (SavedGraphConversion(id="as-text", version=1),)
                }
            ),
            id="conversion",
        ),
        pytest.param(
            _edge("e1", "source", "target").model_copy(
                update={"collection_mode": "map"}
            ),
            id="mapping",
        ),
    ],
)
def test_changed_input_invalidates_target_and_descendants(
    changed_edge: SavedGraphEdge | None,
) -> None:
    nodes = (_node("source"), _node("target"), _node("downstream"), _node("other"))
    downstream_edge = _edge("e2", "target", "downstream")
    previous = SavedGraphDocument(
        nodes=nodes,
        edges=(_edge("e1", "source", "target"), downstream_edge),
    )
    next_edges = [downstream_edge]
    if changed_edge is not None:
        next_edges.append(changed_edge)
    next_document = SavedGraphDocument(nodes=nodes, edges=tuple(next_edges))

    carried = materializations_for_compatible_nodes(
        previous_document=previous,
        next_document=next_document,
        previous_materializations=[_materialization(node.id) for node in nodes],
        next_revision=2,
    )

    assert {item.node_id for item in carried} == {"source", "other"}


def test_disabled_edge_does_not_propagate_invalidation() -> None:
    edges = (
        _edge("e1", "source", "target").model_copy(update={"enabled": False}),
        _edge("e2", "target", "downstream"),
    )
    previous = SavedGraphDocument(
        nodes=(_node("source"), _node("target"), _node("downstream")),
        edges=edges,
    )
    next_document = SavedGraphDocument(
        nodes=(
            _node("source", config={"value": 9}),
            _node("target"),
            _node("downstream"),
        ),
        edges=edges,
    )

    carried = materializations_for_compatible_nodes(
        previous_document=previous,
        next_document=next_document,
        previous_materializations=[
            _materialization(node.id) for node in previous.nodes
        ],
        next_revision=2,
    )

    assert {item.node_id for item in carried} == {"target", "downstream"}


def test_enabling_edge_invalidates_target_and_descendants() -> None:
    nodes = (_node("source"), _node("target"), _node("downstream"))
    edge = _edge("e1", "source", "target")
    downstream_edge = _edge("e2", "target", "downstream")
    previous = SavedGraphDocument(
        nodes=nodes,
        edges=(edge.model_copy(update={"enabled": False}), downstream_edge),
    )
    next_document = SavedGraphDocument(nodes=nodes, edges=(edge, downstream_edge))

    carried = materializations_for_compatible_nodes(
        previous_document=previous,
        next_document=next_document,
        previous_materializations=[_materialization(node.id) for node in nodes],
        next_revision=2,
    )

    assert [item.node_id for item in carried] == ["source"]


def test_reordering_variadic_edges_invalidates_target_and_descendants() -> None:
    nodes = (_node("first"), _node("second"), _node("target"), _node("downstream"))
    first_edge = _edge("e1", "first", "target")
    second_edge = _edge("e2", "second", "target")
    downstream_edge = _edge("e3", "target", "downstream")
    previous = SavedGraphDocument(
        nodes=nodes, edges=(first_edge, second_edge, downstream_edge)
    )
    next_document = SavedGraphDocument(
        nodes=nodes, edges=(second_edge, first_edge, downstream_edge)
    )

    carried = materializations_for_compatible_nodes(
        previous_document=previous,
        next_document=next_document,
        previous_materializations=[_materialization(node.id) for node in nodes],
        next_revision=2,
    )

    assert {item.node_id for item in carried} == {"first", "second"}


def test_explicit_plug_order_controls_freshness_instead_of_edge_order() -> None:
    first_plug = SavedGraphInputPlug(id="first-plug", port="value")
    second_plug = SavedGraphInputPlug(id="second-plug", port="value")
    target = _node("target").model_copy(
        update={"input_plugs": (first_plug, second_plug)}
    )
    nodes = (_node("first"), _node("second"), target, _node("downstream"))
    first_edge = _edge("e1", "first", "target").model_copy(
        update={"to_plug": first_plug.id}
    )
    second_edge = _edge("e2", "second", "target").model_copy(
        update={"to_plug": second_plug.id}
    )
    downstream_edge = _edge("e3", "target", "downstream")
    previous = SavedGraphDocument(
        nodes=nodes, edges=(first_edge, second_edge, downstream_edge)
    )
    reordered_edges = SavedGraphDocument(
        nodes=nodes, edges=(second_edge, first_edge, downstream_edge)
    )
    previous_materializations = [_materialization(node.id) for node in nodes]

    carried = materializations_for_compatible_nodes(
        previous_document=previous,
        next_document=reordered_edges,
        previous_materializations=previous_materializations,
        next_revision=2,
    )

    assert {item.node_id for item in carried} == {node.id for node in nodes}

    reordered_plugs = SavedGraphDocument(
        nodes=(
            nodes[0],
            nodes[1],
            target.model_copy(update={"input_plugs": (second_plug, first_plug)}),
            nodes[3],
        ),
        edges=previous.edges,
    )
    carried = materializations_for_compatible_nodes(
        previous_document=previous,
        next_document=reordered_plugs,
        previous_materializations=previous_materializations,
        next_revision=2,
    )

    assert {item.node_id for item in carried} == {"first", "second"}


def test_cyclic_draft_invalidates_reachable_nodes_without_requiring_execution() -> None:
    nodes = (_node("source"), _node("target"), _node("unrelated"))
    previous = SavedGraphDocument(
        nodes=nodes,
        edges=(_edge("e1", "source", "target"), _edge("e2", "target", "source")),
    )
    next_document = SavedGraphDocument(
        nodes=(_node("source", config={"value": 9}), nodes[1], nodes[2]),
        edges=previous.edges,
    )

    carried = materializations_for_compatible_nodes(
        previous_document=previous,
        next_document=next_document,
        previous_materializations=[_materialization(node.id) for node in nodes],
        next_revision=2,
    )

    assert [item.node_id for item in carried] == ["unrelated"]

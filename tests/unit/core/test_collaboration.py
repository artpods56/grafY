from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.domain.collaboration import (
    AddEdgeCommand,
    AddNodeCommand,
    ApplyGraphCommandBatch,
    ClearNodeArtifactTypeBindingCommand,
    CollaborativeGraphHead,
    DuplicateNodeCommand,
    MoveAnnotationPosition,
    MoveAnnotationsCommand,
    MoveArtifactViewerPosition,
    MoveArtifactViewersCommand,
    MoveNodePosition,
    MoveNodesCommand,
    RemoveEdgesCommand,
    RemoveNodesCommand,
    RenameGraphCommand,
    ReplaceDocumentCommand,
    ReplacePresentationCommand,
    SetNodeArtifactTypeBindingCommand,
    SetNodeInputPlugsCommand,
    UpdateEdgeCommand,
    UpdateNodeConfigurationAndInputPlugsCommand,
    UpdateNodeConfigurationCommand,
    UpdateNodeLayoutCommand,
    UpdateNodeOperatorCommand,
    apply_graph_command,
    command_hmac_digest,
    command_requires_exact_sequence,
    empty_collaborative_document,
    sanitize_document_for_cross_workspace_copy,
)
from grafy_core.domain.errors import CollaborationCommandRejectedError
from grafy_core.domain.saved_graphs import (
    GraphPoint,
    GraphPresentationAnnotation,
    GraphPresentationDocument,
    GraphPresentationLink,
    GraphPresentationViewer,
    SavedGraphAnnotationLayout,
    SavedGraphArtifactTypeBinding,
    SavedGraphDocument,
    SavedGraphEdge,
    SavedGraphInputPlug,
    SavedGraphNode,
    SavedGraphNodeLayout,
)


def _node(
    node_id: str = "n1",
    *,
    x: float = 0,
    y: float = 0,
    config: dict[str, object] | None = None,
) -> SavedGraphNode:
    return SavedGraphNode(
        id=node_id,
        operator_id="example.operator",
        operator_version=1,
        position=GraphPoint(x=x, y=y),
        config=config or {},
    )


def test_apply_rename_and_add_node() -> None:
    document = empty_collaborative_document()
    name, document = apply_graph_command(
        name="Untitled graph",
        document=document,
        command=RenameGraphCommand(name="Named", expected_name="Untitled graph"),
    )
    assert name == "Named"
    name, document = apply_graph_command(
        name=name,
        document=document,
        command=AddNodeCommand(node=_node()),
    )
    assert name == "Named"
    assert document.nodes[0].id == "n1"


def test_apply_batch_adds_dependent_node_and_edge_atomically() -> None:
    source = _node("source")
    original = SavedGraphDocument(nodes=(source,))
    generated = _node("generated", x=200)
    edge = SavedGraphEdge(
        id="source-to-generated",
        from_node="source",
        from_port="result",
        to_node="generated",
        to_port="value",
    )

    name, updated = apply_graph_command(
        name="Graph",
        document=original,
        command=ApplyGraphCommandBatch(
            commands=(
                AddNodeCommand(node=generated),
                AddEdgeCommand(edge=edge),
            )
        ),
    )

    assert name == "Graph"
    assert [node.id for node in updated.nodes] == ["source", "generated"]
    assert [candidate.id for candidate in updated.edges] == ["source-to-generated"]
    assert [node.id for node in original.nodes] == ["source"]
    assert original.edges == ()


def test_apply_batch_failure_does_not_mutate_original_document() -> None:
    source = _node("source")
    original = SavedGraphDocument(nodes=(source,))
    command = ApplyGraphCommandBatch(
        commands=(
            AddNodeCommand(node=_node("generated")),
            AddNodeCommand(node=source),
        )
    )

    with pytest.raises(CollaborationCommandRejectedError) as exc:
        apply_graph_command(name="Graph", document=original, command=command)

    assert exc.value.error_code == "duplicate_node"
    assert [node.id for node in original.nodes] == ["source"]


def test_update_node_operator_preserves_node_and_edge_state() -> None:
    source = _node("source")
    generated = SavedGraphNode(
        id="generated",
        operator_id="generated.node.11111111-1111-1111-1111-111111111111",
        operator_version=1,
        config={"mode": "strict"},
        position=GraphPoint(x=240, y=120),
        layout=SavedGraphNodeLayout(width=420),
        input_plugs=(SavedGraphInputPlug(id="extra-1", port="extra"),),
        artifact_type_bindings=(
            SavedGraphArtifactTypeBinding(
                variable="T",
                artifact_type={"id": "scalar.text", "schema_version": 1},
            ),
        ),
    )
    edge = SavedGraphEdge(
        id="source-generated",
        from_node=source.id,
        from_port="result",
        to_node=generated.id,
        to_port="texts",
    )
    original = SavedGraphDocument(nodes=(source, generated), edges=(edge,))

    _, updated = apply_graph_command(
        name="Graph",
        document=original,
        command=UpdateNodeOperatorCommand(
            node_id=generated.id,
            operator_id=generated.operator_id,
            operator_version=2,
            expected_operator_id=generated.operator_id,
            expected_operator_version=1,
        ),
    )

    promoted = next(node for node in updated.nodes if node.id == generated.id)
    assert promoted.operator_version == 2
    assert promoted.operator_id == generated.operator_id
    assert promoted.id == generated.id
    assert promoted.config == generated.config
    assert promoted.position == generated.position
    assert promoted.layout == generated.layout
    assert promoted.input_plugs == generated.input_plugs
    assert promoted.artifact_type_bindings == generated.artifact_type_bindings
    assert updated.edges == original.edges
    assert original.nodes[1].operator_version == 1


def test_update_node_operator_is_conflict_aware_and_batch_compatible() -> None:
    generated = SavedGraphNode(
        id="generated",
        operator_id="generated.node.11111111-1111-1111-1111-111111111111",
        operator_version=1,
        position=GraphPoint(x=0, y=0),
    )
    original = SavedGraphDocument(nodes=(generated,))
    update = UpdateNodeOperatorCommand(
        node_id=generated.id,
        operator_id=generated.operator_id,
        operator_version=2,
        expected_operator_id=generated.operator_id,
        expected_operator_version=1,
    )

    _, updated = apply_graph_command(
        name="Graph",
        document=original,
        command=ApplyGraphCommandBatch(commands=(update,)),
    )
    assert updated.nodes[0].operator_version == 2

    with pytest.raises(CollaborationCommandRejectedError) as exc:
        apply_graph_command(
            name="Graph",
            document=updated,
            command=update,
        )
    assert exc.value.error_code == "field_conflict"


def test_apply_batch_rejects_nested_batches_and_requires_exact_sequence() -> None:
    primitive = AddNodeCommand(node=_node("generated"))
    batch = ApplyGraphCommandBatch(commands=(primitive,))

    assert command_requires_exact_sequence(batch)
    with pytest.raises(ValidationError):
        ApplyGraphCommandBatch.model_validate(
            {
                "commands": [
                    {
                        "kind": "apply_batch",
                        "commands": [primitive.model_dump(mode="json")],
                    }
                ]
            }
        )


def test_apply_rejects_duplicate_node() -> None:
    node = _node()
    document = SavedGraphDocument(nodes=(node,))
    with pytest.raises(CollaborationCommandRejectedError) as exc:
        apply_graph_command(
            name="Graph",
            document=document,
            command=AddNodeCommand(node=node),
        )
    assert exc.value.error_code == "duplicate_node"


def test_rename_field_conflict() -> None:
    with pytest.raises(CollaborationCommandRejectedError) as exc:
        apply_graph_command(
            name="Current",
            document=SavedGraphDocument(),
            command=RenameGraphCommand(name="Next", expected_name="Stale"),
        )
    assert exc.value.error_code == "field_conflict"


def test_move_remove_update_edge_and_plugs() -> None:
    source = _node("source", x=1, y=2)
    target = SavedGraphNode(
        id="target",
        operator_id="example.operator",
        operator_version=1,
        position=GraphPoint(x=10, y=20),
        input_plugs=(SavedGraphInputPlug(id="plug-a", port="value"),),
        artifact_type_bindings=(
            SavedGraphArtifactTypeBinding(
                variable="T",
                artifact_type=ArtifactTypeKey(id="image.raster", schema_version=1),
            ),
        ),
    )
    edge = SavedGraphEdge(
        id="e1",
        from_node="source",
        from_port="result",
        to_node="target",
        to_port="value",
        to_plug="plug-a",
        enabled=True,
    )
    document = SavedGraphDocument(nodes=(source, target), edges=(edge,))

    _, document = apply_graph_command(
        name="Graph",
        document=document,
        command=MoveNodesCommand(
            positions=(MoveNodePosition(node_id="source", x=5, y=6),)
        ),
    )
    assert document.nodes[0].position == GraphPoint(x=5, y=6)

    _, document = apply_graph_command(
        name="Graph",
        document=document,
        command=UpdateNodeConfigurationCommand(
            node_id="source",
            field="text",
            value="hello",
            expected_value=None,
        ),
    )
    assert document.nodes[0].config_dict()["text"] == "hello"

    layout = SavedGraphNodeLayout(width=400, body_height=200)
    _, document = apply_graph_command(
        name="Graph",
        document=document,
        command=UpdateNodeLayoutCommand(
            node_id="source",
            layout=layout,
            expected_layout=None,
        ),
    )
    assert document.nodes[0].layout == layout

    _, document = apply_graph_command(
        name="Graph",
        document=document,
        command=SetNodeInputPlugsCommand(
            node_id="target",
            input_plugs=(
                SavedGraphInputPlug(id="plug-a", port="value"),
                SavedGraphInputPlug(id="plug-b", port="value"),
            ),
            expected_plug_ids=("plug-a",),
        ),
    )
    assert [plug.id for plug in document.nodes[1].input_plugs] == ["plug-a", "plug-b"]

    binding = SavedGraphArtifactTypeBinding(
        variable="T",
        artifact_type=ArtifactTypeKey(id="text.value", schema_version=1),
    )
    _, document = apply_graph_command(
        name="Graph",
        document=document,
        command=SetNodeArtifactTypeBindingCommand(
            node_id="target",
            binding=binding,
            expected_binding=SavedGraphArtifactTypeBinding(
                variable="T",
                artifact_type=ArtifactTypeKey(id="image.raster", schema_version=1),
            ),
        ),
    )
    assert document.nodes[1].artifact_type_bindings[0] == binding

    _, document = apply_graph_command(
        name="Graph",
        document=document,
        command=ClearNodeArtifactTypeBindingCommand(
            node_id="target",
            variable="T",
            expected_binding=binding,
        ),
    )
    assert document.nodes[1].artifact_type_bindings == ()

    updated_edge = edge.model_copy(update={"enabled": False})
    _, document = apply_graph_command(
        name="Graph",
        document=document,
        command=UpdateEdgeCommand(edge=updated_edge, expected_edge=edge),
    )
    assert document.edges[0].enabled is False

    _, document = apply_graph_command(
        name="Graph",
        document=document,
        command=DuplicateNodeCommand(
            source_node_id="source",
            node=_node("source-copy", x=40, y=40),
        ),
    )
    assert any(node.id == "source-copy" for node in document.nodes)

    _, document = apply_graph_command(
        name="Graph",
        document=document,
        command=RemoveEdgesCommand(edge_ids=("e1", "missing")),
    )
    assert document.edges == ()

    _, document = apply_graph_command(
        name="Graph",
        document=document,
        command=RemoveNodesCommand(node_ids=("source", "missing")),
    )
    assert [node.id for node in document.nodes] == ["target", "source-copy"]


def test_add_edge_and_sanitize_copy_document() -> None:
    node = _node(
        config={
            "uploads": [{"upload_key": "abc", "filename": "a.png", "byte_size": 1}],
            "nested": {"artifact_id": str(uuid4()), "keep": True},
        }
    )
    document = SavedGraphDocument(nodes=(node,))
    edge = SavedGraphEdge(
        id="e1",
        from_node="n1",
        from_port="result",
        to_node="n1",
        to_port="value",
    )
    _, with_edge = apply_graph_command(
        name="Graph",
        document=document,
        command=AddEdgeCommand(edge=edge),
    )
    assert with_edge.edges[0].id == "e1"

    sanitized = sanitize_document_for_cross_workspace_copy(document)
    assert "uploads" not in sanitized.nodes[0].config_dict()
    assert sanitized.nodes[0].config_dict()["nested"] == {"keep": True}

    module_document = SavedGraphDocument(
        nodes=(
            SavedGraphNode(
                id="mod",
                operator_id="graph.module." + str(uuid4()),
                operator_version=1,
                position=GraphPoint(x=0, y=0),
            ),
        )
    )
    with pytest.raises(CollaborationCommandRejectedError) as exc:
        sanitize_document_for_cross_workspace_copy(module_document)
    assert exc.value.error_code == "foreign_module_reference"


def test_command_hmac_digest_is_stable_and_keyed() -> None:
    command = ReplaceDocumentCommand(name="A", document=SavedGraphDocument())
    workspace_id = UUID("00000000-0000-0000-0000-000000000001")
    graph_id = UUID("00000000-0000-0000-0000-000000000002")
    actor_id = UUID("00000000-0000-0000-0000-000000000003")
    room_epoch = uuid4()
    first = command_hmac_digest(
        b"key-a",
        key_version=1,
        workspace_id=workspace_id,
        graph_id=graph_id,
        actor_user_id=actor_id,
        room_epoch=room_epoch,
        observed_sequence=0,
        command=command,
    )
    second = command_hmac_digest(
        b"key-a",
        key_version=1,
        workspace_id=workspace_id,
        graph_id=graph_id,
        actor_user_id=actor_id,
        room_epoch=room_epoch,
        observed_sequence=0,
        command=command,
    )
    other_key = command_hmac_digest(
        b"key-b",
        key_version=1,
        workspace_id=workspace_id,
        graph_id=graph_id,
        actor_user_id=actor_id,
        room_epoch=room_epoch,
        observed_sequence=0,
        command=command,
    )
    assert first == second
    assert first != other_key


def test_existing_graph_head_starts_at_sequence_zero() -> None:
    head = CollaborativeGraphHead.for_existing_saved_graph(
        workspace_id=uuid4(),
        graph_id=uuid4(),
        name="Legacy",
        document=SavedGraphDocument(),
        checkpoint_revision=4,
    )
    assert head.collaboration_sequence == 0
    assert head.checkpoint_sequence == 0
    assert head.checkpoint_revision == 4
    assert head.is_fully_checkpointed


def test_schema_builder_compound_updates_config_plugs_and_drops_orphan_edges() -> None:
    builder = SavedGraphNode(
        id="builder",
        operator_id="schema.builder",
        operator_version=1,
        position=GraphPoint(x=0, y=0),
        config={
            "fields": [
                {"id": "title", "name": "title", "kind": "string"},
                {"id": "body", "name": "body", "kind": "object"},
            ]
        },
        input_plugs=(
            SavedGraphInputPlug(id="title", port="schemas"),
            SavedGraphInputPlug(id="body", port="schemas"),
        ),
    )
    source = _node("source")
    keep_edge = SavedGraphEdge(
        id="e-keep",
        from_node="source",
        from_port="result",
        to_node="builder",
        to_port="schemas",
        to_plug="title",
    )
    drop_edge = SavedGraphEdge(
        id="e-drop",
        from_node="source",
        from_port="result",
        to_node="builder",
        to_port="schemas",
        to_plug="body",
    )
    document = SavedGraphDocument(
        nodes=(source, builder),
        edges=(keep_edge, drop_edge),
    )
    next_config = {
        "fields": [
            {"id": "title", "name": "title", "kind": "string"},
            {"id": "extra", "name": "extra", "kind": "object"},
        ]
    }
    next_plugs = (
        SavedGraphInputPlug(id="title", port="schemas"),
        SavedGraphInputPlug(id="extra", port="schemas"),
    )

    _, updated = apply_graph_command(
        name="Graph",
        document=document,
        command=UpdateNodeConfigurationAndInputPlugsCommand(
            node_id="builder",
            config=next_config,
            input_plugs=next_plugs,
            expected_config=builder.config_dict(),
            expected_plug_ids=("title", "body"),
        ),
    )

    assert updated.nodes[1].config_dict() == next_config
    assert [plug.id for plug in updated.nodes[1].input_plugs] == ["title", "extra"]
    assert [edge.id for edge in updated.edges] == ["e-keep"]


def test_schema_builder_compound_rejects_partial_field_conflict() -> None:
    builder = SavedGraphNode(
        id="builder",
        operator_id="schema.builder",
        operator_version=1,
        position=GraphPoint(x=0, y=0),
        config={"fields": [{"id": "a", "name": "a", "kind": "string"}]},
        input_plugs=(SavedGraphInputPlug(id="a", port="schemas"),),
    )
    document = SavedGraphDocument(nodes=(builder,))
    with pytest.raises(CollaborationCommandRejectedError) as exc:
        apply_graph_command(
            name="Graph",
            document=document,
            command=UpdateNodeConfigurationAndInputPlugsCommand(
                node_id="builder",
                config={"fields": []},
                input_plugs=(),
                expected_config={"fields": [{"id": "stale", "name": "stale", "kind": "string"}]},
                expected_plug_ids=("a",),
            ),
        )
    assert exc.value.error_code == "field_conflict"
    assert document.nodes[0].config_dict()["fields"][0]["id"] == "a"
    assert document.nodes[0].input_plugs[0].id == "a"


def test_saved_graph_document_migrates_to_v4_with_empty_presentation() -> None:
    document = SavedGraphDocument.model_validate(
        {"schema_version": 3, "nodes": [], "edges": []}
    )
    assert document.schema_version == 4
    assert document.presentation.viewers == ()
    assert document.presentation.links == ()
    assert document.presentation.bindings == ()
    assert document.presentation.annotations == ()


def test_replace_and_move_artifact_viewers() -> None:
    document = SavedGraphDocument(nodes=(_node("n1"),))
    presentation = GraphPresentationDocument(
        viewers=(
            GraphPresentationViewer(
                id="artifact-viewer-1",
                position=GraphPoint(x=10, y=20),
            ),
        ),
        links=(
            GraphPresentationLink(
                id="artifact-viewer-edge-1",
                source_node_id="n1",
                source_port_name="out",
                target_viewer_id="artifact-viewer-1",
            ),
        ),
        annotations=(
            GraphPresentationAnnotation(
                id="annotation-1",
                kind="text",
                position=GraphPoint(x=1, y=2),
                layout=SavedGraphAnnotationLayout(width=200, height=100),
                text="hello",
                color="#B45309",
            ),
        ),
    )
    replace = ReplacePresentationCommand(presentation=presentation)
    assert command_requires_exact_sequence(replace)
    _, with_presentation = apply_graph_command(
        name="Graph",
        document=document,
        command=replace,
    )
    assert len(with_presentation.presentation.viewers) == 1
    assert with_presentation.presentation.annotations[0].text == "hello"
    _, moved = apply_graph_command(
        name="Graph",
        document=with_presentation,
        command=MoveArtifactViewersCommand(
            positions=(
                MoveArtifactViewerPosition(
                    viewer_id="artifact-viewer-1",
                    x=99,
                    y=11,
                ),
            ),
        ),
    )
    assert moved.presentation.viewers[0].position == GraphPoint(x=99, y=11)
    assert moved.presentation.links[0].source_node_id == "n1"
    assert moved.presentation.annotations[0].text == "hello"


def test_replace_and_move_annotations() -> None:
    document = SavedGraphDocument()
    presentation = GraphPresentationDocument(
        annotations=(
            GraphPresentationAnnotation(
                id="annotation-1",
                kind="rectangle",
                position=GraphPoint(x=10, y=20),
                layout=SavedGraphAnnotationLayout(width=120, height=80),
                color="sky",
            ),
            GraphPresentationAnnotation(
                id="annotation-2",
                kind="ellipse",
                position=GraphPoint(x=40, y=60),
                layout=SavedGraphAnnotationLayout(width=160, height=160),
            ),
        ),
    )
    _, with_presentation = apply_graph_command(
        name="Graph",
        document=document,
        command=ReplacePresentationCommand(presentation=presentation),
    )
    _, moved = apply_graph_command(
        name="Graph",
        document=with_presentation,
        command=MoveAnnotationsCommand(
            positions=(
                MoveAnnotationPosition(
                    annotation_id="annotation-1",
                    x=77,
                    y=88,
                ),
            ),
        ),
    )
    assert moved.presentation.annotations[0].position == GraphPoint(x=77, y=88)
    assert moved.presentation.annotations[1].position == GraphPoint(x=40, y=60)


def test_remove_nodes_prunes_presentation_links() -> None:
    document = SavedGraphDocument(
        nodes=(_node("n1"), _node("n2")),
        presentation=GraphPresentationDocument(
            viewers=(
                GraphPresentationViewer(
                    id="artifact-viewer-1",
                    position=GraphPoint(x=0, y=0),
                ),
            ),
            links=(
                GraphPresentationLink(
                    id="artifact-viewer-edge-1",
                    source_node_id="n1",
                    source_port_name="out",
                    target_viewer_id="artifact-viewer-1",
                ),
            ),
        ),
    )
    _, pruned = apply_graph_command(
        name="Graph",
        document=document,
        command=RemoveNodesCommand(node_ids=("n1",)),
    )
    assert pruned.presentation.viewers[0].id == "artifact-viewer-1"
    assert pruned.presentation.links == ()

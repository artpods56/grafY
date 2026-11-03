"""Project command batches and the collaborative head that carries them (ADR 0020).

Two layers live here: the per-graph commands that edit one Graph's canvas, and
the project-level commands that add, rename and remove Graphs, place a call
node, refresh a node, or point a per-graph command at one Graph. No I/O, no
clocks, no sleeps: a batch is a fold over document values.
"""

from datetime import datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest

from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
from grafy_core.domain.collaboration import (
    AddCallNodeCommand,
    AddEdgeCommand,
    AddGraphCommand,
    AddNodeCommand,
    AddOriginCommand,
    ClearNodeArtifactTypeBindingCommand,
    DuplicateNodeCommand,
    GraphCommand,
    InGraphCommand,
    MoveAnnotationPosition,
    MoveAnnotationsCommand,
    MoveArtifactViewerPosition,
    MoveArtifactViewersCommand,
    MoveNodePosition,
    MoveNodesCommand,
    PROJECT_COMMAND_ADAPTER,
    ProjectCommand,
    ProjectHead,
    RefreshNodeCommand,
    RemoveEdgesCommand,
    RemoveGraphCommand,
    RemoveNodesCommand,
    RemoveOriginsCommand,
    RenameGraphCommand,
    RenameProjectCommand,
    ReplaceDocumentCommand,
    ReplacePresentationCommand,
    SetNodeArtifactTypeBindingCommand,
    SetNodeInputPlugsCommand,
    UpdateEdgeCommand,
    UpdateNodeConfigurationAndInputPlugsCommand,
    UpdateNodeConfigurationCommand,
    UpdateNodeLayoutCommand,
    UpdateOriginCommand,
    apply_graph_command,
    apply_project_commands,
    canonical_batch_payload,
    command_hmac_digest,
    command_requires_exact_sequence,
    empty_project_document,
    sanitize_document_for_cross_workspace_copy,
    sanitize_project_for_cross_workspace_copy,
)
from grafy_core.domain.errors import CollaborationCommandRejectedError
from grafy_core.kernel.project import (
    CALL_NODE_KIND,
    CALL_NODE_OPERATOR_VERSION,
    CallSite,
    GraphDefinition,
    ProjectDocument,
)
from grafy_core.domain.graph_documents import (
    GraphPoint,
    GraphPresentationAnnotation,
    GraphPresentationDocument,
    GraphPresentationLink,
    GraphPresentationViewer,
    GraphAnnotationLayout,
    GraphArtifactTypeBinding,
    GraphDocument,
    GraphEdge,
    GraphInputPlug,
    GraphNode,
    GraphNodeLayout,
    GraphOrigin,
)


def _node(
    node_id: str = "n1",
    *,
    x: float = 0,
    y: float = 0,
    config: dict[str, object] | None = None,
) -> GraphNode:
    return GraphNode(
        kind="builtin",
        id=node_id,
        operator_id="example.operator",
        operator_version=1,
        position=GraphPoint(x=x, y=y),
        config=config or {},
    )


def test_apply_add_node_to_an_empty_document() -> None:
    document = apply_graph_command(
        document=GraphDocument(),
        command=AddNodeCommand(node=_node()),
    )

    assert document.nodes[0].id == "n1"


def test_apply_rejects_duplicate_node() -> None:
    node = _node()
    document = GraphDocument(nodes=(node,))
    with pytest.raises(CollaborationCommandRejectedError) as exc:
        apply_graph_command(
            document=document,
            command=AddNodeCommand(node=node),
        )
    assert exc.value.error_code == "duplicate_node"


def test_move_remove_update_edge_and_plugs() -> None:
    source = _node("source", x=1, y=2)
    target = GraphNode(
        kind="builtin",
        id="target",
        operator_id="example.operator",
        operator_version=1,
        position=GraphPoint(x=10, y=20),
        input_plugs=(GraphInputPlug(id="plug-a", port="value"),),
        artifact_type_bindings=(
            GraphArtifactTypeBinding(
                variable="T",
                artifact_type=ArtifactTypeKey(id="image.raster", schema_version=1),
            ),
        ),
    )
    edge = GraphEdge(
        id="e1",
        from_node="source",
        from_port="result",
        to_node="target",
        to_port="value",
        to_plug="plug-a",
        enabled=True,
    )
    document = GraphDocument(nodes=(source, target), edges=(edge,))

    document = apply_graph_command(
        document=document,
        command=MoveNodesCommand(
            positions=(MoveNodePosition(node_id="source", x=5, y=6),)
        ),
    )
    assert document.nodes[0].position == GraphPoint(x=5, y=6)

    document = apply_graph_command(
        document=document,
        command=UpdateNodeConfigurationCommand(
            node_id="source",
            field="text",
            value="hello",
            expected_value=None,
        ),
    )
    assert document.nodes[0].config_dict()["text"] == "hello"

    layout = GraphNodeLayout(width=400, body_height=200)
    document = apply_graph_command(
        document=document,
        command=UpdateNodeLayoutCommand(
            node_id="source",
            layout=layout,
            expected_layout=None,
        ),
    )
    assert document.nodes[0].layout == layout

    document = apply_graph_command(
        document=document,
        command=SetNodeInputPlugsCommand(
            node_id="target",
            input_plugs=(
                GraphInputPlug(id="plug-a", port="value"),
                GraphInputPlug(id="plug-b", port="value"),
            ),
            expected_plug_ids=("plug-a",),
        ),
    )
    assert [plug.id for plug in document.nodes[1].input_plugs] == ["plug-a", "plug-b"]

    binding = GraphArtifactTypeBinding(
        variable="T",
        artifact_type=ArtifactTypeKey(id="text.value", schema_version=1),
    )
    document = apply_graph_command(
        document=document,
        command=SetNodeArtifactTypeBindingCommand(
            node_id="target",
            binding=binding,
            expected_binding=GraphArtifactTypeBinding(
                variable="T",
                artifact_type=ArtifactTypeKey(id="image.raster", schema_version=1),
            ),
        ),
    )
    assert document.nodes[1].artifact_type_bindings[0] == binding

    document = apply_graph_command(
        document=document,
        command=ClearNodeArtifactTypeBindingCommand(
            node_id="target",
            variable="T",
            expected_binding=binding,
        ),
    )
    assert document.nodes[1].artifact_type_bindings == ()

    updated_edge = edge.model_copy(update={"enabled": False})
    document = apply_graph_command(
        document=document,
        command=UpdateEdgeCommand(edge=updated_edge, expected_edge=edge),
    )
    assert document.edges[0].enabled is False

    document = apply_graph_command(
        document=document,
        command=DuplicateNodeCommand(
            source_node_id="source",
            node=_node("source-copy", x=40, y=40),
        ),
    )
    assert any(node.id == "source-copy" for node in document.nodes)

    document = apply_graph_command(
        document=document,
        command=RemoveEdgesCommand(edge_ids=("e1", "missing")),
    )
    assert document.edges == ()

    document = apply_graph_command(
        document=document,
        command=RemoveNodesCommand(node_ids=("source", "missing")),
    )
    assert [node.id for node in document.nodes] == ["target", "source-copy"]


def test_replacing_input_plugs_drops_wiring_to_removed_plugs() -> None:
    source = _node("source")
    collect = GraphNode(
        kind="builtin",
        id="collect",
        operator_id="test.sequence.collect",
        operator_version=1,
        position=GraphPoint(x=10, y=20),
        input_plugs=(
            GraphInputPlug(id="plug-a", port="items"),
            GraphInputPlug(id="plug-b", port="items"),
            GraphInputPlug(id="plug-c", port="items"),
        ),
    )
    edge = GraphEdge(
        id="e1",
        from_node="source",
        from_port="result",
        to_node="collect",
        to_port="items",
        to_plug="plug-b",
        enabled=True,
    )
    kept_origin = _origin("o-kept", to_node="collect").model_copy(
        update={"to_port": "items", "to_plug": "plug-a"}
    )
    dropped_origin = _origin("o-dropped", to_node="collect").model_copy(
        update={"to_port": "items", "to_plug": "plug-c"}
    )
    document = GraphDocument(
        nodes=(source, collect),
        edges=(edge,),
        origins=(kept_origin, dropped_origin),
    )

    updated = apply_graph_command(
        document=document,
        command=SetNodeInputPlugsCommand(
            node_id="collect",
            input_plugs=(GraphInputPlug(id="plug-a", port="items"),),
            expected_plug_ids=("plug-a", "plug-b", "plug-c"),
        ),
    )

    assert [plug.id for plug in updated.nodes[1].input_plugs] == ["plug-a"]
    assert updated.edges == ()
    assert updated.origins == (kept_origin,)


def _origin(origin_id: str = "o1", *, to_node: str = "n1") -> GraphOrigin:
    return GraphOrigin(
        id=origin_id,
        to_node=to_node,
        to_port="value",
        value=ArtifactRef(
            artifact_id=UUID("00000000-0000-0000-0000-000000000501"),
            artifact_type="image.raster",
            schema_version=1,
        ),
    )


def test_add_update_and_remove_origins() -> None:
    document = GraphDocument(nodes=(_node("n1"),))
    origin = _origin()

    with_origin = apply_graph_command(
        document=document,
        command=AddOriginCommand(origin=origin),
    )
    assert with_origin.origins == (origin,)

    with pytest.raises(CollaborationCommandRejectedError) as duplicate:
        apply_graph_command(
            document=with_origin,
            command=AddOriginCommand(origin=origin),
        )
    assert duplicate.value.error_code == "duplicate_origin"

    with pytest.raises(CollaborationCommandRejectedError) as conflict:
        apply_graph_command(
            document=with_origin,
            command=UpdateOriginCommand(
                origin=origin.model_copy(update={"to_node": "n1"}),
                expected_origin=origin.model_copy(update={"to_port": "absent"}),
            ),
        )
    assert conflict.value.error_code == "field_conflict"

    repointed = origin.model_copy(
        update={"value": origin.value.model_copy(update={"content_hash": "b" * 64})}
    )
    updated = apply_graph_command(
        document=with_origin,
        command=UpdateOriginCommand(origin=repointed, expected_origin=origin),
    )
    assert updated.origins == (repointed,)

    removed = apply_graph_command(
        document=updated,
        command=RemoveOriginsCommand(origin_ids=("o1", "missing")),
    )
    assert removed.origins == ()


def test_remove_nodes_prunes_origins_targeting_removed_nodes() -> None:
    document = GraphDocument(
        nodes=(_node("n1"), _node("n2")),
        origins=(_origin(), _origin("o2", to_node="n2")),
    )

    remaining = apply_graph_command(
        document=document,
        command=RemoveNodesCommand(node_ids=("n1",)),
    )

    assert [origin.id for origin in remaining.origins] == ["o2"]


def test_plug_edit_prunes_origins_on_removed_plugs() -> None:
    target = GraphNode(
        kind="builtin",
        id="target",
        operator_id="example.operator",
        operator_version=1,
        position=GraphPoint(x=0, y=0),
        input_plugs=(GraphInputPlug(id="plug-a", port="value"),),
    )
    origin = _origin(to_node="target").model_copy(update={"to_plug": "plug-a"})
    document = GraphDocument(nodes=(target,), origins=(origin,))

    remaining = apply_graph_command(
        document=document,
        command=UpdateNodeConfigurationAndInputPlugsCommand(
            node_id="target",
            config={},
            input_plugs=(),
            expected_config={},
            expected_plug_ids=("plug-a",),
        ),
    )

    assert remaining.origins == ()


def test_add_edge_and_sanitize_copy_document() -> None:
    node = _node(
        config={
            "uploads": [{"upload_key": "abc", "filename": "a.png", "byte_size": 1}],
            "nested": {"artifact_id": str(uuid4()), "keep": True},
        }
    )
    document = GraphDocument(nodes=(node,))
    edge = GraphEdge(
        id="e1",
        from_node="n1",
        from_port="result",
        to_node="n1",
        to_port="value",
    )
    with_edge = apply_graph_command(
        document=document,
        command=AddEdgeCommand(edge=edge),
    )
    assert with_edge.edges[0].id == "e1"

    sanitized = sanitize_document_for_cross_workspace_copy(document)
    assert "uploads" not in sanitized.nodes[0].config_dict()
    assert sanitized.nodes[0].config_dict()["nested"] == {"keep": True}


def test_cross_workspace_copy_keeps_an_unsatisfied_artifact_card_reference() -> None:
    reference = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=ArtifactTypeKey("table.data", 1),
    )
    document = GraphDocument(
        presentation=GraphPresentationDocument(
            viewers=(
                GraphPresentationViewer(
                    id="artifact-viewer-card",
                    position=GraphPoint(x=1, y=2),
                    artifact_ref=reference,
                ),
            ),
        ),
    )

    copied = sanitize_document_for_cross_workspace_copy(document)

    assert copied.presentation.viewers[0].artifact_ref == reference


def test_command_hmac_digest_covers_the_batch_and_its_order() -> None:
    workspace_id = UUID("00000000-0000-0000-0000-000000000001")
    project_id = UUID("00000000-0000-0000-0000-000000000002")
    actor_id = UUID("00000000-0000-0000-0000-000000000003")
    room_epoch = uuid4()
    add_graph = AddGraphCommand(graph_id="second", name="Second")
    rename = RenameProjectCommand(name="Weekly", expected_name="Nightly")

    def sign(
        key: bytes,
        commands: list[ProjectCommand],
    ) -> bytes:
        return command_hmac_digest(
            key,
            key_version=1,
            workspace_id=workspace_id,
            project_id=project_id,
            actor_user_id=actor_id,
            room_epoch=room_epoch,
            observed_sequence=0,
            commands=commands,
        )

    assert sign(b"key-a", [rename, add_graph]) == sign(b"key-a", [rename, add_graph])
    assert sign(b"key-a", [rename, add_graph]) != sign(b"key-b", [rename, add_graph])
    # The same commands in the other order are a different batch, so they sign
    # differently: a replay cannot reorder what the client meant.
    assert sign(b"key-a", [rename, add_graph]) != sign(b"key-a", [add_graph, rename])
    assert canonical_batch_payload([rename, add_graph]) != canonical_batch_payload(
        [add_graph, rename]
    )


def test_head_advances_one_sequence_per_accepted_batch() -> None:
    head = ProjectHead.for_existing_project(
        workspace_id=uuid4(),
        project_id=uuid4(),
        name="Legacy",
        document=empty_project_document("main"),
        checkpoint_revision=4,
    )
    assert head.collaboration_sequence == 0
    assert head.checkpoint_sequence == 0
    assert head.checkpoint_revision == 4
    assert head.is_fully_checkpointed

    name, document = apply_project_commands(
        name=head.name,
        document=head.document,
        commands=[
            RenameProjectCommand(name="Weekly", expected_name="Legacy"),
            AddGraphCommand(graph_id="second", name="Second"),
        ],
    )
    head.apply_accepted_batch(name=name, document=document)

    # Two commands, one batch: the sequence moves exactly one step.
    assert head.collaboration_sequence == 1
    assert head.name == "Weekly"
    assert len(head.document.graphs) == 2
    assert not head.is_fully_checkpointed

    head.record_checkpoint(sequence=1, revision=5)
    assert head.checkpoint_sequence == 1
    assert head.checkpoint_revision == 5
    assert head.is_fully_checkpointed


def test_head_invariants_hold_for_a_project() -> None:
    def head(**overrides: object) -> ProjectHead:
        values: dict[str, object] = {
            "workspace_id": uuid4(),
            "project_id": uuid4(),
            "room_epoch": uuid4(),
            "collaboration_sequence": 3,
            "checkpoint_sequence": 2,
            "checkpoint_revision": 1,
            "name": "Nightly",
            "document": empty_project_document("main"),
        }
        values.update(overrides)
        return ProjectHead(**values)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Checkpoint sequence cannot exceed"):
        head(checkpoint_sequence=4)

    with pytest.raises(ValueError, match="Checkpoint revision must be at least 1"):
        head(checkpoint_revision=0)

    with pytest.raises(ValueError, match="Project name must not be blank"):
        head(name="   ")

    with pytest.raises(ValueError, match="timestamp must be timezone-aware"):
        head(updated_at=datetime(2026, 7, 14, 8, 30))

    with pytest.raises(ValueError, match="must equal the current collaboration"):
        head().record_checkpoint(sequence=4, revision=2)

    with pytest.raises(ValueError, match="timestamp must be timezone-aware"):
        head().apply_accepted_batch(
            name="Weekly",
            document=empty_project_document("main"),
            updated_at=datetime(2026, 7, 14, 8, 30),
        )


def test_schema_builder_compound_updates_config_plugs_and_drops_orphan_edges() -> None:
    builder = GraphNode(
        kind="builtin",
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
            GraphInputPlug(id="title", port="schemas"),
            GraphInputPlug(id="body", port="schemas"),
        ),
    )
    source = _node("source")
    keep_edge = GraphEdge(
        id="e-keep",
        from_node="source",
        from_port="result",
        to_node="builder",
        to_port="schemas",
        to_plug="title",
    )
    drop_edge = GraphEdge(
        id="e-drop",
        from_node="source",
        from_port="result",
        to_node="builder",
        to_port="schemas",
        to_plug="body",
    )
    document = GraphDocument(
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
        GraphInputPlug(id="title", port="schemas"),
        GraphInputPlug(id="extra", port="schemas"),
    )

    updated = apply_graph_command(
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
    builder = GraphNode(
        kind="builtin",
        id="builder",
        operator_id="schema.builder",
        operator_version=1,
        position=GraphPoint(x=0, y=0),
        config={"fields": [{"id": "a", "name": "a", "kind": "string"}]},
        input_plugs=(GraphInputPlug(id="a", port="schemas"),),
    )
    document = GraphDocument(nodes=(builder,))
    with pytest.raises(CollaborationCommandRejectedError) as exc:
        apply_graph_command(
            document=document,
            command=UpdateNodeConfigurationAndInputPlugsCommand(
                node_id="builder",
                config={"fields": []},
                input_plugs=(),
                expected_config={
                    "fields": [{"id": "stale", "name": "stale", "kind": "string"}]
                },
                expected_plug_ids=("a",),
            ),
        )
    assert exc.value.error_code == "field_conflict"
    assert document.nodes[0].config_dict()["fields"][0]["id"] == "a"
    assert document.nodes[0].input_plugs[0].id == "a"


def test_replace_and_move_artifact_viewers() -> None:
    document = GraphDocument(nodes=(_node("n1"),))
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
                layout=GraphAnnotationLayout(width=200, height=100),
                text="hello",
                color="#B45309",
            ),
        ),
    )
    replace = ReplacePresentationCommand(presentation=presentation)
    assert command_requires_exact_sequence(
        [InGraphCommand(graph_id="main", command=replace)]
    )
    assert not command_requires_exact_sequence(
        [InGraphCommand(graph_id="main", command=AddNodeCommand(node=_node()))]
    )
    with_presentation = apply_graph_command(
        document=document,
        command=replace,
    )
    assert len(with_presentation.presentation.viewers) == 1
    assert with_presentation.presentation.annotations[0].text == "hello"
    moved = apply_graph_command(
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
    document = GraphDocument()
    presentation = GraphPresentationDocument(
        annotations=(
            GraphPresentationAnnotation(
                id="annotation-1",
                kind="rectangle",
                position=GraphPoint(x=10, y=20),
                layout=GraphAnnotationLayout(width=120, height=80),
                color="#0369A1",
            ),
            GraphPresentationAnnotation(
                id="annotation-2",
                kind="ellipse",
                position=GraphPoint(x=40, y=60),
                layout=GraphAnnotationLayout(width=160, height=160),
            ),
        ),
    )
    with_presentation = apply_graph_command(
        document=document,
        command=ReplacePresentationCommand(presentation=presentation),
    )
    moved = apply_graph_command(
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
    document = GraphDocument(
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
    pruned = apply_graph_command(
        document=document,
        command=RemoveNodesCommand(node_ids=("n1",)),
    )
    assert pruned.presentation.viewers[0].id == "artifact-viewer-1"
    assert pruned.presentation.links == ()


def test_duplicate_node_rejects_existing_target_id() -> None:
    document = GraphDocument(nodes=(_node("source"), _node("copy")))
    with pytest.raises(
        CollaborationCommandRejectedError,
        match="Graph command adds duplicate node copy",
    ) as exc:
        apply_graph_command(
            document=document,
            command=DuplicateNodeCommand(
                source_node_id="source",
                node=_node("copy", x=40, y=40),
            ),
        )
    assert exc.value.error_code == "duplicate_node"


def test_update_node_configuration_rejects_stale_field_value() -> None:
    document = GraphDocument(nodes=(_node("n1", config={"text": "actual"}),))
    with pytest.raises(
        CollaborationCommandRejectedError,
        match=r"Configuration field 'text' on node n1 changed",
    ) as exc:
        apply_graph_command(
            document=document,
            command=UpdateNodeConfigurationCommand(
                node_id="n1",
                field="text",
                value="next",
                expected_value="stale",
            ),
        )
    assert exc.value.error_code == "field_conflict"


def test_update_node_layout_rejects_stale_layout() -> None:
    current = GraphNodeLayout(width=400, body_height=200)
    stale = GraphNodeLayout(width=300, body_height=200)
    document = GraphDocument(
        nodes=(_node("n1").model_copy(update={"layout": current}),)
    )
    with pytest.raises(
        CollaborationCommandRejectedError,
        match="Layout on node n1 changed",
    ) as exc:
        apply_graph_command(
            document=document,
            command=UpdateNodeLayoutCommand(
                node_id="n1",
                layout=GraphNodeLayout(width=500, body_height=200),
                expected_layout=stale,
            ),
        )
    assert exc.value.error_code == "field_conflict"


def test_set_node_input_plugs_rejects_stale_plug_ids() -> None:
    node = _node("n1").model_copy(
        update={"input_plugs": (GraphInputPlug(id="plug-a", port="value"),)}
    )
    document = GraphDocument(nodes=(node,))
    with pytest.raises(
        CollaborationCommandRejectedError,
        match="Input plugs on node n1 changed",
    ) as exc:
        apply_graph_command(
            document=document,
            command=SetNodeInputPlugsCommand(
                node_id="n1",
                input_plugs=(GraphInputPlug(id="plug-a", port="value"),),
                expected_plug_ids=("plug-stale",),
            ),
        )
    assert exc.value.error_code == "field_conflict"


def test_update_node_configuration_and_input_plugs_rejects_stale_plug_ids() -> None:
    node = _node("n1", config={"text": "keep"}).model_copy(
        update={"input_plugs": (GraphInputPlug(id="plug-a", port="value"),)}
    )
    document = GraphDocument(nodes=(node,))
    with pytest.raises(
        CollaborationCommandRejectedError,
        match="Input plugs on node n1 changed",
    ) as exc:
        apply_graph_command(
            document=document,
            command=UpdateNodeConfigurationAndInputPlugsCommand(
                node_id="n1",
                config={"text": "next"},
                input_plugs=(GraphInputPlug(id="plug-a", port="value"),),
                expected_config={"text": "keep"},
                expected_plug_ids=("plug-stale",),
            ),
        )
    assert exc.value.error_code == "field_conflict"
    assert document.nodes[0].config_dict()["text"] == "keep"


def test_set_node_artifact_type_binding_rejects_stale_binding() -> None:
    bound = GraphArtifactTypeBinding(
        variable="T",
        artifact_type=ArtifactTypeKey(id="image.raster", schema_version=1),
    )
    node = _node("n1").model_copy(update={"artifact_type_bindings": (bound,)})
    document = GraphDocument(nodes=(node,))
    with pytest.raises(
        CollaborationCommandRejectedError,
        match=r"Artifact type binding 'T' on node n1 changed",
    ) as exc:
        apply_graph_command(
            document=document,
            command=SetNodeArtifactTypeBindingCommand(
                node_id="n1",
                binding=GraphArtifactTypeBinding(
                    variable="T",
                    artifact_type=ArtifactTypeKey(id="text.value", schema_version=1),
                ),
                expected_binding=GraphArtifactTypeBinding(
                    variable="T",
                    artifact_type=ArtifactTypeKey(id="text.value", schema_version=1),
                ),
            ),
        )
    assert exc.value.error_code == "field_conflict"
    assert document.nodes[0].artifact_type_bindings == (bound,)


def test_clear_node_artifact_type_binding_rejects_stale_binding() -> None:
    document = GraphDocument(nodes=(_node("n1"),))
    with pytest.raises(
        CollaborationCommandRejectedError,
        match=r"Artifact type binding 'T' on node n1 changed",
    ) as exc:
        apply_graph_command(
            document=document,
            command=ClearNodeArtifactTypeBindingCommand(
                node_id="n1",
                variable="T",
                expected_binding=GraphArtifactTypeBinding(
                    variable="T",
                    artifact_type=ArtifactTypeKey(id="image.raster", schema_version=1),
                ),
            ),
        )
    assert exc.value.error_code == "field_conflict"


def test_add_edge_rejects_duplicate_edge_id() -> None:
    edge = GraphEdge(
        id="e1",
        from_node="source",
        from_port="result",
        to_node="target",
        to_port="value",
        to_plug="plug-a",
        enabled=True,
    )
    document = GraphDocument(
        nodes=(
            _node("source"),
            _node("target").model_copy(
                update={"input_plugs": (GraphInputPlug(id="plug-a", port="value"),)}
            ),
        ),
        edges=(edge,),
    )
    with pytest.raises(
        CollaborationCommandRejectedError,
        match="Graph command adds duplicate edge e1",
    ) as exc:
        apply_graph_command(
            document=document,
            command=AddEdgeCommand(edge=edge),
        )
    assert exc.value.error_code == "duplicate_edge"
    assert document.edges == (edge,)


def test_update_edge_rejects_stale_edge() -> None:
    edge = GraphEdge(
        id="e1",
        from_node="source",
        from_port="result",
        to_node="target",
        to_port="value",
        to_plug="plug-a",
        enabled=True,
    )
    document = GraphDocument(
        nodes=(
            _node("source"),
            _node("target").model_copy(
                update={"input_plugs": (GraphInputPlug(id="plug-a", port="value"),)}
            ),
        ),
        edges=(edge,),
    )
    with pytest.raises(
        CollaborationCommandRejectedError,
        match="Edge e1 changed",
    ) as exc:
        apply_graph_command(
            document=document,
            command=UpdateEdgeCommand(
                edge=edge,
                expected_edge=edge.model_copy(update={"enabled": False}),
            ),
        )
    assert exc.value.error_code == "field_conflict"
    assert document.edges == (edge,)


def test_unknown_command_rejects_unsupported_kind() -> None:
    # A command shape this build does not know about falls through every
    # `isinstance` branch in `_apply_graph_command`.
    unknown = cast(GraphCommand, SimpleNamespace(kind="remove_layers"))
    with pytest.raises(
        CollaborationCommandRejectedError,
        match="Unsupported graph command kind",
    ) as exc:
        apply_graph_command(
            document=GraphDocument(),
            command=unknown,
        )
    assert exc.value.error_code == "unsupported_command"
    assert "remove_layers" in str(exc.value)


# Project-level commands: the layer that owns Graphs, names, calls and refresh.


def _project(*graph_ids: str) -> ProjectDocument:
    return ProjectDocument(
        graphs=tuple(
            GraphDefinition(id=graph_id, name=graph_id, document=GraphDocument())
            for graph_id in graph_ids
        )
    )


def _call_node(node_id: str, callee_graph_id: str) -> GraphNode:
    return GraphNode(
        kind=CALL_NODE_KIND,
        id=node_id,
        operator_id=callee_graph_id,
        operator_version=CALL_NODE_OPERATOR_VERSION,
        position=GraphPoint(x=0, y=0),
    )


def _reject(
    *,
    name: str = "Nightly",
    document: ProjectDocument,
    commands: list[ProjectCommand],
) -> CollaborationCommandRejectedError:
    with pytest.raises(CollaborationCommandRejectedError) as exc:
        apply_project_commands(name=name, document=document, commands=commands)
    return exc.value


def test_a_new_project_opens_on_one_empty_graph() -> None:
    document = empty_project_document("main")

    assert [graph.name for graph in document.graphs] == ["Main"]
    assert document.graphs[0].document == GraphDocument()


def test_rename_project_command_is_compare_and_set() -> None:
    name, document = apply_project_commands(
        name="Nightly",
        document=_project("main"),
        commands=[RenameProjectCommand(name="  Weekly  ", expected_name="Nightly")],
    )

    assert name == "Weekly"
    assert document == _project("main")

    rejection = _reject(
        name="Nightly",
        document=_project("main"),
        commands=[RenameProjectCommand(name="Weekly", expected_name="Stale")],
    )
    assert rejection.error_code == "field_conflict"
    assert "index 0" in str(rejection)


def test_add_graph_command_appends_a_named_graph() -> None:
    document = _project("main")

    _, updated = apply_project_commands(
        name="Nightly",
        document=document,
        commands=[AddGraphCommand(graph_id="prepare", name="Prepare")],
    )

    assert [graph.id for graph in updated.graphs] == ["main", "prepare"]
    assert updated.get_graph("prepare").document == GraphDocument()

    assert (
        _reject(
            document=document,
            commands=[AddGraphCommand(graph_id="main", name="Another")],
        ).error_code
        == "duplicate_graph"
    )


def test_add_graph_command_carries_a_document_into_the_project() -> None:
    _, updated = apply_project_commands(
        name="Nightly",
        document=_project("main"),
        commands=[
            AddGraphCommand(
                graph_id="prepare",
                name="Prepare",
                document=GraphDocument(nodes=(_node("source"),)),
            )
        ],
    )

    assert [node.id for node in updated.get_graph("prepare").document.nodes] == [
        "source"
    ]


def test_add_graph_command_rejects_a_document_the_project_cannot_hold() -> None:
    # A call node whose callee is not in the Project cannot be copied in.
    rejection = _reject(
        document=_project("main"),
        commands=[
            AddGraphCommand(
                graph_id="prepare",
                name="Prepare",
                document=GraphDocument(nodes=(_call_node("call", "missing"),)),
            )
        ],
    )

    assert rejection.error_code == "missing_callee"


def test_rename_graph_command_moves_one_graph_name() -> None:
    _, updated = apply_project_commands(
        name="Nightly",
        document=_project("main", "prepare"),
        commands=[
            RenameGraphCommand(
                graph_id="prepare", name=" Prep ", expected_name="prepare"
            )
        ],
    )

    assert [graph.name for graph in updated.graphs] == ["main", "Prep"]

    assert (
        _reject(
            document=_project("main", "prepare"),
            commands=[
                RenameGraphCommand(graph_id="prepare", name="Prep", expected_name="Old")
            ],
        ).error_code
        == "field_conflict"
    )
    assert (
        _reject(
            document=_project("main", "prepare"),
            commands=[
                RenameGraphCommand(
                    graph_id="prepare", name="main", expected_name="prepare"
                )
            ],
        ).error_code
        == "duplicate_graph"
    )
    assert (
        _reject(
            document=_project("main"),
            commands=[
                RenameGraphCommand(graph_id="gone", name="Prep", expected_name="gone")
            ],
        ).error_code
        == "unknown_graph"
    )


def test_remove_graph_command_drops_a_graph_and_keeps_the_rest() -> None:
    _, updated = apply_project_commands(
        name="Nightly",
        document=_project("main", "prepare"),
        commands=[RemoveGraphCommand(graph_id="prepare")],
    )

    assert [graph.id for graph in updated.graphs] == ["main"]

    assert (
        _reject(
            document=_project("main"),
            commands=[RemoveGraphCommand(graph_id="gone")],
        ).error_code
        == "unknown_graph"
    )


def test_add_call_node_command_places_a_sibling_graph() -> None:
    _, updated = apply_project_commands(
        name="Nightly",
        document=_project("main", "prepare"),
        commands=[
            AddCallNodeCommand(
                graph_id="main",
                node_id="call-prepare",
                callee_graph_id="prepare",
                position=GraphPoint(x=40, y=90),
            )
        ],
    )

    call_node = updated.get_graph("main").document.nodes[0]
    assert call_node.kind == CALL_NODE_KIND
    assert call_node.operator_id == "prepare"
    assert call_node.operator_version == CALL_NODE_OPERATOR_VERSION
    assert call_node.position == GraphPoint(x=40, y=90)
    assert updated.callees_of("main") == ("prepare",)


def test_add_call_node_command_rejects_a_missing_callee_and_a_stranger_graph() -> None:
    assert (
        _reject(
            document=_project("main"),
            commands=[
                AddCallNodeCommand(
                    graph_id="main",
                    node_id="call",
                    callee_graph_id="gone",
                    position=GraphPoint(x=0, y=0),
                )
            ],
        ).error_code
        == "missing_callee"
    )
    assert (
        _reject(
            document=_project("main"),
            commands=[
                AddCallNodeCommand(
                    graph_id="gone",
                    node_id="call",
                    callee_graph_id="main",
                    position=GraphPoint(x=0, y=0),
                )
            ],
        ).error_code
        == "unknown_graph"
    )
    assert (
        _reject(
            document=_project("main", "prepare"),
            commands=[
                InGraphCommand(
                    graph_id="main",
                    command=AddNodeCommand(node=_node("call")),
                ),
                AddCallNodeCommand(
                    graph_id="main",
                    node_id="call",
                    callee_graph_id="prepare",
                    position=GraphPoint(x=0, y=0),
                ),
            ],
        ).error_code
        == "duplicate_node"
    )


def test_add_call_node_command_rejects_a_call_cycle() -> None:
    _, with_caller = apply_project_commands(
        name="Nightly",
        document=_project("main", "prepare"),
        commands=[
            AddCallNodeCommand(
                graph_id="main",
                node_id="call-prepare",
                callee_graph_id="prepare",
                position=GraphPoint(x=0, y=0),
            )
        ],
    )

    rejection = _reject(
        document=with_caller,
        commands=[
            AddCallNodeCommand(
                graph_id="prepare",
                node_id="call-main",
                callee_graph_id="main",
                position=GraphPoint(x=0, y=0),
            )
        ],
    )

    assert rejection.error_code == "graph_call_cycle"
    assert with_caller.callers_of("prepare") == (
        CallSite(graph_id="main", node_id="call-prepare"),
    )


def test_remove_graph_command_is_refused_while_a_caller_remains() -> None:
    _, with_caller = apply_project_commands(
        name="Nightly",
        document=_project("main", "prepare"),
        commands=[
            AddCallNodeCommand(
                graph_id="main",
                node_id="call-prepare",
                callee_graph_id="prepare",
                position=GraphPoint(x=0, y=0),
            )
        ],
    )

    rejection = _reject(
        document=with_caller,
        commands=[RemoveGraphCommand(graph_id="prepare")],
    )

    assert rejection.error_code == "graph_has_callers"
    assert "main/call-prepare" in str(rejection)

    # The way out is the way in: drop the call node, then the Graph goes.
    _, without_caller = apply_project_commands(
        name="Nightly",
        document=with_caller,
        commands=[
            InGraphCommand(
                graph_id="main",
                command=RemoveNodesCommand(node_ids=("call-prepare",)),
            ),
            RemoveGraphCommand(graph_id="prepare"),
        ],
    )
    assert [graph.id for graph in without_caller.graphs] == ["main"]


def test_refresh_node_command_advances_the_generation_once() -> None:
    _, started = apply_project_commands(
        name="Nightly",
        document=_project("main"),
        commands=[
            InGraphCommand(
                graph_id="main",
                command=AddNodeCommand(node=_node("noisy")),
            )
        ],
    )

    _, refreshed = apply_project_commands(
        name="Nightly",
        document=started,
        commands=[
            RefreshNodeCommand(graph_id="main", node_id="noisy", expected_generation=0)
        ],
    )

    assert refreshed.get_graph("main").refresh_generations["noisy"] == 1

    assert (
        _reject(
            document=refreshed,
            commands=[
                RefreshNodeCommand(
                    graph_id="main", node_id="noisy", expected_generation=0
                )
            ],
        ).error_code
        == "field_conflict"
    )
    assert (
        _reject(
            document=started,
            commands=[
                RefreshNodeCommand(
                    graph_id="main", node_id="gone", expected_generation=0
                )
            ],
        ).error_code
        == "missing_node"
    )
    assert (
        _reject(
            document=started,
            commands=[
                RefreshNodeCommand(
                    graph_id="gone", node_id="noisy", expected_generation=0
                )
            ],
        ).error_code
        == "unknown_graph"
    )


def test_a_call_node_is_never_refreshable() -> None:
    _, with_caller = apply_project_commands(
        name="Nightly",
        document=_project("main", "prepare"),
        commands=[
            AddCallNodeCommand(
                graph_id="main",
                node_id="call-prepare",
                callee_graph_id="prepare",
                position=GraphPoint(x=0, y=0),
            )
        ],
    )

    assert (
        _reject(
            document=with_caller,
            commands=[
                RefreshNodeCommand(
                    graph_id="main",
                    node_id="call-prepare",
                    expected_generation=0,
                )
            ],
        ).error_code
        == "not_refreshable"
    )


def test_in_graph_command_edits_one_graph_and_leaves_the_other() -> None:
    _, updated = apply_project_commands(
        name="Nightly",
        document=_project("main", "prepare"),
        commands=[
            InGraphCommand(
                graph_id="main",
                command=AddNodeCommand(node=_node("source")),
            )
        ],
    )

    assert [node.id for node in updated.get_graph("main").document.nodes] == ["source"]
    assert updated.get_graph("prepare").document == GraphDocument()

    assert (
        _reject(
            document=_project("main"),
            commands=[
                InGraphCommand(
                    graph_id="gone",
                    command=AddNodeCommand(node=_node("source")),
                )
            ],
        ).error_code
        == "unknown_graph"
    )
    # A rejection inside the Graph reaches the caller with its own code.
    assert (
        _reject(
            document=_project("main", "prepare"),
            commands=[
                InGraphCommand(
                    graph_id="main",
                    command=AddNodeCommand(node=_node("source")),
                ),
                InGraphCommand(
                    graph_id="main",
                    command=AddNodeCommand(node=_node("source")),
                ),
            ],
        ).error_code
        == "duplicate_node"
    )


def test_in_graph_command_replace_document_carries_the_whole_canvas() -> None:
    replacement = GraphDocument(nodes=(_node("only"),))

    _, updated = apply_project_commands(
        name="Nightly",
        document=_project("main", "prepare"),
        commands=[
            InGraphCommand(
                graph_id="prepare",
                command=AddNodeCommand(node=_node("stale")),
            ),
            InGraphCommand(
                graph_id="prepare",
                command=ReplaceDocumentCommand(document=replacement),
            ),
        ],
    )

    assert updated.get_graph("prepare").document == replacement
    assert updated.get_graph("prepare").refresh_generations == {}


def test_a_batch_that_fails_halfway_changes_nothing() -> None:
    document = _project("main", "prepare")

    rejection = _reject(
        name="Nightly",
        document=document,
        commands=[
            RenameProjectCommand(name="Weekly", expected_name="Nightly"),
            AddGraphCommand(graph_id="build", name="Build"),
            RemoveGraphCommand(graph_id="gone"),
        ],
    )

    assert rejection.error_code == "unknown_graph"
    assert "index 2" in str(rejection)
    # The caller's own values are untouched, so it can resend from the index.
    assert document == _project("main", "prepare")


def test_an_empty_batch_is_a_caller_bug_not_a_rejection() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        apply_project_commands(
            name="Nightly",
            document=_project("main"),
            commands=[],
        )


def test_unsupported_project_command_kind_is_rejected() -> None:
    unknown = cast(ProjectCommand, SimpleNamespace(kind="remove_layers"))

    with pytest.raises(CollaborationCommandRejectedError) as exc:
        apply_project_commands(
            name="Nightly",
            document=_project("main"),
            commands=[unknown],
        )

    assert exc.value.error_code == "unsupported_command"
    assert "remove_layers" in str(exc.value)


def test_project_commands_round_trip_through_their_discriminated_adapter() -> None:
    commands: list[ProjectCommand] = [
        RenameProjectCommand(name="Weekly", expected_name="Nightly"),
        AddGraphCommand(graph_id="prepare", name="Prepare"),
        RenameGraphCommand(graph_id="prepare", name="Prep", expected_name="Prepare"),
        AddCallNodeCommand(
            graph_id="main",
            node_id="call-prepare",
            callee_graph_id="prepare",
            position=GraphPoint(x=1, y=2),
        ),
        RefreshNodeCommand(graph_id="main", node_id="noisy", expected_generation=2),
        InGraphCommand(
            graph_id="main",
            command=AddNodeCommand(node=_node("source")),
        ),
        RemoveGraphCommand(graph_id="prepare"),
    ]

    payload = [command.model_dump(mode="json") for command in commands]

    for entry, command in zip(payload, commands, strict=True):
        assert PROJECT_COMMAND_ADAPTER.validate_python(entry) == command
    assert {entry["kind"] for entry in payload} == {
        "rename_project",
        "add_graph",
        "rename_graph",
        "add_call_node",
        "refresh_node",
        "in_graph",
        "remove_graph",
    }


def test_sanitize_project_strips_every_graph_of_a_project() -> None:
    document = _project("main", "prepare")
    _, filled = apply_project_commands(
        name="Nightly",
        document=document,
        commands=[
            InGraphCommand(
                graph_id="main",
                command=AddNodeCommand(
                    node=_node("reader", config={"upload_key": "k", "keep": 1})
                ),
            ),
            InGraphCommand(
                graph_id="prepare",
                command=AddNodeCommand(
                    node=_node("reader", config={"upload_key": "other", "keep": 2})
                ),
            ),
        ],
    )

    copied = sanitize_project_for_cross_workspace_copy(filled)

    assert [graph.document.nodes[0].config_dict() for graph in copied.graphs] == [
        {"keep": 1},
        {"keep": 2},
    ]
    assert copied.get_graph("main").name == filled.get_graph("main").name

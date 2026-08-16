"""Collaborative graph head, commands, receipts, and checkpoints."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
import hmac
import json
from typing import Annotated, ClassVar, Literal, Self, TypeAlias, cast
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
)

from grafy_core.domain.errors import CollaborationCommandRejectedError
from grafy_core.domain.modules import GRAPH_MODULE_OPERATOR_PREFIX
from grafy_core.domain.saved_graphs import (
    GraphIdentifier,
    GraphPoint,
    GraphPresentationAnnotation,
    GraphPresentationDocument,
    GraphPresentationViewer,
    SavedGraphArtifactTypeBinding,
    SavedGraphDocument,
    SavedGraphEdge,
    SavedGraphInputPlug,
    SavedGraphNode,
    SavedGraphNodeLayout,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CollaborationActorKind(StrEnum):
    USER = "user"
    SYSTEM = "system"


class CommandReceiptOutcome(StrEnum):
    ACCEPTED = "accepted"
    IDEMPOTENT_REPLAY = "idempotent_replay"


class GraphCommandKind(StrEnum):
    RENAME_GRAPH = "rename_graph"
    ADD_NODE = "add_node"
    DUPLICATE_NODE = "duplicate_node"
    REMOVE_NODES = "remove_nodes"
    MOVE_NODES = "move_nodes"
    UPDATE_NODE_OPERATOR = "update_node_operator"
    UPDATE_NODE_CONFIGURATION = "update_node_configuration"
    UPDATE_NODE_LAYOUT = "update_node_layout"
    SET_NODE_INPUT_PLUGS = "set_node_input_plugs"
    # Schema Builder field edits must use this one accept_command transaction
    # (config fields + owned input plugs). Do not split into separate primitive
    # update_node_configuration and set_node_input_plugs commands.
    UPDATE_NODE_CONFIGURATION_AND_INPUT_PLUGS = (
        "update_node_configuration_and_input_plugs"
    )
    SET_NODE_ARTIFACT_TYPE_BINDING = "set_node_artifact_type_binding"
    CLEAR_NODE_ARTIFACT_TYPE_BINDING = "clear_node_artifact_type_binding"
    ADD_EDGE = "add_edge"
    UPDATE_EDGE = "update_edge"
    REMOVE_EDGES = "remove_edges"
    REPLACE_DOCUMENT = "replace_document"
    REPLACE_PRESENTATION = "replace_presentation"
    MOVE_ARTIFACT_VIEWERS = "move_artifact_viewers"
    MOVE_ANNOTATIONS = "move_annotations"
    APPLY_BATCH = "apply_batch"


class CollaborationValue(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


def _validated_graph_name(value: str) -> str:
    name = value.strip()
    if name == "":
        raise ValueError("Graph name must not be blank")
    if len(name) > 160:
        raise ValueError("Graph name must be at most 160 characters")
    return name


class RenameGraphCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.RENAME_GRAPH] = GraphCommandKind.RENAME_GRAPH
    name: str
    expected_name: str

    @field_validator("name", "expected_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validated_graph_name(value)


class AddNodeCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.ADD_NODE] = GraphCommandKind.ADD_NODE
    node: SavedGraphNode


class DuplicateNodeCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.DUPLICATE_NODE] = GraphCommandKind.DUPLICATE_NODE
    source_node_id: str
    node: SavedGraphNode


class RemoveNodesCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.REMOVE_NODES] = GraphCommandKind.REMOVE_NODES
    node_ids: tuple[str, ...] = Field(min_length=1)


class MoveNodePosition(CollaborationValue):
    node_id: str
    x: float
    y: float


class MoveNodesCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.MOVE_NODES] = GraphCommandKind.MOVE_NODES
    positions: tuple[MoveNodePosition, ...] = Field(min_length=1)


class UpdateNodeOperatorCommand(CollaborationValue):
    """Compare-and-swap one node's immutable operator release identity."""

    kind: Literal[GraphCommandKind.UPDATE_NODE_OPERATOR] = (
        GraphCommandKind.UPDATE_NODE_OPERATOR
    )
    node_id: GraphIdentifier
    operator_id: GraphIdentifier
    operator_version: int = Field(ge=1)
    expected_operator_id: GraphIdentifier
    expected_operator_version: int = Field(ge=1)


class UpdateNodeConfigurationCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.UPDATE_NODE_CONFIGURATION] = (
        GraphCommandKind.UPDATE_NODE_CONFIGURATION
    )
    node_id: str
    field: str
    value: object
    expected_value: object | None = None


class UpdateNodeLayoutCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.UPDATE_NODE_LAYOUT] = (
        GraphCommandKind.UPDATE_NODE_LAYOUT
    )
    node_id: str
    layout: SavedGraphNodeLayout | None
    expected_layout: SavedGraphNodeLayout | None = None


class SetNodeInputPlugsCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.SET_NODE_INPUT_PLUGS] = (
        GraphCommandKind.SET_NODE_INPUT_PLUGS
    )
    node_id: str
    input_plugs: tuple[SavedGraphInputPlug, ...]
    expected_plug_ids: tuple[str, ...]


class UpdateNodeConfigurationAndInputPlugsCommand(CollaborationValue):
    """Atomic Schema Builder (and similar) config+plug compound gesture."""

    kind: Literal[GraphCommandKind.UPDATE_NODE_CONFIGURATION_AND_INPUT_PLUGS] = (
        GraphCommandKind.UPDATE_NODE_CONFIGURATION_AND_INPUT_PLUGS
    )
    node_id: str
    config: dict[str, object]
    input_plugs: tuple[SavedGraphInputPlug, ...]
    expected_config: dict[str, object]
    expected_plug_ids: tuple[str, ...]


class SetNodeArtifactTypeBindingCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.SET_NODE_ARTIFACT_TYPE_BINDING] = (
        GraphCommandKind.SET_NODE_ARTIFACT_TYPE_BINDING
    )
    node_id: str
    binding: SavedGraphArtifactTypeBinding
    expected_binding: SavedGraphArtifactTypeBinding | None = None


class ClearNodeArtifactTypeBindingCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.CLEAR_NODE_ARTIFACT_TYPE_BINDING] = (
        GraphCommandKind.CLEAR_NODE_ARTIFACT_TYPE_BINDING
    )
    node_id: str
    variable: str
    expected_binding: SavedGraphArtifactTypeBinding


class AddEdgeCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.ADD_EDGE] = GraphCommandKind.ADD_EDGE
    edge: SavedGraphEdge


class UpdateEdgeCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.UPDATE_EDGE] = GraphCommandKind.UPDATE_EDGE
    edge: SavedGraphEdge
    expected_edge: SavedGraphEdge


class RemoveEdgesCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.REMOVE_EDGES] = GraphCommandKind.REMOVE_EDGES
    edge_ids: tuple[str, ...] = Field(min_length=1)


class ReplaceDocumentCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.REPLACE_DOCUMENT] = GraphCommandKind.REPLACE_DOCUMENT
    name: str
    document: SavedGraphDocument

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validated_graph_name(value)


class ReplacePresentationCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.REPLACE_PRESENTATION] = (
        GraphCommandKind.REPLACE_PRESENTATION
    )
    presentation: GraphPresentationDocument


class MoveArtifactViewerPosition(CollaborationValue):
    viewer_id: str
    x: float
    y: float


class MoveArtifactViewersCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.MOVE_ARTIFACT_VIEWERS] = (
        GraphCommandKind.MOVE_ARTIFACT_VIEWERS
    )
    positions: tuple[MoveArtifactViewerPosition, ...] = Field(min_length=1)


class MoveAnnotationPosition(CollaborationValue):
    annotation_id: str
    x: float
    y: float


class MoveAnnotationsCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.MOVE_ANNOTATIONS] = (
        GraphCommandKind.MOVE_ANNOTATIONS
    )
    positions: tuple[MoveAnnotationPosition, ...] = Field(min_length=1)


PrimitiveGraphCommand: TypeAlias = (
    RenameGraphCommand
    | AddNodeCommand
    | DuplicateNodeCommand
    | RemoveNodesCommand
    | MoveNodesCommand
    | UpdateNodeOperatorCommand
    | UpdateNodeConfigurationCommand
    | UpdateNodeLayoutCommand
    | SetNodeInputPlugsCommand
    | UpdateNodeConfigurationAndInputPlugsCommand
    | SetNodeArtifactTypeBindingCommand
    | ClearNodeArtifactTypeBindingCommand
    | AddEdgeCommand
    | UpdateEdgeCommand
    | RemoveEdgesCommand
    | ReplaceDocumentCommand
    | ReplacePresentationCommand
    | MoveArtifactViewersCommand
    | MoveAnnotationsCommand
)

PrimitiveGraphCommandPayload: TypeAlias = Annotated[
    PrimitiveGraphCommand,
    Field(discriminator="kind"),
]


class ApplyGraphCommandBatch(CollaborationValue):
    """Primitive graph commands accepted as one collaborative transaction."""

    kind: Literal[GraphCommandKind.APPLY_BATCH] = GraphCommandKind.APPLY_BATCH
    commands: tuple[PrimitiveGraphCommandPayload, ...] = Field(min_length=1)


GraphCommand: TypeAlias = Annotated[
    PrimitiveGraphCommand | ApplyGraphCommandBatch,
    Field(discriminator="kind"),
]

GRAPH_COMMAND_ADAPTER: TypeAdapter[GraphCommand] = TypeAdapter(GraphCommand)


def empty_collaborative_document() -> SavedGraphDocument:
    return SavedGraphDocument()


def canonical_command_payload(command: GraphCommand) -> bytes:
    dumped = command.model_dump(mode="json")
    return json.dumps(dumped, separators=(",", ":"), sort_keys=True).encode("utf-8")


def command_hmac_digest(
    key: bytes,
    *,
    key_version: int,
    workspace_id: UUID,
    graph_id: UUID,
    actor_user_id: UUID | None,
    room_epoch: UUID,
    observed_sequence: int,
    command: GraphCommand,
) -> bytes:
    del key_version
    envelope = {
        "actor_user_id": None if actor_user_id is None else str(actor_user_id),
        "command": command.model_dump(mode="json"),
        "graph_id": str(graph_id),
        "observed_sequence": observed_sequence,
        "room_epoch": str(room_epoch),
        "workspace_id": str(workspace_id),
    }
    payload = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hmac.new(key, payload, sha256).digest()


def command_requires_exact_sequence(command: GraphCommand) -> bool:
    return isinstance(
        command,
        (
            ApplyGraphCommandBatch,
            ReplaceDocumentCommand,
            ReplacePresentationCommand,
        ),
    )


def _json_equal(left: object, right: object) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right,
        sort_keys=True,
        separators=(",", ":"),
    )


def _model_json(value: BaseModel | None) -> object:
    if value is None:
        return None
    return value.model_dump(mode="json")


def _field_conflict(message: str) -> CollaborationCommandRejectedError:
    return CollaborationCommandRejectedError(code="field_conflict", message=message)


def _node_or_raise(document: SavedGraphDocument, node_id: str) -> SavedGraphNode:
    for node in document.nodes:
        if node.id == node_id:
            return node
    raise CollaborationCommandRejectedError(
        code="missing_node",
        message=f"Graph command targets missing node {node_id}",
    )


def _edge_or_raise(document: SavedGraphDocument, edge_id: str) -> SavedGraphEdge:
    for edge in document.edges:
        if edge.id == edge_id:
            return edge
    raise CollaborationCommandRejectedError(
        code="missing_edge",
        message=f"Graph command targets missing edge {edge_id}",
    )


def _binding_for_variable(
    node: SavedGraphNode,
    variable: str,
) -> SavedGraphArtifactTypeBinding | None:
    for binding in node.artifact_type_bindings:
        if binding.variable == variable:
            return binding
    return None


def _sanitize_config_value(value: object) -> object:
    if isinstance(value, dict):
        mapping = cast(dict[str, object], value)
        sanitized: dict[str, object] = {}
        for key, item in mapping.items():
            if key in {"upload_key", "artifact_id"}:
                continue
            if key == "uploads" and isinstance(item, list):
                continue
            sanitized[key] = _sanitize_config_value(item)
        return sanitized
    if isinstance(value, list):
        items = cast(list[object], value)
        return [_sanitize_config_value(item) for item in items]
    return value


def sanitize_document_for_cross_workspace_copy(
    document: SavedGraphDocument,
) -> SavedGraphDocument:
    for node in document.nodes:
        if node.operator_id.startswith(GRAPH_MODULE_OPERATOR_PREFIX):
            raise CollaborationCommandRejectedError(
                code="foreign_module_reference",
                message=(
                    f"Cross-workspace copy cannot include module operator "
                    f"{node.operator_id}"
                ),
            )
    sanitized_nodes = tuple(
        node.model_copy(
            update={"config": _sanitize_config_value(node.config_dict())}
        )
        for node in document.nodes
    )
    known_nodes = {node.id for node in sanitized_nodes}
    presentation = GraphPresentationDocument(
        viewers=document.presentation.viewers,
        links=tuple(
            link
            for link in document.presentation.links
            if link.source_node_id in known_nodes
        ),
        bindings=document.presentation.bindings,
        annotations=document.presentation.annotations,
    )
    return SavedGraphDocument(
        nodes=sanitized_nodes,
        edges=document.edges,
        presentation=presentation,
    )


def _viewer_or_raise(
    document: SavedGraphDocument,
    viewer_id: str,
) -> GraphPresentationViewer:
    for viewer in document.presentation.viewers:
        if viewer.id == viewer_id:
            return viewer
    raise CollaborationCommandRejectedError(
        code="missing_viewer",
        message=f"Graph command targets missing artifact viewer {viewer_id}",
    )


def _annotation_or_raise(
    document: SavedGraphDocument,
    annotation_id: str,
) -> GraphPresentationAnnotation:
    for annotation in document.presentation.annotations:
        if annotation.id == annotation_id:
            return annotation
    raise CollaborationCommandRejectedError(
        code="missing_annotation",
        message=f"Graph command targets missing annotation {annotation_id}",
    )


def apply_graph_command(
    *,
    name: str,
    document: SavedGraphDocument,
    command: GraphCommand,
) -> tuple[str, SavedGraphDocument]:
    if isinstance(command, ApplyGraphCommandBatch):
        next_name = name
        next_document = document
        for primitive in command.commands:
            next_name, next_document = apply_graph_command(
                name=next_name,
                document=next_document,
                command=primitive,
            )
        return next_name, next_document

    if isinstance(command, RenameGraphCommand):
        if name != command.expected_name:
            raise _field_conflict(
                f"Graph name conflict: expected {command.expected_name!r}, "
                f"actual {name!r}"
            )
        return command.name, document

    if isinstance(command, AddNodeCommand):
        if any(node.id == command.node.id for node in document.nodes):
            raise CollaborationCommandRejectedError(
                code="duplicate_node",
                message=f"Graph command adds duplicate node {command.node.id}",
            )
        return name, document.with_topology(
            nodes=(*document.nodes, command.node),
        )

    if isinstance(command, DuplicateNodeCommand):
        _node_or_raise(document, command.source_node_id)
        if any(node.id == command.node.id for node in document.nodes):
            raise CollaborationCommandRejectedError(
                code="duplicate_node",
                message=f"Graph command adds duplicate node {command.node.id}",
            )
        return name, document.with_topology(
            nodes=(*document.nodes, command.node),
        )

    if isinstance(command, RemoveNodesCommand):
        removed = set(command.node_ids)
        return name, document.with_topology(
            nodes=tuple(node for node in document.nodes if node.id not in removed),
            edges=tuple(
                edge
                for edge in document.edges
                if edge.from_node not in removed and edge.to_node not in removed
            ),
            presentation=document.presentation.prune_for_removed_nodes(removed),
        )

    if isinstance(command, MoveNodesCommand):
        for position in command.positions:
            _node_or_raise(document, position.node_id)
        positions = {
            position.node_id: GraphPoint(x=position.x, y=position.y)
            for position in command.positions
        }
        return name, document.with_topology(
            nodes=tuple(
                node.model_copy(update={"position": positions[node.id]})
                if node.id in positions
                else node
                for node in document.nodes
            ),
        )

    if isinstance(command, UpdateNodeOperatorCommand):
        node = _node_or_raise(document, command.node_id)
        if (
            node.operator_id != command.expected_operator_id
            or node.operator_version != command.expected_operator_version
        ):
            raise _field_conflict(
                f"Operator on node {command.node_id} changed: expected "
                f"{command.expected_operator_id}@"
                f"{command.expected_operator_version}, actual "
                f"{node.operator_id}@{node.operator_version}"
            )
        return name, document.with_topology(
            nodes=tuple(
                candidate.model_copy(
                    update={
                        "operator_id": command.operator_id,
                        "operator_version": command.operator_version,
                    }
                )
                if candidate.id == command.node_id
                else candidate
                for candidate in document.nodes
            ),
        )

    if isinstance(command, UpdateNodeConfigurationCommand):
        node = _node_or_raise(document, command.node_id)
        current_value = node.config_dict().get(command.field)
        if not _json_equal(current_value, command.expected_value):
            raise _field_conflict(
                f"Configuration field {command.field!r} on node "
                f"{command.node_id} changed"
            )
        updated_nodes: list[SavedGraphNode] = []
        for candidate in document.nodes:
            if candidate.id != command.node_id:
                updated_nodes.append(candidate)
                continue
            config = dict(candidate.config_dict())
            config[command.field] = command.value
            updated_nodes.append(candidate.model_copy(update={"config": config}))
        return name, document.with_topology(nodes=tuple(updated_nodes))

    if isinstance(command, UpdateNodeLayoutCommand):
        node = _node_or_raise(document, command.node_id)
        if not _json_equal(
            _model_json(node.layout),
            _model_json(command.expected_layout),
        ):
            raise _field_conflict(f"Layout on node {command.node_id} changed")
        return name, document.with_topology(
            nodes=tuple(
                node.model_copy(update={"layout": command.layout})
                if node.id == command.node_id
                else node
                for node in document.nodes
            ),
        )

    if isinstance(command, SetNodeInputPlugsCommand):
        node = _node_or_raise(document, command.node_id)
        current_ids = tuple(plug.id for plug in node.input_plugs)
        if current_ids != command.expected_plug_ids:
            raise _field_conflict(
                f"Input plugs on node {command.node_id} changed"
            )
        return name, document.with_topology(
            nodes=tuple(
                candidate.model_copy(update={"input_plugs": command.input_plugs})
                if candidate.id == command.node_id
                else candidate
                for candidate in document.nodes
            ),
        )

    if isinstance(command, UpdateNodeConfigurationAndInputPlugsCommand):
        node = _node_or_raise(document, command.node_id)
        if not _json_equal(node.config_dict(), command.expected_config):
            raise _field_conflict(
                f"Configuration on node {command.node_id} changed"
            )
        current_ids = tuple(plug.id for plug in node.input_plugs)
        if current_ids != command.expected_plug_ids:
            raise _field_conflict(
                f"Input plugs on node {command.node_id} changed"
            )
        retained_plug_ids = {plug.id for plug in command.input_plugs}
        return name, document.with_topology(
            nodes=tuple(
                candidate.model_copy(
                    update={
                        "config": command.config,
                        "input_plugs": command.input_plugs,
                    }
                )
                if candidate.id == command.node_id
                else candidate
                for candidate in document.nodes
            ),
            edges=tuple(
                edge
                for edge in document.edges
                if edge.to_node != command.node_id
                or edge.to_plug is None
                or edge.to_plug in retained_plug_ids
            ),
        )

    if isinstance(command, SetNodeArtifactTypeBindingCommand):
        node = _node_or_raise(document, command.node_id)
        current = _binding_for_variable(node, command.binding.variable)
        if not _json_equal(_model_json(current), _model_json(command.expected_binding)):
            raise _field_conflict(
                f"Artifact type binding {command.binding.variable!r} on node "
                f"{command.node_id} changed"
            )
        remaining = tuple(
            binding
            for binding in node.artifact_type_bindings
            if binding.variable != command.binding.variable
        )
        return name, document.with_topology(
            nodes=tuple(
                candidate.model_copy(
                    update={
                        "artifact_type_bindings": (*remaining, command.binding),
                    }
                )
                if candidate.id == command.node_id
                else candidate
                for candidate in document.nodes
            ),
        )

    if isinstance(command, ClearNodeArtifactTypeBindingCommand):
        node = _node_or_raise(document, command.node_id)
        current = _binding_for_variable(node, command.variable)
        if not _json_equal(_model_json(current), _model_json(command.expected_binding)):
            raise _field_conflict(
                f"Artifact type binding {command.variable!r} on node "
                f"{command.node_id} changed"
            )
        return name, document.with_topology(
            nodes=tuple(
                candidate.model_copy(
                    update={
                        "artifact_type_bindings": tuple(
                            binding
                            for binding in candidate.artifact_type_bindings
                            if binding.variable != command.variable
                        )
                    }
                )
                if candidate.id == command.node_id
                else candidate
                for candidate in document.nodes
            ),
        )

    if isinstance(command, AddEdgeCommand):
        if any(edge.id == command.edge.id for edge in document.edges):
            raise CollaborationCommandRejectedError(
                code="duplicate_edge",
                message=f"Graph command adds duplicate edge {command.edge.id}",
            )
        return name, document.with_topology(
            edges=(*document.edges, command.edge),
        )

    if isinstance(command, UpdateEdgeCommand):
        current = _edge_or_raise(document, command.edge.id)
        if not _json_equal(
            _model_json(current),
            _model_json(command.expected_edge),
        ):
            raise _field_conflict(f"Edge {command.edge.id} changed")
        if command.edge.id != command.expected_edge.id:
            raise CollaborationCommandRejectedError(
                code="invalid_edge_update",
                message="Update edge command cannot change edge id",
            )
        return name, document.with_topology(
            edges=tuple(
                command.edge if edge.id == command.edge.id else edge
                for edge in document.edges
            ),
        )

    if isinstance(command, RemoveEdgesCommand):
        removed_edges = set(command.edge_ids)
        return name, document.with_topology(
            edges=tuple(
                edge for edge in document.edges if edge.id not in removed_edges
            ),
        )

    if isinstance(command, ReplaceDocumentCommand):
        return command.name, command.document

    if isinstance(command, ReplacePresentationCommand):
        return name, document.with_topology(presentation=command.presentation)

    if isinstance(command, MoveArtifactViewersCommand):
        for position in command.positions:
            _viewer_or_raise(document, position.viewer_id)
        positions = {
            position.viewer_id: GraphPoint(x=position.x, y=position.y)
            for position in command.positions
        }
        return name, document.with_topology(
            presentation=GraphPresentationDocument(
                viewers=tuple(
                    viewer.model_copy(
                        update={"position": positions[viewer.id]}
                    )
                    if viewer.id in positions
                    else viewer
                    for viewer in document.presentation.viewers
                ),
                links=document.presentation.links,
                bindings=document.presentation.bindings,
                annotations=document.presentation.annotations,
            ),
        )

    for position in command.positions:
        _annotation_or_raise(document, position.annotation_id)
    positions = {
        position.annotation_id: GraphPoint(x=position.x, y=position.y)
        for position in command.positions
    }
    return name, document.with_topology(
        presentation=GraphPresentationDocument(
            viewers=document.presentation.viewers,
            links=document.presentation.links,
            bindings=document.presentation.bindings,
            annotations=tuple(
                annotation.model_copy(update={"position": positions[annotation.id]})
                if annotation.id in positions
                else annotation
                for annotation in document.presentation.annotations
            ),
        ),
    )

@dataclass
class CollaborativeGraphHead:
    workspace_id: UUID
    graph_id: UUID
    room_epoch: UUID
    collaboration_sequence: int
    checkpoint_sequence: int
    checkpoint_revision: int
    name: str
    document: SavedGraphDocument
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if self.collaboration_sequence < 0:
            raise ValueError("Collaboration sequence must be non-negative")
        if self.checkpoint_sequence < 0:
            raise ValueError("Checkpoint sequence must be non-negative")
        if self.checkpoint_sequence > self.collaboration_sequence:
            raise ValueError(
                "Checkpoint sequence cannot exceed collaboration sequence"
            )
        if self.checkpoint_revision < 1:
            raise ValueError("Checkpoint revision must be at least 1")
        self.name = self.name.strip()
        if self.name == "":
            raise ValueError("Collaborative head name must not be blank")
        if len(self.name) > 160:
            raise ValueError("Collaborative head name must be at most 160 characters")
        if self.updated_at.tzinfo is None:
            raise ValueError("Collaborative head timestamp must be timezone-aware")

    @property
    def is_fully_checkpointed(self) -> bool:
        return self.checkpoint_sequence == self.collaboration_sequence

    def apply_accepted_command(
        self,
        *,
        name: str,
        document: SavedGraphDocument,
        updated_at: datetime | None = None,
    ) -> None:
        stamp = updated_at or _utc_now()
        if stamp.tzinfo is None:
            raise ValueError("Collaborative head timestamp must be timezone-aware")
        validated_name = name.strip()
        if validated_name == "":
            raise ValueError("Collaborative head name must not be blank")
        self.name = validated_name
        self.document = document
        self.collaboration_sequence += 1
        self.updated_at = stamp

    def record_checkpoint(
        self,
        *,
        sequence: int,
        revision: int,
        updated_at: datetime | None = None,
    ) -> None:
        if sequence != self.collaboration_sequence:
            raise ValueError(
                "Checkpoint sequence must equal the current collaboration sequence"
            )
        if revision < 1:
            raise ValueError("Checkpoint revision must be at least 1")
        stamp = updated_at or _utc_now()
        if stamp.tzinfo is None:
            raise ValueError("Collaborative head timestamp must be timezone-aware")
        self.checkpoint_sequence = sequence
        self.checkpoint_revision = revision
        self.updated_at = stamp

    @classmethod
    def for_existing_saved_graph(
        cls,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        name: str,
        document: SavedGraphDocument,
        checkpoint_revision: int,
        room_epoch: UUID | None = None,
        updated_at: datetime | None = None,
    ) -> Self:
        return cls(
            workspace_id=workspace_id,
            graph_id=graph_id,
            room_epoch=uuid4() if room_epoch is None else room_epoch,
            collaboration_sequence=0,
            checkpoint_sequence=0,
            checkpoint_revision=checkpoint_revision,
            name=name,
            document=document,
            updated_at=_utc_now() if updated_at is None else updated_at,
        )


class GraphCommandJournalEntry(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    workspace_id: UUID
    graph_id: UUID
    room_epoch: UUID
    command_id: UUID
    command_hmac: bytes
    hmac_key_version: int
    accepted_sequence: int
    actor_kind: CollaborationActorKind
    actor_user_id: UUID | None
    graph_room_session_id: UUID | None
    authorization_version: int | None
    command_kind: GraphCommandKind
    command_payload: dict[str, object]
    accepted_at: datetime = Field(default_factory=_utc_now)

    @field_validator("accepted_at")
    @classmethod
    def require_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Journal acceptance timestamp must be timezone-aware")
        return value


class GraphCommandReceipt(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    workspace_id: UUID
    graph_id: UUID
    command_id: UUID
    command_hmac: bytes
    hmac_key_version: int
    actor_kind: CollaborationActorKind
    actor_user_id: UUID | None
    room_epoch: UUID
    accepted_sequence: int
    outcome: CommandReceiptOutcome
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("created_at")
    @classmethod
    def require_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Receipt timestamp must be timezone-aware")
        return value


class GraphCheckpointMapping(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    workspace_id: UUID
    graph_id: UUID
    room_epoch: UUID
    collaboration_sequence: int
    saved_revision: int
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("created_at")
    @classmethod
    def require_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Checkpoint mapping timestamp must be timezone-aware")
        return value


class GraphExecutionIdempotencyRecord(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    workspace_id: UUID
    graph_id: UUID
    client_request_id: UUID
    request_hmac: bytes
    hmac_key_version: int
    actor_user_id: UUID
    room_epoch: UUID
    head_sequence: int
    execution_id: UUID
    created_at: datetime = Field(default_factory=_utc_now)


class GraphActiveExecutionSlot(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    workspace_id: UUID
    graph_id: UUID
    execution_id: UUID
    updated_at: datetime = Field(default_factory=_utc_now)


__all__ = [
    "AddEdgeCommand",
    "AddNodeCommand",
    "ApplyGraphCommandBatch",
    "ClearNodeArtifactTypeBindingCommand",
    "CollaborationActorKind",
    "CollaborativeGraphHead",
    "CommandReceiptOutcome",
    "DuplicateNodeCommand",
    "GRAPH_COMMAND_ADAPTER",
    "GraphActiveExecutionSlot",
    "GraphCheckpointMapping",
    "GraphCommand",
    "GraphCommandJournalEntry",
    "GraphCommandKind",
    "GraphCommandReceipt",
    "GraphExecutionIdempotencyRecord",
    "MoveAnnotationPosition",
    "MoveAnnotationsCommand",
    "MoveArtifactViewerPosition",
    "MoveArtifactViewersCommand",
    "MoveNodePosition",
    "MoveNodesCommand",
    "PrimitiveGraphCommand",
    "RemoveEdgesCommand",
    "RemoveNodesCommand",
    "RenameGraphCommand",
    "ReplaceDocumentCommand",
    "ReplacePresentationCommand",
    "SetNodeArtifactTypeBindingCommand",
    "SetNodeInputPlugsCommand",
    "UpdateEdgeCommand",
    "UpdateNodeConfigurationAndInputPlugsCommand",
    "UpdateNodeConfigurationCommand",
    "UpdateNodeLayoutCommand",
    "UpdateNodeOperatorCommand",
    "apply_graph_command",
    "canonical_command_payload",
    "command_hmac_digest",
    "command_requires_exact_sequence",
    "empty_collaborative_document",
    "sanitize_document_for_cross_workspace_copy",
]

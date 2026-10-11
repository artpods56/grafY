"""Collaborative graph head, commands, receipts, and checkpoints."""

import hmac
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, ClassVar, Literal, Self
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)
from pydantic_core import to_jsonable_python

from grafy_core.domain.errors import CollaborationCommandRejectedError
from grafy_core.domain.modules import GRAPH_MODULE_OPERATOR_PREFIX
from grafy_core.domain.plugin_identity import PluginReleaseScope
from grafy_core.domain.saved_graphs import (
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
    SavedGraphOrigin,
    SavedGraphPluginReleasePin,
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
    UPDATE_NODE_CONFIGURATION = "update_node_configuration"
    REPLACE_NODE_CONFIGURATION = "replace_node_configuration"
    UPDATE_NODE_LAYOUT = "update_node_layout"
    UPDATE_NODE_PLUGIN_RELEASE = "update_node_plugin_release"
    SET_NODE_INPUT_PLUGS = "set_node_input_plugs"
    # Deprecated: the Workbench sends this gesture as the batch
    # [replace_node_configuration, set_node_input_plugs]. Retire it once no client
    # sends it.
    UPDATE_NODE_CONFIGURATION_AND_INPUT_PLUGS = (
        "update_node_configuration_and_input_plugs"
    )
    SET_NODE_ARTIFACT_TYPE_BINDING = "set_node_artifact_type_binding"
    CLEAR_NODE_ARTIFACT_TYPE_BINDING = "clear_node_artifact_type_binding"
    ADD_EDGE = "add_edge"
    UPDATE_EDGE = "update_edge"
    REMOVE_EDGES = "remove_edges"
    ADD_ORIGIN = "add_origin"
    UPDATE_ORIGIN = "update_origin"
    REMOVE_ORIGINS = "remove_origins"
    REPLACE_DOCUMENT = "replace_document"
    REPLACE_PRESENTATION = "replace_presentation"
    MOVE_ARTIFACT_VIEWERS = "move_artifact_viewers"
    MOVE_ANNOTATIONS = "move_annotations"


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

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            _expect_unchanged(
                lambda draft: draft.name,
                self.expected_name,
                f"Graph name conflict: expected {self.expected_name!r}",
            ),
            ChangeStep(lambda draft: replace(draft, name=self.name)),
        )


class AddNodeCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.ADD_NODE] = GraphCommandKind.ADD_NODE
    node: SavedGraphNode

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            _expect_new_node(self.node.id),
            _edit(lambda document: document.with_node_added(self.node)),
        )


class DuplicateNodeCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.DUPLICATE_NODE] = GraphCommandKind.DUPLICATE_NODE
    source_node_id: str
    node: SavedGraphNode

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            _expect(_node_or_raise, self.source_node_id),
            _expect_new_node(self.node.id),
            _edit(lambda document: document.with_node_added(self.node)),
        )


class RemoveNodesCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.REMOVE_NODES] = GraphCommandKind.REMOVE_NODES
    node_ids: tuple[str, ...] = Field(min_length=1)

    def steps(self) -> tuple[GraphStep, ...]:
        return (_edit(lambda document: document.with_nodes_removed(self.node_ids)),)


class MoveNodePosition(CollaborationValue):
    node_id: str
    x: float
    y: float


class MoveNodesCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.MOVE_NODES] = GraphCommandKind.MOVE_NODES
    positions: tuple[MoveNodePosition, ...] = Field(min_length=1)

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            *(_expect(_node_or_raise, position.node_id) for position in self.positions),
            _edit(
                lambda document: document.with_nodes_moved(
                    {
                        position.node_id: GraphPoint(x=position.x, y=position.y)
                        for position in self.positions
                    }
                )
            ),
        )


class UpdateNodeConfigurationCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.UPDATE_NODE_CONFIGURATION] = (
        GraphCommandKind.UPDATE_NODE_CONFIGURATION
    )
    node_id: str
    field: str
    value: object
    expected_value: object | None = None

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            _expect(_node_or_raise, self.node_id),
            _expect_unchanged(
                lambda draft: _node_or_raise(draft.document, self.node_id)
                .config_dict()
                .get(self.field),
                self.expected_value,
                f"Configuration field {self.field!r} on node {self.node_id} changed",
            ),
            _edit_node(
                self.node_id,
                lambda node: node.model_copy(
                    update={"config": {**node.config_dict(), self.field: self.value}}
                ),
            ),
        )


class ReplaceNodeConfigurationCommand(CollaborationValue):
    """Replace a node's whole configuration; unlike the per-field update it can drop keys."""

    kind: Literal[GraphCommandKind.REPLACE_NODE_CONFIGURATION] = (
        GraphCommandKind.REPLACE_NODE_CONFIGURATION
    )
    node_id: str
    config: dict[str, object]
    expected_config: dict[str, object]

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            _expect(_node_or_raise, self.node_id),
            _expect_unchanged(
                lambda draft: _node_or_raise(
                    draft.document, self.node_id
                ).config_dict(),
                self.expected_config,
                f"Configuration on node {self.node_id} changed",
            ),
            _edit_node(
                self.node_id,
                lambda node: node.model_copy(update={"config": self.config}),
            ),
        )


class UpdateNodeLayoutCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.UPDATE_NODE_LAYOUT] = (
        GraphCommandKind.UPDATE_NODE_LAYOUT
    )
    node_id: str
    layout: SavedGraphNodeLayout | None
    expected_layout: SavedGraphNodeLayout | None = None

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            _expect(_node_or_raise, self.node_id),
            _expect_unchanged(
                lambda draft: _node_or_raise(draft.document, self.node_id).layout,
                self.expected_layout,
                f"Layout on node {self.node_id} changed",
            ),
            _edit_node(
                self.node_id,
                lambda node: node.model_copy(update={"layout": self.layout}),
            ),
        )


class UpdateNodePluginReleaseCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.UPDATE_NODE_PLUGIN_RELEASE] = (
        GraphCommandKind.UPDATE_NODE_PLUGIN_RELEASE
    )
    node_id: str
    plugin_release_pin: SavedGraphPluginReleasePin
    expected_plugin_release_pin: SavedGraphPluginReleasePin

    def steps(self) -> tuple[GraphStep, ...]:
        expected = self.expected_plugin_release_pin
        next_pin = self.plugin_release_pin
        return (
            _expect(_node_or_raise, self.node_id),
            _require(
                lambda draft: _node_or_raise(draft.document, self.node_id).kind
                == "plugin",
                code="invalid_plugin_release_update",
                message=(
                    f"Plugin release update on node {self.node_id} is only "
                    "valid for Plugin nodes"
                ),
            ),
            _expect_unchanged(
                lambda draft: _node_or_raise(
                    draft.document, self.node_id
                ).plugin_release_pin,
                expected,
                lambda draft: (
                    f"Plugin release pin on node {self.node_id} changed: "
                    f"expected {_pin_identity(expected)}, actual "
                    f"{_pin_identity(_node_or_raise(draft.document, self.node_id).plugin_release_pin)}"
                ),
            ),
            _require(
                lambda _draft: next_pin.scope is expected.scope
                and next_pin.slug == expected.slug,
                code="invalid_plugin_release_update",
                message=(
                    f"Plugin release update on node {self.node_id} cannot change "
                    f"release family from {expected.scope.value}:{expected.slug} "
                    f"to {next_pin.scope.value}:{next_pin.slug}"
                ),
            ),
            _edit_node(
                self.node_id,
                lambda node: node.model_copy(
                    update={"plugin_release_pin": self.plugin_release_pin}
                ),
            ),
        )


class SetNodeInputPlugsCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.SET_NODE_INPUT_PLUGS] = (
        GraphCommandKind.SET_NODE_INPUT_PLUGS
    )
    node_id: str
    input_plugs: tuple[SavedGraphInputPlug, ...]
    expected_plug_ids: tuple[str, ...]

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            _expect(_node_or_raise, self.node_id),
            _expect_unchanged(
                lambda draft: tuple(
                    plug.id
                    for plug in _node_or_raise(draft.document, self.node_id).input_plugs
                ),
                self.expected_plug_ids,
                f"Input plugs on node {self.node_id} changed",
            ),
            _edit_node(
                self.node_id,
                lambda node: node.model_copy(update={"input_plugs": self.input_plugs}),
            ),
        )


class UpdateNodeConfigurationAndInputPlugsCommand(CollaborationValue):
    """Deprecated compound of replace_node_configuration and set_node_input_plugs.

    Kept so older clients still work; it expands into exactly those two commands' steps.
    """

    kind: Literal[GraphCommandKind.UPDATE_NODE_CONFIGURATION_AND_INPUT_PLUGS] = (
        GraphCommandKind.UPDATE_NODE_CONFIGURATION_AND_INPUT_PLUGS
    )
    node_id: str
    config: dict[str, object]
    input_plugs: tuple[SavedGraphInputPlug, ...]
    expected_config: dict[str, object]
    expected_plug_ids: tuple[str, ...]

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            *ReplaceNodeConfigurationCommand(
                node_id=self.node_id,
                config=self.config,
                expected_config=self.expected_config,
            ).steps(),
            *SetNodeInputPlugsCommand(
                node_id=self.node_id,
                input_plugs=self.input_plugs,
                expected_plug_ids=self.expected_plug_ids,
            ).steps(),
        )


class SetNodeArtifactTypeBindingCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.SET_NODE_ARTIFACT_TYPE_BINDING] = (
        GraphCommandKind.SET_NODE_ARTIFACT_TYPE_BINDING
    )
    node_id: str
    binding: SavedGraphArtifactTypeBinding
    expected_binding: SavedGraphArtifactTypeBinding | None = None

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            _expect(_node_or_raise, self.node_id),
            _expect_unchanged(
                lambda draft: _binding_for_variable(
                    _node_or_raise(draft.document, self.node_id), self.binding.variable
                ),
                self.expected_binding,
                (
                    f"Artifact type binding {self.binding.variable!r} on node "
                    f"{self.node_id} changed"
                ),
            ),
            _edit_node(
                self.node_id,
                lambda node: node.model_copy(
                    update={
                        "artifact_type_bindings": (
                            *(
                                binding
                                for binding in node.artifact_type_bindings
                                if binding.variable != self.binding.variable
                            ),
                            self.binding,
                        )
                    }
                ),
            ),
        )


class ClearNodeArtifactTypeBindingCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.CLEAR_NODE_ARTIFACT_TYPE_BINDING] = (
        GraphCommandKind.CLEAR_NODE_ARTIFACT_TYPE_BINDING
    )
    node_id: str
    variable: str
    expected_binding: SavedGraphArtifactTypeBinding

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            _expect(_node_or_raise, self.node_id),
            _expect_unchanged(
                lambda draft: _binding_for_variable(
                    _node_or_raise(draft.document, self.node_id), self.variable
                ),
                self.expected_binding,
                f"Artifact type binding {self.variable!r} on node {self.node_id} changed",
            ),
            _edit_node(
                self.node_id,
                lambda node: node.model_copy(
                    update={
                        "artifact_type_bindings": tuple(
                            binding
                            for binding in node.artifact_type_bindings
                            if binding.variable != self.variable
                        )
                    }
                ),
            ),
        )


class AddEdgeCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.ADD_EDGE] = GraphCommandKind.ADD_EDGE
    edge: SavedGraphEdge

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            _require(
                lambda draft: all(
                    edge.id != self.edge.id for edge in draft.document.edges
                ),
                code="duplicate_edge",
                message=f"Graph command adds duplicate edge {self.edge.id}",
            ),
            _edit(lambda document: document.with_edge_added(self.edge)),
        )


class UpdateEdgeCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.UPDATE_EDGE] = GraphCommandKind.UPDATE_EDGE
    edge: SavedGraphEdge
    expected_edge: SavedGraphEdge

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            _expect(_edge_or_raise, self.edge.id),
            _expect_unchanged(
                lambda draft: _edge_or_raise(draft.document, self.edge.id),
                self.expected_edge,
                f"Edge {self.edge.id} changed",
            ),
            _edit(lambda document: document.with_edge_replaced(self.edge)),
        )


class RemoveEdgesCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.REMOVE_EDGES] = GraphCommandKind.REMOVE_EDGES
    edge_ids: tuple[str, ...] = Field(min_length=1)

    def steps(self) -> tuple[GraphStep, ...]:
        return (_edit(lambda document: document.with_edges_removed(self.edge_ids)),)


class AddOriginCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.ADD_ORIGIN] = GraphCommandKind.ADD_ORIGIN
    origin: SavedGraphOrigin

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            _require(
                lambda draft: all(
                    origin.id != self.origin.id for origin in draft.document.origins
                ),
                code="duplicate_origin",
                message=f"Graph command adds duplicate origin {self.origin.id}",
            ),
            _edit(lambda document: document.with_origin_added(self.origin)),
        )


class UpdateOriginCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.UPDATE_ORIGIN] = GraphCommandKind.UPDATE_ORIGIN
    origin: SavedGraphOrigin
    expected_origin: SavedGraphOrigin

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            _expect(_origin_or_raise, self.origin.id),
            _expect_unchanged(
                lambda draft: _origin_or_raise(draft.document, self.origin.id),
                self.expected_origin,
                f"Origin {self.origin.id} changed",
            ),
            _edit(lambda document: document.with_origin_replaced(self.origin)),
        )


class RemoveOriginsCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.REMOVE_ORIGINS] = GraphCommandKind.REMOVE_ORIGINS
    origin_ids: tuple[str, ...] = Field(min_length=1)

    def steps(self) -> tuple[GraphStep, ...]:
        return (_edit(lambda document: document.with_origins_removed(self.origin_ids)),)


class ReplaceDocumentCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.REPLACE_DOCUMENT] = GraphCommandKind.REPLACE_DOCUMENT
    name: str
    document: SavedGraphDocument

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validated_graph_name(value)

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            ChangeStep(
                lambda _draft: GraphDraft(name=self.name, document=self.document)
            ),
        )


class ReplacePresentationCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.REPLACE_PRESENTATION] = (
        GraphCommandKind.REPLACE_PRESENTATION
    )
    presentation: GraphPresentationDocument

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            _edit(
                lambda document: document.with_topology(presentation=self.presentation)
            ),
        )


class MoveArtifactViewerPosition(CollaborationValue):
    viewer_id: str
    x: float
    y: float


class MoveArtifactViewersCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.MOVE_ARTIFACT_VIEWERS] = (
        GraphCommandKind.MOVE_ARTIFACT_VIEWERS
    )
    positions: tuple[MoveArtifactViewerPosition, ...] = Field(min_length=1)

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            *(
                _expect(_viewer_or_raise, position.viewer_id)
                for position in self.positions
            ),
            _edit(
                lambda document: document.with_viewers_moved(
                    {
                        position.viewer_id: GraphPoint(x=position.x, y=position.y)
                        for position in self.positions
                    }
                )
            ),
        )


class MoveAnnotationPosition(CollaborationValue):
    annotation_id: str
    x: float
    y: float


class MoveAnnotationsCommand(CollaborationValue):
    kind: Literal[GraphCommandKind.MOVE_ANNOTATIONS] = GraphCommandKind.MOVE_ANNOTATIONS
    positions: tuple[MoveAnnotationPosition, ...] = Field(min_length=1)

    def steps(self) -> tuple[GraphStep, ...]:
        return (
            *(
                _expect(_annotation_or_raise, position.annotation_id)
                for position in self.positions
            ),
            _edit(
                lambda document: document.with_annotations_moved(
                    {
                        position.annotation_id: GraphPoint(x=position.x, y=position.y)
                        for position in self.positions
                    }
                )
            ),
        )


GraphCommand = Annotated[
    RenameGraphCommand
    | AddNodeCommand
    | DuplicateNodeCommand
    | RemoveNodesCommand
    | MoveNodesCommand
    | UpdateNodeConfigurationCommand
    | ReplaceNodeConfigurationCommand
    | UpdateNodeLayoutCommand
    | UpdateNodePluginReleaseCommand
    | SetNodeInputPlugsCommand
    | UpdateNodeConfigurationAndInputPlugsCommand
    | SetNodeArtifactTypeBindingCommand
    | ClearNodeArtifactTypeBindingCommand
    | AddEdgeCommand
    | UpdateEdgeCommand
    | RemoveEdgesCommand
    | AddOriginCommand
    | UpdateOriginCommand
    | RemoveOriginsCommand
    | ReplaceDocumentCommand
    | ReplacePresentationCommand
    | MoveArtifactViewersCommand
    | MoveAnnotationsCommand,
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
    commands: Sequence[GraphCommand],
) -> bytes:
    """Canonical digest of one accepted batch, used as its idempotency key.

    A batch of one hashes exactly like the single-command submissions that predate batches.
    """

    del key_version
    batch = [command.model_dump(mode="json") for command in commands]
    envelope = {
        "actor_user_id": None if actor_user_id is None else str(actor_user_id),
        **({"command": batch[0]} if len(batch) == 1 else {"commands": batch}),
        "graph_id": str(graph_id),
        "observed_sequence": observed_sequence,
        "room_epoch": str(room_epoch),
        "workspace_id": str(workspace_id),
    }
    payload = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hmac.new(key, payload, sha256).digest()


def command_requires_exact_sequence(commands: Sequence[GraphCommand]) -> bool:
    return any(
        isinstance(command, (ReplaceDocumentCommand, ReplacePresentationCommand))
        for command in commands
    )


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


def _origin_or_raise(
    document: SavedGraphDocument,
    origin_id: str,
) -> SavedGraphOrigin:
    for origin in document.origins:
        if origin.id == origin_id:
            return origin
    raise CollaborationCommandRejectedError(
        code="missing_origin",
        message=f"Graph command targets missing origin {origin_id}",
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
        sanitized: dict[str, object] = {}
        for key, item in value.items():
            if key in {"upload_key", "artifact_id"}:
                continue
            if key == "uploads" and isinstance(item, list):
                continue
            sanitized[key] = _sanitize_config_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_config_value(item) for item in value]
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
        release_pin = node.plugin_release_pin
        if (
            release_pin is not None
            and release_pin.scope is PluginReleaseScope.WORKSPACE
        ):
            raise CollaborationCommandRejectedError(
                code="foreign_workspace_plugin_release",
                message=(
                    "Cross-workspace copy cannot include Workspace Plugin "
                    f"release {release_pin.slug!r} revision "
                    f"{release_pin.revision}"
                ),
            )
    sanitized_nodes = tuple(
        node.model_copy(update={"config": _sanitize_config_value(node.config_dict())})
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


@dataclass(frozen=True)
class GraphDraft:
    """The graph name and document that a batch's steps read and replace."""

    name: str
    document: SavedGraphDocument


@dataclass(frozen=True)
class AssertionStep:
    """Checks the draft and changes nothing; `check` raises the rejection."""

    check: Callable[[GraphDraft], object]

    def run(self, draft: GraphDraft) -> GraphDraft:
        self.check(draft)
        return draft


@dataclass(frozen=True)
class ChangeStep:
    """Returns a new draft; every document it builds is validated on creation."""

    change: Callable[[GraphDraft], GraphDraft]

    def run(self, draft: GraphDraft) -> GraphDraft:
        return self.change(draft)


type GraphStep = AssertionStep | ChangeStep


def _canonical_json(value: object) -> str:
    return json.dumps(to_jsonable_python(value), sort_keys=True, separators=(",", ":"))


def _require(
    holds: Callable[[GraphDraft], bool], *, code: str, message: str
) -> AssertionStep:
    def check(draft: GraphDraft) -> None:
        if not holds(draft):
            raise CollaborationCommandRejectedError(code=code, message=message)

    return AssertionStep(check)


def _expect_unchanged(
    read: Callable[[GraphDraft], object],
    expected: object,
    message: str | Callable[[GraphDraft], str],
) -> AssertionStep:
    """Compare-and-set guard: the current value must equal `expected` as canonical JSON.

    `message` is either a fixed rejection or one built from the draft that failed,
    so it can name the value the command actually met.
    """

    def check(draft: GraphDraft) -> None:
        if _canonical_json(read(draft)) == _canonical_json(expected):
            return
        detail = message(draft) if callable(message) else message
        raise CollaborationCommandRejectedError(code="field_conflict", message=detail)

    return AssertionStep(check)


def _pin_identity(pin: SavedGraphPluginReleasePin | None) -> str:
    if pin is None:
        return "none"
    return f"{pin.scope.value}:{pin.slug}@{pin.revision}"


def _expect[T](
    lookup: Callable[[SavedGraphDocument, str], T], entity_id: str
) -> AssertionStep:
    """Require an entity to exist; `lookup` raises its specific missing-id code."""
    return AssertionStep(lambda draft: lookup(draft.document, entity_id))


def _expect_new_node(node_id: str) -> AssertionStep:
    return _require(
        lambda draft: all(node.id != node_id for node in draft.document.nodes),
        code="duplicate_node",
        message=f"Graph command adds duplicate node {node_id}",
    )


def _edit(edit: Callable[[SavedGraphDocument], SavedGraphDocument]) -> ChangeStep:
    return ChangeStep(lambda draft: replace(draft, document=edit(draft.document)))


def _edit_node(
    node_id: str, update: Callable[[SavedGraphNode], SavedGraphNode]
) -> ChangeStep:
    return _edit(
        lambda document: document.with_node_replaced(
            update(_node_or_raise(document, node_id))
        )
    )


def apply_graph_commands(
    *,
    name: str,
    document: SavedGraphDocument,
    commands: Sequence[GraphCommand],
) -> tuple[str, SavedGraphDocument]:
    """Apply a batch of commands as one change, or reject it at the first failing step.

    Intermediate documents are never persisted, so a rejected batch leaves the
    caller's head as it was.

    A rejection records the index of the failing command in the batch.
    """

    draft = GraphDraft(name=name, document=document)
    for index, command in enumerate(commands):
        try:
            for step in command.steps():
                draft = step.run(draft)
        except CollaborationCommandRejectedError as exc:
            exc.command_index = index
            raise
        except ValidationError as exc:
            violations = "; ".join(
                error["msg"].removeprefix("Value error, ") for error in exc.errors()
            )
            raise CollaborationCommandRejectedError(
                code="invalid_document",
                message=(
                    f"Graph command {command.kind} would leave the graph "
                    f"invalid: {violations}"
                ),
                command_index=index,
            ) from exc
    return draft.name, draft.document


def apply_graph_command(
    *,
    name: str,
    document: SavedGraphDocument,
    command: GraphCommand,
) -> tuple[str, SavedGraphDocument]:
    """Apply one command as a batch of one; see apply_graph_commands."""

    return apply_graph_commands(name=name, document=document, commands=(command,))


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
            raise ValueError("Checkpoint sequence cannot exceed collaboration sequence")
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


__all__ = [
    "AddEdgeCommand",
    "AddNodeCommand",
    "AddOriginCommand",
    "ClearNodeArtifactTypeBindingCommand",
    "CollaborationActorKind",
    "CollaborativeGraphHead",
    "CommandReceiptOutcome",
    "DuplicateNodeCommand",
    "GRAPH_COMMAND_ADAPTER",
    "GraphCheckpointMapping",
    "GraphCommand",
    "GraphCommandKind",
    "GraphCommandReceipt",
    "MoveAnnotationPosition",
    "MoveAnnotationsCommand",
    "MoveArtifactViewerPosition",
    "MoveArtifactViewersCommand",
    "MoveNodePosition",
    "MoveNodesCommand",
    "RemoveEdgesCommand",
    "RemoveNodesCommand",
    "RemoveOriginsCommand",
    "RenameGraphCommand",
    "ReplaceDocumentCommand",
    "ReplaceNodeConfigurationCommand",
    "ReplacePresentationCommand",
    "SetNodeArtifactTypeBindingCommand",
    "SetNodeInputPlugsCommand",
    "UpdateEdgeCommand",
    "UpdateNodeConfigurationAndInputPlugsCommand",
    "UpdateNodeConfigurationCommand",
    "UpdateNodeLayoutCommand",
    "UpdateNodePluginReleaseCommand",
    "UpdateOriginCommand",
    "apply_graph_command",
    "apply_graph_commands",
    "canonical_command_payload",
    "command_hmac_digest",
    "command_requires_exact_sequence",
    "empty_collaborative_document",
    "sanitize_document_for_cross_workspace_copy",
]

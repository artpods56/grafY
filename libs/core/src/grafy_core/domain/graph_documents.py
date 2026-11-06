"""The value types of one Graph's canvas: nodes, edges, origins and presentation.

These are the shape a single Graph is drawn with. They carry no identity, no
revision and no filing: the aggregate that owns them is a Project Graph, in
``grafy_core.kernel.project.GraphDefinition``, and the object that holds them is
``grafy_core.domain.projects.Project``.
"""

import re
from collections.abc import Collection, Mapping
from math import isfinite
from types import MappingProxyType
from typing import Annotated, ClassVar, Literal, Self, cast
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence, ArtifactTypeKey
from grafy_core.conversions import MAX_ARTIFACT_CONVERSION_HOPS

GraphIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class GraphValue(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )

    def __deepcopy__(self, memo: dict[int, object] | None = None) -> Self:
        """A frozen value has nothing to isolate, so a copy is the value itself.

        Its mappings are read-only proxies, which ``deepcopy`` cannot copy, and no holder
        can change what it shares: that is what lets a store keep a head by copying it.
        """
        del memo
        return self


class GraphPoint(GraphValue):
    x: float
    y: float


# Shared ceiling for layout axes: common browser/GPU max texture dimension.
# Larger DOM layers can fail to composite. Floors keep node chrome usable.
GRAPH_LAYOUT_DIMENSION_MAX = 16_384


def validate_graph_layout_dimensions(
    width: float | None,
    body_height: float | None,
    appendix_height: float | None,
) -> None:
    if width is None and body_height is None and appendix_height is None:
        raise ValueError(
            "Saved graph node layout must set at least one of width, "
            "body_height, or appendix_height"
        )


class GraphNodeLayout(GraphValue):
    """Canvas chrome sizes for a node shell and its artifact appendix."""

    width: float | None = Field(default=None, ge=260, le=GRAPH_LAYOUT_DIMENSION_MAX)
    body_height: float | None = Field(
        default=None, ge=96, le=GRAPH_LAYOUT_DIMENSION_MAX
    )
    appendix_height: float | None = Field(
        default=None, ge=120, le=GRAPH_LAYOUT_DIMENSION_MAX
    )

    @model_validator(mode="after")
    def require_at_least_one_dimension(self) -> Self:
        validate_graph_layout_dimensions(
            self.width, self.body_height, self.appendix_height
        )
        return self


def _freeze_json(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("Saved graph config numbers must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        mapping = cast(Mapping[object, object], value)
        for key, item in mapping.items():
            if not isinstance(key, str):
                raise ValueError("Saved graph config object keys must be strings")
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        sequence = cast(list[object] | tuple[object, ...], value)
        return tuple(_freeze_json(item) for item in sequence)
    raise ValueError(
        f"Saved graph config values must be JSON-compatible, got {type(value).__name__}"
    )


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        return {key: _thaw_json(item) for key, item in mapping.items()}
    if isinstance(value, tuple):
        sequence = cast(tuple[object, ...], value)
        return [_thaw_json(item) for item in sequence]
    return value


class GraphInputPlug(GraphValue):
    id: GraphIdentifier
    port: GraphIdentifier


class GraphArtifactTypeBinding(GraphValue):
    variable: GraphIdentifier
    artifact_type: ArtifactTypeKey

    @field_validator("artifact_type", mode="before")
    @classmethod
    def validate_artifact_type_shape(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        raw = cast(Mapping[object, object], value)
        expected_fields = {"id", "schema_version"}
        if set(raw) != expected_fields:
            raise ValueError(
                "Saved graph artifact type binding must contain exactly id and "
                "schema_version"
            )
        return dict(raw)

    @field_validator("artifact_type")
    @classmethod
    def validate_artifact_type_key(
        cls,
        value: ArtifactTypeKey,
    ) -> ArtifactTypeKey:
        if value.id.strip() == "":
            raise ValueError("Saved graph bound artifact type id must not be empty")
        if value.id != value.id.strip():
            raise ValueError(
                "Saved graph bound artifact type id must not have surrounding "
                "whitespace"
            )
        if len(value.id) > 255:
            raise ValueError(
                "Saved graph bound artifact type id must be at most 255 characters"
            )
        if value.schema_version < 1:
            raise ValueError(
                "Saved graph bound artifact type schema version must be positive"
            )
        return value


GraphNodeKind = Literal["builtin", "module", "call"]


class GraphNode(GraphValue):
    kind: GraphNodeKind
    id: GraphIdentifier
    operator_id: GraphIdentifier
    operator_version: int = Field(ge=1)
    config: Mapping[str, object] = Field(default_factory=dict)
    position: GraphPoint
    layout: GraphNodeLayout | None = None
    input_plugs: tuple[GraphInputPlug, ...] = ()
    artifact_type_bindings: tuple[GraphArtifactTypeBinding, ...] = ()

    @field_validator("config")
    @classmethod
    def freeze_config(
        cls,
        value: Mapping[str, object],
    ) -> Mapping[str, object]:
        frozen = _freeze_json(value)
        if not isinstance(frozen, Mapping):
            raise ValueError("Saved graph node config must be an object")
        return cast(Mapping[str, object], frozen)

    @field_serializer("config")
    def serialize_config(self, value: Mapping[str, object]) -> dict[str, object]:
        thawed = _thaw_json(value)
        if not isinstance(thawed, dict):
            raise ValueError("Saved graph node config must be an object")
        return cast(dict[str, object], thawed)

    def config_dict(self) -> dict[str, object]:
        thawed = _thaw_json(self.config)
        if not isinstance(thawed, dict):
            raise ValueError("Saved graph node config must be an object")
        return cast(dict[str, object], thawed)

    @model_validator(mode="after")
    def validate_artifact_type_bindings(self) -> Self:
        variables = [binding.variable for binding in self.artifact_type_bindings]
        if len(variables) != len(set(variables)):
            raise ValueError(
                "Saved graph node artifact type binding variables must be unique"
            )
        return self

    def artifact_type_binding_map(self) -> dict[str, ArtifactTypeKey]:
        return {
            binding.variable: binding.artifact_type
            for binding in self.artifact_type_bindings
        }


class GraphProjection(GraphValue):
    path: tuple[GraphIdentifier, ...] = Field(min_length=1)


class GraphConversion(GraphValue):
    id: GraphIdentifier
    version: int = Field(ge=1)


class GraphEdge(GraphValue):
    id: GraphIdentifier
    enabled: bool = True
    from_node: GraphIdentifier
    from_port: GraphIdentifier
    to_node: GraphIdentifier
    to_port: GraphIdentifier
    to_plug: GraphIdentifier | None = None
    collection_mode: Literal["direct", "map"] = "direct"
    projection: GraphProjection | None = None
    conversion_path: tuple[GraphConversion, ...] = Field(
        default=(),
        max_length=MAX_ARTIFACT_CONVERSION_HOPS,
    )
    route_offset: GraphPoint | None = None


class GraphOrigin(GraphValue):
    """Exact artifact value held on one node input with no incoming edge."""

    id: GraphIdentifier
    to_node: GraphIdentifier
    to_port: GraphIdentifier
    to_plug: GraphIdentifier | None = None
    value: ArtifactRef | ArtifactRefSequence
    collection_mode: Literal["direct", "map"] = "direct"
    conversion_path: tuple[GraphConversion, ...] = Field(
        default=(),
        max_length=MAX_ARTIFACT_CONVERSION_HOPS,
    )


def graph_input_slot(
    *,
    to_node: str,
    to_port: str,
    to_plug: str | None,
) -> tuple[str, str]:
    """Identify one satisfiable input position for an edge or origin."""
    return (to_node, to_plug if to_plug is not None else to_port)


class GraphPresentationViewer(GraphValue):
    id: GraphIdentifier
    position: GraphPoint
    layout: GraphNodeLayout | None = None
    mode: str | None = Field(default=None, max_length=255)
    # A node-less card: it presents persisted artifacts and executes nothing.
    # One reference shows one artifact; a sequence shows them in the order the
    # card passes them on. The reference is kept even when the artifact is gone,
    # so the card can show a missing state until the user removes it. It is
    # never a link target.
    artifact_ref: ArtifactRef | ArtifactRefSequence | None = None

    @field_validator("id")
    @classmethod
    def validate_viewer_id(cls, value: str) -> str:
        if not value.startswith("artifact-viewer-"):
            raise ValueError(
                "Presentation viewer id must start with 'artifact-viewer-'"
            )
        return value


AnnotationKind = Literal["text", "rectangle", "ellipse"]
AnnotationColor = Annotated[
    str,
    StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$"),
]
DEFAULT_ANNOTATION_COLOR = "#475569"


class GraphAnnotationLayout(GraphValue):
    """Axis-aligned size for a presentation annotation on the canvas."""

    width: float = Field(ge=24, le=GRAPH_LAYOUT_DIMENSION_MAX)
    height: float = Field(ge=24, le=GRAPH_LAYOUT_DIMENSION_MAX)


class GraphPresentationAnnotation(GraphValue):
    """Non-executable canvas decoration used to document a graph (Miro-like)."""

    id: GraphIdentifier
    kind: AnnotationKind
    position: GraphPoint
    layout: GraphAnnotationLayout
    text: str = Field(default="", max_length=8_000)
    color: AnnotationColor = DEFAULT_ANNOTATION_COLOR

    @field_validator("id")
    @classmethod
    def validate_annotation_id(cls, value: str) -> str:
        if not value.startswith("annotation-"):
            raise ValueError("Presentation annotation id must start with 'annotation-'")
        return value

    @field_validator("color", mode="before")
    @classmethod
    def canonicalize_annotation_color(cls, value: object) -> object:
        if isinstance(value, str):
            return value.upper()
        return value

    @model_validator(mode="after")
    def validate_text_for_kind(self) -> Self:
        if self.kind != "text" and self.text.strip() != "":
            # Non-text shapes may carry an empty caption placeholder only.
            raise ValueError(
                f"Presentation annotation {self.id} of kind {self.kind!r} "
                "must not carry text"
            )
        return self


class GraphPresentationLink(GraphValue):
    id: GraphIdentifier
    source_node_id: GraphIdentifier
    source_port_name: GraphIdentifier
    target_viewer_id: GraphIdentifier
    # Optional field projection applied when previewing the linked output.
    projection: GraphProjection | None = None
    # Visual routing adjustment from the link's natural midpoint.
    route_offset: GraphPoint | None = None

    @field_validator("id")
    @classmethod
    def validate_link_id(cls, value: str) -> str:
        if not value.startswith("artifact-viewer-edge-"):
            raise ValueError(
                "Presentation link id must start with 'artifact-viewer-edge-'"
            )
        return value


class GraphPresentationBindingMapping(GraphValue):
    source_field: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]
    target_field: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]


class GraphPresentationBinding(GraphValue):
    id: GraphIdentifier
    source_viewer_id: GraphIdentifier
    target_viewer_id: GraphIdentifier
    mappings: tuple[GraphPresentationBindingMapping, ...] = Field(max_length=8)
    effects: tuple[Literal["filter", "highlight", "focus"], ...] = Field(
        min_length=1,
        max_length=3,
    )
    empty_selection: Literal["show_all"] = "show_all"

    @field_validator("id")
    @classmethod
    def validate_binding_id(cls, value: str) -> str:
        if not value.startswith("artifact-viewer-binding-"):
            raise ValueError(
                "Presentation binding id must start with 'artifact-viewer-binding-'"
            )
        return value

    @model_validator(mode="after")
    def validate_binding_endpoints(self) -> Self:
        if self.source_viewer_id == self.target_viewer_id:
            raise ValueError("Presentation binding cannot target its source viewer")
        if len(self.effects) != len(set(self.effects)):
            raise ValueError("Presentation binding effects must be unique")
        return self


class GraphPresentationDocument(GraphValue):
    viewers: tuple[GraphPresentationViewer, ...] = ()
    links: tuple[GraphPresentationLink, ...] = ()
    bindings: tuple[GraphPresentationBinding, ...] = ()
    annotations: tuple[GraphPresentationAnnotation, ...] = ()

    @model_validator(mode="after")
    def validate_presentation(self) -> Self:
        viewer_ids = [viewer.id for viewer in self.viewers]
        if len(viewer_ids) != len(set(viewer_ids)):
            raise ValueError("Presentation viewer ids must be unique")
        known_viewers = set(viewer_ids)
        artifact_viewers = {
            viewer.id for viewer in self.viewers if viewer.artifact_ref is not None
        }

        link_ids = [link.id for link in self.links]
        if len(link_ids) != len(set(link_ids)):
            raise ValueError("Presentation link ids must be unique")
        linked_viewers: set[str] = set()
        for link in self.links:
            if link.target_viewer_id not in known_viewers:
                raise ValueError(
                    f"Presentation link {link.id} references missing viewer "
                    f"{link.target_viewer_id}"
                )
            if link.target_viewer_id in artifact_viewers:
                raise ValueError(
                    f"Presentation link {link.id} cannot target artifact card "
                    f"{link.target_viewer_id}"
                )
            if link.target_viewer_id in linked_viewers:
                raise ValueError(
                    f"Presentation viewer {link.target_viewer_id} accepts at most "
                    "one link"
                )
            linked_viewers.add(link.target_viewer_id)

        binding_ids = [binding.id for binding in self.bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("Presentation binding ids must be unique")
        for binding in self.bindings:
            if binding.source_viewer_id not in known_viewers:
                raise ValueError(
                    f"Presentation binding {binding.id} references missing source "
                    f"viewer {binding.source_viewer_id}"
                )
            if binding.target_viewer_id not in known_viewers:
                raise ValueError(
                    f"Presentation binding {binding.id} references missing target "
                    f"viewer {binding.target_viewer_id}"
                )

        annotation_ids = [annotation.id for annotation in self.annotations]
        if len(annotation_ids) != len(set(annotation_ids)):
            raise ValueError("Presentation annotation ids must be unique")
        return self

    def prune_for_removed_nodes(
        self,
        removed_node_ids: set[str],
    ) -> "GraphPresentationDocument":
        if not removed_node_ids:
            return self
        return GraphPresentationDocument(
            viewers=self.viewers,
            links=tuple(
                link
                for link in self.links
                if link.source_node_id not in removed_node_ids
            ),
            bindings=self.bindings,
            annotations=self.annotations,
        )


def empty_presentation() -> GraphPresentationDocument:
    return GraphPresentationDocument()


SAVED_GRAPH_SCHEMA_VERSION = 7


class DeploymentAgentModel(GraphValue):
    kind: Literal["deployment"] = "deployment"


class CustomAgentModel(GraphValue):
    kind: Literal["custom"] = "custom"
    endpoint: str = Field(min_length=1, max_length=2048)
    model: GraphIdentifier

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        from grafy_core.egress import validated_public_destination

        return str(
            validated_public_destination(AnyHttpUrl(value), service_name="Agent")
        )


AgentModel = Annotated[
    DeploymentAgentModel | CustomAgentModel, Field(discriminator="kind")
]


#: What a model may call a tool: lower-case words, short enough for every provider.
AGENT_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


class AgentContextLink(GraphValue):
    """One thing connected to an Agent as context, read by reference (ADR 0021).

    The three kinds name what is read, never a copy of it: the output port of a node
    of this Graph, a card on this canvas, or an item of the Library. A card and a
    Library item are loose references on purpose. Removing either must not be
    refused because an Agent still points at it, so a missing one is skipped, and
    said so, when a turn reads its context. A node is different: removing it removes
    the link, as it removes the edges.
    """

    id: GraphIdentifier
    kind: Literal["node_output", "card", "library_item"]
    node_id: GraphIdentifier | None = None
    port: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None
    card_id: GraphIdentifier | None = None
    library_item_id: UUID | None = None

    @model_validator(mode="after")
    def validate_kind(self) -> Self:
        named = {
            "node_id": self.node_id,
            "port": self.port,
            "card_id": self.card_id,
            "library_item_id": self.library_item_id,
        }
        wanted = {
            "node_output": {"node_id", "port"},
            "card": {"card_id"},
            "library_item": {"library_item_id"},
        }[self.kind]
        missing = sorted(name for name in wanted if named[name] is None)
        if missing:
            raise ValueError(
                f"Agent context link {self.id} of kind {self.kind} needs "
                f"{', '.join(missing)}"
            )
        extra = sorted(
            name for name, value in named.items() if name not in wanted and value
        )
        if extra:
            raise ValueError(
                f"Agent context link {self.id} of kind {self.kind} must not carry "
                f"{', '.join(extra)}"
            )
        return self


class AgentToolLink(GraphValue):
    """A node of this Graph an Agent may call as a tool (ADR 0021).

    ``filled_ports`` are the node's open inputs the model gives a value; every other
    input keeps what the Graph feeds it, so inputs wired from upstream stay fixed.
    ``returned_ports`` are the outputs handed back to the model; none named means all
    of them. ``name`` is what the model sees and is unique among an Agent's tools.
    """

    id: GraphIdentifier
    node_id: GraphIdentifier
    name: str = Field(pattern=AGENT_TOOL_NAME_PATTERN.pattern)
    description: str = Field(default="", max_length=2_000)
    filled_ports: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=128)], ...
    ] = ()
    returned_ports: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=128)], ...
    ] = ()

    @model_validator(mode="after")
    def validate_ports(self) -> Self:
        for label, ports in (
            ("filled", self.filled_ports),
            ("returned", self.returned_ports),
        ):
            if len(ports) != len(set(ports)):
                raise ValueError(
                    f"Agent tool {self.id} names a {label} port more than once"
                )
        return self


class GraphAgent(GraphValue):
    id: GraphIdentifier
    name: GraphIdentifier
    instructions: str = Field(default="", max_length=100_000)
    model: AgentModel = Field(default_factory=DeploymentAgentModel)
    context: tuple[AgentContextLink, ...] = ()
    tools: tuple[AgentToolLink, ...] = ()

    @model_validator(mode="after")
    def validate_links(self) -> Self:
        link_ids = [link.id for link in (*self.context, *self.tools)]
        if len(link_ids) != len(set(link_ids)):
            raise ValueError(f"Agent {self.id} link ids must be unique")
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError(f"Agent {self.id} tool names must be unique")
        return self

    def without_nodes(self, removed: Collection[str]) -> "GraphAgent":
        """The Agent with every link to a removed node dropped, as edges are."""
        return self.model_copy(
            update={
                "context": tuple(
                    link for link in self.context if link.node_id not in removed
                ),
                "tools": tuple(
                    tool for tool in self.tools if tool.node_id not in removed
                ),
            }
        )

    position: GraphPoint = Field(default_factory=lambda: GraphPoint(x=0, y=0))
    width: float = Field(default=360, ge=260, le=GRAPH_LAYOUT_DIMENSION_MAX)
    height: float = Field(default=480, ge=96, le=GRAPH_LAYOUT_DIMENSION_MAX)


class GraphDocument(GraphValue):
    schema_version: Literal[7] = SAVED_GRAPH_SCHEMA_VERSION
    agents: tuple[GraphAgent, ...] = ()
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()
    origins: tuple[GraphOrigin, ...] = ()
    presentation: GraphPresentationDocument = Field(default_factory=empty_presentation)

    @model_validator(mode="after")
    def validate_structure(self) -> Self:
        agent_ids = [agent.id for agent in self.agents]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("Graph Agent ids must be unique")
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Saved graph node ids must be unique")

        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("Saved graph edge ids must be unique")

        origin_ids = [origin.id for origin in self.origins]
        if len(origin_ids) != len(set(origin_ids)):
            raise ValueError("Saved graph origin ids must be unique")

        known_nodes = set(node_ids)
        for agent in self.agents:
            for tool in agent.tools:
                if tool.node_id not in known_nodes:
                    raise ValueError(
                        f"Agent {agent.id} tool {tool.id} references missing node "
                        f"{tool.node_id}"
                    )
            for link in agent.context:
                if link.node_id is not None and link.node_id not in known_nodes:
                    raise ValueError(
                        f"Agent {agent.id} context link {link.id} references "
                        f"missing node {link.node_id}"
                    )
        plugs_by_node: dict[str, dict[str, GraphInputPlug]] = {}
        for node in self.nodes:
            plug_ids = [plug.id for plug in node.input_plugs]
            if len(plug_ids) != len(set(plug_ids)):
                raise ValueError(
                    f"Saved graph input plug ids must be unique within node {node.id}"
                )
            plugs_by_node[node.id] = {plug.id: plug for plug in node.input_plugs}

        connected_plugs: set[tuple[str, str]] = set()
        enabled_slots: dict[tuple[str, str], str] = {}
        for edge in self.edges:
            if edge.enabled:
                enabled_slots.setdefault(
                    graph_input_slot(
                        to_node=edge.to_node,
                        to_port=edge.to_port,
                        to_plug=edge.to_plug,
                    ),
                    edge.id,
                )
            if edge.from_node not in known_nodes:
                raise ValueError(
                    f"Saved graph edge {edge.id} references missing source node "
                    f"{edge.from_node}"
                )
            if edge.to_node not in known_nodes:
                raise ValueError(
                    f"Saved graph edge {edge.id} references missing target node "
                    f"{edge.to_node}"
                )
            if edge.to_plug is None:
                continue
            target_plug = plugs_by_node[edge.to_node].get(edge.to_plug)
            if target_plug is None:
                raise ValueError(
                    f"Saved graph edge {edge.id} references missing input plug "
                    f"{edge.to_plug} on target node {edge.to_node}"
                )
            if target_plug.port != edge.to_port:
                raise ValueError(
                    f"Saved graph edge {edge.id} targets port {edge.to_port}, but "
                    f"input plug {edge.to_plug} belongs to port {target_plug.port}"
                )
            plug_key = (edge.to_node, edge.to_plug)
            if plug_key in connected_plugs:
                raise ValueError(
                    f"Saved graph input plug {edge.to_plug} on node "
                    f"{edge.to_node} accepts at most one edge"
                )
            connected_plugs.add(plug_key)

        for origin in self.origins:
            if origin.to_node not in known_nodes:
                raise ValueError(
                    f"Saved graph origin {origin.id} references missing target node "
                    f"{origin.to_node}"
                )
            if origin.to_plug is not None:
                target_plug = plugs_by_node[origin.to_node].get(origin.to_plug)
                if target_plug is None:
                    raise ValueError(
                        f"Saved graph origin {origin.id} references missing input "
                        f"plug {origin.to_plug} on target node {origin.to_node}"
                    )
                if target_plug.port != origin.to_port:
                    raise ValueError(
                        f"Saved graph origin {origin.id} targets port "
                        f"{origin.to_port}, but input plug {origin.to_plug} belongs "
                        f"to port {target_plug.port}"
                    )
            slot = graph_input_slot(
                to_node=origin.to_node,
                to_port=origin.to_port,
                to_plug=origin.to_plug,
            )
            if slot in enabled_slots:
                raise ValueError(
                    f"Saved graph input {origin.to_plug or origin.to_port} on node "
                    f"{origin.to_node} is already satisfied by edge "
                    f"{enabled_slots[slot]}"
                )
            enabled_slots[slot] = origin.id

        for link in self.presentation.links:
            if link.source_node_id not in known_nodes:
                raise ValueError(
                    f"Presentation link {link.id} references missing source node "
                    f"{link.source_node_id}"
                )
        return self

    def with_topology(
        self,
        *,
        nodes: tuple[GraphNode, ...] | None = None,
        edges: tuple[GraphEdge, ...] | None = None,
        origins: tuple[GraphOrigin, ...] | None = None,
        presentation: GraphPresentationDocument | None = None,
        agents: tuple[GraphAgent, ...] | None = None,
    ) -> "GraphDocument":
        return GraphDocument(
            agents=self.agents if agents is None else agents,
            nodes=self.nodes if nodes is None else nodes,
            edges=self.edges if edges is None else edges,
            origins=self.origins if origins is None else origins,
            presentation=(self.presentation if presentation is None else presentation),
        )

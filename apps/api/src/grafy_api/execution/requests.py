from collections.abc import Mapping
from typing import Annotated, Final, Literal, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    model_validator,
)

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence
from grafy_core.conversions import MAX_ARTIFACT_CONVERSION_HOPS
from grafy_core.domain.execution_history import (
    GraphExecutionScope,
)
from grafy_core.domain.saved_graphs import (
    SavedGraph,
    SavedGraphRevision,
    SavedGraphNodeKind,
    SavedGraphNode,
    SavedGraphEdge,
)

from grafy_api.v1.models import (
    ArtifactTypeBindingModel,
    ArtifactTypeKeyResponse,
    PluginReleasePinModel,
)


MAX_EXECUTION_NODE_PATH_LENGTH: Final = 64

ExecutionIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]

InputPlugIdentifier = ExecutionIdentifier

InvocationIndex = Annotated[int, Field(ge=0)]


class RunInputPlugRequest(BaseModel):
    id: InputPlugIdentifier
    port: InputPlugIdentifier


class RunNodeRequest(BaseModel):
    kind: SavedGraphNodeKind
    id: ExecutionIdentifier
    operator_id: str
    operator_version: int
    config: dict[str, object] = Field(default_factory=dict)
    input_plugs: list[RunInputPlugRequest] = Field(default_factory=list)
    artifact_type_bindings: list[ArtifactTypeBindingModel] = Field(
        default_factory=list,
    )
    plugin_release: PluginReleasePinModel | None = None

    @classmethod
    def from_saved_node(
        cls,
        node: SavedGraphNode,
        *,
        connected_plug_ids: set[str],
    ) -> "RunNodeRequest":
        return cls(
            kind=node.kind,
            id=node.id,
            operator_id=node.operator_id,
            operator_version=node.operator_version,
            config=node.config_dict(),
            input_plugs=[
                RunInputPlugRequest(id=plug.id, port=plug.port)
                for plug in node.input_plugs
                if plug.id in connected_plug_ids
            ],
            artifact_type_bindings=[
                ArtifactTypeBindingModel(
                    variable=binding.variable,
                    artifact_type=ArtifactTypeKeyResponse.from_key(
                        binding.artifact_type
                    ),
                )
                for binding in node.artifact_type_bindings
            ],
            plugin_release=(
                PluginReleasePinModel.from_saved_pin(node.plugin_release_pin)
                if node.plugin_release_pin is not None
                else None
            ),
        )

    @model_validator(mode="after")
    def validate_artifact_type_bindings(self) -> "RunNodeRequest":
        variables = [binding.variable for binding in self.artifact_type_bindings]
        if len(variables) != len(set(variables)):
            raise ValueError("Node artifact type binding variables must be unique")
        return self

    @model_validator(mode="after")
    def validate_kind_and_pin(self) -> "RunNodeRequest":
        if self.kind == "plugin":
            if self.plugin_release is None:
                raise ValueError(
                    "Plugin node must pin an exact Plugin release with scope, slug, "
                    "and revision"
                )
        elif self.plugin_release is not None:
            raise ValueError(f"{self.kind} node cannot carry a Plugin release pin")
        return self


class FieldProjectionRequest(BaseModel):
    path: list[str] = Field(min_length=1)


class ArtifactConversionRequest(BaseModel):
    id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
    ]
    version: int = Field(ge=1)


class RunEdgeRequest(BaseModel):
    from_node: str
    from_port: str
    to_node: str
    to_port: str
    to_plug: InputPlugIdentifier | None = None
    projection: FieldProjectionRequest | None = None
    conversion_path: list[ArtifactConversionRequest] = Field(
        default_factory=list,
        max_length=MAX_ARTIFACT_CONVERSION_HOPS,
    )
    collection_mode: Literal["direct", "map"] = "direct"

    @classmethod
    def from_saved_edge(cls, edge: SavedGraphEdge) -> "RunEdgeRequest":
        return cls(
            from_node=edge.from_node,
            from_port=edge.from_port,
            to_node=edge.to_node,
            to_port=edge.to_port,
            to_plug=edge.to_plug,
            projection=(
                FieldProjectionRequest(path=list(edge.projection.path))
                if edge.projection is not None
                else None
            ),
            conversion_path=[
                ArtifactConversionRequest(
                    id=conversion.id,
                    version=conversion.version,
                )
                for conversion in edge.conversion_path
            ],
            collection_mode=edge.collection_mode,
        )

    @model_validator(mode="before")
    @classmethod
    def normalize_singular_conversion(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        raw = cast(Mapping[object, object], value)
        if "conversion" not in raw:
            return dict(raw)
        if "conversion_path" in raw:
            raise ValueError(
                "Run edge cannot declare both conversion and conversion_path"
            )
        normalized = dict(raw)
        conversion = normalized.pop("conversion")
        normalized["conversion_path"] = [] if conversion is None else [conversion]
        return normalized


class PinnedOutputRequest(BaseModel):
    from_node: str
    from_port: str
    value: ArtifactRef | ArtifactRefSequence


class RunRequest(BaseModel):
    nodes: list[RunNodeRequest]
    edges: list[RunEdgeRequest] = Field(default_factory=list)
    pinned_outputs: list[PinnedOutputRequest] = Field(default_factory=list)
    scope: GraphExecutionScope = "all"
    graph_id: UUID | None = None
    graph_revision: int | None = Field(default=None, ge=1)
    secret_graph_id: UUID | None = None
    secret_graph_revision: int | None = Field(default=None, ge=1)

    @classmethod
    def from_saved_graph(
        cls,
        graph: SavedGraph | SavedGraphRevision,
    ) -> "RunRequest":
        active_edges = [edge for edge in graph.document.edges if edge.enabled]
        connected_plugs: dict[str, set[str]] = {}
        for edge in active_edges:
            if edge.to_plug is not None:
                connected_plugs.setdefault(edge.to_node, set()).add(edge.to_plug)
        return cls(
            nodes=[
                RunNodeRequest.from_saved_node(
                    node,
                    connected_plug_ids=connected_plugs.get(node.id, set()),
                )
                for node in graph.document.nodes
            ],
            edges=[RunEdgeRequest.from_saved_edge(edge) for edge in active_edges],
            scope="all",
            graph_id=graph.id,
            graph_revision=graph.revision,
            secret_graph_id=graph.id,
            secret_graph_revision=graph.revision,
        )

    @model_validator(mode="after")
    def validate_graph_context(self) -> "RunRequest":
        if (self.graph_id is None) != (self.graph_revision is None):
            raise ValueError("graph_id and graph_revision must be provided together")
        if (self.secret_graph_id is None) != (self.secret_graph_revision is None):
            raise ValueError(
                "secret_graph_id and secret_graph_revision must be provided together"
            )
        if (
            self.graph_id is not None
            and self.secret_graph_id is not None
            and (
                self.graph_id != self.secret_graph_id
                or self.graph_revision != self.secret_graph_revision
            )
        ):
            raise ValueError(
                "graph and secret graph contexts must identify the same saved "
                "graph revision when both are provided"
            )
        return self

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, ClassVar, Literal, Self, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from grafy_core.conversions import MAX_ARTIFACT_CONVERSION_HOPS
from grafy_core.domain.collaboration import (
    CollaborativeGraphHead,
    CommandReceiptOutcome,
    GraphCommand,
    GraphCommandReceipt,
)
from grafy_core.domain.saved_graphs import (
    AnnotationColor,
    AnnotationKind,
    DEFAULT_ANNOTATION_COLOR,
    GraphPoint,
    GraphBrowserItem,
    GraphFolder,
    GraphOrganization,
    GraphPresentationAnnotation,
    GraphPresentationBinding,
    GraphPresentationBindingMapping,
    GraphPresentationDocument,
    GraphPresentationLink,
    GraphPresentationViewer,
    SavedGraph,
    SavedGraphAnnotationLayout,
    SavedGraphDocument,
    SavedGraphEdge,
    SavedGraphNode,
    SavedGraphNodeLayout,
    SavedGraphProjection,
    UserGraphState,
)
from grafy_core.domain.identity import WorkspaceKind

from grafy_api.v1.models import (
    ArtifactTypeBindingModel,
    ArtifactTypeKeyResponse,
    PluginReleasePinModel,
)


Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class SavedGraphApiModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )


class GraphPointModel(SavedGraphApiModel):
    x: float
    y: float


class SavedGraphInputPlugModel(SavedGraphApiModel):
    id: Identifier
    port: Identifier


# Keep in sync with grafy_core.domain.saved_graphs._LAYOUT_DIMENSION_MAX.
_LAYOUT_DIMENSION_MAX = 16_384


class SavedGraphNodeLayoutModel(SavedGraphApiModel):
    width: float | None = Field(default=None, ge=260, le=_LAYOUT_DIMENSION_MAX)
    body_height: float | None = Field(default=None, ge=96, le=_LAYOUT_DIMENSION_MAX)
    appendix_height: float | None = Field(
        default=None, ge=120, le=_LAYOUT_DIMENSION_MAX
    )

    @model_validator(mode="after")
    def require_at_least_one_dimension(self) -> Self:
        if (
            self.width is None
            and self.body_height is None
            and self.appendix_height is None
        ):
            raise ValueError(
                "Saved graph node layout must set at least one of width, "
                "body_height, or appendix_height"
            )
        return self


class SavedGraphNodeModel(SavedGraphApiModel):
    kind: Literal["builtin", "plugin", "module"]
    id: Identifier
    operator_id: Identifier
    operator_version: int = Field(ge=1)
    config: dict[str, object] = Field(default_factory=dict)
    position: GraphPointModel
    layout: SavedGraphNodeLayoutModel | None = None
    input_plugs: list[SavedGraphInputPlugModel] = Field(default_factory=list)
    artifact_type_bindings: list[ArtifactTypeBindingModel] = Field(
        default_factory=list,
    )
    plugin_release: PluginReleasePinModel | None = None

    @model_validator(mode="after")
    def validate_artifact_type_bindings(self) -> Self:
        variables = [binding.variable for binding in self.artifact_type_bindings]
        if len(variables) != len(set(variables)):
            raise ValueError("Node artifact type binding variables must be unique")
        return self

    @model_validator(mode="after")
    def validate_kind_and_pin(self) -> Self:
        if self.kind == "plugin":
            if self.plugin_release is None:
                raise ValueError(
                    "Plugin node must pin an exact Plugin release with scope, slug, "
                    "and revision"
                )
        elif self.plugin_release is not None:
            raise ValueError(f"{self.kind} node cannot carry a Plugin release pin")
        return self

    @classmethod
    def from_domain(cls, node: SavedGraphNode) -> "SavedGraphNodeModel":
        return cls(
            kind=node.kind,
            id=node.id,
            operator_id=node.operator_id,
            operator_version=node.operator_version,
            config=node.config_dict(),
            position=GraphPointModel(x=node.position.x, y=node.position.y),
            layout=(
                SavedGraphNodeLayoutModel(
                    width=node.layout.width,
                    body_height=node.layout.body_height,
                    appendix_height=node.layout.appendix_height,
                )
                if node.layout is not None
                else None
            ),
            input_plugs=[
                SavedGraphInputPlugModel(id=plug.id, port=plug.port)
                for plug in node.input_plugs
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


class SavedGraphProjectionModel(SavedGraphApiModel):
    path: list[Identifier] = Field(min_length=1)


class SavedGraphConversionModel(SavedGraphApiModel):
    id: Identifier
    version: int = Field(ge=1)


class SavedGraphEdgeModel(SavedGraphApiModel):
    id: Identifier
    enabled: bool = True
    from_node: Identifier
    from_port: Identifier
    to_node: Identifier
    to_port: Identifier
    to_plug: Identifier | None = None
    collection_mode: Literal["direct", "map"] = "direct"
    projection: SavedGraphProjectionModel | None = None
    conversion_path: list[SavedGraphConversionModel] = Field(
        default_factory=list,
        max_length=MAX_ARTIFACT_CONVERSION_HOPS,
    )
    route_offset: GraphPointModel | None = None

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
                "Saved graph edge cannot declare both conversion and conversion_path"
            )
        normalized = dict(raw)
        conversion = normalized.pop("conversion")
        normalized["conversion_path"] = [] if conversion is None else [conversion]
        return normalized

    @classmethod
    def from_domain(cls, edge: SavedGraphEdge) -> "SavedGraphEdgeModel":
        return cls(
            id=edge.id,
            enabled=edge.enabled,
            from_node=edge.from_node,
            from_port=edge.from_port,
            to_node=edge.to_node,
            to_port=edge.to_port,
            to_plug=edge.to_plug,
            collection_mode=edge.collection_mode,
            projection=(
                SavedGraphProjectionModel(path=list(edge.projection.path))
                if edge.projection is not None
                else None
            ),
            conversion_path=[
                SavedGraphConversionModel(
                    id=conversion.id,
                    version=conversion.version,
                )
                for conversion in edge.conversion_path
            ],
            route_offset=(
                GraphPointModel(x=edge.route_offset.x, y=edge.route_offset.y)
                if edge.route_offset is not None
                else None
            ),
        )


class GraphPresentationViewerModel(SavedGraphApiModel):
    id: Identifier
    position: GraphPointModel
    layout: SavedGraphNodeLayoutModel | None = None
    mode: str | None = Field(default=None, max_length=255)


class SavedGraphAnnotationLayoutModel(SavedGraphApiModel):
    width: float = Field(ge=24, le=_LAYOUT_DIMENSION_MAX)
    height: float = Field(ge=24, le=_LAYOUT_DIMENSION_MAX)


class GraphPresentationAnnotationModel(SavedGraphApiModel):
    id: Identifier
    kind: AnnotationKind
    position: GraphPointModel
    layout: SavedGraphAnnotationLayoutModel
    text: str = Field(default="", max_length=8_000)
    color: AnnotationColor = DEFAULT_ANNOTATION_COLOR


class GraphPresentationLinkModel(SavedGraphApiModel):
    id: Identifier
    source_node_id: Identifier
    source_port_name: Identifier
    target_viewer_id: Identifier
    projection: SavedGraphProjectionModel | None = None
    route_offset: GraphPointModel | None = None


class GraphPresentationBindingMappingModel(SavedGraphApiModel):
    source_field: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]
    target_field: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]


class GraphPresentationBindingModel(SavedGraphApiModel):
    id: Identifier
    source_viewer_id: Identifier
    target_viewer_id: Identifier
    mappings: list[GraphPresentationBindingMappingModel] = Field(max_length=8)
    effects: list[Literal["filter", "highlight", "focus"]] = Field(
        min_length=1,
        max_length=3,
    )
    empty_selection: Literal["show_all"] = "show_all"


class GraphPresentationDocumentModel(SavedGraphApiModel):
    viewers: list[GraphPresentationViewerModel] = Field(default_factory=list)
    links: list[GraphPresentationLinkModel] = Field(default_factory=list)
    bindings: list[GraphPresentationBindingModel] = Field(default_factory=list)
    annotations: list[GraphPresentationAnnotationModel] = Field(default_factory=list)

    def to_domain(self) -> GraphPresentationDocument:
        return GraphPresentationDocument(
            viewers=tuple(
                GraphPresentationViewer(
                    id=viewer.id,
                    position=GraphPoint(x=viewer.position.x, y=viewer.position.y),
                    layout=(
                        SavedGraphNodeLayout(
                            width=viewer.layout.width,
                            body_height=viewer.layout.body_height,
                            appendix_height=viewer.layout.appendix_height,
                        )
                        if viewer.layout is not None
                        else None
                    ),
                    mode=viewer.mode,
                )
                for viewer in self.viewers
            ),
            links=tuple(
                GraphPresentationLink(
                    id=link.id,
                    source_node_id=link.source_node_id,
                    source_port_name=link.source_port_name,
                    target_viewer_id=link.target_viewer_id,
                    projection=(
                        SavedGraphProjection(path=tuple(link.projection.path))
                        if link.projection is not None
                        else None
                    ),
                    route_offset=(
                        GraphPoint(
                            x=link.route_offset.x,
                            y=link.route_offset.y,
                        )
                        if link.route_offset is not None
                        else None
                    ),
                )
                for link in self.links
            ),
            bindings=tuple(
                GraphPresentationBinding(
                    id=binding.id,
                    source_viewer_id=binding.source_viewer_id,
                    target_viewer_id=binding.target_viewer_id,
                    mappings=tuple(
                        GraphPresentationBindingMapping(
                            source_field=mapping.source_field,
                            target_field=mapping.target_field,
                        )
                        for mapping in binding.mappings
                    ),
                    effects=tuple(binding.effects),
                    empty_selection=binding.empty_selection,
                )
                for binding in self.bindings
            ),
            annotations=tuple(
                GraphPresentationAnnotation(
                    id=annotation.id,
                    kind=annotation.kind,
                    position=GraphPoint(
                        x=annotation.position.x,
                        y=annotation.position.y,
                    ),
                    layout=SavedGraphAnnotationLayout(
                        width=annotation.layout.width,
                        height=annotation.layout.height,
                    ),
                    text=annotation.text,
                    color=annotation.color,
                )
                for annotation in self.annotations
            ),
        )

    @classmethod
    def from_domain(
        cls,
        presentation: GraphPresentationDocument,
    ) -> "GraphPresentationDocumentModel":
        return cls(
            viewers=[
                GraphPresentationViewerModel(
                    id=viewer.id,
                    position=GraphPointModel(
                        x=viewer.position.x,
                        y=viewer.position.y,
                    ),
                    layout=(
                        SavedGraphNodeLayoutModel(
                            width=viewer.layout.width,
                            body_height=viewer.layout.body_height,
                            appendix_height=viewer.layout.appendix_height,
                        )
                        if viewer.layout is not None
                        else None
                    ),
                    mode=viewer.mode,
                )
                for viewer in presentation.viewers
            ],
            links=[
                GraphPresentationLinkModel(
                    id=link.id,
                    source_node_id=link.source_node_id,
                    source_port_name=link.source_port_name,
                    target_viewer_id=link.target_viewer_id,
                    projection=(
                        SavedGraphProjectionModel(path=list(link.projection.path))
                        if link.projection is not None
                        else None
                    ),
                    route_offset=(
                        GraphPointModel(
                            x=link.route_offset.x,
                            y=link.route_offset.y,
                        )
                        if link.route_offset is not None
                        else None
                    ),
                )
                for link in presentation.links
            ],
            bindings=[
                GraphPresentationBindingModel(
                    id=binding.id,
                    source_viewer_id=binding.source_viewer_id,
                    target_viewer_id=binding.target_viewer_id,
                    mappings=[
                        GraphPresentationBindingMappingModel(
                            source_field=mapping.source_field,
                            target_field=mapping.target_field,
                        )
                        for mapping in binding.mappings
                    ],
                    effects=list(binding.effects),
                    empty_selection=binding.empty_selection,
                )
                for binding in presentation.bindings
            ],
            annotations=[
                GraphPresentationAnnotationModel(
                    id=annotation.id,
                    kind=annotation.kind,
                    position=GraphPointModel(
                        x=annotation.position.x,
                        y=annotation.position.y,
                    ),
                    layout=SavedGraphAnnotationLayoutModel(
                        width=annotation.layout.width,
                        height=annotation.layout.height,
                    ),
                    text=annotation.text,
                    color=annotation.color,
                )
                for annotation in presentation.annotations
            ],
        )


class SavedGraphWriteRequest(SavedGraphApiModel):
    name: str = Field(min_length=1, max_length=160)
    document: SavedGraphDocument

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class CreateSavedGraphRequest(SavedGraphWriteRequest):
    pass


class UpdateSavedGraphRequest(SavedGraphWriteRequest):
    expected_revision: int = Field(ge=1)


class SavedGraphResponse(SavedGraphApiModel):
    id: UUID
    name: str
    revision: int
    created_at: datetime
    updated_at: datetime
    document: SavedGraphDocument

    @classmethod
    def from_graph(cls, graph: SavedGraph) -> "SavedGraphResponse":
        return cls(
            id=graph.id,
            name=graph.name,
            revision=graph.revision,
            created_at=graph.created_at,
            updated_at=graph.updated_at,
            document=graph.document,
        )


class SavedGraphSummaryResponse(SavedGraphApiModel):
    id: UUID
    name: str
    revision: int
    node_count: int
    edge_count: int
    updated_at: datetime

    @classmethod
    def from_graph(cls, graph: SavedGraph) -> "SavedGraphSummaryResponse":
        return cls(
            id=graph.id,
            name=graph.name,
            revision=graph.revision,
            node_count=len(graph.document.nodes),
            edge_count=len(graph.document.edges),
            updated_at=graph.updated_at,
        )


class SavedGraphListResponse(SavedGraphApiModel):
    graphs: list[SavedGraphSummaryResponse]

    @classmethod
    def from_graphs(
        cls,
        graphs: list[SavedGraph],
    ) -> "SavedGraphListResponse":
        return cls(
            graphs=[SavedGraphSummaryResponse.from_graph(graph) for graph in graphs]
        )


class GraphFolderWriteRequest(SavedGraphApiModel):
    name: str = Field(min_length=1, max_length=160)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class GraphFolderResponse(SavedGraphApiModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_folder(cls, folder: GraphFolder) -> "GraphFolderResponse":
        return cls(
            id=folder.id,
            name=folder.name,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )


class GraphFolderListResponse(SavedGraphApiModel):
    folders: list[GraphFolderResponse]

    @classmethod
    def from_folders(cls, folders: list[GraphFolder]) -> "GraphFolderListResponse":
        return cls(
            folders=[GraphFolderResponse.from_folder(folder) for folder in folders]
        )


class AssignGraphFolderRequest(SavedGraphApiModel):
    folder_id: UUID | None


class GraphOrganizationResponse(SavedGraphApiModel):
    folder_id: UUID | None
    archived: bool
    archived_at: datetime | None
    updated_at: datetime

    @classmethod
    def from_organization(
        cls,
        organization: GraphOrganization,
    ) -> "GraphOrganizationResponse":
        return cls(
            folder_id=organization.folder_id,
            archived=organization.is_archived,
            archived_at=organization.archived_at,
            updated_at=organization.updated_at,
        )


class UserGraphStateResponse(SavedGraphApiModel):
    starred: bool
    last_opened_at: datetime | None

    @classmethod
    def from_state(cls, state: UserGraphState) -> "UserGraphStateResponse":
        return cls(
            starred=state.starred,
            last_opened_at=state.last_opened_at,
        )


class GraphBrowserLocationResponse(SavedGraphApiModel):
    id: UUID
    slug: str
    name: str
    kind: WorkspaceKind


class GraphBrowserFolderResponse(SavedGraphApiModel):
    id: UUID
    name: str


class GraphBrowserCreatorResponse(SavedGraphApiModel):
    id: UUID
    display_name: str | None


class GraphBrowserDraftResponse(SavedGraphApiModel):
    name: str
    head_sequence: int = Field(ge=0)
    checkpoint_sequence: int = Field(ge=0)
    checkpoint_revision: int = Field(ge=1)
    updated_at: datetime
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)


class GraphBrowserItemResponse(SavedGraphApiModel):
    id: UUID
    location: GraphBrowserLocationResponse
    folder: GraphBrowserFolderResponse | None
    archived: bool
    archived_at: datetime | None
    starred: bool
    last_opened_at: datetime | None
    updated_at: datetime
    draft: GraphBrowserDraftResponse
    creator: GraphBrowserCreatorResponse | None

    @classmethod
    def from_item(cls, item: GraphBrowserItem) -> "GraphBrowserItemResponse":
        updated_at = item.draft.updated_at
        if (
            item.organization_updated_at is not None
            and item.organization_updated_at > updated_at
        ):
            updated_at = item.organization_updated_at
        return cls(
            id=item.id,
            location=GraphBrowserLocationResponse(
                id=item.location.id,
                slug=item.location.slug,
                name=item.location.name,
                kind=item.location.kind,
            ),
            folder=(
                None
                if item.folder is None
                else GraphBrowserFolderResponse(
                    id=item.folder.id,
                    name=item.folder.name,
                )
            ),
            archived=item.is_archived,
            archived_at=item.archived_at,
            starred=item.starred,
            last_opened_at=item.last_opened_at,
            updated_at=updated_at,
            draft=GraphBrowserDraftResponse(
                name=item.draft.name,
                head_sequence=item.draft.head_sequence,
                checkpoint_sequence=item.draft.checkpoint_sequence,
                checkpoint_revision=item.draft.checkpoint_revision,
                updated_at=item.draft.updated_at,
                node_count=item.draft.node_count,
                edge_count=item.draft.edge_count,
            ),
            creator=(
                None
                if item.creator is None
                else GraphBrowserCreatorResponse(
                    id=item.creator.id,
                    display_name=item.creator.display_name,
                )
            ),
        )


class GraphBrowserListResponse(SavedGraphApiModel):
    graphs: list[GraphBrowserItemResponse]

    @classmethod
    def from_items(cls, items: list[GraphBrowserItem]) -> "GraphBrowserListResponse":
        return cls(graphs=[GraphBrowserItemResponse.from_item(item) for item in items])


class CollaborativeHeadResponse(SavedGraphApiModel):
    graph_id: UUID
    room_epoch: UUID
    collaboration_sequence: int
    checkpoint_sequence: int
    checkpoint_revision: int
    name: str
    updated_at: datetime
    nodes: list[SavedGraphNodeModel]
    edges: list[SavedGraphEdgeModel]
    presentation: GraphPresentationDocumentModel = Field(
        default_factory=GraphPresentationDocumentModel,
    )

    @classmethod
    def from_head(cls, head: CollaborativeGraphHead) -> "CollaborativeHeadResponse":
        return cls(
            graph_id=head.graph_id,
            room_epoch=head.room_epoch,
            collaboration_sequence=head.collaboration_sequence,
            checkpoint_sequence=head.checkpoint_sequence,
            checkpoint_revision=head.checkpoint_revision,
            name=head.name,
            updated_at=head.updated_at,
            nodes=[
                SavedGraphNodeModel.from_domain(node) for node in head.document.nodes
            ],
            edges=[
                SavedGraphEdgeModel.from_domain(edge) for edge in head.document.edges
            ],
            presentation=GraphPresentationDocumentModel.from_domain(
                head.document.presentation
            ),
        )


class SubmitGraphCommandRequest(SavedGraphApiModel):
    command_id: UUID
    room_epoch: UUID
    observed_sequence: int = Field(ge=0)
    command: GraphCommand


class GraphCommandReceiptResponse(SavedGraphApiModel):
    command_id: UUID
    outcome: CommandReceiptOutcome
    accepted_sequence: int
    room_epoch: UUID
    deduplicated: bool

    @classmethod
    def from_receipt(
        cls,
        receipt: GraphCommandReceipt,
    ) -> "GraphCommandReceiptResponse":
        return cls(
            command_id=receipt.command_id,
            outcome=receipt.outcome,
            accepted_sequence=receipt.accepted_sequence,
            room_epoch=receipt.room_epoch,
            deduplicated=receipt.outcome is CommandReceiptOutcome.IDEMPOTENT_REPLAY,
        )


class SubmitGraphCommandResponse(SavedGraphApiModel):
    head: CollaborativeHeadResponse
    receipt: GraphCommandReceiptResponse


class CheckpointGraphRequest(SavedGraphApiModel):
    expected_room_epoch: UUID
    expected_sequence: int = Field(ge=0)


class CheckpointGraphResponse(SavedGraphApiModel):
    head: CollaborativeHeadResponse
    saved_revision: int


class CopyExactHeadRequest(SavedGraphApiModel):
    source_workspace_id: UUID
    source_graph_id: UUID
    expected_room_epoch: UUID
    expected_sequence: int = Field(ge=0)
    command_id: UUID
    name: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

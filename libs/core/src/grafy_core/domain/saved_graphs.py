from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite
from types import MappingProxyType
from typing import Annotated, ClassVar, Literal, Self, cast
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.conversions import MAX_ARTIFACT_CONVERSION_HOPS
from grafy_core.domain.errors import SavedGraphRevisionConflictError
from grafy_core.domain.identity import WorkspaceKind
from grafy_core.domain.plugin_identity import PluginReleaseScope


GraphIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class SavedGraphValue(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class GraphPoint(SavedGraphValue):
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


class SavedGraphNodeLayout(SavedGraphValue):
    """Canvas chrome sizes for a node shell and its artifact appendix."""

    width: float | None = Field(default=None, ge=260, le=GRAPH_LAYOUT_DIMENSION_MAX)
    body_height: float | None = Field(default=None, ge=96, le=GRAPH_LAYOUT_DIMENSION_MAX)
    appendix_height: float | None = Field(
        default=None, ge=120, le=GRAPH_LAYOUT_DIMENSION_MAX
    )

    @model_validator(mode="after")
    def require_at_least_one_dimension(self) -> Self:
        validate_graph_layout_dimensions(self.width, self.body_height, self.appendix_height)
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


class SavedGraphInputPlug(SavedGraphValue):
    id: GraphIdentifier
    port: GraphIdentifier


class SavedGraphArtifactTypeBinding(SavedGraphValue):
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


SavedGraphNodeKind = Literal["builtin", "plugin", "module"]


def validate_graph_node_release_pin(kind: SavedGraphNodeKind, *, has_pin: bool) -> None:
    if kind == "plugin":
        if not has_pin:
            raise ValueError(
                "Plugin node must pin an exact Plugin release with scope, slug, "
                "and revision"
            )
    elif has_pin:
        raise ValueError(f"{kind} node cannot carry a Plugin release pin")


class SavedGraphPluginReleasePin(SavedGraphValue):
    """Exact scoped Plugin release identity pinned on one graph node.

    The pin is independent from the operator identity: publishing revision
    N+1 never moves a node pinned to revision N. Workspace membership for a
    Workspace release comes from the owning graph.
    """

    scope: PluginReleaseScope
    slug: GraphIdentifier
    revision: int = Field(ge=1)

    @field_validator("slug", mode="before")
    @classmethod
    def validate_slug(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        if value.strip() == "":
            raise ValueError("Saved graph Plugin release pin slug must not be empty")
        if value != value.strip():
            raise ValueError(
                "Saved graph Plugin release pin slug must not have surrounding "
                "whitespace"
            )
        if len(value) > 100:
            raise ValueError(
                "Saved graph Plugin release pin slug must be at most 100 characters"
            )
        return value.strip()


class BuiltinNodeRef(SavedGraphValue):
    kind: Literal["builtin"] = "builtin"
    operator_id: GraphIdentifier
    operator_version: int = Field(ge=1)


class PluginNodeRef(SavedGraphValue):
    kind: Literal["plugin"] = "plugin"
    operator_id: GraphIdentifier
    operator_version: int = Field(ge=1)
    plugin_release_pin: SavedGraphPluginReleasePin


class ModuleNodeRef(SavedGraphValue):
    kind: Literal["module"] = "module"
    operator_id: GraphIdentifier
    operator_version: int = Field(ge=1)


SavedGraphNodeRef = Annotated[
    BuiltinNodeRef | PluginNodeRef | ModuleNodeRef,
    Field(discriminator="kind"),
]


class SavedGraphNode(SavedGraphValue):
    kind: SavedGraphNodeKind
    id: GraphIdentifier
    operator_id: GraphIdentifier
    operator_version: int = Field(ge=1)
    config: Mapping[str, object] = Field(default_factory=dict)
    position: GraphPoint
    layout: SavedGraphNodeLayout | None = None
    input_plugs: tuple[SavedGraphInputPlug, ...] = ()
    artifact_type_bindings: tuple[SavedGraphArtifactTypeBinding, ...] = ()
    plugin_release_pin: SavedGraphPluginReleasePin | None = None

    @field_validator("plugin_release_pin", mode="before")
    @classmethod
    def validate_plugin_release_pin_shape(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        raw = cast(Mapping[object, object], value)
        expected_fields = {"scope", "slug", "revision"}
        if set(raw) != expected_fields:
            raise ValueError(
                "Saved graph Plugin release pin must contain exactly scope, slug, "
                "and revision"
            )
        return dict(raw)

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
    def validate_kind_and_pin(self) -> Self:
        validate_graph_node_release_pin(self.kind, has_pin=self.plugin_release_pin is not None)
        return self

    @model_validator(mode="after")
    def validate_artifact_type_bindings(self) -> Self:
        variables = [binding.variable for binding in self.artifact_type_bindings]
        if len(variables) != len(set(variables)):
            raise ValueError(
                "Saved graph node artifact type binding variables must be unique"
            )
        return self

    def node_ref(self) -> SavedGraphNodeRef:
        if self.kind == "builtin":
            return BuiltinNodeRef(
                operator_id=self.operator_id,
                operator_version=self.operator_version,
            )
        if self.kind == "plugin":
            if self.plugin_release_pin is None:
                raise ValueError("Plugin node is missing its release pin")
            return PluginNodeRef(
                operator_id=self.operator_id,
                operator_version=self.operator_version,
                plugin_release_pin=self.plugin_release_pin,
            )
        return ModuleNodeRef(
            operator_id=self.operator_id,
            operator_version=self.operator_version,
        )

    def artifact_type_binding_map(self) -> dict[str, ArtifactTypeKey]:
        return {
            binding.variable: binding.artifact_type
            for binding in self.artifact_type_bindings
        }


class SavedGraphProjection(SavedGraphValue):
    path: tuple[GraphIdentifier, ...] = Field(min_length=1)


class SavedGraphConversion(SavedGraphValue):
    id: GraphIdentifier
    version: int = Field(ge=1)


def normalize_saved_graph_edge_conversion(value: object) -> object:
    """Accept the legacy singular conversion without changing canonical output."""
    if not isinstance(value, Mapping):
        return value
    raw = cast(Mapping[object, object], value)
    if "conversion" not in raw:
        return dict(raw)
    if "conversion_path" in raw:
        raise ValueError(
            "Saved graph edge cannot declare both conversion and conversion_path"
        )
    migrated = dict(raw)
    conversion = migrated.pop("conversion")
    migrated["conversion_path"] = [] if conversion is None else [conversion]
    return migrated


class SavedGraphEdge(SavedGraphValue):
    id: GraphIdentifier
    enabled: bool = True
    from_node: GraphIdentifier
    from_port: GraphIdentifier
    to_node: GraphIdentifier
    to_port: GraphIdentifier
    to_plug: GraphIdentifier | None = None
    collection_mode: Literal["direct", "map"] = "direct"
    projection: SavedGraphProjection | None = None
    conversion_path: tuple[SavedGraphConversion, ...] = Field(
        default=(),
        max_length=MAX_ARTIFACT_CONVERSION_HOPS,
    )
    route_offset: GraphPoint | None = None

    migrate_singular_conversion = model_validator(mode="before")(
        normalize_saved_graph_edge_conversion
    )


class GraphPresentationViewer(SavedGraphValue):
    id: GraphIdentifier
    position: GraphPoint
    layout: SavedGraphNodeLayout | None = None
    mode: str | None = Field(default=None, max_length=255)

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
_LEGACY_ANNOTATION_COLORS: Mapping[str, str] = MappingProxyType(
    {
        "slate": "#475569",
        "amber": "#B45309",
        "rose": "#BE123C",
        "emerald": "#047857",
        "sky": "#0369A1",
        "violet": "#6D28D9",
    }
)


class SavedGraphAnnotationLayout(SavedGraphValue):
    """Axis-aligned size for a presentation annotation on the canvas."""

    width: float = Field(ge=24, le=GRAPH_LAYOUT_DIMENSION_MAX)
    height: float = Field(ge=24, le=GRAPH_LAYOUT_DIMENSION_MAX)


class GraphPresentationAnnotation(SavedGraphValue):
    """Non-executable canvas decoration used to document a graph (Miro-like)."""

    id: GraphIdentifier
    kind: AnnotationKind
    position: GraphPoint
    layout: SavedGraphAnnotationLayout
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
    def normalize_annotation_color(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        legacy = _LEGACY_ANNOTATION_COLORS.get(value)
        if legacy is not None:
            return legacy
        if len(value) == 7 and value.startswith("#"):
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


class GraphPresentationLink(SavedGraphValue):
    id: GraphIdentifier
    source_node_id: GraphIdentifier
    source_port_name: GraphIdentifier
    target_viewer_id: GraphIdentifier
    # Optional field projection applied when previewing the linked output.
    projection: SavedGraphProjection | None = None
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


class GraphPresentationBindingMapping(SavedGraphValue):
    source_field: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]
    target_field: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]


class GraphPresentationBinding(SavedGraphValue):
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


class GraphPresentationDocument(SavedGraphValue):
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

    def prune_for_removed_viewers(
        self,
        removed_viewer_ids: set[str],
    ) -> "GraphPresentationDocument":
        if not removed_viewer_ids:
            return self
        viewers = tuple(
            viewer for viewer in self.viewers if viewer.id not in removed_viewer_ids
        )
        known = {viewer.id for viewer in viewers}
        return GraphPresentationDocument(
            viewers=viewers,
            links=tuple(link for link in self.links if link.target_viewer_id in known),
            bindings=tuple(
                binding
                for binding in self.bindings
                if binding.source_viewer_id in known
                and binding.target_viewer_id in known
            ),
            annotations=self.annotations,
        )


def empty_presentation() -> GraphPresentationDocument:
    return GraphPresentationDocument()


SAVED_GRAPH_SCHEMA_VERSION = 6


class SavedGraphDocument(SavedGraphValue):
    schema_version: Literal[6] = SAVED_GRAPH_SCHEMA_VERSION
    nodes: tuple[SavedGraphNode, ...] = ()
    edges: tuple[SavedGraphEdge, ...] = ()
    presentation: GraphPresentationDocument = Field(default_factory=empty_presentation)

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_document(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        raw = cast(Mapping[object, object], value)
        version = raw.get("schema_version")
        if version is None:
            return value
        if version != SAVED_GRAPH_SCHEMA_VERSION:
            raise ValueError(
                "Saved graph document schema_version "
                f"{version!r} is not supported; expected "
                f"{SAVED_GRAPH_SCHEMA_VERSION}"
            )
        return value

    @model_validator(mode="after")
    def validate_structure(self) -> Self:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Saved graph node ids must be unique")

        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("Saved graph edge ids must be unique")

        known_nodes = set(node_ids)
        plugs_by_node: dict[str, dict[str, SavedGraphInputPlug]] = {}
        for node in self.nodes:
            plug_ids = [plug.id for plug in node.input_plugs]
            if len(plug_ids) != len(set(plug_ids)):
                raise ValueError(
                    f"Saved graph input plug ids must be unique within node {node.id}"
                )
            plugs_by_node[node.id] = {plug.id: plug for plug in node.input_plugs}

        connected_plugs: set[tuple[str, str]] = set()
        for edge in self.edges:
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
        nodes: tuple[SavedGraphNode, ...] | None = None,
        edges: tuple[SavedGraphEdge, ...] | None = None,
        presentation: GraphPresentationDocument | None = None,
    ) -> "SavedGraphDocument":
        return SavedGraphDocument(
            nodes=self.nodes if nodes is None else nodes,
            edges=self.edges if edges is None else edges,
            presentation=(self.presentation if presentation is None else presentation),
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _validated_graph_name(value: str) -> str:
    name = value.strip()
    if name == "":
        raise ValueError("Saved graph name must not be blank")
    if len(name) > 160:
        raise ValueError("Saved graph name must be at most 160 characters")
    return name


def _validated_folder_name(value: str) -> str:
    name = value.strip()
    if name == "":
        raise ValueError("Graph folder name must not be blank")
    if len(name) > 160:
        raise ValueError("Graph folder name must be at most 160 characters")
    return name


@dataclass
class GraphFolder:
    workspace_id: UUID
    name: str
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        self.name = _validated_folder_name(self.name)
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Graph folder timestamps must be timezone-aware")

    def rename(self, name: str, *, updated_at: datetime | None = None) -> None:
        replacement_time = updated_at or _utc_now()
        if replacement_time.tzinfo is None:
            raise ValueError("Graph folder timestamps must be timezone-aware")
        self.name = _validated_folder_name(name)
        self.updated_at = replacement_time


@dataclass
class UserGraphState:
    workspace_id: UUID
    graph_id: UUID
    user_id: UUID
    starred: bool = False
    last_opened_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.last_opened_at is not None and self.last_opened_at.tzinfo is None:
            raise ValueError("Graph last-opened timestamp must be timezone-aware")

    def set_starred(self, starred: bool) -> None:
        self.starred = starred

    def record_open(self, *, opened_at: datetime | None = None) -> None:
        opened_time = opened_at or _utc_now()
        if opened_time.tzinfo is None:
            raise ValueError("Graph last-opened timestamp must be timezone-aware")
        if self.last_opened_at is None or opened_time > self.last_opened_at:
            self.last_opened_at = opened_time


@dataclass
class GraphOrganization:
    workspace_id: UUID
    graph_id: UUID
    folder_id: UUID | None = None
    archived_at: datetime | None = None
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if self.updated_at.tzinfo is None:
            raise ValueError("Graph organization timestamp must be timezone-aware")
        if self.archived_at is not None and self.archived_at.tzinfo is None:
            raise ValueError("Graph archive timestamp must be timezone-aware")

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def assign_folder(
        self,
        folder_id: UUID | None,
        *,
        updated_at: datetime | None = None,
    ) -> None:
        replacement_time = updated_at or _utc_now()
        if replacement_time.tzinfo is None:
            raise ValueError("Graph organization timestamp must be timezone-aware")
        self.folder_id = folder_id
        self.updated_at = replacement_time

    def archive(self, *, archived_at: datetime | None = None) -> None:
        archive_time = archived_at or _utc_now()
        if archive_time.tzinfo is None:
            raise ValueError("Graph archive timestamp must be timezone-aware")
        if self.archived_at is None:
            self.archived_at = archive_time
            self.updated_at = archive_time

    def restore(self, *, restored_at: datetime | None = None) -> None:
        restore_time = restored_at or _utc_now()
        if restore_time.tzinfo is None:
            raise ValueError("Graph restore timestamp must be timezone-aware")
        if self.archived_at is not None:
            self.archived_at = None
            self.updated_at = restore_time


@dataclass
class SavedGraph:
    workspace_id: UUID
    name: str
    document: SavedGraphDocument
    created_by_user_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    revision: int = 1
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        self.name = _validated_graph_name(self.name)
        if self.revision < 1:
            raise ValueError("Saved graph revision must be at least 1")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Saved graph timestamps must be timezone-aware")

    def replace(
        self,
        *,
        name: str,
        document: SavedGraphDocument,
        expected_revision: int,
        updated_at: datetime | None = None,
    ) -> None:
        self.ensure_revision(expected_revision)
        validated_name = _validated_graph_name(name)
        replacement_time = updated_at or _utc_now()
        if replacement_time.tzinfo is None:
            raise ValueError("Saved graph timestamps must be timezone-aware")

        self.name = validated_name
        self.document = document
        self.revision += 1
        self.updated_at = replacement_time

    def snapshot(self) -> "SavedGraphRevision":
        return SavedGraphRevision(
            workspace_id=self.workspace_id,
            graph_id=self.id,
            revision=self.revision,
            name=self.name,
            document=self.document,
            created_at=self.updated_at,
        )

    def ensure_revision(self, expected_revision: int) -> None:
        if expected_revision != self.revision:
            raise SavedGraphRevisionConflictError(
                graph_id=self.id,
                expected_revision=expected_revision,
                actual_revision=self.revision,
            )


@dataclass(frozen=True, slots=True)
class SavedGraphRevision:
    workspace_id: UUID
    graph_id: UUID
    revision: int
    name: str
    document: SavedGraphDocument
    created_at: datetime

    @property
    def id(self) -> UUID:
        return self.graph_id

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _validated_graph_name(self.name))
        if self.revision < 1:
            raise ValueError("Saved graph snapshot revision must be at least 1")
        if self.created_at.tzinfo is None:
            raise ValueError("Saved graph snapshot timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class GraphBrowserLocation:
    id: UUID
    slug: str
    name: str
    kind: WorkspaceKind


@dataclass(frozen=True, slots=True)
class GraphBrowserFolder:
    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class GraphBrowserCreator:
    id: UUID
    display_name: str | None


@dataclass(frozen=True, slots=True)
class GraphBrowserDraft:
    name: str
    head_sequence: int
    checkpoint_sequence: int
    checkpoint_revision: int
    updated_at: datetime
    node_count: int
    edge_count: int


@dataclass(frozen=True, slots=True)
class GraphBrowserItem:
    id: UUID
    draft: GraphBrowserDraft
    location: GraphBrowserLocation
    folder: GraphBrowserFolder | None
    archived_at: datetime | None
    starred: bool
    last_opened_at: datetime | None
    organization_updated_at: datetime | None
    creator: GraphBrowserCreator | None

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

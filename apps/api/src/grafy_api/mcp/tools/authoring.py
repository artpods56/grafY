"""Whole-Graph authoring and raw command batches.

``author_graph`` builds a Graph with ``GraphBuilder`` against the live node catalog
and writes it in one batch; the canvas tools (``grafy_api.mcp.tools.canvas``) make
the small edits a user makes by hand. ``apply_project_commands`` is the escape hatch
for any command the task-shaped tools do not cover.
"""

from collections.abc import Mapping
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from fastmcp.exceptions import ToolError
from grafy_client import CardHandle, GraphBuilder, NodeHandle
from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence
from grafy_core.domain.collaboration import PROJECT_COMMAND_ADAPTER, ProjectCommand
from grafy_core.domain.graph_documents import GraphConversion, GraphPoint
from pydantic import Field, ValidationError

from grafy_api.mcp.context import (
    EDIT,
    IDEMPOTENT_EDIT,
    ToolModel,
    dump,
    grafy,
    tool,
    type_key,
)


class PortRef(ToolModel):
    node: str = Field(description="Node id within the graph")
    port: str = Field(description="Port name on that node")


class ArtifactSpec(ToolModel):
    artifact_id: UUID
    artifact_type: str = Field(
        description="Artifact type with version, for example 'file.tiff@1'"
    )
    content_hash: str | None = Field(
        default=None,
        description=(
            "The artifact's sha256 (`artifact.sha256` in list_library). Omit it for "
            "a Library artifact and it is looked up"
        ),
    )


class NodeSpec(ToolModel):
    id: str = Field(description="Node id, unique within the graph")
    operator_id: str
    operator_version: int | None = Field(
        default=None, description="Pin a version; default: the only one in catalog"
    )
    config: dict[str, Any] = Field(default_factory=dict)
    bindings: dict[str, str] = Field(
        default_factory=dict,
        description="Artifact type variable bindings, variable -> 'type@version'",
    )
    x: float | None = None
    y: float | None = None


class ConversionSpec(ToolModel):
    id: str
    version: int = Field(ge=1)


class ConnectionSpec(ToolModel):
    source: PortRef
    target: PortRef
    collection_mode: Literal["direct", "map"] = "direct"
    conversion_path: list[ConversionSpec] = Field(default_factory=list[ConversionSpec])


class OriginSpec(ToolModel):
    """A stored artifact (or ordered list of them) fed straight into an input."""

    target: PortRef
    artifacts: list[ArtifactSpec] = Field(
        min_length=1,
        description="One artifact, or several to form an ordered sequence",
    )
    as_sequence: bool = Field(
        default=False, description="Pass a single artifact as a one-item sequence"
    )
    card: str | None = Field(
        default=None, description="Id of a library card in `cards` that owns it"
    )
    collection_mode: Literal["direct", "map"] = "direct"
    conversion_path: list[ConversionSpec] = Field(default_factory=list[ConversionSpec])


class CardSpec(ToolModel):
    """An artifact card: shows a stored artifact, or follows one node output."""

    id: str = Field(description="Card id; must start with 'artifact-viewer-'")
    artifacts: list[ArtifactSpec] = Field(
        default_factory=list[ArtifactSpec], description="Library card content"
    )
    follows: PortRef | None = Field(
        default=None, description="Output card: the node output it shows"
    )
    projection: list[str] = Field(
        default_factory=list, description="Nested field path shown by an output card"
    )
    x: float | None = None
    y: float | None = None


class CardBindingSpec(ToolModel):
    """Selecting rows or features on one card filters/highlights another."""

    source_card: str
    target_card: str
    fields: dict[str, str] = Field(
        min_length=1, description="source field -> target field that must be equal"
    )
    effects: list[Literal["filter", "highlight", "focus"]] = Field(
        default_factory=lambda: ["highlight", "focus"], min_length=1
    )


type Hashes = Mapping[UUID, str | None]


def artifact_ref(spec: ArtifactSpec, hashes: Hashes) -> ArtifactRef:
    """The exact reference: an origin naming a different hash is not the artifact."""
    content_hash = spec.content_hash
    if content_hash is None:
        if spec.artifact_id not in hashes:
            raise ToolError(
                f"Artifact {spec.artifact_id} is not in the Library; pass its "
                "content_hash"
            )
        content_hash = hashes[spec.artifact_id]
    return ArtifactRef.from_key(
        artifact_id=spec.artifact_id,
        key=type_key(spec.artifact_type),
        content_hash=content_hash,
    )


def artifact_value(
    specs: list[ArtifactSpec], hashes: Hashes, *, as_sequence: bool
) -> ArtifactRef | ArtifactRefSequence:
    refs = [artifact_ref(spec, hashes) for spec in specs]
    if len(refs) == 1 and not as_sequence:
        return refs[0]
    key = type_key(specs[0].artifact_type)
    for spec in specs[1:]:
        if type_key(spec.artifact_type) != key:
            raise ToolError("Every artifact in one sequence must share its type")
    return ArtifactRefSequence.from_key(key=key, item_refs=refs)


def needs_library_hashes(specs: list[ArtifactSpec]) -> bool:
    for spec in specs:
        if spec.content_hash is None:
            return True
    return False


def point(x: float | None, y: float | None) -> GraphPoint | None:
    if x is None or y is None:
        return None
    return GraphPoint(x=x, y=y)


def conversions(specs: list[ConversionSpec]) -> tuple[GraphConversion, ...]:
    return tuple(GraphConversion(id=spec.id, version=spec.version) for spec in specs)


def _add_nodes(builder: GraphBuilder, nodes: list[NodeSpec]) -> dict[str, NodeHandle]:
    handles: dict[str, NodeHandle] = {}
    for spec in nodes:
        handles[spec.id] = builder.add_catalog_node(
            spec.operator_id,
            spec.config,
            operator_version=spec.operator_version,
            bindings={name: type_key(value) for name, value in spec.bindings.items()},
            position=point(spec.x, spec.y),
            node_id=spec.id,
        )
    return handles


def _node(handles: Mapping[str, NodeHandle], ref: PortRef) -> NodeHandle:
    handle = handles.get(ref.node)
    if handle is None:
        raise ToolError(f"No node {ref.node!r} in this graph spec")
    return handle


def _card(cards: Mapping[str, CardHandle], card_id: str) -> CardHandle:
    card = cards.get(card_id)
    if card is None:
        raise ToolError(f"No card {card_id!r} in this graph spec")
    return card


async def author_graph(
    project_id: UUID,
    graph_id: str,
    nodes: list[NodeSpec],
    connections: list[ConnectionSpec] | None = None,
    origins: list[OriginSpec] | None = None,
    cards: list[CardSpec] | None = None,
    card_bindings: list[CardBindingSpec] | None = None,
    graph_name: str | None = None,
    checkpoint: bool = True,
) -> dict[str, Any]:
    """Create or replace one whole Graph from a spec, validated against the catalog.

    Nodes, connections and origins are checked for operator identity, config
    schema, port shapes and artifact types before anything is sent. The Graph is
    then written in one validated batch (add or replace) and, by default,
    checkpointed. Cards show artifacts on the canvas: give `artifacts` for a
    Library card or `follows` for a card that shows a node output. To change part
    of an existing Graph, use the canvas tools instead (add_node, connect, ...).
    """
    all_artifacts = [
        artifact
        for spec in [*(cards or []), *(origins or [])]
        for artifact in spec.artifacts
    ]
    async with grafy() as (client, workspace_id):
        hashes: dict[UUID, str | None] = {}
        if needs_library_hashes(all_artifacts):
            for item in await client.library.list(workspace_id):
                hashes[item.artifact.artifact_id] = item.artifact.sha256
        builder = GraphBuilder(await client.catalog.get(workspace_id))
        handles = _add_nodes(builder, nodes)
        for connection in connections or []:
            builder.connect(
                _node(handles, connection.source).output(connection.source.port),
                _node(handles, connection.target).input(connection.target.port),
                conversion_path=conversions(connection.conversion_path),
                collection_mode=connection.collection_mode,
            )
        card_handles: dict[str, CardHandle] = {}
        for card in cards or []:
            if (card.follows is None) == (not card.artifacts):
                raise ToolError(
                    f"Card {card.id!r} needs exactly one of artifacts or follows"
                )
            position = point(card.x, card.y)
            if card.follows is not None:
                card_handles[card.id] = builder.add_output_card(
                    _node(handles, card.follows).output(card.follows.port),
                    position=position,
                    projection=card.projection,
                    card_id=card.id,
                )
            else:
                card_handles[card.id] = builder.add_artifact_card(
                    artifact_value(card.artifacts, hashes, as_sequence=False),
                    position=position,
                    card_id=card.id,
                )
        for origin in origins or []:
            target = _node(handles, origin.target).input(origin.target.port)
            source = (
                _card(card_handles, origin.card)
                if origin.card is not None
                else artifact_value(
                    origin.artifacts, hashes, as_sequence=origin.as_sequence
                )
            )
            builder.place(
                target,
                source,
                conversion_path=conversions(origin.conversion_path),
                collection_mode=origin.collection_mode,
            )
        for binding in card_bindings or []:
            _ = builder.bind_cards(
                _card(card_handles, binding.source_card),
                _card(card_handles, binding.target_card),
                binding.fields,
                effects=binding.effects,
            )
        head = await client.projects.upsert_graph(
            workspace_id,
            project_id,
            graph_id=graph_id,
            document=builder.build(),
            name=graph_name,
            checkpoint=checkpoint,
        )
    return {
        "project_id": str(head.project_id),
        "graph_id": graph_id,
        "collaboration_sequence": head.collaboration_sequence,
        "checkpoint_revision": head.checkpoint_revision,
        "checkpointed": head.collaboration_sequence == head.checkpoint_sequence,
    }


async def apply_project_commands(
    project_id: UUID,
    commands: Annotated[
        list[dict[str, Any]],
        Field(
            min_length=1,
            description=(
                "Project commands, each with a `kind` (rename_project, add_graph, "
                "rename_graph, remove_graph, refresh_node, add_call_node, in_graph)"
                "; `in_graph` wraps one graph command such as add_node, add_edge, "
                "move_nodes, update_node_configuration, replace_presentation or "
                "remove_nodes"
            ),
        ),
    ],
    checkpoint: bool = False,
) -> dict[str, Any]:
    """Apply raw project commands as one batch, accepted or rejected as a whole.

    Prefer the canvas tools; this is for a command none of them covers.
    """
    try:
        parsed: list[ProjectCommand] = [
            PROJECT_COMMAND_ADAPTER.validate_python(command) for command in commands
        ]
    except ValidationError as exc:
        raise ToolError(f"Invalid project command: {exc}") from exc
    async with grafy() as (client, workspace_id):
        submitted = await client.projects.apply(
            workspace_id, project_id, parsed, checkpoint=checkpoint
        )
    return {
        "receipt": dump(submitted.receipt),
        "collaboration_sequence": submitted.head.collaboration_sequence,
        "checkpoint_revision": submitted.head.checkpoint_revision,
    }


async def checkpoint_project(project_id: UUID) -> dict[str, Any]:
    """Record the live head as a new immutable checkpoint (a restore point)."""
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
        if head.collaboration_sequence == head.checkpoint_sequence:
            return {"checkpoint_revision": head.checkpoint_revision, "new": False}
        head = await client.projects.checkpoint(workspace_id, project_id, head=head)
    return {"checkpoint_revision": head.checkpoint_revision, "new": True}


TOOLS: Final = (
    tool(author_graph, EDIT, tags={"authoring"}),
    tool(apply_project_commands, EDIT, tags={"authoring"}),
    tool(checkpoint_project, IDEMPOTENT_EDIT, tags={"authoring", "history"}),
)

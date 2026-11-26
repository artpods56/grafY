"""The canvas: the edits a person makes by hand in the Workbench.

Each tool reads the live head, edits a copy of one Graph's document, and submits
the difference as the fine-grained commands the Workbench itself sends
(``grafy_client.graph_commands``): ``move_nodes`` for a drag, ``add_edge`` for a
wire, ``update_node_configuration`` for a field. Peers in the room see the same
events a collaborator's gestures produce, a concurrent edit elsewhere in the Graph
does not conflict, and every command carries the value it expects to replace, so a
stale edit is refused instead of overwriting someone else's change.

Wiring goes through ``GraphBuilder.from_document``, so a connection or a placed
artifact is checked against the node catalog (port names, shapes, artifact types,
conversions, input plugs, cycles) before anything is sent.
"""

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from fastmcp.exceptions import ToolError
from grafy_client import (
    CardHandle,
    GrafyClient,
    GraphBuilder,
    NodeCatalog,
    ProjectHead,
    graph_commands,
)
from grafy_core.domain.collaboration import (
    AddCallNodeCommand,
    InGraphCommand,
    ProjectCommand,
)
from grafy_core.domain.graph_documents import (
    AgentToolLink,
    GraphAgent,
    GraphAnnotationLayout,
    GraphArtifactTypeBinding,
    GraphDocument,
    GraphEdge,
    GraphNode,
    GraphNodeLayout,
    GraphPoint,
    GraphPresentationAnnotation,
    GraphPresentationDocument,
    GraphPresentationViewer,
    GraphPresentationViewerLayout,
)
from grafy_core.schema_contracts import validate_json_schema_value
from pydantic import Field, ValidationError

from grafy_api.mcp.context import (
    DESTRUCTIVE,
    EDIT,
    IDEMPOTENT_EDIT,
    READ,
    ToolModel,
    grafy,
    graph_of,
    tool,
    type_key,
    type_label,
)
from grafy_api.mcp.tools.authoring import (
    ArtifactSpec,
    ConversionSpec,
    NodeSpec,
    PortRef,
    artifact_value,
    conversions,
    needs_library_hashes,
    point,
)

# Canvas spacing the Workbench's own auto-placement uses, near enough.
_COLUMN_WIDTH: Final = 380.0
_ROW_HEIGHT: Final = 240.0
_CARD_OFFSET: Final = 340.0

type Transform = Callable[[GraphDocument], GraphDocument]


class Move(ToolModel):
    """Where one canvas item goes: an absolute point, or a nudge from where it is."""

    id: str = Field(description="A node, card, annotation or Agent id")
    x: float | None = Field(default=None, description="New left edge")
    y: float | None = Field(default=None, description="New top edge")
    dx: float = Field(default=0, description="Shift right (negative: left)")
    dy: float = Field(default=0, description="Shift down (negative: up)")


class AgentToolSpec(ToolModel):
    node_id: str
    name: str = Field(description="What the model calls it: lower_snake_case")
    description: str = ""
    filled_ports: list[str] = Field(
        default_factory=list, description="Open inputs the model fills"
    )
    returned_ports: list[str] = Field(
        default_factory=list, description="Outputs returned; empty means all"
    )


# --- reading -----------------------------------------------------------------


def _port_label(node: str, port: str, plug: str | None = None) -> str:
    return f"{node}.{port}" if plug is None else f"{node}.{port}[{plug}]"


def canvas_view(head: ProjectHead, graph_id: str) -> dict[str, Any]:
    graph = graph_of(head, graph_id)
    document = graph.document
    followed: dict[str, str] = {
        link.target_viewer_id: _port_label(link.source_node_id, link.source_port_name)
        for link in document.presentation.links
    }
    return {
        "graph_id": graph.id,
        "name": graph.name,
        "collaboration_sequence": head.collaboration_sequence,
        "nodes": [
            {
                "id": node.id,
                "kind": node.kind,
                "operator": f"{node.operator_id}@{node.operator_version}",
                "x": node.position.x,
                "y": node.position.y,
                **({} if node.layout is None else {"layout": node.layout.model_dump()}),
                "config": node.config_dict(),
                **(
                    {}
                    if not node.artifact_type_bindings
                    else {
                        "bindings": {
                            binding.variable: type_label(binding.artifact_type)
                            for binding in node.artifact_type_bindings
                        }
                    }
                ),
                **(
                    {}
                    if not node.input_plugs
                    else {
                        "input_plugs": [
                            {"id": plug.id, "port": plug.port}
                            for plug in node.input_plugs
                        ]
                    }
                ),
            }
            for node in document.nodes
        ],
        "connections": [
            {
                "id": edge.id,
                "from": _port_label(edge.from_node, edge.from_port),
                "to": _port_label(edge.to_node, edge.to_port, edge.to_plug),
                **({} if edge.enabled else {"enabled": False}),
                **(
                    {}
                    if edge.collection_mode == "direct"
                    else {"collection_mode": edge.collection_mode}
                ),
                **(
                    {}
                    if not edge.conversion_path
                    else {
                        "conversion_path": [
                            f"{step.id}@{step.version}" for step in edge.conversion_path
                        ]
                    }
                ),
            }
            for edge in document.edges
        ],
        "placed_artifacts": [
            {
                "id": origin.id,
                "to": _port_label(origin.to_node, origin.to_port, origin.to_plug),
                "value": origin.value.model_dump(mode="json"),
                **(
                    {}
                    if origin.source_card_ids is None
                    else {"from_cards": list(origin.source_card_ids)}
                ),
            }
            for origin in document.origins
        ],
        "cards": [
            {
                "id": viewer.id,
                "x": viewer.position.x,
                "y": viewer.position.y,
                **({"follows": followed[viewer.id]} if viewer.id in followed else {}),
                **(
                    {}
                    if viewer.artifact_ref is None
                    else {"artifact": viewer.artifact_ref.model_dump(mode="json")}
                ),
            }
            for viewer in document.presentation.viewers
        ],
        "card_bindings": [
            {
                "id": binding.id,
                "source_card": binding.source_viewer_id,
                "target_card": binding.target_viewer_id,
                "fields": {
                    mapping.source_field: mapping.target_field
                    for mapping in binding.mappings
                },
                "effects": list(binding.effects),
            }
            for binding in document.presentation.bindings
        ],
        "annotations": [
            {
                "id": annotation.id,
                "kind": annotation.kind,
                "x": annotation.position.x,
                "y": annotation.position.y,
                "width": annotation.layout.width,
                "height": annotation.layout.height,
                "text": annotation.text,
                "color": annotation.color,
            }
            for annotation in document.presentation.annotations
        ],
        "agents": [
            {
                "id": agent.id,
                "name": agent.name,
                "x": agent.position.x,
                "y": agent.position.y,
                "tools": [link.node_id for link in agent.tools],
            }
            for agent in document.agents
        ],
    }


async def get_canvas(project_id: UUID, graph_id: str) -> dict[str, Any]:
    """One Graph as the canvas shows it: nodes with positions and config, wires
    (`node.port` -> `node.port`), placed artifacts, cards, card bindings,
    annotations and Agents. Use the ids it lists with every other canvas tool."""
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
    return canvas_view(head, graph_id)


# --- writing -----------------------------------------------------------------


async def _commit(
    client: GrafyClient,
    workspace_id: UUID,
    project_id: UUID,
    graph_id: str,
    head: ProjectHead,
    after: GraphDocument,
    *,
    extra: Sequence[ProjectCommand] = (),
) -> dict[str, Any]:
    before = graph_of(head, graph_id).document
    commands: list[ProjectCommand] = [
        InGraphCommand(graph_id=graph_id, command=command)
        for command in graph_commands(before, after)
    ]
    commands.extend(extra)
    if not commands:
        return {
            "changed": False,
            "collaboration_sequence": head.collaboration_sequence,
        }
    submitted = await client.projects.submit_commands(
        workspace_id, project_id, head=head, commands=commands
    )
    return {
        "changed": True,
        "commands": [
            command.command.kind.value
            if isinstance(command, InGraphCommand)
            else command.kind.value
            for command in commands
        ],
        "collaboration_sequence": submitted.head.collaboration_sequence,
    }


async def _edit(
    project_id: UUID, graph_id: str, transform: Transform
) -> dict[str, Any]:
    """Read the head, transform one Graph, and submit the difference."""
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
        after = _validated(transform, graph_of(head, graph_id).document)
        return await _commit(client, workspace_id, project_id, graph_id, head, after)


def _validated(transform: Transform, document: GraphDocument) -> GraphDocument:
    try:
        return transform(document)
    except ValidationError as exc:
        violations = "; ".join(
            error["msg"].removeprefix("Value error, ") for error in exc.errors()
        )
        raise ToolError(f"That edit would leave the Graph invalid: {violations}")


def _node_or_raise(document: GraphDocument, node_id: str) -> GraphNode:
    for node in document.nodes:
        if node.id == node_id:
            return node
    raise ToolError(f"No node {node_id!r} in this Graph; see get_canvas")


def _replace_node(document: GraphDocument, updated: GraphNode) -> GraphDocument:
    return document.with_topology(
        nodes=tuple(
            updated if node.id == updated.id else node for node in document.nodes
        )
    )


def _free_point(document: GraphDocument) -> GraphPoint:
    """Right of everything on the canvas, level with its top."""
    xs = [node.position.x for node in document.nodes] + [
        viewer.position.x for viewer in document.presentation.viewers
    ]
    ys = [node.position.y for node in document.nodes]
    if not xs:
        return GraphPoint(x=0, y=0)
    return GraphPoint(x=max(xs) + _COLUMN_WIDTH, y=min(ys) if ys else 0.0)


def _validate_config(
    catalog: NodeCatalog, node: GraphNode, config: dict[str, Any]
) -> None:
    if node.kind != "builtin":
        return
    for candidate in catalog.nodes:
        if (
            candidate.operator_id == node.operator_id
            and candidate.operator_version == node.operator_version
        ):
            try:
                validate_json_schema_value(
                    json.dumps(candidate.config_schema, ensure_ascii=False), config
                )
            except ValueError as exc:
                raise ToolError(
                    f"Invalid configuration for {node.operator_id}@"
                    f"{node.operator_version}: {exc}"
                ) from exc
            return


async def add_nodes(
    project_id: UUID,
    graph_id: str,
    nodes: Annotated[
        list[NodeSpec],
        Field(
            min_length=1,
            description=(
                "Nodes to drop on the canvas. Omit x/y to place them in a row "
                "right of the existing Graph"
            ),
        ),
    ],
) -> dict[str, Any]:
    """Drop catalog nodes onto a Graph, unwired, the way dragging from the node
    list does. Operator, version, config schema and type bindings are checked
    against the catalog; wire them afterwards with `connect`."""
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
        catalog = await client.catalog.get(workspace_id)
        before = graph_of(head, graph_id).document
        builder = GraphBuilder.from_document(catalog, before)
        anchor = _free_point(before)
        added: list[str] = []
        for index, spec in enumerate(nodes):
            position = point(spec.x, spec.y) or GraphPoint(
                x=anchor.x + index * _COLUMN_WIDTH, y=anchor.y
            )
            handle = builder.add_catalog_node(
                spec.operator_id,
                spec.config,
                operator_version=spec.operator_version,
                bindings={
                    name: type_key(value) for name, value in spec.bindings.items()
                },
                position=position,
                node_id=spec.id,
            )
            added.append(handle.node_id)
        result = await _commit(
            client,
            workspace_id,
            project_id,
            graph_id,
            head,
            builder.build(require_complete=False),
        )
    return {**result, "node_ids": added}


async def duplicate_nodes(
    project_id: UUID,
    graph_id: str,
    node_ids: Annotated[list[str], Field(min_length=1)],
    dx: float = 40.0,
    dy: float = 40.0,
) -> dict[str, Any]:
    """Copy nodes (config, size, type bindings; not their wiring), offset by
    dx/dy, the Workbench's duplicate. Returns the new ids in the same order."""
    created: list[str] = []

    def transform(document: GraphDocument) -> GraphDocument:
        taken = {node.id for node in document.nodes}
        copies: list[GraphNode] = []
        for node_id in node_ids:
            source = _node_or_raise(document, node_id)
            number = 2
            while f"{source.id}-copy-{number}" in taken:
                number += 1
            copy_id = f"{source.id}-copy-{number}"
            taken.add(copy_id)
            created.append(copy_id)
            copies.append(
                source.model_copy(
                    update={
                        "id": copy_id,
                        "position": GraphPoint(
                            x=source.position.x + dx, y=source.position.y + dy
                        ),
                        "input_plugs": (),
                    }
                )
            )
        return document.with_topology(nodes=(*document.nodes, *copies))

    result = await _edit(project_id, graph_id, transform)
    return {**result, "node_ids": created}


async def add_call_node(
    project_id: UUID,
    graph_id: str,
    callee_graph_id: Annotated[
        str, Field(description="The sibling Graph this node runs, like a function")
    ],
    node_id: str,
    x: float | None = None,
    y: float | None = None,
) -> dict[str, Any]:
    """Place another Graph of this Project as one node. Its `graph.input` and
    `graph.output` boundary nodes become this node's ports."""
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
        document = graph_of(head, graph_id).document
        position = point(x, y) or _free_point(document)
        return await _commit(
            client,
            workspace_id,
            project_id,
            graph_id,
            head,
            document,
            extra=[
                AddCallNodeCommand(
                    graph_id=graph_id,
                    node_id=node_id,
                    callee_graph_id=callee_graph_id,
                    position=position,
                )
            ],
        )


def _moved(position: GraphPoint, move: Move) -> GraphPoint:
    return GraphPoint(
        x=(position.x if move.x is None else move.x) + move.dx,
        y=(position.y if move.y is None else move.y) + move.dy,
    )


async def move_items(
    project_id: UUID,
    graph_id: str,
    moves: Annotated[
        list[Move],
        Field(
            min_length=1,
            description=(
                "Each entry moves one node, card, annotation or Agent: give x/y "
                "for a point, dx/dy to nudge, or both"
            ),
        ),
    ],
) -> dict[str, Any]:
    """Drag nodes, cards, annotations and Agents to new canvas positions.

    Coordinates are canvas units with y growing downward; a node is about 300
    wide and 200 tall. Several entries move together, like a multi-selection.
    """
    by_id = {move.id: move for move in moves}

    def transform(document: GraphDocument) -> GraphDocument:
        found: set[str] = set()

        def update(item_id: str, position: GraphPoint) -> dict[str, Any]:
            move = by_id.get(item_id)
            if move is None:
                return {}
            found.add(item_id)
            return {"position": _moved(position, move)}

        presentation = document.presentation
        moved = document.with_topology(
            nodes=tuple(
                node.model_copy(update=update(node.id, node.position))
                for node in document.nodes
            ),
            agents=tuple(
                agent.model_copy(update=update(agent.id, agent.position))
                for agent in document.agents
            ),
            presentation=GraphPresentationDocument(
                viewers=tuple(
                    viewer.model_copy(update=update(viewer.id, viewer.position))
                    for viewer in presentation.viewers
                ),
                links=presentation.links,
                bindings=presentation.bindings,
                annotations=tuple(
                    annotation.model_copy(
                        update=update(annotation.id, annotation.position)
                    )
                    for annotation in presentation.annotations
                ),
            ),
        )
        missing = sorted(set(by_id) - found)
        if missing:
            raise ToolError(f"Nothing to move with id {', '.join(missing)}")
        return moved

    return await _edit(project_id, graph_id, transform)


async def resize_item(
    project_id: UUID,
    graph_id: str,
    id: Annotated[str, Field(description="A node, card, annotation or Agent id")],
    width: Annotated[float | None, Field(gt=0)] = None,
    height: Annotated[
        float | None,
        Field(gt=0, description="Body height for a node or card"),
    ] = None,
) -> dict[str, Any]:
    """Resize one canvas item. A node is at least 260 wide, a card 150, an Agent
    260 by 96, an annotation 24 by 24. Leave both unset on a node or card to
    return it to its natural size."""

    def transform(document: GraphDocument) -> GraphDocument:
        presentation = document.presentation
        for node in document.nodes:
            if node.id == id:
                layout = (
                    None
                    if width is None and height is None
                    else GraphNodeLayout(
                        width=width
                        if width is not None
                        else (None if node.layout is None else node.layout.width),
                        body_height=height
                        if height is not None
                        else (None if node.layout is None else node.layout.body_height),
                        appendix_height=(
                            None if node.layout is None else node.layout.appendix_height
                        ),
                    )
                )
                return _replace_node(
                    document, node.model_copy(update={"layout": layout})
                )
        for viewer in presentation.viewers:
            if viewer.id == id:
                layout = (
                    None
                    if width is None and height is None
                    else GraphPresentationViewerLayout(
                        width=width
                        if width is not None
                        else (None if viewer.layout is None else viewer.layout.width),
                        body_height=height
                        if height is not None
                        else (
                            None if viewer.layout is None else viewer.layout.body_height
                        ),
                    )
                )
                resized = viewer.model_copy(update={"layout": layout})
                return document.with_topology(
                    presentation=presentation.model_copy(
                        update={
                            "viewers": tuple(
                                resized if item.id == id else item
                                for item in presentation.viewers
                            )
                        }
                    )
                )
        for annotation in presentation.annotations:
            if annotation.id == id:
                resized_annotation = annotation.model_copy(
                    update={
                        "layout": GraphAnnotationLayout(
                            width=width or annotation.layout.width,
                            height=height or annotation.layout.height,
                        )
                    }
                )
                return document.with_topology(
                    presentation=presentation.model_copy(
                        update={
                            "annotations": tuple(
                                resized_annotation if item.id == id else item
                                for item in presentation.annotations
                            )
                        }
                    )
                )
        for agent in document.agents:
            if agent.id == id:
                resized_agent = GraphAgent.model_validate(
                    {
                        **agent.model_dump(),
                        "width": width or agent.width,
                        "height": height or agent.height,
                    }
                )
                return document.with_topology(
                    agents=tuple(
                        resized_agent if item.id == id else item
                        for item in document.agents
                    )
                )
        raise ToolError(f"Nothing to resize with id {id!r}")

    return await _edit(project_id, graph_id, transform)


async def configure_node(
    project_id: UUID,
    graph_id: str,
    node_id: str,
    config: Annotated[
        dict[str, Any],
        Field(description="Fields to set; other fields keep their values"),
    ],
    unset: Annotated[
        list[str] | None, Field(description="Fields to clear back to their default")
    ] = None,
) -> dict[str, Any]:
    """Change a node's configuration, the fields of its side panel. The result is
    checked against the node's config schema (see describe_node) before it is
    sent; each changed field becomes one edit that fails if someone else changed
    that field first."""
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
        catalog = await client.catalog.get(workspace_id)
        document = graph_of(head, graph_id).document
        node = _node_or_raise(document, node_id)
        merged = {**node.config_dict(), **config}
        for field in unset or []:
            merged.pop(field, None)
        _validate_config(catalog, node, merged)
        after = _replace_node(document, node.model_copy(update={"config": merged}))
        return await _commit(client, workspace_id, project_id, graph_id, head, after)


async def set_type_binding(
    project_id: UUID,
    graph_id: str,
    node_id: str,
    variable: Annotated[str, Field(description="The node's type variable, e.g. T")],
    artifact_type: Annotated[
        str | None,
        Field(description="'type.id@1' to bind, or null to clear the binding"),
    ],
) -> dict[str, Any]:
    """Bind (or clear) a generic node's artifact type variable, the type picker
    on nodes such as Collect or Pick."""

    def transform(document: GraphDocument) -> GraphDocument:
        node = _node_or_raise(document, node_id)
        bindings = [
            binding
            for binding in node.artifact_type_bindings
            if binding.variable != variable
        ]
        if artifact_type is not None:
            bindings.append(
                GraphArtifactTypeBinding(
                    variable=variable, artifact_type=type_key(artifact_type)
                )
            )
        return _replace_node(
            document,
            node.model_copy(update={"artifact_type_bindings": tuple(bindings)}),
        )

    return await _edit(project_id, graph_id, transform)


async def connect(
    project_id: UUID,
    graph_id: str,
    source: PortRef,
    target: PortRef,
    collection_mode: Annotated[
        Literal["direct", "map"],
        Field(description="'map' runs the target once per item of a list output"),
    ] = "direct",
    conversion_path: list[ConversionSpec] | None = None,
) -> dict[str, Any]:
    """Wire an output port to an input port. Checked against the catalog: port
    names, list/single shapes, artifact types (binding a generic node's type
    variable when needed), conversions, one wire per input, and no cycles."""
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
        catalog = await client.catalog.get(workspace_id)
        before = graph_of(head, graph_id).document
        builder = GraphBuilder.from_document(catalog, before)
        builder.connect(
            builder.node(source.node).output(source.port),
            builder.node(target.node).input(target.port),
            conversion_path=conversions(conversion_path or []),
            collection_mode=collection_mode,
        )
        after = builder.build(require_complete=False)
        result = await _commit(client, workspace_id, project_id, graph_id, head, after)
    new_edges = [edge.id for edge in after.edges if edge not in before.edges]
    return {**result, "connection_id": new_edges[0] if new_edges else None}


async def update_connection(
    project_id: UUID,
    graph_id: str,
    connection_id: str,
    enabled: Annotated[
        bool | None,
        Field(description="False keeps the wire but stops it carrying values"),
    ] = None,
    collection_mode: Literal["direct", "map"] | None = None,
) -> dict[str, Any]:
    """Turn a wire off or on, or switch it between direct and mapped."""

    def transform(document: GraphDocument) -> GraphDocument:
        edges: list[GraphEdge] = []
        found = False
        for edge in document.edges:
            if edge.id != connection_id:
                edges.append(edge)
                continue
            found = True
            update: dict[str, Any] = {}
            if enabled is not None:
                update["enabled"] = enabled
            if collection_mode is not None:
                update["collection_mode"] = collection_mode
            edges.append(GraphEdge.model_validate({**edge.model_dump(), **update}))
        if not found:
            raise ToolError(f"No connection {connection_id!r}; see get_canvas")
        return document.with_topology(edges=tuple(edges))

    return await _edit(project_id, graph_id, transform)


async def place_artifacts(
    project_id: UUID,
    graph_id: str,
    target: PortRef,
    artifacts: Annotated[
        list[ArtifactSpec] | None,
        Field(description="Stored artifacts to feed in; one, or several in order"),
    ] = None,
    card: Annotated[
        str | None,
        Field(description="Feed the artifact a standalone card on the canvas shows"),
    ] = None,
    as_sequence: bool = False,
    collection_mode: Literal["direct", "map"] = "direct",
    conversion_path: list[ConversionSpec] | None = None,
) -> dict[str, Any]:
    """Feed stored artifacts (uploads, Library items, earlier results) straight
    into a node input, the Workbench's drop of a file or card onto a port. Give
    `card` to feed from a card already on the canvas, or `artifacts`."""
    if (card is None) == (not artifacts):
        raise ToolError("Give exactly one of artifacts or card")
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
        catalog = await client.catalog.get(workspace_id)
        before = graph_of(head, graph_id).document
        builder = GraphBuilder.from_document(catalog, before)
        source: Any
        if card is not None:
            source = builder.card(card)
        else:
            hashes: dict[UUID, str | None] = {}
            if needs_library_hashes(artifacts or []):
                for item in await client.library.list(workspace_id):
                    hashes[item.artifact.artifact_id] = item.artifact.sha256
            source = artifact_value(artifacts or [], hashes, as_sequence=as_sequence)
        builder.place(
            builder.node(target.node).input(target.port),
            source,
            conversion_path=conversions(conversion_path or []),
            collection_mode=collection_mode,
        )
        after = builder.build(require_complete=False)
        result = await _commit(client, workspace_id, project_id, graph_id, head, after)
    new_origins = [
        origin.id for origin in after.origins if origin not in before.origins
    ]
    return {**result, "placed_id": new_origins[0] if new_origins else None}


async def add_card(
    project_id: UUID,
    graph_id: str,
    follows: Annotated[
        PortRef | None,
        Field(description="Show what this node output produces, across Runs"),
    ] = None,
    artifacts: Annotated[
        list[ArtifactSpec] | None,
        Field(description="Show these stored artifacts (a standalone card)"),
    ] = None,
    projection: Annotated[
        list[str] | None,
        Field(description="Output card only: the nested field path it previews"),
    ] = None,
    card_id: str | None = None,
    x: float | None = None,
    y: float | None = None,
) -> dict[str, Any]:
    """Put an artifact card on the canvas: a preview of a node output (table,
    map, image, text...) or of stored artifacts. Give exactly one of `follows`
    or `artifacts`. Without x/y an output card sits right of its node."""
    if (follows is None) == (not artifacts):
        raise ToolError("Give exactly one of follows or artifacts")
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
        catalog = await client.catalog.get(workspace_id)
        before = graph_of(head, graph_id).document
        builder = GraphBuilder.from_document(catalog, before)
        position = point(x, y)
        handle: CardHandle
        if follows is not None:
            if position is None:
                source = _node_or_raise(before, follows.node)
                position = GraphPoint(
                    x=source.position.x + _CARD_OFFSET, y=source.position.y
                )
            handle = builder.add_output_card(
                builder.node(follows.node).output(follows.port),
                position=position,
                projection=projection or [],
                card_id=card_id,
            )
        else:
            hashes: dict[UUID, str | None] = {}
            specs = artifacts or []
            if needs_library_hashes(specs):
                for item in await client.library.list(workspace_id):
                    hashes[item.artifact.artifact_id] = item.artifact.sha256
            handle = builder.add_artifact_card(
                artifact_value(specs, hashes, as_sequence=False),
                position=position or _free_point(before),
                card_id=card_id,
            )
        result = await _commit(
            client,
            workspace_id,
            project_id,
            graph_id,
            head,
            builder.build(require_complete=False),
        )
    return {**result, "card_id": handle.card_id}


async def bind_cards(
    project_id: UUID,
    graph_id: str,
    source_card: str,
    target_card: str,
    fields: Annotated[
        dict[str, str],
        Field(min_length=1, description="source field -> target field to match"),
    ],
    effects: Annotated[
        list[Literal["filter", "highlight", "focus"]],
        Field(min_length=1),
    ] = ["highlight", "focus"],  # noqa: B006 - an immutable tool default
) -> dict[str, Any]:
    """Link two cards: selecting rows or features on the source card filters,
    highlights or focuses the matching ones on the target card."""
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
        catalog = await client.catalog.get(workspace_id)
        builder = GraphBuilder.from_document(catalog, graph_of(head, graph_id).document)
        binding_id = builder.bind_cards(
            builder.card(source_card),
            builder.card(target_card),
            fields,
            effects=effects,
        )
        result = await _commit(
            client,
            workspace_id,
            project_id,
            graph_id,
            head,
            builder.build(require_complete=False),
        )
    return {**result, "binding_id": binding_id}


async def add_annotation(
    project_id: UUID,
    graph_id: str,
    kind: Literal["text", "rectangle", "ellipse"] = "text",
    text: Annotated[str, Field(max_length=8_000)] = "",
    x: float | None = None,
    y: float | None = None,
    width: Annotated[float, Field(ge=24)] = 240.0,
    height: Annotated[float, Field(ge=24)] = 96.0,
    color: Annotated[
        str, Field(pattern=r"^#[0-9A-Fa-f]{6}$", description="Hex colour")
    ] = "#475569",
) -> dict[str, Any]:
    """Draw a note or shape on the canvas to document the Graph. Only `text`
    annotations carry text; use a rectangle behind nodes to group them."""
    created: list[str] = []

    def transform(document: GraphDocument) -> GraphDocument:
        presentation = document.presentation
        taken = {annotation.id for annotation in presentation.annotations}
        number = len(taken) + 1
        while f"annotation-{number:04d}" in taken:
            number += 1
        annotation = GraphPresentationAnnotation(
            id=f"annotation-{number:04d}",
            kind=kind,
            position=point(x, y) or _free_point(document),
            layout=GraphAnnotationLayout(width=width, height=height),
            text=text,
            color=color,
        )
        created.append(annotation.id)
        return document.with_topology(
            presentation=presentation.model_copy(
                update={"annotations": (*presentation.annotations, annotation)}
            )
        )

    result = await _edit(project_id, graph_id, transform)
    return {**result, "annotation_id": created[0]}


async def edit_annotation(
    project_id: UUID,
    graph_id: str,
    annotation_id: str,
    text: Annotated[str | None, Field(max_length=8_000)] = None,
    color: Annotated[str | None, Field(pattern=r"^#[0-9A-Fa-f]{6}$")] = None,
) -> dict[str, Any]:
    """Change an annotation's text or colour (move and resize have their own
    tools)."""

    def transform(document: GraphDocument) -> GraphDocument:
        presentation = document.presentation
        changed = False
        annotations: list[GraphPresentationAnnotation] = []
        for annotation in presentation.annotations:
            if annotation.id == annotation_id:
                changed = True
                annotation = GraphPresentationAnnotation.model_validate(
                    {
                        **annotation.model_dump(),
                        **({} if text is None else {"text": text}),
                        **({} if color is None else {"color": color}),
                    }
                )
            annotations.append(annotation)
        if not changed:
            raise ToolError(f"No annotation {annotation_id!r}; see get_canvas")
        return document.with_topology(
            presentation=presentation.model_copy(
                update={"annotations": tuple(annotations)}
            )
        )

    return await _edit(project_id, graph_id, transform)


async def remove_items(
    project_id: UUID,
    graph_id: str,
    ids: Annotated[
        list[str],
        Field(
            min_length=1,
            description=(
                "Ids from get_canvas: nodes, connections, placed artifacts, cards, "
                "card bindings, annotations, Agents"
            ),
        ),
    ],
) -> dict[str, Any]:
    """Delete a selection from the canvas, the Delete key. A removed node takes
    its wires, placed artifacts and the cards' links to it along; a removed card
    takes its bindings. A checkpoint restore brings anything back."""
    wanted = set(ids)

    def transform(document: GraphDocument) -> GraphDocument:
        presentation = document.presentation
        known = (
            {node.id for node in document.nodes}
            | {edge.id for edge in document.edges}
            | {origin.id for origin in document.origins}
            | {viewer.id for viewer in presentation.viewers}
            | {binding.id for binding in presentation.bindings}
            | {annotation.id for annotation in presentation.annotations}
            | {agent.id for agent in document.agents}
        )
        unknown = sorted(wanted - known)
        if unknown:
            raise ToolError(f"Nothing to remove with id {', '.join(unknown)}")
        nodes = {node.id for node in document.nodes} & wanted
        cards = {viewer.id for viewer in presentation.viewers} & wanted
        return document.with_topology(
            nodes=tuple(node for node in document.nodes if node.id not in wanted),
            edges=tuple(
                edge
                for edge in document.edges
                if edge.id not in wanted
                and edge.from_node not in nodes
                and edge.to_node not in nodes
            ),
            origins=tuple(
                origin
                for origin in document.origins
                if origin.id not in wanted and origin.to_node not in nodes
            ),
            agents=tuple(
                agent.without_nodes(nodes)
                for agent in document.agents
                if agent.id not in wanted
            ),
            presentation=GraphPresentationDocument(
                viewers=tuple(
                    viewer for viewer in presentation.viewers if viewer.id not in cards
                ),
                links=tuple(
                    link
                    for link in presentation.links
                    if link.source_node_id not in nodes
                    and link.target_viewer_id not in cards
                ),
                bindings=tuple(
                    binding
                    for binding in presentation.bindings
                    if binding.id not in wanted
                    and binding.source_viewer_id not in cards
                    and binding.target_viewer_id not in cards
                ),
                annotations=tuple(
                    annotation
                    for annotation in presentation.annotations
                    if annotation.id not in wanted
                ),
            ),
        )

    return await _edit(project_id, graph_id, transform)


def _layered_positions(document: GraphDocument) -> dict[str, GraphPoint]:
    """Columns by longest path from the sources, rows by current height."""
    incoming: dict[str, list[str]] = defaultdict(list)
    for edge in document.edges:
        incoming[edge.to_node].append(edge.from_node)
    depth: dict[str, int] = {}

    def depth_of(node_id: str, seen: frozenset[str]) -> int:
        if node_id in depth:
            return depth[node_id]
        parents = [parent for parent in incoming[node_id] if parent not in seen]
        value = 0
        if parents:
            value = 1 + max(depth_of(parent, seen | {node_id}) for parent in parents)
        depth[node_id] = value
        return value

    for node in document.nodes:
        _ = depth_of(node.id, frozenset())
    columns: dict[int, list[GraphNode]] = defaultdict(list)
    for node in document.nodes:
        columns[depth[node.id]].append(node)
    left = min((node.position.x for node in document.nodes), default=0.0)
    top = min((node.position.y for node in document.nodes), default=0.0)
    positions: dict[str, GraphPoint] = {}
    for column, members in columns.items():
        members.sort(key=lambda node: (node.position.y, node.position.x))
        for row, node in enumerate(members):
            positions[node.id] = GraphPoint(
                x=left + column * (_COLUMN_WIDTH + _CARD_OFFSET * 0.5),
                y=top + row * _ROW_HEIGHT,
            )
    return positions


async def arrange_graph(project_id: UUID, graph_id: str) -> dict[str, Any]:
    """Tidy the canvas: nodes in left-to-right columns by data flow, each output
    card beside the node it follows. Annotations stay where they are."""

    def transform(document: GraphDocument) -> GraphDocument:
        positions = _layered_positions(document)
        followed = {
            link.target_viewer_id: link.source_node_id
            for link in document.presentation.links
        }
        stacked: dict[str, int] = defaultdict(int)
        viewers: list[GraphPresentationViewer] = []
        for viewer in document.presentation.viewers:
            node_id = followed.get(viewer.id)
            if node_id is None or node_id not in positions:
                viewers.append(viewer)
                continue
            anchor = positions[node_id]
            offset = stacked[node_id]
            stacked[node_id] += 1
            viewers.append(
                viewer.model_copy(
                    update={
                        "position": GraphPoint(
                            x=anchor.x + _CARD_OFFSET * 0.9,
                            y=anchor.y + offset * (_ROW_HEIGHT * 0.5),
                        )
                    }
                )
            )
        return document.with_topology(
            nodes=tuple(
                node.model_copy(update={"position": positions[node.id]})
                for node in document.nodes
            ),
            presentation=document.presentation.model_copy(
                update={"viewers": tuple(viewers)}
            ),
        )

    return await _edit(project_id, graph_id, transform)


async def add_agent(
    project_id: UUID,
    graph_id: str,
    agent_id: str,
    name: Annotated[str, Field(description="Shown on the canvas card")],
    instructions: Annotated[str, Field(max_length=100_000)] = "",
    tools: Annotated[
        list[AgentToolSpec] | None,
        Field(description="Nodes of this Graph the Agent may call"),
    ] = None,
    x: float | None = None,
    y: float | None = None,
) -> dict[str, Any]:
    """Put a chat Agent on the canvas (ADR 0021). It answers in its own
    conversations and calls the given nodes as tools; talk to it with
    `send_agent_message`."""

    def transform(document: GraphDocument) -> GraphDocument:
        agent = GraphAgent(
            id=agent_id,
            name=name,
            instructions=instructions,
            tools=tuple(
                AgentToolLink(
                    id=f"tool-{index + 1:04d}",
                    node_id=spec.node_id,
                    name=spec.name,
                    description=spec.description,
                    filled_ports=tuple(spec.filled_ports),
                    returned_ports=tuple(spec.returned_ports),
                )
                for index, spec in enumerate(tools or [])
            ),
            position=point(x, y) or _free_point(document),
        )
        return document.with_topology(agents=(*document.agents, agent))

    return await _edit(project_id, graph_id, transform)


async def configure_agent(
    project_id: UUID,
    graph_id: str,
    agent_id: str,
    name: str | None = None,
    instructions: Annotated[str | None, Field(max_length=100_000)] = None,
    tools: Annotated[
        list[AgentToolSpec] | None,
        Field(description="Replaces the Agent's tools when given"),
    ] = None,
) -> dict[str, Any]:
    """Rename an Agent, rewrite its instructions, or replace its tools."""

    def transform(document: GraphDocument) -> GraphDocument:
        agents: list[GraphAgent] = []
        found = False
        for agent in document.agents:
            if agent.id == agent_id:
                found = True
                update: dict[str, Any] = {}
                if name is not None:
                    update["name"] = name
                if instructions is not None:
                    update["instructions"] = instructions
                if tools is not None:
                    update["tools"] = [
                        {
                            "id": f"tool-{index + 1:04d}",
                            **spec.model_dump(),
                        }
                        for index, spec in enumerate(tools)
                    ]
                agent = GraphAgent.model_validate({**agent.model_dump(), **update})
            agents.append(agent)
        if not found:
            raise ToolError(f"No Agent {agent_id!r}; see get_canvas")
        return document.with_topology(agents=tuple(agents))

    return await _edit(project_id, graph_id, transform)


TOOLS: Final = (
    tool(get_canvas, READ, tags={"canvas"}),
    tool(add_nodes, EDIT, tags={"canvas"}),
    tool(duplicate_nodes, EDIT, tags={"canvas"}),
    tool(add_call_node, EDIT, tags={"canvas"}),
    tool(move_items, IDEMPOTENT_EDIT, tags={"canvas"}),
    tool(resize_item, IDEMPOTENT_EDIT, tags={"canvas"}),
    tool(configure_node, IDEMPOTENT_EDIT, tags={"canvas"}),
    tool(set_type_binding, IDEMPOTENT_EDIT, tags={"canvas"}),
    tool(connect, EDIT, tags={"canvas"}),
    tool(update_connection, IDEMPOTENT_EDIT, tags={"canvas"}),
    tool(place_artifacts, EDIT, tags={"canvas"}),
    tool(add_card, EDIT, tags={"canvas"}),
    tool(bind_cards, EDIT, tags={"canvas"}),
    tool(add_annotation, EDIT, tags={"canvas"}),
    tool(edit_annotation, IDEMPOTENT_EDIT, tags={"canvas"}),
    tool(remove_items, DESTRUCTIVE, tags={"canvas"}),
    tool(arrange_graph, IDEMPOTENT_EDIT, tags={"canvas"}),
    tool(add_agent, EDIT, tags={"canvas", "agents"}),
    tool(configure_agent, IDEMPOTENT_EDIT, tags={"canvas", "agents"}),
)

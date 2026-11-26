"""Turn an edited Graph document into the commands a user's gestures would send.

A client that edits a copy of a Graph (move these nodes, connect that port, drop
this card) can submit the whole new document as ``replace_document``, but then
every peer in the room sees the Graph swapped wholesale and a concurrent edit to
anything conflicts. :func:`graph_commands` instead returns the fine-grained
commands the Workbench itself sends (``move_nodes``, ``add_edge``,
``update_node_configuration`` ...), each carrying the value it expects to replace,
so the server applies them exactly like a person's edits.
"""

from collections.abc import Sequence
from typing import cast

from grafy_core.domain.collaboration import (
    AddAgentCommand,
    AddEdgeCommand,
    AddNodeCommand,
    AddOriginCommand,
    ClearNodeArtifactTypeBindingCommand,
    ConfigureAgentCommand,
    GraphCommand,
    MoveAnnotationPosition,
    MoveAnnotationsCommand,
    MoveArtifactViewerPosition,
    MoveArtifactViewersCommand,
    MoveNodePosition,
    MoveNodesCommand,
    RemoveAgentCommand,
    RemoveEdgesCommand,
    RemoveNodesCommand,
    RemoveOriginsCommand,
    ReplacePresentationCommand,
    SetNodeArtifactTypeBindingCommand,
    SetNodeInputPlugsCommand,
    UpdateEdgeCommand,
    UpdateNodeConfigurationAndInputPlugsCommand,
    UpdateNodeConfigurationCommand,
    UpdateNodeLayoutCommand,
    UpdateOriginCommand,
)
from grafy_core.domain.graph_documents import (
    GraphDocument,
    GraphNode,
    GraphPresentationDocument,
)


def _by_id[T](items: Sequence[T]) -> dict[str, T]:
    return {cast(str, getattr(item, "id")): item for item in items}


def _node_commands(before: GraphNode, after: GraphNode) -> list[GraphCommand]:
    """Commands that turn one node into its edited self (same id, same operator)."""

    commands: list[GraphCommand] = []
    old_config = before.config_dict()
    new_config = after.config_dict()
    plugs_changed = before.input_plugs != after.input_plugs
    removed_keys = set(old_config) - set(new_config)
    if removed_keys or (plugs_changed and old_config != new_config):
        # A dropped key cannot be expressed field by field, and a config change
        # that comes with new plugs is one compound gesture in the Workbench.
        commands.append(
            UpdateNodeConfigurationAndInputPlugsCommand(
                node_id=after.id,
                config=new_config,
                input_plugs=after.input_plugs,
                expected_config=old_config,
                expected_plug_ids=tuple(plug.id for plug in before.input_plugs),
            )
        )
    else:
        for field, value in new_config.items():
            if field in old_config and old_config[field] == value:
                continue
            commands.append(
                UpdateNodeConfigurationCommand(
                    node_id=after.id,
                    field=field,
                    value=value,
                    expected_value=old_config.get(field),
                )
            )
        if plugs_changed:
            commands.append(
                SetNodeInputPlugsCommand(
                    node_id=after.id,
                    input_plugs=after.input_plugs,
                    expected_plug_ids=tuple(plug.id for plug in before.input_plugs),
                )
            )
    if before.layout != after.layout:
        commands.append(
            UpdateNodeLayoutCommand(
                node_id=after.id,
                layout=after.layout,
                expected_layout=before.layout,
            )
        )
    old_bindings = {
        binding.variable: binding for binding in before.artifact_type_bindings
    }
    new_bindings = {
        binding.variable: binding for binding in after.artifact_type_bindings
    }
    for variable, binding in new_bindings.items():
        if old_bindings.get(variable) != binding:
            commands.append(
                SetNodeArtifactTypeBindingCommand(
                    node_id=after.id,
                    binding=binding,
                    expected_binding=old_bindings.get(variable),
                )
            )
    for variable, binding in old_bindings.items():
        if variable not in new_bindings:
            commands.append(
                ClearNodeArtifactTypeBindingCommand(
                    node_id=after.id, variable=variable, expected_binding=binding
                )
            )
    return commands


def _same_identity(before: GraphNode, after: GraphNode) -> bool:
    return (
        before.kind == after.kind
        and before.operator_id == after.operator_id
        and before.operator_version == after.operator_version
    )


def _presentation_commands(
    before: GraphPresentationDocument, after: GraphPresentationDocument
) -> list[GraphCommand]:
    if before == after:
        return []
    old_viewers = _by_id(before.viewers)
    old_annotations = _by_id(before.annotations)
    viewers_only_moved = [viewer.id for viewer in after.viewers] == [
        viewer.id for viewer in before.viewers
    ] and all(
        viewer.model_copy(update={"position": old_viewers[viewer.id].position})
        == old_viewers[viewer.id]
        for viewer in after.viewers
    )
    annotations_only_moved = [annotation.id for annotation in after.annotations] == [
        annotation.id for annotation in before.annotations
    ] and all(
        annotation.model_copy(
            update={"position": old_annotations[annotation.id].position}
        )
        == old_annotations[annotation.id]
        for annotation in after.annotations
    )
    if (
        not viewers_only_moved
        or not annotations_only_moved
        or before.links != after.links
        or before.bindings != after.bindings
    ):
        return [ReplacePresentationCommand(presentation=after)]
    commands: list[GraphCommand] = []
    moved_viewers = tuple(
        MoveArtifactViewerPosition(
            viewer_id=viewer.id, x=viewer.position.x, y=viewer.position.y
        )
        for viewer in after.viewers
        if viewer.position != old_viewers[viewer.id].position
    )
    if moved_viewers:
        commands.append(MoveArtifactViewersCommand(positions=moved_viewers))
    moved_annotations = tuple(
        MoveAnnotationPosition(
            annotation_id=annotation.id,
            x=annotation.position.x,
            y=annotation.position.y,
        )
        for annotation in after.annotations
        if annotation.position != old_annotations[annotation.id].position
    )
    if moved_annotations:
        commands.append(MoveAnnotationsCommand(positions=moved_annotations))
    return commands


def graph_commands(before: GraphDocument, after: GraphDocument) -> list[GraphCommand]:
    """The ordered graph commands that turn ``before`` into ``after``.

    Removals come first (edges and origins, then nodes), then new nodes, then
    edits to surviving nodes, then wiring, then the canvas presentation and Agents,
    so every command finds what it refers to. A node whose operator changed under
    the same id is removed and added again. Equal documents give no commands.
    """

    old_nodes = _by_id(before.nodes)
    new_nodes = _by_id(after.nodes)
    old_edges = _by_id(before.edges)
    new_edges = _by_id(after.edges)
    old_origins = _by_id(before.origins)
    new_origins = _by_id(after.origins)

    replaced_nodes = {
        node_id
        for node_id, node in new_nodes.items()
        if node_id in old_nodes and not _same_identity(old_nodes[node_id], node)
    }
    removed_nodes = [
        node_id
        for node_id in old_nodes
        if node_id not in new_nodes or node_id in replaced_nodes
    ]
    removed_set = set(removed_nodes)

    commands: list[GraphCommand] = []
    # A removed node takes its edges and origins with it on the server.
    removed_edges = tuple(
        edge_id
        for edge_id, edge in old_edges.items()
        if edge_id not in new_edges
        and edge.from_node not in removed_set
        and edge.to_node not in removed_set
    )
    if removed_edges:
        commands.append(RemoveEdgesCommand(edge_ids=removed_edges))
    removed_origins = tuple(
        origin_id
        for origin_id, origin in old_origins.items()
        if origin_id not in new_origins and origin.to_node not in removed_set
    )
    if removed_origins:
        commands.append(RemoveOriginsCommand(origin_ids=removed_origins))
    if removed_nodes:
        commands.append(RemoveNodesCommand(node_ids=tuple(removed_nodes)))

    for node in after.nodes:
        if node.id not in old_nodes or node.id in replaced_nodes:
            commands.append(AddNodeCommand(node=node))

    moved: list[MoveNodePosition] = []
    for node in after.nodes:
        previous = old_nodes.get(node.id)
        if previous is None or node.id in replaced_nodes:
            continue
        if previous.position != node.position:
            moved.append(
                MoveNodePosition(node_id=node.id, x=node.position.x, y=node.position.y)
            )
        commands.extend(_node_commands(previous, node))
    if moved:
        commands.append(MoveNodesCommand(positions=tuple(moved)))

    for edge in after.edges:
        previous_edge = old_edges.get(edge.id)
        survives = previous_edge is not None and (
            previous_edge.from_node not in removed_set
            and previous_edge.to_node not in removed_set
        )
        if previous_edge is not None and survives:
            if previous_edge != edge:
                commands.append(
                    UpdateEdgeCommand(edge=edge, expected_edge=previous_edge)
                )
            continue
        commands.append(AddEdgeCommand(edge=edge))

    for origin in after.origins:
        previous_origin = old_origins.get(origin.id)
        if previous_origin is not None and previous_origin.to_node not in removed_set:
            if previous_origin != origin:
                commands.append(
                    UpdateOriginCommand(origin=origin, expected_origin=previous_origin)
                )
            continue
        commands.append(AddOriginCommand(origin=origin))

    # The server prunes links to removed nodes itself; compare against that.
    pruned = before.presentation.prune_for_removed_nodes(removed_set)
    commands.extend(_presentation_commands(pruned, after.presentation))

    old_agents = {agent.id: agent.without_nodes(removed_set) for agent in before.agents}
    new_agents = _by_id(after.agents)
    for agent_id in old_agents:
        if agent_id not in new_agents:
            commands.append(RemoveAgentCommand(agent_id=agent_id))
    for agent in after.agents:
        previous_agent = old_agents.get(agent.id)
        if previous_agent is None:
            commands.append(AddAgentCommand(agent=agent))
        elif previous_agent != agent:
            commands.append(ConfigureAgentCommand(agent=agent))
    return commands


__all__ = ["graph_commands"]

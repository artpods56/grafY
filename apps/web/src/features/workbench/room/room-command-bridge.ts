import type { CollaborativeHead } from "@/lib/api";

import {
  emptyGraphPresentation,
  type GraphPresentation,
} from "../canvas/artifact-viewer";
import {
  applyGraphCommand,
  authoredGraphDocument,
  createSavedGraphRequest,
  type AuthoredGraphDocument,
  type GraphCommand,
} from "../model/graph-document";
import type { RoomGraphCommand } from "./protocol";

/** Map a local authoring command to a room submit payload when the shapes align. */
export function toRoomGraphCommand(
  command: GraphCommand,
  document: AuthoredGraphDocument,
): RoomGraphCommand | null {
  const asRoom = (value: unknown): RoomGraphCommand => value as RoomGraphCommand;
  switch (command.kind) {
    case "move_nodes":
      return asRoom({
        kind: "move_nodes",
        positions: command.positions.map((position) => ({
          node_id: position.node_id,
          x: position.x,
          y: position.y,
        })),
      });
    case "add_node": {
      const projected = createSavedGraphRequest({
        name: document.name,
        nodes: [command.node],
        edges: [],
      });
      return asRoom({ kind: "add_node", node: projected.nodes?.[0] });
    }
    case "remove_nodes":
      return asRoom({
        kind: "remove_nodes",
        node_ids: [...command.node_ids],
      });
    case "add_edge": {
      const projected = createSavedGraphRequest({
        name: document.name,
        nodes: document.nodes,
        edges: [command.edge],
      });
      return asRoom({ kind: "add_edge", edge: projected.edges?.[0] });
    }
    case "remove_edges":
      return asRoom({
        kind: "remove_edges",
        edge_ids: [...command.edge_ids],
      });
    case "rename_graph":
      return asRoom({
        kind: "rename_graph",
        name: command.name,
        expected_name: document.name,
      });
    case "update_node_configuration": {
      const node = document.nodes.find(
        (candidate) => candidate.id === command.node_id,
      );
      if (!node) return null;
      return asRoom({
        kind: "update_node_configuration",
        node_id: command.node_id,
        field: command.field,
        value: command.value,
        expected_value: node.config?.[command.field] ?? null,
      });
    }
    case "update_node_layout": {
      const node = document.nodes.find(
        (candidate) => candidate.id === command.node_id,
      );
      if (!node) return null;
      return asRoom({
        kind: "update_node_layout",
        node_id: command.node_id,
        layout: command.layout ?? null,
        expected_layout: node.layout ?? null,
      });
    }
    case "update_node_configuration_and_input_plugs": {
      const node = document.nodes.find(
        (candidate) => candidate.id === command.node_id,
      );
      if (!node) return null;
      return asRoom({
        kind: "update_node_configuration_and_input_plugs",
        node_id: command.node_id,
        config: { ...command.config },
        input_plugs: [...command.input_plugs],
        expected_config: { ...(node.config ?? {}) },
        expected_plug_ids: (node.input_plugs ?? []).map((plug) => plug.id),
      });
    }
    case "bind_artifact_type": {
      const node = document.nodes.find(
        (candidate) => candidate.id === command.node_id,
      );
      if (!node) return null;
      const current = (node.artifact_type_bindings ?? []).find(
        (binding) => binding.variable === command.variable,
      );
      return asRoom({
        kind: "set_node_artifact_type_binding",
        node_id: command.node_id,
        binding: {
          variable: command.variable,
          artifact_type: command.artifact_type,
        },
        expected_binding: current ?? null,
      });
    }
    case "reset_artifact_type_binding": {
      const node = document.nodes.find(
        (candidate) => candidate.id === command.node_id,
      );
      const current = (node?.artifact_type_bindings ?? []).find(
        (binding) => binding.variable === command.variable,
      );
      if (!current) return null;
      return asRoom({
        kind: "clear_node_artifact_type_binding",
        node_id: command.node_id,
        variable: command.variable,
        expected_binding: current,
      });
    }
    case "update_edge": {
      const edge = document.edges.find(
        (candidate) => candidate.id === command.edge_id,
      );
      if (!edge) return null;
      const projected = createSavedGraphRequest({
        name: document.name,
        nodes: document.nodes,
        edges: [{ ...edge, ...command.update }],
      });
      const expected = createSavedGraphRequest({
        name: document.name,
        nodes: document.nodes,
        edges: [edge],
      });
      return asRoom({
        kind: "update_edge",
        expected_edge: expected.edges?.[0],
        edge: projected.edges?.[0],
      });
    }
    case "replace_document": {
      const projected = createSavedGraphRequest(command.document);
      return asRoom({
        kind: "replace_document",
        name: projected.name,
        document: {
          schema_version: 4,
          nodes: projected.nodes ?? [],
          edges: projected.edges ?? [],
          presentation: projected.presentation ?? emptyGraphPresentation(),
        },
      });
    }
    case "add_input_plug":
    case "remove_input_plug":
    case "reorder_input_plug": {
      const node = document.nodes.find(
        (candidate) => candidate.id === command.node_id,
      );
      if (!node) return null;
      const nextDocument = applyGraphCommand(document, command);
      const nextNode = nextDocument.nodes.find(
        (candidate) => candidate.id === command.node_id,
      );
      if (!nextNode) return null;
      return asRoom({
        kind: "set_node_input_plugs",
        node_id: command.node_id,
        input_plugs: [...(nextNode.input_plugs ?? [])],
        expected_plug_ids: (node.input_plugs ?? []).map((plug) => plug.id),
      });
    }
  }
}

/** Map a room broadcast command onto the local authoring command vocabulary. */
export function toLocalGraphCommand(
  command: RoomGraphCommand,
  document?: AuthoredGraphDocument,
): GraphCommand | null {
  switch (command.kind) {
    case "move_nodes":
      return {
        kind: "move_nodes",
        positions: command.positions.map((position) => ({
          node_id: position.node_id,
          x: position.x,
          y: position.y,
        })),
      };
    case "add_node":
      return { kind: "add_node", node: command.node };
    case "remove_nodes":
      return { kind: "remove_nodes", node_ids: command.node_ids };
    case "add_edge":
      return { kind: "add_edge", edge: command.edge };
    case "remove_edges":
      return { kind: "remove_edges", edge_ids: command.edge_ids };
    case "rename_graph":
      return { kind: "rename_graph", name: command.name };
    case "update_node_configuration":
      return {
        kind: "update_node_configuration",
        node_id: command.node_id,
        field: command.field,
        value: command.value,
      };
    case "update_node_layout":
      return {
        kind: "update_node_layout",
        node_id: command.node_id,
        layout: command.layout,
      };
    case "update_node_configuration_and_input_plugs":
      return {
        kind: "update_node_configuration_and_input_plugs",
        node_id: command.node_id,
        config: command.config,
        input_plugs: command.input_plugs,
      };
    case "set_node_artifact_type_binding":
      return {
        kind: "bind_artifact_type",
        node_id: command.node_id,
        variable: command.binding.variable,
        artifact_type: command.binding.artifact_type,
      };
    case "clear_node_artifact_type_binding":
      return {
        kind: "reset_artifact_type_binding",
        node_id: command.node_id,
        variable: command.variable,
      };
    case "set_node_input_plugs": {
      const node = document?.nodes.find(
        (candidate) => candidate.id === command.node_id,
      );
      if (!node) return null;
      return {
        kind: "update_node_configuration_and_input_plugs",
        node_id: command.node_id,
        config: { ...(node.config ?? {}) },
        input_plugs: command.input_plugs,
      };
    }
    case "update_edge":
      return {
        kind: "update_edge",
        edge_id: command.edge.id,
        update: {
          enabled: command.edge.enabled,
          collection_mode: command.edge.collection_mode,
          projection: command.edge.projection,
          conversion_path: command.edge.conversion_path,
          route_offset: command.edge.route_offset,
        },
      };
    case "replace_document":
      return {
        kind: "replace_document",
        document: authoredGraphDocument({
          name: command.name,
          nodes: command.document.nodes,
          edges: command.document.edges,
        }),
      };
    case "duplicate_node":
      return { kind: "add_node", node: command.node };
    case "replace_presentation":
    case "move_artifact_viewers":
    case "move_annotations":
      return null;
    default:
      return null;
  }
}

/** Translate an accepted room transaction without losing primitive ordering. */
export function toLocalGraphCommands(
  command: RoomGraphCommand,
  document: AuthoredGraphDocument,
): readonly GraphCommand[] | null {
  if (command.kind !== "apply_batch") {
    const local = toLocalGraphCommand(command, document);
    return local ? [local] : null;
  }

  const localCommands: GraphCommand[] = [];
  let current = document;
  try {
    for (const primitive of command.commands) {
      const local = toLocalGraphCommand(primitive, current);
      if (!local) return null;
      localCommands.push(local);
      current = applyGraphCommand(current, local);
    }
  } catch {
    // The accepted room head is authoritative. If this local snapshot has
    // diverged, let the caller rehydrate instead of throwing in its listener.
    return null;
  }
  return localCommands;
}

function headPresentation(head: CollaborativeHead): GraphPresentation {
  return {
    viewers: [...(head.presentation?.viewers ?? [])],
    links: [...(head.presentation?.links ?? [])],
    bindings: [...(head.presentation?.bindings ?? [])],
    annotations: [...(head.presentation?.annotations ?? [])],
  };
}

function prunePresentationLinks(
  presentation: GraphPresentation,
  removedNodeIds: ReadonlySet<string>,
): GraphPresentation {
  if (!removedNodeIds.size) return presentation;
  return {
    ...presentation,
    links: (presentation.links ?? []).filter(
      (link) => !removedNodeIds.has(link.source_node_id),
    ),
  };
}

export function applyRoomCommandToHead(
  head: CollaborativeHead,
  command: RoomGraphCommand,
  sequence: number,
): CollaborativeHead {
  if (command.kind === "apply_batch") {
    return command.commands.reduce(
      (current, primitive) =>
        applyRoomCommandToHead(current, primitive, sequence),
      head,
    );
  }

  if (command.kind === "replace_document") {
    return {
      ...head,
      name: command.name,
      nodes: command.document.nodes ?? [],
      edges: command.document.edges ?? [],
      presentation:
        command.document.presentation ?? emptyGraphPresentation(),
      collaboration_sequence: sequence,
    };
  }

  if (command.kind === "replace_presentation") {
    return {
      ...head,
      presentation: command.presentation,
      collaboration_sequence: sequence,
    };
  }

  if (command.kind === "move_artifact_viewers") {
    const positions = new Map(
      command.positions.map((position) => [
        position.viewer_id,
        { x: position.x, y: position.y },
      ]),
    );
    const presentation = headPresentation(head);
    return {
      ...head,
      collaboration_sequence: sequence,
      presentation: {
        ...presentation,
        viewers: (presentation.viewers ?? []).map((viewer) => {
          const position = positions.get(viewer.id);
          return position
            ? { ...viewer, position }
            : viewer;
        }),
      },
    };
  }

  if (command.kind === "move_annotations") {
    const positions = new Map(
      command.positions.map((position) => [
        position.annotation_id,
        { x: position.x, y: position.y },
      ]),
    );
    const presentation = headPresentation(head);
    return {
      ...head,
      collaboration_sequence: sequence,
      presentation: {
        ...presentation,
        annotations: (presentation.annotations ?? []).map((annotation) => {
          const position = positions.get(annotation.id);
          return position
            ? { ...annotation, position }
            : annotation;
        }),
      },
    };
  }

  if (command.kind === "set_node_input_plugs") {
    return {
      ...head,
      collaboration_sequence: sequence,
      nodes: head.nodes.map((node) =>
        node.id === command.node_id
          ? { ...node, input_plugs: [...command.input_plugs] }
          : node,
      ),
    };
  }

  const base = authoredGraphDocument({
    name: head.name,
    nodes: head.nodes,
    edges: head.edges,
  });
  const local = toLocalGraphCommand(command, base);
  if (!local) {
    return { ...head, collaboration_sequence: sequence };
  }

  const nextDocument = applyGraphCommand(base, local);
  const request = createSavedGraphRequest(nextDocument);
  let presentation = headPresentation(head);
  if (local.kind === "remove_nodes") {
    presentation = prunePresentationLinks(
      presentation,
      new Set(local.node_ids),
    );
  }
  return {
    ...head,
    name: request.name,
    nodes: request.nodes ?? [],
    edges: request.edges ?? [],
    presentation,
    collaboration_sequence: sequence,
  };
}

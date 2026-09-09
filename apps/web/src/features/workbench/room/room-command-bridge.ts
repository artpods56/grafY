import type { CollaborativeHead, CreateSavedGraphRequest } from "@/lib/api";

import {
  emptyGraphPresentation,
  presentationFromCollaborativeHead,
  type GraphPresentation,
} from "../canvas/artifact-viewer";
import {
  applyGraphCommand,
  authoredGraphDocument,
  createSavedGraphRequest,
  projectSavedGraphNode,
  projectSavedGraphEdge,
  type AuthoredGraphDocument,
  type GraphCommand,
} from "../model/graph-document";
import type { RoomGraphCommand } from "./protocol";

type RoomReplaceDocumentCommand = Extract<
  RoomGraphCommand,
  { readonly kind: "replace_document" }
>;

/** Project the REST/UI draft aliases into the exact graph-room wire contract. */
export function toRoomReplaceDocumentCommand(
  draft: CreateSavedGraphRequest,
): RoomReplaceDocumentCommand {
  const document = authoredGraphDocument(draft);
  const presentation = draft.document.presentation ?? emptyGraphPresentation();
  return {
    kind: "replace_document",
    name: document.name,
    document: {
      schema_version: 6,
      nodes: document.nodes.map(projectSavedGraphNode),
      edges: document.edges.map(projectSavedGraphEdge),
      presentation: {
        annotations: [...(presentation.annotations ?? [])],
        bindings: [...(presentation.bindings ?? [])],
        links: [...(presentation.links ?? [])],
        viewers: [...(presentation.viewers ?? [])],
      },
    },
  };
}

/** Map a local authoring command to a room submit payload when the shapes align. */
export function toRoomGraphCommand(
  command: GraphCommand,
  document: AuthoredGraphDocument,
): RoomGraphCommand | null {
  const asRoom = (value: unknown): RoomGraphCommand =>
    value as RoomGraphCommand;
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
    case "add_node":
      return { kind: "add_node", node: projectSavedGraphNode(command.node) };
    case "remove_nodes":
      return asRoom({
        kind: "remove_nodes",
        node_ids: [...command.node_ids],
      });
    case "add_edge":
      return { kind: "add_edge", edge: projectSavedGraphEdge(command.edge) };
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
    case "update_node_plugin_release": {
      const node = document.nodes.find(
        (candidate) => candidate.id === command.node_id,
      );
      const expectedPin = node?.plugin_release_pin;
      if (!expectedPin) return null;
      return {
        kind: "update_node_plugin_release",
        node_id: command.node_id,
        plugin_release_pin: {
          scope: command.plugin_release.scope,
          slug: command.plugin_release.slug,
          revision: command.plugin_release.revision,
        },
        expected_plugin_release_pin: {
          scope: expectedPin.scope,
          slug: expectedPin.slug,
          revision: expectedPin.revision,
        },
      };
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
      return {
        kind: "update_edge",
        expected_edge: projectSavedGraphEdge(edge),
        edge: projectSavedGraphEdge({ ...edge, ...command.update }),
      };
    }
    case "replace_document": {
      return toRoomReplaceDocumentCommand(
        createSavedGraphRequest(command.document),
      );
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
      return { kind: "add_node", node: projectSavedGraphNode(command.node) };
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
    case "update_node_plugin_release":
      return {
        kind: "update_node_plugin_release",
        node_id: command.node_id,
        plugin_release: {
          scope: command.plugin_release_pin.scope,
          slug: command.plugin_release_pin.slug,
          revision: command.plugin_release_pin.revision,
        },
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
          document: command.document,
        }),
      };
    case "duplicate_node":
      return { kind: "add_node", node: projectSavedGraphNode(command.node) };
    case "replace_presentation":
    case "move_artifact_viewers":
    case "move_annotations":
      return null;
    default:
      return null;
  }
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
  if (command.kind === "replace_document") {
    return {
      ...head,
      name: command.name,
      document: {
        schema_version: 6,
        nodes: command.document.nodes.map(projectSavedGraphNode),
        edges: command.document.edges,
        presentation: command.document.presentation ?? emptyGraphPresentation(),
      },
      collaboration_sequence: sequence,
    };
  }

  if (command.kind === "replace_presentation") {
    return {
      ...head,
      document: { ...head.document, presentation: command.presentation },
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
    const presentation = presentationFromCollaborativeHead(head);
    return {
      ...head,
      collaboration_sequence: sequence,
      document: {
        ...head.document,
        presentation: {
          ...presentation,
          viewers: presentation.viewers.map((viewer) => {
            const position = positions.get(viewer.id);
            return position ? { ...viewer, position } : viewer;
          }),
        },
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
    const presentation = presentationFromCollaborativeHead(head);
    return {
      ...head,
      collaboration_sequence: sequence,
      document: {
        ...head.document,
        presentation: {
          ...presentation,
          annotations: presentation.annotations.map((annotation) => {
            const position = positions.get(annotation.id);
            return position ? { ...annotation, position } : annotation;
          }),
        },
      },
    };
  }

  if (command.kind === "set_node_input_plugs") {
    return {
      ...head,
      collaboration_sequence: sequence,
      document: {
        ...head.document,
        nodes: head.document.nodes.map((node) =>
          node.id === command.node_id
            ? { ...node, input_plugs: [...command.input_plugs] }
            : node,
        ),
      },
    };
  }

  const base = authoredGraphDocument(head);
  const local = toLocalGraphCommand(command, base);
  if (!local) return { ...head, collaboration_sequence: sequence };

  const nextDocument = applyGraphCommand(base, local);
  let presentation = presentationFromCollaborativeHead(head);
  if (local.kind === "remove_nodes") {
    presentation = prunePresentationLinks(presentation, new Set(local.node_ids));
  }
  const request = createSavedGraphRequest(nextDocument, presentation);
  return {
    ...head,
    ...request,
    collaboration_sequence: sequence,
  };
}

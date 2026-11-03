import type {
  CollaborativeHead,
  GraphDefinition,
  GraphPresentationDocument,
  InGraphCommand,
  ProjectCommand,
  SavedGraph,
  SavedGraphDocument,
} from "@/lib/api";

import {
  emptyGraphPresentation,
  presentationFromGraphDocument,
  type GraphPresentation,
} from "../canvas/artifact-viewer";
import {
  applyGraphCommand,
  authoredGraphDocument,
  createGraphDraft,
  projectSavedGraphNode,
  projectSavedGraphEdge,
  projectSavedGraphOrigin,
  type AuthoredGraphDocument,
  type GraphDraft,
  type GraphCommand,
} from "../model/graph-document";

/** One Project command batch entry, as the room carries it. */
export type RoomProjectCommand = ProjectCommand;

/** A command that addresses the inside of one Graph. */
export type RoomGraphBodyCommand = InGraphCommand["command"];

/** @deprecated a command is addressed to a Project, and maybe to one Graph inside it. */
export type RoomGraphCommand = RoomProjectCommand;

function asRoomBody(value: unknown): RoomGraphBodyCommand {
  return value as RoomGraphBodyCommand;
}

/** Address a Graph command to the Graph it belongs to. */
export function toInGraphCommand(
  graphId: string,
  command: RoomGraphBodyCommand,
): InGraphCommand {
  return { kind: "in_graph", graph_id: graphId, command };
}

/**
 * Project the Workbench draft into the wire contract for one Graph.
 *
 * The Graph's own name is not part of its document: renaming it is a Project
 * command of its own, so a save that carries a new name sends both.
 */
export function toRoomReplaceDocumentCommand(
  draft: GraphDraft,
  graphId?: string,
): RoomProjectCommand {
  const document = authoredGraphDocument(draft);
  const presentation = draft.document.presentation ?? emptyGraphPresentation();
  const command: RoomGraphBodyCommand = {
    kind: "replace_document",
    document: {
      schema_version: 7,
      nodes: document.nodes.map(projectSavedGraphNode),
      edges: document.edges.map(projectSavedGraphEdge),
      origins: document.origins.map(projectSavedGraphOrigin),
      presentation: {
        annotations: [...presentation.annotations],
        bindings: [...presentation.bindings],
        links: [...presentation.links],
        viewers: [...presentation.viewers],
      },
    },
  };
  return graphId === undefined
    ? command
    : toInGraphCommand(graphId, command);
}

/** Rename the Graph itself. Graphs are named by the Project that holds them. */
export function toRoomRenameGraphCommand(
  graphId: string,
  name: string,
  expectedName: string,
): RoomProjectCommand {
  return { kind: "rename_graph", graph_id: graphId, name, expected_name: expectedName };
}

/** Rename the Project. Its name is what a person opens from the browser. */
export function toRoomRenameProjectCommand(
  name: string,
  expectedName: string,
): RoomProjectCommand {
  return { kind: "rename_project", name, expected_name: expectedName };
}

/**
 * Map a local authoring command to the Project command that carries it.
 *
 * Every Graph command is addressed to one Graph, so `graphId` is required: a
 * Project holds several Graphs and an unaddressed edit names none of them.
 */
export function toRoomGraphCommand(
  command: GraphCommand,
  document: AuthoredGraphDocument,
  graphId?: string,
): RoomProjectCommand | null {
  const body = toRoomGraphBodyCommand(command, document);
  if (body === null) return null;
  if (body.kind === "rename_graph") {
    if (graphId === undefined) return null;
    return toRoomRenameGraphCommand(graphId, body.name, document.name);
  }
  if (graphId === undefined) return body;
  return toInGraphCommand(graphId, body);
}

/** The Graph-scoped half of the mapping, without its Project wrapper. */
export function toRoomGraphBodyCommand(
  command: GraphCommand,
  document: AuthoredGraphDocument,
): RoomGraphBodyCommand | null {
  switch (command.kind) {
    case "move_nodes":
      return asRoomBody({
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
      return asRoomBody({
        kind: "remove_nodes",
        node_ids: [...command.node_ids],
      });
    case "add_edge":
      return { kind: "add_edge", edge: projectSavedGraphEdge(command.edge) };
    case "remove_edges":
      return asRoomBody({
        kind: "remove_edges",
        edge_ids: [...command.edge_ids],
      });
    case "add_origin":
      return {
        kind: "add_origin",
        origin: projectSavedGraphOrigin(command.origin),
      };
    case "remove_origins":
      return asRoomBody({
        kind: "remove_origins",
        origin_ids: [...command.origin_ids],
      });
    case "rename_graph":
      return asRoomBody({ kind: "rename_graph", name: command.name });
    case "update_node_configuration": {
      const node = document.nodes.find(
        (candidate) => candidate.id === command.node_id,
      );
      if (!node) return null;
      return asRoomBody({
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
      return asRoomBody({
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
      return asRoomBody({
        kind: "update_node_configuration_and_input_plugs",
        node_id: command.node_id,
        config: { ...command.config },
        input_plugs: [...command.input_plugs],
        expected_config: { ...(node.config ?? {}) },
        expected_plug_ids: node.input_plugs.map((plug) => plug.id),
      });
    }
    case "bind_artifact_type": {
      const node = document.nodes.find(
        (candidate) => candidate.id === command.node_id,
      );
      if (!node) return null;
      const current = node.artifact_type_bindings.find(
        (binding) => binding.variable === command.variable,
      );
      return asRoomBody({
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
      const current = node?.artifact_type_bindings.find(
        (binding) => binding.variable === command.variable,
      );
      if (!current) return null;
      return asRoomBody({
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
    case "update_origin": {
      const origin = document.origins.find(
        (candidate) => candidate.id === command.origin_id,
      );
      if (!origin) return null;
      return {
        kind: "update_origin",
        expected_origin: projectSavedGraphOrigin(origin),
        origin: projectSavedGraphOrigin({ ...origin, ...command.update }),
      };
    }
    case "replace_document": {
      const draft = createGraphDraft(command.document);
      const presentation =
        command.document.presentation ?? emptyGraphPresentation();
      return {
        kind: "replace_document",
        document: {
          ...draft.document,
          presentation: {
            annotations: [...presentation.annotations],
            bindings: [...presentation.bindings],
            links: [...presentation.links],
            viewers: [...presentation.viewers],
          },
        },
      };
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
      return asRoomBody({
        kind: "set_node_input_plugs",
        node_id: command.node_id,
        input_plugs: [...nextNode.input_plugs],
        expected_plug_ids: node.input_plugs.map((plug) => plug.id),
      });
    }
  }
}

/**
 * Map an accepted Project command onto the local authoring vocabulary.
 *
 * `document` is the Graph the caller has open: an accepted command addressed to
 * another Graph of the same Project is reported as not-applicable here rather
 * than applied to the wrong canvas.
 */
export function toLocalGraphCommand(
  command: RoomProjectCommand,
  document?: AuthoredGraphDocument,
  graphId?: string,
): GraphCommand | null {
  const body = inGraphBody(command, graphId);
  if (body === null) return null;
  switch (body.kind) {
    case "move_nodes":
      return {
        kind: "move_nodes",
        positions: body.positions.map((position) => ({
          node_id: position.node_id,
          x: position.x,
          y: position.y,
        })),
      };
    case "add_node":
      return { kind: "add_node", node: projectSavedGraphNode(body.node) };
    case "remove_nodes":
      return { kind: "remove_nodes", node_ids: body.node_ids };
    case "add_edge":
      return { kind: "add_edge", edge: body.edge };
    case "remove_edges":
      return { kind: "remove_edges", edge_ids: body.edge_ids };
    case "rename_graph":
      return { kind: "rename_graph", name: body.name };
    case "update_node_configuration":
      return {
        kind: "update_node_configuration",
        node_id: body.node_id,
        field: body.field,
        value: body.value,
      };
    case "update_node_layout":
      return {
        kind: "update_node_layout",
        node_id: body.node_id,
        layout: body.layout,
      };
    case "update_node_configuration_and_input_plugs":
      return {
        kind: "update_node_configuration_and_input_plugs",
        node_id: body.node_id,
        config: body.config,
        input_plugs: body.input_plugs,
      };
    case "set_node_artifact_type_binding":
      return {
        kind: "bind_artifact_type",
        node_id: body.node_id,
        variable: body.binding.variable,
        artifact_type: body.binding.artifact_type,
      };
    case "clear_node_artifact_type_binding":
      return {
        kind: "reset_artifact_type_binding",
        node_id: body.node_id,
        variable: body.variable,
      };
    case "set_node_input_plugs": {
      const node = document?.nodes.find(
        (candidate) => candidate.id === body.node_id,
      );
      if (!node) return null;
      return {
        kind: "update_node_configuration_and_input_plugs",
        node_id: body.node_id,
        config: { ...(node.config ?? {}) },
        input_plugs: body.input_plugs,
      };
    }
    case "update_edge":
      return {
        kind: "update_edge",
        edge_id: body.edge.id,
        update: {
          enabled: body.edge.enabled,
          collection_mode: body.edge.collection_mode,
          projection: body.edge.projection,
          conversion_path: body.edge.conversion_path,
          route_offset: body.edge.route_offset,
        },
      };
    case "add_origin":
      return { kind: "add_origin", origin: body.origin };
    case "update_origin":
      return {
        kind: "update_origin",
        origin_id: body.origin.id,
        update: {
          to_node: body.origin.to_node,
          to_port: body.origin.to_port,
          to_plug: body.origin.to_plug,
          value: body.origin.value,
          collection_mode: body.origin.collection_mode,
          conversion_path: body.origin.conversion_path,
        },
      };
    case "remove_origins":
      return { kind: "remove_origins", origin_ids: body.origin_ids };
    case "replace_document":
      return {
        kind: "replace_document",
        document: authoredGraphDocument({
          name: document?.name ?? "",
          document: body.document,
        }),
      };
    case "duplicate_node":
      return { kind: "add_node", node: projectSavedGraphNode(body.node) };
    case "replace_presentation":
    case "move_artifact_viewers":
    case "move_annotations":
      return null;
  }
}

/**
 * The Graph-scoped half of an accepted command, or null when it belongs to
 * another Graph or to the Project as a whole.
 */
function inGraphBody(
  command: RoomProjectCommand,
  graphId?: string,
): RoomGraphBodyCommand | null {
  if (command.kind !== "in_graph") return null;
  if (graphId !== undefined && command.graph_id !== graphId) return null;
  return command.command;
}

/** The Graph a command batch is addressed to, when every entry names the same one. */
export function commandBatchGraphId(
  commands: readonly RoomProjectCommand[],
): string | null {
  const graphIds = new Set(
    commands
      .filter((command) => command.kind === "in_graph")
      .map((command) =>
        command.kind === "in_graph" ? command.graph_id : null,
      ),
  );
  if (graphIds.size !== 1) return null;
  const [graphId] = [...graphIds];
  return typeof graphId === "string" ? graphId : null;
}

function prunePresentationLinks(
  presentation: GraphPresentation,
  removedNodeIds: ReadonlySet<string>,
): GraphPresentation {
  if (!removedNodeIds.size) return presentation;
  return {
    ...presentation,
    links: presentation.links.filter(
      (link) => !removedNodeIds.has(link.source_node_id),
    ),
  };
}

/** One Graph of a Project document, as the canvas sees it. */
export function savedGraphFromProjectHead(
  head: CollaborativeHead,
  graphId: string,
): SavedGraph | null {
  const graph = head.document.graphs.find(
    (candidate: GraphDefinition) => candidate.id === graphId,
  );
  if (!graph) return null;
  return {
    id: graph.id,
    name: graph.name,
    revision: head.collaboration_sequence,
    created_at: head.updated_at,
    updated_at: head.updated_at,
    document: graph.document,
  };
}

/** The Graph a Workbench opens: the one it was showing, else the first one. */
export function defaultGraphId(head: CollaborativeHead): string | null {
  const [first] = head.document.graphs;
  return first ? first.id : null;
}

/**
 * Replay an accepted command batch onto the confirmed head.
 *
 * A batch is one unit: the head advances by one sequence for the whole of it,
 * and a command addressed to a Graph this client does not hold still counts
 * against that Graph's document, because the document is the shared fact.
 */
export function applyRoomCommandsToHead(
  head: CollaborativeHead,
  commands: readonly RoomProjectCommand[],
  sequence: number,
): CollaborativeHead {
  let next = head;
  for (const command of commands) {
    next = applyRoomCommandToHead(next, command, sequence);
  }
  return next;
}

/** Replay one accepted Project command onto the confirmed head. */
export function applyRoomCommandToHead(
  head: CollaborativeHead,
  command: RoomProjectCommand,
  sequence: number,
): CollaborativeHead {
  if (command.kind === "rename_project") {
    return {
      ...head,
      name: command.name,
      collaboration_sequence: sequence,
    };
  }

  if (command.kind === "add_graph") {
    if (head.document.graphs.some((graph) => graph.id === command.graph_id)) {
      return { ...head, collaboration_sequence: sequence };
    }
    const graph: GraphDefinition = {
      id: command.graph_id,
      name: command.name,
      document:
        command.document ??
        ({
          schema_version: 7,
          nodes: [],
          edges: [],
          origins: [],
          presentation: emptyGraphPresentation(),
        } satisfies SavedGraphDocument),
    };
    return {
      ...head,
      document: { graphs: [...head.document.graphs, graph] },
      collaboration_sequence: sequence,
    };
  }

  if (command.kind === "remove_graph") {
    return {
      ...head,
      document: {
        graphs: head.document.graphs.filter(
          (graph) => graph.id !== command.graph_id,
        ),
      },
      collaboration_sequence: sequence,
    };
  }

  if (command.kind === "rename_graph") {
    return {
      ...head,
      document: {
        graphs: head.document.graphs.map((graph) =>
          graph.id === command.graph_id
            ? { ...graph, name: command.name }
            : graph,
        ),
      },
      collaboration_sequence: sequence,
    };
  }

  if (command.kind === "refresh_node") {
    // A refresh raises the generation the node's inputs are pinned to; the
    // instance's derived state comes from the Run, not from this document.
    return { ...head, collaboration_sequence: sequence };
  }

  if (command.kind === "add_call_node") {
    return mapGraphDocument(head, command.graph_id, (graph, presentation) => {
      const nodes = graph.document.nodes.map((node) =>
        node.id === command.node_id
          ? {
              ...node,
              kind: "call" as const,
              position: command.position,
            }
          : node,
      );
      return withGraphDocument(graph, {
        ...graph.document,
        nodes,
        presentation,
      });
    }, sequence);
  }

  if (command.kind !== "in_graph") {
    return { ...head, collaboration_sequence: sequence };
  }

  const body = command.command;

  if (body.kind === "replace_document") {
    return mapGraphDocument(
      head,
      command.graph_id,
      (graph) =>
        withGraphDocument(graph, {
          ...body.document,
          presentation:
            body.document.presentation ?? graph.document.presentation,
        }),
      sequence,
    );
  }

  if (body.kind === "replace_presentation") {
    return mapGraphDocument(
      head,
      command.graph_id,
      (graph) =>
        withGraphDocument(graph, {
          ...graph.document,
          presentation: body.presentation,
        }),
      sequence,
    );
  }

  if (body.kind === "move_artifact_viewers") {
    return mapGraphDocument(
      head,
      command.graph_id,
      (graph) => {
        const positions = new Map(
          body.positions.map((position) => [
            position.viewer_id,
            { x: position.x, y: position.y },
          ]),
        );
        const presentation = presentationFromGraphDocument(graph.document);
        return withGraphDocument(graph, presentationIntoDocument(graph.document, {
          ...presentation,
          viewers: presentation.viewers.map((viewer) => {
            const position = positions.get(viewer.id);
            return position ? { ...viewer, position } : viewer;
          }),
        }));
      },
      sequence,
    );
  }

  if (body.kind === "move_annotations") {
    return mapGraphDocument(
      head,
      command.graph_id,
      (graph) => {
        const positions = new Map(
          body.positions.map((position) => [
            position.annotation_id,
            { x: position.x, y: position.y },
          ]),
        );
        const presentation = presentationFromGraphDocument(graph.document);
        return withGraphDocument(graph, presentationIntoDocument(graph.document, {
          ...presentation,
          annotations: presentation.annotations.map((annotation) => {
            const position = positions.get(annotation.id);
            return position ? { ...annotation, position } : annotation;
          }),
        }));
      },
      sequence,
    );
  }

  if (body.kind === "set_node_input_plugs") {
    return mapGraphDocument(
      head,
      command.graph_id,
      (graph) =>
        withGraphDocument(graph, {
          ...graph.document,
          nodes: graph.document.nodes.map((node) =>
            node.id === body.node_id
              ? { ...node, input_plugs: [...body.input_plugs] }
              : node,
          ),
        }),
      sequence,
    );
  }

  return mapGraphDocument(
    head,
    command.graph_id,
    (graph) => {
      const base = authoredGraphDocument({
        name: graph.name,
        document: graph.document,
      });
      const local = toLocalGraphCommand(command, base, graph.id);
      if (!local) return graph;
      const nextDocument = applyGraphCommand(base, local);
      let presentation = presentationFromGraphDocument(graph.document);
      if (local.kind === "remove_nodes") {
        presentation = prunePresentationLinks(
          presentation,
          new Set(local.node_ids),
        );
      }
      const draft = createGraphDraft(nextDocument, presentation);
      return withGraphDocument(graph, draft.document);
    },
    sequence,
  );
}

function mapGraphDocument(
  head: CollaborativeHead,
  graphId: string,
  update: (graph: GraphDefinition) => GraphDefinition,
  sequence: number,
): CollaborativeHead {
  const graphs = head.document.graphs;
  const exists = graphs.some((graph) => graph.id === graphId);
  if (!exists) {
    // A command for a Graph this head does not hold is a protocol fault the
    // caller resolves by rehydrating; keeping the sequence moving is what lets
    // the next accepted command apply.
    return { ...head, collaboration_sequence: sequence };
  }
  return {
    ...head,
    document: {
      graphs: graphs.map((graph) =>
        graph.id === graphId ? update(graph) : graph,
      ),
    },
    collaboration_sequence: sequence,
  };
}

function withGraphDocument(
  graph: GraphDefinition,
  document: SavedGraphDocument,
): GraphDefinition {
  return { ...graph, document };
}

function presentationIntoDocument(
  document: SavedGraphDocument,
  presentation: GraphPresentation,
): SavedGraphDocument {
  const body: GraphPresentationDocument = {
    viewers: [...presentation.viewers],
    links: [...presentation.links],
    bindings: [...presentation.bindings],
    annotations: [...presentation.annotations],
  };
  return { ...document, presentation: body };
}

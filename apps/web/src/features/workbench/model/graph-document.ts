import type {
  CreateSavedGraphRequest,
  SavedGraphDocument,
  SavedGraphEdge,
  SavedGraphNode,
} from "@/lib/api";

/**
 * The durable, authored part of a Workbench graph.
 *
 * This type deliberately contains no React Flow objects, callbacks, selection,
 * viewport state, execution state, or secret values. It is the client-side
 * document that can later be sent over a semantic collaboration protocol.
 */
export interface AuthoredGraphDocument {
  readonly name: string;
  readonly nodes: readonly SavedGraphNode[];
  readonly edges: readonly SavedGraphEdge[];
}

export type AuthoredGraphNode = SavedGraphNode;
export type AuthoredGraphEdge = SavedGraphEdge;

type SavedGraphEdgeUpdate = Partial<
  Pick<
    AuthoredGraphEdge,
    | "collection_mode"
    | "enabled"
    | "projection"
    | "conversion_path"
    | "route_offset"
    | "to_plug"
    | "from_port"
    | "to_port"
  >
>;

export type GraphCommand =
  | {
      readonly kind: "rename_graph";
      readonly name: string;
    }
  | {
      readonly kind: "add_node";
      readonly node: AuthoredGraphNode;
    }
  | {
      readonly kind: "remove_nodes";
      readonly node_ids: readonly string[];
    }
  | {
      readonly kind: "move_nodes";
      readonly positions: readonly {
        readonly node_id: string;
        readonly x: number;
        readonly y: number;
      }[];
    }
  | {
      readonly kind: "update_node_configuration";
      readonly node_id: string;
      readonly field: string;
      readonly value: unknown;
    }
  | {
      readonly kind: "update_node_layout";
      readonly node_id: string;
      readonly layout: AuthoredGraphNode["layout"];
    }
  | {
      readonly kind: "update_node_plugin_release";
      readonly node_id: string;
      readonly plugin_release: NonNullable<
        AuthoredGraphNode["plugin_release_pin"]
      >;
    }
  | {
      readonly kind: "add_input_plug";
      readonly node_id: string;
      readonly plug: NonNullable<AuthoredGraphNode["input_plugs"]>[number];
    }
  | {
      readonly kind: "remove_input_plug";
      readonly node_id: string;
      readonly plug_id: string;
    }
  | {
      readonly kind: "reorder_input_plug";
      readonly node_id: string;
      readonly port: string;
      readonly plug_id: string;
      readonly to_index: number;
    }
  | {
      readonly kind: "update_node_configuration_and_input_plugs";
      readonly node_id: string;
      readonly config: Readonly<Record<string, unknown>>;
      readonly input_plugs: readonly NonNullable<
        AuthoredGraphNode["input_plugs"]
      >[number][];
    }
  | {
      readonly kind: "bind_artifact_type";
      readonly node_id: string;
      readonly variable: string;
      readonly artifact_type: NonNullable<
        AuthoredGraphNode["artifact_type_bindings"]
      >[number]["artifact_type"];
    }
  | {
      readonly kind: "reset_artifact_type_binding";
      readonly node_id: string;
      readonly variable: string;
    }
  | {
      readonly kind: "add_edge";
      readonly edge: AuthoredGraphEdge;
    }
  | {
      readonly kind: "update_edge";
      readonly edge_id: string;
      readonly update: SavedGraphEdgeUpdate;
    }
  | {
      readonly kind: "remove_edges";
      readonly edge_ids: readonly string[];
    }
  | {
      readonly kind: "replace_document";
      readonly document: AuthoredGraphDocument;
    };

export function authoredGraphDocument(
  value: Pick<CreateSavedGraphRequest, "name" | "document">,
): AuthoredGraphDocument {
  return {
    name: value.name,
    nodes: value.document.nodes.map(projectSavedGraphNode),
    edges: value.document.edges.map(projectSavedGraphEdge),
  };
}

export function createSavedGraphRequest(
  document: AuthoredGraphDocument,
  presentation?: SavedGraphDocument["presentation"],
): CreateSavedGraphRequest {
  return {
    name: document.name.trim(),
    document: {
      schema_version: 6,
      nodes: document.nodes.map(projectSavedGraphNode),
      edges: document.edges.map(projectSavedGraphEdge),
      presentation: presentation ?? {
        viewers: [],
        links: [],
        bindings: [],
        annotations: [],
      },
    },
  };
}

export function projectSavedGraphNode(
  node: SavedGraphNode,
): SavedGraphNode {
  const pluginReleasePin = node.plugin_release_pin;
  return {
    artifact_type_bindings: (node.artifact_type_bindings ?? []).map(
      projectArtifactTypeBinding,
    ),
    config: structuredClone(node.config ?? {}),
    id: node.id,
    kind: node.kind,
    input_plugs: (node.input_plugs ?? []).map(projectSavedGraphInputPlug),
    layout: projectSavedGraphLayout(node.layout),
    operator_id: node.operator_id,
    operator_version: node.operator_version,
    plugin_release_pin:
      pluginReleasePin === null || pluginReleasePin === undefined
        ? null
        : {
            scope: pluginReleasePin.scope,
            slug: pluginReleasePin.slug,
            revision: pluginReleasePin.revision,
          },
    position: {
      x: node.position.x,
      y: node.position.y,
    },
  };
}

function projectSavedGraphLayout(
  layout: SavedGraphNode["layout"],
): SavedGraphNode["layout"] {
  return layout === null || layout === undefined
    ? null
    : {
        appendix_height: layout.appendix_height ?? null,
        body_height: layout.body_height ?? null,
        width: layout.width ?? null,
      };
}

function projectSavedGraphInputPlug(
  plug: NonNullable<SavedGraphNode["input_plugs"]>[number],
): NonNullable<SavedGraphNode["input_plugs"]>[number] {
  return { id: plug.id, port: plug.port };
}

function projectArtifactTypeBinding(
  binding: NonNullable<SavedGraphNode["artifact_type_bindings"]>[number],
): NonNullable<SavedGraphNode["artifact_type_bindings"]>[number] {
  return {
    variable: binding.variable,
    artifact_type: {
      id: binding.artifact_type.id,
      schema_version: binding.artifact_type.schema_version,
    },
  };
}

export function projectSavedGraphEdge(
  edge: SavedGraphEdge,
): SavedGraphEdge {
  return {
    collection_mode: edge.collection_mode ?? "direct",
    conversion_path: (edge.conversion_path ?? []).map((conversion) => ({
      id: conversion.id,
      version: conversion.version,
    })),
    enabled: edge.enabled ?? true,
    from_node: edge.from_node,
    from_port: edge.from_port,
    id: edge.id,
    projection:
      edge.projection === null || edge.projection === undefined
        ? null
        : { path: [...edge.projection.path] },
    route_offset:
      edge.route_offset === null || edge.route_offset === undefined
        ? null
        : { x: edge.route_offset.x, y: edge.route_offset.y },
    to_node: edge.to_node,
    to_plug: edge.to_plug ?? null,
    to_port: edge.to_port,
  };
}

function projectSavedGraphEdgeUpdate(
  update: SavedGraphEdgeUpdate,
): SavedGraphEdgeUpdate {
  const projected = {} as {
    -readonly [Key in keyof SavedGraphEdgeUpdate]: SavedGraphEdgeUpdate[Key];
  };
  if (Object.prototype.hasOwnProperty.call(update, "collection_mode")) {
    projected.collection_mode = update.collection_mode;
  }
  if (Object.prototype.hasOwnProperty.call(update, "enabled")) {
    projected.enabled = update.enabled;
  }
  if (Object.prototype.hasOwnProperty.call(update, "projection")) {
    projected.projection =
      update.projection === null || update.projection === undefined
        ? null
        : { path: [...update.projection.path] };
  }
  if (Object.prototype.hasOwnProperty.call(update, "conversion_path")) {
    projected.conversion_path = (update.conversion_path ?? []).map(
      ({ id, version }) => ({
        id,
        version,
      }),
    );
  }
  if (Object.prototype.hasOwnProperty.call(update, "route_offset")) {
    projected.route_offset =
      update.route_offset === null || update.route_offset === undefined
        ? null
        : { x: update.route_offset.x, y: update.route_offset.y };
  }
  if (Object.prototype.hasOwnProperty.call(update, "to_plug")) {
    projected.to_plug = update.to_plug ?? null;
  }
  if (Object.prototype.hasOwnProperty.call(update, "from_port")) {
    projected.from_port = update.from_port;
  }
  if (Object.prototype.hasOwnProperty.call(update, "to_port")) {
    projected.to_port = update.to_port;
  }
  return projected;
}

function executionDescendants(
  document: AuthoredGraphDocument,
  roots: readonly string[],
): Set<string> {
  const knownNodeIds = new Set(document.nodes.map((node) => node.id));
  const invalidated = new Set(
    roots.filter((nodeId) => knownNodeIds.has(nodeId)),
  );
  const pending = [...invalidated];
  while (pending.length) {
    const sourceNodeId = pending.shift();
    if (!sourceNodeId) continue;
    for (const edge of document.edges) {
      if (
        edge.enabled === false ||
        edge.from_node !== sourceNodeId ||
        invalidated.has(edge.to_node) ||
        !knownNodeIds.has(edge.to_node)
      ) {
        continue;
      }
      invalidated.add(edge.to_node);
      pending.push(edge.to_node);
    }
  }
  return invalidated;
}

/** Return the runtime execution scope affected by one authored command. */
export function executionInvalidatedNodeIds(
  document: AuthoredGraphDocument,
  command: GraphCommand,
): Set<string> {
  switch (command.kind) {
    case "update_node_configuration":
    case "update_node_configuration_and_input_plugs":
    case "update_node_plugin_release":
    case "add_input_plug":
    case "remove_input_plug":
    case "reorder_input_plug":
    case "bind_artifact_type":
    case "reset_artifact_type_binding":
      return executionDescendants(document, [command.node_id]);
    case "add_edge":
      return executionDescendants(document, [command.edge.to_node]);
    case "update_edge": {
      if (Object.keys(command.update).every((key) => key === "route_offset")) {
        return new Set();
      }
      const edge = document.edges.find(
        (candidate) => candidate.id === command.edge_id,
      );
      return edge ? executionDescendants(document, [edge.to_node]) : new Set();
    }
    case "remove_edges":
      return executionDescendants(
        document,
        document.edges
          .filter((edge) => command.edge_ids.includes(edge.id))
          .map((edge) => edge.to_node),
      );
    case "remove_nodes":
      return executionDescendants(
        document,
        document.edges
          .filter((edge) => command.node_ids.includes(edge.from_node))
          .map((edge) => edge.to_node),
      );
    case "rename_graph":
    case "add_node":
    case "move_nodes":
    case "update_node_layout":
      return new Set();
    case "replace_document":
      return new Set(document.nodes.map((node) => node.id));
  }
}

function nodeOrThrow(
  document: AuthoredGraphDocument,
  nodeId: string,
): AuthoredGraphNode {
  const node = document.nodes.find((candidate) => candidate.id === nodeId);
  if (!node) throw new Error(`Graph command targets missing node ${nodeId}`);
  return node;
}

function edgeOrThrow(
  document: AuthoredGraphDocument,
  edgeId: string,
): AuthoredGraphEdge {
  const edge = document.edges.find((candidate) => candidate.id === edgeId);
  if (!edge) throw new Error(`Graph command targets missing edge ${edgeId}`);
  return edge;
}

function updateNode(
  document: AuthoredGraphDocument,
  nodeId: string,
  update: (node: AuthoredGraphNode) => AuthoredGraphNode,
): AuthoredGraphDocument {
  nodeOrThrow(document, nodeId);
  return {
    ...document,
    nodes: document.nodes.map((node) =>
      node.id === nodeId ? update(structuredClone(node)) : node,
    ),
  };
}

/**
 * Apply one command to an already-normalized authored document without
 * re-normalizing or deep-cloning the whole document. Callers that batch
 * several commands normalize the starting document once and then reuse this
 * canonical transition to avoid O(K × (V+E)) work per batch.
 */
export function applyGraphCommandNormalized(
  document: AuthoredGraphDocument,
  command: GraphCommand,
): AuthoredGraphDocument {
  switch (command.kind) {
    case "rename_graph":
      return { ...document, name: command.name };
    case "add_node":
      if (document.nodes.some((node) => node.id === command.node.id)) {
        throw new Error(`Graph command adds duplicate node ${command.node.id}`);
      }
      return {
        ...document,
        nodes: [...document.nodes, projectSavedGraphNode(command.node)],
      };
    case "remove_nodes": {
      const removed = new Set(command.node_ids);
      return {
        ...document,
        nodes: document.nodes.filter((node) => !removed.has(node.id)),
        edges: document.edges.filter(
          (edge) => !removed.has(edge.from_node) && !removed.has(edge.to_node),
        ),
      };
    }
    case "move_nodes": {
      for (const position of command.positions)
        nodeOrThrow(document, position.node_id);
      const positions = new Map(
        command.positions.map((position) => [position.node_id, position]),
      );
      return {
        ...document,
        nodes: document.nodes.map((node) => {
          const position = positions.get(node.id);
          return position
            ? { ...node, position: { x: position.x, y: position.y } }
            : node;
        }),
      };
    }
    case "update_node_configuration":
      return updateNode(document, command.node_id, (node) => ({
        ...node,
        config: {
          ...(node.config ?? {}),
          [command.field]: structuredClone(command.value),
        },
      }));
    case "update_node_layout":
      return updateNode(document, command.node_id, (node) => ({
        ...node,
        layout: projectSavedGraphLayout(command.layout),
      }));
    case "update_node_plugin_release":
      return updateNode(document, command.node_id, (node) => ({
        ...node,
        plugin_release_pin: {
          scope: command.plugin_release.scope,
          slug: command.plugin_release.slug,
          revision: command.plugin_release.revision,
        },
      }));
    case "add_input_plug":
      return updateNode(document, command.node_id, (node) => ({
        ...node,
        input_plugs: [
          ...(node.input_plugs ?? []),
          projectSavedGraphInputPlug(command.plug),
        ],
      }));
    case "remove_input_plug": {
      const next = updateNode(document, command.node_id, (node) => ({
        ...node,
        input_plugs: (node.input_plugs ?? []).filter(
          (plug) => plug.id !== command.plug_id,
        ),
      }));
      return {
        ...next,
        edges: next.edges.filter(
          (edge) =>
            edge.to_node !== command.node_id ||
            edge.to_plug !== command.plug_id,
        ),
      };
    }
    case "reorder_input_plug":
      return updateNode(document, command.node_id, (node) => {
        const plugs = [...(node.input_plugs ?? [])];
        const currentIndex = plugs.findIndex(
          (plug) => plug.id === command.plug_id && plug.port === command.port,
        );
        if (currentIndex < 0) {
          throw new Error(
            `Graph command targets missing input plug ${command.plug_id}`,
          );
        }
        const [plug] = plugs.splice(currentIndex, 1);
        if (!plug)
          throw new Error("Graph command could not reorder input plug");
        plugs.splice(
          Math.max(0, Math.min(command.to_index, plugs.length)),
          0,
          plug,
        );
        return { ...node, input_plugs: plugs };
      });
    case "update_node_configuration_and_input_plugs": {
      const next = updateNode(document, command.node_id, (node) => ({
        ...node,
        config: structuredClone(command.config),
        input_plugs: command.input_plugs.map(projectSavedGraphInputPlug),
      }));
      const retainedPlugIds = new Set(
        command.input_plugs.map((plug) => plug.id),
      );
      return {
        ...next,
        edges: next.edges.filter(
          (edge) =>
            edge.to_node !== command.node_id ||
            edge.to_plug === null ||
            edge.to_plug === undefined ||
            retainedPlugIds.has(edge.to_plug),
        ),
      };
    }
    case "bind_artifact_type":
      return updateNode(document, command.node_id, (node) => ({
        ...node,
        artifact_type_bindings: [
          ...(node.artifact_type_bindings ?? []).filter(
            (binding) => binding.variable !== command.variable,
          ),
          {
            variable: command.variable,
            artifact_type: projectArtifactTypeBinding({
              variable: command.variable,
              artifact_type: command.artifact_type,
            }).artifact_type,
          },
        ],
      }));
    case "reset_artifact_type_binding":
      return updateNode(document, command.node_id, (node) => ({
        ...node,
        artifact_type_bindings: (node.artifact_type_bindings ?? []).filter(
          (binding) => binding.variable !== command.variable,
        ),
      }));
    case "add_edge":
      if (document.edges.some((edge) => edge.id === command.edge.id)) {
        throw new Error(`Graph command adds duplicate edge ${command.edge.id}`);
      }
      return {
        ...document,
        edges: [...document.edges, projectSavedGraphEdge(command.edge)],
      };
    case "update_edge": {
      edgeOrThrow(document, command.edge_id);
      return {
        ...document,
        edges: document.edges.map((edge) =>
          edge.id === command.edge_id
            ? { ...edge, ...projectSavedGraphEdgeUpdate(command.update) }
            : edge,
        ),
      };
    }
    case "remove_edges": {
      const removed = new Set(command.edge_ids);
      return {
        ...document,
        edges: document.edges.filter((edge) => !removed.has(edge.id)),
      };
    }
    case "replace_document":
      return authoredGraphDocument(createSavedGraphRequest(command.document));
  }
}

/** Normalize the document, apply one command, and return the result. */
export function applyGraphCommand(
  document: AuthoredGraphDocument,
  command: GraphCommand,
): AuthoredGraphDocument {
  return applyGraphCommandNormalized(
    authoredGraphDocument(createSavedGraphRequest(document)),
    command,
  );
}

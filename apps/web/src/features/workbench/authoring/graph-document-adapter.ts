import {
  applyGraphCommandNormalized,
  authoredGraphDocument,
  createSavedGraphRequest,
  executionInvalidatedNodeIds,
  type AuthoredGraphDocument,
  type GraphCommand,
} from "./graph-document";
import { newNodeKind } from "./project-graphs";
import type {
  GraphConnection,
  WorkflowEdge,
  WorkflowNode,
  WorkflowNodeData,
} from "./types";
import { serializeNodeLayout } from "./node-layout";

export type NodeOverlays = Record<
  string,
  Pick<WorkflowNodeData, "run" | "execution" | "progress">
>;

export interface WorkbenchAuthoringState {
  document: AuthoredGraphDocument;
  nodeOverlays: NodeOverlays;
  error: string | null;
}

export type WorkbenchAuthoringAction =
  | {
      kind: "apply_commands";
      commands: readonly GraphCommand[];
    }
  | {
      kind: "replace_document";
      document: AuthoredGraphDocument;
      nodeOverlays: NodeOverlays;
    }
  | {
      kind: "update_overlays";
      update: NodeOverlays;
    }
  | {
      kind: "clear_error";
    };

export function nodeOverlaysFromNodes(
  nodes: readonly WorkflowNode[],
): NodeOverlays {
  return Object.fromEntries(
    nodes.map((node) => [
      node.id,
      {
        run: node.data.run,
        execution: node.data.execution,
        progress: node.data.progress,
      },
    ]),
  );
}

export function reduceWorkbenchAuthoringState(
  state: WorkbenchAuthoringState,
  action: WorkbenchAuthoringAction,
): WorkbenchAuthoringState {
  if (action.kind === "replace_document") {
    const document = authoredGraphDocument(
      createSavedGraphRequest(action.document),
    );
    return {
      document,
      nodeOverlays: action.nodeOverlays,
      error: null,
    };
  }
  if (action.kind === "update_overlays") {
    return { ...state, nodeOverlays: action.update };
  }
  if (action.kind === "clear_error") {
    return { ...state, error: null };
  }

  try {
    // Normalize the starting document once per batch, then apply each command
    // through the canonical transition without re-normalizing per command.
    let nextDocument = authoredGraphDocument(
      createSavedGraphRequest(state.document),
    );
    const invalidatedNodeIds = new Set<string>();
    for (const command of action.commands) {
      for (const nodeId of executionInvalidatedNodeIds(nextDocument, command)) {
        invalidatedNodeIds.add(nodeId);
      }
      nextDocument = applyGraphCommandNormalized(nextDocument, command);
    }

    const nodeOverlays: NodeOverlays = {};
    for (const node of nextDocument.nodes) {
      const previous = state.nodeOverlays[node.id];
      if (!previous) continue;
      nodeOverlays[node.id] = invalidatedNodeIds.has(node.id)
        ? { run: null, execution: { status: "idle" }, progress: null }
        : previous;
    }
    return { document: nextDocument, nodeOverlays, error: null };
  } catch (error) {
    return {
      ...state,
      error: error instanceof Error ? error.message : "Graph edit failed.",
    };
  }
}

/** Project one catalog node into the durable authoring command shape. */
export function addNodeCommand(
  nodeId: string,
  data: WorkflowNodeData,
  position: WorkflowNode["position"],
): Extract<GraphCommand, { readonly kind: "add_node" }> {
  return {
    kind: "add_node",
    node: {
      artifact_type_bindings: Object.entries(data.artifactTypeBindings).map(
        ([variable, artifactType]) => ({
          variable,
          artifact_type: {
            id: artifactType.id,
            schema_version: artifactType.schema_version,
          },
        }),
      ),
      config: structuredClone(data.config),
      id: nodeId,
      kind: newNodeKind(data.spec),
      input_plugs: data.inputPlugs.map((plug) => ({
        id: plug.id,
        port: plug.portName,
      })),
      layout: serializeNodeLayout(data.layout),
      operator_id: data.spec.operator_id,
      operator_version: data.spec.operator_version,
      position: { x: position.x, y: position.y },
    },
  };
}

export function addEdgeCommand(
  connection: GraphConnection,
  data: WorkflowEdge["data"],
  edgeId: string,
): GraphCommand {
  if (
    !connection.source ||
    !connection.target ||
    !connection.sourcePort ||
    !connection.targetPort
  ) {
    throw new Error("Cannot author an edge without typed endpoint ports");
  }
  return {
    kind: "add_edge",
    edge: {
      id: edgeId,
      from_node: connection.source,
      from_port: connection.sourcePort,
      to_node: connection.target,
      to_port: connection.targetPort,
      to_plug: connection.targetPlug ?? null,
      enabled: data?.enabled ?? true,
      collection_mode: data?.collectionMode ?? "direct",
      projection: data?.projection ? { path: [...data.projection.path] } : null,
      conversion_path: (data?.conversionPath ?? []).map((conversion) => ({
        id: conversion.id,
        version: conversion.version,
      })),
      route_offset: data?.routeOffset
        ? { x: data.routeOffset.x, y: data.routeOffset.y }
        : null,
    },
  };
}

import {
  type GraphDraft,
  type NodeRegistry,
  type NodeSpec,
  type RunNodeResult,
  type SavedGraph,
  type SavedGraphEdge,
  type SavedGraphNode,
} from "@/lib/api";
import {
  operatorSpecKey,
  resolveGraphSemantics,
  type ResolvedGraphSemantics,
} from "./graph-semantics";
import { connectionRouteForPortSelection } from "./connection-routes";
import { hydrateNodeLayout } from "./node-layout";
import {
  collectionModesForShapes,
  createWorkflowNodeData,
  defaultNodeLayout,
  portHasInstancePlugs,
  portMetaForPort,
  type WorkflowEdge,
  type WorkflowNode,
  workflowNodeIsSupported,
} from "./types";
import { createGraphDraft, type AuthoredGraphDocument } from "./graph-document";

export type SavedGraphWorkflowNode = WorkflowNode;

export interface HydratedSavedGraph {
  nodes: SavedGraphWorkflowNode[];
  edges: WorkflowEdge[];
}

export function hydrateAuthoredGraphDocument(
  document: AuthoredGraphDocument,
  registry: NodeRegistry,
  nodeRuns: readonly RunNodeResult[] = [],
  semantics?: ResolvedGraphSemantics,
): HydratedSavedGraph {
  return hydrateSavedGraph(
    {
      id: "00000000-0000-4000-8000-000000000000",
      revision: 0,
      created_at: "1970-01-01T00:00:00.000Z",
      updated_at: "1970-01-01T00:00:00.000Z",
      ...createGraphDraft(document),
    },
    registry,
    nodeRuns,
    semantics,
  );
}

export function withMaterializedNodeRuns(
  nodes: readonly SavedGraphWorkflowNode[],
  nodeRuns: readonly RunNodeResult[],
): SavedGraphWorkflowNode[] {
  const runsByNodeId = new Map(
    nodeRuns
      .filter((run) => run.status === "succeeded")
      .map((run) => [run.node_id, run]),
  );

  return nodes.map((node) => {
    const run = runsByNodeId.get(node.id) ?? null;
    return {
      ...node,
      data: {
        ...node.data,
        run,
        execution: run ? { status: "succeeded" } : { status: "idle" },
      },
    };
  });
}

export class SavedGraphHydrationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SavedGraphHydrationError";
  }
}

function unavailableNodeSpec(savedNode: SavedGraphNode): NodeSpec {
  const identity = operatorSpecKey(
    savedNode.operator_id,
    savedNode.operator_version,
  );
  return {
    operator_id: savedNode.operator_id,
    operator_version: savedNode.operator_version,
    plugin_slug: "unavailable",
    origin: "builtin",
    title: savedNode.operator_id,
    description: `Saved operator ${identity} is not available in the live registry.`,
    catalog_visible: false,
    runnable: false,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [],
  };
}

function sortedRecord(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => sortedRecord(item));
  }
  if (typeof value !== "object" || value === null) return value;

  const sorted: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value).sort(([left], [right]) =>
    left.localeCompare(right),
  )) {
    if (item !== undefined) sorted[key] = sortedRecord(item);
  }
  return sorted;
}

export function savedGraphFingerprint(graph: GraphDraft): string {
  const presentation = graph.document.presentation ?? {
    viewers: [],
    links: [],
    bindings: [],
    annotations: [],
  };
  const normalized = {
    name: graph.name,
    schema_version: graph.document.schema_version,
    nodes: [...graph.document.nodes].sort((left, right) =>
      left.id.localeCompare(right.id),
    ),
    edges: [...graph.document.edges].sort((left, right) =>
      left.id.localeCompare(right.id),
    ),
    origins: [...(graph.document.origins ?? [])].sort((left, right) =>
      left.id.localeCompare(right.id),
    ),
    presentation: {
      viewers: [...presentation.viewers].sort((left, right) =>
        left.id.localeCompare(right.id),
      ),
      links: [...presentation.links].sort((left, right) =>
        left.id.localeCompare(right.id),
      ),
      bindings: [...presentation.bindings].sort((left, right) =>
        left.id.localeCompare(right.id),
      ),
      annotations: [...presentation.annotations].sort((left, right) =>
        left.id.localeCompare(right.id),
      ),
    },
  };
  return JSON.stringify(sortedRecord(normalized));
}

/**
 * Fingerprint of execution-relevant graph structure only.
 * Presentation (viewers/annotations) must not block materialization.
 */
export function savedGraphExecutionFingerprint(graph: GraphDraft): string {
  const normalized = {
    name: graph.name,
    schema_version: graph.document.schema_version,
    nodes: [...graph.document.nodes].sort((left, right) =>
      left.id.localeCompare(right.id),
    ),
    edges: [...graph.document.edges].sort((left, right) =>
      left.id.localeCompare(right.id),
    ),
    origins: [...(graph.document.origins ?? [])].sort((left, right) =>
      left.id.localeCompare(right.id),
    ),
  };
  return JSON.stringify(sortedRecord(normalized));
}

function requireEdgeEndpoint(
  savedGraph: SavedGraph,
  edge: SavedGraphEdge,
  nodeById: ReadonlyMap<string, SavedGraphWorkflowNode>,
): {
  sourceNode: SavedGraphWorkflowNode;
  targetNode: SavedGraphWorkflowNode;
} {
  const sourceNode = nodeById.get(edge.from_node);
  if (!sourceNode) {
    throw new SavedGraphHydrationError(
      `Cannot open “${savedGraph.name}”. A connection points at a step that is not on the canvas.`,
    );
  }
  const targetNode = nodeById.get(edge.to_node);
  if (!targetNode) {
    throw new SavedGraphHydrationError(
      `Cannot open “${savedGraph.name}”. A connection points at a step that is not on the canvas.`,
    );
  }
  return { sourceNode, targetNode };
}

function connectionRouteIsValid(
  edge: SavedGraphEdge,
  sourceNode: SavedGraphWorkflowNode,
  targetNode: SavedGraphWorkflowNode,
  registry: NodeRegistry,
): boolean {
  const sourcePort = sourceNode.data.spec.outputs.find(
    (port) => port.name === edge.from_port,
  );
  const targetPort = targetNode.data.spec.inputs.find(
    (port) => port.name === edge.to_port,
  );
  if (!sourcePort || !targetPort) return false;

  return (
    connectionRouteForPortSelection(
      portMetaForPort(
        sourcePort,
        sourcePort.shape,
        undefined,
        sourceNode.data.artifactTypeBindings,
      ),
      portMetaForPort(
        targetPort,
        targetPort.shape,
        edge.to_plug ?? undefined,
        targetNode.data.artifactTypeBindings,
      ),
      registry.artifact_types,
      registry.artifact_conversions,
      {
        projection: edge.projection ?? undefined,
        conversionPath: edge.conversion_path,
      },
    ) !== null
  );
}

export function hydrateSavedGraph(
  savedGraph: SavedGraph,
  registry: NodeRegistry,
  nodeRuns: readonly RunNodeResult[] = [],
  providedSemantics?: ResolvedGraphSemantics,
): HydratedSavedGraph {
  const savedEdges = savedGraph.document.edges;
  const nodeIds = new Set<string>();
  for (const savedNode of savedGraph.document.nodes) {
    if (nodeIds.has(savedNode.id)) {
      throw new SavedGraphHydrationError(
        `Cannot open “${savedGraph.name}”. This file has two steps with the same identity.`,
      );
    }
    nodeIds.add(savedNode.id);
  }

  const semantics =
    providedSemantics ?? resolveGraphSemantics(savedGraph.document, registry);

  const nodes: SavedGraphWorkflowNode[] = savedGraph.document.nodes.map(
    (savedNode: SavedGraphNode) => {
      const resolved = semantics.nodes.get(savedNode.id);
      const spec = resolved?.spec ?? unavailableNodeSpec(savedNode);
      const data = createWorkflowNodeData(spec, savedNode.input_plugs);
      data.compatibility = resolved?.compatibility ?? { status: "supported" };
      data.artifactTypeBindings = resolved
        ? { ...resolved.artifactTypeBindings }
        : {};
      data.config = structuredClone(savedNode.config ?? {});
      data.layout =
        resolved?.compatibility.status === "supported"
          ? (hydrateNodeLayout(savedNode.layout) ?? defaultNodeLayout(spec))
          : hydrateNodeLayout(savedNode.layout);
      return {
        id: savedNode.id,
        position: {
          x: savedNode.position.x,
          y: savedNode.position.y,
        },
        selected: false,
        data,
      } satisfies SavedGraphWorkflowNode;
    },
  );
  const nodeById = new Map(nodes.map((node) => [node.id, node]));

  const savedEdgesToRead = semantics.edgeModeRepairs.size
    ? savedEdges.map((savedEdge: SavedGraphEdge) => {
        const collectionMode = semantics.edgeModeRepairs.get(savedEdge.id);
        return collectionMode
          ? { ...savedEdge, collection_mode: collectionMode }
          : savedEdge;
      })
    : savedEdges;

  const mapEdgeByTargetInput = new Map<string, SavedGraphEdge>();
  const mappedNodeIds = new Set<string>(semantics.authoringMappedNodeIds);
  for (const edge of savedEdgesToRead) {
    if (edge.collection_mode !== "map") continue;
    const targetKey = JSON.stringify([edge.to_node, edge.to_port]);
    const existing = mapEdgeByTargetInput.get(targetKey);
    if (existing) {
      throw new SavedGraphHydrationError(
        `Cannot open “${savedGraph.name}”. A connection uses a list mode this input does not accept.`,
      );
    }
    mapEdgeByTargetInput.set(targetKey, edge);
  }
  const edgeIds = new Set<string>();
  const occupiedTargetPlugIds = new Set<string>();

  const edges = savedEdgesToRead.map((savedEdge: SavedGraphEdge) => {
    if (edgeIds.has(savedEdge.id)) {
      throw new SavedGraphHydrationError(
        `Cannot open “${savedGraph.name}”. This file has two connections with the same identity.`,
      );
    }
    edgeIds.add(savedEdge.id);
    const { sourceNode, targetNode } = requireEdgeEndpoint(
      savedGraph,
      savedEdge,
      nodeById,
    );
    const sourceSupported = workflowNodeIsSupported(sourceNode.data);
    const targetSupported = workflowNodeIsSupported(targetNode.data);
    const sourcePort = sourceSupported
      ? sourceNode.data.spec.outputs.find(
          (port) => port.name === savedEdge.from_port,
        )
      : undefined;
    const targetPort = targetSupported
      ? targetNode.data.spec.inputs.find(
          (port) => port.name === savedEdge.to_port,
        )
      : undefined;
    if (sourceSupported && !sourcePort) {
      throw new SavedGraphHydrationError(
        `Cannot open “${savedGraph.name}”. A connection points at an input that is not on that step.`,
      );
    }
    if (targetSupported && !targetPort) {
      throw new SavedGraphHydrationError(
        `Cannot open “${savedGraph.name}”. A connection points at an input that is not on that step.`,
      );
    }

    const compatibilityIssues: string[] = [];
    if (!sourceSupported || !targetSupported) {
      if (sourceNode.data.compatibility.status !== "supported") {
        compatibilityIssues.push(
          ...sourceNode.data.compatibility.issues.map(
            (issue) => `${sourceNode.id}: ${issue}`,
          ),
        );
      }
      if (targetNode.data.compatibility.status !== "supported") {
        compatibilityIssues.push(
          ...targetNode.data.compatibility.issues.map(
            (issue) => `${targetNode.id}: ${issue}`,
          ),
        );
      }
    } else {
      if (!sourcePort || !targetPort) {
        throw new SavedGraphHydrationError(
          `Cannot open “${savedGraph.name}”. A connection points at an input that is not on that step.`,
        );
      }
      if (portHasInstancePlugs(targetPort)) {
        const targetPlug = targetNode.data.inputPlugs.find(
          (plug) =>
            plug.id === savedEdge.to_plug && plug.portName === targetPort.name,
        );
        if (!targetPlug) {
          throw new SavedGraphHydrationError(
            `Cannot open “${savedGraph.name}”. A connection points at a slot that was removed.`,
          );
        }
        const targetPlugKey = `${targetNode.id}::${targetPlug.id}`;
        if (occupiedTargetPlugIds.has(targetPlugKey)) {
          throw new SavedGraphHydrationError(
            `Cannot open “${savedGraph.name}”. Two connections land on the same slot.`,
          );
        }
        occupiedTargetPlugIds.add(targetPlugKey);
      } else if (
        savedEdge.to_plug !== null &&
        savedEdge.to_plug !== undefined
      ) {
        throw new SavedGraphHydrationError(
          `Cannot open “${savedGraph.name}”. A step has a slot the input does not allow.`,
        );
      }

      const sourceShape = mappedNodeIds.has(sourceNode.id)
        ? "many"
        : sourcePort.shape;
      const otherMapEdge = mapEdgeByTargetInput.get(
        JSON.stringify([targetNode.id, targetPort.name]),
      );
      const targetShape =
        otherMapEdge !== savedEdge && otherMapEdge?.to_port === targetPort.name
          ? "many"
          : targetPort.shape;
      const expectedCollectionModes = collectionModesForShapes(
        sourceShape,
        targetPort,
        targetShape,
      );
      if (!expectedCollectionModes.includes(savedEdge.collection_mode)) {
        throw new SavedGraphHydrationError(
          `Cannot open “${savedGraph.name}”. A connection uses a list mode this input does not accept.`,
        );
      }

      if (
        !connectionRouteIsValid(savedEdge, sourceNode, targetNode, registry)
      ) {
        throw new SavedGraphHydrationError(
          `Cannot open “${savedGraph.name}”. A connection joins two kinds of document that do not fit.`,
        );
      }
    }

    return {
      id: savedEdge.id,
      source: savedEdge.from_node,
      sourcePort: savedEdge.from_port,
      target: savedEdge.to_node,
      targetPort: savedEdge.to_port,
      targetPlug: savedEdge.to_plug ?? null,
      data: {
        enabled: savedEdge.enabled,
        collectionMode: savedEdge.collection_mode,
        ...(compatibilityIssues.length ? { compatibilityIssues } : {}),
        ...(savedEdge.projection
          ? { projection: { path: [...savedEdge.projection.path] } }
          : {}),
        conversionPath: [...savedEdge.conversion_path].map((conversion) => ({
          id: conversion.id,
          version: conversion.version,
        })),
        ...(savedEdge.route_offset
          ? {
              routeOffset: {
                x: savedEdge.route_offset.x,
                y: savedEdge.route_offset.y,
              },
            }
          : {}),
      },
    } satisfies WorkflowEdge;
  });

  return { nodes: withMaterializedNodeRuns(nodes, nodeRuns), edges };
}

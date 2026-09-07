import type { Node } from "@xyflow/react";

import {
  type CreateSavedGraphRequest,
  type NodeRegistry,
  type NodeSpec,
  type PluginReleasePin,
  type RunNodeResult,
  type SavedGraph,
  type SavedGraphEdge,
  type SavedGraphNode,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  connectionRouteForSelection,
  encodeHandleId,
} from "./handles";
import {
  hydrateNodeLayout,
} from "./node-layout";
import { artifactTypeColor } from "./nodes.css";
import {
  WORKFLOW_EDGE_TYPE,
  WORKFLOW_NODE_TYPE,
  acceptedPortShapes,
  compatibilityHandleId,
  createWorkflowNodeData,
  defaultNodeLayout,
  declaredArtifactTypeVariables,
  portHasInstancePlugs,
  portMetaForPort,
  resolvedPortArtifactType,
  type WorkflowEdge,
  type WorkflowArtifactTypeBindingInput,
  type WorkflowArtifactTypeBindings,
  type WorkflowCompatibilityEndpoint,
  type WorkflowNodeData,
  workflowNodeIsSupported,
} from "./types";
import {
  createSavedGraphRequest,
  type AuthoredGraphDocument,
} from "../model/graph-document";

export type SavedGraphWorkflowNode = Node<
  WorkflowNodeData,
  typeof WORKFLOW_NODE_TYPE
>;

export interface HydratedSavedGraph {
  nodes: SavedGraphWorkflowNode[];
  edges: WorkflowEdge[];
}

export function hydrateAuthoredGraphDocument(
  document: AuthoredGraphDocument,
  registry: NodeRegistry,
  nodeRuns: readonly RunNodeResult[] = [],
): HydratedSavedGraph {
  return hydrateSavedGraph(
    {
      id: "00000000-0000-4000-8000-000000000000",
      revision: 0,
      created_at: "1970-01-01T00:00:00.000Z",
      updated_at: "1970-01-01T00:00:00.000Z",
      ...createSavedGraphRequest(document),
    },
    registry,
    nodeRuns,
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

function operatorKey(operatorId: string, operatorVersion: number): string {
  return `${operatorId}@${operatorVersion}`;
}

function scopedOperatorKey(
  operatorId: string,
  operatorVersion: number,
  pluginRelease: Pick<PluginReleasePin, "scope" | "slug"> | null | undefined,
): string {
  const operator = operatorKey(operatorId, operatorVersion);
  return pluginRelease
    ? `${operator}::${pluginRelease.scope}:${pluginRelease.slug}`
    : operator;
}

function compatibilityEndpoints(
  savedNode: SavedGraphNode,
  savedEdges: readonly SavedGraphEdge[],
): {
  inputs: WorkflowCompatibilityEndpoint[];
  outputs: WorkflowCompatibilityEndpoint[];
} {
  const inputs = new Map<string, WorkflowCompatibilityEndpoint>();
  const outputs = new Map<string, WorkflowCompatibilityEndpoint>();
  for (const plug of savedNode.input_plugs ?? []) {
    inputs.set(`${plug.port}::${plug.id}`, {
      portName: plug.port,
      plugId: plug.id,
    });
  }
  for (const edge of savedEdges) {
    if (edge.to_node === savedNode.id) {
      const endpoint = {
        portName: edge.to_port,
        ...(edge.to_plug ? { plugId: edge.to_plug } : {}),
      };
      inputs.set(`${edge.to_port}::${edge.to_plug ?? ""}`, endpoint);
    }
    if (edge.from_node === savedNode.id) {
      outputs.set(edge.from_port, { portName: edge.from_port });
    }
  }
  return {
    inputs: [...inputs.values()],
    outputs: [...outputs.values()],
  };
}

function unavailableNodeSpec(savedNode: SavedGraphNode): NodeSpec {
  const identity = operatorKey(
    savedNode.operator_id,
    savedNode.operator_version,
  );
  return {
    operator_id: savedNode.operator_id,
    operator_version: savedNode.operator_version,
    plugin_slug: "unavailable",
    origin: savedNode.kind,
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

function persistedPluginReleasePin(
  savedNode: SavedGraphNode,
): WorkflowNodeData["pluginReleasePin"] {
  const pin = savedNode.plugin_release_pin;
  return pin
    ? { scope: pin.scope, slug: pin.slug, revision: pin.revision }
    : null;
}

function incompatibleNodeData(
  savedNode: SavedGraphNode,
  savedEdges: readonly SavedGraphEdge[],
  status: "unsupported" | "invalid",
  issues: readonly string[],
  spec: NodeSpec = unavailableNodeSpec(savedNode),
): WorkflowNodeData {
  const data = createWorkflowNodeData(spec, savedNode.input_plugs ?? []);
  const artifactTypeBindings: Record<
    string,
    WorkflowArtifactTypeBindingInput["artifact_type"]
  > = {};
  for (const binding of savedNode.artifact_type_bindings ?? []) {
    artifactTypeBindings[binding.variable] = {
      id: binding.artifact_type.id,
      schema_version: binding.artifact_type.schema_version,
    };
  }
  data.compatibility = {
    status,
    issues: [...issues],
    ...compatibilityEndpoints(savedNode, savedEdges),
    persistedNode: structuredClone(savedNode),
  };
  data.artifactTypeBindings = artifactTypeBindings;
  data.pluginReleasePin = persistedPluginReleasePin(savedNode);
  data.config = structuredClone(savedNode.config ?? {});
  data.layout = hydrateNodeLayout(savedNode.layout);
  return data;
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

function requireArtifactTypeBindings(
  savedGraph: SavedGraph,
  savedNode: SavedGraphNode,
  spec: NodeSpec,
  registry: NodeRegistry,
): WorkflowArtifactTypeBindings {
  const declaredVariables = new Set(declaredArtifactTypeVariables(spec));
  const registryArtifactTypes = new Set(
    registry.artifact_types.map(
      (artifact) =>
        `${artifact.key.id}@${artifact.key.schema_version}`,
    ),
  );
  const bindings: Record<string, WorkflowArtifactTypeBindingInput["artifact_type"]> = {};
  for (const binding of savedNode.artifact_type_bindings ?? []) {
    if (!declaredVariables.has(binding.variable)) {
      throw new SavedGraphHydrationError(
        `Cannot open “${savedGraph.name}”: node ${savedNode.id} binds undeclared artifact type variable ${binding.variable}`,
      );
    }
    if (binding.variable in bindings) {
      throw new SavedGraphHydrationError(
        `Cannot open “${savedGraph.name}”: node ${savedNode.id} binds artifact type variable ${binding.variable} more than once`,
      );
    }
    const artifactTypeKey =
      `${binding.artifact_type.id}@${binding.artifact_type.schema_version}`;
    if (!registryArtifactTypes.has(artifactTypeKey)) {
      throw new SavedGraphHydrationError(
        `Cannot open “${savedGraph.name}”: node ${savedNode.id} binds unavailable artifact type ${artifactTypeKey}`,
      );
    }
    bindings[binding.variable] = {
      id: binding.artifact_type.id,
      schema_version: binding.artifact_type.schema_version,
    };
  }
  return bindings;
}

export function savedGraphFingerprint(
  graph: CreateSavedGraphRequest,
): string {
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
    edges: [...graph.document.edges]
      .map((edge) => ({
        ...edge,
        enabled: edge.enabled ?? true,
      }))
      .sort((left, right) => left.id.localeCompare(right.id)),
    presentation: {
      viewers: [...(presentation.viewers ?? [])].sort((left, right) =>
        left.id.localeCompare(right.id),
      ),
      links: [...(presentation.links ?? [])].sort((left, right) =>
        left.id.localeCompare(right.id),
      ),
      bindings: [...(presentation.bindings ?? [])].sort((left, right) =>
        left.id.localeCompare(right.id),
      ),
      annotations: [...(presentation.annotations ?? [])].sort((left, right) =>
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
export function savedGraphExecutionFingerprint(
  graph: CreateSavedGraphRequest,
): string {
  const normalized = {
    name: graph.name,
    schema_version: graph.document.schema_version,
    nodes: [...graph.document.nodes].sort((left, right) =>
      left.id.localeCompare(right.id),
    ),
    edges: [...graph.document.edges]
      .map((edge) => ({
        ...edge,
        enabled: edge.enabled ?? true,
      }))
      .sort((left, right) => left.id.localeCompare(right.id)),
  };
  return JSON.stringify(sortedRecord(normalized));
}

function requireInputPlugs(
  savedGraph: SavedGraph,
  savedNode: SavedGraphNode,
  spec: NodeSpec,
): NonNullable<typeof savedNode.input_plugs> {
  const inputPlugs = savedNode.input_plugs ?? [];
  const plugIds = new Set<string>();
  for (const plug of inputPlugs) {
    const port = spec.inputs.find((candidate) => candidate.name === plug.port);
    if (!port || !portHasInstancePlugs(port)) {
      throw new SavedGraphHydrationError(
        `Cannot open “${savedGraph.name}”: node ${savedNode.id} input plug ${plug.id} references non-instance input ${plug.port}`,
      );
    }
    if (plugIds.has(plug.id)) {
      throw new SavedGraphHydrationError(
        `Cannot open “${savedGraph.name}”: node ${savedNode.id} has duplicate input plug id ${plug.id}`,
      );
    }
    plugIds.add(plug.id);
  }
  return inputPlugs;
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
      `Cannot open “${savedGraph.name}”: edge ${edge.id} references missing source node ${edge.from_node}`,
    );
  }
  const targetNode = nodeById.get(edge.to_node);
  if (!targetNode) {
    throw new SavedGraphHydrationError(
      `Cannot open “${savedGraph.name}”: edge ${edge.id} references missing target node ${edge.to_node}`,
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

  const connection = {
    sourceHandle: encodeHandleId(
      portMetaForPort(
        sourcePort,
        sourcePort.shape,
        undefined,
        sourceNode.data.artifactTypeBindings,
      ),
    ),
    targetHandle: encodeHandleId(
      portMetaForPort(
        targetPort,
        targetPort.shape,
        edge.to_plug ?? undefined,
        targetNode.data.artifactTypeBindings,
      ),
    ),
  };
  return connectionRouteForSelection(
    connection,
    registry.artifact_types,
    registry.artifact_conversions,
    {
      projection: edge.projection ?? undefined,
      conversionPath: edge.conversion_path ?? [],
    },
  ) !== null;
}

export function hydrateSavedGraph(
  savedGraph: SavedGraph,
  registry: NodeRegistry,
  nodeRuns: readonly RunNodeResult[] = [],
): HydratedSavedGraph {
  const savedEdges = savedGraph.document.edges;
  const specs = new Map(
    registry.nodes.map((spec) => [
      scopedOperatorKey(
        spec.operator_id,
        spec.operator_version,
        spec.plugin_release,
      ),
      spec,
    ]),
  );
  const nodeIds = new Set<string>();
  const nodes: SavedGraphWorkflowNode[] = savedGraph.document.nodes.map((savedNode) => {
    if (nodeIds.has(savedNode.id)) {
      throw new SavedGraphHydrationError(
        `Cannot open “${savedGraph.name}”: duplicate node id ${savedNode.id}`,
      );
    }
    nodeIds.add(savedNode.id);
    const operatorIdentity = operatorKey(
      savedNode.operator_id,
      savedNode.operator_version,
    );
    const spec = specs.get(
      scopedOperatorKey(
        savedNode.operator_id,
        savedNode.operator_version,
        savedNode.plugin_release_pin,
      ),
    );
    let data: WorkflowNodeData;
    if (!spec) {
      data = incompatibleNodeData(
        savedNode,
        savedEdges,
        "unsupported",
        [
          `Operator ${operatorIdentity} is unavailable. This saved node is preserved but cannot run.`,
        ],
      );
    } else {
      try {
        const inputPlugs = requireInputPlugs(savedGraph, savedNode, spec);
        data = createWorkflowNodeData(spec, inputPlugs);
        data.artifactTypeBindings = requireArtifactTypeBindings(
          savedGraph,
          savedNode,
          spec,
          registry,
        );
        data.pluginReleasePin = persistedPluginReleasePin(savedNode);
        data.config = structuredClone(savedNode.config ?? {});
        data.layout =
          hydrateNodeLayout(savedNode.layout) ?? defaultNodeLayout(spec);
      } catch (error) {
        if (!(error instanceof SavedGraphHydrationError)) throw error;
        const graphPrefix = `Cannot open “${savedGraph.name}”: `;
        const issue = error.message.startsWith(graphPrefix)
          ? error.message.slice(graphPrefix.length)
          : error.message;
        data = incompatibleNodeData(
          savedNode,
          savedEdges,
          "invalid",
          [issue],
          spec,
        );
      }
    }
    return {
      id: savedNode.id,
      type: WORKFLOW_NODE_TYPE,
      position: {
        x: savedNode.position.x,
        y: savedNode.position.y,
      },
      selected: false,
      data,
    } satisfies SavedGraphWorkflowNode;
  });
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const savedNodeById = new Map(
    savedGraph.document.nodes.map((savedNode) => [savedNode.id, savedNode]),
  );

  for (const savedEdge of savedEdges) {
    const sourceNode = nodeById.get(savedEdge.from_node);
    const targetNode = nodeById.get(savedEdge.to_node);
    if (!sourceNode || !targetNode) continue;
    if (
      workflowNodeIsSupported(sourceNode.data) &&
      !sourceNode.data.spec.outputs.some(
        (port) => port.name === savedEdge.from_port,
      )
    ) {
      const savedNode = savedNodeById.get(sourceNode.id);
      if (savedNode) {
        sourceNode.data = incompatibleNodeData(
          savedNode,
          savedEdges,
          "invalid",
          [
            `Saved connection ${savedEdge.id} references removed output ${savedEdge.from_port}.`,
          ],
          sourceNode.data.spec,
        );
      }
    }
    if (
      workflowNodeIsSupported(targetNode.data) &&
      !targetNode.data.spec.inputs.some(
        (port) => port.name === savedEdge.to_port,
      )
    ) {
      const savedNode = savedNodeById.get(targetNode.id);
      if (savedNode) {
        targetNode.data = incompatibleNodeData(
          savedNode,
          savedEdges,
          "invalid",
          [
            `Saved connection ${savedEdge.id} references removed input ${savedEdge.to_port}.`,
          ],
          targetNode.data.spec,
        );
      }
    }
  }
  const mapEdgeByTargetNode = new Map<string, SavedGraphEdge>();
  for (const edge of savedEdges) {
    if (edge.collection_mode !== "map") continue;
    const existing = mapEdgeByTargetNode.get(edge.to_node);
    if (existing) {
      throw new SavedGraphHydrationError(
        `Cannot open “${savedGraph.name}”: node ${edge.to_node} has more than one map edge: ${existing.id} targets input ${existing.to_port} and ${edge.id} targets input ${edge.to_port}; exactly one edge may drive mapped execution`,
      );
    }
    mapEdgeByTargetNode.set(edge.to_node, edge);
  }
  const edgeIds = new Set<string>();
  const occupiedTargetPlugIds = new Set<string>();

  const edges = savedEdges.map((savedEdge) => {
    if (edgeIds.has(savedEdge.id)) {
      throw new SavedGraphHydrationError(
        `Cannot open “${savedGraph.name}”: duplicate edge id ${savedEdge.id}`,
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
        `Cannot open “${savedGraph.name}”: edge ${savedEdge.id} references missing output ${sourceNode.data.spec.operator_id}.${savedEdge.from_port}`,
      );
    }
    if (targetSupported && !targetPort) {
      throw new SavedGraphHydrationError(
        `Cannot open “${savedGraph.name}”: edge ${savedEdge.id} references missing input ${targetNode.data.spec.operator_id}.${savedEdge.to_port}`,
      );
    }

    let sourceHandle: string;
    let targetHandle: string;
    let color: string = tokens.colorMuted;
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
      const sourceShape = sourcePort
        ? (mapEdgeByTargetNode.has(sourceNode.id) ? "many" : sourcePort.shape)
        : "one";
      sourceHandle = sourcePort
        ? encodeHandleId(
            portMetaForPort(
              sourcePort,
              sourceShape,
              undefined,
              sourceNode.data.artifactTypeBindings,
            ),
          )
        : compatibilityHandleId("output", {
            portName: savedEdge.from_port,
          });
      targetHandle = targetPort
        ? encodeHandleId(
            portMetaForPort(
              targetPort,
              targetPort.shape,
              savedEdge.to_plug ?? undefined,
              targetNode.data.artifactTypeBindings,
            ),
          )
        : compatibilityHandleId("input", {
            portName: savedEdge.to_port,
            ...(savedEdge.to_plug ? { plugId: savedEdge.to_plug } : {}),
          });
      if (sourcePort) {
        const sourceArtifactType = resolvedPortArtifactType(
          sourcePort,
          sourceNode.data.artifactTypeBindings,
        );
        color = sourceArtifactType
          ? artifactTypeColor(sourceArtifactType.id, tokens.colorMuted)
          : tokens.colorMuted;
      }
    } else {
      if (!sourcePort || !targetPort) {
        throw new SavedGraphHydrationError(
          `Cannot open “${savedGraph.name}”: edge ${savedEdge.id} has unavailable ports`,
        );
      }
      if (portHasInstancePlugs(targetPort)) {
        const targetPlug = targetNode.data.inputPlugs.find(
          (plug) =>
            plug.id === savedEdge.to_plug && plug.portName === targetPort.name,
        );
        if (!targetPlug) {
          throw new SavedGraphHydrationError(
            `Cannot open “${savedGraph.name}”: edge ${savedEdge.id} references missing input plug ${savedEdge.to_plug ?? "null"}`,
          );
        }
        const targetPlugKey = `${targetNode.id}::${targetPlug.id}`;
        if (occupiedTargetPlugIds.has(targetPlugKey)) {
          throw new SavedGraphHydrationError(
            `Cannot open “${savedGraph.name}”: multiple edges target input plug ${targetPlug.id} on node ${targetNode.id}`,
          );
        }
        occupiedTargetPlugIds.add(targetPlugKey);
      } else if (
        savedEdge.to_plug !== null &&
        savedEdge.to_plug !== undefined
      ) {
        throw new SavedGraphHydrationError(
          `Cannot open “${savedGraph.name}”: edge ${savedEdge.id} assigns input plug ${savedEdge.to_plug} to non-instance input ${targetPort.name}`,
        );
      }

      const sourceShape = mapEdgeByTargetNode.has(sourceNode.id)
        ? "many"
        : sourcePort.shape;
      const otherMapEdge = mapEdgeByTargetNode.get(targetNode.id);
      const targetShape =
        otherMapEdge !== savedEdge && otherMapEdge?.to_port === targetPort.name
          ? "many"
          : targetPort.shape;
      let expectedCollectionMode: SavedGraphEdge["collection_mode"] | null =
        null;
      if (acceptedPortShapes(targetPort).includes(sourceShape)) {
        expectedCollectionMode = "direct";
      } else if (!portHasInstancePlugs(targetPort)) {
        if (sourceShape === targetShape) {
          expectedCollectionMode = "direct";
        } else if (sourceShape === "many" && targetShape === "one") {
          expectedCollectionMode = "map";
        }
      }
      if (savedEdge.collection_mode !== expectedCollectionMode) {
        const expectedMode = expectedCollectionMode
          ? `'${expectedCollectionMode}'`
          : "no supported collection mode";
        throw new SavedGraphHydrationError(
          `Cannot open “${savedGraph.name}”: edge ${savedEdge.id} uses collection mode '${savedEdge.collection_mode}' for source shape '${sourceShape}' and target shape '${targetShape}', expected ${expectedMode}`,
        );
      }

      if (!connectionRouteIsValid(savedEdge, sourceNode, targetNode, registry)) {
        throw new SavedGraphHydrationError(
          `Cannot open “${savedGraph.name}”: edge ${savedEdge.id} has an incompatible artifact route`,
        );
      }

      const sourceArtifactType = resolvedPortArtifactType(
        sourcePort,
        sourceNode.data.artifactTypeBindings,
      );
      color = sourceArtifactType
        ? artifactTypeColor(sourceArtifactType.id, tokens.colorAccent)
        : tokens.colorAccent;
      sourceHandle = encodeHandleId(
        portMetaForPort(
          sourcePort,
          sourceShape,
          undefined,
          sourceNode.data.artifactTypeBindings,
        ),
      );
      targetHandle = encodeHandleId(
        portMetaForPort(
          targetPort,
          targetPort.shape,
          savedEdge.to_plug ?? undefined,
          targetNode.data.artifactTypeBindings,
        ),
      );
    }

    const enabled = savedEdge.enabled ?? true;
    return {
      id: savedEdge.id,
      source: savedEdge.from_node,
      sourceHandle,
      target: savedEdge.to_node,
      targetHandle,
      type: WORKFLOW_EDGE_TYPE,
      animated: false,
      data: {
        enabled,
        collectionMode: savedEdge.collection_mode,
        sourcePortName: savedEdge.from_port,
        targetPortName: savedEdge.to_port,
        targetPlugId: savedEdge.to_plug ?? null,
        persistedEdge: structuredClone(savedEdge),
        ...(compatibilityIssues.length ? { compatibilityIssues } : {}),
        ...(savedEdge.projection
          ? { projection: { path: [...savedEdge.projection.path] } }
          : {}),
        conversionPath: [...(savedEdge.conversion_path ?? [])].map((conversion) => ({
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
      style: {
        stroke: color,
        strokeWidth: 2,
        ...(compatibilityIssues.length
          ? { strokeDasharray: "7 5", opacity: 0.68 }
          : {}),
      },
    } satisfies WorkflowEdge;
  });

  return { nodes: withMaterializedNodeRuns(nodes, nodeRuns), edges };
}

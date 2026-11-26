import type {
  ArtifactConversionSpec,
  ArtifactTypeSpec,
  SavedGraphOrigin,
} from "@/lib/api";

import {
  connectionRoutesForPorts,
  connectionRouteSelection,
  type ConnectionRoute,
} from "./connection-routes";
import {
  formatArtifactTypeLabel,
  type ArtifactTypeCatalog,
} from "../artifacts/artifact-type-label";
import {
  collectionModesForShapes,
  effectivePortShape,
  portHasInstancePlugs,
  portMetaForPort,
  type GraphConnection,
  type PortMeta,
  type WorkflowEdge,
  type WorkflowEdgeRouteOption,
  type WorkflowNodeData,
  workflowNodeIsSupported,
} from "./types";

export interface GraphAuthoringNode {
  id: string;
  data: WorkflowNodeData;
}

export interface GraphAuthoringConversion {
  key: {
    id: string;
    version: number;
  };
  title: string;
}

type WorkflowPort = WorkflowNodeData["spec"]["inputs"][number];
type CollectionMode = NonNullable<WorkflowEdge["data"]>["collectionMode"];

export function connectionRouteTitle(
  route: ConnectionRoute,
  artifactTypes: ArtifactTypeCatalog,
): string {
  const conversionTitle = route.conversionPath
    .map((conversion) => conversion.title)
    .join(" → ");
  let title = "Whole output";
  if (route.kind === "projection") title = route.projection.title;
  if (route.kind === "conversion") title = conversionTitle;
  if (route.kind === "projection-conversion") {
    title = `${route.projection.title} → ${conversionTitle}`;
  }
  const binding = route.artifactTypeBinding;
  return binding
    ? `${title} · ${formatArtifactTypeLabel(binding.artifactType, artifactTypes)}`
    : title;
}

export function workflowEdgeRouteOption(
  route: ConnectionRoute,
): WorkflowEdgeRouteOption {
  const selection = connectionRouteSelection(route);
  return {
    ...selection,
    projectionTitle:
      route.kind === "projection" || route.kind === "projection-conversion"
        ? route.projection.title
        : undefined,
    conversionTitles: route.conversionPath.map(
      (conversion) => conversion.title,
    ),
  };
}

export function mappedInputPortsForNode(
  nodeId: string,
  edges: readonly WorkflowEdge[],
  includeDisabledEdges = false,
  origins: readonly SavedGraphOrigin[] = [],
): string[] {
  return [
    ...edges.flatMap((edge) => {
      if (
        edge.target !== nodeId ||
        (!includeDisabledEdges && edge.data?.enabled === false) ||
        edge.data?.collectionMode !== "map"
      ) {
        return [];
      }
      return edge.targetPort ? [edge.targetPort] : [];
    }),
    ...origins
      .filter(
        (origin) =>
          origin.to_node === nodeId && origin.collection_mode === "map",
      )
      .map((origin) => origin.to_port),
  ];
}

function effectiveShapeForPort(
  node: GraphAuthoringNode,
  port: WorkflowPort,
  edges: readonly WorkflowEdge[],
  includeDisabledEdges = false,
  origins: readonly SavedGraphOrigin[] = [],
): WorkflowPort["shape"] {
  return effectivePortShape(
    {
      ...node.data,
      mappedInputPorts: mappedInputPortsForNode(
        node.id,
        edges,
        includeDisabledEdges,
        origins,
      ),
    },
    port,
  );
}

/** Resolve the two structured port descriptors for a connection between workflow nodes. */
export function resolveConnectionPortMeta(
  connection: GraphConnection,
  nodes: readonly GraphAuthoringNode[],
  edges: readonly WorkflowEdge[],
  origins: readonly SavedGraphOrigin[] = [],
): { source: PortMeta; target: PortMeta } | null {
  const sourceNode = nodes.find((node) => node.id === connection.source);
  const targetNode = nodes.find((node) => node.id === connection.target);
  if (
    !sourceNode ||
    !targetNode ||
    !workflowNodeIsSupported(sourceNode.data) ||
    !workflowNodeIsSupported(targetNode.data)
  ) {
    return null;
  }
  const sourcePort = sourceNode.data.spec.outputs.find(
    (port) => port.name === connection.sourcePort,
  );
  const targetPort = targetNode.data.spec.inputs.find(
    (port) => port.name === connection.targetPort,
  );
  if (!sourcePort || !targetPort) return null;

  return {
    source: portMetaForPort(
      sourcePort,
      effectiveShapeForPort(sourceNode, sourcePort, edges, true, origins),
      undefined,
      sourceNode.data.artifactTypeBindings,
    ),
    target: portMetaForPort(
      targetPort,
      effectiveShapeForPort(targetNode, targetPort, edges, true, origins),
      connection.targetPlug ?? undefined,
      targetNode.data.artifactTypeBindings,
    ),
  };
}

export function collectionModeForConnection(
  connection: GraphConnection,
  nodes: readonly GraphAuthoringNode[],
  edges: readonly WorkflowEdge[],
  origins: readonly SavedGraphOrigin[] = [],
): CollectionMode | null {
  return (
    collectionModesForConnection(connection, nodes, edges, origins)[0] ?? null
  );
}

export function collectionModesForConnection(
  connection: GraphConnection,
  nodes: readonly GraphAuthoringNode[],
  edges: readonly WorkflowEdge[],
  origins: readonly SavedGraphOrigin[] = [],
): CollectionMode[] {
  const sourceNode = nodes.find((node) => node.id === connection.source);
  const targetNode = nodes.find((node) => node.id === connection.target);
  if (
    !sourceNode ||
    !targetNode ||
    !workflowNodeIsSupported(sourceNode.data) ||
    !workflowNodeIsSupported(targetNode.data)
  ) {
    return [];
  }
  const sourcePort = sourceNode.data.spec.outputs.find(
    (port) => port.name === connection.sourcePort,
  );
  const targetPort = targetNode.data.spec.inputs.find(
    (port) => port.name === connection.targetPort,
  );
  if (!sourcePort || !targetPort) return [];

  const sourceShape = effectiveShapeForPort(
    sourceNode,
    sourcePort,
    edges,
    true,
    origins,
  );
  const targetShape = effectiveShapeForPort(
    targetNode,
    targetPort,
    edges,
    true,
    origins,
  );
  return collectionModesForShapes(sourceShape, targetPort, targetShape);
}

export function isConnectionAccepted(
  connection: GraphConnection,
  nodes: readonly GraphAuthoringNode[],
  edges: readonly WorkflowEdge[],
  artifactTypes: readonly ArtifactTypeSpec[],
  artifactConversions: readonly ArtifactConversionSpec[],
  existingEdgeId: string | null = null,
  origins: readonly SavedGraphOrigin[] = [],
): boolean {
  const collectionMode = collectionModeForConnection(
    connection,
    nodes,
    edges,
    origins,
  );
  if (!collectionMode) return false;

  const endpoints = resolveConnectionPortMeta(
    connection,
    nodes,
    edges,
    origins,
  );
  if (
    !endpoints ||
    !connectionRoutesForPorts(
      endpoints.source,
      endpoints.target,
      artifactTypes,
      artifactConversions,
    ).length
  ) {
    return false;
  }

  const targetNode = nodes.find((node) => node.id === connection.target);
  const input = targetNode?.data.spec.inputs.find(
    (port) => port.name === connection.targetPort,
  );
  if (!targetNode || !input) return false;

  const targetPlug = connection.targetPlug ?? null;
  if (portHasInstancePlugs(input)) {
    if (
      !targetPlug ||
      !targetNode.data.inputPlugs.some(
        (plug) => plug.id === targetPlug && plug.portName === input.name,
      )
    ) {
      return false;
    }
  } else if (targetPlug) {
    return false;
  }

  if (
    collectionMode === "map" &&
    edges.some(
      (edge) =>
        edge.id !== existingEdgeId &&
        edge.target === connection.target &&
        edge.targetPort === connection.targetPort &&
        edge.data?.collectionMode === "map",
    )
  ) {
    return false;
  }

  const pendingNodeIds = [connection.target];
  const visitedNodeIds = new Set<string>();
  while (pendingNodeIds.length) {
    const nodeId = pendingNodeIds.pop();
    if (!nodeId || visitedNodeIds.has(nodeId)) continue;
    if (nodeId === connection.source) return false;
    visitedNodeIds.add(nodeId);
    for (const edge of edges) {
      if (edge.id !== existingEdgeId && edge.source === nodeId) {
        pendingNodeIds.push(edge.target);
      }
    }
  }

  if (portHasInstancePlugs(input)) {
    return !edges.some(
      (edge) =>
        edge.id !== existingEdgeId &&
        edge.target === connection.target &&
        (edge.targetPlug ?? null) === targetPlug,
    );
  }
  if (input.variadic) return true;
  if (
    edges.some(
      (edge) =>
        edge.id !== existingEdgeId &&
        edge.target === connection.target &&
        edge.targetPort === connection.targetPort,
    )
  ) {
    return false;
  }
  if (input.exclusive_group) {
    const siblingPorts = new Set(
      targetNode.data.spec.inputs
        .filter(
          (port) =>
            port.name !== input.name &&
            port.exclusive_group === input.exclusive_group,
        )
        .map((port) => port.name),
    );
    const siblingConnectedByEdge = edges.some(
      (edge) =>
        edge.id !== existingEdgeId &&
        edge.data?.enabled !== false &&
        edge.target === connection.target &&
        siblingPorts.has(edge.targetPort),
    );
    const siblingConnectedByOrigin = origins.some(
      (origin) =>
        origin.to_node === connection.target &&
        siblingPorts.has(origin.to_port),
    );
    if (siblingConnectedByEdge || siblingConnectedByOrigin) {
      return false;
    }
  }
  return true;
}

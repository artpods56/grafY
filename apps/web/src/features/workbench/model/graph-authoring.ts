import type {
  ArtifactConversionSpec,
  ArtifactTypeKey,
  ArtifactTypeSpec,
} from "@/lib/api";

import {
  connectionRoutesFor,
  connectionRouteSelection,
  decodeHandleId,
  decodedHandleArtifactType,
  type ConnectionRoute,
} from "../canvas/handles";
import {
  collectContributionLabel,
  inputPlugsForPort,
  type WorkflowInputPlugBinding,
} from "../canvas/input-plugs";
import {
  acceptedPortShapes,
  effectivePortShape,
  portHasInstancePlugs,
  type WorkflowEdge,
  type WorkflowEdgeRouteOption,
  type WorkflowNodeData,
  workflowNodeIsSupported,
} from "../canvas/types";

export interface GraphAuthoringNode {
  id: string;
  data: WorkflowNodeData;
}

export interface GraphAuthoringConnection {
  source: string;
  sourceHandle: string | null;
  target: string;
  targetHandle: string | null;
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

export function connectionRouteTitle(route: ConnectionRoute): string {
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
    ? `${title} · ${binding.artifactType.id}@${binding.artifactType.schema_version}`
    : title;
}

export function connectionRouteDescription(
  sourcePortName: string,
  route: ConnectionRoute,
): string {
  const conversionDescription = route.conversionPath
    .map(
      (conversion) =>
        `${conversion.title} · ${conversion.key.id}@${conversion.key.version}`,
    )
    .join(" → ");
  if (route.kind === "projection") {
    return `${sourcePortName}.${route.projection.path.join(".")}`;
  }
  if (route.kind === "conversion") {
    return `${sourcePortName} → ${conversionDescription}`;
  }
  if (route.kind === "projection-conversion") {
    return `${sourcePortName}.${route.projection.path.join(".")} → ${conversionDescription}`;
  }
  return sourcePortName;
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

export function mappedInputPortForNode(
  nodeId: string,
  edges: readonly WorkflowEdge[],
  includeDisabledEdges = false,
): string | null {
  const edge = edges.find(
    (candidate) =>
      candidate.target === nodeId &&
      (includeDisabledEdges || candidate.data?.enabled !== false) &&
      candidate.data?.collectionMode === "map",
  );
  return decodeHandleId(edge?.targetHandle)?.portName ?? null;
}

function effectiveShapeForPort(
  node: GraphAuthoringNode,
  port: WorkflowPort,
  edges: readonly WorkflowEdge[],
  includeDisabledEdges = false,
): WorkflowPort["shape"] {
  return effectivePortShape(
    {
      ...node.data,
      mappedInputPort: mappedInputPortForNode(
        node.id,
        edges,
        includeDisabledEdges,
      ),
    },
    port,
  );
}

export function collectionModeForConnection(
  connection: GraphAuthoringConnection,
  nodes: readonly GraphAuthoringNode[],
  edges: readonly WorkflowEdge[],
): CollectionMode | null {
  const sourceHandle = decodeHandleId(connection.sourceHandle);
  const targetHandle = decodeHandleId(connection.targetHandle);
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
  const sourcePort = sourceNode?.data.spec.outputs.find(
    (port) => port.name === sourceHandle?.portName,
  );
  const targetPort = targetNode?.data.spec.inputs.find(
    (port) => port.name === targetHandle?.portName,
  );
  if (!sourcePort || !targetPort) return null;

  const sourceShape = effectiveShapeForPort(
    sourceNode,
    sourcePort,
    edges,
    true,
  );
  if (acceptedPortShapes(targetPort).includes(sourceShape)) return "direct";
  if (portHasInstancePlugs(targetPort)) return null;

  const targetShape = effectiveShapeForPort(
    targetNode,
    targetPort,
    edges,
    true,
  );
  if (sourceShape === targetShape) return "direct";
  if (sourceShape === "many" && targetShape === "one") return "map";
  return null;
}

export function isConnectionAccepted(
  connection: GraphAuthoringConnection,
  nodes: readonly GraphAuthoringNode[],
  edges: readonly WorkflowEdge[],
  artifactTypes: readonly ArtifactTypeSpec[],
  artifactConversions: readonly ArtifactConversionSpec[],
  existingEdgeId: string | null = null,
): boolean {
  const collectionMode = collectionModeForConnection(connection, nodes, edges);
  if (
    !collectionMode ||
    !connectionRoutesFor(connection, artifactTypes, artifactConversions).length
  ) {
    return false;
  }

  const target = decodeHandleId(connection.targetHandle);
  const targetNode = nodes.find((node) => node.id === connection.target);
  const input = targetNode?.data.spec.inputs.find(
    (port) => port.name === target?.portName,
  );
  if (!target || !targetNode || !input) return false;

  if (portHasInstancePlugs(input)) {
    if (
      !target.plugId ||
      !targetNode.data.inputPlugs.some(
        (plug) => plug.id === target.plugId && plug.portName === input.name,
      )
    ) {
      return false;
    }
  } else if (target.plugId) {
    return false;
  }

  if (
    collectionMode === "map" &&
    edges.some(
      (edge) =>
        edge.target === connection.target &&
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
        decodeHandleId(edge.targetHandle)?.plugId === target.plugId,
    );
  }
  if (input.variadic) return true;
  return !edges.some(
    (edge) =>
      edge.id !== existingEdgeId &&
      edge.target === connection.target &&
      decodeHandleId(edge.targetHandle)?.portName === target.portName,
  );
}

function projectionTitleForEdge(
  edge: WorkflowEdge,
  sourceHandleArtifactType: ArtifactTypeKey | null,
  artifactTypes: readonly ArtifactTypeSpec[],
): string | undefined {
  const path = edge.data?.projection?.path;
  if (!path?.length) return undefined;
  if (!sourceHandleArtifactType) return path.join(".");
  const sourceArtifact = artifactTypes.find(
    (artifact) =>
      artifact.key.id === sourceHandleArtifactType.id &&
      artifact.key.schema_version === sourceHandleArtifactType.schema_version,
  );
  return (
    sourceArtifact?.field_projections.find(
      (projection) =>
        projection.path.length === path.length &&
        projection.path.every((segment, index) => segment === path[index]),
    )?.title ?? path.join(".")
  );
}

export function inputPlugBindingsForNode(
  node: GraphAuthoringNode,
  nodes: readonly GraphAuthoringNode[],
  edges: readonly WorkflowEdge[],
  artifactConversions: readonly GraphAuthoringConversion[],
  artifactTypes: readonly ArtifactTypeSpec[] = [],
): Readonly<Record<string, WorkflowInputPlugBinding>> {
  if (!workflowNodeIsSupported(node.data)) return {};
  const bindings: Record<string, WorkflowInputPlugBinding> = {};
  for (const port of node.data.spec.inputs.filter(portHasInstancePlugs)) {
    const portPlugs = inputPlugsForPort(node.data.inputPlugs, port.name);
    portPlugs.forEach((plug, inputIndex) => {
      const edge = edges.find(
        (candidate) =>
          candidate.data?.enabled !== false &&
          candidate.target === node.id &&
          decodeHandleId(candidate.targetHandle)?.plugId === plug.id,
      );
      if (!edge) return;

      const sourceHandle = decodeHandleId(edge.sourceHandle);
      const sourceNode = nodes.find(
        (candidate) => candidate.id === edge.source,
      );
      if (sourceNode && !workflowNodeIsSupported(sourceNode.data)) return;
      const sourcePort = sourceNode?.data.spec.outputs.find(
        (candidate) => candidate.name === sourceHandle?.portName,
      );
      if (!sourceHandle || !sourceNode || !sourcePort) return;

      const projectionTitle = projectionTitleForEdge(
        edge,
        decodedHandleArtifactType(sourceHandle),
        artifactTypes,
      );
      const conversionLabels = (edge.data?.conversionPath ?? []).map(
        (requestedConversion) =>
          artifactConversions.find(
            (conversion) =>
              conversion.key.id === requestedConversion.id &&
              conversion.key.version === requestedConversion.version,
          )?.title ??
          `${requestedConversion.id}@${requestedConversion.version}`,
      );
      const feedLabel = [projectionTitle, ...conversionLabels]
        .filter((label): label is string => Boolean(label))
        .join(" → ");
      const contributionLabel = collectContributionLabel(
        node.data.run,
        inputIndex,
      );
      bindings[plug.id] = {
        sourceLabel: `${sourceNode.data.spec.title} · ${sourcePort.title ?? sourcePort.name}`,
        sourceShape: effectiveShapeForPort(sourceNode, sourcePort, edges),
        ...(feedLabel ? { conversionLabel: feedLabel } : {}),
        ...(contributionLabel ? { contributionLabel } : {}),
      };
    });
  }
  return bindings;
}

export function nodeAndDescendantIds(
  nodeId: string,
  edges: readonly WorkflowEdge[],
): Set<string> {
  const descendantIds = new Set([nodeId]);
  const pendingNodeIds = [nodeId];

  while (pendingNodeIds.length) {
    const sourceNodeId = pendingNodeIds.shift();
    if (sourceNodeId === undefined) continue;

    for (const edge of edges) {
      if (
        edge.data?.enabled === false ||
        edge.source !== sourceNodeId ||
        descendantIds.has(edge.target)
      ) {
        continue;
      }
      descendantIds.add(edge.target);
      pendingNodeIds.push(edge.target);
    }
  }

  return descendantIds;
}

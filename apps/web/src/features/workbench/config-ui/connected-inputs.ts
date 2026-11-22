import type {
  ArtifactConversionSpec,
  ArtifactTypeSpec,
  NodeSpec,
  SavedGraphEdge,
  SavedGraphNode,
  SavedGraphOrigin,
} from "@/lib/api";

import {
  cardArtifactRefs,
  type ArtifactCardValue,
} from "../artifacts/artifact-card";
import { ARTIFACT_ORIGIN_EDGE_TYPE } from "../artifacts/artifact-origin-edge";
import {
  artifactTypeKey,
  type ArtifactTypeIdentity,
} from "../artifacts/artifact-type-key";
import {
  ARTIFACT_VIEWER_NODE_TYPE,
  type CanvasEdge,
  type CanvasNode,
} from "../artifacts/artifact-viewer";
import type {
  ConnectedInputPortInfo,
  ConnectedInputPortMap,
} from "./config-schema";
import {
  decodeHandleId,
  decodedHandleArtifactType,
} from "../authoring/handles";
import {
  WORKFLOW_EDGE_TYPE,
  WORKFLOW_NODE_TYPE,
  resolvedPortArtifactType,
  type WorkflowEdge,
  type WorkflowEdgeConversionPath,
} from "../authoring/types";

export type {
  ConnectedInputPortInfo,
  ConnectedInputPortMap,
} from "./config-schema";

interface ConnectedInputPortsOptions {
  nodeId: string;
  spec: Pick<NodeSpec, "inputs">;
  edges: readonly CanvasEdge[];
  nodes: readonly CanvasNode[];
  origins?: readonly SavedGraphOrigin[];
  conversions?: readonly ArtifactConversionSpec[];
  artifactTypes?: readonly ArtifactTypeSpec[];
}

function isWorkflowEdge(edge: CanvasEdge): edge is WorkflowEdge {
  return (
    edge.type === WORKFLOW_EDGE_TYPE ||
    (edge.type === undefined &&
      (!edge.data || typeof edge.data.enabled === "boolean"))
  );
}

function conversionTarget(
  path:
    WorkflowEdgeConversionPath | SavedGraphEdge["conversion_path"] | undefined,
  conversions: readonly ArtifactConversionSpec[],
): ArtifactTypeIdentity | undefined {
  const last = path?.at(-1);
  if (!last) return undefined;
  return conversions.find(
    ({ key }) => key.id === last.id && key.version === last.version,
  )?.target_artifact_type;
}

function refArtifactType(value: ArtifactCardValue): ArtifactTypeIdentity {
  return { id: value.artifact_type, schema_version: value.schema_version };
}

function sourceArtifactType(
  edge: WorkflowEdge,
  sourceNode: CanvasNode | undefined,
): ArtifactTypeIdentity | null {
  const handle = decodeHandleId(edge.sourceHandle);
  const portName = handle?.portName ?? edge.data?.sourcePortName;
  if (sourceNode?.type === WORKFLOW_NODE_TYPE) {
    const port = sourceNode.data.spec.outputs.find(
      ({ name }) => name === portName,
    );
    if (port) {
      const type = resolvedPortArtifactType(
        port,
        sourceNode.data.artifactTypeBindings,
      );
      if (type) return type;
    }
  }
  return handle ? decodedHandleArtifactType(handle) : null;
}

function deliveredArtifactType(
  edge: WorkflowEdge,
  sourceNode: CanvasNode | undefined,
  conversions: readonly ArtifactConversionSpec[],
  artifactTypes: readonly ArtifactTypeSpec[],
): ArtifactTypeIdentity | null {
  const converted = conversionTarget(edge.data?.conversionPath, conversions);
  if (converted) return converted;
  return projectedArtifactType(
    sourceArtifactType(edge, sourceNode),
    edge.data?.projection?.path,
    artifactTypes,
  );
}

/** The field a projection reads out of `type`, or `type` when there is none. */
function projectedArtifactType(
  type: ArtifactTypeIdentity | null,
  path: readonly string[] | undefined,
  artifactTypes: readonly ArtifactTypeSpec[],
): ArtifactTypeIdentity | null {
  if (!type || !path) return type;

  const sourceSpec = artifactTypes.find(
    ({ key }) => artifactTypeKey(key) === artifactTypeKey(type),
  );
  const projection = sourceSpec?.field_projections.find(
    (candidate) =>
      candidate.path.length === path.length &&
      candidate.path.every((segment, index) => segment === path[index]),
  );
  return projection?.target_artifact_type ?? type;
}

/** Report active inputs and the first known delivered type for each port. */
export function connectedInputPortsForNode({
  nodeId,
  spec,
  edges,
  nodes,
  origins,
  conversions = [],
  artifactTypes = [],
}: ConnectedInputPortsOptions): ConnectedInputPortMap {
  const inputs = new Map<string, ConnectedInputPortInfo>(
    spec.inputs.map(({ name }) => [
      name,
      { connected: false, artifactTypeKey: null },
    ]),
  );
  const nodesById = new Map(nodes.map((node) => [node.id, node]));

  function connect(port: string, type: ArtifactTypeIdentity | null) {
    const previous = inputs.get(port);
    if (!previous || previous.artifactTypeKey !== null) return;
    inputs.set(port, {
      connected: true,
      artifactTypeKey: type ? artifactTypeKey(type) : null,
    });
  }

  for (const edge of edges) {
    if (edge.target !== nodeId || edge.data?.enabled === false) continue;
    const handle = decodeHandleId(edge.targetHandle);
    if (handle?.direction !== "input" || !inputs.has(handle.portName)) continue;
    const source = nodesById.get(edge.source);
    if (edge.type === ARTIFACT_ORIGIN_EDGE_TYPE) {
      if (origins !== undefined) continue;
      const ref =
        source?.type === ARTIFACT_VIEWER_NODE_TYPE
          ? cardArtifactRefs(source.data.artifactRef)[0]
          : undefined;
      connect(handle.portName, ref ? refArtifactType(ref) : null);
    } else if (isWorkflowEdge(edge)) {
      connect(
        handle.portName,
        deliveredArtifactType(edge, source, conversions, artifactTypes),
      );
    }
  }

  for (const origin of origins ?? []) {
    if (origin.to_node !== nodeId) continue;
    const type =
      conversionTarget(origin.conversion_path, conversions) ??
      refArtifactType(origin.value);
    connect(origin.to_port, type);
  }

  return Object.fromEntries(inputs);
}

interface DocumentConnectedInputPortsOptions {
  nodeId: string;
  spec: Pick<NodeSpec, "inputs">;
  edges: readonly SavedGraphEdge[];
  origins: readonly SavedGraphOrigin[];
  /** Spec and bindings of each source node, by id, to type what it sends. */
  sources: ReadonlyMap<
    string,
    {
      node: Pick<SavedGraphNode, "artifact_type_bindings">;
      spec: Pick<NodeSpec, "outputs"> | undefined;
    }
  >;
  conversions?: readonly ArtifactConversionSpec[];
  artifactTypes?: readonly ArtifactTypeSpec[];
}

/**
 * {@link connectedInputPortsForNode} read off an authored graph document
 * instead of canvas nodes and edges: the cell canvas paints from the document,
 * so it has no React Flow shapes to hand over. Same answer, same rules — an
 * enabled edge or an origin connects a port, and the first typed delivery
 * names what the port receives.
 */
export function connectedInputPortsForDocumentNode({
  nodeId,
  spec,
  edges,
  origins,
  sources,
  conversions = [],
  artifactTypes = [],
}: DocumentConnectedInputPortsOptions): ConnectedInputPortMap {
  const inputs = new Map<string, ConnectedInputPortInfo>(
    spec.inputs.map(({ name }) => [
      name,
      { connected: false, artifactTypeKey: null },
    ]),
  );

  function connect(port: string, type: ArtifactTypeIdentity | null) {
    const previous = inputs.get(port);
    if (!previous || previous.artifactTypeKey !== null) return;
    inputs.set(port, {
      connected: true,
      artifactTypeKey: type ? artifactTypeKey(type) : null,
    });
  }

  for (const edge of edges) {
    if (edge.to_node !== nodeId || edge.enabled === false) continue;
    const converted = conversionTarget(edge.conversion_path, conversions);
    if (converted) {
      connect(edge.to_port, converted);
      continue;
    }
    const source = sources.get(edge.from_node);
    const port = source?.spec?.outputs.find(
      ({ name }) => name === edge.from_port,
    );
    const variable = port?.artifact_type_variable;
    const bound = variable
      ? source?.node.artifact_type_bindings.find(
          (binding) => binding.variable === variable,
        )?.artifact_type
      : undefined;
    connect(
      edge.to_port,
      projectedArtifactType(
        bound ?? port?.artifact_type ?? null,
        edge.projection?.path,
        artifactTypes,
      ),
    );
  }

  for (const origin of origins) {
    if (origin.to_node !== nodeId) continue;
    connect(
      origin.to_port,
      conversionTarget(origin.conversion_path, conversions) ??
        refArtifactType(origin.value),
    );
  }

  return Object.fromEntries(inputs);
}

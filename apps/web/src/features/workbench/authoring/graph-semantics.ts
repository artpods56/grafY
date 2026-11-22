import type {
  EdgeCollectionMode,
  NodeRegistry,
  NodeSpec,
  Port,
  SavedGraphEdge,
  SavedGraphNode,
} from "@/lib/api";

import { artifactTypeKey } from "../artifacts/artifact-type-key";
import {
  solveCollectionModeRepairs,
  type CollectionStepResolver,
} from "./edge-collection-modes";
import type {
  AuthoredGraphDocument,
  AuthoredGraphEdge,
  AuthoredGraphNode,
  AuthoredGraphOrigin,
} from "./graph-document";
import {
  collectionModesForShapes,
  declaredArtifactTypeVariables,
  defaultNodeConfig,
  originCollectionModes,
  portHasInstancePlugs,
  resolveInstancePortShapes,
  type WorkflowArtifactTypeBindingInput,
  type WorkflowArtifactTypeBindings,
  type WorkflowCompatibilityEndpoint,
  type WorkflowNodeCompatibility,
} from "./types";

/**
 * The resolved semantic interface of one node in a graph.
 *
 * Computed once from `(AuthoredGraphDocument, NodeRegistry)` so authoring,
 * hydration, execution planning, and Cell Canvas rendering all read the exact
 * same resolved port shapes, compatibility issues, and mappedness instead of
 * each re-deriving them independently.
 */
export interface ResolvedNodeSemantics {
  readonly nodeId: string;
  readonly node: AuthoredGraphNode;
  /** Exact-version catalog spec with `shape_field` overrides applied, or null if unavailable. */
  readonly spec: NodeSpec | null;
  /** Spec for display when rendering a card whose exact version moved (`spec` or operator-id fallback). */
  readonly displaySpec: NodeSpec | null;
  readonly compatibility: WorkflowNodeCompatibility;
  readonly artifactTypeBindings: WorkflowArtifactTypeBindings;
  /** Input ports currently driven in `map` mode by origins or enabled edges. */
  readonly mappedInputPorts: readonly string[];
  /** Input ports driven in `map` mode by origins or any edge (including disabled edges). */
  readonly allMappedInputPorts: readonly string[];
  /** True when at least one active origin or enabled edge drives this step per item. */
  readonly runsPerItem: boolean;
  /** True when any origin or edge (including disabled edges) marks this step as mapped. */
  readonly outputsWidenedForAuthoring: boolean;
  /** Rendered output port shapes (`"many"` when `runsPerItem`, else declared/resolved `port.shape`). */
  readonly effectiveOutputShapes: ReadonlyMap<string, Port["shape"]>;
  /** Authoring/hydration output port shapes (`"many"` when `outputsWidenedForAuthoring`). */
  readonly authoringOutputShapes: ReadonlyMap<string, Port["shape"]>;
}

export interface ResolvedEdgeSemantics {
  readonly edgeId: string;
  readonly edge: AuthoredGraphEdge;
  /** Stored mode after graph-level collection-mode repairs are applied. */
  readonly collectionMode: EdgeCollectionMode;
  readonly sourcePort: Port | null;
  readonly targetPort: Port | null;
  readonly sourceShape: Port["shape"];
  readonly targetShape: Port["shape"];
  readonly allowedCollectionModes: readonly EdgeCollectionMode[];
}

export interface ResolvedOriginSemantics {
  readonly originId: string;
  readonly origin: AuthoredGraphOrigin;
  /** Stored mode after graph-level collection-mode repairs are applied. */
  readonly collectionMode: EdgeCollectionMode;
  readonly targetPort: Port | null;
  readonly valueShape: Port["shape"];
  readonly allowedCollectionModes: readonly EdgeCollectionMode[];
}

export interface ResolvedGraphSemantics {
  readonly nodes: ReadonlyMap<string, ResolvedNodeSemantics>;
  readonly edges: ReadonlyMap<string, ResolvedEdgeSemantics>;
  readonly origins: ReadonlyMap<string, ResolvedOriginSemantics>;
  readonly edgeModeRepairs: ReadonlyMap<string, EdgeCollectionMode>;
  readonly originModeRepairs: ReadonlyMap<string, EdgeCollectionMode>;
  /** Every node id with at least one active map driver (origin or enabled edge). */
  readonly mappedNodeIds: ReadonlySet<string>;
  /** Every node id with any map driver (including disabled edges). */
  readonly authoringMappedNodeIds: ReadonlySet<string>;
}

/** Stable identity for an operator version in the registry. */
export function operatorSpecKey(
  operatorId: string,
  operatorVersion: number,
): string {
  return `${operatorId}@${operatorVersion}`;
}

/** Resolve instance-specific `shape_field` overrides on a node's catalog spec. */
export function resolveSpecForNode(
  node: Pick<AuthoredGraphNode, "config">,
  spec: NodeSpec,
): NodeSpec {
  return resolveInstancePortShapes(spec, {
    ...defaultNodeConfig(spec),
    ...(node.config ?? {}),
  });
}

function compatibilityEndpoints(
  savedNode: Pick<SavedGraphNode, "id" | "input_plugs">,
  savedEdges: readonly Pick<
    SavedGraphEdge,
    "from_node" | "from_port" | "to_node" | "to_port" | "to_plug"
  >[],
): {
  inputs: WorkflowCompatibilityEndpoint[];
  outputs: WorkflowCompatibilityEndpoint[];
} {
  const inputs = new Map<string, WorkflowCompatibilityEndpoint>();
  const outputs = new Map<string, WorkflowCompatibilityEndpoint>();
  for (const plug of savedNode.input_plugs) {
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

/** What a call node's saved connections still name that its callee no longer declares. */
function staleCallPorts(
  document: Pick<AuthoredGraphDocument, "edges" | "origins">,
  node: Pick<AuthoredGraphNode, "id">,
  spec: NodeSpec,
): string[] {
  const inputs = new Set(spec.inputs.map((port) => port.name));
  const outputs = new Set(spec.outputs.map((port) => port.name));
  const issues: string[] = [];
  const note = (direction: "input" | "output", port: string) => {
    const message = `${direction === "input" ? "Input" : "Output"} “${port}” no longer exists on “${spec.title}”.`;
    if (!issues.includes(message)) issues.push(message);
  };
  for (const edge of document.edges) {
    if (edge.to_node === node.id && !inputs.has(edge.to_port)) {
      note("input", edge.to_port);
    }
    if (edge.from_node === node.id && !outputs.has(edge.from_port)) {
      note("output", edge.from_port);
    }
  }
  for (const origin of document.origins) {
    if (origin.to_node === node.id && !inputs.has(origin.to_port)) {
      note("input", origin.to_port);
    }
  }
  return issues;
}

function validateInputPlugs(
  node: AuthoredGraphNode,
  spec: NodeSpec,
): string | null {
  const plugIds = new Set<string>();
  for (const plug of node.input_plugs) {
    const port = spec.inputs.find((candidate) => candidate.name === plug.port);
    if (!port || !portHasInstancePlugs(port)) {
      return "A step has a slot the input does not allow.";
    }
    if (plugIds.has(plug.id)) {
      return "A step has two slots with the same identity.";
    }
    plugIds.add(plug.id);
  }
  return null;
}

function readArtifactTypeBindings(
  node: AuthoredGraphNode,
): WorkflowArtifactTypeBindings {
  const bindings: Record<
    string,
    WorkflowArtifactTypeBindingInput["artifact_type"]
  > = {};
  for (const binding of node.artifact_type_bindings) {
    bindings[binding.variable] = {
      id: binding.artifact_type.id,
      schema_version: binding.artifact_type.schema_version,
    };
  }
  return bindings;
}

function validateArtifactTypeBindings(
  node: AuthoredGraphNode,
  spec: NodeSpec,
  registryArtifactTypes: ReadonlySet<string>,
):
  | { readonly ok: true; readonly bindings: WorkflowArtifactTypeBindings }
  | { readonly ok: false; readonly issue: string } {
  const declaredVariables = new Set(declaredArtifactTypeVariables(spec));
  const bindings: Record<
    string,
    WorkflowArtifactTypeBindingInput["artifact_type"]
  > = {};
  for (const binding of node.artifact_type_bindings) {
    if (!declaredVariables.has(binding.variable)) {
      return { ok: false, issue: "A step’s type is not available." };
    }
    if (binding.variable in bindings) {
      return { ok: false, issue: "A step’s type is not available." };
    }
    const key = artifactTypeKey(binding.artifact_type);
    if (!registryArtifactTypes.has(key)) {
      return { ok: false, issue: "A step’s type is not available." };
    }
    bindings[binding.variable] = {
      id: binding.artifact_type.id,
      schema_version: binding.artifact_type.schema_version,
    };
  }
  return { ok: true, bindings };
}

function outputShapesMap(
  spec: NodeSpec | null,
  widened: boolean,
): ReadonlyMap<string, Port["shape"]> {
  const shapes = new Map<string, Port["shape"]>();
  if (!spec) return shapes;
  for (const port of spec.outputs) {
    shapes.set(
      port.name,
      port.kind === "service" ? port.shape : widened ? "many" : port.shape,
    );
  }
  return shapes;
}

function inputDriverKey(nodeId: string, portName: string): string {
  return `${nodeId}\u0000${portName}`;
}

interface DraftNodeResolution {
  readonly node: AuthoredGraphNode;
  readonly spec: NodeSpec | null;
  readonly displaySpec: NodeSpec | null;
  compatibility: WorkflowNodeCompatibility;
  readonly artifactTypeBindings: WorkflowArtifactTypeBindings;
}

/**
 * Resolve every node's effective spec, compatibility status, mapped inputs,
 * output shapes, and connection collection modes in one pass.
 */
export function resolveGraphSemantics(
  document: Pick<AuthoredGraphDocument, "nodes" | "edges" | "origins">,
  registry: NodeRegistry,
): ResolvedGraphSemantics {
  const specsByKey = new Map<string, NodeSpec>();
  const specsByOperatorId = new Map<string, NodeSpec>();
  for (const spec of registry.nodes) {
    specsByKey.set(
      operatorSpecKey(spec.operator_id, spec.operator_version),
      spec,
    );
    if (!specsByOperatorId.has(spec.operator_id)) {
      specsByOperatorId.set(spec.operator_id, spec);
    }
  }
  const registryArtifactTypes = new Set(
    registry.artifact_types.map((artifact) => artifactTypeKey(artifact.key)),
  );

  const drafts = new Map<string, DraftNodeResolution>();
  for (const node of document.nodes) {
    const identity = operatorSpecKey(node.operator_id, node.operator_version);
    const exactRaw = specsByKey.get(identity);
    const fallbackRaw = exactRaw ?? specsByOperatorId.get(node.operator_id);
    const resolvedExact = exactRaw ? resolveSpecForNode(node, exactRaw) : null;
    const displaySpec = fallbackRaw
      ? resolveSpecForNode(node, fallbackRaw)
      : null;

    let compatibility: WorkflowNodeCompatibility;
    let artifactTypeBindings: WorkflowArtifactTypeBindings;

    if (node.kind === "module") {
      compatibility = {
        status: "unsupported",
        issues: [
          `Operator ${identity} is a Module, a node type that is no longer supported. This saved node is preserved but cannot run.`,
        ],
        ...compatibilityEndpoints(node, document.edges),
        persistedNode: structuredClone(node),
      };
      artifactTypeBindings = readArtifactTypeBindings(node);
    } else if (!resolvedExact) {
      compatibility = {
        status: "unsupported",
        issues: [
          `Operator ${identity} is unavailable. This saved node is preserved but cannot run.`,
        ],
        ...compatibilityEndpoints(node, document.edges),
        persistedNode: structuredClone(node),
      };
      artifactTypeBindings = readArtifactTypeBindings(node);
    } else if (
      node.kind === "call" &&
      staleCallPorts(document, node, resolvedExact).length > 0
    ) {
      compatibility = {
        status: "invalid",
        issues: staleCallPorts(document, node, resolvedExact),
        ...compatibilityEndpoints(node, document.edges),
        persistedNode: structuredClone(node),
      };
      artifactTypeBindings = readArtifactTypeBindings(node);
    } else {
      const plugIssue = validateInputPlugs(node, resolvedExact);
      const bindingCheck = plugIssue
        ? null
        : validateArtifactTypeBindings(
            node,
            resolvedExact,
            registryArtifactTypes,
          );
      if (plugIssue) {
        compatibility = {
          status: "invalid",
          issues: [plugIssue],
          ...compatibilityEndpoints(node, document.edges),
          persistedNode: structuredClone(node),
        };
        artifactTypeBindings = readArtifactTypeBindings(node);
      } else if (bindingCheck && !bindingCheck.ok) {
        compatibility = {
          status: "invalid",
          issues: [bindingCheck.issue],
          ...compatibilityEndpoints(node, document.edges),
          persistedNode: structuredClone(node),
        };
        artifactTypeBindings = readArtifactTypeBindings(node);
      } else {
        compatibility = { status: "supported" };
        artifactTypeBindings = bindingCheck?.ok ? bindingCheck.bindings : {};
      }
    }

    drafts.set(node.id, {
      node,
      spec: resolvedExact,
      displaySpec,
      compatibility,
      artifactTypeBindings,
    });
  }

  for (const edge of document.edges) {
    const source = drafts.get(edge.from_node);
    const target = drafts.get(edge.to_node);
    if (!source || !target) continue;
    if (
      source.compatibility.status === "supported" &&
      source.spec &&
      !source.spec.outputs.some((port) => port.name === edge.from_port)
    ) {
      source.compatibility = {
        status: "invalid",
        issues: [
          "A saved connection points at an output this step no longer has.",
        ],
        ...compatibilityEndpoints(source.node, document.edges),
        persistedNode: structuredClone(source.node),
      };
    }
    if (
      target.compatibility.status === "supported" &&
      target.spec &&
      !target.spec.inputs.some((port) => port.name === edge.to_port)
    ) {
      target.compatibility = {
        status: "invalid",
        issues: [
          "A saved connection points at an input this step no longer has.",
        ],
        ...compatibilityEndpoints(target.node, document.edges),
        persistedNode: structuredClone(target.node),
      };
    }
  }

  const resolveStep: CollectionStepResolver = (nodeId) => {
    const draft = drafts.get(nodeId);
    if (!draft || draft.compatibility.status !== "supported" || !draft.spec) {
      return null;
    }
    return {
      inputs: draft.spec.inputs,
      outputs: draft.spec.outputs,
    };
  };

  const { edges: edgeModeRepairs, origins: originModeRepairs } =
    solveCollectionModeRepairs(document.edges, document.origins, resolveStep);

  const mappedPortsByNode = new Map<string, string[]>();
  const allMappedPortsByNode = new Map<string, string[]>();
  const mapDriversByInput = new Map<string, Set<string>>();
  const mappedNodeIds = new Set<string>();
  const authoringMappedNodeIds = new Set<string>();

  const recordMapDriver = (
    nodeId: string,
    portName: string,
    driverId: string,
    active: boolean,
  ) => {
    authoringMappedNodeIds.add(nodeId);
    const allPorts = allMappedPortsByNode.get(nodeId) ?? [];
    allPorts.push(portName);
    allMappedPortsByNode.set(nodeId, allPorts);

    const key = inputDriverKey(nodeId, portName);
    const inputDrivers = mapDriversByInput.get(key) ?? new Set<string>();
    inputDrivers.add(driverId);
    mapDriversByInput.set(key, inputDrivers);

    if (active) {
      mappedNodeIds.add(nodeId);
      const activePorts = mappedPortsByNode.get(nodeId) ?? [];
      activePorts.push(portName);
      mappedPortsByNode.set(nodeId, activePorts);
    }
  };

  for (const edge of document.edges) {
    const mode = edgeModeRepairs.get(edge.id) ?? edge.collection_mode;
    if (mode !== "map") continue;
    recordMapDriver(
      edge.to_node,
      edge.to_port,
      `edge:${edge.id}`,
      edge.enabled !== false,
    );
  }
  for (const origin of document.origins) {
    const mode = originModeRepairs.get(origin.id) ?? origin.collection_mode;
    if (mode !== "map") continue;
    recordMapDriver(
      origin.to_node,
      origin.to_port,
      `origin:${origin.id}`,
      true,
    );
  }

  const nodes = new Map<string, ResolvedNodeSemantics>();
  for (const [nodeId, draft] of drafts) {
    const mappedInputPorts = mappedPortsByNode.get(nodeId) ?? [];
    const allMappedInputPorts = allMappedPortsByNode.get(nodeId) ?? [];
    const runsPerItem = mappedInputPorts.length > 0;
    const outputsWidenedForAuthoring = allMappedInputPorts.length > 0;
    const portSpec = draft.spec ?? draft.displaySpec;
    nodes.set(nodeId, {
      nodeId,
      node: draft.node,
      spec: draft.spec,
      displaySpec: draft.displaySpec,
      compatibility: draft.compatibility,
      artifactTypeBindings: draft.artifactTypeBindings,
      mappedInputPorts,
      allMappedInputPorts,
      runsPerItem,
      outputsWidenedForAuthoring,
      effectiveOutputShapes: outputShapesMap(portSpec, runsPerItem),
      authoringOutputShapes: outputShapesMap(
        portSpec,
        outputsWidenedForAuthoring,
      ),
    });
  }

  const edges = new Map<string, ResolvedEdgeSemantics>();
  for (const edge of document.edges) {
    const collectionMode = edgeModeRepairs.get(edge.id) ?? edge.collection_mode;
    const sourceNode = nodes.get(edge.from_node);
    const targetNode = nodes.get(edge.to_node);
    const sourceSupported =
      sourceNode?.compatibility.status === "supported" &&
      sourceNode.spec !== null;
    const targetSupported =
      targetNode?.compatibility.status === "supported" &&
      targetNode.spec !== null;
    const sourcePort = sourceSupported
      ? (sourceNode.spec.outputs.find((port) => port.name === edge.from_port) ??
        null)
      : null;
    const targetPort = targetSupported
      ? (targetNode.spec.inputs.find((port) => port.name === edge.to_port) ??
        null)
      : null;

    const sourceShape: Port["shape"] = sourcePort
      ? sourceNode?.outputsWidenedForAuthoring && sourcePort.kind !== "service"
        ? "many"
        : sourcePort.shape
      : "one";

    const inputDrivers = mapDriversByInput.get(
      inputDriverKey(edge.to_node, edge.to_port),
    );
    const hasOtherMapDriver =
      inputDrivers !== undefined &&
      [...inputDrivers].some((driverId) => driverId !== `edge:${edge.id}`);
    const targetShape: Port["shape"] = targetPort
      ? hasOtherMapDriver
        ? "many"
        : targetPort.shape
      : "one";

    const allowedCollectionModes =
      sourcePort && targetPort
        ? collectionModesForShapes(sourceShape, targetPort, targetShape)
        : [];

    edges.set(edge.id, {
      edgeId: edge.id,
      edge,
      collectionMode,
      sourcePort,
      targetPort,
      sourceShape,
      targetShape,
      allowedCollectionModes,
    });
  }

  const origins = new Map<string, ResolvedOriginSemantics>();
  for (const origin of document.origins) {
    const collectionMode =
      originModeRepairs.get(origin.id) ?? origin.collection_mode;
    const targetNode = nodes.get(origin.to_node);
    const targetSupported =
      targetNode?.compatibility.status === "supported" &&
      targetNode.spec !== null;
    const targetPort = targetSupported
      ? (targetNode.spec.inputs.find((port) => port.name === origin.to_port) ??
        null)
      : null;
    const valueShape: Port["shape"] =
      "item_refs" in origin.value ? "many" : "one";
    const allowedCollectionModes = targetPort
      ? originCollectionModes(targetPort, valueShape)
      : [];
    origins.set(origin.id, {
      originId: origin.id,
      origin,
      collectionMode,
      targetPort,
      valueShape,
      allowedCollectionModes,
    });
  }

  return {
    nodes,
    edges,
    origins,
    edgeModeRepairs,
    originModeRepairs,
    mappedNodeIds,
    authoringMappedNodeIds,
  };
}

/**
 * Effective rendered shape of a node's output port, falling back to `port.shape`
 * when the node is not present in `semantics`.
 */
export function effectiveOutputPortShape(
  semantics: ResolvedGraphSemantics | null | undefined,
  nodeId: string,
  port: Port,
): Port["shape"] {
  return (
    semantics?.nodes.get(nodeId)?.effectiveOutputShapes.get(port.name) ??
    port.shape
  );
}

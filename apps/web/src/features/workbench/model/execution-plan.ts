import type { Node } from "@xyflow/react";

import { decodeHandleId } from "../canvas/handles";
import { inputPlugsForPort } from "../canvas/input-plugs";
import {
  WORKFLOW_NODE_TYPE,
  portHasInstancePlugs,
  serializeRunNode,
  serializeWorkflowEdgeTransport,
  type WorkflowEdge,
  type WorkflowNodeData,
  workflowNodeIsSupported,
} from "../canvas/types";
import type {
  PinnedOutputInput,
  RunEdgeInput,
  RunOriginInput,
  RunRequest,
  RunScopeInput,
  SavedGraphOrigin,
} from "@/lib/api";

export type WorkflowNode = Node<WorkflowNodeData, typeof WORKFLOW_NODE_TYPE>;

export type RunScope = RunScopeInput;

function workflowEdgeEndpoints(edge: WorkflowEdge): {
  sourcePortName: string;
  targetPortName: string;
  targetPlugId: string | null;
} | null {
  const source = decodeHandleId(edge.sourceHandle);
  const target = decodeHandleId(edge.targetHandle);
  const sourcePortName = edge.data?.sourcePortName ?? source?.portName;
  const targetPortName = edge.data?.targetPortName ?? target?.portName;
  if (!sourcePortName || !targetPortName) return null;
  const targetPlugId =
    edge.data?.targetPlugId !== undefined
      ? edge.data.targetPlugId
      : (target?.plugId ?? null);
  return { sourcePortName, targetPortName, targetPlugId };
}

export interface ExecutionSubgraph {
  nodeIds: ReadonlySet<string>;
  nodes: readonly WorkflowNode[];
  edges: readonly WorkflowEdge[];
}

export interface MissingRequiredInput {
  nodeId: string;
  nodeTitle: string;
  portName: string;
}

export interface ExecutionValidationIssue {
  nodeId: string | null;
  message: string;
}

export type ExecutionRequestPlanResult =
  | {
      status: "ready";
      request: RunRequest;
    }
  | {
      status: "invalid";
      message: string;
    };

function originSatisfiesSlot(
  origin: SavedGraphOrigin,
  nodeId: string,
  portName: string,
  plugId: string | null,
): boolean {
  return (
    origin.to_node === nodeId &&
    origin.to_port === portName &&
    (origin.to_plug ?? null) === plugId
  );
}

function serializeRunOrigin(origin: SavedGraphOrigin): RunOriginInput {
  return {
    to_node: origin.to_node,
    to_port: origin.to_port,
    to_plug: origin.to_plug ?? null,
    value: structuredClone(origin.value),
    conversion_path: (origin.conversion_path ?? []).map((step) => ({
      id: step.id,
      version: step.version,
    })),
  };
}

export function selectedNodeAndAncestorIds(
  nodes: readonly WorkflowNode[],
  edges: readonly WorkflowEdge[],
): Set<string> {
  const knownNodeIds = new Set(nodes.map((node) => node.id));
  const executionNodeIds = new Set(
    nodes.filter((node) => node.selected).map((node) => node.id),
  );
  const pendingNodeIds = [...executionNodeIds];

  while (pendingNodeIds.length) {
    const targetNodeId = pendingNodeIds.shift();
    if (targetNodeId === undefined) continue;

    for (const edge of edges) {
      if (
        edge.data?.enabled === false ||
        edge.target !== targetNodeId ||
        !knownNodeIds.has(edge.source) ||
        executionNodeIds.has(edge.source)
      ) {
        continue;
      }
      executionNodeIds.add(edge.source);
      pendingNodeIds.push(edge.source);
    }
  }

  return executionNodeIds;
}

export function executionSubgraphFor(
  scope: RunScope,
  nodes: readonly WorkflowNode[],
  edges: readonly WorkflowEdge[],
): ExecutionSubgraph {
  const activeEdges = edges.filter((edge) => edge.data?.enabled !== false);
  let nodeIds: Set<string>;

  if (scope === "all") {
    nodeIds = new Set(nodes.map((node) => node.id));
  } else if (scope === "selected-with-dependencies") {
    nodeIds = selectedNodeAndAncestorIds(nodes, activeEdges);
  } else {
    nodeIds = new Set(
      nodes.filter((node) => node.selected).map((node) => node.id),
    );
  }

  const executionNodes = nodes.filter((node) => nodeIds.has(node.id));
  let executionEdges: WorkflowEdge[];

  if (scope === "all") {
    executionEdges = activeEdges;
  } else if (scope === "selected-with-dependencies") {
    executionEdges = activeEdges.filter(
      (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target),
    );
  } else {
    executionEdges = activeEdges.filter((edge) => nodeIds.has(edge.target));
  }

  return {
    nodeIds,
    nodes: executionNodes,
    edges: executionEdges,
  };
}

export function missingRequiredInputsFor(
  nodes: readonly WorkflowNode[],
  edges: readonly WorkflowEdge[],
  origins: readonly SavedGraphOrigin[] = [],
): MissingRequiredInput[] {
  return nodes.flatMap((node) =>
    node.data.spec.inputs.flatMap((port) => {
      if (portHasInstancePlugs(port)) {
        if (!port.required) return [];
        const plugs = inputPlugsForPort(node.data.inputPlugs, port.name);
        if (!plugs.length) {
          return [
            {
              nodeId: node.id,
              nodeTitle: node.data.spec.title,
              portName: port.name,
            },
          ];
        }
        return plugs.flatMap((plug, index) =>
          edges.some(
            (edge) =>
              edge.data?.enabled !== false &&
              edge.target === node.id &&
              decodeHandleId(edge.targetHandle)?.plugId === plug.id,
          ) ||
          origins.some((origin) =>
            originSatisfiesSlot(origin, node.id, port.name, plug.id),
          )
            ? []
            : [
                {
                  nodeId: node.id,
                  nodeTitle: node.data.spec.title,
                  portName: `${port.name} input ${index + 1}`,
                },
              ],
        );
      }
      if (!port.required) return [];
      return edges.some(
        (edge) =>
          edge.data?.enabled !== false &&
          edge.target === node.id &&
          decodeHandleId(edge.targetHandle)?.portName === port.name,
      ) ||
        origins.some((origin) =>
          originSatisfiesSlot(origin, node.id, port.name, null),
        )
        ? []
        : [
            {
              nodeId: node.id,
              nodeTitle: node.data.spec.title,
              portName: port.name,
            },
          ];
    }),
  );
}

export function executionValidationIssue(
  scope: RunScope,
  executionNodes: readonly WorkflowNode[],
  executionEdges: readonly WorkflowEdge[],
  origins: readonly SavedGraphOrigin[] = [],
): ExecutionValidationIssue | null {
  if (!executionNodes.length) {
    return {
      nodeId: null,
      message:
        scope !== "all"
          ? "Select at least one node before running a selection."
          : "Add at least one node before running the workflow.",
    };
  }

  const incompatibleNode = executionNodes.find(
    (node) => !workflowNodeIsSupported(node.data),
  );
  if (incompatibleNode) {
    const compatibility = incompatibleNode.data.compatibility;
    const issue =
      compatibility.status === "supported"
        ? "The node is unavailable."
        : compatibility.issues.join(" ");
    return {
      nodeId: incompatibleNode.id,
      message: `Cannot run ${incompatibleNode.data.spec.title}: ${issue}`,
    };
  }

  const executionNodeIds = new Set(executionNodes.map((node) => node.id));
  const incompatibleEdge = executionEdges.find(
    (edge) =>
      edge.data?.compatibilityIssues?.length &&
      executionNodeIds.has(edge.source) &&
      executionNodeIds.has(edge.target),
  );
  if (incompatibleEdge) {
    return {
      nodeId: incompatibleEdge.target,
      message: `Cannot run connection ${incompatibleEdge.id}: ${incompatibleEdge.data?.compatibilityIssues?.join(" ")}`,
    };
  }

  const missingInputs = missingRequiredInputsFor(
    executionNodes,
    executionEdges,
    origins,
  );
  if (!missingInputs.length) return null;

  const first = missingInputs[0];
  return {
    nodeId: first.nodeId,
    message: `${first.nodeTitle}.${first.portName} is required but unconnected in this run.`,
  };
}

export function executionRequestPlan(
  scope: RunScope,
  planningNodes: readonly WorkflowNode[],
  execution: ExecutionSubgraph,
  origins: readonly SavedGraphOrigin[] = [],
): ExecutionRequestPlanResult {
  const pinnedOutputs: PinnedOutputInput[] = [];

  if (scope === "selected") {
    const nodesById = new Map(planningNodes.map((node) => [node.id, node]));
    const pinnedSourcePorts = new Map<string, Set<string>>();
    const missingPinnedOutputs: string[] = [];

    for (const edge of execution.edges) {
      if (execution.nodeIds.has(edge.source)) continue;

      const endpoints = workflowEdgeEndpoints(edge);
      if (!endpoints) {
        return {
          status: "invalid",
          message: `Cannot run the selection because edge ${edge.id} does not identify both source and target ports.`,
        };
      }

      const sourcePorts =
        pinnedSourcePorts.get(edge.source) ?? new Set<string>();
      if (sourcePorts.has(endpoints.sourcePortName)) continue;
      sourcePorts.add(endpoints.sourcePortName);
      pinnedSourcePorts.set(edge.source, sourcePorts);

      const sourceNode = nodesById.get(edge.source);
      const output =
        sourceNode?.data.run?.status === "succeeded"
          ? sourceNode.data.run.outputs.find(
              (candidate) => candidate.port === endpoints.sourcePortName,
            )
          : undefined;
      if (!output) {
        const sourceName = sourceNode?.data.spec.title ?? edge.source;
        missingPinnedOutputs.push(`${sourceName}.${endpoints.sourcePortName}`);
        continue;
      }

      pinnedOutputs.push({
        from_node: edge.source,
        from_port: endpoints.sourcePortName,
        value: output.value,
      });
    }

    if (missingPinnedOutputs.length) {
      const endpoints = missingPinnedOutputs.join(", ");
      return {
        status: "invalid",
        message: `Cannot run the selection because no accessible materialized output is available for ${endpoints}. Select the missing upstream nodes too, or choose “Run with dependencies”.`,
      };
    }
  }

  const runEdges = execution.edges.flatMap<RunEdgeInput>((edge) => {
    const endpoints = workflowEdgeEndpoints(edge);
    if (!endpoints) return [];
    return [
      {
        from_node: edge.source,
        from_port: endpoints.sourcePortName,
        to_node: edge.target,
        to_port: endpoints.targetPortName,
        to_plug: endpoints.targetPlugId,
        ...serializeWorkflowEdgeTransport(edge.data),
      },
    ];
  });

  const runOrigins = origins
    .filter((origin) => execution.nodeIds.has(origin.to_node))
    .map(serializeRunOrigin);

  const activeInputPlugIdsByNode = new Map<string, Set<string>>();
  for (const edge of execution.edges) {
    const target = decodeHandleId(edge.targetHandle);
    const targetPlugId =
      edge.data?.targetPlugId !== undefined
        ? edge.data.targetPlugId
        : target?.plugId;
    if (!targetPlugId) continue;
    const plugIds = activeInputPlugIdsByNode.get(edge.target) ?? new Set();
    plugIds.add(targetPlugId);
    activeInputPlugIdsByNode.set(edge.target, plugIds);
  }
  for (const origin of runOrigins) {
    if (!origin.to_plug) continue;
    const plugIds = activeInputPlugIdsByNode.get(origin.to_node) ?? new Set();
    plugIds.add(origin.to_plug);
    activeInputPlugIdsByNode.set(origin.to_node, plugIds);
  }

  const runNodes = execution.nodes.map((node) => {
    const activeInputPlugIds =
      activeInputPlugIdsByNode.get(node.id) ?? new Set<string>();
    return serializeRunNode(node.id, node.data, activeInputPlugIds);
  });

  const request: RunRequest = {
    nodes: runNodes,
    edges: runEdges,
    origins: runOrigins,
    scope,
    ...(scope === "selected" ? { pinned_outputs: pinnedOutputs } : {}),
  };
  return { status: "ready", request };
}

import type { Node } from "@xyflow/react";

import { decodeHandleId } from "../canvas/handles";
import { inputPlugsForPort } from "../canvas/input-plugs";
import { isCollectionNode } from "./collection-spec";
import { validateConfig } from "../canvas/config-schema";
import {
  WORKFLOW_NODE_TYPE,
  portHasInstancePlugs,
  type WorkflowEdge,
  type WorkflowNodeData,
  workflowNodeIsSupported,
} from "../canvas/types";
import type { RunTargetInput, SavedGraphOrigin } from "@/lib/api";

export type WorkflowNode = Node<WorkflowNodeData, typeof WORKFLOW_NODE_TYPE>;

/**
 * Which nodes a person is asking to become fresh. Every Run demands the same
 * thing — the named instances and the stale part of what they read — so the
 * scope only chooses the names; it never changes what is sent to the server.
 */
export type RunScope = "all" | "selected" | "selected-with-dependencies";

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
        const filled = plugs.map(
          (plug) =>
            edges.some(
              (edge) =>
                edge.data?.enabled !== false &&
                edge.target === node.id &&
                decodeHandleId(edge.targetHandle)?.plugId === plug.id,
            ) ||
            origins.some((origin) =>
              originSatisfiesSlot(origin, node.id, port.name, plug.id),
            ),
        );
        // A collection keeps a spare plug for its next member; empty plugs
        // are left out of the run, so it only needs one member to be ready.
        if (isCollectionNode(node)) {
          return filled.some(Boolean)
            ? []
            : [
                {
                  nodeId: node.id,
                  nodeTitle: node.data.spec.title,
                  portName: port.name,
                },
              ];
        }
        return plugs.flatMap((plug, index) =>
          filled[index]
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

  for (const node of executionNodes) {
    const issue = validateConfig(
      node.data.spec.config_schema,
      node.data.config,
    )[0];
    if (!issue) continue;
    return {
      nodeId: node.id,
      message: `Cannot run ${node.data.spec.title}: ${issue.message}`,
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

  const [first] = missingInputs;
  if (!first) return null;
  return {
    nodeId: first.nodeId,
    message: `${first.nodeTitle}.${first.portName} is required but unconnected in this run.`,
  };
}

/**
 * The demand a Run carries: the instances the person named, in canvas order.
 *
 * A Run never travels with a copy of the graph or with upstream values pinned
 * into the request. The server reads the live Project head, fingerprints these
 * instances and their upstream, and schedules only the part that is not fresh,
 * so naming the nodes is the whole ask and a selection reads whatever its
 * upstream already stored.
 */
export function runTargetsFor(
  execution: ExecutionSubgraph,
): readonly RunTargetInput[] {
  return execution.nodes.map((node) => ({ node_id: node.id, call_path: [] }));
}

import type { Port } from "@/lib/api";

import { serviceContractKey } from "../authoring/service-contract-key";
import {
  portIsService,
  type WorkflowEdge,
  type WorkflowNodeData,
} from "../authoring/types";

export interface UnsupportedProviderOutput {
  portName: string;
  providerTitle: string;
}

interface GraphNode {
  id: string;
  data: WorkflowNodeData;
}

function portWords(port: Port): string {
  const title = port.title?.trim();
  return title ? title : port.name.replaceAll("_", " ");
}

/** An optional consumer output the connected provider does not produce. */
export function unsupportedOutputForPort(
  port: Port,
  consumer: GraphNode,
  nodes: readonly GraphNode[],
  edges: readonly WorkflowEdge[],
): UnsupportedProviderOutput | null {
  const requirement = port.requires_service_feature;
  if (!requirement || port.direction !== "output") return null;

  const input = consumer.data.spec.inputs.find(
    (candidate) => candidate.name === requirement.input_port,
  );
  if (!input || !portIsService(input)) return null;
  const edge = edges.find(
    (candidate) =>
      candidate.data?.enabled !== false &&
      candidate.target === consumer.id &&
      candidate.targetPort === input.name,
  );
  if (!edge) return null;
  const provider = nodes.find((candidate) => candidate.id === edge.source);
  if (!provider) return null;
  const output = provider.data.spec.outputs.find(
    (candidate) => candidate.name === edge.sourcePort,
  );
  if (!output || !portIsService(output)) return null;

  const accepted = new Set(input.service_contracts?.map(serviceContractKey));
  const declaration = output.service_features?.find((entry) =>
    accepted.has(serviceContractKey(entry.contract)),
  );
  if (!declaration || declaration.features.includes(requirement.feature)) {
    return null;
  }
  return { portName: port.name, providerTitle: provider.data.spec.title };
}

export function unsupportedOutputLabel(
  unsupported: UnsupportedProviderOutput,
): string {
  return `Not produced by ${unsupported.providerTitle}`;
}

/**
 * Why an input on `nodeId` cannot receive a result: the upstream provider does
 * not produce the wired output. Matches the run binder's wording.
 */
export function notProducedInputReasons(
  nodeId: string,
  nodes: readonly GraphNode[],
  edges: readonly WorkflowEdge[],
): readonly { portName: string; message: string }[] {
  const node = nodes.find((candidate) => candidate.id === nodeId);
  if (!node) return [];

  const reasons: { portName: string; message: string }[] = [];
  for (const edge of edges) {
    if (edge.data?.enabled === false || edge.target !== nodeId) continue;

    const source = nodes.find((candidate) => candidate.id === edge.source);
    if (!source) continue;
    const sourcePort = source.data.spec.outputs.find(
      (port) => port.name === edge.sourcePort,
    );
    if (!sourcePort) continue;

    const unsupported = unsupportedOutputForPort(
      sourcePort,
      source,
      nodes,
      edges,
    );
    if (!unsupported) continue;

    const targetPort = node.data.spec.inputs.find(
      (port) => port.name === edge.targetPort,
    );
    const label = targetPort ? portWords(targetPort) : edge.targetPort;
    reasons.push({
      portName: edge.targetPort,
      message: `${label} are not produced by ${unsupported.providerTitle}`,
    });
  }
  return reasons;
}

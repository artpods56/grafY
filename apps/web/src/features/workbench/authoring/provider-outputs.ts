import type { NodeSpec, Port } from "@/lib/api";

import { serviceContractKey } from "./service-contract-key";
import { portIsService } from "./types";

export interface UnsupportedProviderOutput {
  portName: string;
  providerTitle: string;
}

export interface GatedInputOutput {
  portName: string;
  inputPortName: string;
  inputTitle: string;
}

export interface ExclusiveBlockedInput {
  portName: string;
  activeInputTitle: string;
}

/** The slice of a node this check reads. A workflow node satisfies it. */
export interface ProviderOutputNode {
  readonly id: string;
  readonly data: { readonly spec: NodeSpec };
}

/** The slice of an edge this check reads. A workflow edge satisfies it. */
export interface ProviderOutputEdge {
  readonly source: string;
  readonly target: string;
  readonly sourcePort: string;
  readonly targetPort: string;
  readonly data?: { readonly enabled?: boolean };
}

/** The slice of an origin this check reads. */
export interface ProviderOutputOrigin {
  readonly to_node: string;
  readonly to_port: string;
}

function portWords(port: Port): string {
  const title = port.title?.trim();
  return title ? title : port.name.replaceAll("_", " ");
}

function inputPortConnected(
  nodeId: string,
  portName: string,
  edges: readonly ProviderOutputEdge[],
  origins: readonly ProviderOutputOrigin[],
): boolean {
  if (
    origins.some(
      (origin) => origin.to_node === nodeId && origin.to_port === portName,
    )
  ) {
    return true;
  }
  return edges.some(
    (edge) =>
      edge.data?.enabled !== false &&
      edge.target === nodeId &&
      edge.targetPort === portName,
  );
}

/** An optional consumer output the connected provider does not produce. */
export function unsupportedOutputForPort(
  port: Port,
  consumer: ProviderOutputNode,
  nodes: readonly ProviderOutputNode[],
  edges: readonly ProviderOutputEdge[],
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

/** An optional output gated on an artifact input that is not connected yet. */
export function gatedOutputForPort(
  port: Port,
  consumer: ProviderOutputNode,
  edges: readonly ProviderOutputEdge[],
  origins: readonly ProviderOutputOrigin[] = [],
): GatedInputOutput | null {
  const requiredInput = port.requires_input;
  if (!requiredInput || port.direction !== "output") return null;

  const input = consumer.data.spec.inputs.find(
    (candidate) => candidate.name === requiredInput,
  );
  if (!input || portIsService(input)) return null;
  if (inputPortConnected(consumer.id, input.name, edges, origins)) {
    return null;
  }
  return {
    portName: port.name,
    inputPortName: input.name,
    inputTitle: portWords(input),
  };
}

export function gatedOutputLabel(gated: GatedInputOutput): string {
  return `Connect ${gated.inputTitle}`;
}

/** An optional input dimmed because another input in its exclusive group is connected. */
export function exclusiveInputReason(
  port: Port,
  node: ProviderOutputNode,
  edges: readonly ProviderOutputEdge[],
  origins: readonly ProviderOutputOrigin[] = [],
): ExclusiveBlockedInput | null {
  const group = port.exclusive_group;
  if (!group || port.direction !== "input") return null;
  if (inputPortConnected(node.id, port.name, edges, origins)) return null;

  for (const sibling of node.data.spec.inputs) {
    if (sibling.name === port.name || sibling.exclusive_group !== group) {
      continue;
    }
    if (inputPortConnected(node.id, sibling.name, edges, origins)) {
      return {
        portName: port.name,
        activeInputTitle: portWords(sibling),
      };
    }
  }
  return null;
}

export function exclusiveInputLabel(blocked: ExclusiveBlockedInput): string {
  return `Using ${blocked.activeInputTitle}`;
}

/**
 * Why an input on `nodeId` cannot receive a result: the upstream provider or
 * unconnected input does not produce the wired output. Matches the run binder's
 * wording.
 */
export function notProducedInputReasons(
  nodeId: string,
  nodes: readonly ProviderOutputNode[],
  edges: readonly ProviderOutputEdge[],
  origins: readonly ProviderOutputOrigin[] = [],
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

    const targetPort = node.data.spec.inputs.find(
      (port) => port.name === edge.targetPort,
    );
    const label = targetPort ? portWords(targetPort) : edge.targetPort;

    const unsupported = unsupportedOutputForPort(
      sourcePort,
      source,
      nodes,
      edges,
    );
    if (unsupported) {
      reasons.push({
        portName: edge.targetPort,
        message: `${label} are not produced by ${unsupported.providerTitle}`,
      });
      continue;
    }

    const gated = gatedOutputForPort(sourcePort, source, edges, origins);
    if (gated) {
      reasons.push({
        portName: edge.targetPort,
        message: `${label} is not produced because ${gated.inputTitle} is not connected`,
      });
    }
  }
  return reasons;
}

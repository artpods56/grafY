import type { Port } from "@/lib/api";

import { decodeHandleId } from "./handles";
import {
  portIsService,
  type WorkflowEdge,
  type WorkflowNodeData,
} from "./types";

export interface ConnectedServiceProvider {
  nodeId: string;
  title: string;
  /** Feature strings from the provider's service output catalog entry. */
  features: readonly string[];
}

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

/**
 * The service provider feeding `nodeId`, when exactly one service input has an
 * enabled wire from a provider node that declares features on its output.
 */
export function connectedServiceProvider(
  nodeId: string,
  nodes: readonly GraphNode[],
  edges: readonly WorkflowEdge[],
): ConnectedServiceProvider | null {
  const node = nodes.find((candidate) => candidate.id === nodeId);
  if (!node) return null;

  for (const port of node.data.spec.inputs) {
    if (!portIsService(port)) continue;
    const edge = edges.find(
      (candidate) =>
        candidate.data?.enabled !== false &&
        candidate.target === nodeId &&
        decodeHandleId(candidate.targetHandle)?.portName === port.name,
    );
    if (!edge) continue;
    const provider = nodes.find((candidate) => candidate.id === edge.source);
    if (!provider) continue;
    const sourceHandle = decodeHandleId(edge.sourceHandle);
    const output = provider.data.spec.outputs.find(
      (candidate) => candidate.name === sourceHandle?.portName,
    );
    if (!output || !portIsService(output)) continue;
    return {
      nodeId: provider.id,
      title: provider.data.spec.title,
      features: output.features ?? [],
    };
  }
  return null;
}

/**
 * An optional consumer output the connected provider does not produce.
 *
 * ASSUMPTION: feature strings on a service output match optional consumer
 * output port names. Required outputs stay available.
 */
export function unsupportedOutputForPort(
  port: Port,
  provider: ConnectedServiceProvider | null,
): UnsupportedProviderOutput | null {
  if (!provider || port.direction !== "output" || port.required) return null;
  if (provider.features.includes(port.name)) return null;
  return {
    portName: port.name,
    providerTitle: provider.title,
  };
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
    const targetHandle = decodeHandleId(edge.targetHandle);
    const sourceHandle = decodeHandleId(edge.sourceHandle);
    if (!targetHandle || !sourceHandle) continue;

    const source = nodes.find((candidate) => candidate.id === edge.source);
    if (!source) continue;
    const sourcePort = source.data.spec.outputs.find(
      (port) => port.name === sourceHandle.portName,
    );
    if (!sourcePort) continue;

    const provider = connectedServiceProvider(source.id, nodes, edges);
    const unsupported = unsupportedOutputForPort(sourcePort, provider);
    if (!unsupported) continue;

    const targetPort = node.data.spec.inputs.find(
      (port) => port.name === targetHandle.portName,
    );
    const label = targetPort ? portWords(targetPort) : targetHandle.portName;
    reasons.push({
      portName: targetHandle.portName,
      message: `${label} are not produced by ${unsupported.providerTitle}`,
    });
  }
  return reasons;
}

import type { Connection, Edge } from "@xyflow/react";
import type {
  ArtifactConversionSpec,
  SavedGraphOrigin,
  RunPortOutput,
  RunNodeResult,
} from "@/lib/api";
import {
  artifactDropPayload,
  resolveArtifactDrop,
} from "../model/artifact-drop";
import { cardArtifactRefs, type ArtifactCardValue } from "./artifact-card";
import type {
  ArtifactViewerEdge,
  ArtifactViewerNode,
  CanvasWorkflowNode,
} from "./artifact-viewer";
import { decodeHandleId, encodeHandleId } from "./handles";
import {
  effectivePortShape,
  portHasInstancePlugs,
  portMetaForPort,
  workflowNodeIsSupported,
} from "./types";

export const ARTIFACT_CARD_OUTPUT_HANDLE = "artifact-card-output";
export const ARTIFACT_ORIGIN_EDGE_TYPE = "grafyArtifactOriginEdge";
interface ArtifactOriginEdgeData extends Record<string, unknown> {
  originId: string;
  onDisconnect?: (originId: string) => void;
}
export type ArtifactOriginEdge = Edge<
  ArtifactOriginEdgeData,
  typeof ARTIFACT_ORIGIN_EDGE_TYPE
> & { data: ArtifactOriginEdgeData };

type ArtifactCardSource =
  | { kind: "fixed"; value: ArtifactCardValue | null; output: null }
  | { kind: "waiting"; value: null; output: null }
  | { kind: "output"; value: ArtifactCardValue; output: RunPortOutput };

/** Rendering and outgoing connections resolve the same exact output value. */
export function resolveArtifactCardSource({
  value,
  feed,
  run,
}: {
  value: ArtifactCardValue | null | undefined;
  feed: ArtifactViewerEdge | undefined;
  run: RunNodeResult | null | undefined;
}): ArtifactCardSource {
  if (!feed) return { kind: "fixed", value: value ?? null, output: null };
  const output =
    run?.status === "succeeded"
      ? run.outputs.find((output) => output.port === feed.data?.sourcePortName)
      : undefined;
  if (!output || feed.data?.projection?.path.length) {
    return { kind: "waiting", value: null, output: null };
  }
  return { kind: "output", value: output.value, output };
}

/** A following card may pass only the current output, never its saved fallback. */
export function artifactCardConnectionValue(
  card: ArtifactViewerNode,
  feeds: readonly ArtifactViewerEdge[],
  nodes: readonly CanvasWorkflowNode[],
): ArtifactCardValue | null {
  const feed = feeds.find((edge) => edge.target === card.id);
  return resolveArtifactCardSource({
    value: card.data.artifactRef,
    feed,
    run: nodes.find((node) => node.id === feed?.source)?.data.run,
  }).value;
}

/** Resolve real canvas endpoints before applying the normal artifact-input rules. */
export function resolveArtifactCardConnection(
  connection: Connection,
  cards: readonly ArtifactViewerNode[],
  feeds: readonly ArtifactViewerEdge[],
  nodes: readonly CanvasWorkflowNode[],
  conversions: readonly ArtifactConversionSpec[],
) {
  if (connection.sourceHandle !== ARTIFACT_CARD_OUTPUT_HANDLE) return null;
  const card = cards.find((card) => card.id === connection.source);
  const node = nodes.find((node) => node.id === connection.target);
  const handle = decodeHandleId(connection.targetHandle);
  if (
    !card ||
    !node ||
    !workflowNodeIsSupported(node.data) ||
    handle?.direction !== "input"
  )
    return null;
  const port = node.data.spec.inputs.find(
    (port) => port.name === handle.portName,
  );
  if (!port) return null;
  const plugId = handle.plugId ?? null;
  if (
    portHasInstancePlugs(port)
      ? !node.data.inputPlugs.some(
          (plug) => plug.id === plugId && plug.portName === port.name,
        )
      : plugId !== null
  )
    return null;
  const value = artifactCardConnectionValue(card, feeds, nodes);
  if (!value || cardArtifactRefs(value).length === 0) return null;
  const payload = artifactDropPayload(value);
  const variable = port.artifact_type_variable;
  const binding =
    variable && !node.data.artifactTypeBindings[variable]
      ? {
          variable,
          artifactType: {
            id: value.artifact_type,
            schema_version: value.schema_version,
          },
        }
      : null;
  const bindings = binding
    ? {
        ...node.data.artifactTypeBindings,
        [binding.variable]: binding.artifactType,
      }
    : node.data.artifactTypeBindings;
  if (!resolveArtifactDrop(payload, port, bindings, conversions)) return null;
  return {
    payload,
    target: { nodeId: node.id, portName: port.name, plugId },
    port,
    bindings,
    binding,
  };
}

/** Draw saved artifact inputs from the cards that still display those exact values. */
export function artifactOriginConnections(
  cards: readonly ArtifactViewerNode[],
  feeds: readonly ArtifactViewerEdge[],
  nodes: readonly CanvasWorkflowNode[],
  origins: readonly SavedGraphOrigin[],
): ArtifactOriginEdge[] {
  const edges: ArtifactOriginEdge[] = [];
  for (const origin of origins) {
    const target = nodes.find((node) => node.id === origin.to_node);
    const port = target?.data.spec.inputs.find(
      (port) => port.name === origin.to_port,
    );
    if (!target || !port) continue;
    const remaining = new Set(
      cardArtifactRefs(origin.value).map((ref) => ref.artifact_id),
    );
    for (const card of cards) {
      const value = artifactCardConnectionValue(card, feeds, nodes);
      const refs = cardArtifactRefs(value);
      if (
        !value ||
        value.artifact_type !== origin.value.artifact_type ||
        value.schema_version !== origin.value.schema_version ||
        refs.length === 0 ||
        !refs.every((ref) => remaining.has(ref.artifact_id))
      )
        continue;
      edges.push({
        id: `artifact-origin:${origin.id}:${card.id}`,
        type: ARTIFACT_ORIGIN_EDGE_TYPE,
        source: card.id,
        sourceHandle: ARTIFACT_CARD_OUTPUT_HANDLE,
        target: target.id,
        targetHandle: encodeHandleId(
          portMetaForPort(
            port,
            effectivePortShape(target.data, port),
            origin.to_plug ?? undefined,
            target.data.artifactTypeBindings,
          ),
        ),
        data: { originId: origin.id },
      });
      for (const ref of refs) remaining.delete(ref.artifact_id);
      if (remaining.size === 0) break;
    }
  }
  return edges;
}

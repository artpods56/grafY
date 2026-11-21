import type { Connection } from "@xyflow/react";

import type { NodeRegistry } from "@/lib/api";
import { ARTIFACT_CARD_OUTPUT_HANDLE } from "../canvas/artifact-connections";
import {
  ARTIFACT_VIEWER_INPUT_HANDLE,
  type ArtifactViewerCanvasState,
  type GraphPresentation,
} from "../canvas/artifact-viewer";
import { decodeHandleId, encodeHandleId } from "../canvas/handles";
import {
  effectivePortShape,
  portMetaForPort,
  workflowNodeIsSupported,
} from "../canvas/types";
import type {
  CellCardMove,
  CellConnectionEnds,
} from "../cell-canvas/CellCanvas";
import type {
  CellRemotePeerState,
  CellSelectionSnapshot,
} from "../cell-canvas/cell-contracts";
import {
  cellGraphFromAuthoredDocument,
  cellOriginFromWorld,
  graphCommandsFromCellDeleteForDocument,
  graphCommandsFromCellMovesForDocument,
  type CellNodeRunState,
} from "../cell-canvas/cell-document-adapter";
import { CELL_SIZE, cellToWorldOrigin } from "../cell-canvas/cell-model";
import type { WorkflowNode } from "../model/execution-plan";
import type { AuthoredGraphDocument } from "../model/graph-document";
import type { PresenceParticipant, RoomInstanceState } from "../room/protocol";
import { actorColor } from "../room/remote-selection";
import type { CanvasSelection } from "./workbench-canvas-selection";

function cellNodeStatus(
  node: WorkflowNode,
  instance: RoomInstanceState | undefined,
): Pick<CellNodeRunState, "status" | "statusLabel"> {
  switch (instance?.state ?? node.data.execution.status) {
    case "running":
    case "cancelling":
      return { status: "working", statusLabel: "Running" };
    case "queued":
      return { status: "working", statusLabel: "Queued" };
    case "failed":
      return { status: "error", statusLabel: "Error" };
    case "succeeded":
    case "fresh":
      return { status: "done", statusLabel: "Fresh" };
    case "stale":
      return { status: "idle", statusLabel: "Stale" };
    default:
      if (!instance && node.data.execution.status === "idle") {
        if (node.data.run?.status === "succeeded")
          return { status: "done", statusLabel: "Fresh" };
        if (node.data.run?.status === "failed")
          return { status: "error", statusLabel: "Error" };
      }
      return { status: "idle" };
  }
}

export function buildWorkbenchCellScene({
  document,
  registry,
  presentation,
  nodes,
  nodeInstanceStates,
  collapsedAppendices,
  canRun,
}: {
  document: AuthoredGraphDocument;
  registry: NodeRegistry;
  presentation: GraphPresentation | null;
  nodes: readonly WorkflowNode[];
  nodeInstanceStates: Readonly<Record<string, RoomInstanceState>>;
  collapsedAppendices: ReadonlySet<string>;
  canRun: boolean;
}) {
  const nodeRunState: Record<string, CellNodeRunState> = {};
  for (const node of nodes) {
    const instance = nodeInstanceStates[node.id];
    const { run, execution, layout } = node.data;
    const status = cellNodeStatus(node, instance);
    const error =
      status.status === "error"
        ? instance?.error ||
          execution.error ||
          run?.error ||
          "Execution failed."
        : null;
    const outputs = run?.outputs ?? [];
    const itemCount = outputs.reduce(
      (count, output) => count + output.artifacts.length,
      0,
    );
    const heightCells = Math.max(
      4,
      Math.ceil((layout?.appendixHeight ?? 0) / CELL_SIZE),
    );
    nodeRunState[node.id] = {
      ...status,
      runDisabled: !canRun || !workflowNodeIsSupported(node.data),
      appendix: error
        ? {
            title: "Execution error",
            kindBadge: "Error",
            summaryText: error,
            heightCells,
          }
        : outputs.length
          ? {
              title: "Execution output",
              kindBadge: "Output",
              summaryText: `${outputs.length} output port${outputs.length === 1 ? "" : "s"}`,
              previewLines: outputs.map(
                ({ port, artifacts }) =>
                  `${port}: ${artifacts.length} artifact${artifacts.length === 1 ? "" : "s"}`,
              ),
              itemCount,
              heightCells,
            }
          : undefined,
    };
  }
  return cellGraphFromAuthoredDocument(document, registry, {
    presentation,
    nodeRunState,
    collapsedAppendices,
  });
}

export function cellRemotePeersFromParticipants(
  participants: readonly PresenceParticipant[],
  localSessionId: string | null,
  openGraphId: string | null,
): CellRemotePeerState[] {
  if (openGraphId === null) return [];
  return participants
    .filter(
      (peer) =>
        peer.project_room_session_id !== localSessionId &&
        peer.graph_id === openGraphId,
    )
    .map((peer) => ({
      actorId: peer.actor.actor_id,
      sessionId: peer.project_room_session_id,
      displayName: peer.actor.display_name,
      color: actorColor(peer.actor.color),
      cursor: peer.cursor,
      activity: peer.activity ?? "idle",
      selectedCardIds: peer.selected_node_ids,
      draggingCards: Object.fromEntries(
        peer.transient_node_positions.map((position) => [
          position.node_id,
          cellOriginFromWorld(position),
        ]),
      ),
    }));
}

export function encodeCellPortHandleForDiscovery(
  node: WorkflowNode,
  portId: string,
  direction: "input" | "output",
) {
  const separator = direction === "input" ? portId.indexOf("::") : -1;
  const portName = separator < 0 ? portId : portId.slice(0, separator);
  const plugId = separator < 0 ? undefined : portId.slice(separator + 2);
  const ports =
    direction === "input" ? node.data.spec.inputs : node.data.spec.outputs;
  const port = ports.find((candidate) => candidate.name === portName);
  if (!port || port.direction !== direction) return null;
  const handleId = encodeHandleId(
    portMetaForPort(
      port,
      direction === "input" ? port.shape : effectivePortShape(node.data, port),
      plugId,
      node.data.artifactTypeBindings,
    ),
  );
  const decoded = decodeHandleId(handleId);
  return decoded ? { port, handleId, decoded } : null;
}

export function cellConnectionToWorkbenchConnection(
  nodes: readonly WorkflowNode[],
  viewers: readonly ArtifactViewerCanvasState["nodes"][number][],
  {
    sourceCardId,
    sourcePortId,
    targetCardId,
    targetPortId,
  }: CellConnectionEnds,
): Connection | null {
  const sourceNode = nodes.find((node) => node.id === sourceCardId);
  const targetNode = nodes.find((node) => node.id === targetCardId);
  const sourceHandle = sourceNode
    ? encodeCellPortHandleForDiscovery(sourceNode, sourcePortId, "output")
        ?.handleId
    : sourcePortId === ARTIFACT_CARD_OUTPUT_HANDLE &&
        viewers.some((viewer) => viewer.id === sourceCardId)
      ? ARTIFACT_CARD_OUTPUT_HANDLE
      : null;
  const targetHandle = targetNode
    ? encodeCellPortHandleForDiscovery(targetNode, targetPortId, "input")
        ?.handleId
    : targetPortId === ARTIFACT_VIEWER_INPUT_HANDLE &&
        viewers.some((viewer) => viewer.id === targetCardId)
      ? ARTIFACT_VIEWER_INPUT_HANDLE
      : null;
  return sourceHandle && targetHandle
    ? { source: sourceCardId, target: targetCardId, sourceHandle, targetHandle }
    : null;
}

export function partitionCellSelection(
  { cardIds, pipeIds }: CellSelectionSnapshot,
  document: AuthoredGraphDocument,
  artifactViewers: ArtifactViewerCanvasState,
): CanvasSelection {
  return {
    nodeIds: document.nodes
      .filter(({ id }) => cardIds.has(id))
      .map(({ id }) => id),
    agentIds: document.agents
      .filter(({ id }) => cardIds.has(id))
      .map(({ id }) => id),
    viewerIds: artifactViewers.nodes
      .filter(({ id }) => cardIds.has(id))
      .map(({ id }) => id),
    annotationIds: artifactViewers.annotations
      .filter(({ id }) => cardIds.has(id))
      .map(({ id }) => id),
    edgeIds: [...pipeIds],
  };
}

export function partitionCellMoves(
  moves: readonly CellCardMove[],
  document: AuthoredGraphDocument,
  artifactViewers: ArtifactViewerCanvasState,
) {
  const viewerIds = new Set(artifactViewers.nodes.map(({ id }) => id));
  const annotationIds = new Set(
    artifactViewers.annotations.map(({ id }) => id),
  );
  const viewerPositions = moves
    .filter(({ cardId }) => viewerIds.has(cardId))
    .map(({ cardId, col, row }) => ({
      viewer_id: cardId,
      ...cellToWorldOrigin(col, row),
    }));
  const annotationPositions = moves
    .filter(({ cardId }) => annotationIds.has(cardId))
    .map(({ cardId, col, row }) => ({
      annotation_id: cardId,
      ...cellToWorldOrigin(col, row),
    }));
  return {
    graphCommands: graphCommandsFromCellMovesForDocument(document, moves),
    viewerPositions,
    annotationPositions,
  };
}

export function partitionCellRemovals(
  cardIds: readonly string[],
  pipeIds: readonly string[],
  document: AuthoredGraphDocument,
  artifactViewers: ArtifactViewerCanvasState,
) {
  const cards = new Set(cardIds);
  const pipes = new Set(pipeIds);
  const removedWorkflowNodeIds = document.nodes
    .filter(({ id }) => cards.has(id))
    .map(({ id }) => id);
  const removedViewerIds = artifactViewers.nodes
    .filter(({ id }) => cards.has(id))
    .map(({ id }) => id);
  const removedAnnotationIds = artifactViewers.annotations
    .filter(({ id }) => cards.has(id))
    .map(({ id }) => id);
  const removedViewerEdgeIds = artifactViewers.edges
    .filter(
      ({ id, source, target }) =>
        pipes.has(id) || cards.has(source) || cards.has(target),
    )
    .map(({ id }) => id);
  return {
    graphCommands: graphCommandsFromCellDeleteForDocument(
      document,
      cardIds,
      pipeIds,
    ),
    removedWorkflowNodeIds,
    removedViewerIds,
    removedAnnotationIds,
    removedViewerEdgeIds,
  };
}

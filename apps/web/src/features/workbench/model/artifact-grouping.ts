import type { SavedGraphOrigin } from "@/lib/api";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_INPUT_HANDLE,
  ARTIFACT_VIEWER_NODE_TYPE,
  type ArtifactViewerCanvasState,
  type ArtifactViewerNode,
} from "../canvas/artifact-viewer";
import {
  artifactCardMediaHeight,
  artifactCardValue,
  cardArtifactRefs,
  collectArtifactCardRefs,
  DEFAULT_ARTIFACT_CARD_WIDTH,
  DEFAULT_ARTIFACT_TABLE_CARD_WIDTH,
  DEFAULT_ARTIFACT_TABLE_BODY_HEIGHT,
  isTableArtifact,
  type ArtifactCardValue,
} from "../canvas/artifact-card";
import { createUuid } from "./uuid";

/** Replacing these cards must not remove or reinterpret a saved connection. */
/** A feed from a producer into the card. Collect snapshots that output and drops the feed. */
function isProducerFeed(
  edge: ArtifactViewerCanvasState["edges"][number],
  cardIds: ReadonlySet<string>,
): boolean {
  return (
    edge.type === ARTIFACT_VIEWER_EDGE_TYPE &&
    edge.targetHandle === ARTIFACT_VIEWER_INPUT_HANDLE &&
    cardIds.has(edge.target)
  );
}

export function artifactGroupingDisabledReason({
  cards,
  state,
  origins,
  values,
  allowProducerFeeds = false,
}: {
  cards: readonly ArtifactViewerNode[];
  state: ArtifactViewerCanvasState;
  origins: readonly SavedGraphOrigin[];
  /** Live output of a card that follows a producer, when it has no stored ref. */
  values?: Readonly<Record<string, ArtifactCardValue>>;
  /** Collect snapshots a producer feed. Ungroup leaves that link alone. */
  allowProducerFeeds?: boolean;
}): string | null {
  const ids = new Set(cards.map((card) => card.id));
  const artifactIds = new Set(
    cards.flatMap((card) =>
      cardArtifactRefs(values?.[card.id] ?? card.data.artifactRef).map(
        (ref) => ref.artifact_id,
      ),
    ),
  );
  const linked = state.edges.some((edge) => {
    if (!ids.has(edge.source) && !ids.has(edge.target)) return false;
    if (allowProducerFeeds && isProducerFeed(edge, ids)) return false;
    return true;
  });
  if (
    linked ||
    state.bindings.some(
      (binding) =>
        ids.has(binding.sourceViewerId) || ids.has(binding.targetViewerId),
    ) ||
    origins.some((origin) =>
      cardArtifactRefs(origin.value).some((ref) =>
        artifactIds.has(ref.artifact_id),
      ),
    )
  )
    return "Disconnect these artifacts before grouping or ungrouping.";
  return null;
}

/** Replace the selected, unconnected cards with one ordered sequence. */
export function collectArtifactCards({
  state,
  origins,
  values,
}: {
  state: ArtifactViewerCanvasState;
  origins: readonly SavedGraphOrigin[];
  /** Live output of a card that follows a producer, when it has no stored ref. */
  values?: Readonly<Record<string, ArtifactCardValue>>;
}): ArtifactViewerCanvasState {
  const selected = state.nodes.filter((node) => node.selected);
  if (
    artifactGroupingDisabledReason({
      cards: selected,
      state,
      origins,
      values,
      allowProducerFeeds: true,
    })
  )
    return state;
  const cards = selected.flatMap((node) => {
    const value = values?.[node.id] ?? node.data.artifactRef;
    return value ? [{ position: node.position, value }] : [];
  });
  if (cards.length !== selected.length || cards.length < 1) return state;
  const refs = collectArtifactCardRefs(cards);
  if (!refs) return state;
  const value = artifactCardValue(refs, null, { asSequence: true });
  if (!value) return state;
  const stack: ArtifactViewerNode = {
    id: `artifact-viewer-${createUuid()}`,
    type: ARTIFACT_VIEWER_NODE_TYPE,
    position: {
      x: Math.min(...selected.map((node) => node.position.x)),
      y: Math.min(...selected.map((node) => node.position.y)),
    },
    selected: true,
    data: {
      layout: { width: DEFAULT_ARTIFACT_CARD_WIDTH },
      mode: null,
      artifactRef: value,
    },
  };
  const removed = new Set(selected.map((node) => node.id));
  return {
    ...state,
    nodes: [...state.nodes.filter((node) => !node.selected), stack],
    edges: state.edges.filter(
      (edge) => !removed.has(edge.source) && !removed.has(edge.target),
    ),
  };
}

/** Replace a stack with its individual references, laid out in sequence order. */
export function ungroupArtifactCard({
  state,
  origins,
  nodeId,
}: {
  state: ArtifactViewerCanvasState;
  origins: readonly SavedGraphOrigin[];
  nodeId: string;
}): ArtifactViewerCanvasState {
  const stack = state.nodes.find((node) => node.id === nodeId);
  const value = stack?.data.artifactRef;
  if (
    !stack ||
    !value ||
    !("item_refs" in value) ||
    artifactGroupingDisabledReason({ cards: [stack], state, origins })
  )
    return state;
  if (!value.item_refs.length) return state;
  const table = isTableArtifact(value);
  const width = table
    ? Math.max(
        stack.data.layout?.width ?? DEFAULT_ARTIFACT_TABLE_CARD_WIDTH,
        DEFAULT_ARTIFACT_TABLE_CARD_WIDTH,
      )
    : (stack.data.layout?.width ?? DEFAULT_ARTIFACT_CARD_WIDTH);
  const bodyHeight = table
    ? DEFAULT_ARTIFACT_TABLE_BODY_HEIGHT
    : artifactCardMediaHeight(width);
  const columns = Math.ceil(Math.sqrt(value.item_refs.length));
  const cards = value.item_refs.map((ref, index): ArtifactViewerNode => ({
    id: `artifact-viewer-${createUuid()}`,
    type: ARTIFACT_VIEWER_NODE_TYPE,
    selected: true,
    position: {
      x: stack.position.x + (index % columns) * (Math.max(width, 300) + 64),
      y: stack.position.y + Math.floor(index / columns) * (bodyHeight + 88),
    },
    data: { layout: { width }, mode: null, artifactRef: ref },
  }));
  return {
    ...state,
    nodes: [
      ...state.nodes
        .filter((node) => node.id !== nodeId)
        .map((node) => ({ ...node, selected: false })),
      ...cards,
    ],
  };
}

/** Arrange selected cards in reading order without changing artifact values. */
export function tidyArtifactCards(
  state: ArtifactViewerCanvasState,
): ArtifactViewerCanvasState {
  const selected = state.nodes.filter((node) => node.selected);
  if (selected.length < 2) return state;
  const _ = selected.sort(
    (a, b) => a.position.y - b.position.y || a.position.x - b.position.x,
  );
  const columns = Math.ceil(Math.sqrt(selected.length));
  const left = Math.min(...selected.map((node) => node.position.x));
  const top = Math.min(...selected.map((node) => node.position.y));
  const width = Math.max(
    ...selected.map(
      (node) =>
        node.measured?.width ??
        node.data.layout?.width ??
        DEFAULT_ARTIFACT_CARD_WIDTH,
    ),
  );
  const height = Math.max(
    ...selected.map(
      (node) =>
        node.measured?.height ??
        artifactCardMediaHeight(
          node.data.layout?.width ?? DEFAULT_ARTIFACT_CARD_WIDTH,
        ) + 24,
    ),
  );
  const positions = new Map(
    selected.map((node, index) => [
      node.id,
      {
        x: left + (index % columns) * (width + 64),
        y: top + Math.floor(index / columns) * (height + 64),
      },
    ]),
  );
  return {
    ...state,
    nodes: state.nodes.map((node) => {
      const position = positions.get(node.id);
      return position ? { ...node, position } : node;
    }),
  };
}

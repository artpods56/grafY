import type {
  CellCardInteractionState,
  CellInteractionStore,
  CellMarqueeRect,
  CellPipeInteractionState,
  CellRemotePeerBadge,
  CellRemotePeerState,
  CellSelectionSnapshot,
} from "./cell-contracts";
import {
  cardWorldRect,
  type CellCardModel,
  type CellCoord,
  type RoutedCellPipe,
  type WorldPoint,
} from "./cell-model";

export const EMPTY_REMOTE_BADGES: readonly CellRemotePeerBadge[] =
  Object.freeze([]);

type Listener = () => void;
type ListenerBuckets = Map<string, Set<Listener>>;

function subscribe(listeners: Set<Listener>, listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function subscribeById(
  buckets: ListenerBuckets,
  id: string,
  listener: Listener,
): () => void {
  const listeners = buckets.get(id) ?? new Set<Listener>();
  buckets.set(id, listeners);
  listeners.add(listener);
  return () => {
    if (listeners.delete(listener) && listeners.size === 0) buckets.delete(id);
  };
}

function notify(listeners: Set<Listener> | undefined): void {
  if (!listeners) return;
  for (const listener of [...listeners]) listener();
}

function changedIds(
  before: ReadonlySet<string>,
  after: ReadonlySet<string>,
): string[] {
  const changed: string[] = [];
  for (const id of before) if (!after.has(id)) changed.push(id);
  for (const id of after) if (!before.has(id)) changed.push(id);
  return changed;
}

function selectionIds(
  next: Iterable<string> | undefined,
  previous: ReadonlySet<string>,
) {
  if (next === undefined || next === previous)
    return { ids: previous, changed: [] };
  const ids = new Set(next);
  const changed = changedIds(previous, ids);
  return { ids: changed.length ? ids : previous, changed };
}

function sameBadges(
  before: readonly CellRemotePeerBadge[],
  after: readonly CellRemotePeerBadge[],
): boolean {
  return (
    before === after ||
    (before.length === after.length &&
      before.every((badge, index) => {
        const other = after[index];
        return (
          badge.actorId === other?.actorId &&
          badge.displayName === other.displayName &&
          badge.color === other.color
        );
      }))
  );
}

function sameCell(a: CellCoord | null, b: CellCoord | null): boolean {
  return (
    a === b || (a !== null && b !== null && a.col === b.col && a.row === b.row)
  );
}

interface RemoteCardState {
  badges: CellRemotePeerBadge[];
  dragCell: CellCoord | null;
  dragColor: string | null;
}

function indexRemoteCards(
  peers: readonly CellRemotePeerState[],
): Map<string, RemoteCardState> {
  const cards = new Map<string, RemoteCardState>();
  function stateFor(id: string): RemoteCardState {
    const existing = cards.get(id);
    if (existing) return existing;
    const state: RemoteCardState = {
      badges: [],
      dragCell: null,
      dragColor: null,
    };
    cards.set(id, state);
    return state;
  }

  for (const {
    actorId,
    displayName,
    color,
    selectedCardIds,
    draggingCards,
  } of peers) {
    const badge = { actorId, displayName, color };
    for (const id of new Set(selectedCardIds)) stateFor(id).badges.push(badge);
    for (const [id, cell] of Object.entries(draggingCards)) {
      const state = stateFor(id);
      if (state.dragCell !== null) continue; // The first peer wins a shared drag.
      state.dragCell = { ...cell };
      state.dragColor = color;
    }
  }
  return cards;
}

export function createCellInteractionStore(): CellInteractionStore {
  const cardListeners: ListenerBuckets = new Map();
  const pipeListeners: ListenerBuckets = new Map();
  const selectionListeners = new Set<Listener>();
  const marqueeListeners = new Set<Listener>();
  const remotePeerListeners = new Set<Listener>();
  const activePortListeners = new Set<Listener>();

  const cardStates = new Map<string, CellCardInteractionState>();
  const pipeStates = new Map<string, CellPipeInteractionState>();
  let selection: CellSelectionSnapshot = {
    cardIds: new Set(),
    pipeIds: new Set(),
  };
  let hoveredCard: string | null = null;
  let hoveredPipe: string | null = null;
  let resizingCard: string | null = null;
  let draggingCards = new Set<string>();
  let marquee: CellMarqueeRect | null = null;
  let activePortKey: string | null = null;
  let remotePeers: readonly CellRemotePeerState[] = [];
  let remoteCards = new Map<string, RemoteCardState>();

  function getCardState(id: string): CellCardInteractionState {
    const selected = selection.cardIds.has(id);
    const hovered = hoveredCard === id;
    const dragging = draggingCards.has(id);
    const resizing = resizingCard === id;
    const remote = remoteCards.get(id);
    const badges = remote?.badges.length ? remote.badges : EMPTY_REMOTE_BADGES;
    const remoteDragCell = remote?.dragCell ?? null;
    const remoteDragColor = remote?.dragColor ?? null;
    const previous = cardStates.get(id);
    const remoteSelectedBy =
      previous && sameBadges(previous.remoteSelectedBy, badges)
        ? previous.remoteSelectedBy
        : badges;
    if (
      previous &&
      previous.selected === selected &&
      previous.hovered === hovered &&
      previous.dragging === dragging &&
      previous.resizing === resizing &&
      previous.remoteSelectedBy === remoteSelectedBy &&
      sameCell(previous.remoteDragCell, remoteDragCell) &&
      previous.remoteDragColor === remoteDragColor
    )
      return previous;

    const next = {
      selected,
      hovered,
      dragging,
      resizing,
      remoteSelectedBy,
      remoteDragCell,
      remoteDragColor,
    };
    cardStates.set(id, next);
    return next;
  }

  function setSelection(
    next: Parameters<CellInteractionStore["setSelection"]>[0],
  ): void {
    const cards = selectionIds(next.cardIds, selection.cardIds);
    const pipes = selectionIds(next.pipeIds, selection.pipeIds);
    if (!cards.changed.length && !pipes.changed.length) return;
    selection = { cardIds: cards.ids, pipeIds: pipes.ids };
    for (const id of cards.changed) notify(cardListeners.get(id));
    for (const id of pipes.changed) notify(pipeListeners.get(id));
    notify(selectionListeners);
  }

  return {
    subscribeCard: (id, listener) => subscribeById(cardListeners, id, listener),
    getCardState,
    subscribePipe: (id, listener) => subscribeById(pipeListeners, id, listener),
    getPipeState(id) {
      const selected = selection.pipeIds.has(id);
      const hovered = hoveredPipe === id;
      const previous = pipeStates.get(id);
      if (previous?.selected === selected && previous.hovered === hovered)
        return previous;
      const next = { selected, hovered };
      pipeStates.set(id, next);
      return next;
    },
    subscribeSelection: (listener) => subscribe(selectionListeners, listener),
    getSelection: () => selection,
    subscribeMarquee: (listener) => subscribe(marqueeListeners, listener),
    getMarquee: () => marquee,
    subscribeRemotePeers: (listener) =>
      subscribe(remotePeerListeners, listener),
    getRemotePeers: () => remotePeers,
    subscribeActivePort: (listener) => subscribe(activePortListeners, listener),
    getActivePortKey: () => activePortKey,
    setSelection,
    toggleCardSelection(id) {
      const cardIds = new Set(selection.cardIds);
      if (!cardIds.delete(id)) cardIds.add(id);
      selection = { cardIds, pipeIds: selection.pipeIds };
      notify(cardListeners.get(id));
      notify(selectionListeners);
    },
    clearSelection() {
      setSelection({ cardIds: [], pipeIds: [] });
    },
    setHoveredCard(id) {
      const previous = hoveredCard;
      if (previous === id) return;
      hoveredCard = id;
      if (previous !== null) notify(cardListeners.get(previous));
      if (id !== null) notify(cardListeners.get(id));
    },
    setHoveredPipe(id) {
      const previous = hoveredPipe;
      if (previous === id) return;
      hoveredPipe = id;
      if (previous !== null) notify(pipeListeners.get(previous));
      if (id !== null) notify(pipeListeners.get(id));
    },
    setDraggingCards(ids) {
      const next = new Set(ids);
      const changed = changedIds(draggingCards, next);
      draggingCards = next;
      for (const id of changed) notify(cardListeners.get(id));
    },
    setResizingCard(id) {
      const previous = resizingCard;
      if (previous === id) return;
      resizingCard = id;
      if (previous !== null) notify(cardListeners.get(previous));
      if (id !== null) notify(cardListeners.get(id));
    },
    setMarquee(rect) {
      if (
        marquee === rect ||
        (marquee &&
          rect &&
          marquee.start.x === rect.start.x &&
          marquee.start.y === rect.start.y &&
          marquee.current.x === rect.current.x &&
          marquee.current.y === rect.current.y)
      )
        return;
      marquee = rect;
      notify(marqueeListeners);
    },
    setRemotePeers(peers) {
      if (remotePeers === peers) return;
      const previousCards = remoteCards;
      const changed: string[] = [];
      remotePeers = peers;
      remoteCards = indexRemoteCards(peers);
      for (const id of new Set([
        ...previousCards.keys(),
        ...remoteCards.keys(),
      ])) {
        const previous = previousCards.get(id);
        const next = remoteCards.get(id);
        if (
          previous &&
          next &&
          sameBadges(previous.badges, next.badges) &&
          sameCell(previous.dragCell, next.dragCell) &&
          previous.dragColor === next.dragColor
        ) {
          remoteCards.set(id, previous);
          continue;
        }
        changed.push(id);
      }
      for (const id of changed) notify(cardListeners.get(id));
      notify(remotePeerListeners);
    },
    setActivePortKey(key) {
      if (Object.is(activePortKey, key)) return;
      activePortKey = key;
      notify(activePortListeners);
    },
  };
}

type WorldRect = ReturnType<typeof cardWorldRect>;

export function normalizeMarqueeRect(rect: CellMarqueeRect): WorldRect {
  return {
    x: Math.min(rect.start.x, rect.current.x),
    y: Math.min(rect.start.y, rect.current.y),
    width: Math.abs(rect.start.x - rect.current.x),
    height: Math.abs(rect.start.y - rect.current.y),
  };
}

export function cardsInMarqueeRect(
  cards: readonly CellCardModel[],
  rect: CellMarqueeRect,
  mode: "intersect" | "contain" = "intersect",
): string[] {
  const { x, y, width, height } = normalizeMarqueeRect(rect);
  const right = x + width;
  const bottom = y + height;
  return cards
    .filter((card) => {
      const bounds = cardWorldRect(card);
      const cardRight = bounds.x + bounds.width;
      const cardBottom = bounds.y + bounds.height;
      if (mode === "contain") {
        return (
          x <= bounds.x &&
          y <= bounds.y &&
          cardRight <= right &&
          cardBottom <= bottom
        );
      }
      return (
        x <= cardRight &&
        y <= cardBottom &&
        bounds.x <= right &&
        bounds.y <= bottom
      );
    })
    .map((card) => card.id);
}

function segmentIntersectsRect(
  a: WorldPoint,
  b: WorldPoint,
  rect: WorldRect,
): boolean {
  // Clip the segment's parameter interval to the bounds on each axis.
  let enters = 0;
  let exits = 1;
  for (const axis of ["x", "y"] as const) {
    const low = rect[axis];
    const high = low + (axis === "x" ? rect.width : rect.height);
    const delta = b[axis] - a[axis];
    if (delta === 0) {
      if (a[axis] < low || a[axis] > high) return false;
      continue;
    }
    const t0 = (low - a[axis]) / delta;
    const t1 = (high - a[axis]) / delta;
    enters = Math.max(enters, Math.min(t0, t1));
    exits = Math.min(exits, Math.max(t0, t1));
    if (enters > exits) return false;
  }
  return true;
}

export function pipesInMarqueeRect(
  routedPipes: ReadonlyMap<string, RoutedCellPipe>,
  rect: CellMarqueeRect,
): string[] {
  const bounds = normalizeMarqueeRect(rect);
  const hits: string[] = [];
  for (const [id, { points }] of routedPipes) {
    if (
      points.some((point, index) => {
        const previous = points[index - 1];
        return (
          previous !== undefined &&
          segmentIntersectsRect(previous, point, bounds)
        );
      })
    )
      hits.push(id);
  }
  return hits;
}

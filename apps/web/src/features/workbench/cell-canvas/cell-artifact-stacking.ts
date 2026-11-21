import type { CellCardSurfaceData } from "./cell-contracts";
import {
  CARD_PLATE_BOTTOM_INSET,
  CELL_SIZE,
  cardWorldRect,
  type CellCardModel,
  type WorldPoint,
} from "./cell-model";

/**
 * Where artifact cards offer to become one sequence. Cards laid flush side by
 * side read as one run left to right; stacks laid flush one above the other
 * read as one pile. A one-cell gap is how a person says "keep these apart",
 * so nothing is offered across it. A whole flush run is offered once, with
 * one button under it, never one button per seam.
 */

export type ArtifactMergeOrder = "target-first" | "source-first";

/** Whether `source` may join `target`'s sequence. */
export type CanMergeArtifactCards = (
  sourceCardId: string,
  targetCardId: string,
) => boolean;

export interface ArtifactMergeSuggestion {
  /** The run's card ids joined, in visual order. */
  id: string;
  axis: "horizontal" | "vertical";
  /** Left to right, or top to bottom. */
  cardIds: readonly string[];
  /** The card that keeps the sequence; every other card goes into it. */
  targetCardId: string;
  /** Items across the whole run. */
  itemCount: number;
  /** The run's shared box, in cells. */
  bounds: { col: number; row: number; widthCells: number; heightCells: number };
  /**
   * Under the middle of the run, on the plates' bottom edge, so the button
   * covers no picture and no card's floating header.
   */
  anchor: WorldPoint;
}

/** How many artifacts an artifact card holds, or null for any other card. */
export function artifactCardItemCount(
  surface: CellCardSurfaceData | undefined,
): number | null {
  if (surface?.kind !== "artifact") return null;
  return surface.itemCount ?? 1;
}

function rangesOverlap(
  aStart: number,
  aLength: number,
  bStart: number,
  bLength: number,
): boolean {
  return aStart < bStart + bLength && bStart < aStart + aLength;
}

function runBounds(
  run: readonly CellCardModel[],
): ArtifactMergeSuggestion["bounds"] {
  let col = Infinity;
  let row = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const card of run) {
    col = Math.min(col, card.col);
    row = Math.min(row, card.row);
    right = Math.max(right, card.col + card.widthCells);
    bottom = Math.max(bottom, card.row + card.heightCells);
  }
  return { col, row, widthCells: right - col, heightCells: bottom - row };
}

/**
 * The card every other card of `run` may go into: the first when it can,
 * otherwise the one card that can take all the rest (a wired card stays).
 */
function runTarget(
  run: readonly CellCardModel[],
  canMerge: CanMergeArtifactCards,
): string | null {
  for (const candidate of run) {
    const takesAll = run.every(
      (other) => other.id === candidate.id || canMerge(other.id, candidate.id),
    );
    if (takesAll) return candidate.id;
  }
  return null;
}

type Axis = ArtifactMergeSuggestion["axis"];

/** The card flush after `card` along `axis`, if any. */
function flushNext(
  card: CellCardModel,
  others: readonly CellCardModel[],
  axis: Axis,
): CellCardModel | null {
  let best: CellCardModel | null = null;
  let bestOffset = Infinity;
  for (const other of others) {
    if (other.id === card.id) continue;
    const flush =
      axis === "horizontal"
        ? other.col === card.col + card.widthCells &&
          rangesOverlap(
            card.row,
            card.heightCells,
            other.row,
            other.heightCells,
          )
        : other.row === card.row + card.heightCells &&
          rangesOverlap(card.col, card.widthCells, other.col, other.widthCells);
    if (!flush) continue;
    // Of several flush neighbours, the one most squarely beside this card.
    const offset =
      axis === "horizontal"
        ? Math.abs(other.row - card.row)
        : Math.abs(other.col - card.col);
    if (offset < bestOffset) {
      best = other;
      bestOffset = offset;
    }
  }
  return best;
}

/** Maximal flush chains along `axis`, each card in at most one chain. */
function flushChains(
  cards: readonly CellCardModel[],
  axis: Axis,
): CellCardModel[][] {
  const next = new Map<string, CellCardModel>();
  const claimed = new Set<string>();
  for (const card of cards) {
    const candidate = flushNext(card, cards, axis);
    if (!candidate || claimed.has(candidate.id)) continue;
    claimed.add(candidate.id);
    next.set(card.id, candidate);
  }
  const chains: CellCardModel[][] = [];
  for (const card of cards) {
    if (claimed.has(card.id) || !next.has(card.id)) continue;
    const chain = [card];
    let current = next.get(card.id);
    while (current && !chain.includes(current)) {
      chain.push(current);
      current = next.get(current.id);
    }
    chains.push(chain);
  }
  return chains;
}

/**
 * A chain cut into the longest runs that each have one card to merge into,
 * left to right. Two wired cards that cannot meet end up in separate runs.
 */
function mergeableRuns(
  chain: readonly CellCardModel[],
  canMerge: CanMergeArtifactCards,
): { run: CellCardModel[]; targetCardId: string }[] {
  const runs: { run: CellCardModel[]; targetCardId: string }[] = [];
  let start = 0;
  while (start < chain.length - 1) {
    let found: { run: CellCardModel[]; targetCardId: string } | null = null;
    for (let end = chain.length; end >= start + 2; end -= 1) {
      const run = chain.slice(start, end);
      const targetCardId = runTarget(run, canMerge);
      if (targetCardId) {
        found = { run, targetCardId };
        break;
      }
    }
    if (found) {
      runs.push(found);
      start += found.run.length;
    } else {
      start += 1;
    }
  }
  return runs;
}

export function findArtifactMergeSuggestions(
  cards: readonly CellCardModel[],
  surfaces: Readonly<Record<string, CellCardSurfaceData>>,
  canMerge: CanMergeArtifactCards,
): ArtifactMergeSuggestion[] {
  const artifacts = cards.filter(
    (card) => artifactCardItemCount(surfaces[card.id]) !== null,
  );
  const countOf = (card: CellCardModel) =>
    artifactCardItemCount(surfaces[card.id]) ?? 1;
  const suggestions: ArtifactMergeSuggestion[] = [];
  const used = new Set<string>();

  const offer = (axis: Axis, run: CellCardModel[], targetCardId: string) => {
    const bounds = runBounds(run);
    for (const card of run) used.add(card.id);
    suggestions.push({
      id: run.map((card) => card.id).join("|"),
      axis,
      cardIds: run.map((card) => card.id),
      targetCardId,
      itemCount: run.reduce((sum, card) => sum + countOf(card), 0),
      bounds,
      anchor: {
        x: (bounds.col + bounds.widthCells / 2) * CELL_SIZE,
        y:
          (bounds.row + bounds.heightCells) * CELL_SIZE -
          CARD_PLATE_BOTTOM_INSET,
      },
    });
  };

  for (const chain of flushChains(artifacts, "horizontal")) {
    for (const { run, targetCardId } of mergeableRuns(chain, canMerge)) {
      offer("horizontal", run, targetCardId);
    }
  }
  // A card already offered side by side is not offered again in a column.
  const free = artifacts.filter((card) => !used.has(card.id));
  for (const chain of flushChains(free, "vertical")) {
    for (const { run, targetCardId } of mergeableRuns(chain, canMerge)) {
      // Two single cards one above the other are two cards, not a pile.
      if (!run.some((card) => countOf(card) > 1)) continue;
      offer("vertical", run, targetCardId);
    }
  }
  return suggestions;
}

// --- The spread ------------------------------------------------------------

/** How far the free corridor is scanned when nothing stands in the way. */
export const MAX_FREE_SCAN_COLS = 120;
/** Card slots a windowed spread opens by default when the viewport is unknown. */
const DEFAULT_WINDOWED_SLOTS = 4;

export type SequenceSpreadLayout =
  | { canExpand: false }
  | {
      canExpand: true;
      /** End slots hold stacked items whenever fewer slots than items are open. */
      windowed: boolean;
      /** Always the collapsed card's own column: spreads strictly rightward. */
      startCol: number;
      row: number;
      /** Exact card-width multiple: `visibleCount * card.widthCells`. */
      totalCols: number;
      heightCells: number;
      /** Number of card slots laid open (`[1][2][3][4*]`). */
      visibleCount: number;
      minVisibleCount: number;
      maxVisibleCount: number;
    };

export type OpenSequenceSpreadLayout = Extract<
  SequenceSpreadLayout,
  { canExpand: true }
>;

export interface SpreadInsertTarget {
  spreadCardId: string;
  /** Gap among the visible slots (0 before slot 0, visibleCount after the last). */
  slot: number;
  /**
   * Sequence index to insert the dropped card at: `windowStart + slot`, except
   * the outer edge of a side stack, which means the sequence's start or end.
   */
  insertIndex: number;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/**
 * Where a sequence card lays its items open in place: always starting at
 * `card.col` and expanding strictly rightward in whole card widths
 * (`visibleCount * card.widthCells`). When fewer slots than items fit, the
 * outer slots double as left/right stacks whenever they hold 2+ items
 * (`[1][2][3][4*]` -> `[2*][3][4][5*]` -> `[3*][4][5][6]`), so there are
 * never empty dock boxes and the frame width stays fixed while paging.
 */
export function computeSequenceSpreadLayout({
  card,
  itemCount,
  foregroundCards,
  viewportWorldWidth,
  preferredVisibleCount,
}: {
  card: CellCardModel;
  itemCount: number;
  foregroundCards: readonly CellCardModel[];
  viewportWorldWidth?: number;
  preferredVisibleCount?: number;
}): SequenceSpreadLayout {
  const w = card.widthCells;
  const h = card.heightCells;
  const minVisibleCount = itemCount <= 2 ? 2 : 3;
  if (itemCount < 2 || w <= 0) return { canExpand: false };

  let freeRightCols = MAX_FREE_SCAN_COLS;
  for (const other of foregroundCards) {
    if (other.id === card.id) continue;
    if (!rangesOverlap(card.row, h, other.row, other.heightCells)) continue;
    if (other.col >= card.col + w) {
      freeRightCols = Math.min(freeRightCols, other.col - (card.col + w));
    }
  }

  const maxFitSlots = Math.floor((w + freeRightCols) / w);
  if (maxFitSlots < minVisibleCount) return { canExpand: false };

  const maxVisibleCount = Math.min(itemCount, maxFitSlots);
  const viewportSlots =
    viewportWorldWidth !== undefined
      ? Math.floor((viewportWorldWidth * 0.85) / (w * CELL_SIZE))
      : undefined;

  let defaultSlots: number;
  if (viewportSlots !== undefined) {
    const comfortCap =
      itemCount <= 5 && viewportSlots >= itemCount ? itemCount : 4;
    defaultSlots = clamp(
      viewportSlots,
      minVisibleCount,
      Math.min(comfortCap, maxVisibleCount),
    );
  } else {
    defaultSlots =
      itemCount <= 5
        ? Math.min(itemCount, maxVisibleCount)
        : Math.min(DEFAULT_WINDOWED_SLOTS, maxVisibleCount);
  }

  const visibleCount = clamp(
    preferredVisibleCount ?? defaultSlots,
    minVisibleCount,
    maxVisibleCount,
  );

  return {
    canExpand: true,
    windowed: visibleCount < itemCount,
    startCol: card.col,
    row: card.row,
    totalCols: visibleCount * w,
    heightCells: h,
    visibleCount,
    minVisibleCount,
    maxVisibleCount,
  };
}

/**
 * Where a compatible card dragged from the canvas lands inside an open spread,
 * or null when the pointer is outside the spread's frame.
 */
export function findSpreadInsertTarget({
  spreadCardId,
  layout,
  windowStart,
  itemCount,
  cardWidthCells,
  point,
  outsetPx = 6,
}: {
  spreadCardId: string;
  layout: OpenSequenceSpreadLayout;
  windowStart: number;
  /** Items in the open sequence, to tell a side stack's outer edge. */
  itemCount: number;
  cardWidthCells: number;
  point: WorldPoint;
  outsetPx?: number;
}): SpreadInsertTarget | null {
  const left = layout.startCol * CELL_SIZE - outsetPx;
  const right = (layout.startCol + layout.totalCols) * CELL_SIZE + outsetPx;
  const top = layout.row * CELL_SIZE - outsetPx;
  const bottom = (layout.row + layout.heightCells) * CELL_SIZE + outsetPx;
  if (point.x < left || point.x > right || point.y < top || point.y > bottom) {
    return null;
  }
  let slot = 0;
  for (let s = 0; s < layout.visibleCount; s += 1) {
    const middle = (layout.startCol + (s + 0.5) * cardWidthCells) * CELL_SIZE;
    if (point.x > middle) slot += 1;
  }
  // The outer edge of a side stack is past every card that stack holds, so it
  // means the sequence's own start or end, never the middle of the stack.
  const maxStart = Math.max(0, itemCount - layout.visibleCount);
  const start = layout.windowed ? clamp(windowStart, 0, maxStart) : 0;
  let insertIndex = start + slot;
  if (slot === 0 && start > 0) insertIndex = 0;
  if (slot === layout.visibleCount && start < maxStart) insertIndex = itemCount;
  return { spreadCardId, slot, insertIndex };
}

/**
 * The artifact card under the pointer that a dragged card may be dropped
 * into, or null.
 */
export function findArtifactMergeTarget(
  cards: readonly CellCardModel[],
  surfaces: Readonly<Record<string, CellCardSurfaceData>>,
  draggedCardId: string,
  point: WorldPoint,
  canMerge: CanMergeArtifactCards,
): string | null {
  if (artifactCardItemCount(surfaces[draggedCardId]) === null) return null;
  for (const card of cards) {
    if (card.id === draggedCardId) continue;
    if (artifactCardItemCount(surfaces[card.id]) === null) continue;
    const rect = cardWorldRect(card);
    const inside =
      point.x >= rect.x &&
      point.x < rect.x + rect.width &&
      point.y >= rect.y &&
      point.y < rect.y + rect.height;
    if (inside && canMerge(draggedCardId, card.id)) return card.id;
  }
  return null;
}

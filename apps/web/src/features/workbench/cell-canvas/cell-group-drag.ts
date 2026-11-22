import type { CellResizeCommit, CellResizeEdge } from "./cell-contracts";
import {
  ARTIFACT_CARD_OUTPUT_PORT_ID,
  CELL_SIZE,
  cellToWorldOrigin,
  type CellCardModel,
  type CellCoord,
  type CellGraph,
  type CellPipeModel,
  type CellRect,
  type WorldPoint,
} from "./cell-model";
import { magneticTugOffset, snapCellWithHysteresis } from "./cell-transitions";

export interface GroupDragSession {
  anchorCardId: string;
  movingCardIds: ReadonlySet<string>;
  initialCells: ReadonlyMap<string, CellCoord>;
  anchorInitialCell: CellCoord;
  grabOffsetWorld: WorldPoint;
  currentDelta: CellCoord;
}

function normalizeZero(value: number): number {
  return value === 0 ? 0 : value;
}

export function createGroupDragSession(
  cards: readonly CellCardModel[],
  selectedCardIds: ReadonlySet<string>,
  anchorCardId: string,
  startPointerWorld: WorldPoint,
): GroupDragSession {
  const candidates = selectedCardIds.has(anchorCardId)
    ? selectedCardIds
    : new Set([anchorCardId]);
  const initialCells = new Map<string, CellCoord>();
  for (const { id, col, row } of cards) {
    if (candidates.has(id)) initialCells.set(id, { col, row });
  }

  const anchorInitialCell = initialCells.get(anchorCardId);
  if (!anchorInitialCell)
    throw new Error(`Missing drag anchor card: ${anchorCardId}`);
  const origin = cellToWorldOrigin(
    anchorInitialCell.col,
    anchorInitialCell.row,
  );
  return {
    anchorCardId,
    movingCardIds: new Set(initialCells.keys()),
    initialCells,
    anchorInitialCell,
    grabOffsetWorld: {
      x: startPointerWorld.x - origin.x,
      y: startPointerWorld.y - origin.y,
    },
    currentDelta: { col: 0, row: 0 },
  };
}

export function updateGroupDragSession(
  session: GroupDragSession,
  cards: readonly CellCardModel[],
  pointerWorld: WorldPoint,
): {
  session: GroupDragSession;
  snappedDelta: CellCoord;
  visualOffset: WorldPoint;
  changedCell: boolean;
  movedCards: CellCardModel[];
} {
  const { anchorInitialCell, currentDelta, grabOffsetWorld } = session;
  const anchorRawOrigin = {
    x: pointerWorld.x - grabOffsetWorld.x,
    y: pointerWorld.y - grabOffsetWorld.y,
  };
  const snappedAnchor = snapCellWithHysteresis(anchorRawOrigin, {
    col: anchorInitialCell.col + currentDelta.col,
    row: anchorInitialCell.row + currentDelta.row,
  });
  const snappedDelta = {
    col: normalizeZero(snappedAnchor.col - anchorInitialCell.col),
    row: normalizeZero(snappedAnchor.row - anchorInitialCell.row),
  };
  const changedCell =
    snappedDelta.col !== currentDelta.col ||
    snappedDelta.row !== currentDelta.row;
  const movedCards = cards.map((card) => {
    if (!session.movingCardIds.has(card.id)) return card;
    const initial = session.initialCells.get(card.id);
    if (!initial) return card;
    const col = initial.col + snappedDelta.col;
    const row = initial.row + snappedDelta.row;
    return col === card.col && row === card.row ? card : { ...card, col, row };
  });
  return {
    session: changedCell ? { ...session, currentDelta: snappedDelta } : session,
    snappedDelta,
    visualOffset: magneticTugOffset(anchorRawOrigin, snappedAnchor),
    changedCell,
    movedCards,
  };
}

function pipeWellKeys(pipe: CellPipeModel): [string, string] {
  return [
    `${pipe.sourceCardId}:${pipe.sourcePortId}`,
    `${pipe.targetCardId}:${pipe.targetPortId}`,
  ];
}

export function partitionSceneForMovingCards(
  graph: CellGraph,
  movingCardIds: ReadonlySet<string>,
): {
  restingPipes: CellPipeModel[];
  movingPipes: CellPipeModel[];
  attachedPipeIds: Set<string>;
  restingWellKeys: Set<string>;
  movingWellKeys: Set<string>;
} {
  const restingPipes: CellPipeModel[] = [];
  const movingPipes: CellPipeModel[] = [];
  const attachedPipeIds = new Set<string>();
  const restingWellKeys = new Set<string>();
  const movingWellKeys = new Set<string>();
  for (const pipe of graph.pipes) {
    if (
      movingCardIds.has(pipe.sourceCardId) ||
      movingCardIds.has(pipe.targetCardId)
    ) {
      movingPipes.push(pipe);
      attachedPipeIds.add(pipe.id);
    } else {
      restingPipes.push(pipe);
      for (const key of pipeWellKeys(pipe)) restingWellKeys.add(key);
    }
  }
  for (const pipe of movingPipes) {
    for (const key of pipeWellKeys(pipe)) {
      if (!restingWellKeys.has(key)) movingWellKeys.add(key);
    }
  }
  return {
    restingPipes,
    movingPipes,
    attachedPipeIds,
    restingWellKeys,
    movingWellKeys,
  };
}

export function rectsOverlap(a: CellRect, b: CellRect): boolean {
  return (
    Math.max(a.col, b.col) <
      Math.min(a.col + a.widthCells, b.col + b.widthCells) &&
    Math.max(a.row, b.row) <
      Math.min(a.row + a.heightCells, b.row + b.heightCells)
  );
}

export function hasCardOverlap(cards: readonly CellCardModel[]): boolean {
  for (const [index, card] of cards.entries()) {
    for (
      let otherIndex = index + 1;
      otherIndex < cards.length;
      otherIndex += 1
    ) {
      const other = cards[otherIndex];
      if (other && rectsOverlap(card, other)) return true;
    }
  }
  return false;
}

export function resolveNonOverlappingDelta(
  cards: readonly CellCardModel[],
  movingCardIds: ReadonlySet<string>,
  proposedDelta: CellCoord,
  maxSearchRadius = 48,
): CellCoord {
  const moving: CellCardModel[] = [];
  const stationary: CellCardModel[] = [];
  for (const card of cards) {
    (movingCardIds.has(card.id) ? moving : stationary).push(card);
  }

  function canPlace(col: number, row: number): boolean {
    return moving.every((card) => {
      const shifted = {
        col: card.col + col,
        row: card.row + row,
        widthCells: card.widthCells,
        heightCells: card.heightCells,
      };
      return !stationary.some((other) => rectsOverlap(shifted, other));
    });
  }

  const col = normalizeZero(proposedDelta.col);
  const row = normalizeZero(proposedDelta.row);
  if (canPlace(col, row)) return { col, row };

  // Visit each Manhattan ring in row order, trying the left candidate first.
  for (let distance = 1; distance <= maxSearchRadius; distance += 1) {
    for (let dy = -distance; dy <= distance; dy += 1) {
      const dx = distance - Math.abs(dy);
      const candidateRow = row + dy;
      if (canPlace(col - dx, candidateRow))
        return { col: col - dx, row: candidateRow };
      if (dx !== 0 && canPlace(col + dx, candidateRow)) {
        return { col: col + dx, row: candidateRow };
      }
    }
  }
  // Keep the original positions when there is no valid placement in range.
  return { col: 0, row: 0 };
}

export function minCardHeightCellsForPorts(
  card: Pick<CellCardModel, "ports">,
): number {
  return card.ports.reduce(
    // A fixed port's row, then a row the plate's bottom inset may take.
    // An artifact card's corner output moves with the bottom edge, so it
    // never pins the card's minimum height to its current height.
    (height, port) =>
      port.id === ARTIFACT_CARD_OUTPUT_PORT_ID
        ? height
        : Math.max(height, port.rowOffset + 2),
    0,
  );
}

export function computeCellResize(
  card: CellCardModel,
  edge: CellResizeEdge,
  startPointerWorld: WorldPoint,
  currentPointerWorld: WorldPoint,
): CellResizeCommit {
  const bounds = card.resizeBounds;
  let { widthCells, heightCells } = card;
  if (edge === "e" || edge === "se") {
    const delta = Math.round(
      (currentPointerWorld.x - startPointerWorld.x) / CELL_SIZE,
    );
    widthCells = Math.max(
      bounds?.minWidthCells ?? 6,
      Math.min(bounds?.maxWidthCells ?? 80, widthCells + delta),
    );
  }
  if (edge === "s" || edge === "se") {
    const delta = Math.round(
      (currentPointerWorld.y - startPointerWorld.y) / CELL_SIZE,
    );
    const minHeight = Math.max(
      minCardHeightCellsForPorts(card),
      bounds?.minHeightCells ?? 4,
    );
    heightCells = Math.max(
      minHeight,
      Math.min(bounds?.maxHeightCells ?? 80, heightCells + delta),
    );
  }
  return { cardId: card.id, widthCells, heightCells };
}

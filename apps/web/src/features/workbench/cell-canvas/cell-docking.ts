import type { CellDockedJoin } from "./cell-contracts";
import {
  CELL_SIZE,
  type CellCardModel,
  type CellCoord,
  type CellGraph,
  type CellPipeModel,
  type CellPort,
  type CellRect,
} from "./cell-model";

function pipeEndpoints(
  pipe: CellPipeModel,
  cardsById: ReadonlyMap<string, CellCardModel>,
) {
  const sourceCard = cardsById.get(pipe.sourceCardId);
  const targetCard = cardsById.get(pipe.targetCardId);
  if (!sourceCard || !targetCard) return null;

  const sourcePort = sourceCard.ports.find(
    (port) => port.id === pipe.sourcePortId,
  );
  const targetPort = targetCard.ports.find(
    (port) => port.id === pipe.targetPortId,
  );
  if (sourcePort?.direction !== "output" || targetPort?.direction !== "input") {
    return null;
  }
  return { sourceCard, sourcePort, targetCard, targetPort };
}

export function isPortPairDocked(
  sourceCard: CellCardModel,
  sourcePort: CellPort,
  targetCard: CellCardModel,
  targetPort: CellPort,
): boolean {
  return (
    sourcePort.direction === "output" &&
    targetPort.direction === "input" &&
    sourceCard.col + sourceCard.widthCells === targetCard.col &&
    sourceCard.row + sourcePort.rowOffset ===
      targetCard.row + targetPort.rowOffset
  );
}

export function detectCellDockedJoins(
  graph: CellGraph,
  resolveColor: (artifactTypeId: string) => string,
): {
  dockedJoins: CellDockedJoin[];
  routablePipes: CellPipeModel[];
  dockedPipeIds: Set<string>;
} {
  const cardsById = new Map(graph.cards.map((card) => [card.id, card]));
  const dockedJoins: CellDockedJoin[] = [];
  const routablePipes: CellPipeModel[] = [];
  const dockedPipeIds = new Set<string>();

  for (const pipe of graph.pipes) {
    const ends = pipeEndpoints(pipe, cardsById);
    if (
      !ends ||
      !isPortPairDocked(
        ends.sourceCard,
        ends.sourcePort,
        ends.targetCard,
        ends.targetPort,
      )
    ) {
      routablePipes.push(pipe);
      continue;
    }

    const { sourceCard, sourcePort, targetCard, targetPort } = ends;
    const seamCol = targetCard.col;
    const row = sourceCard.row + sourcePort.rowOffset;
    dockedPipeIds.add(pipe.id);
    dockedJoins.push({
      pipeId: pipe.id,
      sourceCardId: pipe.sourceCardId,
      sourcePortId: pipe.sourcePortId,
      targetCardId: pipe.targetCardId,
      targetPortId: pipe.targetPortId,
      seamCol,
      row,
      seamPoint: { x: seamCol * CELL_SIZE, y: (row + 0.5) * CELL_SIZE },
      color: resolveColor(sourcePort.artifactTypeId),
      sequence: sourcePort.shape === "many" || targetPort.shape === "many",
      enabled: pipe.enabled ?? true,
      projectionLabel: pipe.projectionLabel ?? null,
      conversionLabel: pipe.conversionLabel ?? null,
    });
  }

  return { dockedJoins, routablePipes, dockedPipeIds };
}

function overlaps(a: CellRect, b: CellRect): boolean {
  return (
    a.col < b.col + b.widthCells &&
    a.col + a.widthCells > b.col &&
    a.row < b.row + b.heightCells &&
    a.row + a.heightCells > b.row
  );
}

interface DockSnapCandidate extends CellCoord {
  matchedPipeIds: string[];
}

export function findDockSnapCandidate(
  draggedCard: CellCardModel,
  stationaryCards: readonly CellCardModel[],
  pipes: readonly CellPipeModel[],
  thresholdCells = 1,
): DockSnapCandidate | null {
  const cardsById = new Map(stationaryCards.map((card) => [card.id, card]));
  cardsById.set(draggedCard.id, draggedCard);

  let best: DockSnapCandidate | null = null;
  let bestDistance = Infinity;
  let bestManhattanDistance = Infinity;
  for (const pipe of pipes) {
    const draggingSource = pipe.sourceCardId === draggedCard.id;
    const draggingTarget = pipe.targetCardId === draggedCard.id;
    if (draggingSource === draggingTarget) continue;

    const ends = pipeEndpoints(pipe, cardsById);
    if (!ends) continue;
    const { sourceCard, sourcePort, targetCard, targetPort } = ends;
    const col = draggingSource
      ? targetCard.col - draggedCard.widthCells
      : sourceCard.col + sourceCard.widthCells;
    const row = draggingSource
      ? targetCard.row + targetPort.rowOffset - sourcePort.rowOffset
      : sourceCard.row + sourcePort.rowOffset - targetPort.rowOffset;

    if (best && best.col === col && best.row === row) {
      best.matchedPipeIds.push(pipe.id);
      continue;
    }
    const columns = Math.abs(col - draggedCard.col);
    const rows = Math.abs(row - draggedCard.row);
    const distance = Math.max(columns, rows);
    const manhattanDistance = columns + rows;
    if (distance > thresholdCells || distance > bestDistance) continue;
    if (distance === bestDistance && manhattanDistance >= bestManhattanDistance)
      continue;

    const placement = {
      widthCells: draggedCard.widthCells,
      heightCells: draggedCard.heightCells,
      col,
      row,
    };
    if (stationaryCards.some((card) => overlaps(placement, card))) continue;
    best = { col, row, matchedPipeIds: [pipe.id] };
    bestDistance = distance;
    bestManhattanDistance = manhattanDistance;
  }
  return best;
}

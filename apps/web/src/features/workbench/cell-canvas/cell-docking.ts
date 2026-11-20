import type { CellDockedJoin } from "./cell-contracts";
import {
  CELL_SIZE,
  type CellCardModel,
  type CellGraph,
  type CellPipeModel,
  type CellPort,
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

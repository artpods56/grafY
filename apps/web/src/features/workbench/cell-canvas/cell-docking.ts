import type { CellDockedJoin } from "./cell-contracts";
import {
  CELL_SIZE,
  type CellCardModel,
  type CellGraph,
  type CellPipeModel,
  type CellPort,
  punchedPortCardCentre,
  findPipeEndPort,
} from "./cell-model";

function pipeEndpoints(
  pipe: CellPipeModel,
  cardsById: ReadonlyMap<string, CellCardModel>,
) {
  const sourceCard = cardsById.get(pipe.sourceCardId);
  const targetCard = cardsById.get(pipe.targetCardId);
  if (!sourceCard || !targetCard) return null;

  const sourcePort = findPipeEndPort(
    sourceCard.ports,
    pipe.sourcePortId,
    "output",
  );
  const targetPort = findPipeEndPort(
    targetCard.ports,
    pipe.targetPortId,
    "input",
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

/**
 * A punched hole off its row's midline, as the artifact card's corner output
 * is: a flush seam bridges midline to midline, so it cannot dock there and the
 * pipe routes into the hole instead.
 */
function isPunchedOffMidline(card: CellCardModel, port: CellPort): boolean {
  const midline = (port.rowOffset + 0.5) * CELL_SIZE;
  return Math.abs(punchedPortCardCentre(card, port).y - midline) >= 0.5;
}

export function detectCellDockedJoins(
  graph: CellGraph,
  resolveColor: (artifactTypeId: string, port?: CellPort) => string,
  { punched = false }: { punched?: boolean } = {},
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
      ) ||
      (punched &&
        (isPunchedOffMidline(ends.sourceCard, ends.sourcePort) ||
          isPunchedOffMidline(ends.targetCard, ends.targetPort)))
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
      color: resolveColor(sourcePort.artifactTypeId, sourcePort),
      sequence: sourcePort.shape === "many" || targetPort.shape === "many",
      enabled: pipe.enabled ?? true,
      projectionLabel: pipe.projectionLabel ?? null,
      conversionLabel: pipe.conversionLabel ?? null,
    });
  }

  return { dockedJoins, routablePipes, dockedPipeIds };
}

import type { CellDockedJoin, CellPipeAttachment } from "./cell-contracts";
import {
  CELL_SIZE,
  cardWorldRect,
  type CellCardModel,
  type CellPipeModel,
  type CellPort,
  type RoutedCellPipe,
  type WorldPoint,
  findPipeEndPort,
} from "./cell-model";

/** A 150 × 25 box: the 24px capsule with a pixel to spare. */
export const ATTACHMENT_WIDTH_CELLS = 6;
export const ATTACHMENT_HEIGHT_CELLS = 1;
export const ATTACHMENT_WIDTH_PX = ATTACHMENT_WIDTH_CELLS * CELL_SIZE;
export const ATTACHMENT_HEIGHT_PX = ATTACHMENT_HEIGHT_CELLS * CELL_SIZE;

const MIN_LONG_SEGMENT = 140;
const PORT_CLEARANCE = 1.5 * CELL_SIZE;
const CARD_PENALTY = 10_000;
const PORT_PENALTY = 5_000;
const HALF_WIDTH = ATTACHMENT_WIDTH_PX / 2;
const HALF_HEIGHT = ATTACHMENT_HEIGHT_PX / 2;

type WorldRect = ReturnType<typeof cardWorldRect>;

interface SegmentCandidate {
  anchor: WorldPoint;
  start: WorldPoint;
  direction: WorldPoint;
  length: number;
  distanceFromStart: number;
  orientation: CellPipeAttachment["segmentOrientation"];
}

function attachmentRect(anchor: WorldPoint): WorldRect {
  return {
    x: anchor.x - HALF_WIDTH,
    y: anchor.y - HALF_HEIGHT,
    width: ATTACHMENT_WIDTH_PX,
    height: ATTACHMENT_HEIGHT_PX,
  };
}

function overlaps(a: WorldRect, b: WorldRect): boolean {
  return (
    a.x < b.x + b.width &&
    a.x + a.width > b.x &&
    a.y < b.y + b.height &&
    a.y + a.height > b.y
  );
}

function nearPort(anchor: WorldPoint, port: WorldPoint): boolean {
  const dx = Math.max(0, Math.abs(anchor.x - port.x) - HALF_WIDTH);
  const dy = Math.max(0, Math.abs(anchor.y - port.y) - HALF_HEIGHT);
  return Math.hypot(dx, dy) < PORT_CLEARANCE;
}

function placementPenalty(
  anchor: WorldPoint,
  cards: readonly WorldRect[],
  ports: readonly WorldPoint[],
): number {
  const box = attachmentRect(anchor);
  let penalty = 0;
  for (const card of cards) {
    if (overlaps(box, card)) penalty += CARD_PENALTY;
  }
  for (const port of ports) {
    if (nearPort(anchor, port)) penalty += PORT_PENALTY;
  }
  return penalty;
}

function bestSegmentCandidate(
  points: readonly WorldPoint[],
  cards: readonly WorldRect[],
  ports: readonly WorldPoint[],
): SegmentCandidate | null {
  let best: SegmentCandidate | null = null;
  let bestScore = -Infinity;
  for (const [index, start] of points.entries()) {
    const end = points[index + 1];
    if (!end) break;

    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const length = Math.hypot(dx, dy);
    if (length === 0) continue;

    const orientation =
      Math.abs(dx) >= Math.abs(dy) ? "horizontal" : "vertical";
    const long = length >= MIN_LONG_SEGMENT;
    const horizontalBonus = long && orientation === "horizontal" ? 1 : 0;
    // Keep the length score bounded so even a very long run favors clearance.
    const segmentScore =
      horizontalBonus + length / (length + ATTACHMENT_WIDTH_PX);
    for (const fraction of long ? [0.5, 0.25, 0.75] : [0.5]) {
      const anchor = { x: start.x + dx * fraction, y: start.y + dy * fraction };
      const score = segmentScore - placementPenalty(anchor, cards, ports);
      if (score <= bestScore) continue;
      bestScore = score;
      best = {
        anchor,
        start,
        direction: { x: dx / length, y: dy / length },
        length,
        distanceFromStart: length * fraction,
        orientation,
      };
    }
  }
  return best;
}

function staggerAnchor(
  candidate: SegmentCandidate,
  cards: readonly WorldRect[],
  ports: readonly WorldPoint[],
  occupied: readonly WorldRect[],
): WorldPoint {
  const overlapsPill = (anchor: WorldPoint) => {
    const box = attachmentRect(anchor);
    return occupied.some((other) => overlaps(box, other));
  };
  if (!overlapsPill(candidate.anchor)) return candidate.anchor;

  const { start, direction, length, distanceFromStart } = candidate;
  const nudges = [
    { along: 40, across: 0 },
    { along: 75, across: 0 },
    { along: 0, across: 28 },
    { along: 0, across: 2 * CELL_SIZE },
  ];
  for (const { along, across } of nudges) {
    for (const sign of [1, -1]) {
      const distance = Math.max(
        0,
        Math.min(length, distanceFromStart + sign * along),
      );
      const anchor = {
        x: start.x + direction.x * distance - direction.y * sign * across,
        y: start.y + direction.y * distance + direction.x * sign * across,
      };
      if (
        !overlapsPill(anchor) &&
        placementPenalty(anchor, cards, ports) === 0
      ) {
        return anchor;
      }
    }
  }
  return candidate.anchor;
}

function pipeAttachmentLabel(pipe: CellPipeModel): string {
  if (pipe.incompatible) return "Incompatible";
  if (pipe.projectionLabel) {
    return pipe.collectionMode === "map"
      ? `map · ${pipe.projectionLabel}`
      : pipe.projectionLabel;
  }
  if (pipe.collectionMode === "map") return "each item";
  if (pipe.conversionLabel) return pipe.conversionLabel;
  if (pipe.enabled === false) return "Disabled";
  return pipe.sourcePortLabel ?? "";
}

export function solvePipeAttachmentAnchors({
  cards,
  pipes,
  routedPipes,
  dockedJoins,
  resolveColor,
  includeAll,
  activePipeIds,
}: {
  cards: readonly CellCardModel[];
  pipes: readonly CellPipeModel[];
  routedPipes: ReadonlyMap<string, RoutedCellPipe>;
  dockedJoins: readonly CellDockedJoin[];
  resolveColor: (artifactTypeId: string, port?: CellPort) => string;
  includeAll?: boolean;
  activePipeIds?: ReadonlySet<string>;
}): CellPipeAttachment[] {
  const eligiblePipes = pipes
    .filter(
      (pipe) =>
        includeAll === true ||
        pipe.projectionLabel ||
        pipe.conversionLabel ||
        pipe.collectionMode === "map" ||
        pipe.enabled === false ||
        pipe.incompatible === true ||
        activePipeIds?.has(pipe.id),
    )
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const cardsById = new Map(cards.map((card) => [card.id, card]));
  const cardRects = cards.map(cardWorldRect);
  const joinsByPipeId = new Map(dockedJoins.map((join) => [join.pipeId, join]));
  // Seams are fixed, so reserve their pills before placing any routed pill.
  const occupied = eligiblePipes.flatMap((pipe) => {
    const join = joinsByPipeId.get(pipe.id);
    return join ? [attachmentRect(join.seamPoint)] : [];
  });

  const attachments: CellPipeAttachment[] = [];
  for (const pipe of eligiblePipes) {
    const appearance = {
      pipeId: pipe.id,
      widthCells: ATTACHMENT_WIDTH_CELLS,
      heightCells: ATTACHMENT_HEIGHT_CELLS,
      label: pipeAttachmentLabel(pipe),
      conversionLabel: pipe.conversionLabel ?? null,
      enabled: pipe.enabled ?? true,
    };
    const join = joinsByPipeId.get(pipe.id);
    if (join) {
      attachments.push({
        ...appearance,
        anchor: { ...join.seamPoint },
        segmentOrientation: "horizontal",
        color: join.color,
        isDocked: true,
      });
      continue;
    }

    const points = routedPipes.get(pipe.id)?.points;
    const source = points?.[0];
    const target = points?.at(-1);
    const sourceCard = cardsById.get(pipe.sourceCardId);
    const sourcePort =
      sourceCard &&
      findPipeEndPort(sourceCard.ports, pipe.sourcePortId, "output");
    if (!points || !source || !target || !sourcePort) continue;

    const ports = [source, target];
    const candidate = bestSegmentCandidate(points, cardRects, ports);
    if (!candidate) continue;
    const anchor = staggerAnchor(candidate, cardRects, ports, occupied);
    occupied.push(attachmentRect(anchor));
    attachments.push({
      ...appearance,
      anchor,
      segmentOrientation: candidate.orientation,
      color: resolveColor(sourcePort.artifactTypeId, sourcePort),
      isDocked: false,
    });
  }
  return attachments;
}

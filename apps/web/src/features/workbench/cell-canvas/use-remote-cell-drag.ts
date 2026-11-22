import * as React from "react";

import type { CellRemotePeerState } from "./cell-contracts";
import {
  cellToWorldOrigin,
  type CellCardModel,
  type CellCoord,
  type WorldPoint,
} from "./cell-model";
import {
  createCardSettle,
  retargetCardSettle,
  stepCardSettle,
  type CardSettleState,
} from "./cell-transitions";

/** Give the room time to deliver the confirmed move after presence clears. */
const DROP_HANDOFF_MS = 320;
const NO_POSITIONS: ReadonlyMap<string, WorldPoint> = new Map();

interface RemoteDragTrack {
  start: WorldPoint;
  settle: CardSettleState;
  releasedAt: number | null;
}

function samePoint(a: WorldPoint, b: WorldPoint) {
  return a.x === b.x && a.y === b.y;
}

/** Animate in world coordinates so an arriving document move cannot shift the card mid-glide. */
export function useRemoteCellDrag(
  cards: readonly CellCardModel[],
  peers: readonly CellRemotePeerState[],
  localDraggingIds: ReadonlySet<string>,
  scope?: string | null,
): ReadonlyMap<string, WorldPoint> {
  const tracksRef = React.useRef(new Map<string, RemoteDragTrack>());
  const [positions, setPositions] = React.useState(NO_POSITIONS);

  React.useLayoutEffect(() => {
    const tracks = tracksRef.current;
    return () => tracks.clear();
  }, [scope]);

  React.useLayoutEffect(() => {
    const tracks = tracksRef.current;
    const targets = new Map<string, CellCoord>();
    for (const peer of peers) {
      for (const [cardId, target] of Object.entries(peer.draggingCards)) {
        targets.set(cardId, target);
      }
    }
    if (targets.size === 0 && tracks.size === 0) {
      setPositions(NO_POSITIONS);
      return;
    }

    const origins = new Map<string, WorldPoint>();
    for (const card of cards) {
      if (localDraggingIds.has(card.id)) continue;
      if (targets.has(card.id) || tracks.has(card.id)) {
        origins.set(card.id, cellToWorldOrigin(card.col, card.row));
      }
    }

    const now = performance.now();
    for (const id of tracks.keys()) {
      if (!origins.has(id)) tracks.delete(id);
    }
    for (const [id, origin] of origins) {
      const cell = targets.get(id);
      const track = tracks.get(id);
      if (cell) {
        const target = cellToWorldOrigin(cell.col, cell.row);
        if (!track) {
          tracks.set(id, {
            start: origin,
            settle: retargetCardSettle(createCardSettle(origin), target, now),
            releasedAt: null,
          });
        } else {
          track.start = track.releasedAt === null ? track.start : origin;
          track.releasedAt = null;
          if (!samePoint(track.settle.to, target)) {
            track.settle = retargetCardSettle(track.settle, target, now);
          }
        }
      } else if (track && track.releasedAt === null) {
        track.releasedAt = now;
      }
    }

    let frame: number | undefined;
    let releaseTimer: number | undefined;
    function draw(time: number) {
      const visible = new Map<string, WorldPoint>();
      let animating = false;
      let nextRelease = Infinity;
      for (const [id, track] of tracks) {
        const origin = origins.get(id);
        if (!origin) continue;
        let waitingForDrop = false;
        if (track.releasedAt !== null) {
          const expiresAt = track.releasedAt + DROP_HANDOFF_MS;
          waitingForDrop =
            time < expiresAt &&
            samePoint(origin, track.start) &&
            !samePoint(origin, track.settle.to);
          if (waitingForDrop) {
            nextRelease = Math.min(nextRelease, expiresAt);
          } else if (!samePoint(track.settle.to, origin)) {
            track.settle = retargetCardSettle(track.settle, origin, time);
          }
        }
        track.settle = stepCardSettle(track.settle, time);
        if (
          track.releasedAt !== null &&
          !waitingForDrop &&
          !track.settle.active
        ) {
          tracks.delete(id);
          continue;
        }
        visible.set(id, track.settle.current);
        animating ||= track.settle.active;
      }
      setPositions(visible.size === 0 ? NO_POSITIONS : visible);
      if (animating) {
        frame = requestAnimationFrame(draw);
      } else if (Number.isFinite(nextRelease)) {
        releaseTimer = window.setTimeout(
          () => draw(performance.now()),
          Math.max(0, Math.ceil(nextRelease - time)),
        );
      }
    }
    draw(now);

    return () => {
      if (frame !== undefined) cancelAnimationFrame(frame);
      if (releaseTimer !== undefined) window.clearTimeout(releaseTimer);
    };
  }, [cards, localDraggingIds, peers, scope]);

  return positions;
}

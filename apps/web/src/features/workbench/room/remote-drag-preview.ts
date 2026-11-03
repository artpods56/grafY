import type { PresenceParticipant, TransientNodePosition } from "./protocol";
import {
  applyRemoteCursorSample,
  createRemoteCursorMotion,
  stepRemoteCursorMotion,
  type RemoteCursorMotion,
} from "./remote-cursor-motion";

/** Keep the last preview briefly so durable move_nodes can land first. */
export const REMOTE_DRAG_RELEASE_HOLD_MS = 320;

export interface RemoteDragTrack {
  nodeId: string;
  motion: RemoteCursorMotion;
  /** Set when the peer clears transient positions; removed after the hold. */
  releaseAt: number | null;
}

/** Latest drag targets from every remote participant (one position per node). */
export function remoteDragTargetsFromParticipants(
  participants: readonly PresenceParticipant[],
  localSessionId: string | null,
): Map<string, TransientNodePosition> {
  const targets = new Map<string, TransientNodePosition>();
  for (const participant of participants) {
    if (participant.project_room_session_id === localSessionId) continue;
    for (const position of participant.transient_node_positions) {
      // Later participants in the list win when two peers drag the same node.
      targets.set(position.node_id, position);
    }
  }
  return targets;
}

export function syncRemoteDragTracks(
  tracks: Map<string, RemoteDragTrack>,
  targets: Map<string, TransientNodePosition>,
  now: number,
): void {
  const seen = new Set<string>();
  for (const [nodeId, position] of targets) {
    seen.add(nodeId);
    const existing = tracks.get(nodeId);
    if (!existing) {
      tracks.set(nodeId, {
        nodeId,
        motion: createRemoteCursorMotion({
          x: position.x,
          y: position.y,
          at: now,
        }),
        releaseAt: null,
      });
      continue;
    }
    existing.releaseAt = null;
    existing.motion = applyRemoteCursorSample(existing.motion, {
      x: position.x,
      y: position.y,
      at: now,
    });
  }
  for (const [nodeId, track] of tracks) {
    if (seen.has(nodeId)) continue;
    if (track.releaseAt === null) track.releaseAt = now;
  }
}

/**
 * Advance smoothed preview positions.
 * Returns displayed positions; removes tracks past the post-clear hold.
 */
export function stepRemoteDragTracks(
  tracks: Map<string, RemoteDragTrack>,
  now: number,
  dtMs: number,
): Record<string, { x: number; y: number }> {
  const positions: Record<string, { x: number; y: number }> = {};
  for (const [nodeId, track] of tracks) {
    if (
      track.releaseAt !== null &&
      now - track.releaseAt >= REMOTE_DRAG_RELEASE_HOLD_MS
    ) {
      tracks.delete(nodeId);
      continue;
    }
    const next = stepRemoteCursorMotion(track.motion, now, dtMs);
    if (next === null) {
      tracks.delete(nodeId);
      continue;
    }
    track.motion = next;
    positions[nodeId] = { x: next.x, y: next.y };
  }
  return positions;
}

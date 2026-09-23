import { describe, expect, it } from "vitest";

import {
  REMOTE_DRAG_RELEASE_HOLD_MS,
  remoteDragTargetsFromParticipants,
  stepRemoteDragTracks,
  syncRemoteDragTracks,
  type RemoteDragTrack,
} from "./remote-drag-preview";
import type { PresenceParticipant } from "./protocol";

function participant(
  sessionId: string,
  positions: { node_id: string; x: number; y: number }[],
): PresenceParticipant {
  return {
    graph_room_session_id: sessionId,
    actor: {
      actor_id: "00000000-0000-4000-8000-000000000001",
      display_name: "Editor",
      color: "indigo",
    },
    presence_sequence: 1,
    cursor: null,
    selected_node_ids: [],
    selected_edge_ids: [],
    activity: positions.length ? "moving_nodes" : null,
    activity_target_ids: positions.map((position) => position.node_id),
    transient_node_positions: positions,
  };
}

describe("remote drag previews", () => {
  it("collects transient positions from remote participants only", () => {
    const targets = remoteDragTargetsFromParticipants(
      [
        participant("local", [{ node_id: "a", x: 1, y: 2 }]),
        participant("remote-1", [{ node_id: "b", x: 10, y: 20 }]),
        participant("remote-2", [{ node_id: "b", x: 11, y: 21 }]),
      ],
      "local",
    );

    expect(targets.get("a")).toBeUndefined();
    expect(targets.get("b")).toEqual({ node_id: "b", x: 11, y: 21 });
  });

  it("smooths toward live targets and holds briefly after clear", () => {
    const tracks = new Map<string, RemoteDragTrack>();
    syncRemoteDragTracks(
      tracks,
      new Map([["node-1", { node_id: "node-1", x: 0, y: 0 }]]),
      0,
    );
    syncRemoteDragTracks(
      tracks,
      new Map([["node-1", { node_id: "node-1", x: 100, y: 0 }]]),
      50,
    );

    const mid = stepRemoteDragTracks(tracks, 66, 16);
    expect(mid["node-1"]?.x).toBeGreaterThan(0);
    expect(mid["node-1"]?.x).toBeLessThan(100);

    syncRemoteDragTracks(tracks, new Map(), 100);
    expect(tracks.get("node-1")?.releaseAt).toBe(100);

    const held = stepRemoteDragTracks(
      tracks,
      100 + REMOTE_DRAG_RELEASE_HOLD_MS - 10,
      16,
    );
    expect(held["node-1"]).toBeDefined();

    const gone = stepRemoteDragTracks(
      tracks,
      100 + REMOTE_DRAG_RELEASE_HOLD_MS + 1,
      16,
    );
    expect(gone["node-1"]).toBeUndefined();
    expect(tracks.size).toBe(0);
  });
});

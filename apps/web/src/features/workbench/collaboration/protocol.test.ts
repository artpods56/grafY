import { describe, expect, it } from "vitest";

import { parseServerRoomMessage } from "./protocol";

function roomReady(overrides: Record<string, unknown> = {}) {
  return {
    protocol_version: 1,
    type: "room.ready",
    workspace_id: "workspace",
    project_id: "project",
    project_room_session_id: "session",
    actor: { actor_id: "actor", display_name: "Ada", color: "teal" },
    capabilities: {
      capabilities: ["view_project"],
      authorization_version: 1,
    },
    head: {
      project_id: "project",
      room_epoch: "epoch",
      collaboration_sequence: 0,
      checkpoint_sequence: 0,
      checkpoint_revision: 1,
      name: "Project",
      updated_at: "2026-08-07T10:00:00Z",
      document: {
        graphs: [
          {
            id: "graph",
            name: "Main",
            document: { nodes: [], edges: [], origins: [] },
          },
        ],
      },
    },
    participants: [],
    active_runs: [],
    instances: [],
    registry_marker: "builtin",
    ...overrides,
  };
}

function progressFrame(
  sequence: number,
  overrides: Record<string, unknown> = {},
) {
  return {
    protocol_version: 1,
    type: "node.progress",
    instance: {
      project_id: "project",
      graph_id: "graph",
      call_path: [],
      node_id: "ocr",
      map_index: null,
    },
    fingerprint: "fp",
    computation_id: "computation",
    sequence,
    message: `step ${sequence}`,
    current: sequence,
    total: 4,
    invocation_path: [],
    ...overrides,
  };
}

describe("parseServerRoomMessage room.ready node_progress", () => {
  it("reads a missing or null list as no frames", () => {
    const omitted = parseServerRoomMessage(roomReady());
    const explicitNull = parseServerRoomMessage(
      roomReady({ node_progress: null }),
    );
    expect(omitted?.type).toBe("room.ready");
    expect(explicitNull?.type).toBe("room.ready");
    if (omitted?.type !== "room.ready" || explicitNull?.type !== "room.ready") {
      return;
    }
    expect(omitted.node_progress).toEqual([]);
    expect(explicitNull.node_progress).toEqual([]);
  });

  it("keeps replay frames in the order the server sent them", () => {
    const parsed = parseServerRoomMessage(
      roomReady({
        node_progress: [progressFrame(1), progressFrame(2, { current: 2 })],
      }),
    );
    expect(parsed?.type).toBe("room.ready");
    if (parsed?.type !== "room.ready") return;
    expect(parsed.node_progress?.map((frame) => frame.sequence)).toEqual([
      1, 2,
    ]);
    expect(parsed.node_progress?.[1]?.message).toBe("step 2");
  });

  it("rejects the ready frame when one progress frame is not a progress message", () => {
    expect(
      parseServerRoomMessage(
        roomReady({ node_progress: [progressFrame(1), { type: "nope" }] }),
      ),
    ).toBeNull();
    expect(
      parseServerRoomMessage(roomReady({ node_progress: "later" })),
    ).toBeNull();
  });

  it("still parses a live node.progress frame on its own", () => {
    const parsed = parseServerRoomMessage(progressFrame(3));
    expect(parsed).toMatchObject({
      type: "node.progress",
      sequence: 3,
      message: "step 3",
    });
  });
});

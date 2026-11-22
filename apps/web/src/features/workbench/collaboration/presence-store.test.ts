import { describe, expect, it } from "vitest";

import type { PresenceParticipant } from "./protocol";
import {
  ProjectRoomPresenceStore,
  sameVisualParticipants,
} from "./presence-store";

const GRAPH_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_GRAPH_ID = "22222222-2222-4222-8222-222222222222";
const LOCAL_SESSION_ID = "local-session";

function participant(
  sessionId: string,
  overrides: Partial<PresenceParticipant> = {},
): PresenceParticipant {
  return {
    project_room_session_id: sessionId,
    actor: {
      actor_id: `actor-${sessionId}`,
      display_name: `Editor ${sessionId}`,
      color: "indigo",
    },
    graph_id: GRAPH_ID,
    presence_sequence: 1,
    cursor: { x: 10, y: 20 },
    selected_node_ids: ["selected-node"],
    selected_edge_ids: ["selected-edge"],
    activity: "moving_nodes",
    activity_target_ids: ["dragged-node"],
    transient_node_positions: [{ node_id: "dragged-node", x: 30, y: 40 }],
    ...overrides,
  };
}

describe("ProjectRoomPresenceStore", () => {
  it("compares every visual protocol field but ignores presence_sequence", () => {
    const base = participant("remote");
    const sequenceOnly = { ...base, presence_sequence: 2 };
    expect(sameVisualParticipants([base], [sequenceOnly])).toBe(true);

    const changes: PresenceParticipant[] = [
      { ...base, project_room_session_id: "other-session" },
      { ...base, actor: { ...base.actor, actor_id: "other-actor" } },
      { ...base, actor: { ...base.actor, display_name: "Other editor" } },
      { ...base, actor: { ...base.actor, color: "rose" } },
      { ...base, graph_id: OTHER_GRAPH_ID },
      { ...base, cursor: null },
      { ...base, cursor: { x: 11, y: 20 } },
      { ...base, cursor: { x: 10, y: 21 } },
      { ...base, selected_node_ids: ["other-node"] },
      { ...base, selected_edge_ids: ["other-edge"] },
      { ...base, activity: "editing_node" },
      { ...base, activity_target_ids: ["other-target"] },
      {
        ...base,
        transient_node_positions: [{ node_id: "other-node", x: 30, y: 40 }],
      },
      {
        ...base,
        transient_node_positions: [{ node_id: "dragged-node", x: 31, y: 40 }],
      },
      {
        ...base,
        transient_node_positions: [{ node_id: "dragged-node", x: 30, y: 41 }],
      },
      { ...base, transient_node_positions: [] },
    ];

    for (const changed of changes) {
      expect(sameVisualParticipants([base], [changed])).toBe(false);
    }
    expect(sameVisualParticipants([base], [])).toBe(false);
  });

  it("caches each projection and keeps cursor arrival timing", () => {
    const store = new ProjectRoomPresenceStore();
    const local = participant(LOCAL_SESSION_ID);
    const first = participant("remote-first", {
      actor: {
        actor_id: "actor-first",
        display_name: "First",
        color: "teal",
      },
    });
    const last = participant("remote-last", {
      actor: {
        actor_id: "actor-last",
        display_name: "Last",
        color: "orange",
      },
      transient_node_positions: [{ node_id: "dragged-node", x: 50, y: 60 }],
    });
    store.replaceParticipants([local, first, last], LOCAL_SESSION_ID);

    const collaborators = store.getCollaborators(GRAPH_ID);
    const cursors = store.getCursorSamples(GRAPH_ID);
    const selections = store.getRemoteSelectionColors(GRAPH_ID);
    const drags = store.getRemoteDragTargets(GRAPH_ID);

    expect(collaborators.map((item) => item.displayName)).toEqual([
      "First",
      "Last",
    ]);
    expect(selections.get("selected-node")).toBe("#0d9488");
    expect(drags.get("dragged-node")).toEqual({
      node_id: "dragged-node",
      x: 50,
      y: 60,
    });

    store.upsertParticipant({ ...first, presence_sequence: 2 });

    expect(store.getCollaborators(GRAPH_ID)).toBe(collaborators);
    expect(store.getRemoteSelectionColors(GRAPH_ID)).toBe(selections);
    expect(store.getRemoteDragTargets(GRAPH_ID)).toBe(drags);
    const nextCursors = store.getCursorSamples(GRAPH_ID);
    expect(nextCursors).not.toBe(cursors);
    expect(nextCursors[0]?.sampleRevision).toBeGreaterThan(
      cursors[0]?.sampleRevision ?? 0,
    );
  });

  it("scopes every projection to the active Graph and publishes removals", () => {
    const store = new ProjectRoomPresenceStore();
    const current = participant("current");
    const other = participant("other", {
      graph_id: OTHER_GRAPH_ID,
      selected_node_ids: ["foreign-selection"],
      transient_node_positions: [{ node_id: "foreign-drag", x: 100, y: 200 }],
    });
    store.replaceParticipants(
      [participant(LOCAL_SESSION_ID), current, other],
      LOCAL_SESSION_ID,
    );

    expect(store.getCollaborators(GRAPH_ID)).toHaveLength(1);
    expect(store.getCursorSamples(GRAPH_ID)).toHaveLength(1);
    expect(
      store.getRemoteSelectionColors(GRAPH_ID).has("foreign-selection"),
    ).toBe(false);
    expect(store.getRemoteDragTargets(GRAPH_ID).has("foreign-drag")).toBe(
      false,
    );

    const liveTargets = store.getRemoteDragTargets(GRAPH_ID);
    expect(liveTargets.has("dragged-node")).toBe(true);
    store.upsertParticipant({
      ...current,
      presence_sequence: 2,
      activity: null,
      activity_target_ids: [],
      transient_node_positions: [],
    });
    const releasedTargets = store.getRemoteDragTargets(GRAPH_ID);
    expect(releasedTargets).not.toBe(liveTargets);
    expect(releasedTargets.has("dragged-node")).toBe(false);

    store.removeParticipant("current");
    expect(store.getCollaborators(GRAPH_ID)).toEqual([]);
    expect(store.getCursorSamples(GRAPH_ID)).toEqual([]);
    expect(store.getRemoteSelectionColors(GRAPH_ID).size).toBe(0);
    expect(store.getRemoteDragTargets(GRAPH_ID).size).toBe(0);
  });
});

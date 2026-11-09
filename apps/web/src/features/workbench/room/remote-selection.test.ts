import { describe, expect, it } from "vitest";

import type { PresenceParticipant } from "./protocol";
import { actorColor, remoteSelectionColor } from "./remote-selection";

function participant(
  sessionId: string,
  selectedNodeIds: readonly string[],
  color = "rose",
): PresenceParticipant {
  return {
    project_room_session_id: sessionId,
    graph_id: "graph-1",
    actor: {
      actor_id: "00000000-0000-4000-8000-000000000001",
      display_name: "Ada",
      color,
    },
    presence_sequence: 1,
    cursor: null,
    selected_node_ids: selectedNodeIds,
    selected_edge_ids: [],
    activity: null,
    activity_target_ids: [],
    transient_node_positions: [],
  };
}

describe("remote selection helpers", () => {
  it("maps actor palette keys and falls back for unknown colors", () => {
    expect(actorColor("sky")).toBe("#0284c7");
    expect(actorColor("not-a-color")).toBe("#4f46e5");
  });

  it("returns the first remote collaborator color for a node", () => {
    const participants = [
      participant("local", ["n1"], "violet"),
      participant("remote-a", ["n1"], "teal"),
      participant("remote-b", ["n1"], "orange"),
    ];

    expect(remoteSelectionColor(participants, "local", "n1")).toBe("#0d9488");
    expect(remoteSelectionColor(participants, "local", "missing")).toBeNull();
  });
});

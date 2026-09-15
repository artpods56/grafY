import { afterEach, describe, expect, it, vi } from "vitest";
import {
  checkpointGraph,
  getCollaborativeHead,
  submitGraphCommand,
  type CollaborativeHead,
  type LegacyCollaborativeHead,
} from "@/lib/api";
import { authoredGraphDocument } from "../model/graph-document";
import { parseServerRoomMessage } from "./protocol";
import { applyRoomCommandToHead } from "./room-command-bridge";

const canonical: CollaborativeHead = {
  graph_id: "graph-1",
  room_epoch: "epoch-1",
  name: "Uncheckpointed edits",
  collaboration_sequence: 8,
  checkpoint_sequence: 3,
  checkpoint_revision: 2,
  updated_at: "2026-09-09T10:00:00Z",
  document: {
    schema_version: 7,
    nodes: [{
      id: "source", kind: "plugin", operator_id: "table.read", operator_version: 1,
      plugin_release_pin: { scope: "system", slug: "tables", revision: 7 },
      config: { nested: { delimiter: "," } },
      position: { x: 21, y: 34 },
      layout: { width: 420 },
      artifact_type_bindings: [],
      input_plugs: [{ id: "rows-1", port: "rows" }],
    }],
    edges: [{
      id: "edge-1", from_node: "source", from_port: "rows",
      to_node: "target", to_port: "rows", to_plug: "rows-1",
      enabled: true, collection_mode: "map", conversion_path: [],
      projection: { path: ["records"] }, route_offset: { x: 4, y: 5 },
    }],
    origins: [{
      id: "origin-1", to_node: "target", to_port: "rows", to_plug: "rows-1",
      value: { artifact_id: "00000000-0000-4000-8000-000000000002", artifact_type: "rows", schema_version: 1 },
      conversion_path: [],
    }],
    presentation: {
      viewers: [{ id: "viewer-1", position: { x: 80, y: 90 }, mode: "table" }],
      links: [{ id: "link-1", source_node_id: "source", source_port_name: "rows", target_viewer_id: "viewer-1" }],
      bindings: [], annotations: [],
    },
  },
};
const legacy: LegacyCollaborativeHead = {
  graph_id: canonical.graph_id, room_epoch: canonical.room_epoch,
  name: canonical.name, collaboration_sequence: canonical.collaboration_sequence,
  checkpoint_sequence: canonical.checkpoint_sequence,
  checkpoint_revision: canonical.checkpoint_revision, updated_at: canonical.updated_at,
  nodes: canonical.document.nodes.map(({ plugin_release_pin, ...node }) => ({
    ...node, plugin_release: plugin_release_pin,
  })),
  edges: canonical.document.edges,
  origins: canonical.document.origins,
  presentation: canonical.document.presentation,
};

afterEach(() => vi.unstubAllGlobals());

describe("canonical collaborative head flow", () => {
  it("uses the same document for HTTP refresh, v1 room input, and checkpoint reconciliation", async () => {
    const receipt = {
      command_id: "rename-1", outcome: "accepted", accepted_sequence: 8,
      room_epoch: "epoch-1", deduplicated: false,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(Response.json(canonical))
      .mockResolvedValueOnce(Response.json({ head: legacy, receipt }))
      .mockResolvedValueOnce(Response.json({ head: legacy, saved_revision: 2 }));
    vi.stubGlobal("fetch", fetchMock);

    const refreshed = await getCollaborativeHead("workspace-1", "graph-1");
    const submitted = await submitGraphCommand("workspace-1", "graph-1", {
      command_id: "rename-1", room_epoch: "epoch-1", observed_sequence: 7,
      command: { kind: "rename_graph", name: canonical.name, expected_name: "Before" },
    });
    const checkpointed = await checkpointGraph("workspace-1", "graph-1", {
      expected_room_epoch: "epoch-1", expected_sequence: 8,
    });
    const room = parseServerRoomMessage({
      protocol_version: 1, type: "room.ready", workspace_id: "workspace-1",
      graph_id: "graph-1", graph_room_session_id: "session-1",
      actor: { actor_id: "owner-1", display_name: "Owner", color: "emerald" },
      capabilities: { capabilities: ["view_graph"], authorization_version: 1 },
      head: legacy, participants: [], active_execution: null, registry_marker: "registry-1",
    });
    if (room?.type !== "room.ready") throw new Error("Expected a parsed v1 ready message");
    const rehydrated = parseServerRoomMessage({
      protocol_version: 1, type: "room.rehydrate", reason: "epoch_reset", head: legacy,
    });
    if (rehydrated?.type !== "room.rehydrate") throw new Error("Expected a parsed v1 reset");

    for (const head of [refreshed, submitted.head, checkpointed.head, room.head, rehydrated.head]) {
      expect(head).toEqual(canonical);
      expect(head).not.toHaveProperty("nodes");
      expect(head.document.nodes[0]).not.toHaveProperty("plugin_release");
      expect(authoredGraphDocument(head)).toMatchObject({
        name: canonical.name, nodes: canonical.document.nodes, edges: canonical.document.edges,
      });
      const moved = applyRoomCommandToHead(head, {
        kind: "move_nodes", positions: [{ node_id: "source", x: 100, y: 200 }],
      }, 9);
      expect(moved.document.nodes[0]?.position).toEqual({ x: 100, y: 200 });
      expect(moved.document.nodes[0]?.plugin_release_pin).toEqual({ scope: "system", slug: "tables", revision: 7 });
      expect(moved.document.presentation).toEqual(canonical.document.presentation);
      expect(moved.checkpoint_sequence).toBe(3);
    }
    expect(fetchMock).toHaveBeenNthCalledWith(1,
      "/api/v1/workspaces/workspace-1/graphs/graph-1/head/document",
      expect.objectContaining({ method: "GET" }),
    );
    expect(submitted.receipt).toEqual(receipt);
    expect(checkpointed.saved_revision).toBe(2);
    expect(legacy.nodes[0]).toHaveProperty("plugin_release");
    expect(legacy.nodes[0]).not.toHaveProperty("plugin_release_pin");
  });

  it("normalizes optional v1 collections before they enter document state", () => {
    const room = parseServerRoomMessage({
      protocol_version: 1, type: "room.rehydrate", reason: "epoch_reset",
      head: {
        ...legacy, presentation: undefined,
        nodes: legacy.nodes.map((node) => ({ ...node, artifact_type_bindings: undefined, input_plugs: undefined })),
        edges: legacy.edges.map((edge) => ({ ...edge, conversion_path: undefined })),
        origins: (legacy.origins ?? []).map((origin) => ({ ...origin, conversion_path: undefined })),
      },
    });
    if (room?.type !== "room.rehydrate") throw new Error("Expected a parsed v1 reset");
    expect(room.head.document.nodes[0]?.input_plugs).toEqual([]);
    expect(room.head.document.nodes[0]?.artifact_type_bindings).toEqual([]);
    expect(room.head.document.edges[0]?.conversion_path).toEqual([]);
    expect(room.head.document.origins[0]?.conversion_path).toEqual([]);
    expect(room.head.document.presentation).toEqual({ viewers: [], links: [], bindings: [], annotations: [] });
  });

  it.each([{ invalid: null }, { invalid: 42 }, { invalid: "invalid" }, { invalid: [] }])("rejects non-object v1 graph members: $invalid", ({ invalid }) => {
    for (const field of ["nodes", "edges"]) {
      expect(parseServerRoomMessage({
        protocol_version: 1, type: "room.rehydrate", reason: "epoch_reset",
        head: { ...legacy, [field]: [invalid] },
      })).toBeNull();
    }
  });
});

import { describe, expect, it } from "vitest";

import {
  applyRoomCommandToHead,
  toLocalGraphCommand,
  toLocalGraphCommands,
  toRoomGraphCommand,
} from "./room-command-bridge";
import type { AuthoredGraphDocument } from "../model/graph-document";
import type { CollaborativeHead } from "@/lib/api";

const document: AuthoredGraphDocument = {
  name: "Demo",
  nodes: [
    {
      id: "a",
      operator_id: "demo.op",
      operator_version: 1,
      position: { x: 10, y: 20 },
      config: { threshold: 1 },
    },
  ],
  edges: [],
};

const head: CollaborativeHead = {
  graph_id: "11111111-1111-4111-8111-111111111111",
  room_epoch: "22222222-2222-4222-8222-222222222222",
  collaboration_sequence: 3,
  checkpoint_sequence: 3,
  checkpoint_revision: 1,
  name: "Demo",
  updated_at: "2026-08-07T12:00:00Z",
  nodes: document.nodes,
  edges: [],
};

describe("room-command-bridge", () => {
  it("maps move_nodes both ways", () => {
    const room = toRoomGraphCommand(
      {
        kind: "move_nodes",
        positions: [{ node_id: "a", x: 40, y: 50 }],
      },
      document,
    );
    expect(room).toEqual({
      kind: "move_nodes",
      positions: [{ node_id: "a", x: 40, y: 50 }],
    });
    expect(toLocalGraphCommand(room!)).toEqual({
      kind: "move_nodes",
      positions: [{ node_id: "a", x: 40, y: 50 }],
    });
  });

  it("includes expected_name when renaming", () => {
    expect(
      toRoomGraphCommand({ kind: "rename_graph", name: "Next" }, document),
    ).toEqual({
      kind: "rename_graph",
      name: "Next",
      expected_name: "Demo",
    });
  });

  it("applies accepted move_nodes onto the collaborative head", () => {
    const next = applyRoomCommandToHead(
      head,
      {
        kind: "move_nodes",
        positions: [{ node_id: "a", x: 99, y: 11 }],
      },
      4,
    );
    expect(next.collaboration_sequence).toBe(4);
    expect(next.nodes[0]?.position).toEqual({ x: 99, y: 11 });
  });

  it("applies replace_document onto the collaborative head", () => {
    const next = applyRoomCommandToHead(
      head,
      {
        kind: "replace_document",
        name: "Replaced",
        document: {
          schema_version: 4,
          nodes: [],
          edges: [],
        },
      },
      5,
    );
    expect(next).toMatchObject({
      name: "Replaced",
      collaboration_sequence: 5,
      nodes: [],
      edges: [],
    });
  });

  it("applies an accepted batch in primitive order without waiting for rehydration", () => {
    const command = {
      kind: "apply_batch" as const,
      commands: [
        {
          kind: "add_node" as const,
          node: {
            id: "b",
            operator_id: "generated.node.b",
            operator_version: 1,
            position: { x: 80, y: 40 },
            config: {},
            layout: null,
            input_plugs: [],
            artifact_type_bindings: [],
          },
        },
        {
          kind: "add_edge" as const,
          edge: {
            id: "a-to-b",
            from_node: "a",
            from_port: "result",
            to_node: "b",
            to_port: "value",
            to_plug: null,
            enabled: true,
            collection_mode: "direct" as const,
            projection: null,
            conversion_path: [],
            route_offset: null,
          },
        },
      ],
    };

    expect(toLocalGraphCommands(command, document)?.map(({ kind }) => kind))
      .toEqual(["add_node", "add_edge"]);
    const next = applyRoomCommandToHead(head, command, 4);
    expect(next.collaboration_sequence).toBe(4);
    expect(next.nodes.map((node) => node.id)).toEqual(["a", "b"]);
    expect(next.edges.map((edge) => edge.id)).toEqual(["a-to-b"]);
  });

  it("requests authoritative rehydration when a batch diverges locally", () => {
    const duplicate = {
      kind: "apply_batch" as const,
      commands: [
        {
          kind: "add_node" as const,
          node: {
            id: "a",
            operator_id: "demo.op",
            operator_version: 1,
            position: { x: 40, y: 40 },
            config: {},
            layout: null,
            input_plugs: [],
            artifact_type_bindings: [],
          },
        },
      ],
    };

    expect(toLocalGraphCommands(duplicate, document)).toBeNull();
  });

  it("applies replace_presentation and move_artifact_viewers onto the head", () => {
    const withViewer = applyRoomCommandToHead(
      head,
      {
        kind: "replace_presentation",
        presentation: {
          viewers: [
            {
              id: "artifact-viewer-1",
              position: { x: 1, y: 2 },
              layout: null,
              mode: null,
            },
          ],
          links: [],
          bindings: [],
          annotations: [],
        },
      },
      4,
    );
    expect(withViewer.presentation?.viewers).toHaveLength(1);
    const moved = applyRoomCommandToHead(
      withViewer,
      {
        kind: "move_artifact_viewers",
        positions: [{ viewer_id: "artifact-viewer-1", x: 8, y: 9 }],
      },
      5,
    );
    expect(moved.presentation?.viewers?.[0]?.position).toEqual({ x: 8, y: 9 });
  });
});

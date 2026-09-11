import { describe, expect, it } from "vitest";

import {
  applyRoomCommandToHead,
  toLocalGraphCommand,
  toRoomGraphCommand,
  toRoomReplaceDocumentCommand,
} from "./room-command-bridge";
import type { AuthoredGraphDocument } from "../model/graph-document";
import type { CollaborativeHead } from "@/lib/api";

const document: AuthoredGraphDocument = {
  name: "Demo",
  nodes: [
    {
      id: "a",
      kind: "builtin",
      operator_id: "demo.op",
      operator_version: 1,
      position: { x: 10, y: 20 },
      config: { threshold: 1 },
      input_plugs: [],
      artifact_type_bindings: [],
    },
  ],
  edges: [],
  origins: [],
};

const head: CollaborativeHead = {
  graph_id: "11111111-1111-4111-8111-111111111111",
  room_epoch: "22222222-2222-4222-8222-222222222222",
  collaboration_sequence: 3,
  checkpoint_sequence: 3,
  checkpoint_revision: 1,
  name: "Demo",
  updated_at: "2026-08-07T12:00:00Z",
  document: {
    schema_version: 7,
    nodes: document.nodes,
    edges: [],
    origins: []
  }
};

const scopedNode: AuthoredGraphDocument["nodes"][number] = {
  artifact_type_bindings: [
    {
      variable: "T",
      artifact_type: { id: "table.data", schema_version: 2 },
    },
  ],
  config: { nested: { threshold: 3 } },
  id: "scoped",
  kind: "plugin",
  input_plugs: [{ id: "plug-1", port: "rows" }],
  layout: { width: 420, body_height: 180, appendix_height: 260 },
  operator_id: "reports.render",
  operator_version: 7,
  plugin_release_pin: { scope: "system", slug: "reports", revision: 11 },
  position: { x: 80, y: 120 },
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

  it("maps every authored node field and scoped pin into room add_node", () => {
    const room = toRoomGraphCommand(
      { kind: "add_node", node: scopedNode },
      document,
    );

    expect(room).toEqual({
      kind: "add_node",
      node: {
        artifact_type_bindings: [
          {
            variable: "T",
            artifact_type: { id: "table.data", schema_version: 2 },
          },
        ],
        config: { nested: { threshold: 3 } },
        id: "scoped",
        kind: "plugin",
        input_plugs: [{ id: "plug-1", port: "rows" }],
        layout: { width: 420, body_height: 180, appendix_height: 260 },
        operator_id: "reports.render",
        operator_version: 7,
        plugin_release_pin: {
          scope: "system",
          slug: "reports",
          revision: 11,
        },
        position: { x: 80, y: 120 },
      },
    });
    expect(toLocalGraphCommand(room!)).toEqual({
      kind: "add_node",
      node: scopedNode,
    });
  });

  it("isolates room and local nodes while excluding runtime fields", () => {
    const node = {
      ...scopedNode,
      config: { nested: { threshold: 3 } },
      position: { x: 80, y: 120, selected: true },
      selected: true,
      onClick: () => undefined,
    };
    const room = toRoomGraphCommand({ kind: "add_node", node }, document);
    if (room?.kind !== "add_node") throw new Error("Expected add_node");
    const local = toLocalGraphCommand(room);
    if (local?.kind !== "add_node") throw new Error("Expected local add_node");
    const replay = applyRoomCommandToHead(head, room, 4);
    const replayedNode = replay.document.nodes.find((candidate) => candidate.id === node.id);

    node.config.nested.threshold = 99;
    node.position.x = 999;
    expect(room.node.config).toEqual({ nested: { threshold: 3 } });
    expect(local.node.config).toEqual({ nested: { threshold: 3 } });
    expect(replayedNode?.config).toEqual({ nested: { threshold: 3 } });
    expect(room.node.position).toEqual({ x: 80, y: 120 });
    expect(local.node.position).toEqual({ x: 80, y: 120 });
    for (const projected of [room.node, local.node, replayedNode]) {
      expect(projected).not.toHaveProperty("selected");
      expect(projected).not.toHaveProperty("onClick");
      expect(projected?.position).not.toHaveProperty("selected");
    }
    Object.assign(room.node.config ?? {}, { nested: { threshold: 77 } });
    expect(local.node.config).toEqual({ nested: { threshold: 3 } });
    expect(replayedNode?.config).toEqual({ nested: { threshold: 3 } });
    expect(replayedNode).toHaveProperty("plugin_release_pin", scopedNode.plugin_release_pin);
    expect(replayedNode).not.toHaveProperty("plugin_release");
  });

  it("maps scoped pins through replace_document in both directions", () => {
    const room = toRoomGraphCommand(
      {
        kind: "replace_document",
        document: { name: "Replacement", nodes: [scopedNode], edges: [], origins: [] },
      },
      document,
    );

    expect(room).toMatchObject({
      kind: "replace_document",
      name: "Replacement",
      document: {
        nodes: [
          {
            id: "scoped",
            plugin_release_pin: {
              scope: "system",
              slug: "reports",
              revision: 11,
            },
          },
        ],
      },
    });
    expect(toLocalGraphCommand(room!)).toMatchObject({
      kind: "replace_document",
      document: {
        name: "Replacement",
        nodes: [
          {
            id: "scoped",
            plugin_release_pin: {
              scope: "system",
              slug: "reports",
              revision: 11,
            },
          },
        ],
      },
    });
    expect(applyRoomCommandToHead(head, room!, 8)).toMatchObject({
      name: "Replacement",
      collaboration_sequence: 8,
      document: { nodes: [
        {
          id: "scoped",
          plugin_release_pin: {
            scope: "system",
            slug: "reports",
            revision: 11,
          },
        },
      ] },
    });
  });

  it("projects the canonical saved document into replace_document", () => {
    const room = toRoomReplaceDocumentCommand({
      name: "Replacement",
      document: {
        schema_version: 7,
        nodes: [scopedNode],
        edges: [],
        origins: [],
        presentation: {
          viewers: [],
          links: [],
          bindings: [],
          annotations: [],
        },
      },
    });

    expect(room).toEqual({
      kind: "replace_document",
      name: "Replacement",
      document: {
        schema_version: 7,
        nodes: [
          {
            artifact_type_bindings: [
              {
                variable: "T",
                artifact_type: { id: "table.data", schema_version: 2 },
              },
            ],
            config: { nested: { threshold: 3 } },
            id: "scoped",
            kind: "plugin",
            input_plugs: [{ id: "plug-1", port: "rows" }],
            layout: { width: 420, body_height: 180, appendix_height: 260 },
            operator_id: "reports.render",
            operator_version: 7,
            plugin_release_pin: {
              scope: "system",
              slug: "reports",
              revision: 11,
            },
            position: { x: 80, y: 120 },
          },
        ],
        edges: [],
        origins: [],
        presentation: {
          viewers: [],
          links: [],
          bindings: [],
          annotations: [],
        },
      },
    });
  });

  it("maps a Plugin upgrade to a scoped single-node CAS command", () => {
    const room = toRoomGraphCommand(
      {
        kind: "update_node_plugin_release",
        node_id: "scoped",
        plugin_release: {
          scope: "system",
          slug: "reports",
          revision: 12,
        },
      },
      { name: "Demo", nodes: [scopedNode], edges: [], origins: [] },
    );

    expect(room).toEqual({
      kind: "update_node_plugin_release",
      node_id: "scoped",
      plugin_release_pin: {
        scope: "system",
        slug: "reports",
        revision: 12,
      },
      expected_plugin_release_pin: {
        scope: "system",
        slug: "reports",
        revision: 11,
      },
    });
    expect(toLocalGraphCommand(room!)).toEqual({
      kind: "update_node_plugin_release",
      node_id: "scoped",
      plugin_release: {
        scope: "system",
        slug: "reports",
        revision: 12,
      },
    });
  });

  it("applies an accepted Plugin upgrade without replacing presentation", () => {
    const presentation = {
      viewers: [
        {
          id: "viewer-1",
          position: { x: 4, y: 8 },
          layout: null,
          mode: null,
        },
      ],
      links: [],
      bindings: [],
      annotations: [],
    };
    const scopedHead: CollaborativeHead = {
      ...head,
      document: {
        ...head.document,
        nodes: [scopedNode, ...head.document.nodes],
        presentation
      }
    };
    const room = toRoomGraphCommand(
      {
        kind: "update_node_plugin_release",
        node_id: "scoped",
        plugin_release: {
          scope: "system",
          slug: "reports",
          revision: 12,
        },
      },
      { name: "Demo", nodes: [scopedNode], edges: [], origins: [] },
    );
    if (!room) throw new Error("Expected Plugin upgrade command");

    const next = applyRoomCommandToHead(scopedHead, room, 9);

    expect(next.document.nodes[0]?.plugin_release_pin).toEqual({
      scope: "system",
      slug: "reports",
      revision: 12,
    });
    expect(next.document.nodes[1]).toMatchObject(head.document.nodes[0]!);
    expect(next.document.presentation).toEqual(presentation);
    expect(next.collaboration_sequence).toBe(9);
  });

  it("maps an accepted room duplicate back to the REST authored shape", () => {
    const add = toRoomGraphCommand(
      { kind: "add_node", node: scopedNode },
      document,
    );
    if (!add || add.kind !== "add_node") throw new Error("Expected add_node");

    expect(
      toLocalGraphCommand({
        kind: "duplicate_node",
        source_node_id: "a",
        node: { ...add.node, id: "scoped-copy" },
      }),
    ).toMatchObject({
      kind: "add_node",
      node: {
        id: "scoped-copy",
        plugin_release_pin: {
          scope: "system",
          slug: "reports",
          revision: 11,
        },
      },
    });
  });

  it("maps origin commands through the room protocol in both directions", () => {
    const origin = {
      id: "origin-1",
      to_node: "a",
      to_port: "input",
      to_plug: null,
      value: {
        artifact_id: "00000000-0000-4000-8000-000000000001",
        artifact_type: "scalar.text",
        schema_version: 1,
      },
      conversion_path: [],
    };
    const withOrigin = { ...document, origins: [origin] };

    expect(toRoomGraphCommand({ kind: "add_origin", origin }, document)).toEqual({
      kind: "add_origin",
      origin,
    });
    expect(toLocalGraphCommand({ kind: "add_origin", origin })).toEqual({
      kind: "add_origin",
      origin,
    });
    expect(
      toRoomGraphCommand(
        {
          kind: "update_origin",
          origin_id: "origin-1",
          update: { to_plug: "plug-1" },
        },
        withOrigin,
      ),
    ).toEqual({
      kind: "update_origin",
      expected_origin: origin,
      origin: { ...origin, to_plug: "plug-1" },
    });
    expect(
      toLocalGraphCommand({
        kind: "update_origin",
        expected_origin: origin,
        origin: { ...origin, to_port: "other" },
      }),
    ).toEqual({
      kind: "update_origin",
      origin_id: "origin-1",
      update: {
        to_node: "a",
        to_port: "other",
        to_plug: null,
        value: origin.value,
        conversion_path: [],
      },
    });
    expect(
      toRoomGraphCommand(
        {
          kind: "update_origin",
          origin_id: "missing-origin",
          update: { to_port: "other" },
        },
        document,
      ),
    ).toBeNull();
    expect(
      toRoomGraphCommand(
        { kind: "remove_origins", origin_ids: ["origin-1"] },
        withOrigin,
      ),
    ).toEqual({ kind: "remove_origins", origin_ids: ["origin-1"] });
    expect(
      toLocalGraphCommand({
        kind: "remove_origins",
        origin_ids: ["origin-1"],
      }),
    ).toEqual({ kind: "remove_origins", origin_ids: ["origin-1"] });
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
    expect(next.document.nodes[0]?.position).toEqual({ x: 99, y: 11 });
  });

  it("applies replace_document onto the collaborative head", () => {
    const next = applyRoomCommandToHead(
      head,
      {
        kind: "replace_document",
        name: "Replaced",
        document: {
          schema_version: 7,
          nodes: [],
          edges: [],
          origins: [],
        },
      },
      5,
    );
    expect(next).toMatchObject({
      name: "Replaced",
      collaboration_sequence: 5,
      document: { nodes: [], edges: [] },
    });
  });

  it("applies accepted add and duplicate commands without losing scoped pins", () => {
    const add = toRoomGraphCommand(
      { kind: "add_node", node: scopedNode },
      document,
    );
    if (!add || add.kind !== "add_node") throw new Error("Expected add_node");

    const afterAdd = applyRoomCommandToHead(head, add, 4);
    expect(afterAdd.document.nodes[1]).toMatchObject({
      id: "scoped",
      plugin_release_pin: {
        scope: "system",
        slug: "reports",
        revision: 11,
      },
    });
    const afterDuplicate = applyRoomCommandToHead(
      afterAdd,
      {
        kind: "duplicate_node",
        source_node_id: "scoped",
        node: { ...add.node, id: "scoped-copy" },
      },
      5,
    );
    expect(afterDuplicate.document.nodes[2]).toMatchObject({
      id: "scoped-copy",
      plugin_release_pin: {
        scope: "system",
        slug: "reports",
        revision: 11,
      },
    });
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
    expect(withViewer.document.presentation?.viewers).toHaveLength(1);
    const moved = applyRoomCommandToHead(
      withViewer,
      {
        kind: "move_artifact_viewers",
        positions: [{ viewer_id: "artifact-viewer-1", x: 8, y: 9 }],
      },
      5,
    );
    expect(moved.document.presentation?.viewers?.[0]?.position).toEqual({ x: 8, y: 9 });
  });
});

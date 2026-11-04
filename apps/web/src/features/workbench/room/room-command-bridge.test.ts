import { describe, expect, it } from "vitest";

import {
  applyRoomCommandToHead,
  applyRoomCommandsToHead,
  commandBatchGraphId,
  defaultGraphId,
  savedGraphFromProjectHead,
  toInGraphCommand,
  toLocalGraphCommand,
  toRoomGraphBodyCommand,
  toRoomGraphCommand,
  toRoomRenameGraphCommand,
  toRoomRenameProjectCommand,
  toRoomReplaceDocumentCommand,
  type RoomProjectCommand,
} from "./room-command-bridge";
import type { AuthoredGraphDocument } from "../model/graph-document";
import type {
  CollaborativeHead,
  GraphDefinition,
  SavedGraphDocument,
} from "@/lib/api";

/** The Graph the caller has open in its canvas. */
const GRAPH_ID = "11111111-1111-4111-8111-111111111111";
/** Another Graph of the same Project. */
const OTHER_GRAPH_ID = "66666666-6666-4666-8666-666666666666";
/** A Graph this head does not hold. */
const UNKNOWN_GRAPH_ID = "77777777-7777-4777-8777-777777777777";
const PROJECT_ID = "99999999-9999-4999-8999-999999999991";

function graphDocument(
  overrides: Partial<SavedGraphDocument> = {},
): SavedGraphDocument {
  return {
    schema_version: 7,
    nodes: [],
    edges: [],
    origins: [],
    agents: [],
    presentation: { viewers: [], links: [], bindings: [], annotations: [] },
    ...overrides,
  };
}

function graph(
  graphId: string,
  name: string,
  document: SavedGraphDocument = graphDocument(),
): GraphDefinition {
  return { id: graphId, name, document };
}

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
  agents: [],
};

/** The head of the Project the caller is editing: it holds both Graphs. */
const head: CollaborativeHead = {
  project_id: PROJECT_ID,
  room_epoch: "22222222-2222-4222-8222-222222222222",
  collaboration_sequence: 3,
  checkpoint_sequence: 3,
  checkpoint_revision: 1,
  name: "Room project",
  updated_at: "2026-08-07T12:00:00Z",
  document: {
    graphs: [
      graph(GRAPH_ID, "Demo", graphDocument({ nodes: document.nodes })),
      graph(OTHER_GRAPH_ID, "Other"),
    ],
  },
};

function graphOf(
  target: CollaborativeHead,
  graphId: string,
): GraphDefinition | undefined {
  return target.document.graphs.find((candidate) => candidate.id === graphId);
}

function nodesOf(target: CollaborativeHead, graphId: string) {
  return graphOf(target, graphId)?.document.nodes ?? [];
}

function viewersOf(target: CollaborativeHead, graphId: string) {
  return graphOf(target, graphId)?.document.presentation?.viewers ?? [];
}

const scopedNode: AuthoredGraphDocument["nodes"][number] = {
  artifact_type_bindings: [
    {
      variable: "T",
      artifact_type: { id: "table.data", schema_version: 2 },
    },
  ],
  config: { nested: { threshold: 3 } },
  id: "scoped",
  kind: "builtin",
  input_plugs: [{ id: "plug-1", port: "rows" }],
  layout: { width: 420, body_height: 180, appendix_height: 260 },
  operator_id: "reports.render",
  operator_version: 7,
  position: { x: 80, y: 120 },
};

/** The authored shape a scoped node keeps after a room round trip. */
const scopedNodeOnTheWire = {
  artifact_type_bindings: [
    {
      variable: "T",
      artifact_type: { id: "table.data", schema_version: 2 },
    },
  ],
  config: { nested: { threshold: 3 } },
  id: "scoped",
  kind: "builtin",
  input_plugs: [{ id: "plug-1", port: "rows" }],
  layout: { width: 420, body_height: 180, appendix_height: 260 },
  operator_id: "reports.render",
  operator_version: 7,
  position: { x: 80, y: 120 },
};

describe("room-command-bridge", () => {
  it("addresses every Graph command at the Graph it edits, both ways", () => {
    const room = toRoomGraphCommand(
      {
        kind: "move_nodes",
        positions: [{ node_id: "a", x: 40, y: 50 }],
      },
      document,
      GRAPH_ID,
    );
    // A Project holds several Graphs: an unaddressed edit names none of them.
    expect(room).toEqual({
      kind: "in_graph",
      graph_id: GRAPH_ID,
      command: {
        kind: "move_nodes",
        positions: [{ node_id: "a", x: 40, y: 50 }],
      },
    });
    expect(toLocalGraphCommand(room!, document, GRAPH_ID)).toEqual({
      kind: "move_nodes",
      positions: [{ node_id: "a", x: 40, y: 50 }],
    });
    // The same accepted command is not applicable to a canvas on another Graph.
    expect(toLocalGraphCommand(room!, document, OTHER_GRAPH_ID)).toBeNull();
    // The Graph-scoped half, without its Project wrapper.
    expect(
      toRoomGraphBodyCommand(
        {
          kind: "move_nodes",
          positions: [{ node_id: "a", x: 40, y: 50 }],
        },
        document,
      ),
    ).toEqual({
      kind: "move_nodes",
      positions: [{ node_id: "a", x: 40, y: 50 }],
    });
  });

  it("names a Graph at the Project level, never inside one", () => {
    const room = toRoomGraphCommand(
      { kind: "rename_graph", name: "Next" },
      document,
      GRAPH_ID,
    );

    // A Graph is named by the Project that holds it, so this is not an edit
    // inside a Graph and carries no `in_graph` wrapper.
    expect(room).toEqual({
      kind: "rename_graph",
      graph_id: GRAPH_ID,
      name: "Next",
      expected_name: "Demo",
    });
    expect(room).toEqual(toRoomRenameGraphCommand(GRAPH_ID, "Next", "Demo"));
    // There is no in-graph form of a rename to map to.
    expect(
      toRoomGraphBodyCommand({ kind: "rename_graph", name: "Next" }, document),
    ).toBeNull();
    // And the canvas vocabulary has no project-level edits to map back to.
    expect(toLocalGraphCommand(room!, document, GRAPH_ID)).toBeNull();
    expect(toRoomRenameProjectCommand("Project", "Room project")).toEqual({
      kind: "rename_project",
      name: "Project",
      expected_name: "Room project",
    });
  });

  it("maps every authored node field and scoped pin into an addressed add_node", () => {
    const room = toRoomGraphCommand(
      { kind: "add_node", node: scopedNode },
      document,
      GRAPH_ID,
    );

    expect(room).toEqual({
      kind: "in_graph",
      graph_id: GRAPH_ID,
      command: { kind: "add_node", node: scopedNodeOnTheWire },
    });
    expect(toLocalGraphCommand(room!, document, GRAPH_ID)).toEqual({
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
    const room = toRoomGraphCommand(
      { kind: "add_node", node },
      document,
      GRAPH_ID,
    );
    if (room?.kind !== "in_graph" || room.command.kind !== "add_node") {
      throw new Error("Expected an addressed add_node");
    }
    const roomNode = room.command.node;
    const local = toLocalGraphCommand(room, document, GRAPH_ID);
    if (local?.kind !== "add_node") throw new Error("Expected local add_node");
    const replay = applyRoomCommandToHead(head, room, 4);
    const replayedNode = nodesOf(replay, GRAPH_ID).find(
      (candidate) => candidate.id === node.id,
    );

    node.config.nested.threshold = 99;
    node.position.x = 999;
    expect(roomNode.config).toEqual({ nested: { threshold: 3 } });
    expect(local.node.config).toEqual({ nested: { threshold: 3 } });
    expect(replayedNode?.config).toEqual({ nested: { threshold: 3 } });
    expect(roomNode.position).toEqual({ x: 80, y: 120 });
    expect(local.node.position).toEqual({ x: 80, y: 120 });
    for (const projected of [roomNode, local.node, replayedNode]) {
      expect(projected).not.toHaveProperty("selected");
      expect(projected).not.toHaveProperty("onClick");
      expect(projected?.position).not.toHaveProperty("selected");
    }
    Object.assign(roomNode.config ?? {}, { nested: { threshold: 77 } });
    expect(local.node.config).toEqual({ nested: { threshold: 3 } });
    expect(replayedNode?.config).toEqual({ nested: { threshold: 3 } });
    expect(replayedNode).not.toHaveProperty("plugin_release_pin");
    expect(replayedNode).not.toHaveProperty("plugin_release");
    // The replay landed in the Graph the command addressed, nowhere else.
    expect(nodesOf(replay, OTHER_GRAPH_ID)).toEqual([]);
  });

  it("maps family nodes through replace_document in both directions", () => {
    const room = toRoomGraphCommand(
      {
        kind: "replace_document",
        document: {
          name: "Replacement",
          nodes: [scopedNode],
          edges: [],
          origins: [],
          agents: [],
        },
      },
      document,
      GRAPH_ID,
    );

    // The Graph's name is not part of its document, so the wire carries only
    // the body; renaming it is a Project command of its own.
    expect(room).toEqual({
      kind: "in_graph",
      graph_id: GRAPH_ID,
      command: {
        kind: "replace_document",
        document: {
          schema_version: 7,
          nodes: [scopedNodeOnTheWire],
          edges: [],
          origins: [],
          agents: [],
          presentation: {
            viewers: [],
            links: [],
            bindings: [],
            annotations: [],
          },
        },
      },
    });
    // The local projection names the Graph the caller has open, which is the
    // only Graph this command could replace for it.
    expect(toLocalGraphCommand(room!, document, GRAPH_ID)).toMatchObject({
      kind: "replace_document",
      document: {
        name: "Demo",
        nodes: [{ id: "scoped" }],
      },
    });
    expect(applyRoomCommandsToHead(head, [room!], 8)).toMatchObject({
      name: "Room project",
      collaboration_sequence: 8,
      document: {
        graphs: [
          {
            id: GRAPH_ID,
            name: "Demo",
            document: { nodes: [{ id: "scoped" }] },
          },
          { id: OTHER_GRAPH_ID, name: "Other" },
        ],
      },
    });
  });

  it("projects the canonical saved document into an addressed replace_document", () => {
    const room = toRoomReplaceDocumentCommand(
      {
        name: "Replacement",
        document: {
          schema_version: 7,
          nodes: [scopedNode],
          edges: [],
          origins: [],
          agents: [],
          presentation: {
            viewers: [],
            links: [],
            bindings: [],
            annotations: [],
          },
        },
      },
      GRAPH_ID,
    );

    expect(room).toEqual({
      kind: "in_graph",
      graph_id: GRAPH_ID,
      command: {
        kind: "replace_document",
        document: {
          schema_version: 7,
          nodes: [scopedNodeOnTheWire],
          edges: [],
          origins: [],
          agents: [],
          presentation: {
            viewers: [],
            links: [],
            bindings: [],
            annotations: [],
          },
        },
      },
    });
  });

  it("maps an accepted room duplicate back to the authored shape", () => {
    const add = toRoomGraphCommand(
      { kind: "add_node", node: scopedNode },
      document,
      GRAPH_ID,
    );
    if (add?.kind !== "in_graph" || add.command.kind !== "add_node") {
      throw new Error("Expected an addressed add_node");
    }

    expect(
      toLocalGraphCommand(
        toInGraphCommand(GRAPH_ID, {
          kind: "duplicate_node",
          source_node_id: "a",
          node: { ...add.command.node, id: "scoped-copy" },
        }),
        document,
        GRAPH_ID,
      ),
    ).toMatchObject({
      kind: "add_node",
      node: { id: "scoped-copy" },
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
      collection_mode: "direct" as const,
      conversion_path: [],
    };
    const withOrigin = { ...document, origins: [origin] };

    expect(
      toRoomGraphCommand({ kind: "add_origin", origin }, document, GRAPH_ID),
    ).toEqual({
      kind: "in_graph",
      graph_id: GRAPH_ID,
      command: { kind: "add_origin", origin },
    });
    expect(
      toLocalGraphCommand(
        toInGraphCommand(GRAPH_ID, { kind: "add_origin", origin }),
        document,
        GRAPH_ID,
      ),
    ).toEqual({
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
        GRAPH_ID,
      ),
    ).toEqual({
      kind: "in_graph",
      graph_id: GRAPH_ID,
      command: {
        kind: "update_origin",
        expected_origin: origin,
        origin: { ...origin, to_plug: "plug-1" },
      },
    });
    expect(
      toLocalGraphCommand(
        toInGraphCommand(GRAPH_ID, {
          kind: "update_origin",
          expected_origin: origin,
          origin: { ...origin, to_port: "other" },
        }),
        document,
        GRAPH_ID,
      ),
    ).toEqual({
      kind: "update_origin",
      origin_id: "origin-1",
      update: {
        to_node: "a",
        to_port: "other",
        to_plug: null,
        value: origin.value,
        collection_mode: "direct" as const,
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
        GRAPH_ID,
      ),
    ).toBeNull();
    expect(
      toRoomGraphCommand(
        { kind: "remove_origins", origin_ids: ["origin-1"] },
        withOrigin,
        GRAPH_ID,
      ),
    ).toEqual({
      kind: "in_graph",
      graph_id: GRAPH_ID,
      command: { kind: "remove_origins", origin_ids: ["origin-1"] },
    });
    expect(
      toLocalGraphCommand(
        toInGraphCommand(GRAPH_ID, {
          kind: "remove_origins",
          origin_ids: ["origin-1"],
        }),
        document,
        GRAPH_ID,
      ),
    ).toEqual({ kind: "remove_origins", origin_ids: ["origin-1"] });
  });

  it("applies accepted move_nodes onto the Graph it addressed", () => {
    const otherBefore = graphOf(head, OTHER_GRAPH_ID);
    const next = applyRoomCommandToHead(
      head,
      toInGraphCommand(GRAPH_ID, {
        kind: "move_nodes",
        positions: [{ node_id: "a", x: 99, y: 11 }],
      }),
      4,
    );
    expect(next.collaboration_sequence).toBe(4);
    expect(nodesOf(next, GRAPH_ID)[0]?.position).toEqual({ x: 99, y: 11 });
    // The other Graph of the Project is not rewritten on the way past.
    expect(graphOf(next, OTHER_GRAPH_ID)).toBe(otherBefore);
  });

  it("applies replace_document onto one Graph of the Project document", () => {
    const next = applyRoomCommandToHead(
      head,
      toInGraphCommand(GRAPH_ID, {
        kind: "replace_document",
        document: graphDocument(),
      }),
      5,
    );
    expect(next).toMatchObject({
      name: "Room project",
      collaboration_sequence: 5,
      document: {
        graphs: [
          { id: GRAPH_ID, name: "Demo", document: { nodes: [], edges: [] } },
          { id: OTHER_GRAPH_ID, name: "Other" },
        ],
      },
    });
  });

  it("applies accepted add and duplicate commands without losing scoped pins", () => {
    const add = toRoomGraphCommand(
      { kind: "add_node", node: scopedNode },
      document,
      GRAPH_ID,
    );
    if (add?.kind !== "in_graph" || add.command.kind !== "add_node") {
      throw new Error("Expected an addressed add_node");
    }

    const afterAdd = applyRoomCommandToHead(head, add, 4);
    expect(nodesOf(afterAdd, GRAPH_ID)[1]).toMatchObject({ id: "scoped" });
    const afterDuplicate = applyRoomCommandToHead(
      afterAdd,
      toInGraphCommand(GRAPH_ID, {
        kind: "duplicate_node",
        source_node_id: "scoped",
        node: { ...add.command.node, id: "scoped-copy" },
      }),
      5,
    );
    expect(nodesOf(afterDuplicate, GRAPH_ID)[2]).toMatchObject({
      id: "scoped-copy",
    });
    // The pins travelled: a replayed node is still bound to its release.
    expect(nodesOf(afterDuplicate, GRAPH_ID)[2]).toMatchObject({
      artifact_type_bindings: [
        {
          variable: "T",
          artifact_type: { id: "table.data", schema_version: 2 },
        },
      ],
    });
    expect(nodesOf(afterDuplicate, OTHER_GRAPH_ID)).toEqual([]);
  });

  it("applies replace_presentation and move_artifact_viewers onto the addressed Graph", () => {
    const withViewer = applyRoomCommandToHead(
      head,
      toInGraphCommand(GRAPH_ID, {
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
      }),
      4,
    );
    expect(viewersOf(withViewer, GRAPH_ID)).toHaveLength(1);
    expect(viewersOf(withViewer, OTHER_GRAPH_ID)).toEqual([]);
    const moved = applyRoomCommandToHead(
      withViewer,
      toInGraphCommand(GRAPH_ID, {
        kind: "move_artifact_viewers",
        positions: [{ viewer_id: "artifact-viewer-1", x: 8, y: 9 }],
      }),
      5,
    );
    expect(viewersOf(moved, GRAPH_ID)[0]?.position).toEqual({ x: 8, y: 9 });
    expect(moved.collaboration_sequence).toBe(5);
  });

  it("folds a command batch and advances the sequence once for the whole batch", () => {
    const batch: readonly RoomProjectCommand[] = [
      toRoomRenameGraphCommand(GRAPH_ID, "Renamed", "Demo"),
      toInGraphCommand(GRAPH_ID, {
        kind: "move_nodes",
        positions: [{ node_id: "a", x: 40, y: 50 }],
      }),
      toInGraphCommand(OTHER_GRAPH_ID, {
        kind: "replace_presentation",
        presentation: {
          viewers: [
            {
              id: "other-viewer",
              position: { x: 3, y: 4 },
              layout: null,
              mode: null,
            },
          ],
          links: [],
          bindings: [],
          annotations: [],
        },
      }),
    ];

    const next = applyRoomCommandsToHead(head, batch, 9);

    // One batch is one unit of work: three commands, one sequence number.
    expect(next.collaboration_sequence).toBe(9);
    expect(graphOf(next, GRAPH_ID)?.name).toBe("Renamed");
    expect(nodesOf(next, GRAPH_ID)[0]?.position).toEqual({ x: 40, y: 50 });
    expect(viewersOf(next, OTHER_GRAPH_ID)).toHaveLength(1);
    // A batch may rename a Graph without renaming the Project that holds it.
    expect(next.name).toBe("Room project");
  });

  it("reaches one Graph of the Project the way a canvas does", () => {
    expect(defaultGraphId(head)).toBe(GRAPH_ID);

    const saved = savedGraphFromProjectHead(head, OTHER_GRAPH_ID);
    expect(saved).toEqual({
      id: OTHER_GRAPH_ID,
      name: "Other",
      // A save is compared against the Project's collaboration sequence.
      revision: head.collaboration_sequence,
      created_at: head.updated_at,
      updated_at: head.updated_at,
      document: graphDocument(),
    });
    expect(savedGraphFromProjectHead(head, UNKNOWN_GRAPH_ID)).toBeNull();
    // A Graph with no authored Graphs leaves the canvas with nothing to open.
    expect(defaultGraphId({ ...head, document: { graphs: [] } })).toBeNull();
  });

  it("reports the Graph a batch is addressed to, and none when it is mixed", () => {
    expect(
      commandBatchGraphId([
        toInGraphCommand(GRAPH_ID, {
          kind: "remove_nodes",
          node_ids: ["a"],
        }),
        toInGraphCommand(GRAPH_ID, {
          kind: "move_nodes",
          positions: [{ node_id: "b", x: 1, y: 1 }],
        }),
      ]),
    ).toBe(GRAPH_ID);
    // Two Graphs in one batch name no single Graph for a canvas to apply.
    expect(
      commandBatchGraphId([
        toInGraphCommand(GRAPH_ID, { kind: "remove_nodes", node_ids: ["a"] }),
        toInGraphCommand(OTHER_GRAPH_ID, {
          kind: "remove_nodes",
          node_ids: ["b"],
        }),
      ]),
    ).toBeNull();
    // A Project-level batch addresses the Project, not a Graph.
    expect(
      commandBatchGraphId([
        toRoomRenameProjectCommand("Project", "Room project"),
      ]),
    ).toBeNull();
  });

  it("applies Project-level commands to the Project, not into a Graph", () => {
    const renamed = applyRoomCommandToHead(
      head,
      toRoomRenameProjectCommand("Renamed project", "Room project"),
      4,
    );
    expect(renamed.name).toBe("Renamed project");
    expect(renamed.collaboration_sequence).toBe(4);
    // The Graphs and their documents are untouched by a Project rename.
    expect(renamed.document.graphs).toEqual(head.document.graphs);

    const added = applyRoomCommandToHead(
      renamed,
      {
        kind: "add_graph",
        graph_id: UNKNOWN_GRAPH_ID,
        name: "Third",
      },
      5,
    );
    expect(added.document.graphs.map((candidate) => candidate.name)).toEqual([
      "Demo",
      "Other",
      "Third",
    ]);
    expect(graphOf(added, UNKNOWN_GRAPH_ID)?.document.nodes).toEqual([]);

    // A refresh raises the generation a node's inputs are pinned to; the
    // document itself does not change, and the instance state comes from the Run.
    const refreshed = applyRoomCommandToHead(
      added,
      {
        kind: "refresh_node",
        graph_id: GRAPH_ID,
        node_id: "a",
        expected_generation: 0,
      },
      6,
    );
    expect(refreshed.collaboration_sequence).toBe(6);
    expect(graphOf(refreshed, GRAPH_ID)).toEqual(graphOf(added, GRAPH_ID));

    const removed = applyRoomCommandToHead(
      refreshed,
      { kind: "remove_graph", graph_id: OTHER_GRAPH_ID },
      7,
    );
    expect(removed.document.graphs.map((candidate) => candidate.id)).toEqual([
      GRAPH_ID,
      UNKNOWN_GRAPH_ID,
    ]);
    expect(removed.collaboration_sequence).toBe(7);
  });

  it("converts a node into a call node without wiping the Graph's presentation", () => {
    const withViewer = applyRoomCommandToHead(
      head,
      toInGraphCommand(GRAPH_ID, {
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
      }),
      4,
    );

    const next = applyRoomCommandToHead(
      withViewer,
      {
        kind: "add_call_node",
        graph_id: GRAPH_ID,
        node_id: "a",
        callee_graph_id: OTHER_GRAPH_ID,
        position: { x: 30, y: 40 },
      },
      5,
    );

    const callNode = nodesOf(next, GRAPH_ID).find(
      (candidate) => candidate.id === "a",
    );
    expect(callNode).toMatchObject({
      kind: "call",
      position: { x: 30, y: 40 },
    });
    // The Graph keeps the viewers it already had: converting a node is not a
    // reason to drop the rest of the Graph's presentation.
    expect(viewersOf(next, GRAPH_ID)).toHaveLength(1);
    expect(next.collaboration_sequence).toBe(5);
  });

  it("leaves every Graph untouched by a command for a Graph the head lacks, and still advances", () => {
    const graphsBefore = head.document.graphs;

    const afterInGraph = applyRoomCommandToHead(
      head,
      toInGraphCommand(UNKNOWN_GRAPH_ID, {
        kind: "move_nodes",
        positions: [{ node_id: "ghost", x: 1, y: 1 }],
      }),
      4,
    );
    // Inventing the Graph would hide a protocol fault the caller must resolve
    // by rehydrating, so no Graph is created and none is rewritten...
    expect(afterInGraph.document.graphs).toBe(graphsBefore);
    // ...but the sequence still moves, which is the difference between waiting
    // for a snapshot and stalling on this command forever.
    expect(afterInGraph.collaboration_sequence).toBe(4);

    const afterRename = applyRoomCommandToHead(
      afterInGraph,
      toRoomRenameGraphCommand(UNKNOWN_GRAPH_ID, "Ghost", "Whatever"),
      5,
    );
    expect(
      afterRename.document.graphs.map((candidate) => candidate.name),
    ).toEqual(["Demo", "Other"]);
    expect(afterRename.document.graphs[0]).toBe(graphsBefore[0]);
    expect(afterRename.document.graphs[1]).toBe(graphsBefore[1]);
    expect(afterRename.collaboration_sequence).toBe(5);
  });
});

describe("room-command-bridge agents", () => {
  /** A card as the canvas holds it: what it is called, what it was told, where it sits. */
  const scribe: AuthoredGraphDocument["agents"][number] = {
    id: "agent-scribe",
    name: "Scribe",
    instructions: "Read the table back to me",
    model: {
      kind: "custom",
      endpoint: "https://models.example/v1",
      model: "some-model",
    },
    position: { x: 320, y: 40 },
    width: 360,
    height: 480,
  };

  function agentsOf(target: CollaborativeHead, graphId: string) {
    return graphOf(target, graphId)?.document.agents ?? [];
  }

  it("carries a new card out, back, and into the head it addressed", () => {
    // Mutable on purpose: the projection has to copy. A card edited after its command left
    // must not change what the room was sent, nor what the head now holds.
    const draft = { ...scribe, position: { x: 320, y: 40 } };
    const added = toRoomGraphCommand(
      { kind: "add_agent", agent: draft },
      document,
      GRAPH_ID,
    );

    if (added?.kind !== "in_graph" || added.command.kind !== "add_agent") {
      throw new Error("Expected an addressed add_agent");
    }
    // The Graph's cards belong to the Graph the command named, so the address is half the
    // command and the body the other half.
    expect(added.graph_id).toBe(GRAPH_ID);
    expect(added.command.agent).toEqual(scribe);
    expect(toLocalGraphCommand(added, document, GRAPH_ID)).toEqual({
      kind: "add_agent",
      agent: scribe,
    });

    const replayed = applyRoomCommandToHead(head, added, 4);
    expect(agentsOf(replayed, GRAPH_ID)).toEqual([scribe]);
    // The card belongs to the Graph the command named, not to the Project's other ones.
    expect(agentsOf(replayed, OTHER_GRAPH_ID)).toEqual([]);
    expect(replayed.collaboration_sequence).toBe(4);

    draft.name = "Edited on this tab";
    draft.position.x = 999;
    expect(agentsOf(replayed, GRAPH_ID)[0]?.name).toBe("Scribe");
    expect(agentsOf(replayed, GRAPH_ID)[0]?.position).toEqual({
      x: 320,
      y: 40,
    });
  });

  it("reconfigures a card from the wire with the model choice it now carries", () => {
    const withCard = applyRoomCommandToHead(
      head,
      toInGraphCommand(GRAPH_ID, { kind: "add_agent", agent: scribe }),
      4,
    );

    const configured = toInGraphCommand(GRAPH_ID, {
      kind: "configure_agent",
      agent: { ...scribe, model: { kind: "deployment" } },
    });
    const replayed = applyRoomCommandToHead(withCard, configured, 5);

    expect(agentsOf(replayed, GRAPH_ID)).toEqual([
      { ...scribe, model: { kind: "deployment" } },
    ]);
  });

  it("removes a card by id and leaves the rest of the canvas alone", () => {
    const other = { ...scribe, id: "agent-other", name: "Other" };
    const withCards = applyRoomCommandToHead(
      head,
      toInGraphCommand(GRAPH_ID, { kind: "add_agent", agent: scribe }),
      4,
    );
    const withBoth = applyRoomCommandToHead(
      withCards,
      toInGraphCommand(GRAPH_ID, { kind: "add_agent", agent: other }),
      5,
    );

    const replayed = applyRoomCommandToHead(
      withBoth,
      toInGraphCommand(GRAPH_ID, { kind: "remove_agent", agent_id: scribe.id }),
      6,
    );

    expect(agentsOf(replayed, GRAPH_ID).map((agent) => agent.id)).toEqual([
      "agent-other",
    ]);
    expect(nodesOf(replayed, GRAPH_ID).map((node) => node.id)).toEqual(["a"]);
  });

  it("reports an agent command for another Graph as not ours to apply", () => {
    const forOtherGraph = toInGraphCommand(OTHER_GRAPH_ID, {
      kind: "remove_agent",
      agent_id: scribe.id,
    });

    // The caller's canvas shows one Graph: an accepted command addressed to another must not
    // be applied to it, and must not look like a command this tab cannot understand.
    expect(toLocalGraphCommand(forOtherGraph, document, GRAPH_ID)).toBeNull();
  });

  it("saves the cards of a Graph through the whole-document command", () => {
    const draft = {
      name: "With a card",
      document: graphDocument({ agents: [scribe] }),
    };

    const room = toRoomReplaceDocumentCommand(draft, GRAPH_ID);

    if (room?.kind !== "in_graph" || room.command.kind !== "replace_document") {
      throw new Error("Expected an addressed replace_document");
    }
    expect(room.command.document.agents).toEqual([scribe]);

    const replayed = applyRoomCommandToHead(head, room, 7);
    expect(agentsOf(replayed, GRAPH_ID)).toEqual([scribe]);
  });
});

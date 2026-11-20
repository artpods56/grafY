import { assert, describe, expect, it } from "vitest";

import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import { ARTIFACT_CARD_OUTPUT_HANDLE } from "../canvas/artifact-connections";
import {
  ARTIFACT_VIEWER_INPUT_HANDLE,
  artifactViewersFromPresentation,
  type GraphPresentation,
} from "../canvas/artifact-viewer";
import { hydrateAuthoredGraphDocument } from "../canvas/saved-graph";
import type {
  AuthoredGraphDocument,
  AuthoredGraphNode,
} from "../model/graph-document";
import type { PresenceParticipant, RoomInstanceState } from "../room/protocol";
import {
  buildWorkbenchCellScene,
  cellConnectionToWorkbenchConnection,
  cellRemotePeersFromParticipants,
  encodeCellPortHandleForDiscovery,
  partitionCellMoves,
  partitionCellRemovals,
  partitionCellSelection,
} from "./workbench-cell-canvas";

const type = { id: "scalar.text", schema_version: 2 };
const output: Port = {
  name: "result",
  kind: "artifact",
  direction: "output",
  artifact_type: type,
  accepted_shapes: ["one"],
  shape: "one",
  required: true,
  variadic: false,
  instance_plugs: false,
};
const input: Port = {
  ...output,
  name: "items",
  direction: "input",
  artifact_type: null,
  artifact_type_variable: "T",
  instance_plugs: true,
};
const spec: NodeSpec = {
  operator_id: "test.text",
  operator_version: 1,
  title: "Text",
  description: "",
  plugin_slug: "test",
  origin: "builtin",
  runnable: true,
  catalog_visible: true,
  input_schema: {},
  output_schema: {},
  config_schema: {},
  inputs: [input],
  outputs: [output],
};
const registry: NodeRegistry = {
  nodes: [spec],
  artifact_types: [],
  artifact_conversions: [],
  plugins: [],
};
const source: AuthoredGraphNode = {
  id: "source",
  kind: "builtin",
  operator_id: spec.operator_id,
  operator_version: spec.operator_version,
  position: { x: 0, y: 0 },
  layout: null,
  config: {},
  input_plugs: [],
  artifact_type_bindings: [],
};
const artifact = {
  artifact_id: "a",
  artifact_type: type.id,
  schema_version: 2,
};
const graph: AuthoredGraphDocument = {
  name: "Test",
  nodes: [
    source,
    {
      ...source,
      id: "target",
      position: { x: 500, y: 0 },
      input_plugs: [{ port: "items", id: "plug-a" }],
      artifact_type_bindings: [{ variable: "T", artifact_type: type }],
    },
  ],
  edges: [
    {
      id: "edge",
      from_node: "source",
      from_port: "result",
      to_node: "target",
      to_port: "items",
      to_plug: "plug-a",
      collection_mode: "direct",
      enabled: true,
      conversion_path: [],
    },
  ],
  agents: [
    {
      id: "agent",
      name: "Agent",
      instructions: "",
      model: {
        kind: "custom",
        model: "test",
        endpoint: "https://example.test",
      },
      width: 400,
      height: 100,
      position: { x: 0, y: 100 },
      context: [],
      tools: [],
    },
  ],
  origins: [],
};
const presentation: GraphPresentation = {
  viewers: [
    {
      id: "card",
      position: { x: 0, y: 300 },
      artifact_ref: artifact,
      mode: "artifact",
    },
  ],
  links: [
    {
      id: "link",
      source_node_id: "source",
      source_port_name: "result",
      target_viewer_id: "card",
    },
  ],
  annotations: [
    {
      id: "note",
      kind: "text",
      position: { x: 0, y: 500 },
      layout: { width: 150, height: 100 },
      text: "Note",
      color: "#475569",
    },
  ],
  bindings: [],
};
const viewers = artifactViewersFromPresentation(presentation);
const { nodes } = hydrateAuthoredGraphDocument(graph, registry);
const [sourceNode, targetNode] = nodes;
assert(sourceNode && targetNode);
const candidate = {
  sourceCardId: "source",
  sourcePortId: "result",
  targetCardId: "target",
  targetPortId: "items::plug-a",
};

describe("buildWorkbenchCellScene", () => {
  const artifactResult = { ...artifact, content_hash: null };
  const run = {
    node_id: "source",
    status: "succeeded",
    error: null,
    outputs: [
      {
        port: "result",
        kind: "single",
        artifacts: [artifactResult],
        value: artifact,
      },
    ],
    result_fingerprint: "result",
    created_at: null,
  } satisfies NonNullable<typeof sourceNode.data.run>;
  const instance = {
    project_id: "project",
    graph_id: "graph",
    call_path: [],
    node_id: "source",
    map_index: null,
    state: "fresh",
    fingerprint: "instance",
    last_result_fingerprint: "result",
    error: null,
  } satisfies RoomInstanceState;
  const scene = (state: RoomInstanceState["state"], canRun = true) =>
    buildWorkbenchCellScene({
      document: graph,
      registry,
      presentation,
      nodes: [{ ...sourceNode, data: { ...sourceNode.data, run } }, targetNode],
      nodeInstanceStates: {
        source: {
          ...instance,
          state,
          error: state === "failed" ? "Broken" : null,
        },
      },
      collapsedAppendices: new Set(["source"]),
      canRun,
    });
  it.each([
    ["queued", "working", "Queued"],
    ["running", "working", "Running"],
    ["fresh", "done", "Fresh"],
    ["stale", "idle", "Stale"],
    ["failed", "error", "Error"],
  ] as const)(
    "maps %s room state to the card",
    (state, status, statusLabel) => {
      const { graph, surfaceById } = scene(state);
      expect(graph.cards.find(({ id }) => id === "source")).toMatchObject({
        status,
      });
      expect(surfaceById.source).toMatchObject({
        statusLabel,
        runDisabled: false,
      });
    },
  );
  it("builds output and error appendices with the saved collapse state", () => {
    expect(scene("fresh", false).surfaceById.source).toMatchObject({
      runDisabled: true,
      appendix: {
        collapsed: true,
        itemCount: 1,
        summaryText: "1 output port",
        previewLines: ["result: 1 artifact"],
      },
    });
    expect(scene("failed").surfaceById.source).toMatchObject({
      appendix: { collapsed: true, summaryText: "Broken", kindBadge: "Error" },
    });
  });
});

it("maps only remote sessions on the open graph", () => {
  const peer: PresenceParticipant = {
    project_room_session_id: "remote",
    actor: { actor_id: "person", display_name: "Ada", color: "teal" },
    graph_id: "graph",
    presence_sequence: 1,
    cursor: { x: 20, y: 40 },
    selected_node_ids: ["target"],
    selected_edge_ids: [],
    activity: "moving_nodes",
    activity_target_ids: ["target"],
    transient_node_positions: [{ node_id: "target", x: 26, y: -49 }],
  };
  expect(
    cellRemotePeersFromParticipants(
      [
        peer,
        { ...peer, project_room_session_id: "local" },
        { ...peer, project_room_session_id: "other", graph_id: "other" },
      ],
      "local",
      "graph",
    ),
  ).toEqual([
    {
      actorId: "person",
      sessionId: "remote",
      displayName: "Ada",
      color: "#0d9488",
      cursor: { x: 20, y: 40 },
      selectedCardIds: ["target"],
      activity: "moving_nodes",
      draggingCards: { target: { col: 1, row: -2 } },
    },
  ]);
});

it("encodes the discovery port with its resolved type and plug id", () => {
  expect(
    encodeCellPortHandleForDiscovery(targetNode, "items::plug-a", "input"),
  ).toMatchObject({
    port: { name: "items" },
    handleId: "items::scalar.text::2::one::input::plug-a",
    decoded: {
      portName: "items",
      plugId: "plug-a",
      artifactTypeId: "scalar.text",
      schemaVersion: 2,
    },
  });
  expect(
    encodeCellPortHandleForDiscovery(targetNode, "items::plug-a", "output"),
  ).toBeNull();
});

it("uses the rendered shape for mapped outputs and the declared shape for inputs", () => {
  const mapped = {
    ...targetNode,
    data: { ...targetNode.data, mappedInputPorts: ["items"] },
  };
  expect(
    encodeCellPortHandleForDiscovery(mapped, "result", "output")?.decoded.shape,
  ).toBe("many");
  expect(
    encodeCellPortHandleForDiscovery(mapped, "items::plug-a", "input")?.decoded
      .shape,
  ).toBe("one");
});

it("translates workflow connections and rejects a missing port", () => {
  expect(
    cellConnectionToWorkbenchConnection(nodes, viewers.nodes, candidate),
  ).toEqual({
    source: "source",
    sourceHandle: "result::scalar.text::2::one::output",
    target: "target",
    targetHandle: "items::scalar.text::2::one::input::plug-a",
  });
  expect(
    cellConnectionToWorkbenchConnection(nodes, viewers.nodes, {
      ...candidate,
      targetPortId: "missing",
    }),
  ).toBeNull();
});

it("preserves the dedicated artifact card and viewer handles", () => {
  expect(
    cellConnectionToWorkbenchConnection(nodes, viewers.nodes, {
      ...candidate,
      sourceCardId: "card",
      sourcePortId: ARTIFACT_CARD_OUTPUT_HANDLE,
    }),
  ).toMatchObject({
    source: "card",
    sourceHandle: ARTIFACT_CARD_OUTPUT_HANDLE,
  });
  expect(
    cellConnectionToWorkbenchConnection(nodes, viewers.nodes, {
      ...candidate,
      targetCardId: "card",
      targetPortId: ARTIFACT_VIEWER_INPUT_HANDLE,
    }),
  ).toMatchObject({
    target: "card",
    targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
  });
});

it("partitions mixed selection across authoring and presentation", () => {
  expect(
    partitionCellSelection(
      {
        cardIds: new Set(["source", "agent", "card", "note", "unknown"]),
        pipeIds: new Set(["edge", "link"]),
      },
      graph,
      viewers,
    ),
  ).toEqual({
    nodeIds: ["source"],
    agentIds: ["agent"],
    viewerIds: ["card"],
    annotationIds: ["note"],
    edgeIds: ["edge", "link"],
  });
});

it("partitions mixed moves and converts cells to world coordinates", () => {
  expect(
    partitionCellMoves(
      ["source", "agent", "card", "note", "unknown"].map((cardId) => ({
        cardId,
        col: 3,
        row: -2,
      })),
      graph,
      viewers,
    ),
  ).toEqual({
    graphCommands: [
      { kind: "move_nodes", positions: [{ node_id: "source", x: 75, y: -50 }] },
      {
        kind: "configure_agent",
        agent: { ...graph.agents[0], position: { x: 75, y: -50 } },
      },
    ],
    viewerPositions: [{ viewer_id: "card", x: 75, y: -50 }],
    annotationPositions: [{ annotation_id: "note", x: 75, y: -50 }],
  });
});

it("partitions removals and includes links incident to removed cards", () => {
  expect(
    partitionCellRemovals(
      ["source", "agent", "card", "note", "unknown"],
      ["edge"],
      graph,
      viewers,
    ),
  ).toEqual({
    graphCommands: [
      { kind: "remove_edges", edge_ids: ["edge"] },
      { kind: "remove_nodes", node_ids: ["source"] },
      { kind: "remove_agent", agent_id: "agent" },
    ],
    removedWorkflowNodeIds: ["source"],
    removedViewerIds: ["card"],
    removedAnnotationIds: ["note"],
    removedViewerEdgeIds: ["link"],
  });
  expect(
    partitionCellRemovals([], ["link"], graph, viewers).removedViewerEdgeIds,
  ).toEqual(["link"]);
});

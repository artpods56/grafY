import { assert, describe, expect, it } from "vitest";

import {
  artifactInlineContentUrl,
  type NodeRegistry,
  type NodeSpec,
  type PlacedLibraryItem,
  type Port,
} from "@/lib/api";
import { imagePath, imageThumbnailUrl } from "@/lib/api/images";
import { ARTIFACT_CARD_OUTPUT_HANDLE } from "../artifacts/artifact-connections";
import {
  ARTIFACT_ORIGIN_EDGE_TYPE,
  type ArtifactOriginEdge,
} from "../artifacts/artifact-origin-edge";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_INPUT_HANDLE,
  artifactViewersFromPresentation,
  type ArtifactViewerEdge,
  type GraphPresentation,
} from "../artifacts/artifact-viewer";
import { hydrateAuthoredGraphDocument } from "../authoring/saved-graph";
import type {
  WorkflowEdge,
  WorkflowNode,
  WorkflowNodeConfig,
} from "../authoring/types";
import type {
  AuthoredGraphDocument,
  AuthoredGraphNode,
} from "../authoring/graph-document";
import {
  instanceKeyText,
  type PresenceParticipant,
  type RoomInstanceState,
} from "../collaboration/protocol";
import {
  buildAppendixSpec,
  buildWorkbenchCellScene,
  cellConnectionToWorkbenchConnection,
  cellRemotePeersFromParticipants,
  resolveCellPortEndpoint,
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
  pack_slugs: [],
  role: "operator",
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
  packs: [],
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
  const scene = (
    state: RoomInstanceState["state"],
    canRun = true,
    runDisabledReason?: string,
  ) =>
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
      runDisabledReason,
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
  it("explains a blocked run on the operator surface only while running is unavailable", () => {
    const reason = "Save the graph before running it.";
    expect(scene("fresh", false, reason).surfaceById.source).toMatchObject({
      runDisabled: true,
      runDisabledReason: reason,
    });
    expect(scene("fresh", true, reason).surfaceById.source).not.toHaveProperty(
      "runDisabledReason",
    );
  });

  it("builds output and error appendices with the saved collapse state", () => {
    expect(scene("fresh", false).surfaceById.source).toMatchObject({
      runDisabled: true,
      appendix: {
        kind: "output",
        title: "Outputs",
        collapsed: true,
        itemCount: 1,
        summaryText: "1 item",
        heightCells: 3,
        outputs: [
          {
            port: "result",
            label: "result",
            count: 1,
            kind: "single",
            typeLabel: "scalar.text@2",
            typeKey: "scalar.text@2",
            toneColor: "light-dark(#b46735, #e88a50)",
            artifactIds: ["a"],
          },
        ],
      },
    });
    expect(scene("failed").surfaceById.source).toMatchObject({
      appendix: {
        kind: "error",
        title: "Run failed",
        collapsed: true,
        summaryText: "Broken",
        errorText: "Broken",
        kindBadge: "Error",
        heightCells: 4,
      },
    });
  });

  it("resolves human port labels, catalog artifact type labels, port tones, and bounded cell heights", () => {
    const ocrSpec: NodeSpec = {
      ...spec,
      operator_id: "ocr.document",
      title: "Document OCR",
      inputs: [],
      outputs: [
        {
          ...output,
          name: "markdown",
          title: "Transcription",
          artifact_type: { id: "text.markdown", schema_version: 1 },
          shape: "one",
        },
        {
          ...output,
          name: "blocks",
          title: "Text blocks",
          artifact_type: { id: "ocr.document_result", schema_version: 1 },
          shape: "many",
        },
        {
          ...output,
          name: "regions",
          title: "Boxes on the page",
          artifact_type: { id: "ocr.tiff_text_regions", schema_version: 2 },
          shape: "many",
        },
      ],
    };
    const ocrRegistry: NodeRegistry = {
      ...registry,
      nodes: [ocrSpec],
      artifact_types: [
        {
          key: { id: "text.markdown", schema_version: 1 },
          title: "Markdown",
          preview_kind: "markdown",
          bundle: { format: "inline-json", version: 1 },
          field_projections: [],
          payload_schema: {},
        },
        {
          key: { id: "ocr.document_result", schema_version: 1 },
          title: "Document OCR blocks",
          preview_kind: "text",
          bundle: { format: "inline-json", version: 1 },
          field_projections: [],
          payload_schema: {},
        },
        {
          key: { id: "ocr.tiff_text_regions", schema_version: 2 },
          title: "Page regions",
          preview_kind: "tiff-text",
          bundle: { format: "inline-json", version: 1 },
          field_projections: [],
          payload_schema: {},
        },
      ],
    };
    const ocrNode: WorkflowNode = {
      ...sourceNode,
      id: "ocr",
      data: {
        ...sourceNode.data,
        spec: ocrSpec,
        run: {
          node_id: "ocr",
          status: "succeeded",
          error: null,
          // Intentionally scrambled order relative to spec.outputs
          outputs: [
            {
              port: "regions",
              kind: "sequence",
              artifacts: [
                {
                  artifact_id: "r1",
                  artifact_type: "ocr.tiff_text_regions",
                  schema_version: 2,
                  content_hash: null,
                },
                {
                  artifact_id: "r2",
                  artifact_type: "ocr.tiff_text_regions",
                  schema_version: 2,
                  content_hash: null,
                },
              ],
              value: {
                artifact_type: "ocr.tiff_text_regions",
                schema_version: 2,
                index_key: "index",
                ordered: true,
                item_refs: [],
              },
            },
            {
              port: "blocks",
              kind: "sequence",
              artifacts: [
                {
                  artifact_id: "b1",
                  artifact_type: "ocr.document_result",
                  schema_version: 1,
                  content_hash: null,
                },
                {
                  artifact_id: "b2",
                  artifact_type: "ocr.document_result",
                  schema_version: 1,
                  content_hash: null,
                },
                {
                  artifact_id: "b3",
                  artifact_type: "ocr.document_result",
                  schema_version: 1,
                  content_hash: null,
                },
              ],
              value: {
                artifact_type: "ocr.document_result",
                schema_version: 1,
                index_key: "index",
                ordered: true,
                item_refs: [],
              },
            },
            {
              port: "markdown",
              kind: "single",
              artifacts: [
                {
                  artifact_id: "m1",
                  artifact_type: "text.markdown",
                  schema_version: 1,
                  content_hash: null,
                },
              ],
              value: {
                artifact_id: "m1",
                artifact_type: "text.markdown",
                schema_version: 1,
              },
            },
          ],
          result_fingerprint: "ocr-res",
          created_at: "2026-11-24T01:55:00.000Z",
        },
      },
    };
    const appendix = buildAppendixSpec({
      node: ocrNode,
      status: "done",
      registry: ocrRegistry,
      nowMs: Date.parse("2026-11-24T02:00:00.000Z"),
    });
    expect(appendix).toEqual({
      kind: "output",
      title: "Outputs",
      kindBadge: "Output",
      summaryText: "3 outputs · 6 items",
      previewLines: [
        "Transcription: 1 item",
        "Text blocks: 3 items",
        "Boxes on the page: 2 items",
      ],
      itemCount: 6,
      completedAtLabel: "5m ago",
      heightCells: 5,
      outputs: [
        {
          port: "markdown",
          label: "Transcription",
          count: 1,
          kind: "single",
          typeLabel: "Markdown",
          typeKey: "text.markdown@1",
          toneColor: "light-dark(#b46735, #e88a50)",
          artifactIds: ["m1"],
        },
        {
          port: "blocks",
          label: "Text blocks",
          count: 3,
          kind: "sequence",
          typeLabel: "Document OCR blocks",
          typeKey: "ocr.document_result@1",
          toneColor: "light-dark(#7b63c9, #9a7cf2)",
          artifactIds: ["b1", "b2", "b3"],
        },
        {
          port: "regions",
          label: "Boxes on the page",
          count: 2,
          kind: "sequence",
          typeLabel: "Page regions · v2",
          typeKey: "ocr.tiff_text_regions@2",
          toneColor: "light-dark(#7b63c9, #9a7cf2)",
          artifactIds: ["r1", "r2"],
        },
      ],
    });

    // Without a registry catalog, typeLabel falls back to full id@version.
    const noCatalog = buildAppendixSpec({
      node: ocrNode,
      status: "done",
      registry: null,
    });
    expect(noCatalog?.outputs?.[0]?.typeLabel).toBe("text.markdown@1");

    // 1 output port sizes expanded height to 3 cells (header + 1 row, no extra padding).
    const singleOutputNode: WorkflowNode = {
      ...ocrNode,
      data: {
        ...ocrNode.data,
        run: {
          ...ocrNode.data.run!,
          outputs: [ocrNode.data.run!.outputs[0]!],
        },
      },
    };
    expect(
      buildAppendixSpec({
        node: singleOutputNode,
        status: "done",
        registry: ocrRegistry,
      })?.heightCells,
    ).toBe(3);

    // 8 output ports cap expanded height at 8 cells (header + 6 visible rows).
    const manyOutputsNode: WorkflowNode = {
      ...ocrNode,
      data: {
        ...ocrNode.data,
        run: {
          ...ocrNode.data.run!,
          outputs: Array.from({ length: 8 }, (_, index) => ({
            port: `out_${index}`,
            kind: "single" as const,
            artifacts: [
              {
                artifact_id: `art-${index}`,
                artifact_type: "text.markdown",
                schema_version: 1,
                content_hash: null,
              },
            ],
            value: {
              artifact_id: `art-${index}`,
              artifact_type: "text.markdown",
              schema_version: 1,
            },
          })),
        },
      },
    };
    expect(
      buildAppendixSpec({
        node: manyOutputsNode,
        status: "done",
        registry: ocrRegistry,
      })?.heightCells,
    ).toBe(8);

    // Multi-line errors grow up to 6 cells without overflowing the card.
    const longErrorNode: WorkflowNode = {
      ...ocrNode,
      data: {
        ...ocrNode.data,
        run: {
          ...ocrNode.data.run!,
          status: "failed",
          error: Array.from(
            { length: 7 },
            (_, idx) =>
              `Line ${idx + 1}: provider returned an unexpected failure`,
          ).join("\n"),
        },
      },
    };
    expect(
      buildAppendixSpec({ node: longErrorNode, status: "error" }),
    ).toMatchObject({
      kind: "error",
      title: "Run failed",
      heightCells: 6,
    });
  });

  it("attaches live progress and cancel only while the node is running on this call trail", () => {
    const key = instanceKeyText({
      project_id: "project",
      graph_id: "graph",
      call_path: [],
      node_id: "source",
      map_index: null,
    });
    const otherKey = instanceKeyText({
      project_id: "project",
      graph_id: "graph",
      call_path: ["other"],
      node_id: "source",
      map_index: null,
    });
    const entries = [
      {
        sequence: 2,
        message: "Parsing OCR pages…",
        current: 3,
        total: 12,
        fingerprint: "instance",
      },
      {
        sequence: 1,
        message: "Sending document to Mistral OCR…",
        current: null,
        total: null,
        fingerprint: "instance",
      },
    ];
    const progress = new Map([
      [key, { entries }],
      [
        otherKey,
        {
          entries: [
            {
              sequence: 9,
              message: "Wrong trail",
              current: 1,
              total: 2,
              fingerprint: "instance",
            },
          ],
        },
      ],
    ]);
    const runs = [
      {
        run_id: "run-1",
        graph_id: "graph",
        targets: [{ node_id: "source", call_path: [] as string[] }],
        starter: null,
        started_at: "2026-08-07T10:00:00Z",
        cancellable: true,
      },
    ];
    const cancelled: string[] = [];
    const liveRun = {
      projectId: "project",
      graphId: "graph",
      callPath: [] as readonly string[],
      progress,
      runs,
      cancellingRunIds: new Set<string>(),
      canCancelRun: true,
      onCancelNodeRun: (nodeId: string) => cancelled.push(nodeId),
    };
    const withLive = (state: RoomInstanceState["state"]) =>
      buildWorkbenchCellScene({
        document: graph,
        registry,
        presentation,
        nodes: [
          { ...sourceNode, data: { ...sourceNode.data, run } },
          targetNode,
        ],
        nodeInstanceStates: {
          source: { ...instance, state, error: null },
        },
        collapsedAppendices: new Set(),
        canRun: true,
        liveRun,
      });

    const running = withLive("running").surfaceById.source;
    expect(running).toMatchObject({
      kind: "operator",
      progress: {
        latestMessage: "Parsing OCR pages…",
        current: 3,
        total: 12,
        recentMessages: [
          {
            sequence: 2,
            message: "Parsing OCR pages…",
            current: 3,
            total: 12,
          },
          {
            sequence: 1,
            message: "Sending document to Mistral OCR…",
            current: null,
            total: null,
          },
        ],
      },
      cancelling: false,
      canCancel: true,
    });
    if (running?.kind === "operator") running.onCancelRun?.();
    expect(cancelled).toEqual(["source"]);

    const finished = withLive("fresh").surfaceById.source;
    expect(finished).not.toHaveProperty("progress");
    expect(finished).not.toHaveProperty("canCancel");

    const staleFrame = withLive("running");
    const mismatched = buildWorkbenchCellScene({
      document: graph,
      registry,
      presentation,
      nodes: [{ ...sourceNode, data: { ...sourceNode.data, run } }, targetNode],
      nodeInstanceStates: {
        source: { ...instance, state: "running", fingerprint: "next" },
      },
      collapsedAppendices: new Set(),
      canRun: true,
      liveRun,
    }).surfaceById.source;
    expect(staleFrame.surfaceById.source).toHaveProperty("progress");
    expect(mismatched).not.toHaveProperty("progress");
    expect(mismatched).toMatchObject({ canCancel: true });

    const otherTrail = buildWorkbenchCellScene({
      document: graph,
      registry,
      presentation,
      nodes: [{ ...sourceNode, data: { ...sourceNode.data, run } }, targetNode],
      nodeInstanceStates: {
        source: { ...instance, state: "running" },
      },
      collapsedAppendices: new Set(),
      canRun: true,
      liveRun: { ...liveRun, callPath: ["other"], progress: new Map() },
    }).surfaceById.source;
    expect(otherTrail).not.toHaveProperty("progress");
    expect(otherTrail).toMatchObject({ canCancel: false });
  });

  it("cancels the sole run from an upstream node and refuses a second cancel", () => {
    const runs = [
      {
        run_id: "run-1",
        graph_id: "graph",
        targets: [{ node_id: "target", call_path: [] as string[] }],
        starter: null,
        started_at: "2026-08-07T10:00:00Z",
        cancellable: true,
      },
    ];
    const base = {
      document: graph,
      registry,
      presentation,
      nodes: [{ ...sourceNode, data: { ...sourceNode.data, run } }, targetNode],
      collapsedAppendices: new Set<string>(),
      canRun: true,
    };
    const instances = {
      source: { ...instance, state: "queued" as const },
      target: {
        ...instance,
        node_id: "target",
        state: "running" as const,
      },
    };
    const live = (
      cancellingRunIds: ReadonlySet<string>,
      canCancelRun = true,
      nextRuns = runs,
    ) =>
      buildWorkbenchCellScene({
        ...base,
        nodeInstanceStates: instances,
        liveRun: {
          projectId: "project",
          graphId: "graph",
          callPath: [],
          runs: nextRuns,
          cancellingRunIds,
          canCancelRun,
          onCancelNodeRun: () => {},
        },
      });

    const idle = new Set<string>();
    expect(live(idle).surfaceById.source).toMatchObject({
      canCancel: true,
      cancelling: false,
    });
    expect(live(idle).surfaceById.target).toMatchObject({
      canCancel: true,
      cancelling: false,
    });
    expect(live(new Set(["run-1"])).surfaceById.source).toMatchObject({
      canCancel: false,
      cancelling: true,
    });
    expect(live(new Set(["run-1"])).surfaceById.target).toMatchObject({
      canCancel: false,
      cancelling: true,
    });
    expect(live(idle, false).surfaceById.target).toMatchObject({
      canCancel: false,
    });
    const first = runs[0];
    if (!first) throw new Error("expected a run");
    expect(
      live(idle, true, [
        first,
        {
          ...first,
          run_id: "run-2",
          targets: [{ node_id: "elsewhere", call_path: [] }],
          started_at: "2026-08-07T11:00:00Z",
        },
      ]).surfaceById.source,
    ).toMatchObject({ canCancel: false });
  });

  it("keeps a second node's run cancellable while the first run is cancelling", () => {
    const scene = buildWorkbenchCellScene({
      document: graph,
      registry,
      presentation,
      nodes: [{ ...sourceNode, data: { ...sourceNode.data, run } }, targetNode],
      collapsedAppendices: new Set<string>(),
      canRun: true,
      nodeInstanceStates: {
        source: { ...instance, state: "running" },
        target: {
          ...instance,
          node_id: "target",
          state: "running",
          fingerprint: "target-instance",
        },
      },
      liveRun: {
        projectId: "project",
        graphId: "graph",
        callPath: [],
        runs: [
          {
            run_id: "run-1",
            graph_id: "graph",
            targets: [{ node_id: "source", call_path: [] }],
            starter: null,
            started_at: "2026-08-07T10:00:00Z",
            cancellable: true,
          },
          {
            run_id: "run-2",
            graph_id: "graph",
            targets: [{ node_id: "target", call_path: [] }],
            starter: null,
            started_at: "2026-08-07T10:01:00Z",
            cancellable: true,
          },
        ],
        cancellingRunIds: new Set(["run-1"]),
        canCancelRun: true,
        onCancelNodeRun: () => {},
      },
    });

    expect(scene.surfaceById.source).toMatchObject({
      cancelling: true,
      canCancel: false,
    });
    expect(scene.surfaceById.target).toMatchObject({
      cancelling: false,
      canCancel: true,
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

it("resolves a cell port endpoint with its type and plug id", () => {
  expect(
    resolveCellPortEndpoint(targetNode, "items::plug-a", "input"),
  ).toMatchObject({
    port: { name: "items" },
    portName: "items",
    plugId: "plug-a",
    meta: {
      portName: "items",
      plugId: "plug-a",
      artifactTypeId: "scalar.text",
      schemaVersion: 2,
      direction: "input",
      shape: "one",
    },
  });
  expect(
    resolveCellPortEndpoint(targetNode, "items::plug-a", "output"),
  ).toBeNull();
});

it("uses the rendered shape for mapped outputs and the declared shape for inputs", () => {
  const mapped = {
    ...targetNode,
    data: { ...targetNode.data, mappedInputPorts: ["items"] },
  };
  expect(resolveCellPortEndpoint(mapped, "result", "output")?.meta.shape).toBe(
    "many",
  );
  expect(
    resolveCellPortEndpoint(mapped, "items::plug-a", "input")?.meta.shape,
  ).toBe("one");
});

it("translates workflow connections and rejects a missing port", () => {
  expect(
    cellConnectionToWorkbenchConnection(nodes, viewers.nodes, candidate),
  ).toEqual({
    kind: "workflow",
    source: "source",
    sourcePort: "result",
    target: "target",
    targetPort: "items",
    targetPlug: "plug-a",
  });
  expect(
    cellConnectionToWorkbenchConnection(nodes, viewers.nodes, {
      ...candidate,
      targetPortId: "missing",
    }),
  ).toBeNull();
});

it("translates artifact card and viewer connections", () => {
  expect(
    cellConnectionToWorkbenchConnection(nodes, viewers.nodes, {
      ...candidate,
      sourceCardId: "card",
      sourcePortId: ARTIFACT_CARD_OUTPUT_HANDLE,
    }),
  ).toEqual({
    kind: "artifact-card",
    sourceCardId: "card",
    targetNodeId: "target",
    targetPort: "items",
    targetPlug: "plug-a",
  });
  expect(
    cellConnectionToWorkbenchConnection(nodes, viewers.nodes, {
      ...candidate,
      targetCardId: "card",
      targetPortId: ARTIFACT_VIEWER_INPUT_HANDLE,
    }),
  ).toEqual({
    kind: "artifact-viewer",
    sourceNodeId: "source",
    sourcePort: "result",
    targetViewerId: "card",
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

it("wires workflow metadata, live viewer outputs, origin edges, service providers, and origin deletions", () => {
  const serviceOutput: Port = {
    name: "service",
    kind: "service",
    direction: "output",
    artifact_type: null,
    service_contracts: [{ id: "llm.chat", version: 1 }],
    accepted_shapes: ["one"],
    shape: "one",
    required: false,
    variadic: false,
    instance_plugs: false,
  };
  const providerSpec: NodeSpec = {
    ...spec,
    operator_id: "test.provider",
    operator_version: 1,
    title: "Provider",
    inputs: [],
    outputs: [serviceOutput],
  };
  const serviceRegistry: NodeRegistry = {
    ...registry,
    nodes: [spec, providerSpec],
    service_contracts: [
      {
        id: "llm.chat",
        version: 1,
        title: "Chat Service",
      },
    ],
  };
  const providerDocNode: AuthoredGraphNode = {
    ...source,
    id: "provider",
    operator_id: "test.provider",
    operator_version: 1,
  };
  const followingDoc: AuthoredGraphDocument = {
    ...graph,
    nodes: [...graph.nodes, providerDocNode],
    origins: [
      {
        id: "origin-1",
        to_node: "target",
        to_port: "items",
        to_plug: "plug-a",
        source_card_ids: ["card"],
        value: artifact,
        collection_mode: "direct",
        conversion_path: [],
      },
    ],
  };
  const followingPresentation: GraphPresentation = {
    ...presentation,
    viewers: [
      {
        id: "card",
        position: { x: 0, y: 300 },
        artifact_ref: null,
        mode: "artifact",
      },
      {
        id: "card-proj",
        position: { x: 300, y: 300 },
        artifact_ref: artifact,
        mode: "artifact",
      },
    ],
    links: [
      ...presentation.links,
      {
        id: "link-proj",
        source_node_id: "source",
        source_port_name: "result",
        target_viewer_id: "card-proj",
      },
    ],
  };
  const { nodes: hydratedNodes } = hydrateAuthoredGraphDocument(
    followingDoc,
    serviceRegistry,
  );
  const [hydratedSource, hydratedTarget, hydratedProvider] = hydratedNodes;
  assert(hydratedSource && hydratedTarget && hydratedProvider);
  const sourceWithRun = {
    ...hydratedSource,
    data: {
      ...hydratedSource.data,
      run: {
        node_id: "source",
        status: "succeeded" as const,
        error: null,
        outputs: [
          {
            port: "result",
            kind: "single" as const,
            artifacts: [{ ...artifact, content_hash: null }],
            value: artifact,
          },
        ],
        result_fingerprint: "res",
        created_at: null,
      },
    },
  };
  const hydratedViewers = artifactViewersFromPresentation(
    followingPresentation,
  );
  const canvasEdges: WorkflowEdge[] = [
    {
      id: "edge",
      source: "source",
      sourcePort: "result",
      target: "target",
      targetPort: "items",
      targetPlug: "plug-a",
      data: {
        enabled: true,
        collectionMode: "direct",
        projection: { path: ["text"] },
        conversionTitles: ["CSV → Table"],
        compatibilityIssues: ["Incompatible output"],
        routeOptions: [
          {
            projection: { path: ["text"] },
            projectionTitle: "Text body",
            conversionPath: [],
            conversionTitles: ["CSV → Table"],
          },
        ],
      },
    },
  ];
  const viewerEdges: ArtifactViewerEdge[] = [
    {
      id: "link",
      type: ARTIFACT_VIEWER_EDGE_TYPE,
      source: "source",
      target: "card",
      data: {
        sourcePortName: "result",
      },
    },
    {
      id: "link-proj",
      type: ARTIFACT_VIEWER_EDGE_TYPE,
      source: "source",
      target: "card-proj",
      data: {
        sourcePortName: "result",
        projection: { path: ["body"] },
        projectionTitle: "Body",
      },
    },
  ];
  const originEdges: ArtifactOriginEdge[] = [
    {
      id: "artifact-origin:origin-1:card",
      type: ARTIFACT_ORIGIN_EDGE_TYPE,
      source: "card",
      target: "target",
      targetPort: "items",
      targetPlug: "plug-a",
      data: {
        originId: "origin-1",
        collectionMode: "map",
      },
    },
  ];

  const built = buildWorkbenchCellScene({
    document: followingDoc,
    registry: serviceRegistry,
    presentation: followingPresentation,
    nodes: [sourceWithRun, hydratedTarget, hydratedProvider],
    nodeInstanceStates: {},
    collapsedAppendices: new Set(),
    canRun: true,
    canvasEdges,
    artifactViewerEdges: viewerEdges,
    artifactViewerNodes: hydratedViewers.nodes,
    artifactOriginEdges: originEdges,
  });

  expect(built.graph.cards.find((c) => c.id === "provider")?.status).toBe(
    "idle",
  );
  expect(built.surfaceById.provider).toMatchObject({
    runDisabled: true,
  });
  expect(
    built.graph.cards.find((c) => c.id === "card")?.ports.map((p) => p.id),
  ).toEqual([ARTIFACT_VIEWER_INPUT_HANDLE, ARTIFACT_CARD_OUTPUT_HANDLE]);
  expect(built.graph.pipes.find((p) => p.id === "edge")).toMatchObject({
    projectionLabel: "Text body",
    conversionLabel: "CSV → Table",
    incompatible: true,
  });
  expect(built.graph.pipes.find((p) => p.id === "link-proj")).toMatchObject({
    projectionLabel: "Body",
  });
  expect(
    built.graph.pipes.find((p) => p.id === "artifact-origin:origin-1:card"),
  ).toMatchObject({
    collectionMode: "map",
    sourcePortLabel: "artifact",
  });

  const removal = partitionCellRemovals(
    [],
    ["artifact-origin:origin-1:card"],
    followingDoc,
    hydratedViewers,
    originEdges,
  );
  expect(removal.graphCommands).toEqual([
    { kind: "remove_origins", origin_ids: ["origin-1"] },
  ]);
});

describe("artifact card downloads", () => {
  it.each([
    {
      id: "table.data",
      bundle: "table-bundle",
      previewKind: "table",
      authorable: true,
      formats: ["json", "csv", "csv"],
      expected: [
        { format: "csv", label: "CSV" },
        { format: "json", label: "JSON" },
      ],
    },
    {
      id: "scalar.text",
      bundle: "inline-json",
      previewKind: "text",
      authorable: true,
      formats: ["txt"],
      expected: [
        { format: "txt", label: "TXT" },
        { format: "json", label: "JSON" },
      ],
    },
    {
      id: "ocr.tiff_text_regions",
      bundle: "inline-json",
      previewKind: "tiff-text",
      authorable: true,
      formats: [],
      expected: [{ format: "json", label: "JSON" }],
    },
    {
      id: "file.tiff",
      bundle: "binary-file",
      previewKind: "tiff",
      authorable: false,
      formats: [],
      expected: [],
    },
  ] as const)(
    "derives export choices for $id",
    ({ id, bundle, previewKind, authorable, formats, expected }) => {
      const presentation: GraphPresentation = {
        viewers: [
          {
            id: "downloadable",
            position: { x: 0, y: 0 },
            artifact_ref: {
              artifact_id: "artifact-1",
              artifact_type: id,
              schema_version: 1,
            },
            mode: "artifact",
          },
        ],
        links: [],
        annotations: [],
        bindings: [],
      };
      const viewers = artifactViewersFromPresentation(presentation);
      const { surfaceById } = buildWorkbenchCellScene({
        workspaceId: "ws",
        document: graph,
        registry: {
          ...registry,
          artifact_types: [
            {
              key: { id, schema_version: 1 },
              title: id,
              authorable,
              preview_kind: previewKind,
              bundle: { format: bundle, version: 1 },
              export_formats: formats.map((format) => ({
                format,
                content_type: "application/octet-stream",
                filename: `artifact.${format}`,
              })),
              field_projections: [],
              payload_schema: {},
            },
          ],
        },
        presentation,
        nodes: [],
        nodeInstanceStates: {},
        collapsedAppendices: new Set(),
        canRun: false,
        artifactViewerEdges: viewers.edges,
        artifactViewerNodes: viewers.nodes,
      });
      expect(surfaceById.downloadable).toMatchObject({
        downloadFormats: expected,
        inLibrary: false,
      });
    },
  );
});

describe("artifact card pictures", () => {
  const png = (id: string) => ({
    artifact_id: id,
    artifact_type: "file.png",
    schema_version: 1,
  });
  const pictures: GraphPresentation = {
    viewers: [
      {
        id: "png",
        position: { x: 0, y: 300 },
        artifact_ref: png("p 1"),
        mode: "artifact",
      },
      {
        id: "jpeg",
        position: { x: 300, y: 300 },
        artifact_ref: {
          artifact_id: "j",
          artifact_type: "file.jpeg",
          schema_version: 1,
        },
        mode: "artifact",
      },
      {
        id: "tiff",
        position: { x: 600, y: 300 },
        artifact_ref: {
          artifact_id: "t",
          artifact_type: "file.tiff",
          schema_version: 1,
        },
        mode: "artifact",
      },
      {
        id: "pages",
        position: { x: 900, y: 300 },
        artifact_ref: {
          artifact_type: "file.png",
          schema_version: 1,
          index_key: "order_index",
          ordered: true,
          item_refs: [png("s1"), png("s2"), png("s3"), png("s4")],
        },
        mode: "artifact",
      },
      {
        id: "follow",
        position: { x: 0, y: 600 },
        artifact_ref: null,
        mode: "artifact",
      },
    ],
    links: [
      {
        id: "follow-link",
        source_node_id: "source",
        source_port_name: "result",
        target_viewer_id: "follow",
      },
    ],
    annotations: [],
    bindings: [],
  };
  const pictureViewers = artifactViewersFromPresentation(pictures);
  const produced = png("live");
  const run = {
    node_id: "source",
    status: "succeeded",
    error: null,
    outputs: [
      {
        port: "result",
        kind: "single",
        artifacts: [{ ...produced, content_hash: null }],
        value: produced,
      },
    ],
    result_fingerprint: "result",
    created_at: null,
  } satisfies NonNullable<typeof sourceNode.data.run>;
  const build = (
    workspaceId: string | null,
    libraryItemsByArtifactId?: ReadonlyMap<string, PlacedLibraryItem>,
    imageNaturalSizes?: ReadonlyMap<string, { width: number; height: number }>,
  ) =>
    buildWorkbenchCellScene({
      libraryItemsByArtifactId,
      imageNaturalSizes,
      workspaceId,
      document: graph,
      registry,
      presentation: pictures,
      nodes: [{ ...sourceNode, data: { ...sourceNode.data, run } }, targetNode],
      nodeInstanceStates: {},
      collapsedAppendices: new Set(),
      canRun: true,
      artifactViewerEdges: pictureViewers.edges,
      artifactViewerNodes: pictureViewers.nodes,
    });
  const url = (id: string) => artifactInlineContentUrl("ws", id);

  it("names each PNG and JPEG card's bytes through the workspace", () => {
    const { surfaceById } = build("ws");
    expect(surfaceById.png).toMatchObject({
      previewKind: "image",
      imageUrl: url("p 1"),
    });
    expect(surfaceById.jpeg).toMatchObject({
      imageUrl: url("j"),
    });
  });

  it("auto-fits an unsized PNG card to its decoded natural aspect ratio", () => {
    const { graph: fitted } = build(
      "ws",
      undefined,
      new Map([[url("p 1"), { width: 1200, height: 1600 }]]),
    );
    const pngCard = fitted.cards.find((card) => card.id === "png");
    expect(pngCard?.widthCells).toBe(10);
    expect(pngCard?.heightCells).toBe(14);
  });

  it("shows a TIFF through its first-page thumbnail", () => {
    const thumb = imageThumbnailUrl(imagePath("ws", "t"), 0);
    expect(build("ws").surfaceById.tiff).toMatchObject({
      previewKind: "tiff",
      imageUrl: thumb,
      workspaceId: "ws",
      artifact: {
        artifact_id: "t",
        artifact_type: "file.tiff",
        schema_version: 1,
      },
    });
    const { graph: fitted } = build(
      "ws",
      undefined,
      new Map([[thumb, { width: 1200, height: 1600 }]]),
    );
    const tiffCard = fitted.cards.find((card) => card.id === "tiff");
    expect(tiffCard?.widthCells).toBe(10);
    expect(tiffCard?.heightCells).toBe(14);
  });

  it("wires a TIFF card's crop window to its one consumer", () => {
    const patches: [string, WorkflowNodeConfig][] = [];
    const consumer: WorkflowNode = {
      ...targetNode,
      data: {
        ...targetNode.data,
        compatibility: { status: "supported" },
        config: {
          page: 1,
          col: 2,
          row: 3,
          width: 40,
          height: 50,
          scope: "Whole TIFF page",
          strategy: "Single crop",
        },
      },
    };
    const { surfaceById } = buildWorkbenchCellScene({
      workspaceId: "ws",
      document: graph,
      registry,
      presentation: pictures,
      nodes: [{ ...sourceNode, data: { ...sourceNode.data, run } }, consumer],
      nodeInstanceStates: {},
      collapsedAppendices: new Set(),
      canRun: true,
      artifactViewerEdges: pictureViewers.edges,
      artifactViewerNodes: pictureViewers.nodes,
      artifactOriginEdges: [
        {
          id: "origin-edge",
          type: ARTIFACT_ORIGIN_EDGE_TYPE,
          source: "tiff",
          target: "target",
          targetPort: "tiff",
          data: { originId: "origin-tiff" },
        },
      ],
      onOperatorConfigChange: (nodeId, patch) => {
        patches.push([nodeId, patch]);
      },
    });
    const surface = surfaceById.tiff;
    assert(surface?.kind === "artifact");
    expect(surface.tiffWindow).toMatchObject({
      artifactId: "t",
      selection: {
        window: { page: 1, col: 2, row: 3, width: 40, height: 50 },
        wholePage: true,
        singleCrop: true,
      },
    });
    surface.tiffWindow?.selection.onChange({
      page: 2,
      col: 0,
      row: 0,
      width: 8,
      height: 9,
    });
    expect(patches).toEqual([
      ["target", { page: 2, col: 0, row: 0, width: 8, height: 9 }],
    ]);
  });

  it("links TIFF text to the scan window its producer reads", () => {
    const textArtifact = {
      artifact_id: "regions",
      artifact_type: "ocr.tiff_recognized_text",
      schema_version: 1,
    };
    const textPresentation: GraphPresentation = {
      viewers: [
        {
          id: "regions",
          position: { x: 0, y: 0 },
          artifact_ref: null,
          mode: "artifact",
        },
      ],
      links: [
        {
          id: "feed",
          source_node_id: "source",
          source_port_name: "result",
          target_viewer_id: "regions",
        },
      ],
      annotations: [],
      bindings: [],
    };
    const textViewers = artifactViewersFromPresentation(textPresentation);
    const textRun = {
      node_id: "source",
      status: "succeeded",
      error: null,
      outputs: [
        {
          port: "result",
          kind: "single",
          artifacts: [{ ...textArtifact, content_hash: null }],
          value: textArtifact,
        },
      ],
      result_fingerprint: "result",
      created_at: null,
    } satisfies NonNullable<typeof sourceNode.data.run>;
    const producer = {
      ...sourceNode,
      data: {
        ...sourceNode.data,
        config: { page: 0, col: 4, row: 5, width: 6, height: 7 },
        run: textRun,
      },
    };
    const { surfaceById } = buildWorkbenchCellScene({
      workspaceId: "ws",
      document: {
        ...graph,
        origins: [
          {
            id: "fed-tiff",
            to_node: "source",
            to_port: "tiff",
            collection_mode: "direct",
            conversion_path: [],
            value: {
              artifact_id: "scan",
              artifact_type: "file.tiff",
              schema_version: 1,
            },
          },
        ],
      },
      registry,
      presentation: textPresentation,
      nodes: [producer, targetNode],
      nodeInstanceStates: {},
      collapsedAppendices: new Set(),
      canRun: true,
      artifactViewerEdges: textViewers.edges,
      artifactViewerNodes: textViewers.nodes,
      onOperatorConfigChange: () => {},
    });
    const surface = surfaceById.regions;
    assert(surface?.kind === "artifact");
    expect(surface.previewKind).toBe("tiff-text");
    expect(surface.tiffText).toMatchObject({
      url: artifactInlineContentUrl("ws", "regions"),
      recognized: true,
      linkedWindow: {
        artifactId: "scan",
        selection: {
          window: { page: 0, col: 4, row: 5, width: 6, height: 7 },
        },
      },
    });
  });

  it("shows a linked TIFF on a text card before its producer runs", () => {
    const textType = { id: "ocr.tiff_text_regions", schema_version: 1 };
    const textSpec: NodeSpec = {
      ...spec,
      operator_id: "test.tiff-text",
      outputs: [{ ...output, artifact_type: textType }],
    };
    const textRegistry: NodeRegistry = { ...registry, nodes: [spec, textSpec] };
    const textGraph: AuthoredGraphDocument = {
      ...graph,
      nodes: graph.nodes.map((node) =>
        node.id === "source"
          ? { ...node, operator_id: textSpec.operator_id }
          : node,
      ),
      origins: [
        {
          id: "fed-tiff",
          to_node: "source",
          to_port: "tiff",
          collection_mode: "direct",
          conversion_path: [],
          value: {
            artifact_id: "scan",
            artifact_type: "file.tiff",
            schema_version: 1,
          },
        },
      ],
    };
    const waiting: GraphPresentation = {
      viewers: [
        {
          id: "regions",
          position: { x: 0, y: 0 },
          artifact_ref: null,
          mode: "artifact",
        },
      ],
      links: [
        {
          id: "feed",
          source_node_id: "source",
          source_port_name: "result",
          target_viewer_id: "regions",
        },
      ],
      annotations: [],
      bindings: [],
    };
    const { nodes: hydrated } = hydrateAuthoredGraphDocument(
      textGraph,
      textRegistry,
    );
    const textSource = hydrated.find((node) => node.id === "source");
    const textTarget = hydrated.find((node) => node.id === "target");
    assert(textSource && textTarget);
    const producer = {
      ...textSource,
      data: {
        ...textSource.data,
        config: { page: 0, col: 4, row: 5, width: 6, height: 7 },
      },
    };
    const thumb = imageThumbnailUrl(imagePath("ws", "scan"), 0);
    const viewers = artifactViewersFromPresentation(waiting);
    const input = {
      workspaceId: "ws",
      document: textGraph,
      registry: textRegistry,
      presentation: waiting,
      nodes: [producer, textTarget],
      nodeInstanceStates: {},
      collapsedAppendices: new Set<string>(),
      canRun: true,
      artifactViewerEdges: viewers.edges,
      artifactViewerNodes: viewers.nodes,
      imageNaturalSizes: new Map([[thumb, { width: 1200, height: 1600 }]]),
      onOperatorConfigChange: () => {},
    };
    const { graph: fitted, surfaceById } = buildWorkbenchCellScene(input);
    const surface = surfaceById.regions;
    assert(surface?.kind === "artifact");
    expect(surface.previewKind).toBe("tiff-text");
    expect(surface.artifact).toBeUndefined();
    expect(surface.workspaceId).toBe("ws");
    expect(surface.tiffText).toMatchObject({
      url: null,
      recognized: false,
      linkedWindow: {
        artifactId: "scan",
        selection: {
          window: { page: 0, col: 4, row: 5, width: 6, height: 7 },
        },
      },
    });
    const card = fitted.cards.find((item) => item.id === "regions");
    expect(card?.widthCells).toBe(10);
    expect(card?.heightCells).toBe(14);

    // A producer with no TIFF input links no window. Its card still gets the
    // surface that keeps the last scan open.
    const unlinked = buildWorkbenchCellScene({
      ...input,
      document: { ...textGraph, origins: [] },
    }).surfaceById.regions;
    assert(unlinked?.kind === "artifact");
    expect(unlinked.tiffText).toEqual({ url: null, recognized: false });
  });

  it("shows what a following card's run produced", () => {
    expect(build("ws").surfaceById.follow).toMatchObject({
      previewKind: "image",
      artifactTypeId: "file.png",
      imageUrl: url("live"),
    });
  });

  it("gives a sequence its first picture and the next two", () => {
    const pages = build("ws").surfaceById.pages;
    expect(pages).toMatchObject({
      imageUrl: url("s1"),
      stackImageUrls: [url("s2"), url("s3")],
      itemCount: 4,
    });
  });

  it("names a single artifact's card after its Library file", () => {
    const libraryItem = (
      id: string,
      name: string,
      originalFilename: string | null,
      byteSize: number,
    ): PlacedLibraryItem => ({
      artifact: {
        artifact_id: id,
        artifact_type: "file.jpeg",
        schema_version: 1,
        sha256: `hash-${id}`,
        content_url: `/v1/artifacts/${id}/content`,
        content_type: "image/jpeg",
        byte_size: byteSize,
        download_formats: [],
        metadata: {},
      },
      name,
      provenance: {
        source: "upload",
        call_path: [],
        saved_at: "2026-11-20T12:00:00Z",
        original_filename: originalFilename,
      },
      folder_id: null,
    });
    const library = new Map([
      ["j", libraryItem("j", "Amalfi", "amalfi.jpg", 248_000)],
      ["p 1", libraryItem("p 1", "harbour", null, 900)],
      ["s1", libraryItem("s1", "page-1", "page-1.png", 10)],
    ]);
    const { surfaceById } = build("ws", library);
    expect(surfaceById.jpeg).toMatchObject({
      filename: "amalfi.jpg",
      byteSizeLabel: "242 KB",
      inLibrary: true,
    });
    // Without an upload's original filename, the Library's own name.
    expect(surfaceById.png).toMatchObject({
      filename: "harbour",
      byteSizeLabel: "900 B",
    });
    // A sequence has no one file name, so it keeps its count.
    expect(surfaceById.pages).not.toHaveProperty("filename");
    // A file the Library does not hold keeps the feed's port name.
    expect(surfaceById.follow).toMatchObject({ filename: "result" });
    expect(build("ws").surfaceById.jpeg).not.toHaveProperty("filename");
  });

  it("lists every item of a sequence for its spread", () => {
    const library = new Map<string, PlacedLibraryItem>([
      [
        "s2",
        {
          artifact: {
            artifact_id: "s2",
            artifact_type: "file.png",
            schema_version: 1,
            sha256: "hash-s2",
            content_url: "/v1/artifacts/s2/content",
            content_type: "image/png",
            byte_size: 10,
            download_formats: [],
            metadata: {},
          },
          name: "page-2",
          provenance: {
            source: "upload",
            call_path: [],
            saved_at: "2026-11-20T12:00:00Z",
            original_filename: "page-2.png",
          },
          folder_id: null,
        },
      ],
    ]);
    expect(build("ws", library).surfaceById.pages).toMatchObject({
      workspaceId: "ws",
      stackItems: [
        {
          artifactId: "s1",
          artifact: {
            artifact_id: "s1",
            artifact_type: "file.png",
            schema_version: 1,
          },
          imageUrl: url("s1"),
          label: "#1",
        },
        {
          artifactId: "s2",
          artifact: {
            artifact_id: "s2",
            artifact_type: "file.png",
            schema_version: 1,
          },
          imageUrl: url("s2"),
          label: "page-2.png",
          byteSizeLabel: "10 B",
        },
        {
          artifactId: "s3",
          artifact: {
            artifact_id: "s3",
            artifact_type: "file.png",
            schema_version: 1,
          },
          imageUrl: url("s3"),
          label: "#3",
        },
        {
          artifactId: "s4",
          artifact: {
            artifact_id: "s4",
            artifact_type: "file.png",
            schema_version: 1,
          },
          imageUrl: url("s4"),
          label: "#4",
        },
      ],
    });
    // Without a workspace the tiles keep their names and drop the pictures.
    expect(build(null).surfaceById.pages).toMatchObject({
      stackItems: [
        { artifactId: "s1", imageUrl: null, label: "#1" },
        { artifactId: "s2", imageUrl: null, label: "#2" },
        { artifactId: "s3", imageUrl: null, label: "#3" },
        { artifactId: "s4", imageUrl: null, label: "#4" },
      ],
    });
    // A single card has no spread.
    expect(build("ws").surfaceById.png).not.toHaveProperty("stackItems");
  });

  it("paints nothing without a workspace to ask", () => {
    const { surfaceById } = build(null);
    expect(surfaceById.png).not.toHaveProperty("imageUrl");
    expect(surfaceById.follow).not.toHaveProperty("imageUrl");
  });
});

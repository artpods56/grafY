// @vitest-environment jsdom

import { changeOriginCardReferences } from "../artifacts/origin-card-commands";
import { act } from "react";
import * as React from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

import { reduceWorkbenchAuthoringState } from "./graph-document-adapter";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_NODE_TYPE,
  presentationFromArtifactViewers,
  type ArtifactViewerCanvasState,
  type ArtifactViewerEdge,
  type ArtifactViewerNode,
} from "../artifacts/artifact-viewer";
import {
  authoredGraphDocument,
  createSavedGraphRequest,
  type AuthoredGraphDocument,
  type GraphCommand,
} from "./graph-document";
import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import {
  useWorkbenchAuthoringCommands,
  type WorkbenchRoomCommandSync,
} from "./workbench-authoring-commands";

const savedNode = (id: string) => ({
  id,
  kind: "builtin" as const,
  operator_id: `test.${id}`,
  operator_version: 1,
  config: {},
  input_plugs: [],
  artifact_type_bindings: [],
  position: { x: 0, y: 0 },
  layout: null,
});

function card(id: string): ArtifactViewerNode {
  return {
    id,
    type: ARTIFACT_VIEWER_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: { layout: null, mode: "table" },
  };
}

function cardLink(
  id: string,
  sourceNodeId: string,
  targetViewerId: string,
): ArtifactViewerEdge {
  return {
    id,
    type: ARTIFACT_VIEWER_EDGE_TYPE,
    source: sourceNodeId,
    target: targetViewerId,
    targetHandle: "artifact-viewer-input",
    data: { sourcePortName: "result" },
  };
}

function initialViewers(): ArtifactViewerCanvasState {
  return {
    nodes: [card("artifact-viewer-1"), card("artifact-viewer-2")],
    edges: [
      cardLink("artifact-viewer-edge-1", "card-source", "artifact-viewer-1"),
      cardLink("artifact-viewer-edge-2", "other", "artifact-viewer-2"),
    ],
    bindings: [],
    annotations: [],
  };
}

function initialDocument(): AuthoredGraphDocument {
  return authoredGraphDocument(
    createSavedGraphRequest({
      name: "Cards and producers",
      nodes: [savedNode("card-source"), savedNode("other")],
      edges: [],
      origins: [],
      agents: [],
    }),
  );
}

/** A port that says what it carries, which a collection mode is decided from. */
function portSpec(
  direction: "input" | "output",
  name: string,
  artifactId: string,
  shape: "one" | "many" = "one",
): Port {
  return {
    accepted_shapes: [shape],
    artifact_type: { id: artifactId, schema_version: 1 },
    direction,
    instance_plugs: false,
    kind: "artifact",
    name,
    required: true,
    shape,
    variadic: false,
  };
}

function stepSpec(
  operatorId: string,
  inputs: readonly Port[],
  outputs: readonly Port[],
): NodeSpec {
  return {
    pack_slugs: [],
    role: "operator",
    operator_id: operatorId,
    operator_version: 1,
    plugin_slug: "test",
    origin: "builtin",
    title: operatorId,
    description: operatorId,
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: [...inputs],
    outputs: [...outputs],
  };
}

/** Pages, the OCR step that reads them, and the step that paints boxes on them. */
function mappedStepRegistry(): NodeRegistry {
  return {
    packs: [],
    plugins: [],
    artifact_types: [],
    artifact_conversions: [],
    nodes: [
      stepSpec("test.pages", [], [portSpec("output", "items", "page", "many")]),
      stepSpec(
        "test.ocr",
        [portSpec("input", "document", "page")],
        [
          portSpec("output", "markdown", "markdown"),
          portSpec("output", "regions", "boxes"),
        ],
      ),
      stepSpec(
        "test.boxes",
        [
          portSpec("input", "image", "page"),
          portSpec("input", "regions", "boxes"),
        ],
        [portSpec("output", "image", "page")],
      ),
    ],
  };
}

function savedConnection(
  id: string,
  fromNode: string,
  fromPort: string,
  toNode: string,
  toPort: string,
): AuthoredGraphDocument["edges"][number] {
  return {
    id,
    enabled: true,
    from_node: fromNode,
    from_port: fromPort,
    to_node: toNode,
    to_port: toPort,
    to_plug: null,
    collection_mode: "map",
    projection: null,
    route_offset: null,
    conversion_path: [],
  };
}

/** The graph as it stands while the OCR step runs once per page. */
function mappedStepDocument(): AuthoredGraphDocument {
  return authoredGraphDocument(
    createSavedGraphRequest({
      name: "Readings",
      nodes: [savedNode("pages"), savedNode("ocr"), savedNode("boxes")],
      edges: [
        savedConnection("feed", "pages", "items", "ocr", "document"),
        savedConnection("page", "pages", "items", "boxes", "image"),
        savedConnection("reading", "ocr", "regions", "boxes", "regions"),
      ],
      origins: [],
      agents: [],
    }),
  );
}

type Harness = {
  apply: (
    commands: readonly GraphCommand[],
    options?: { syncRoom?: boolean },
  ) => void;
  liveDocument: () => AuthoredGraphDocument;
  document: AuthoredGraphDocument;
  error: string | null;
  submitted: GraphCommand[][];
  viewers: ArtifactViewerCanvasState;
};

async function mount(
  options: {
    localAuthoringEnabled?: boolean;
    nodeRegistry?: NodeRegistry | null;
    document?: AuthoredGraphDocument;
  } = {},
) {
  const submitted: GraphCommand[][] = [];
  const refused: { message: string | null } = { message: null };
  let latest: Harness | null = null;

  function HarnessComponent() {
    const [authoring, dispatchAuthoringState] = React.useReducer(
      reduceWorkbenchAuthoringState,
      {
        document: options.document ?? initialDocument(),
        nodeOverlays: {},
        error: null,
      },
    );
    const authoredDocumentRef = React.useRef(authoring.document);
    React.useLayoutEffect(() => {
      authoredDocumentRef.current = authoring.document;
    }, [authoring.document]);
    const [viewers, setArtifactViewers] = React.useState(initialViewers);
    const [, setSelectedNodeIdSet] = React.useState<ReadonlySet<string>>(
      new Set(),
    );
    const [, setSelectedEdgeIdSet] = React.useState<ReadonlySet<string>>(
      new Set(),
    );
    const [, setPositionOverrides] = React.useState<
      Record<string, { x: number; y: number }>
    >({});
    const [, setRunErrorState] = React.useState<string | null>(null);
    const roomCommandSyncRef = React.useRef<WorkbenchRoomCommandSync>({
      submitLocal: (commands) => {
        submitted.push([...commands]);
      },
    });
    const localAuthoringEnabledRef = React.useRef(
      options.localAuthoringEnabled ?? true,
    );
    const localAuthoringBlockedMessageRef = React.useRef(
      "Wait for the running operation to finish.",
    );

    const { applyAuthoringCommands } = useWorkbenchAuthoringCommands({
      authoredDocument: authoring.document,
      authoredDocumentRef,
      dispatchAuthoringState,
      localAuthoringBlockedMessageRef,
      localAuthoringEnabledRef,
      nodeRegistry: options.nodeRegistry ?? null,
      roomCommandSyncRef,
      setArtifactViewers,
      setPendingConnectionRoute: () => undefined,
      setPositionOverrides,
      setRunError: (value) => {
        setRunErrorState(() => {
          refused.message =
            typeof value === "function" ? value(refused.message) : value;
          return refused.message;
        });
      },
      setSelectedEdgeIdSet,
      setSelectedNodeIdSet,
    });

    latest = {
      apply: applyAuthoringCommands,
      liveDocument: () => authoredDocumentRef.current,
      document: authoring.document,
      error: authoring.error ?? refused.message,
      submitted,
      viewers,
    };
    return null;
  }

  const root = createRoot(document.createElement("div"));
  await act(async () => {
    root.render(React.createElement(HarnessComponent));
  });

  return {
    read(): Harness {
      if (!latest) throw new Error("harness did not render");
      return latest;
    },
    run: (commands: readonly GraphCommand[], action?: { syncRoom?: boolean }) =>
      act(async () => {
        latest?.apply(commands, action);
      }),
    unmount: () => root.unmount(),
  };
}

/** The presentation the workbench would put on the wire after the given commands. */
function savedPresentation(harness: Harness) {
  return createSavedGraphRequest(
    harness.document,
    presentationFromArtifactViewers(harness.viewers),
  ).document.presentation;
}

describe("workbench authoring commands", () => {
  it("uses live ownership across node and edge removal callbacks before a render", async () => {
    const view = await mount();
    const ref = {
      artifact_id: "same",
      artifact_type: "file.png",
      schema_version: 1,
    };
    await view.run([
      {
        kind: "add_origin",
        origin: {
          id: "origin-copies",
          to_node: "other",
          to_port: "input",
          to_plug: null,
          value: {
            artifact_type: "file.png",
            schema_version: 1,
            item_refs: [ref, ref],
            sequence_id: "sequence",
            ordered: true,
            index_key: "order_index",
          },
          source_card_ids: ["A", "B"],
          collection_mode: "direct",
          conversion_path: [],
        },
      },
    ]);
    const beforeCount = view.read().submitted.length;
    await act(async () => {
      const harness = view.read();
      const removeCard = (id: string) => {
        harness.apply(
          harness
            .liveDocument()
            .origins.flatMap((origin) =>
              changeOriginCardReferences(origin, new Set([id])),
            ),
        );
      };
      removeCard("A"); // Node callback.
      removeCard("A"); // Incident-edge callback must do nothing.
      expect(harness.liveDocument().origins[0]?.source_card_ids).toEqual(["B"]);
      removeCard("B"); // A separately selected edge uses the updated origin.
    });
    expect(view.read().document.origins).toEqual([]);
    expect(view.read().submitted.length - beforeCount).toBe(2);
    view.unmount();
  });

  it("retires card links when a node removal deletes their source", async () => {
    const view = await mount();

    const commands = [
      { kind: "remove_nodes" as const, node_ids: ["card-source"] },
    ];
    expect(commands).toEqual([
      { kind: "remove_nodes", node_ids: ["card-source"] },
    ]);
    await view.run(commands);

    const harness = view.read();
    expect(harness.document.nodes.map((node) => node.id)).toEqual(["other"]);
    expect(harness.viewers.edges.map((edge) => edge.id)).toEqual([
      "artifact-viewer-edge-2",
    ]);
    expect(savedPresentation(harness)?.links.map((link) => link.id)).toEqual([
      "artifact-viewer-edge-2",
    ]);
  });

  it("retires card links for a remote removal without broadcasting it back", async () => {
    const view = await mount();

    await view.run(
      [{ kind: "remove_nodes", node_ids: ["card-source", "other"] }],
      {
        syncRoom: false,
      },
    );

    const harness = view.read();
    expect(harness.viewers.edges).toEqual([]);
    expect(savedPresentation(harness)?.links).toEqual([]);
    expect(harness.submitted).toEqual([]);
  });

  it("keeps card links when the command removes nothing", async () => {
    const view = await mount();

    await view.run([
      { kind: "move_nodes", positions: [{ node_id: "other", x: 12, y: 20 }] },
    ]);

    const harness = view.read();
    expect(harness.viewers.edges.map((edge) => edge.id)).toEqual([
      "artifact-viewer-edge-1",
      "artifact-viewer-edge-2",
    ]);
    expect(harness.submitted).toEqual([
      [{ kind: "move_nodes", positions: [{ node_id: "other", x: 12, y: 20 }] }],
    ]);
    expect(harness.error).toBeNull();
  });

  it("leaves the cards alone when it refuses the command", async () => {
    const view = await mount({ localAuthoringEnabled: false });

    await view.run([{ kind: "remove_nodes", node_ids: ["card-source"] }]);

    const harness = view.read();
    expect(harness.error).toBe("Wait for the running operation to finish.");
    expect(harness.document.nodes.map((node) => node.id)).toEqual([
      "card-source",
      "other",
    ]);
    expect(harness.viewers.edges.map((edge) => edge.id)).toEqual([
      "artifact-viewer-edge-1",
      "artifact-viewer-edge-2",
    ]);
    expect(harness.submitted).toEqual([]);
  });

  it("moves the collection modes a removal left behind into the same batch", async () => {
    const view = await mount({
      nodeRegistry: mappedStepRegistry(),
      document: mappedStepDocument(),
    });

    // Removing the sequence feed from the OCR step: it runs once now, so the
    // reading it offers is one value and cannot travel as a list.
    await view.run([{ kind: "remove_edges", edge_ids: ["feed"] }]);

    const harness = view.read();
    expect(harness.submitted.at(-1)).toEqual([
      { kind: "remove_edges", edge_ids: ["feed"] },
      {
        kind: "update_edge",
        edge_id: "reading",
        update: { collection_mode: "direct" },
      },
    ]);
    expect(
      harness.liveDocument().edges.find((edge) => edge.id === "reading")
        ?.collection_mode,
    ).toBe("direct");
    // The page still arrives one at a time, so that connection keeps its list.
    expect(
      harness.liveDocument().edges.find((edge) => edge.id === "page")
        ?.collection_mode,
    ).toBe("map");
  });

  it("moves no mode while the graph still runs its step per item", async () => {
    const view = await mount({
      nodeRegistry: mappedStepRegistry(),
      document: mappedStepDocument(),
    });

    await view.run([{ kind: "remove_edges", edge_ids: ["page"] }]);

    const harness = view.read();
    expect(harness.submitted.at(-1)).toEqual([
      { kind: "remove_edges", edge_ids: ["page"] },
    ]);
  });

  it("moves no mode until the node types are known", async () => {
    const view = await mount({ document: mappedStepDocument() });

    await view.run([{ kind: "remove_edges", edge_ids: ["feed"] }]);

    const harness = view.read();
    expect(harness.submitted.at(-1)).toEqual([
      { kind: "remove_edges", edge_ids: ["feed"] },
    ]);
  });
});

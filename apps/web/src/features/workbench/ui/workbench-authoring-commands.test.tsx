// @vitest-environment jsdom

import { act } from "react";
import * as React from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

import {
  graphCommandsFromNodeChanges,
  reduceWorkbenchAuthoringState,
} from "../canvas/graph-document-adapter";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_NODE_TYPE,
  presentationFromArtifactViewers,
  type ArtifactViewerCanvasState,
  type ArtifactViewerEdge,
  type ArtifactViewerNode,
} from "../canvas/artifact-viewer";
import {
  authoredGraphDocument,
  createSavedGraphRequest,
  type AuthoredGraphDocument,
  type GraphCommand,
} from "../model/graph-document";
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
  plugin_release_pin: null,
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
    graphId: "graph-1",
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
    }),
  );
}

type Harness = {
  apply: (
    commands: readonly GraphCommand[],
    options?: { syncRoom?: boolean },
  ) => void;
  document: AuthoredGraphDocument;
  error: string | null;
  submitted: GraphCommand[][];
  viewers: ArtifactViewerCanvasState;
};

async function mount(options: { localAuthoringEnabled?: boolean } = {}) {
  const submitted: GraphCommand[][] = [];
  const refused: { message: string | null } = { message: null };
  let latest: Harness | null = null;

  function HarnessComponent() {
    const [authoring, dispatchAuthoringState] = React.useReducer(
      reduceWorkbenchAuthoringState,
      { document: initialDocument(), nodeOverlays: {}, error: null },
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
  it("retires card links when a React Flow node removal deletes their source", async () => {
    const view = await mount();

    // The Delete key path: React Flow reports a node removal, the adapter turns it into
    // a `remove_nodes` command, and the workbench applies it.
    const commands = graphCommandsFromNodeChanges([
      { id: "card-source", type: "remove" },
    ]);
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
});

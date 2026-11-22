// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { describe, expect, it } from "vitest";

import type { NodeRegistry, NodeSpec, Port, SavedGraphAgent } from "@/lib/api";
import {
  runEffectReducer,
  runEffectSequence,
} from "@/lib/state/effect-reducer";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_NODE_TYPE,
  type ArtifactViewerCanvasState,
  type ArtifactViewerEdge,
  type ArtifactViewerNode,
} from "../artifacts/artifact-viewer";
import type { PendingConnectionRoute } from "./ConnectionRouteDialog";
import {
  authoredGraphDocument,
  createSavedGraphRequest,
  type AuthoredGraphDocument,
  type GraphCommand,
} from "./graph-document";
import type { NodeOverlays } from "./graph-document-adapter";
import { useWorkbenchAuthoringReducer } from "./useWorkbenchAuthoringReducer";
import {
  initialWorkbenchAuthoringUiState,
  workbenchAuthoringUiReducer,
  type PendingFolderDropState,
  type WorkbenchAuthoringUiAction,
  type WorkbenchAuthoringUiEffect,
  type WorkbenchAuthoringUiState,
} from "./workbench-authoring-reducer";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

type Discovery = { readonly id: string };
type Menu = { readonly kind: "node"; readonly nodeId: string };
type State = WorkbenchAuthoringUiState<Discovery, Menu>;
type Action = WorkbenchAuthoringUiAction<Discovery, Menu>;

const reducer = workbenchAuthoringUiReducer<Discovery, Menu>;
const BLOCKED = "Editing is paused.";
const externalCloses: WorkbenchAuthoringUiEffect[] = [
  { kind: "closeGraphBrowser" },
  { kind: "closeGridPanel" },
];

const idleOverlay: NodeOverlays[string] = {
  run: null,
  execution: { status: "idle" },
  progress: null,
};

function savedNode(id: string) {
  return {
    id,
    kind: "builtin" as const,
    operator_id: `test.${id}`,
    operator_version: 1,
    config: {},
    input_plugs: [],
    artifact_type_bindings: [],
    position: { x: 0, y: 0 },
    layout: null,
  };
}

function agent(id: string): SavedGraphAgent {
  return {
    id,
    name: id,
    instructions: "",
    context: [],
    tools: [],
    width: 360,
    height: 480,
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

function documentWith(
  input: Partial<AuthoredGraphDocument> & { name?: string } = {},
): AuthoredGraphDocument {
  return authoredGraphDocument(
    createSavedGraphRequest({
      name: input.name ?? "Workflow",
      nodes: input.nodes ?? [savedNode("alpha"), savedNode("beta")],
      edges: input.edges ?? [],
      origins: input.origins ?? [],
      agents: input.agents ?? [],
    }),
  );
}

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

function mappedStepRegistry(): NodeRegistry {
  return {
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

function mappedStepDocument(): AuthoredGraphDocument {
  return documentWith({
    name: "Readings",
    nodes: [savedNode("pages"), savedNode("ocr"), savedNode("boxes")],
    edges: [
      savedConnection("feed", "pages", "items", "ocr", "document"),
      savedConnection("page", "pages", "items", "boxes", "image"),
      savedConnection("reading", "ocr", "regions", "boxes", "regions"),
    ],
  });
}

function freshState(patch: Partial<State> = {}): State {
  return { ...initialWorkbenchAuthoringUiState<Discovery, Menu>(), ...patch };
}

function applyAction(
  commands: readonly GraphCommand[],
  extras: Partial<Extract<Action, { kind: "applyCommands" }>> = {},
): Action {
  return {
    kind: "applyCommands",
    commands,
    localAuthoringEnabled: true,
    blockedMessage: BLOCKED,
    nodeRegistry: null,
    ...extras,
  };
}

function transition(state: State, action: Action) {
  return runEffectReducer(reducer, state, action);
}

function routeFixture(): PendingConnectionRoute {
  return {
    connection: {
      source: "alpha",
      target: "beta",
      sourceHandle: "out",
      targetHandle: "in",
    },
    collectionMode: "direct",
    candidates: [],
    source: { nodeTitle: "Alpha", portName: "out", artifactType: "page" },
    target: { nodeTitle: "Beta", portName: "in", artifactType: "page" },
  };
}

function folderDrop(): PendingFolderDropState {
  return {
    drop: { folderName: "Photos", groups: [], canPlaceAll: true },
    destination: { kind: "canvas", point: { x: 12, y: 40 } },
  };
}

describe("workbenchAuthoringUiReducer", () => {
  it("starts from an empty untitled document", () => {
    const state = initialWorkbenchAuthoringUiState();
    expect(state.document).toBe(initialWorkbenchAuthoringUiState().document);
    expect(state.document).toMatchObject({
      name: "Untitled workflow",
      nodes: [],
      edges: [],
      origins: [],
      agents: [],
    });
    expect(state.popover).toEqual({ kind: "none" });
    expect(state.fitRevision).toBe(0);
    expect(state.error).toBeNull();
  });

  describe("applyCommands", () => {
    it("ignores an empty batch without reporting a block", () => {
      const state = freshState({ error: "kept" });
      const result = transition(
        state,
        applyAction([], { localAuthoringEnabled: false }),
      );
      expect(result.state).toBe(state);
      expect(result.effects).toEqual([]);
    });

    it("reports a blocked command and leaves the document", () => {
      const state = freshState({
        document: documentWith(),
        selectedNodeIds: new Set(["alpha"]),
      });
      const result = transition(
        state,
        applyAction([{ kind: "rename_graph", name: "Next" }], {
          localAuthoringEnabled: false,
        }),
      );
      expect(result.state).toBe(state);
      expect(result.effects).toEqual([
        { kind: "reportBlockedError", message: BLOCKED },
      ]);
    });

    it("applies a room replay while local authoring is paused", () => {
      const state = freshState({ document: documentWith({ name: "Before" }) });
      const result = transition(
        state,
        applyAction([{ kind: "rename_graph", name: "Remote" }], {
          localAuthoringEnabled: false,
          options: { syncRoom: false },
        }),
      );
      expect(result.state.document.name).toBe("Remote");
      expect(result.state.error).toBeNull();
      expect(result.effects).toEqual([{ kind: "clearRunError" }]);
    });

    it("syncs the batch against the document from before the command", () => {
      const before = documentWith({ name: "Before" });
      const state = freshState({
        document: before,
        error: "stale authoring error",
        positionOverrides: { alpha: { x: 9, y: 8 } },
        pendingConnectionRoute: routeFixture(),
        selectedNodeIds: new Set(["alpha", "gone"]),
        selectedEdgeIds: new Set(["missing-edge"]),
        selectedAgentIds: new Set(["missing-agent"]),
        canvasUpload: "Uploading 1 of 2…",
        collapsedAppendices: new Set(["alpha"]),
        fitRevision: 4,
      });
      const commands: GraphCommand[] = [
        { kind: "rename_graph", name: "After" },
      ];
      const result = transition(state, applyAction(commands));
      expect(result.state.document.name).toBe("After");
      expect(result.state.error).toBeNull();
      expect(result.state.positionOverrides).toEqual({});
      expect(result.state.pendingConnectionRoute).toBeNull();
      expect([...result.state.selectedNodeIds]).toEqual(["alpha"]);
      expect(result.state.selectedEdgeIds.size).toBe(0);
      expect(result.state.selectedAgentIds.size).toBe(0);
      expect(result.state.canvasUpload).toBe("Uploading 1 of 2…");
      expect([...result.state.collapsedAppendices]).toEqual(["alpha"]);
      expect(result.state.fitRevision).toBe(4);
      expect(result.effects).toEqual([
        { kind: "clearRunError" },
        { kind: "syncRoomCommands", commands: [...commands], before },
      ]);
    });

    it("keeps selection sets that still name surviving records", () => {
      const state = freshState({
        document: documentWith(),
        selectedNodeIds: new Set(["alpha", "beta"]),
      });
      const result = transition(
        state,
        applyAction([{ kind: "rename_graph", name: "Same nodes" }]),
      );
      expect(result.state.selectedNodeIds).toBe(state.selectedNodeIds);
    });

    it("keeps an authoring error and skips the room when a command fails", () => {
      const state = freshState({
        document: documentWith(),
        error: null,
        selectedNodeIds: new Set(["alpha"]),
      });
      const result = transition(
        state,
        applyAction([
          {
            kind: "update_node_configuration",
            node_id: "missing",
            field: "title",
            value: "nope",
          },
        ]),
      );
      expect(result.state.document).toBe(state.document);
      expect(result.state.selectedNodeIds).toBe(state.selectedNodeIds);
      expect(result.state.error).toBe(
        "Graph command targets missing node missing",
      );
      expect(result.effects).toEqual([]);
    });

    it("prunes selections and viewer links when nodes and edges leave", () => {
      const document = documentWith({
        nodes: [savedNode("alpha"), savedNode("beta"), savedNode("gamma")],
        edges: [savedConnection("link", "alpha", "out", "beta", "in")],
        agents: [agent("keeper"), agent("leaving")],
      });
      const state = freshState({
        document,
        nodeOverlays: { alpha: idleOverlay, beta: idleOverlay },
        selectedNodeIds: new Set(["alpha", "beta", "gamma"]),
        selectedEdgeIds: new Set(["link", "other"]),
        selectedAgentIds: new Set(["keeper", "leaving"]),
        popover: {
          kind: "inspectedPipe",
          graphId: "graph-1",
          pipeId: "link",
          anchor: { x: 1, y: 2 },
        },
      });
      const commands: GraphCommand[] = [
        { kind: "remove_nodes", node_ids: ["beta"] },
        { kind: "remove_edges", edge_ids: ["link"] },
        { kind: "remove_agent", agent_id: "leaving" },
      ];
      const result = transition(state, applyAction(commands));
      expect(result.state.document.nodes.map((node) => node.id)).toEqual([
        "alpha",
        "gamma",
      ]);
      expect(result.state.document.edges).toEqual([]);
      expect(result.state.document.agents.map((item) => item.id)).toEqual([
        "keeper",
      ]);
      expect([...result.state.selectedNodeIds]).toEqual(["alpha", "gamma"]);
      expect(result.state.selectedEdgeIds.size).toBe(0);
      expect([...result.state.selectedAgentIds]).toEqual(["keeper"]);
      expect(result.state.nodeOverlays).toEqual({ alpha: idleOverlay });
      expect(result.state.popover).toEqual(state.popover);
      expect(result.effects).toEqual([
        { kind: "pruneArtifactViewerEdges", nodeIds: ["beta"] },
        { kind: "clearRunError" },
        {
          kind: "syncRoomCommands",
          commands: [...commands],
          before: document,
        },
      ]);
    });

    it("joins every removed node id and can skip the room broadcast", () => {
      const state = freshState({ document: documentWith() });
      const result = transition(
        state,
        applyAction(
          [
            { kind: "remove_nodes", node_ids: ["alpha"] },
            { kind: "remove_nodes", node_ids: ["beta", "beta"] },
          ],
          { options: { syncRoom: false } },
        ),
      );
      expect(result.state.document.nodes).toEqual([]);
      expect(result.effects).toEqual([
        {
          kind: "pruneArtifactViewerEdges",
          nodeIds: ["alpha", "beta", "beta"],
        },
        { kind: "clearRunError" },
      ]);
    });

    it("folds collection-mode repairs into the same room batch", () => {
      const before = mappedStepDocument();
      const state = freshState({ document: before });
      const commands: GraphCommand[] = [
        { kind: "remove_edges", edge_ids: ["feed"] },
      ];
      const result = transition(
        state,
        applyAction(commands, { nodeRegistry: mappedStepRegistry() }),
      );
      const reading = result.state.document.edges.find(
        (edge) => edge.id === "reading",
      );
      const page = result.state.document.edges.find(
        (edge) => edge.id === "page",
      );
      expect(reading?.collection_mode).toBe("direct");
      expect(page?.collection_mode).toBe("map");
      expect(result.effects).toEqual([
        { kind: "clearRunError" },
        {
          kind: "syncRoomCommands",
          commands: [
            ...commands,
            {
              kind: "update_edge",
              edge_id: "reading",
              update: { collection_mode: "direct" },
            },
          ],
          before,
        },
      ]);
    });

    it("leaves modes alone until the node registry is known", () => {
      const state = freshState({ document: mappedStepDocument() });
      const commands: GraphCommand[] = [
        { kind: "remove_edges", edge_ids: ["feed"] },
      ];
      const result = transition(state, applyAction(commands));
      expect(
        result.state.document.edges.find((edge) => edge.id === "reading")
          ?.collection_mode,
      ).toBe("map");
      expect(result.effects[1]).toMatchObject({
        kind: "syncRoomCommands",
        commands: [...commands],
      });
    });

    it("threads each batch through the document the previous batch produced", () => {
      const result = runEffectSequence(reducer, freshState(), [
        applyAction([{ kind: "rename_graph", name: "First" }]),
        applyAction([{ kind: "rename_graph", name: "Second" }]),
      ]);
      expect(result.state.document.name).toBe("Second");
      expect(result.effects).toEqual([
        { kind: "clearRunError" },
        {
          kind: "syncRoomCommands",
          commands: [{ kind: "rename_graph", name: "First" }],
          before: initialWorkbenchAuthoringUiState().document,
        },
        { kind: "clearRunError" },
        {
          kind: "syncRoomCommands",
          commands: [{ kind: "rename_graph", name: "Second" }],
          before: expect.objectContaining({ name: "First" }),
        },
      ]);
    });
  });

  describe("document, overlays, and selection", () => {
    it("normalizes a replacement and keeps overlays for surviving nodes", () => {
      const state = freshState({
        document: documentWith(),
        nodeOverlays: { alpha: idleOverlay, beta: idleOverlay },
        error: "previous",
        selectedNodeIds: new Set(["alpha"]),
        selectedEdgeIds: new Set(["edge"]),
        selectedAgentIds: new Set(["agent"]),
        positionOverrides: { alpha: { x: 3, y: 4 } },
        popover: { kind: "library", insertAt: { x: 1, y: 1 } },
        pendingConnectionRoute: routeFixture(),
      });
      const result = transition(state, {
        kind: "replaceDocument",
        document: documentWith({
          name: "  Renamed  ",
          nodes: [savedNode("alpha")],
        }),
      });
      expect(result.state.document.name).toBe("Renamed");
      expect(result.state.document.nodes.map((node) => node.id)).toEqual([
        "alpha",
      ]);
      expect(result.state.nodeOverlays).toEqual({ alpha: idleOverlay });
      expect(result.state.error).toBeNull();
      expect(result.state.selectedNodeIds.size).toBe(0);
      expect(result.state.selectedEdgeIds.size).toBe(0);
      expect(result.state.selectedAgentIds.size).toBe(0);
      expect(result.state.positionOverrides).toEqual({});
      expect(result.state.popover).toEqual({
        kind: "library",
        insertAt: { x: 1, y: 1 },
      });
      expect(result.state.pendingConnectionRoute).toBe(
        state.pendingConnectionRoute,
      );
      expect(result.effects).toEqual([]);
    });

    it("uses caller overlays when a replacement supplies them", () => {
      const nodeOverlays: NodeOverlays = { beta: idleOverlay };
      const result = transition(
        freshState({ nodeOverlays: { alpha: idleOverlay } }),
        {
          kind: "replaceDocument",
          document: documentWith({ nodes: [savedNode("alpha")] }),
          nodeOverlays,
        },
      );
      expect(result.state.nodeOverlays).toBe(nodeOverlays);
    });

    it("replaces overlays and applies a node snapshot", () => {
      const update: NodeOverlays = { alpha: idleOverlay };
      const replaced = transition(freshState(), {
        kind: "updateOverlays",
        update,
      });
      expect(replaced.state.nodeOverlays).toBe(update);
      expect(replaced.effects).toEqual([]);

      const same = transition(replaced.state, {
        kind: "updateOverlays",
        update,
      });
      expect(same.state).toBe(replaced.state);

      const selectedNodeIds = new Set(["alpha"]);
      const positionOverrides = { alpha: { x: 5, y: 6 } };
      const snapshot = transition(replaced.state, {
        kind: "applyNodesSnapshot",
        selectedNodeIds,
        positionOverrides,
        nodeOverlays: update,
      });
      expect(snapshot.state.selectedNodeIds).toBe(selectedNodeIds);
      expect(snapshot.state.positionOverrides).toBe(positionOverrides);
      expect(snapshot.state.nodeOverlays).toBe(update);
      const repeat = transition(snapshot.state, {
        kind: "applyNodesSnapshot",
        selectedNodeIds,
        positionOverrides,
        nodeOverlays: update,
      });
      expect(repeat.state).toBe(snapshot.state);
    });

    it("sets selection and position overrides, including identical writes", () => {
      const nodes = new Set(["alpha"]);
      const edges = new Set(["link"]);
      const agents = new Set(["keeper"]);
      const overrides = { alpha: { x: 1, y: 2 } };
      const result = runEffectSequence(reducer, freshState(), [
        { kind: "setSelectedNodeIds", ids: nodes },
        { kind: "setSelectedEdgeIds", ids: edges },
        { kind: "setSelectedAgentIds", ids: agents },
        { kind: "setPositionOverrides", overrides },
        { kind: "setSelectedNodeIds", ids: nodes },
      ]);
      expect(result.state.selectedNodeIds).toBe(nodes);
      expect(result.state.selectedEdgeIds).toBe(edges);
      expect(result.state.selectedAgentIds).toBe(agents);
      expect(result.state.positionOverrides).toBe(overrides);
      expect(result.effects).toEqual([]);
    });

    it("opens and closes one card's config section without touching another's", () => {
      const opened = transition(freshState(), {
        kind: "setConfigSection",
        cardId: "card-1",
        sectionKey: "advanced",
        open: true,
      });
      expect(opened.state.configSections).toEqual({
        "card-1": { advanced: true },
      });
      const nested = transition(opened.state, {
        kind: "setConfigSection",
        cardId: "card-1",
        sectionKey: "object:style",
        open: true,
      });
      const closed = transition(nested.state, {
        kind: "setConfigSection",
        cardId: "card-1",
        sectionKey: "advanced",
        open: false,
      });
      expect(closed.state.configSections).toEqual({
        "card-1": { advanced: false, "object:style": true },
      });
      const same = transition(closed.state, {
        kind: "setConfigSection",
        cardId: "card-1",
        sectionKey: "advanced",
        open: false,
      });
      expect(same.state).toBe(closed.state);
      expect(same.effects).toEqual([]);
    });

    it("toggles appendix membership and bumps the fit revision", () => {
      const once = transition(freshState(), {
        kind: "toggleAppendix",
        cardId: "card-1",
      });
      expect([...once.state.collapsedAppendices]).toEqual(["card-1"]);
      const twice = transition(once.state, {
        kind: "toggleAppendix",
        cardId: "card-1",
      });
      expect(twice.state.collapsedAppendices.size).toBe(0);
      const other = transition(once.state, {
        kind: "toggleAppendix",
        cardId: "card-2",
      });
      expect([...other.state.collapsedAppendices].sort()).toEqual([
        "card-1",
        "card-2",
      ]);
      const fitted = runEffectSequence(
        reducer,
        freshState({ fitRevision: 3 }),
        [{ kind: "requestCanvasRefit" }, { kind: "requestCanvasRefit" }],
      );
      expect(fitted.state.fitRevision).toBe(5);
    });
  });

  describe("popovers", () => {
    const anchor = { x: 8, y: 9 };
    const session: Discovery = { id: "discovery" };
    const request: Menu = { kind: "node", nodeId: "alpha" };

    it("opens the library and the shapes menu exclusively", () => {
      const opened = transition(freshState(), {
        kind: "toggleLibrary",
        insertAt: anchor,
      });
      expect(opened.state.popover).toEqual({
        kind: "library",
        insertAt: anchor,
      });
      expect(opened.effects).toEqual(externalCloses);

      const shapes = transition(opened.state, { kind: "toggleShapesMenu" });
      expect(shapes.state.popover).toEqual({ kind: "shapesMenu" });
      expect(shapes.effects).toEqual(externalCloses);

      const closed = transition(shapes.state, { kind: "toggleShapesMenu" });
      expect(closed.state.popover).toEqual({ kind: "none" });
      expect(closed.effects).toEqual([]);

      const reopened = transition(closed.state, {
        kind: "setShapesMenuOpen",
        open: true,
      });
      expect(reopened.state.popover).toEqual({ kind: "shapesMenu" });
      expect(reopened.effects).toEqual(externalCloses);
      const again = transition(reopened.state, {
        kind: "setShapesMenuOpen",
        open: true,
      });
      expect(again.state).toBe(reopened.state);
      expect(again.effects).toEqual(externalCloses);
    });

    it("closes a popover only when that popover is the one open", () => {
      const library = transition(freshState(), {
        kind: "setLibraryOpen",
        open: true,
        insertAt: anchor,
      });
      const falseShapes = transition(library.state, {
        kind: "setShapesMenuOpen",
        open: false,
      });
      expect(falseShapes.state).toBe(library.state);
      expect(falseShapes.effects).toEqual([]);

      const samePoint = transition(library.state, {
        kind: "setLibraryOpen",
        open: true,
        insertAt: { x: anchor.x, y: anchor.y },
      });
      expect(samePoint.state).toBe(library.state);
      expect(samePoint.effects).toEqual(externalCloses);

      const moved = transition(library.state, {
        kind: "setLibraryOpen",
        open: true,
        insertAt: { x: 0, y: 1 },
      });
      expect(moved.state.popover).toEqual({
        kind: "library",
        insertAt: { x: 0, y: 1 },
      });

      const shut = transition(moved.state, {
        kind: "setLibraryOpen",
        open: false,
      });
      expect(shut.state.popover).toEqual({ kind: "none" });
      expect(shut.effects).toEqual([]);

      const fromShapes = transition(shut.state, { kind: "toggleLibrary" });
      expect(fromShapes.state.popover).toEqual({
        kind: "library",
        insertAt: null,
      });
      const toggledShut = transition(fromShapes.state, {
        kind: "toggleLibrary",
        insertAt: anchor,
      });
      expect(toggledShut.state.popover).toEqual({ kind: "none" });
      expect(toggledShut.effects).toEqual([]);
    });

    it("walks discovery, pipe inspection, and the context menu", () => {
      const result = runEffectSequence(reducer, freshState(), [
        { kind: "openContextualDiscovery", session },
        { kind: "openContextualDiscovery", session },
        {
          kind: "toggleInspectedPipe",
          graphId: "graph-1",
          pipeId: "pipe-1",
          anchor,
        },
        { kind: "closeContextualDiscovery" },
        { kind: "pruneInspectedPipes", pipeIds: ["pipe-2"] },
        {
          kind: "toggleInspectedPipe",
          graphId: null,
          pipeId: "pipe-2",
          anchor,
        },
        { kind: "pruneInspectedPipes", pipeIds: ["pipe-2"] },
        { kind: "openContextMenu", request },
        { kind: "closeInspectedPipe" },
        { kind: "closeContextMenu" },
        { kind: "closeContextMenu" },
      ]);
      expect(result.state.popover).toEqual({ kind: "none" });
      expect(result.effects).toEqual(externalCloses);
    });

    it("toggles the same inspected pipe shut and ignores a foreign close", () => {
      const opened = transition(freshState(), {
        kind: "toggleInspectedPipe",
        graphId: "graph-1",
        pipeId: "pipe-1",
        anchor,
      });
      expect(opened.effects).toEqual([]);
      expect(opened.state.popover).toEqual({
        kind: "inspectedPipe",
        graphId: "graph-1",
        pipeId: "pipe-1",
        anchor,
      });
      const shut = transition(opened.state, {
        kind: "toggleInspectedPipe",
        graphId: "graph-1",
        pipeId: "pipe-1",
        anchor: { x: 0, y: 0 },
      });
      expect(shut.state.popover).toEqual({ kind: "none" });
      const menu = transition(freshState(), {
        kind: "openContextMenu",
        request,
      });
      const ignored = transition(menu.state, { kind: "closeInspectedPipe" });
      expect(ignored.state).toBe(menu.state);
      const closed = transition(menu.state, { kind: "closeContextMenu" });
      expect(closed.state.popover).toEqual({ kind: "none" });
    });

    it("closes every popover and, unless asked not to, the external panels", () => {
      const menu = transition(freshState(), {
        kind: "openContextMenu",
        request,
      });
      const kept = transition(menu.state, {
        kind: "closeAllPopovers",
        closeExternal: false,
      });
      expect(kept.state.popover).toEqual({ kind: "none" });
      expect(kept.effects).toEqual([]);
      const none = transition(kept.state, { kind: "closeAllPopovers" });
      expect(none.state).toBe(kept.state);
      expect(none.effects).toEqual(externalCloses);
      const discovery = transition(freshState(), {
        kind: "openContextualDiscovery",
        session,
      });
      const all = transition(discovery.state, { kind: "closeAllPopovers" });
      expect(all.state.popover).toEqual({ kind: "none" });
      expect(all.effects).toEqual(externalCloses);
    });
  });

  describe("dialogs, upload, and errors", () => {
    it("stores and clears the connection and folder dialogs", () => {
      const route = routeFixture();
      const drop = folderDrop();
      const inputDrop: PendingFolderDropState = {
        drop: drop.drop,
        destination: {
          kind: "input",
          target: { nodeId: "alpha", portName: "in", plugId: null },
        },
      };
      const result = runEffectSequence(reducer, freshState(), [
        { kind: "setPendingConnectionRoute", route },
        { kind: "setPendingConnectionRoute", route },
        { kind: "setPendingFolderDrop", drop },
        { kind: "setPendingFolderDrop", drop: inputDrop },
        { kind: "setCanvasUpload", status: "Uploading 1 of 1…" },
        { kind: "setCanvasUpload", status: "Uploading 1 of 1…" },
        { kind: "setCanvasUpload", status: null },
        { kind: "setPendingConnectionRoute", route: null },
        { kind: "setPendingFolderDrop", drop: null },
      ]);
      expect(result.state.pendingConnectionRoute).toBeNull();
      expect(result.state.pendingFolderDrop).toBeNull();
      expect(result.state.canvasUpload).toBeNull();
      expect(result.effects).toEqual([]);
    });

    it("clears an authoring error only when the dismissal names it", () => {
      const failed = transition(freshState({ document: documentWith() }), {
        kind: "applyCommands",
        commands: [
          {
            kind: "update_node_configuration",
            node_id: "missing",
            field: "title",
            value: "nope",
          },
        ],
        localAuthoringEnabled: true,
        blockedMessage: BLOCKED,
        nodeRegistry: null,
      });
      const message = failed.state.error;
      expect(message).toBe("Graph command targets missing node missing");
      const ignored = transition(failed.state, {
        kind: "dismissError",
        message: "something else",
      });
      expect(ignored.state).toBe(failed.state);
      const dismissed = transition(failed.state, {
        kind: "dismissError",
        message: message ?? "",
      });
      expect(dismissed.state.error).toBeNull();
      const already = transition(dismissed.state, { kind: "clearError" });
      expect(already.state).toBe(dismissed.state);
      const again = transition(failed.state, { kind: "clearError" });
      expect(again.state.error).toBeNull();
    });
  });
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

describe("useWorkbenchAuthoringReducer", () => {
  const roots: Array<{ root: Root; container: HTMLElement }> = [];

  function mount() {
    const submitted: Array<{
      commands: readonly GraphCommand[];
      beforeName: string;
    }> = [];
    const closes = { graph: 0, grid: 0, cleared: 0 };
    const enabledRef: { current: boolean } = { current: true };
    const blockedRef: { current: string } = { current: BLOCKED };
    const registryRef: { current: NodeRegistry | null } = { current: null };
    let latest: ReturnType<typeof useWorkbenchAuthoringReducer> | null = null;
    let viewers: ArtifactViewerCanvasState = {
      nodes: [card("viewer-1"), card("viewer-2")],
      edges: [
        cardLink("viewer-edge-1", "alpha", "viewer-1"),
        cardLink("viewer-edge-2", "beta", "viewer-2"),
      ],
      bindings: [],
      annotations: [],
    };
    let runError: string | null = "transient";

    function Harness() {
      const api = useWorkbenchAuthoringReducer({
        localAuthoringEnabledRef: enabledRef,
        localAuthoringBlockedMessageRef: blockedRef,
        nodeRegistryRef: registryRef,
        roomCommandSyncRef: {
          current: {
            submitLocal: (commands, before) => {
              submitted.push({
                commands: [...commands],
                beforeName: before.name,
              });
            },
          },
        },
        setArtifactViewers: (update) => {
          viewers = typeof update === "function" ? update(viewers) : update;
        },
        setRunError: (update) => {
          runError = typeof update === "function" ? update(runError) : update;
        },
        onClearRunError: () => {
          closes.cleared += 1;
        },
        onCloseGraphBrowser: () => {
          closes.graph += 1;
        },
        onCloseGridPanel: () => {
          closes.grid += 1;
        },
      });
      latest = api;
      return null;
    }

    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push({ root, container });
    act(() => {
      root.render(React.createElement(Harness));
    });

    return {
      enabledRef,
      blockedRef,
      registryRef,
      api: () => {
        if (!latest) throw new Error("harness did not render");
        return latest;
      },
      submitted: () => submitted,
      closes: () => closes,
      viewers: () => viewers,
      runError: () => runError,
      rerender: () => {
        act(() => {
          root.render(React.createElement(Harness));
        });
      },
    };
  }

  it("applies sequential commands against the live document ref", () => {
    const view = mount();
    const api = view.api();
    act(() => {
      api.applyAuthoringCommands([{ kind: "rename_graph", name: "First" }]);
      expect(api.authoredDocumentRef.current.name).toBe("First");
      api.applyAuthoringCommands([{ kind: "rename_graph", name: "Second" }]);
      expect(api.authoredDocumentRef.current.name).toBe("Second");
      expect(api.nodeOverlaysRef.current).toEqual({});
    });
    expect(view.api().authoredDocument.name).toBe("Second");
    expect(view.submitted().map((batch) => batch.beforeName)).toEqual([
      "Untitled workflow",
      "First",
    ]);
    expect(view.runError()).toBeNull();
    expect(view.closes().cleared).toBe(2);
  });

  it("reads the registry and the block message at call time", () => {
    const view = mount();
    const api = view.api();
    act(() => {
      api.replaceDocument(mappedStepDocument());
      expect(api.authoredDocumentRef.current.name).toBe("Readings");
    });
    view.registryRef.current = mappedStepRegistry();
    act(() => {
      api.applyAuthoringCommands([
        { kind: "remove_edges", edge_ids: ["feed"] },
      ]);
    });
    expect(view.submitted().at(-1)?.commands).toEqual([
      { kind: "remove_edges", edge_ids: ["feed"] },
      {
        kind: "update_edge",
        edge_id: "reading",
        update: { collection_mode: "direct" },
      },
    ]);

    view.enabledRef.current = false;
    view.blockedRef.current = "Wait for the run.";
    act(() => {
      api.applyAuthoringCommands([{ kind: "rename_graph", name: "Nope" }]);
    });
    expect(view.api().authoredDocument.name).toBe("Readings");
    expect(view.runError()).toBe("Wait for the run.");
  });

  it("updates selection like a state setter and prunes viewer links", () => {
    const view = mount();
    const api = view.api();
    act(() => {
      api.replaceDocument(
        documentWith({
          nodes: [savedNode("alpha"), savedNode("beta")],
          edges: [savedConnection("kept", "beta", "out", "beta", "in")],
          agents: [agent("keeper"), agent("leaving")],
        }),
        { alpha: idleOverlay },
      );
      expect(api.nodeOverlaysRef.current).toEqual({ alpha: idleOverlay });
      api.setSelectedNodeIdSet(new Set(["beta"]));
      api.setSelectedNodeIdSet((current) => new Set([...current, "alpha"]));
      api.setSelectedEdgeIdSet(new Set(["kept"]));
      api.setSelectedEdgeIdSet((current) => new Set([...current, "gone"]));
      api.setSelectedAgentIds(new Set(["keeper"]));
      api.setSelectedAgentIds((current) => new Set([...current, "leaving"]));
      api.setPositionOverrides({ alpha: { x: 1, y: 2 } });
      api.setPositionOverrides((current) => ({
        ...current,
        beta: { x: 3, y: 4 },
      }));
    });
    expect([...view.api().selectedNodeIdSet].sort()).toEqual(["alpha", "beta"]);
    expect([...view.api().selectedEdgeIdSet].sort()).toEqual(["gone", "kept"]);
    expect([...view.api().selectedAgentIds].sort()).toEqual([
      "keeper",
      "leaving",
    ]);
    expect(view.api().positionOverrides).toEqual({
      alpha: { x: 1, y: 2 },
      beta: { x: 3, y: 4 },
    });
    act(() => {
      view.api().applyAuthoringCommands([
        { kind: "remove_nodes", node_ids: ["alpha"] },
        { kind: "remove_agent", agent_id: "leaving" },
      ]);
    });
    expect([...view.api().selectedNodeIdSet]).toEqual(["beta"]);
    expect([...view.api().selectedEdgeIdSet]).toEqual(["kept"]);
    expect([...view.api().selectedAgentIds]).toEqual(["keeper"]);
    expect(view.api().positionOverrides).toEqual({});
    expect(view.viewers().edges.map((edge) => edge.id)).toEqual([
      "viewer-edge-2",
    ]);
    expect(view.api().authoringError).toBeNull();
  });

  it("drives the popover, dialog, and error surface", () => {
    const view = mount();
    const api = view.api();
    const session = { id: "discovery" };
    const request = { kind: "node" as const, nodeId: "alpha" };
    act(() => {
      api.toggleLibrary({ x: 2, y: 3 });
      api.toggleShapesMenu();
      api.openContextualDiscovery(session);
      api.toggleInspectedPipe("graph-1", "pipe-1", { x: 1, y: 1 });
      api.pruneInspectedPipes(["pipe-9"]);
      api.pruneInspectedPipes(["pipe-1"]);
      api.openContextMenu(request);
      api.setLibraryOpen(false);
      api.closeContextMenu();
      api.setShapesMenuOpen(true);
      api.closeCanvasPopovers(false);
      api.setCanvasUpload("Uploading…");
      api.setPendingConnectionRoute(routeFixture());
      api.setPendingFolderDrop(folderDrop());
      api.toggleAppendix("card-1");
      api.requestCanvasRefit();
      api.applyAuthoringCommands([
        {
          kind: "update_node_configuration",
          node_id: "missing",
          field: "title",
          value: "nope",
        },
      ]);
    });
    const shown = view.api();
    expect(shown.libraryOpen).toBe(false);
    expect(shown.shapesMenuOpen).toBe(false);
    expect(shown.contextualDiscovery).toBeNull();
    expect(shown.inspectedPipe).toBeNull();
    expect(shown.canvasMenu).toBeNull();
    expect(shown.canvasUpload).toBe("Uploading…");
    expect(shown.pendingConnectionRoute?.connection.source).toBe("alpha");
    expect(shown.pendingFolderDrop?.drop.folderName).toBe("Photos");
    expect([...shown.collapsedAppendices]).toEqual(["card-1"]);
    expect(shown.fitRevision).toBe(1);
    expect(shown.authoringError).toBe(
      "Graph command targets missing node missing",
    );
    expect(view.closes()).toMatchObject({ graph: 4, grid: 4 });
    act(() => {
      shown.dismissAuthoringError("transient");
    });
    expect(view.api().authoringError).toBe(
      "Graph command targets missing node missing",
    );
    expect(view.runError()).toBeNull();
    act(() => {
      view
        .api()
        .dismissAuthoringError("Graph command targets missing node missing");
    });
    expect(view.api().authoringError).toBeNull();
    act(() => {
      view.api().setCanvasUpload("busy");
      view.api().clearAuthoringError();
      view.api().closeCanvasPopovers();
    });
    expect(view.api().canvasUpload).toBe("busy");
    expect(view.closes().graph).toBe(5);
  });
});

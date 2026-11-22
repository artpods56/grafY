// @vitest-environment jsdom

import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CollaborativeHead,
  NodeRegistry,
  NodeSpec,
  SavedGraph,
  SavedGraphDocument,
  SavedGraphSummary,
} from "@/lib/api";
import { artifactPortFixture, nodeSpecFixture } from "../test-fixtures";
import { deferred } from "../test/deferred";
import { renderHook } from "../test/renderHook";
import { useGraphAutosave } from "./useGraphAutosave";
import { useSavedGraphLifecycle } from "./useSavedGraphLifecycle";

const router = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
}));

const savedGraphQuery = vi.hoisted(() => ({
  mutate: vi.fn(),
}));

const graphSummaryRefresh = vi.hoisted(() => vi.fn());

/**
 * The Project endpoints the lifecycle touches. A canvas is one Graph inside one
 * Project, so opening reads the Project head, saving writes the document as a
 * Project command, and deleting retires the whole Project.
 * `graphFromProjectHead` stays the real projection: a mock that reimplemented it
 * could pass while the client projected a different Graph than the canvas shows.
 */
const api = vi.hoisted(() => ({
  createProject: vi.fn(),
  deleteProject: vi.fn(),
  getCollaborativeHead: vi.fn(),
  submitProjectCommand: vi.fn(),
  checkpointProject: vi.fn(),
  listGraphInstances: vi.fn(),
  getInstanceResult: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
}));

vi.mock("@/hooks/use-api", () => ({
  useWorkspaceProjects: () => ({
    data: { projects: [] },
    error: undefined,
    isLoading: false,
    isValidating: false,
    mutate: savedGraphQuery.mutate,
  }),
  useProjectSummaryRefresh: () => graphSummaryRefresh,
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

// The route, the room, and the head are all addressed by Project, so these are
// Project ids; each Project holds the one Graph the canvas shows.
const GRAPH_A_ID = "00000000-0000-4000-8000-00000000000a";
const GRAPH_B_ID = "00000000-0000-4000-8000-00000000000b";
const PROJECT_ID = GRAPH_A_ID;

const registry: NodeRegistry = {
  plugins: [],
  artifact_types: [],
  artifact_conversions: [],
  nodes: [],
};

function savedGraph(id: string, name: string, revision = 1): SavedGraph {
  return {
    id,
    revision,
    name,
    created_at: "2026-07-17T12:00:00Z",
    updated_at: "2026-07-17T12:00:00Z",
    document: {
      schema_version: 7,
      nodes: [],
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
  };
}

const ROOM_EPOCH = "00000000-0000-4000-8000-0000000000ee";

function savedGraphSummary(graph: SavedGraph): SavedGraphSummary {
  return {
    id: graph.id,
    revision: graph.revision,
    name: graph.name,
    // The list counts a Project's Graphs, which is what the browser shows for
    // it; a canvas is one of them.
    graph_count: 1,
    node_count: graph.document.nodes.length,
    edge_count: graph.document.edges.length,
    updated_at: graph.updated_at,
    draft_pending: false,
  };
}

/**
 * A Project head holding one Graph. The route names the Project and the canvas
 * shows its Graph, so the fixture keeps them on the same id: a test that cares
 * about which Graph a canvas is showing says so with `graphId`.
 */
function projectHead(
  graph: SavedGraph,
  overrides: {
    collaborationSequence?: number;
    checkpointSequence?: number;
    graphName?: string;
    name?: string;
    updatedAt?: string;
    roomEpoch?: string;
  } = {},
): CollaborativeHead {
  const collaborationSequence =
    overrides.collaborationSequence ?? graph.revision;
  const checkpointSequence = overrides.checkpointSequence ?? graph.revision;
  return {
    project_id: graph.id,
    name: overrides.name ?? graph.name,
    room_epoch: overrides.roomEpoch ?? ROOM_EPOCH,
    collaboration_sequence: collaborationSequence,
    checkpoint_sequence: checkpointSequence,
    checkpoint_revision: checkpointSequence,
    updated_at: overrides.updatedAt ?? graph.updated_at,
    // A Project document is a list of Graphs; the route names the Project and
    // this fixture keeps its one Graph on the same id.
    document: {
      graphs: [
        {
          id: graph.id,
          name: overrides.graphName ?? graph.name,
          document: graph.document,
        },
      ],
    },
  };
}

/** The open path: a Project whose head holds this Graph. */
function stubOpen(graph: SavedGraph): void {
  api.getCollaborativeHead.mockImplementation((_workspaceId, projectId) =>
    Promise.resolve(
      projectHead(
        projectId === graph.id
          ? graph
          : savedGraph(projectId, `Project ${projectId}`),
      ),
    ),
  );
}

/** A first save copies the authored draft into a newly created Project. */
function stubCreate(projectId: string, graph: SavedGraph) {
  api.createProject.mockResolvedValue({
    id: projectId,
    name: graph.name,
    created_at: graph.created_at,
    updated_at: graph.updated_at,
  });
  const previousHeadRead = api.getCollaborativeHead.getMockImplementation();
  api.getCollaborativeHead.mockImplementation(
    (workspaceId: string, requestedProjectId: string) =>
      requestedProjectId === projectId || !previousHeadRead
        ? Promise.resolve(projectHead(graph))
        : previousHeadRead(workspaceId, requestedProjectId),
  );
}

function submittedDocuments(): SavedGraphDocument[] {
  return api.createProject.mock.calls.map((call) => call[1].graph_document);
}

type LifecycleOptions = Parameters<typeof useSavedGraphLifecycle>[0];

interface LifecycleCallbacks {
  replaceDocument: ReturnType<typeof vi.fn>;
  replacePresentation: ReturnType<typeof vi.fn>;
  refreshNodeSecretStatuses: LifecycleOptions["refreshNodeSecretStatuses"];
  clearGraphSecretStatuses: ReturnType<typeof vi.fn>;
  clearPendingConnectionRoute: ReturnType<typeof vi.fn>;
  clearRunError: ReturnType<typeof vi.fn>;
  closeNodeLibrary: ReturnType<typeof vi.fn>;
  requestCanvasRefit: ReturnType<typeof vi.fn>;
  refreshNodeRegistry: ReturnType<typeof vi.fn>;
}

function lifecycleOptions(
  initialGraphId: string | null,
  refreshNodeSecretStatuses: LifecycleOptions["refreshNodeSecretStatuses"] = vi
    .fn()
    .mockResolvedValue(true),
  initialDocument: LifecycleOptions["document"] = {
    name: "Untitled workflow",
    nodes: [],
    edges: [],
    origins: [],
    agents: [],
  },
): { options: LifecycleOptions; callbacks: LifecycleCallbacks } {
  const document = {
    name: initialDocument.name,
    nodes: initialDocument.nodes,
    edges: initialDocument.edges,
    origins: initialDocument.origins,
    agents: initialDocument.agents,
  };
  const callbacks = {
    replaceDocument: vi.fn((nextDocument: LifecycleOptions["document"]) => {
      document.name = nextDocument.name;
      document.nodes = nextDocument.nodes;
      document.edges = nextDocument.edges;
      document.origins = nextDocument.origins;
      document.agents = nextDocument.agents;
    }),
    replacePresentation: vi.fn(),
    refreshNodeSecretStatuses,
    clearGraphSecretStatuses: vi.fn(),
    clearPendingConnectionRoute: vi.fn(),
    clearRunError: vi.fn(),
    closeNodeLibrary: vi.fn(),
    requestCanvasRefit: vi.fn(),
    refreshNodeRegistry: vi.fn(),
  };
  const updateDocumentName = vi.fn((name: string) => {
    document.name = name;
  });
  return {
    options: {
      workspaceId: "workspace-1",
      workspaceSlug: "team",
      initialGraphId,
      registry,
      document,
      isExecutionRunning: () => false,
      replaceDocument: callbacks.replaceDocument,
      replacePresentation: callbacks.replacePresentation,
      updateDocumentName,
      refreshNodeSecretStatuses: callbacks.refreshNodeSecretStatuses,
      clearGraphSecretStatuses: callbacks.clearGraphSecretStatuses,
      clearPendingConnectionRoute: callbacks.clearPendingConnectionRoute,
      clearRunError: callbacks.clearRunError,
      closeNodeLibrary: callbacks.closeNodeLibrary,
      requestCanvasRefit: callbacks.requestCanvasRefit,
      refreshNodeRegistry: callbacks.refreshNodeRegistry,
    },
    callbacks,
  };
}

async function flushAsyncWork(): Promise<void> {
  await React.act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function waitFor(assertion: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (assertion()) return;
    await flushAsyncWork();
  }
  throw new Error("Hook did not reach the expected state");
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  // A Graph whose instances nobody has run holds no results, so the cards open
  // empty rather than failing the open.
  api.listGraphInstances.mockResolvedValue({ instances: [] });
  api.createProject.mockImplementation((_workspaceId, body) =>
    Promise.resolve({
      id: PROJECT_ID,
      name: body.name,
      created_at: "2026-07-17T12:00:00Z",
      updated_at: "2026-07-17T12:00:00Z",
    }),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useSavedGraphLifecycle document ownership", () => {
  it("autosaves a new draft through Project creation and command acceptance", async () => {
    vi.useFakeTimers();
    try {
      const graph = savedGraph(GRAPH_A_ID, "My draft");
      stubCreate(GRAPH_A_ID, graph);
      const { options } = lifecycleOptions(null, undefined, {
        name: "My draft",
        nodes: [],
        edges: [],
        origins: [],
        agents: [],
      });
      const hook = await renderHook((props: LifecycleOptions) => {
        const lifecycle = useSavedGraphLifecycle(props);
        useGraphAutosave({
          enabled: !lifecycle.persistenceOperationBusy,
          dirty: lifecycle.isDirty,
          fingerprint: lifecycle.currentFingerprint,
          save: lifecycle.saveCurrentGraph,
        });
        return lifecycle;
      }, options);
      expect(api.createProject).not.toHaveBeenCalled();
      await React.act(async () => vi.advanceTimersByTimeAsync(1000));
      expect(api.createProject).toHaveBeenCalledTimes(1);
      expect(api.checkpointProject).not.toHaveBeenCalled();
      expect(submittedDocuments()).toHaveLength(1);
      expect(hook.result.current.activeGraph?.id).toBe(GRAPH_A_ID);
      expect(hook.result.current.persistenceError).toBeNull();
      await hook.unmount();
    } finally {
      vi.useRealTimers();
    }
  });

  it("pauses editing and prevents duplicate creation during a first save", async () => {
    const graph = savedGraph(GRAPH_A_ID, "First save");
    stubCreate(GRAPH_A_ID, graph);
    const submitted = deferred<CollaborativeHead>();
    api.getCollaborativeHead.mockReturnValue(submitted.promise);
    const { options } = lifecycleOptions(null);
    const hook = await renderHook(useSavedGraphLifecycle, options);

    let save!: Promise<void>;
    await React.act(async () => {
      save = hook.result.current.saveCurrentGraph("First save");
      await hook.result.current.saveCurrentGraph("Duplicate");
    });
    expect(hook.result.current.persistenceOperationBusy).toBe(true);
    expect(api.createProject).toHaveBeenCalledTimes(1);

    await React.act(async () => {
      submitted.resolve(projectHead(graph));
      await save;
    });
    expect(hook.result.current.activeGraph?.id).toBe(GRAPH_A_ID);
    expect(hook.result.current.persistenceOperationBusy).toBe(false);
  });

  it("reuses the first-save identity after a response is lost", async () => {
    const graph = savedGraph(GRAPH_A_ID, "First save");
    stubCreate(GRAPH_A_ID, graph);
    api.createProject.mockRejectedValueOnce(new Error("Connection lost"));
    const { options } = lifecycleOptions(null);
    const hook = await renderHook(useSavedGraphLifecycle, options);

    await React.act(async () =>
      hook.result.current.saveCurrentGraph("First save"),
    );
    expect(hook.result.current.persistenceError).toBe("Connection lost");

    await React.act(async () =>
      hook.result.current.saveCurrentGraph("First save"),
    );
    expect(api.createProject.mock.calls[1]).toEqual(
      api.createProject.mock.calls[0],
    );
    expect(hook.result.current.activeGraph?.id).toBe(GRAPH_A_ID);
  });

  it("submits the canonical final drag position", async () => {
    const finalPosition = { x: 240, y: 180 };
    const node = {
      id: "source",
      kind: "builtin" as const,
      operator_id: "test.source",
      operator_version: 1,
      config: { label: "source" },
      input_plugs: [],
      artifact_type_bindings: [],
      position: finalPosition,
      layout: null,
    };
    const graph: SavedGraph = {
      ...savedGraph(GRAPH_A_ID, "Dragged graph", 3),
      document: {
        ...savedGraph(GRAPH_A_ID, "Dragged graph", 3).document,
        nodes: [node],
      },
    };
    const document = {
      name: "Dragged graph",
      nodes: [node],
      edges: [],
      origins: [],
      agents: [],
    };
    stubCreate(GRAPH_A_ID, graph);
    const { options, callbacks } = lifecycleOptions(null, undefined, document);
    const hook = await renderHook(useSavedGraphLifecycle, options);

    await React.act(async () => {
      await hook.result.current.saveCurrentGraph();
    });

    // A first save names a Project and writes the canvas into its Graph. The
    // node has to carry the position the drag ended at, not the one it started
    // from, or the canvas the next person opens is the canvas before the drag.
    expect(api.createProject).toHaveBeenCalledWith(
      "workspace-1",
      expect.objectContaining({ name: "Dragged graph" }),
    );
    expect(submittedDocuments()[0]).toMatchObject({
      nodes: [expect.objectContaining({ position: finalPosition })],
    });

    expect(callbacks.replaceDocument).not.toHaveBeenCalled();
  });

  it("uses the accepted live head for active nodes and refreshes changed secret bindings", async () => {
    const spec = nodeSpecFixture({
      operator_id: "llm.example",
      secret_inputs: [
        {
          name: "api_key",
          title: "API key",
          config_dependencies: ["base_url"],
          provider_kind: "openai_compatible",
          supports_verification: true,
        },
      ],
    });
    const node = {
      id: "llm",
      kind: "builtin" as const,
      operator_id: spec.operator_id,
      operator_version: spec.operator_version,
      config: { base_url: "https://first.example" },
      position: { x: 0, y: 0 },
      input_plugs: [],
      artifact_type_bindings: [],
    };
    const graph = savedGraph(GRAPH_A_ID, "Live graph", 1);
    const original = {
      ...graph,
      document: { ...graph.document, nodes: [node] },
    };
    const originalHead = projectHead(original);
    const refresh = vi.fn().mockResolvedValue(true);
    const { options, callbacks } = lifecycleOptions(GRAPH_A_ID, refresh);
    options.registry = { ...registry, nodes: [spec] };
    const hook = await renderHook(useSavedGraphLifecycle, {
      ...options,
      roomHead: originalHead,
    });
    expect(refresh).toHaveBeenCalledTimes(1);

    const changedNode = {
      ...node,
      config: { base_url: "https://second.example" },
    };
    const acceptedHead = projectHead(
      { ...original, document: { ...original.document, nodes: [changedNode] } },
      { collaborationSequence: 2, checkpointSequence: 1 },
    );
    await hook.rerender({
      ...options,
      roomHead: acceptedHead,
      hasPendingRoomCommands: true,
    });
    expect(hook.result.current.isDirty).toBe(true);
    expect(hook.result.current.activeGraph).toMatchObject({
      revision: 2,
      nodes: [changedNode],
    });
    expect(refresh).toHaveBeenCalledTimes(2);
    expect(refresh).toHaveBeenLastCalledWith(
      expect.objectContaining({ revision: 2, nodes: [changedNode] }),
      [expect.objectContaining({ id: "llm" })],
      expect.any(AbortSignal),
    );

    await hook.rerender({ ...options, roomHead: acceptedHead });
    expect(hook.result.current.isDirty).toBe(false);

    await hook.rerender({
      ...options,
      roomHead: {
        ...acceptedHead,
        checkpoint_sequence: 2,
        checkpoint_revision: 2,
      },
    });
    expect(callbacks.replaceDocument).not.toHaveBeenCalled();
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("retries a transient secret status failure without an edit", async () => {
    vi.useFakeTimers();
    try {
      const graph = savedGraph(GRAPH_A_ID, "Live graph");
      const refresh = vi
        .fn()
        .mockResolvedValueOnce(false)
        .mockResolvedValueOnce(true);
      const { options } = lifecycleOptions(GRAPH_A_ID, refresh);
      const hook = await renderHook(useSavedGraphLifecycle, {
        ...options,
        roomHead: projectHead(graph),
      });

      expect(refresh).toHaveBeenCalledTimes(1);
      await React.act(async () => vi.advanceTimersByTimeAsync(1000));
      expect(refresh).toHaveBeenCalledTimes(2);
      await hook.unmount();
    } finally {
      vi.useRealTimers();
    }
  });

  it("never submits a save for an existing Project", async () => {
    const graph = savedGraph(GRAPH_A_ID, "Saved graph", 3);
    const { options } = lifecycleOptions(GRAPH_A_ID);
    const hook = await renderHook(useSavedGraphLifecycle, {
      ...options,
      roomHead: projectHead(graph, { checkpointSequence: 1 }),
    });

    await React.act(async () => {
      await hook.result.current.saveCurrentGraph("New name");
    });

    expect(api.createProject).not.toHaveBeenCalled();
    expect(api.submitProjectCommand).not.toHaveBeenCalled();
    expect(api.checkpointProject).not.toHaveBeenCalled();
    expect(hook.result.current.isDirty).toBe(false);
  });

  it("restores the canonical final drag position when opening", async () => {
    const finalPosition = { x: 240, y: 180 };
    const graph: SavedGraph = {
      ...savedGraph(GRAPH_A_ID, "Dragged graph", 3),
      document: {
        ...savedGraph(GRAPH_A_ID, "Dragged graph", 3).document,
        nodes: [
          {
            id: "source",
            kind: "builtin" as const,
            operator_id: "test.source",
            operator_version: 1,
            config: { label: "source" },
            input_plugs: [],
            artifact_type_bindings: [],
            position: finalPosition,
            layout: null,
          },
        ],
      },
    };
    stubOpen(graph);
    const { options, callbacks } = lifecycleOptions(GRAPH_A_ID);
    await renderHook(useSavedGraphLifecycle, options);

    await waitFor(() => callbacks.replaceDocument.mock.calls.length === 1);

    const openedDocument = callbacks.replaceDocument.mock.calls[0]?.[0];
    expect(openedDocument.nodes[0]?.position).toEqual(finalPosition);
  });

  it("opens a graph containing an unavailable operator as a preserved placeholder", async () => {
    const graph: SavedGraph = {
      ...savedGraph(GRAPH_A_ID, "Legacy graph"),
      document: {
        ...savedGraph(GRAPH_A_ID, "Legacy graph").document,
        nodes: [
          {
            id: "legacy-node",
            kind: "builtin" as const,
            operator_id: "legacy.operator",
            operator_version: 7,
            config: { preserved: true },
            position: { x: 20, y: 40 },
            input_plugs: [],
            artifact_type_bindings: [],
          },
        ],
      },
    };
    stubOpen(graph);
    const { options, callbacks } = lifecycleOptions(GRAPH_A_ID);
    const hook = await renderHook(useSavedGraphLifecycle, options);

    await waitFor(() => hook.result.current.activeGraph?.id === GRAPH_A_ID);

    expect(hook.result.current.persistenceError).toBeNull();
    expect(callbacks.replaceDocument).toHaveBeenCalledOnce();
    const openedDocument = callbacks.replaceDocument.mock.calls[0]?.[0];
    expect(openedDocument.nodes).toHaveLength(1);
    expect(openedDocument.nodes[0]).toMatchObject({
      operator_id: "legacy.operator",
      operator_version: 7,
    });
  });

  it("does not apply trailing UI mutations from an open superseded during secret refresh", async () => {
    const graphA = savedGraph(GRAPH_A_ID, "Graph A");
    const graphB = savedGraph(GRAPH_B_ID, "Graph B");
    const graphASecrets = deferred<boolean>();
    stubOpen(graphA);
    api.getCollaborativeHead.mockImplementation((_workspaceId, projectId) =>
      Promise.resolve(projectHead(projectId === GRAPH_A_ID ? graphA : graphB)),
    );
    const refreshSecrets = vi.fn((graph: { id: string }) =>
      graph.id === GRAPH_A_ID ? graphASecrets.promise : Promise.resolve(true),
    );
    const { options, callbacks } = lifecycleOptions(GRAPH_A_ID, refreshSecrets);
    const hook = await renderHook(useSavedGraphLifecycle, options);

    await waitFor(() => hook.result.current.activeGraph?.id === GRAPH_A_ID);
    expect(refreshSecrets).toHaveBeenCalledTimes(1);

    await hook.rerender({ ...options, initialGraphId: GRAPH_B_ID });
    await waitFor(() => hook.result.current.activeGraph?.id === GRAPH_B_ID);
    await waitFor(() => hook.result.current.openingGraphId === null);

    await React.act(async () => {
      graphASecrets.resolve(true);
      await graphASecrets.promise;
    });

    expect(hook.result.current.graphName).toBe("Graph B");
    expect(callbacks.requestCanvasRefit).toHaveBeenCalledTimes(2);
  });

  it("marks a graph switch busy before the route reaches the loading effect", async () => {
    const graphA = savedGraph(GRAPH_A_ID, "Graph A");
    stubOpen(graphA);
    const { options } = lifecycleOptions(GRAPH_A_ID);
    const hook = await renderHook(useSavedGraphLifecycle, options);
    await waitFor(() => hook.result.current.activeGraph?.id === GRAPH_A_ID);

    await React.act(async () => {
      await hook.result.current.openSavedGraph(GRAPH_B_ID);
    });

    expect(router.push).toHaveBeenCalledWith(
      `/workspaces/team/projects/${GRAPH_B_ID}`,
      { scroll: false },
    );
    expect(hook.result.current.openingGraphId).toBe(GRAPH_B_ID);
    expect(hook.result.current.persistenceOperationBusy).toBe(true);
  });

  it("clears the graph-switch lock when navigation throws", async () => {
    const graphA = savedGraph(GRAPH_A_ID, "Graph A");
    stubOpen(graphA);
    router.push.mockImplementationOnce(() => {
      throw new Error("Route unavailable");
    });
    const { options } = lifecycleOptions(GRAPH_A_ID);
    const hook = await renderHook(useSavedGraphLifecycle, options);
    await waitFor(() => hook.result.current.activeGraph?.id === GRAPH_A_ID);

    await React.act(async () => {
      await hook.result.current.openSavedGraph(GRAPH_B_ID);
    });

    expect(hook.result.current.openingGraphId).toBeNull();
    expect(hook.result.current.persistenceOperationBusy).toBe(false);
    expect(hook.result.current.persistenceError).toBe(
      "Could not navigate to the graph: Route unavailable",
    );
  });

  it("does not let a late create response replace a graph opened by navigation", async () => {
    const graphB = savedGraph(GRAPH_B_ID, "Graph B");
    const created = savedGraph(GRAPH_A_ID, "Local draft");
    stubCreate(GRAPH_A_ID, created);
    const createResponse = deferred<{ id: string }>();
    api.createProject.mockReturnValue(createResponse.promise);
    api.getCollaborativeHead.mockImplementation((_workspaceId, projectId) =>
      Promise.resolve(projectHead(projectId === GRAPH_A_ID ? created : graphB)),
    );
    stubOpen(graphB);
    const { options } = lifecycleOptions(null);
    const hook = await renderHook(useSavedGraphLifecycle, options);

    await React.act(async () => {
      hook.result.current.setGraphName("Local draft");
    });
    let savePromise!: Promise<void>;
    await React.act(async () => {
      savePromise = hook.result.current.saveCurrentGraph();
      await Promise.resolve();
    });
    await hook.rerender({ ...options, initialGraphId: GRAPH_B_ID });
    await waitFor(() => hook.result.current.activeGraph?.id === GRAPH_B_ID);

    await React.act(async () => {
      createResponse.resolve({ id: created.id });
      await savePromise;
    });

    expect(hook.result.current.activeGraph?.id).toBe(GRAPH_B_ID);
    expect(hook.result.current.graphName).toBe("Graph B");
    expect(router.replace).not.toHaveBeenCalled();
    expect(graphSummaryRefresh).toHaveBeenCalledWith(options.workspaceId);
  });

  it("does not let a late active-delete response clear a graph opened by navigation", async () => {
    const graphA = savedGraph(GRAPH_A_ID, "Graph A");
    const graphB = savedGraph(GRAPH_B_ID, "Graph B");
    const deleteResponse = deferred<void>();
    stubOpen(graphA);
    api.getCollaborativeHead.mockImplementation((_workspaceId, projectId) =>
      Promise.resolve(projectHead(projectId === GRAPH_A_ID ? graphA : graphB)),
    );
    api.deleteProject.mockReturnValue(deleteResponse.promise);
    const { options, callbacks } = lifecycleOptions(GRAPH_A_ID);
    const hook = await renderHook(useSavedGraphLifecycle, options);
    await waitFor(() => hook.result.current.activeGraph?.id === GRAPH_A_ID);

    let deletePromise!: Promise<void>;
    await React.act(async () => {
      deletePromise = hook.result.current.removeSavedGraph(
        savedGraphSummary(graphA),
      );
      await Promise.resolve();
    });
    await hook.rerender({ ...options, initialGraphId: GRAPH_B_ID });
    await waitFor(() => hook.result.current.activeGraph?.id === GRAPH_B_ID);
    const canvasReplacementCount = callbacks.replaceDocument.mock.calls.length;

    await React.act(async () => {
      deleteResponse.resolve();
      await deletePromise;
    });

    expect(hook.result.current.activeGraph?.id).toBe(GRAPH_B_ID);
    expect(hook.result.current.graphName).toBe("Graph B");
    expect(router.replace).not.toHaveBeenCalled();
    expect(callbacks.clearGraphSecretStatuses).not.toHaveBeenCalled();
    expect(callbacks.replaceDocument).toHaveBeenCalledTimes(
      canvasReplacementCount,
    );
    expect(graphSummaryRefresh).toHaveBeenCalledWith(options.workspaceId);
    expect(callbacks.refreshNodeRegistry).toHaveBeenCalledOnce();
  });

  it("aborts an in-flight open and skips its trailing mutations on unmount", async () => {
    const graph = savedGraph(GRAPH_A_ID, "Graph A");
    const response = deferred<CollaborativeHead>();
    let requestSignal: AbortSignal | undefined;
    api.getCollaborativeHead.mockImplementation(
      (_workspaceId, _projectId, signal) => {
        requestSignal = signal;
        return response.promise;
      },
    );
    const { options, callbacks } = lifecycleOptions(GRAPH_A_ID);
    const hook = await renderHook(useSavedGraphLifecycle, options);
    expect(hook.result.current.openingGraphId).toBe(GRAPH_A_ID);

    await hook.unmount();
    expect(requestSignal?.aborted).toBe(true);

    response.resolve(projectHead(graph));
    await flushAsyncWork();
    expect(callbacks.replaceDocument).not.toHaveBeenCalled();
    expect(callbacks.requestCanvasRefit).not.toHaveBeenCalled();
  });

  it("routes a newly created graph before secret refresh finishes", async () => {
    const secretRefresh = deferred<boolean>();
    stubCreate(GRAPH_A_ID, savedGraph(GRAPH_A_ID, "Created graph"));
    const refreshSecrets = vi.fn(() => secretRefresh.promise);
    const { options, callbacks } = lifecycleOptions(null, refreshSecrets);
    const hook = await renderHook(useSavedGraphLifecycle, options);

    await React.act(async () => {
      hook.result.current.setGraphName("Created graph");
    });
    let savePromise!: Promise<void>;
    await React.act(async () => {
      savePromise = hook.result.current.saveCurrentGraph("Created graph");
      await Promise.resolve();
    });
    await waitFor(() => refreshSecrets.mock.calls.length === 1);
    await flushAsyncWork();

    expect(hook.result.current.activeGraph?.id).toBe(GRAPH_A_ID);
    expect(router.replace).toHaveBeenCalledWith(
      `/workspaces/team/projects/${GRAPH_A_ID}`,
      { scroll: false },
    );
    expect(callbacks.replaceDocument).not.toHaveBeenCalled();
    const routeOrder = router.replace.mock.invocationCallOrder.at(0);
    const secretRefreshOrder = refreshSecrets.mock.invocationCallOrder.at(0);
    if (routeOrder === undefined || secretRefreshOrder === undefined) {
      throw new Error("Expected routing and secret refresh to both run");
    }
    expect(routeOrder).toBeLessThan(secretRefreshOrder);

    await React.act(async () => {
      secretRefresh.resolve(true);
      await savePromise;
    });
  });

  describe("leaving the page", () => {
    function fireBeforeUnload(): boolean {
      const event = new Event("beforeunload", {
        cancelable: true,
        bubbles: true,
      });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    }

    async function openJournaledGraph(name: string) {
      stubOpen(savedGraph(GRAPH_A_ID, name, 4));
      const rendered = lifecycleOptions(GRAPH_A_ID);
      const hook = await renderHook(useSavedGraphLifecycle, rendered.options);
      await waitFor(() => hook.result.current.activeGraph?.id === GRAPH_A_ID);
      return { ...rendered, hook };
    }

    it("stays silent when the room journal already holds the canvas", async () => {
      const { options, hook } = await openJournaledGraph("Journal holds it");

      // An edit the room has recorded but no checkpoint has captured yet.
      await React.act(async () => {
        await hook.rerender({
          ...options,
          document: {
            ...options.document,
            name: "Renamed after a journal write",
          },
        });
      });

      expect(hook.result.current.isDirty).toBe(false);
      expect(fireBeforeUnload()).toBe(false);
    });

    it("opens a new graph without asking when the journal holds the canvas", async () => {
      const { options, hook } = await openJournaledGraph("Journal holds it");
      await React.act(async () => {
        await hook.rerender({
          ...options,
          document: {
            ...options.document,
            name: "Renamed after a journal write",
          },
        });
      });

      await React.act(async () => {
        hook.result.current.requestNewGraph();
      });

      expect(window.confirm).not.toHaveBeenCalled();
    });

    it("leaves without asking when the room refused edits while reconnecting", async () => {
      const { options, hook } = await openJournaledGraph("Refused edits");
      expect(fireBeforeUnload()).toBe(false);

      await React.act(async () => {
        await hook.rerender({ ...options, hasUnsyncedRoomEdits: true });
      });

      expect(fireBeforeUnload()).toBe(false);
      await React.act(async () => {
        hook.result.current.requestNewGraph();
      });
      expect(window.confirm).not.toHaveBeenCalled();
    });

    it("leaves without asking while the graph exists only in this tab", async () => {
      const { options } = lifecycleOptions(null, undefined, {
        name: "Drawn but never saved",
        nodes: [],
        edges: [],
        origins: [],
        agents: [],
      });
      await renderHook(useSavedGraphLifecycle, options);

      expect(fireBeforeUnload()).toBe(false);
    });

    it("stays silent for an empty canvas nobody has drawn on", async () => {
      await renderHook(useSavedGraphLifecycle, lifecycleOptions(null).options);

      expect(fireBeforeUnload()).toBe(false);
    });
  });
});

describe("useSavedGraphLifecycle Graphs inside one Project", () => {
  // Every other case here puts a Project and its Graph on the same id, which is
  // the shape a single-Graph Project really has. These cases keep the two apart,
  // because "which Graph of this Project is the canvas showing?" is a question
  // the Project model newly asks and a shared fixture cannot answer.
  const SHARED_PROJECT_ID = "00000000-0000-4000-8000-00000000000d";

  function graphDefinition(id: string, name: string) {
    return { id, name, document: savedGraph(id, name).document };
  }

  function headWithGraphs(
    graphs: readonly {
      id: string;
      name: string;
      document: SavedGraphDocument;
    }[],
    sequences: { collaboration: number; checkpoint?: number },
  ): CollaborativeHead {
    const checkpoint = sequences.checkpoint ?? sequences.collaboration;
    return {
      project_id: SHARED_PROJECT_ID,
      name: "Two graphs, one project",
      room_epoch: ROOM_EPOCH,
      collaboration_sequence: sequences.collaboration,
      checkpoint_sequence: checkpoint,
      checkpoint_revision: checkpoint,
      updated_at: "2026-08-14T12:00:00Z",
      document: { graphs },
    };
  }

  it("opens a Project's first Graph and keeps the Project's own address", async () => {
    api.getCollaborativeHead.mockResolvedValue(
      headWithGraphs(
        [
          graphDefinition(GRAPH_A_ID, "First"),
          graphDefinition(GRAPH_B_ID, "Second"),
        ],
        { collaboration: 6 },
      ),
    );
    const { options } = lifecycleOptions(SHARED_PROJECT_ID);
    const hook = await renderHook(useSavedGraphLifecycle, options);
    await waitFor(() => hook.result.current.activeGraph !== null);

    // The route names the Project and the canvas shows one Graph of it, so the
    // caller needs both ids to say which. The revision is the head's: no Graph
    // of a Project has a counter of its own to disagree with.
    expect(hook.result.current.activeGraph).toMatchObject({
      id: SHARED_PROJECT_ID,
      graphId: GRAPH_A_ID,
      revision: 6,
    });
    expect(hook.result.current.graphName).toBe("First");
    // Stored results belong to a Graph's node instances, addressed inside the
    // Project. Asking with the Project id as the Graph would open the first
    // Graph's cards onto whichever Graph the canvas ended up showing.
    const instanceRead = api.listGraphInstances.mock.calls.at(0);
    if (instanceRead === undefined)
      throw new Error("Expected the open to read the Graph's instances");
    expect(instanceRead.slice(0, 3)).toEqual([
      "workspace-1",
      SHARED_PROJECT_ID,
      GRAPH_A_ID,
    ]);
  });

  it("keeps the Graph the canvas opened when a newer head lists it second", async () => {
    api.getCollaborativeHead.mockResolvedValue(
      headWithGraphs(
        [
          graphDefinition(GRAPH_A_ID, "First"),
          graphDefinition(GRAPH_B_ID, "Second"),
        ],
        { collaboration: 6 },
      ),
    );
    const { options, callbacks } = lifecycleOptions(SHARED_PROJECT_ID);
    const hook = await renderHook(useSavedGraphLifecycle, options);
    await waitFor(
      () => hook.result.current.activeGraph?.graphId === GRAPH_A_ID,
    );

    // A checkpoint that happens to list the Graphs in the other order is not a
    // request to change what the author is looking at: the canvas keeps its
    // Graph and the document it was given.
    React.act(() => {
      hook.result.current.syncFromCollaborativeHead(
        headWithGraphs(
          [
            graphDefinition(GRAPH_B_ID, "Second"),
            graphDefinition(GRAPH_A_ID, "First"),
          ],
          { collaboration: 7 },
        ),
      );
    });

    expect(hook.result.current.activeGraph).toMatchObject({
      id: SHARED_PROJECT_ID,
      graphId: GRAPH_A_ID,
      revision: 7,
    });
    expect(callbacks.replaceDocument).toHaveBeenLastCalledWith(
      expect.objectContaining({ name: "First" }),
    );
  });

  it("says so when a Project holds no Graph to open", async () => {
    api.getCollaborativeHead.mockResolvedValue(
      headWithGraphs([], { collaboration: 1 }),
    );
    const { options, callbacks } = lifecycleOptions(SHARED_PROJECT_ID);
    const hook = await renderHook(useSavedGraphLifecycle, options);
    await waitFor(() => hook.result.current.persistenceError !== null);

    // An empty Project is a state the browser can genuinely link to. The canvas
    // stays where it was and the person is told, rather than being shown a blank
    // canvas under the address of somebody else's work.
    expect(hook.result.current.persistenceError).toBe(
      "This project holds no graph to open.",
    );
    expect(hook.result.current.activeGraph).toBeNull();
    expect(callbacks.replaceDocument).not.toHaveBeenCalled();
  });
});

describe("useSavedGraphLifecycle presentation ownership", () => {
  const sourceSpec: NodeSpec = nodeSpecFixture({
    operator_id: "test.source",
    title: "Source",
    description: "Source",
    outputs: [
      artifactPortFixture({
        name: "output",
        title: "Output",
        direction: "output",
        required: false,
      }),
    ],
  });

  const producerNode = {
    id: "node-a",
    kind: "builtin" as const,
    operator_id: "test.source",
    operator_version: 1,
    config: {},
    input_plugs: [],
    artifact_type_bindings: [],
    position: { x: 0, y: 0 },
    layout: null,
  };

  const cardViewer = {
    id: "artifact-viewer-1",
    position: { x: 320, y: 0 },
    layout: null,
    mode: null,
    artifact_ref: null,
  };

  const cardLink = {
    id: "artifact-viewer-edge-1",
    source_node_id: "node-a",
    source_port_name: "output",
    target_viewer_id: "artifact-viewer-1",
    projection: null,
    route_offset: null,
  };

  /**
   * Models the workbench's artifact-card slice: `replacePresentation` is the only writer,
   * so whatever it last held is what the canvas paints and the save body carries.
   */
  function presentationCanvas() {
    const held = {
      presentation: {
        viewers: [],
        links: [],
        bindings: [],
        annotations: [],
      } as NonNullable<SavedGraphDocument["presentation"]>,
    };
    return {
      held,
      replace(presentation: typeof held.presentation) {
        held.presentation = presentation;
      },
    };
  }

  it("saves a new graph without the artifact cards of the graph opened before it", async () => {
    const graphA: SavedGraph = {
      ...savedGraph(GRAPH_A_ID, "Graph with cards", 4),
      document: {
        ...savedGraph(GRAPH_A_ID, "Graph with cards", 4).document,
        nodes: [producerNode],
        presentation: {
          viewers: [cardViewer],
          links: [cardLink],
          bindings: [],
          annotations: [],
        },
      },
    };
    stubOpen(graphA);
    stubCreate(GRAPH_B_ID, savedGraph(GRAPH_B_ID, "Untitled workflow", 1));

    const canvas = presentationCanvas();
    const { options, callbacks } = lifecycleOptions(GRAPH_A_ID);
    options.registry = { ...registry, nodes: [sourceSpec] };
    callbacks.replacePresentation.mockImplementation(canvas.replace);
    const props = () => ({
      ...options,
      presentation: canvas.held.presentation,
    });

    const hook = await renderHook(useSavedGraphLifecycle, props());
    await waitFor(() => hook.result.current.activeGraph?.id === GRAPH_A_ID);
    await hook.rerender(props());

    // Opening a graph puts its cards on the canvas.
    expect(canvas.held.presentation.viewers.map((viewer) => viewer.id)).toEqual(
      ["artifact-viewer-1"],
    );
    expect(canvas.held.presentation.links.map((link) => link.id)).toEqual([
      "artifact-viewer-edge-1",
    ]);

    // Starting a new graph moves the route and renders the blank draft over the top.
    await React.act(async () => {
      hook.result.current.requestNewGraph();
    });
    expect(router.push).toHaveBeenCalledWith("/workspaces/team/projects/new", {
      scroll: false,
    });
    await React.act(async () => {
      await hook.rerender({
        ...props(),
        initialGraphId: null,
      });
    });
    // The workbench then renders the blank draft, which hands the hook the presentation
    // the canvas now holds — the same re-render that replaces the document.
    await React.act(async () => {
      await hook.rerender({
        ...props(),
        initialGraphId: null,
      });
    });

    expect(hook.result.current.activeGraph).toBeNull();
    expect(canvas.held.presentation.viewers).toEqual([]);
    expect(canvas.held.presentation.links).toEqual([]);

    await React.act(async () => {
      await hook.result.current.saveCurrentGraph();
    });

    const document = submittedDocuments()[0];
    expect(document?.nodes).toEqual([]);
    // The cards are the canvas' own layout, so a new Project starts with none of
    // the previous Graph's cards on it.
    expect(document?.presentation?.links).toEqual([]);
    expect(document?.presentation?.viewers).toEqual([]);
  });

  it("keeps the cards a collaborator moved during a delete on the draft it keeps", async () => {
    const graphA: SavedGraph = {
      ...savedGraph(GRAPH_A_ID, "Graph with cards", 4),
      document: {
        ...savedGraph(GRAPH_A_ID, "Graph with cards", 4).document,
        nodes: [producerNode],
        presentation: {
          viewers: [cardViewer],
          links: [cardLink],
          bindings: [],
          annotations: [],
        },
      },
    };
    stubOpen(graphA);
    const deleteResponse = deferred<void>();
    api.deleteProject.mockReturnValue(deleteResponse.promise);

    const canvas = presentationCanvas();
    const { options, callbacks } = lifecycleOptions(GRAPH_A_ID);
    options.registry = { ...registry, nodes: [sourceSpec] };
    callbacks.replacePresentation.mockImplementation(canvas.replace);
    const props = () => ({
      ...options,
      presentation: canvas.held.presentation,
    });

    const hook = await renderHook(useSavedGraphLifecycle, props());
    await waitFor(() => hook.result.current.activeGraph?.id === GRAPH_A_ID);
    await hook.rerender(props());

    let deletePromise!: Promise<void>;
    await React.act(async () => {
      deletePromise = hook.result.current.removeSavedGraph(
        savedGraphSummary(graphA),
      );
      await Promise.resolve();
    });

    // The card moves while the delete is in flight. Local editing is paused for the
    // whole delete, so this can only be a command that arrived from the room.
    canvas.replace({
      ...canvas.held.presentation,
      viewers: [{ ...cardViewer, position: { x: 999, y: 0 } }],
    });
    await React.act(async () => {
      await hook.rerender(props());
    });

    await React.act(async () => {
      deleteResponse.resolve();
      await deletePromise;
    });

    expect(canvas.held.presentation.viewers[0]?.position).toEqual({
      x: 999,
      y: 0,
    });
    expect(hook.result.current.persistenceError).toContain(
      "remain as an unsaved draft",
    );
  });
});

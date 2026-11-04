// @vitest-environment jsdom

import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CollaborativeHead,
  GraphCommandInput,
  NodeRegistry,
  NodeSpec,
  SavedGraph,
  SavedGraphDocument,
  SavedGraphSummary,
} from "@/lib/api";
import { deferred } from "./test/deferred";
import { renderHook } from "./test/renderHook";
import {
  useSavedGraphLifecycle,
  type GraphRoomPersistenceResult,
} from "./useSavedGraphLifecycle";

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
 * Project command and checkpoints it, and deleting retires the whole Project.
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

/**
 * A head whose document is given directly, for the room cases that are not a
 * saved Graph — a peer's edit, or a journal write no checkpoint has caught.
 */
function headWithDocument(
  projectId: string,
  document: SavedGraphDocument,
  sequences: { collaboration: number; checkpoint: number },
  name = "Room head",
): CollaborativeHead {
  return {
    project_id: projectId,
    name,
    room_epoch: ROOM_EPOCH,
    collaboration_sequence: sequences.collaboration,
    checkpoint_sequence: sequences.checkpoint,
    checkpoint_revision: sequences.checkpoint,
    updated_at: "2026-08-13T12:00:00Z",
    document: { graphs: [{ id: projectId, name, document }] },
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

/** The create path: a new Project, then its first Graph's document. */
function stubCreate(
  projectId: string,
  graph: SavedGraph,
  options: { holdCheckpoint?: boolean } = {},
) {
  api.createProject.mockResolvedValue({
    id: projectId,
    name: graph.name,
    created_at: graph.created_at,
    updated_at: graph.updated_at,
  });
  return stubRoomlessSave(projectId, graph, options);
}

/** The document a save submitted, as the Project command carried it. */
function submittedDocuments(): Extract<
  GraphCommandInput,
  { kind: "replace_document" }
>["document"][] {
  return api.submitProjectCommand.mock.calls.map((call) => {
    const body = call[2] as { commands: { command: GraphCommandInput }[] };
    const command = body.commands[0]?.command;
    if (command?.kind !== "replace_document") {
      throw new Error("Expected the save to submit a replace_document command");
    }
    return command.document;
  });
}

/**
 * The roomless save path: read the head, accept the document command, then
 * checkpoint. The checkpointed head is what a save reports back, and its
 * collaboration sequence is the revision the canvas then holds.
 */
function stubRoomlessSave(
  projectId: string,
  graph: SavedGraph,
  options: { holdCheckpoint?: boolean } = {},
) {
  // A save reads the head of the Project it is writing to. A test that also
  // opened another Project keeps its own head reader: the two are addressed
  // apart, and an open must not start answering for a save.
  const previousHeadRead = api.getCollaborativeHead.getMockImplementation();
  api.getCollaborativeHead.mockImplementation(
    (_workspaceId: string, requestedProjectId: string) =>
      requestedProjectId === projectId
        ? Promise.resolve(
            projectHead(
              savedGraph(projectId, "Before the save", graph.revision),
            ),
          )
        : previousHeadRead !== undefined
          ? previousHeadRead(_workspaceId, requestedProjectId)
          : Promise.resolve(projectHead(graph)),
  );
  api.submitProjectCommand.mockResolvedValue({
    head: projectHead(graph),
    receipt: {
      accepted_sequence: graph.revision,
      command_id: "00000000-0000-4000-8000-0000000000cc",
      deduplicated: false,
      outcome: "applied",
      room_epoch: ROOM_EPOCH,
    },
  });
  const response = deferred<{
    head: CollaborativeHead;
    checkpoint_revision: number;
  }>();
  if (options.holdCheckpoint) {
    api.checkpointProject.mockReturnValue(response.promise);
    return response;
  }
  api.checkpointProject.mockResolvedValue({
    head: projectHead(graph),
    checkpoint_revision: graph.revision,
  });
  return response;
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
      nodes: [],
      isExecutionRunning: () => false,
      replaceDocument: callbacks.replaceDocument,
      replacePresentation: callbacks.replacePresentation,
      updateDocumentName,
      attachNodeCallbacks: (data) => data,
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

  it("keeps an active canvas intact while room persistence is synchronizing", async () => {
    const graph = savedGraph(GRAPH_A_ID, "Graph awaiting sync", 3);
    const persistDocument = vi.fn();
    stubOpen(graph);
    const { options, callbacks } = lifecycleOptions(GRAPH_A_ID);
    options.roomPersistence = {
      canPersist: false,
      persistDocument,
    };
    const hook = await renderHook(useSavedGraphLifecycle, options);
    await waitFor(() => hook.result.current.activeGraph?.id === GRAPH_A_ID);
    const canvasReplacementCount = callbacks.replaceDocument.mock.calls.length;

    await React.act(async () => {
      await hook.result.current.saveCurrentGraph();
    });

    expect(persistDocument).not.toHaveBeenCalled();
    expect(api.submitProjectCommand).not.toHaveBeenCalled();
    expect(callbacks.replaceDocument).toHaveBeenCalledTimes(
      canvasReplacementCount,
    );
    expect(hook.result.current.activeGraph).toMatchObject({
      id: GRAPH_A_ID,
      revision: 3,
    });
    expect(hook.result.current.persistenceError).toBe(
      "Graph synchronization is unavailable while the collaboration room connects or reconnects. Your canvas is unchanged; wait for synchronization to finish, then try saving again.",
    );
  });

  it("keeps an uncheckpointed collaborative head dirty and non-materializable", async () => {
    const checkpointNode = {
      id: "llm",
      kind: "builtin" as const,
      operator_id: "llm.openai.completion",
      operator_version: 1,
      position: { x: 0, y: 0 },
      config: { base_url: "https://api.openai.com/v1" },
    };
    const graph = {
      ...savedGraph(GRAPH_A_ID, "Checkpoint", 3),
      document: {
        ...savedGraph(GRAPH_A_ID, "Checkpoint", 3).document,
        nodes: [
          {
            ...checkpointNode,
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
    const liveHead = headWithDocument(
      GRAPH_A_ID,
      {
        schema_version: 7,
        origins: [],
        agents: [],
        nodes: [
          {
            ...checkpointNode,
            input_plugs: [],
            artifact_type_bindings: [],
            config: { base_url: "https://openrouter.ai/api/v1" },
          },
        ],
        edges: [],
      },
      { collaboration: 4, checkpoint: 3 },
      "Live room edit",
    );

    React.act(() => {
      hook.result.current.syncFromCollaborativeHead(liveHead);
    });

    expect(hook.result.current.activeGraph).toMatchObject({
      id: GRAPH_A_ID,
      revision: 3,
      nodes: [checkpointNode],
    });
    expect(hook.result.current.isDirty).toBe(true);
    expect(hook.result.current.canMaterializeSavedGraph).toBe(false);
    expect(callbacks.replaceDocument).toHaveBeenLastCalledWith(
      expect.objectContaining({
        name: "Live room edit",
        nodes: [
          expect.objectContaining({
            id: "llm",
            config: { base_url: "https://openrouter.ai/api/v1" },
          }),
        ],
        edges: [],
      }),
    );
  });

  it("marks the reconciled room head saved when checkpoint catches up", async () => {
    const graph = savedGraph(GRAPH_A_ID, "Checkpoint", 1);
    stubOpen(graph);
    const { options } = lifecycleOptions(GRAPH_A_ID);
    const checkpointHead = headWithDocument(
      GRAPH_A_ID,
      { schema_version: 7, origins: [], nodes: [], edges: [], agents: [] },
      { collaboration: 4, checkpoint: 4 },
      "Checkpoint",
    );
    options.roomPersistence = {
      canPersist: true,
      persistDocument: vi.fn().mockResolvedValue({
        checkpointHead,
        currentHead: checkpointHead,
      }),
    };
    const hook = await renderHook(useSavedGraphLifecycle, options);
    await waitFor(() => hook.result.current.activeGraph?.id === GRAPH_A_ID);

    await React.act(async () => {
      await hook.result.current.saveCurrentGraph();
    });

    expect(hook.result.current.activeGraph).toMatchObject({
      id: GRAPH_A_ID,
      // The Project head's collaboration sequence is the number the next save
      // is compared against; a checkpoint at that sequence is what made the
      // canvas clean.
      revision: 4,
    });
    expect(hook.result.current.isDirty).toBe(false);
    expect(hook.result.current.canMaterializeSavedGraph).toBe(true);
  });

  it("refreshes the secret binding snapshot from a checkpointed room head", async () => {
    const checkpointNode = {
      id: "llm",
      kind: "builtin" as const,
      operator_id: "llm.openai.completion",
      operator_version: 1,
      position: { x: 0, y: 0 },
      config: { base_url: "https://api.openai.com/v1" },
    };
    const graph = {
      ...savedGraph(GRAPH_A_ID, "Checkpoint", 1),
      document: {
        ...savedGraph(GRAPH_A_ID, "Checkpoint", 1).document,
        nodes: [
          {
            ...checkpointNode,
            input_plugs: [],
            artifact_type_bindings: [],
          },
        ],
      },
    };
    const refreshNodeSecretStatuses = vi.fn().mockResolvedValue(true);
    stubOpen(graph);
    const { options } = lifecycleOptions(GRAPH_A_ID, refreshNodeSecretStatuses);
    const hook = await renderHook(useSavedGraphLifecycle, options);
    await waitFor(() => hook.result.current.activeGraph?.id === GRAPH_A_ID);
    refreshNodeSecretStatuses.mockClear();
    const checkpointedNode = {
      ...checkpointNode,
      input_plugs: [],
      artifact_type_bindings: [],
      config: { base_url: "https://openrouter.ai/api/v1" },
    };

    React.act(() => {
      hook.result.current.syncFromCollaborativeHead(
        headWithDocument(
          GRAPH_A_ID,
          {
            schema_version: 7,
            origins: [],
            agents: [],
            nodes: [checkpointedNode],
            edges: [],
          },
          { collaboration: 4, checkpoint: 4 },
          "Checkpoint",
        ),
      );
    });

    expect(hook.result.current.activeGraph).toMatchObject({
      id: GRAPH_A_ID,
      revision: 4,
      nodes: [checkpointedNode],
    });
    expect(refreshNodeSecretStatuses).toHaveBeenCalledOnce();
    expect(refreshNodeSecretStatuses).toHaveBeenCalledWith(
      expect.objectContaining({
        id: GRAPH_A_ID,
        revision: 4,
        nodes: [expect.objectContaining(checkpointedNode)],
      }),
      expect.any(Array),
    );
  });

  it("keeps a peer head dirty when it advances during checkpoint continuation", async () => {
    const graph = savedGraph(GRAPH_A_ID, "Checkpoint", 1);
    const checkpointContinuation = deferred<GraphRoomPersistenceResult>();
    const persistDocument = vi.fn(() => checkpointContinuation.promise);
    stubOpen(graph);
    const { options, callbacks } = lifecycleOptions(GRAPH_A_ID);
    options.roomPersistence = {
      canPersist: true,
      persistDocument,
    };
    const hook = await renderHook(useSavedGraphLifecycle, options);
    await waitFor(() => hook.result.current.activeGraph?.id === GRAPH_A_ID);

    let savePromise!: Promise<void>;
    await React.act(async () => {
      savePromise = hook.result.current.saveCurrentGraph();
      await Promise.resolve();
    });
    expect(persistDocument).toHaveBeenCalledOnce();

    const peerPresentation = {
      viewers: [
        {
          id: "peer-viewer",
          position: { x: 80, y: 120 },
          layout: null,
          mode: null,
        },
      ],
      links: [],
      bindings: [],
      annotations: [],
    };
    const peerHeadBeforeCheckpoint = headWithDocument(
      GRAPH_A_ID,
      {
        schema_version: 7,
        origins: [],
        agents: [],
        nodes: [],
        edges: [],
        presentation: peerPresentation,
      },
      { collaboration: 5, checkpoint: 1 },
      "Peer presentation",
    );
    React.act(() => {
      hook.result.current.syncFromCollaborativeHead(peerHeadBeforeCheckpoint);
    });

    await React.act(async () => {
      const checkpointHead = headWithDocument(
        GRAPH_A_ID,
        { schema_version: 7, origins: [], nodes: [], edges: [], agents: [] },
        { collaboration: 4, checkpoint: 4 },
        "Checkpoint",
      );
      checkpointContinuation.resolve({
        checkpointHead,
        currentHead: {
          ...peerHeadBeforeCheckpoint,
          checkpoint_sequence: 4,
          checkpoint_revision: 4,
        },
      });
      await savePromise;
    });

    expect(hook.result.current.activeGraph).toMatchObject({
      id: GRAPH_A_ID,
      // The peer's newer sequence is not a save, so the canvas still holds the
      // checkpointed sequence the save reported.
      revision: 4,
    });
    expect(hook.result.current.graphName).toBe("Peer presentation");
    expect(hook.result.current.isDirty).toBe(true);
    expect(hook.result.current.canMaterializeSavedGraph).toBe(false);
    expect(callbacks.replacePresentation).toHaveBeenLastCalledWith(
      peerPresentation,
    );
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
    expect(callbacks.clearPendingConnectionRoute).toHaveBeenCalledTimes(1);
    expect(callbacks.clearRunError).toHaveBeenCalledTimes(1);
    expect(callbacks.closeNodeLibrary).toHaveBeenCalledTimes(1);
    expect(callbacks.requestCanvasRefit).toHaveBeenCalledTimes(1);
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
    const createResponse = stubCreate(GRAPH_A_ID, created, {
      holdCheckpoint: true,
    });
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
      createResponse.resolve({
        head: projectHead(created),
        checkpoint_revision: created.revision,
      });
      await savePromise;
    });

    expect(hook.result.current.activeGraph?.id).toBe(GRAPH_B_ID);
    expect(hook.result.current.graphName).toBe("Graph B");
    expect(router.replace).not.toHaveBeenCalled();
    expect(graphSummaryRefresh).toHaveBeenCalledWith(options.workspaceId);
    expect(options.refreshNodeRegistry).toHaveBeenCalledOnce();
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
    const graphA = savedGraph(GRAPH_A_ID, "Graph A");
    const secretRefresh = deferred<boolean>();
    let requestSignal: AbortSignal | undefined;
    api.getCollaborativeHead.mockImplementation(
      (_workspaceId, _projectId, signal) => {
        requestSignal = signal;
        return Promise.resolve(projectHead(graphA));
      },
    );
    const refreshSecrets = vi.fn(() => secretRefresh.promise);
    const { options, callbacks } = lifecycleOptions(GRAPH_A_ID, refreshSecrets);
    const hook = await renderHook(useSavedGraphLifecycle, options);
    await waitFor(() => refreshSecrets.mock.calls.length === 1);

    await hook.unmount();
    expect(requestSignal?.aborted).toBe(true);

    secretRefresh.resolve(true);
    await secretRefresh.promise;
    await flushAsyncWork();

    expect(callbacks.clearPendingConnectionRoute).not.toHaveBeenCalled();
    expect(callbacks.clearRunError).not.toHaveBeenCalled();
    expect(callbacks.closeNodeLibrary).not.toHaveBeenCalled();
    expect(callbacks.requestCanvasRefit).not.toHaveBeenCalled();
  });

  it("accepts a same-document save revision while keeping newer edits dirty", async () => {
    const submitted = savedGraph(GRAPH_A_ID, "Submitted name", 4);
    const createResponse = stubCreate(GRAPH_A_ID, submitted, {
      holdCheckpoint: true,
    });
    const { options } = lifecycleOptions(null);
    const hook = await renderHook(useSavedGraphLifecycle, options);

    await React.act(async () => {
      hook.result.current.setGraphName("Submitted name");
    });
    let savePromise!: Promise<void>;
    await React.act(async () => {
      savePromise = hook.result.current.saveCurrentGraph();
      await Promise.resolve();
    });
    await React.act(async () => {
      hook.result.current.setGraphName("Newer local name");
    });

    await React.act(async () => {
      createResponse.resolve({
        head: projectHead(submitted),
        checkpoint_revision: submitted.revision,
      });
      await savePromise;
    });

    expect(hook.result.current.activeGraph).toMatchObject({
      id: GRAPH_A_ID,
      revision: 4,
    });
    expect(hook.result.current.graphName).toBe("Newer local name");
    expect(hook.result.current.isDirty).toBe(true);
    expect(router.replace).toHaveBeenCalledWith(
      `/workspaces/team/projects/${GRAPH_A_ID}`,
      { scroll: false },
    );
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
      savePromise = hook.result.current.saveCurrentGraph();
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

      expect(hook.result.current.isDirty).toBe(true);
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

  it("writes a save into the Graph the canvas shows, not the Project's first", async () => {
    const opened = headWithGraphs(
      [
        graphDefinition(GRAPH_A_ID, "First"),
        graphDefinition(GRAPH_B_ID, "Second"),
      ],
      { collaboration: 6 },
    );
    // The head a save reads and checkpoints lists the canvas's Graph second, so
    // a write that picked "the first Graph" would land on the other Graph.
    const reordered = headWithGraphs(
      [
        graphDefinition(GRAPH_B_ID, "Second"),
        graphDefinition(GRAPH_A_ID, "First"),
      ],
      { collaboration: 7 },
    );
    api.getCollaborativeHead.mockResolvedValueOnce(opened);
    api.getCollaborativeHead.mockResolvedValue(reordered);
    api.submitProjectCommand.mockResolvedValue({
      head: reordered,
      receipt: {
        accepted_sequence: 7,
        command_id: "00000000-0000-4000-8000-0000000000cc",
        deduplicated: false,
        outcome: "applied",
        room_epoch: ROOM_EPOCH,
      },
    });
    api.checkpointProject.mockResolvedValue({
      head: reordered,
      checkpoint_revision: 7,
    });
    const { options } = lifecycleOptions(SHARED_PROJECT_ID);
    const hook = await renderHook(useSavedGraphLifecycle, options);
    await waitFor(
      () => hook.result.current.activeGraph?.graphId === GRAPH_A_ID,
    );

    await React.act(async () => {
      await hook.result.current.saveCurrentGraph();
    });

    // The command is addressed to the Project, and the Graph it edits is the one
    // on the canvas.
    expect(api.submitProjectCommand).toHaveBeenCalledWith(
      "workspace-1",
      SHARED_PROJECT_ID,
      expect.objectContaining({
        observed_sequence: 7,
        commands: [
          expect.objectContaining({
            kind: "in_graph",
            graph_id: GRAPH_A_ID,
            command: expect.objectContaining({ kind: "replace_document" }),
          }),
        ],
      }),
    );
    expect(api.checkpointProject).toHaveBeenCalledWith(
      "workspace-1",
      SHARED_PROJECT_ID,
      { expected_room_epoch: ROOM_EPOCH, expected_sequence: 7 },
    );
    // The head the save read back lists the other Graph first; that is still not
    // a reason to move the canvas off the one it was editing.
    expect(hook.result.current.activeGraph).toMatchObject({
      id: SHARED_PROJECT_ID,
      graphId: GRAPH_A_ID,
      revision: 7,
    });
  });

  it("pairs a room save with the Graph it writes", async () => {
    const head = headWithGraphs(
      [
        graphDefinition(GRAPH_A_ID, "First"),
        graphDefinition(GRAPH_B_ID, "Second"),
      ],
      { collaboration: 6 },
    );
    const persistDocument = vi.fn().mockResolvedValue({
      checkpointHead: head,
      currentHead: head,
    });
    api.getCollaborativeHead.mockResolvedValue(head);
    const { options } = lifecycleOptions(SHARED_PROJECT_ID);
    options.roomPersistence = { canPersist: true, persistDocument };
    const hook = await renderHook(useSavedGraphLifecycle, options);
    await waitFor(
      () => hook.result.current.activeGraph?.graphId === GRAPH_A_ID,
    );

    await React.act(async () => {
      await hook.result.current.saveCurrentGraph();
    });

    // A draft on its own cannot say which Graph of the Project to replace: the
    // bridge needs the id beside it.
    expect(persistDocument).toHaveBeenCalledWith(
      expect.objectContaining({ name: "First" }),
      GRAPH_A_ID,
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
  const sourceSpec: NodeSpec = {
    operator_id: "test.source",
    operator_version: 1,
    plugin_slug: "test",
    origin: "builtin",
    title: "Source",
    description: "Source",
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [
      {
        name: "output",
        title: "Output",
        description: null,
        direction: "output",
        artifact_type: { id: "scalar.text", schema_version: 1 },
        shape: "one",
        accepted_shapes: ["one"],
        instance_plugs: false,
        variadic: false,
        required: false,
      },
    ],
  };

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

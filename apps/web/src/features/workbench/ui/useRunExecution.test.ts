// @vitest-environment jsdom

import * as React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ActiveRunSummary,
  ArtifactRef,
  InstanceResult,
  InstanceState,
  InstanceStateName,
  NodeSpec,
  Port,
  Run,
  RunStatus,
  SavedGraphNode,
} from "@/lib/api";
import { ApiError } from "@/lib/api/client";
import {
  WORKFLOW_NODE_TYPE,
  createWorkflowNodeData,
  type WorkflowEdge,
  type WorkflowNodeCompatibility,
} from "../canvas/types";
import { encodeHandleId } from "../canvas/handles";
import type { WorkflowNode } from "../model/execution-plan";
import { deferred } from "./test/deferred";
import { renderHook } from "./test/renderHook";
import type { ActiveSavedGraph } from "./useSavedGraphLifecycle";
import {
  RUN_SURFACE_POLL_INTERVAL_MS,
  runRejectionMessage,
  useRunExecution,
} from "./useRunExecution";

const api = vi.hoisted(() => ({
  startRun: vi.fn(),
  listRuns: vi.fn(),
  getRun: vi.fn(),
  cancelRun: vi.fn(),
  listGraphInstances: vi.fn(),
  getInstanceResult: vi.fn(),
}));

vi.mock("@/lib/api", () => api);

const WORKSPACE_ID = "workspace-1";
const PROJECT_ID = "00000000-0000-4000-8000-0000000000p1";
const GRAPH_ID = "00000000-0000-4000-8000-0000000000g1";
const OTHER_GRAPH_ID = "00000000-0000-4000-8000-0000000000g2";
const RUN_ID = "00000000-0000-4000-8000-0000000000r1";

function port(name: string, direction: Port["direction"] = "input"): Port {
  const shape = "one";
  return {
    name,
    title: name,
    description: null,
    direction,
    artifact_type: { id: "test.artifact", schema_version: 1 },
    shape,
    accepted_shapes: [shape],
    instance_plugs: false,
    variadic: false,
    required: true,
  };
}

interface SpecOptions {
  inputs?: readonly Port[];
  outputs?: readonly Port[];
  configSchema?: Record<string, unknown>;
  secretInputs?: NonNullable<NodeSpec["secret_inputs"]>;
  title?: string;
}

function nodeSpec(
  operatorId = "test.operator",
  options: SpecOptions = {},
): NodeSpec {
  return {
    operator_id: operatorId,
    operator_version: 1,
    plugin_slug: "test",
    origin: "builtin",
    title: options.title ?? operatorId,
    description: operatorId,
    catalog_visible: true,
    runnable: true,
    config_schema: options.configSchema ?? {},
    input_schema: {},
    output_schema: {},
    inputs: options.inputs ?? [],
    outputs: options.outputs ?? [port("result", "output")],
    secret_inputs: options.secretInputs,
  };
}

function workflowNode(
  id: string,
  options: {
    spec?: NodeSpec;
    selected?: boolean;
    config?: Record<string, unknown>;
    compatibility?: WorkflowNodeCompatibility;
  } = {},
): WorkflowNode {
  const spec = options.spec ?? nodeSpec();
  const data = createWorkflowNodeData(spec);
  if (options.compatibility) {
    data.compatibility = options.compatibility;
  }
  return {
    id,
    type: WORKFLOW_NODE_TYPE,
    position: { x: 0, y: 0 },
    selected: options.selected ?? false,
    data: { ...data, config: options.config ?? {} },
  };
}

function outputHandle(): string {
  return encodeHandleId({
    portName: "result",
    artifactTypeId: "test.artifact",
    schemaVersion: 1,
    shape: "one",
    direction: "output",
  });
}

function inputHandle(): string {
  return encodeHandleId({
    portName: "input",
    artifactTypeId: "test.artifact",
    schemaVersion: 1,
    shape: "one",
    direction: "input",
  });
}

function workflowEdge(source: string, target: string): WorkflowEdge {
  return {
    id: `${source}-${target}`,
    source,
    sourceHandle: outputHandle(),
    target,
    targetHandle: inputHandle(),
    data: { enabled: true, collectionMode: "direct", conversionPath: [] },
  };
}

function savedNode(
  id: string,
  options: { config?: Record<string, unknown>; operatorId?: string } = {},
): SavedGraphNode {
  return {
    id,
    kind: "builtin",
    // The saved node has to be the same node the canvas holds: the secret
    // binding check compares operator and version, and a fixture that differs
    // would refuse the Run for being changed rather than for anything under test.
    operator_id: options.operatorId ?? "test.operator",
    operator_version: 1,
    config: options.config ?? {},
    input_plugs: [],
    artifact_type_bindings: [],
    position: { x: 0, y: 0 },
  };
}

function activeSavedGraph(
  overrides: Partial<ActiveSavedGraph> = {},
): ActiveSavedGraph {
  return {
    id: PROJECT_ID,
    graphId: GRAPH_ID,
    revision: 3,
    nodes: [savedNode("a"), savedNode("b")],
    ...overrides,
  };
}

function run(status: RunStatus, overrides: Partial<Run> = {}): Run {
  return {
    id: RUN_ID,
    status,
    graph_id: GRAPH_ID,
    targets: [{ node_id: "a", call_path: [] }],
    started_by_user_id: null,
    error: null,
    project_id: PROJECT_ID,
    workspace_id: WORKSPACE_ID,
    created_at: "2026-07-20T08:00:00Z",
    finished_at: null,
    ...overrides,
  };
}

function artifact(nodeId: string): ArtifactRef {
  return {
    artifact_id: `artifact-${nodeId}`,
    artifact_type: "text.plain",
    schema_version: 1,
    content_hash: "hash-1",
  };
}

function instanceState(
  nodeId: string,
  state: InstanceStateName,
  overrides: {
    graphId?: string;
    callPath?: readonly string[];
    fingerprint?: string | null;
    error?: string | null;
  } = {},
): InstanceState {
  return {
    key: {
      project_id: PROJECT_ID,
      graph_id: overrides.graphId ?? GRAPH_ID,
      node_id: nodeId,
      call_path: overrides.callPath ?? [],
      map_index: null,
    },
    state,
    fingerprint: `document-${nodeId}`,
    last_result_fingerprint:
      overrides.fingerprint === undefined
        ? `result-${nodeId}`
        : overrides.fingerprint,
    error: overrides.error ?? null,
  };
}

function storedResult(
  nodeId: string,
  fingerprint = `result-${nodeId}`,
): InstanceResult {
  return {
    instance: instanceState(nodeId, "fresh", { fingerprint }),
    outputs: { result: artifact(nodeId) },
    result_fingerprint: fingerprint,
    created_at: "2026-07-20T08:05:00Z",
  };
}

function activeRunSummary(
  runId: string,
  overrides: Partial<ActiveRunSummary> = {},
) {
  return {
    run_id: runId,
    graph_id: GRAPH_ID,
    targets: [{ node_id: "a", call_path: [] }],
    starter: null,
    started_at: "2026-07-20T08:00:00Z",
    cancellable: true,
    ...overrides,
  };
}

/** The canvas the hook paints onto, so a test can read the overlays it set. */
function canvasState(nodes: readonly WorkflowNode[]) {
  const holder = { current: [...nodes] };
  const setNodes = vi.fn((next: React.SetStateAction<WorkflowNode[]>) => {
    holder.current =
      typeof next === "function"
        ? (next as (current: WorkflowNode[]) => WorkflowNode[])(holder.current)
        : next;
  });
  return {
    holder,
    setNodes,
    node: (id: string) => holder.current.find((n) => n.id === id),
  };
}

type HookOptions = Parameters<typeof useRunExecution>[0];

// The Workbench holds one `activeGraph` object per saved state, so a rerender of
// the same canvas reuses it. A fresh object each call would read as a new Graph
// and make every test re-fetch.
const defaultActiveGraph = activeSavedGraph();
const defaultEdges: WorkflowEdge[] = [];
// A fresh callback on every rerender would change the identity of the reads that
// depend on it, so a rerender that changed nothing would look like a new Graph.
const defaultSetRunError = vi.fn();

function hookOptions(
  canvas: ReturnType<typeof canvasState>,
  overrides: Partial<HookOptions> = {},
): HookOptions {
  return {
    workspaceId: WORKSPACE_ID,
    projectId: PROJECT_ID,
    registryAvailable: true,
    nodes: canvas.holder.current,
    edges: defaultEdges,
    origins: [],
    activeGraph: defaultActiveGraph,
    currentExecutionFingerprint: "fingerprint-1",
    canRunSavedGraph: true,
    nodeSecretStatuses: {},
    roomConnected: false,
    roomActiveRuns: null,
    roomRunsRevision: 0,
    roomInstancesRevision: 0,
    setNodes: canvas.setNodes,
    setRunError: defaultSetRunError,
    ...overrides,
  };
}

async function flush(): Promise<void> {
  await React.act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function settle(): Promise<void> {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    await flush();
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listGraphInstances.mockResolvedValue({ instances: [] });
  api.listRuns.mockResolvedValue({ runs: [] });
  api.getInstanceResult.mockImplementation(
    (_workspaceId: string, _projectId: string, key: { node_id: string }) =>
      Promise.resolve(storedResult(key.node_id)),
  );
  api.startRun.mockImplementation(async (_workspaceId, _projectId, body) =>
    run("running", {
      graph_id: body.graph_id,
      targets: body.targets,
    }),
  );
  api.getRun.mockResolvedValue(
    run("succeeded", { finished_at: "2026-07-20T08:06:00Z" }),
  );
  api.cancelRun.mockResolvedValue(run("cancelled"));
});

describe("reading what a Graph's node instances hold", () => {
  it("shows a stored result the moment the canvas opens, with nobody having run anything", async () => {
    // A person who came back to a Graph they ran yesterday should see yesterday's
    // outputs on the cards, not an empty canvas waiting for a Run.
    api.listGraphInstances.mockResolvedValue({
      instances: [instanceState("a", "stale")],
    });

    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(useRunExecution, hookOptions(canvas));
    await settle();

    expect(api.listGraphInstances).toHaveBeenCalledWith(
      WORKSPACE_ID,
      PROJECT_ID,
      GRAPH_ID,
      undefined,
    );
    expect(hook.result.current.resultByNodeId.a?.result_fingerprint).toBe(
      "result-a",
    );
    expect(hook.result.current.instanceStates.a).toBe("stale");
    expect(
      canvas.node("a")?.data.run?.outputs[0]?.artifacts[0]?.artifact_id,
    ).toBe("artifact-a");
    await hook.unmount();
  });

  it("paints each instance state with the overlay the card chrome speaks", async () => {
    api.listGraphInstances.mockResolvedValue({
      instances: [
        instanceState("a", "fresh"),
        instanceState("b", "running"),
        instanceState("c", "failed", { error: "boom" }),
      ],
    });

    const canvas = canvasState([
      workflowNode("a"),
      workflowNode("b"),
      workflowNode("c"),
      workflowNode("d"),
    ]);
    const hook = await renderHook(useRunExecution, hookOptions(canvas));
    await settle();

    expect(canvas.node("a")?.data.execution.status).toBe("succeeded");
    expect(canvas.node("b")?.data.execution.status).toBe("running");
    expect(canvas.node("c")?.data.execution).toEqual({
      status: "failed",
      error: "boom",
    });
    // A node the instance list does not name is nobody's news: it keeps what the
    // canvas already showed rather than being reset by an absence.
    expect(canvas.node("d")?.data.execution.status).toBe("idle");
    expect(canvas.node("d")?.data.run).toBeNull();
    await hook.unmount();
  });

  it("reads an instance behind a call node without painting the outer card with it", async () => {
    // The callee's instance belongs to the Graph too, but not to a card on this
    // canvas; collapsing it onto the call node would show someone else's state.
    api.listGraphInstances.mockResolvedValue({
      instances: [instanceState("inner", "running", { callPath: ["call"] })],
    });

    const canvas = canvasState([workflowNode("call")]);
    const hook = await renderHook(useRunExecution, hookOptions(canvas));
    await settle();

    expect(hook.result.current.instanceStates).toEqual({});
    expect(canvas.node("call")?.data.execution.status).toBe("idle");
    await hook.unmount();
  });

  it("reads a stored result once and skips it while its fingerprint has not moved", async () => {
    api.listGraphInstances.mockResolvedValue({
      instances: [instanceState("a", "fresh")],
    });
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(useRunExecution, hookOptions(canvas));
    await settle();
    expect(api.getInstanceResult).toHaveBeenCalledTimes(1);

    await React.act(async () => {
      await hook.result.current.refresh();
    });

    // The list is cheap and always re-read; a result is fetched per instance, so
    // an unchanged fingerprint must not buy another round trip.
    expect(api.listGraphInstances).toHaveBeenCalledTimes(2);
    expect(api.getInstanceResult).toHaveBeenCalledTimes(1);
    expect(hook.result.current.resultByNodeId.a?.result_fingerprint).toBe(
      "result-a",
    );
    await hook.unmount();
  });

  it("reads a result again the moment its instance points at a new fingerprint", async () => {
    api.listGraphInstances.mockResolvedValue({
      instances: [instanceState("a", "fresh")],
    });
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(useRunExecution, hookOptions(canvas));
    await settle();

    api.listGraphInstances.mockResolvedValue({
      instances: [instanceState("a", "fresh", { fingerprint: "result-a-2" })],
    });
    api.getInstanceResult.mockResolvedValue(storedResult("a", "result-a-2"));
    await React.act(async () => {
      await hook.result.current.refresh();
    });

    expect(api.getInstanceResult).toHaveBeenCalledTimes(2);
    expect(hook.result.current.resultByNodeId.a?.result_fingerprint).toBe(
      "result-a-2",
    );
    await hook.unmount();
  });

  it("reads the new Graph's instances when the canvas moves to another Graph of the Project", async () => {
    // Both halves of the address matter: a Project holds several Graphs and their
    // instances are separate, so reusing the previous Graph's cards would show
    // results that belong to a document nobody is looking at.
    const canvas = canvasState([workflowNode("a")]);
    const first = hookOptions(canvas);
    const hook = await renderHook(useRunExecution, first);
    await settle();

    await hook.rerender(
      hookOptions(canvas, {
        activeGraph: activeSavedGraph({ graphId: OTHER_GRAPH_ID }),
      }),
    );
    await settle();

    expect(api.listGraphInstances).toHaveBeenLastCalledWith(
      WORKSPACE_ID,
      PROJECT_ID,
      OTHER_GRAPH_ID,
      undefined,
    );
    await hook.unmount();
  });

  it("says so when instance state cannot be read, rather than showing an idle canvas", async () => {
    api.listGraphInstances.mockRejectedValue(
      new Error("instances are rebuilding"),
    );
    const setRunError = vi.fn();
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, { setRunError }),
    );
    await settle();

    expect(setRunError).toHaveBeenCalledWith("instances are rebuilding");
    await hook.unmount();
  });
});

describe("asking for a Run", () => {
  it("names every node of the Graph when the whole Graph is asked for", async () => {
    const canvas = canvasState([
      workflowNode("a"),
      workflowNode("b", { spec: nodeSpec("test.other") }),
    ]);
    api.getRun.mockResolvedValue(run("running"));
    const hook = await renderHook(useRunExecution, hookOptions(canvas));
    await settle();

    await React.act(async () => {
      await hook.result.current.runWorkflow("all");
    });

    expect(api.startRun).toHaveBeenCalledWith(WORKSPACE_ID, PROJECT_ID, {
      graph_id: GRAPH_ID,
      targets: [
        { node_id: "a", call_path: [] },
        { node_id: "b", call_path: [] },
      ],
    });
    expect(hook.result.current.running).toBe(true);
    expect(hook.result.current.runningScope).toBe("all");
    await hook.unmount();
  });

  it("names only the selection, and leaves its upstream to the stored results", async () => {
    // The upstream node is deliberately unselected and holds a stored result. A
    // Run reads that result by fingerprint, so the browser ships no values at
    // all — the reason the old per-run document snapshot could be deleted.
    api.listGraphInstances.mockResolvedValue({
      instances: [instanceState("a", "fresh")],
    });
    const canvas = canvasState([
      workflowNode("a"),
      workflowNode("b", { spec: nodeSpec("test.other"), selected: true }),
    ]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, { edges: [workflowEdge("a", "b")] }),
    );
    await settle();

    await React.act(async () => {
      await hook.result.current.runWorkflow("selected");
    });

    expect(api.startRun.mock.calls[0]?.[2]).toMatchObject({
      graph_id: GRAPH_ID,
      targets: [{ node_id: "b", call_path: [] }],
    });
    await hook.unmount();
  });

  it("names the selection and its ancestors when dependencies were asked for", async () => {
    const canvas = canvasState([
      workflowNode("a"),
      workflowNode("b", { spec: nodeSpec("test.other"), selected: true }),
    ]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, { edges: [workflowEdge("a", "b")] }),
    );
    await settle();

    await React.act(async () => {
      await hook.result.current.runWorkflow("selected-with-dependencies");
    });

    expect(
      api.startRun.mock.calls[0]?.[2].targets.map(
        (target: { node_id: string }) => target.node_id,
      ),
    ).toEqual(["a", "b"]);
    await hook.unmount();
  });

  it("refuses an empty selection in words, and asks the server for nothing", async () => {
    const setRunError = vi.fn();
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, { setRunError }),
    );
    await settle();

    await React.act(async () => {
      await hook.result.current.runWorkflow("selected");
    });

    expect(setRunError).toHaveBeenCalledWith(
      "Select at least one node before running a selection.",
    );
    expect(api.startRun).not.toHaveBeenCalled();
    await hook.unmount();
  });

  it("puts a node's own refusal on that node instead of in the banner", async () => {
    const setRunError = vi.fn();
    const canvas = canvasState([
      workflowNode("a"),
      workflowNode("b", {
        spec: nodeSpec("test.other"),
        selected: true,
        compatibility: {
          status: "unsupported",
          issues: ["its operator is not in the live registry"],
          inputs: [],
          outputs: [],
          persistedNode: savedNode("b", { operatorId: "test.other" }),
        },
      }),
    ]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, { setRunError }),
    );
    await settle();

    await React.act(async () => {
      await hook.result.current.runWorkflow("selected");
    });

    // The banner is cleared on purpose: the refusal belongs to the card, and a
    // second copy above the canvas would read as a problem with the whole Run.
    expect(setRunError).toHaveBeenCalledWith(null);
    expect(canvas.node("b")?.data.execution).toMatchObject({
      status: "failed",
      error: expect.stringContaining("Cannot run test.other"),
    });
    expect(api.startRun).not.toHaveBeenCalled();
    await hook.unmount();
  });

  it("tells a person to save before running, rather than starting a Run against nothing", async () => {
    const setRunError = vi.fn();
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, { projectId: null, activeGraph: null, setRunError }),
    );
    await settle();

    await React.act(async () => {
      await hook.result.current.runWorkflow("all");
    });

    expect(setRunError).toHaveBeenCalledWith(
      "Save the graph before running it.",
    );
    expect(api.startRun).not.toHaveBeenCalled();
    await hook.unmount();
  });

  it("does not start a second Run while this tab's demand is still open", async () => {
    // The Run is still going: the demand is open, and a second click cannot
    // double the work the first one is already waiting for.
    api.getRun.mockResolvedValue(run("running"));
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(useRunExecution, hookOptions(canvas));
    await settle();

    await React.act(async () => {
      await hook.result.current.runWorkflow("all");
    });
    await settle();
    await React.act(async () => {
      await hook.result.current.runWorkflow("all");
    });

    expect(api.startRun).toHaveBeenCalledTimes(1);
    expect(hook.result.current.running).toBe(true);
    await hook.unmount();
  });

  it("refuses to run a node whose stored secret lives on an unsaved canvas", async () => {
    const setRunError = vi.fn();
    const spec = nodeSpec("llm.operator", {
      secretInputs: [
        { name: "api_key", config_dependencies: ["model"], title: "API key" },
      ],
    });
    const canvas = canvasState([workflowNode("a", { spec })]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, {
        setRunError,
        canRunSavedGraph: false,
        activeGraph: activeSavedGraph({ nodes: [savedNode("a")] }),
      }),
    );
    await settle();

    await React.act(async () => {
      await hook.result.current.runWorkflow("all");
    });

    expect(setRunError).toHaveBeenCalledWith(
      "Save the graph before running nodes that use stored secrets.",
    );
    expect(api.startRun).not.toHaveBeenCalled();
    await hook.unmount();
  });

  it("refuses to run a node whose secret binding is newer than the saved one", async () => {
    // The server resolves a secret against the node as saved. Pointing the node
    // at a different account and running anyway would quietly charge the old one.
    const setRunError = vi.fn();
    const spec = nodeSpec("llm.operator", {
      secretInputs: [
        { name: "api_key", config_dependencies: ["model"], title: "API key" },
      ],
    });
    const canvas = canvasState([
      workflowNode("a", { spec, config: { model: "gpt-big" } }),
    ]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, {
        setRunError,
        activeGraph: activeSavedGraph({
          nodes: [
            savedNode("a", {
              config: { model: "gpt-small" },
              operatorId: "llm.operator",
            }),
          ],
        }),
        nodeSecretStatuses: {
          a: { api_key: { state: "configured", name: "api_key" } },
        } as never,
      }),
    );
    await settle();

    await React.act(async () => {
      await hook.result.current.runWorkflow("all");
    });

    expect(setRunError).toHaveBeenCalledWith(
      "Save the graph before running llm.operator: its API key binding is new or changed.",
    );
    await hook.unmount();
  });

  it("refuses to run a node whose required secret is not configured", async () => {
    const setRunError = vi.fn();
    const spec = nodeSpec("llm.operator", {
      secretInputs: [
        { name: "api_key", config_dependencies: ["model"], title: "API key" },
      ],
    });
    const canvas = canvasState([
      workflowNode("a", { spec, config: { model: "gpt" } }),
    ]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, {
        setRunError,
        activeGraph: activeSavedGraph({
          nodes: [
            savedNode("a", {
              config: { model: "gpt" },
              operatorId: "llm.operator",
            }),
          ],
        }),
        nodeSecretStatuses: {} as never,
      }),
    );
    await settle();

    await React.act(async () => {
      await hook.result.current.runWorkflow("all");
    });

    expect(setRunError).toHaveBeenCalledWith(
      "Configure every required secret for llm.operator before running.",
    );
    await hook.unmount();
  });

  it("turns a rejected Run into the sentence the code means, not the status code", async () => {
    const setRunError = vi.fn();
    const canvas = canvasState([workflowNode("a")]);
    api.startRun.mockRejectedValue(
      new ApiError(400, "node c is not on the canvas", "unknown_target"),
    );
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, { setRunError }),
    );
    await settle();

    await React.act(async () => {
      await hook.result.current.runWorkflow("all");
    });

    expect(setRunError).toHaveBeenCalledWith(
      "A node this Run was asked for is no longer on the canvas. Select the nodes again.",
    );
    // The tab holds no demand: the refusal was the answer.
    expect(hook.result.current.running).toBe(false);
    await hook.unmount();
  });
});

describe("the words for a Run that was refused", () => {
  function rejection(detail: string, code?: string): ApiError {
    return new ApiError(400, detail, code);
  }

  it("names the code's own problem, because the code is the stable half", () => {
    expect(
      runRejectionMessage(rejection("the graph is gone", "unknown_graph")),
    ).toBe("This Graph is no longer in the Project. Reload it before running.");
    expect(
      runRejectionMessage(
        rejection("node c is not on the canvas", "unknown_target"),
      ),
    ).toBe(
      "A node this Run was asked for is no longer on the canvas. Select the nodes again.",
    );
    expect(
      runRejectionMessage(
        rejection("llm.x is not published", "unknown_operator"),
      ),
    ).toBe("llm.x is not published");
    expect(
      runRejectionMessage(rejection("no config", "invalid_document")),
    ).toBe("no config");
  });

  it("falls back to what the server said for a code nobody named", () => {
    expect(runRejectionMessage(rejection("too many demands"))).toBe(
      "too many demands",
    );
    expect(
      runRejectionMessage(rejection("too many demands", "rate_limited")),
    ).toBe("too many demands");
  });
});

describe("settling this tab's own Run", () => {
  async function start(hook: {
    result: { current: ReturnType<typeof useRunExecution> };
  }) {
    await React.act(async () => {
      await hook.result.current.runWorkflow("all");
    });
  }

  it("reads its own Run by id, because a list cannot say which demand was mine", async () => {
    api.getRun.mockResolvedValue(run("running"));
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(useRunExecution, hookOptions(canvas));
    await settle();
    await start(hook);

    expect(api.getRun).toHaveBeenCalledWith(WORKSPACE_ID, PROJECT_ID, RUN_ID);
    expect(hook.result.current.running).toBe(true);
    expect(hook.result.current.ownRunStatus).toBe("running");
    expect(hook.result.current.announcement).toBe("");
    await hook.unmount();
  });

  it("announces a fresh result and republishes the instances it touched", async () => {
    api.getRun.mockResolvedValue(
      run("succeeded", { finished_at: "2026-07-20T08:06:00Z" }),
    );
    api.listGraphInstances.mockResolvedValueOnce({ instances: [] });
    api.listGraphInstances.mockResolvedValue({
      instances: [instanceState("a", "fresh")],
    });
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(useRunExecution, hookOptions(canvas));
    await settle();
    expect(canvas.node("a")?.data.execution.status).toBe("idle");

    await start(hook);
    await settle();

    expect(hook.result.current.running).toBe(false);
    expect(hook.result.current.ownRun).toBeNull();
    expect(hook.result.current.announcement).toBe(
      "Run made its targets fresh.",
    );
    expect(canvas.node("a")?.data.execution.status).toBe("succeeded");
    expect(hook.result.current.resultByNodeId.a?.result_fingerprint).toBe(
      "result-a",
    );
    await hook.unmount();
  });

  it("reports a failed Run with the server's reason", async () => {
    api.getRun.mockResolvedValue(
      run("failed", { error: "the operator raised ZeroDivisionError" }),
    );
    const setRunError = vi.fn();
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, { setRunError }),
    );
    await settle();

    await start(hook);
    await settle();

    expect(setRunError).toHaveBeenCalledWith(
      "the operator raised ZeroDivisionError",
    );
    expect(hook.result.current.announcement).toBe("Run failed.");
    expect(hook.result.current.running).toBe(false);
    await hook.unmount();
  });

  it("says an interrupted Run can be resumed, because the results it made stayed", async () => {
    // ADR 0020: a Run is a demand for freshness, so the work it finished is
    // stored and a rerun starts from what is already fresh. The sentence has to
    // say that, or a person thinks they lost the hour.
    api.getRun.mockResolvedValue(run("interrupted"));
    const setRunError = vi.fn();
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, { setRunError }),
    );
    await settle();

    await start(hook);
    await settle();

    expect(setRunError).toHaveBeenCalledWith(
      "The Run was interrupted before it finished. Running it again resumes from what is already fresh.",
    );
    await hook.unmount();
  });

  it("says a Run ended into a moved canvas, rather than calling it fresh", async () => {
    // The document changed while the Run was going, so the fresh badge would be
    // about a document nobody is looking at.
    api.getRun.mockResolvedValue(run("running"));
    const setRunError = vi.fn();
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, { setRunError }),
    );
    await settle();
    await start(hook);

    api.getRun.mockResolvedValue(run("succeeded"));
    await hook.rerender(
      hookOptions(canvas, {
        setRunError,
        currentExecutionFingerprint: "fingerprint-2",
      }),
    );
    await React.act(async () => {
      await hook.result.current.refresh();
    });
    await settle();

    expect(setRunError).toHaveBeenCalledWith(
      "The graph changed while the Run was going. Its results are stored, and the nodes it touched read as stale.",
    );
    expect(hook.result.current.announcement).toBe(
      "Run succeeded, and the graph had already moved.",
    );
    await hook.unmount();
  });

  it("keeps the demand open when the read fails, and settles on the next push", async () => {
    api.getRun.mockRejectedValueOnce(new Error("gateway hiccup"));
    const setRunError = vi.fn();
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, { setRunError }),
    );
    await settle();

    await start(hook);
    await settle();

    // A transient read failure is not the Run vanishing, and must not be reported
    // as one: the surface still believes its own demand is open.
    expect(hook.result.current.running).toBe(true);
    expect(setRunError).not.toHaveBeenCalledWith(expect.any(String));

    await hook.rerender(
      hookOptions(canvas, { setRunError, roomRunsRevision: 1 }),
    );
    await settle();

    expect(hook.result.current.running).toBe(false);
    expect(hook.result.current.announcement).toBe(
      "Run made its targets fresh.",
    );
    await hook.unmount();
  });
});

describe("withdrawing this tab's demand", () => {
  async function startedRun() {
    const canvas = canvasState([workflowNode("a")]);
    api.getRun.mockResolvedValue(run("running"));
    const hook = await renderHook(useRunExecution, hookOptions(canvas));
    await settle();
    await React.act(async () => {
      await hook.result.current.runWorkflow("all");
    });
    return { canvas, hook };
  }

  it("cancels only the Run this browser started, by its id", async () => {
    const { hook } = await startedRun();

    await React.act(async () => {
      await hook.result.current.cancelCurrentRun();
    });

    expect(api.cancelRun).toHaveBeenCalledWith(
      WORKSPACE_ID,
      PROJECT_ID,
      RUN_ID,
    );
    expect(hook.result.current.announcement).toBe("Cancelling this Run.");
    expect(hook.result.current.running).toBe(true);
    await hook.unmount();
  });

  it("cancels nothing when this tab started no Run, even though another tab has one open", async () => {
    // The list is full of other people's demands and the room names one as active.
    // There is no "the" active Run to cancel, and reaching for one would stop a
    // stranger's work.
    const setRunError = vi.fn();
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, {
        setRunError,
        roomConnected: true,
        roomActiveRuns: [
          activeRunSummary("00000000-0000-4000-8000-0000000000r9"),
        ],
      }),
    );
    await settle();

    await React.act(async () => {
      await hook.result.current.cancelCurrentRun();
    });

    expect(api.cancelRun).not.toHaveBeenCalled();
    expect(setRunError).not.toHaveBeenCalled();
    await hook.unmount();
  });

  it("reports a refusal to cancel and leaves the Run where it is", async () => {
    const setRunError = vi.fn();
    api.cancelRun.mockRejectedValue(
      new Error("only the starter may withdraw this"),
    );
    const canvas = canvasState([workflowNode("a")]);
    api.getRun.mockResolvedValue(run("running"));
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, { setRunError }),
    );
    await settle();
    await React.act(async () => {
      await hook.result.current.runWorkflow("all");
    });

    await React.act(async () => {
      await hook.result.current.cancelCurrentRun();
    });

    expect(setRunError).toHaveBeenCalledWith(
      "only the starter may withdraw this",
    );
    expect(hook.result.current.running).toBe(true);
    await hook.unmount();
  });
});

describe("several Runs in one Project", () => {
  it("shows the room's Runs, the listed Runs, and this tab's own, each once", async () => {
    const ownRunId = RUN_ID;
    api.listRuns.mockResolvedValue({
      runs: [
        run("running", { id: "00000000-0000-4000-8000-0000000000r2" }),
        run("running", { id: ownRunId }),
      ],
    });
    api.getRun.mockResolvedValue(run("running", { id: ownRunId }));
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, {
        roomConnected: true,
        roomActiveRuns: [
          activeRunSummary("00000000-0000-4000-8000-0000000000r2"),
          activeRunSummary("00000000-0000-4000-8000-0000000000r3"),
        ],
      }),
    );
    await settle();
    await React.act(async () => {
      await hook.result.current.runWorkflow("all");
    });
    await settle();

    const ids = hook.result.current.activeRuns.map((summary) => summary.run_id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toEqual(
      expect.arrayContaining([
        "00000000-0000-4000-8000-0000000000r2",
        "00000000-0000-4000-8000-0000000000r3",
        ownRunId,
      ]),
    );
    await hook.unmount();
  });
});

describe("keeping the surface current", () => {
  it("re-reads instance state when the room says instances changed", async () => {
    const canvas = canvasState([workflowNode("a")]);
    const first = hookOptions(canvas);
    const hook = await renderHook(useRunExecution, first);
    await settle();
    expect(api.listGraphInstances).toHaveBeenCalledTimes(1);

    await hook.rerender(
      hookOptions(canvas, { roomConnected: true, roomInstancesRevision: 1 }),
    );
    await settle();

    expect(api.listGraphInstances).toHaveBeenCalledTimes(2);
    await hook.unmount();
  });

  it("polls while there is no room to tell it anything, and only while work is open", async () => {
    const intervals = vi.spyOn(window, "setInterval");
    api.getRun.mockResolvedValue(run("running"));
    api.listRuns.mockResolvedValue({
      runs: [run("running", { id: "00000000-0000-4000-8000-0000000000r2" })],
    });
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(useRunExecution, hookOptions(canvas));
    await settle();

    expect(intervals).toHaveBeenCalledWith(
      expect.any(Function),
      RUN_SURFACE_POLL_INTERVAL_MS,
    );

    // With nothing in flight there is nothing to learn, so the surface stops
    // asking and the Project's read rate stops tracking how many tabs are open.
    intervals.mockClear();
    api.listRuns.mockResolvedValue({ runs: [] });
    api.getRun.mockResolvedValue(run("succeeded"));
    await React.act(async () => {
      await hook.result.current.refresh();
    });
    await settle();
    expect(intervals).not.toHaveBeenCalled();
    intervals.mockRestore();
    await hook.unmount();
  });

  it("does not poll while the room is carrying it", async () => {
    const intervals = vi.spyOn(window, "setInterval");
    api.listRuns.mockResolvedValue({
      runs: [run("running", { id: "00000000-0000-4000-8000-0000000000r2" })],
    });
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, { roomConnected: true }),
    );
    await settle();

    expect(intervals).not.toHaveBeenCalled();
    intervals.mockRestore();
    await hook.unmount();
  });
});

describe("leaving the canvas", () => {
  it("gives up the demand on unmount without cancelling the Run", async () => {
    // Closing a tab is not withdrawing a demand: the Run stays where it is so
    // another tab, or the same person later, can still read and cancel it.
    api.getRun.mockResolvedValue(run("running"));
    const setRunError = vi.fn();
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(
      useRunExecution,
      hookOptions(canvas, { setRunError }),
    );
    await settle();
    await React.act(async () => {
      await hook.result.current.runWorkflow("all");
    });

    await hook.unmount();
    const paintedAfterOpen = canvas.setNodes.mock.calls.length;

    api.getRun.mockResolvedValue(run("succeeded"));
    await flush();

    expect(api.cancelRun).not.toHaveBeenCalled();
    expect(canvas.setNodes.mock.calls.length).toBe(paintedAfterOpen);
    expect(setRunError).not.toHaveBeenCalledWith(expect.any(String));
  });

  it("ignores a late answer about a Graph the canvas has already left", async () => {
    const slow = deferred<{ instances: InstanceState[] }>();
    api.listGraphInstances
      .mockReturnValueOnce(slow.promise)
      .mockResolvedValue({ instances: [] });
    const canvas = canvasState([workflowNode("a")]);
    const hook = await renderHook(useRunExecution, hookOptions(canvas));
    await flush();

    await hook.rerender(
      hookOptions(canvas, {
        activeGraph: activeSavedGraph({ graphId: OTHER_GRAPH_ID }),
      }),
    );
    await settle();
    const painted = canvas.setNodes.mock.calls.length;

    await React.act(async () => {
      slow.resolve({ instances: [instanceState("a", "fresh")] });
      await flush();
    });

    // The first Graph's answer arrived after the canvas moved on; painting it
    // would put a fresh badge on a node whose instance nobody asked about.
    expect(canvas.setNodes.mock.calls.length).toBe(painted);
    await hook.unmount();
  });
});

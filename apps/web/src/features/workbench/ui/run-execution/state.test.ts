import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ArtifactRef,
  ArtifactRefSequence,
  InstanceResult,
  InstanceState,
  InstanceStateName,
  NodeSpec,
} from "@/lib/api";
import type { WorkflowNode } from "../../model/execution-plan";
import { WORKFLOW_NODE_TYPE, createWorkflowNodeData } from "../../canvas/types";
import {
  IDLE_OVERLAY,
  instanceStateByNodeId,
  instanceStateIsTerminal,
  isRootInstance,
  loadInstanceSnapshot,
  overlayStatusForInstance,
  runNodeResultFromInstance,
  runPortOutputs,
  withInstanceResults,
  withInstanceStates,
} from "./state";

const listGraphInstances = vi.fn();
const getInstanceResult = vi.fn();

vi.mock("@/lib/api", () => ({
  listGraphInstances: (...args: unknown[]) => listGraphInstances(...args),
  getInstanceResult: (...args: unknown[]) => getInstanceResult(...args),
}));

function nodeSpec(): NodeSpec {
  return {
    operator_id: "test.operator",
    operator_version: 1,
    plugin_slug: "test",
    origin: "builtin",
    title: "Test operator",
    description: "Test operator",
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [],
  };
}

function workflowNode(id: string): WorkflowNode {
  return {
    id,
    type: WORKFLOW_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: { ...createWorkflowNodeData(nodeSpec()), run: null },
  };
}

function instance(
  nodeId: string,
  state: InstanceStateName = "fresh",
  overrides: {
    callPath?: readonly string[];
    mapIndex?: number | null;
    fingerprint?: string | null;
    error?: string | null;
  } = {},
): InstanceState {
  return {
    key: {
      project_id: "project-1",
      graph_id: "graph-1",
      node_id: nodeId,
      call_path: overrides.callPath ?? [],
      map_index: overrides.mapIndex ?? null,
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

function artifactValue(nodeId: string): ArtifactRef {
  return {
    artifact_id: `artifact-${nodeId}`,
    artifact_type: "text.plain",
    schema_version: 1,
    content_hash: "hash-1",
  };
}

function sequenceValue(nodeId: string): ArtifactRefSequence {
  return {
    artifact_type: "text.plain",
    schema_version: 1,
    index_key: "order_index",
    ordered: true,
    item_refs: [
      { ...artifactValue(nodeId), content_hash: "hash-a" },
      { ...artifactValue(nodeId), artifact_id: `second-${nodeId}` },
    ],
  };
}

function instanceResult(
  nodeId: string,
  overrides: {
    state?: InstanceStateName;
    outputs?: InstanceResult["outputs"];
    fingerprint?: string | null;
    createdAt?: string | null;
    error?: string | null;
  } = {},
): InstanceResult {
  return {
    instance: instance(nodeId, overrides.state ?? "fresh", {
      error: overrides.error,
    }),
    outputs: overrides.outputs ?? { output: artifactValue(nodeId) },
    result_fingerprint:
      overrides.fingerprint === undefined
        ? `result-${nodeId}`
        : overrides.fingerprint,
    created_at:
      overrides.createdAt === undefined
        ? "2026-07-20T08:00:00Z"
        : overrides.createdAt,
  };
}

function nodeById(nodes: readonly WorkflowNode[], id: string): WorkflowNode {
  const node = nodes.find((candidate) => candidate.id === id);
  if (!node) throw new Error(`Missing node ${id} in result`);
  return node;
}

describe("instance state overlays", () => {
  it("paints each instance state with the overlay the card chrome speaks", () => {
    expect(overlayStatusForInstance("fresh")).toBe("succeeded");
    expect(overlayStatusForInstance("queued")).toBe("queued");
    expect(overlayStatusForInstance("running")).toBe("running");
    expect(overlayStatusForInstance("failed")).toBe("failed");
  });

  it("paints a stale instance as idle, because its result is not this Run's", () => {
    // Stale is not "nothing happened": the card keeps showing the stored
    // result. The overlay only says no current Run produced it.
    expect(overlayStatusForInstance("stale")).toBe("idle");
  });

  it("treats the three settled states as terminal, and the two in flight as not", () => {
    expect(instanceStateIsTerminal("fresh")).toBe(true);
    expect(instanceStateIsTerminal("stale")).toBe(true);
    expect(instanceStateIsTerminal("failed")).toBe(true);
    expect(instanceStateIsTerminal("queued")).toBe(false);
    expect(instanceStateIsTerminal("running")).toBe(false);
  });

  it("names an instance of the Graph being looked at, and not one behind a call node", () => {
    expect(isRootInstance(instance("a"))).toBe(true);
    expect(isRootInstance(instance("a", "fresh", { callPath: ["call"] }))).toBe(
      false,
    );
    // One item of a mapped collection belongs to the collection, not to a card.
    expect(isRootInstance(instance("a", "fresh", { mapIndex: 2 }))).toBe(false);
  });

  it("keys state by node id and leaves addressed instances out", () => {
    const byNodeId = instanceStateByNodeId([
      instance("a", "fresh"),
      instance("a", "running", { callPath: ["call"] }),
      instance("b", "stale"),
    ]);

    expect([...byNodeId.keys()]).toEqual(["a", "b"]);
    expect(byNodeId.get("a")?.state).toBe("fresh");
  });
});

describe("stored results", () => {
  it("reads a single artifact output as one port holding one reference", () => {
    const ports = runPortOutputs({ output: artifactValue("a") });

    expect(ports).toEqual([
      {
        port: "output",
        kind: "single",
        value: artifactValue("a"),
        artifacts: [
          {
            artifact_id: "artifact-a",
            artifact_type: "text.plain",
            schema_version: 1,
            content_hash: "hash-1",
          },
        ],
      },
    ]);
  });

  it("reads a sequence output as one port holding every item reference", () => {
    const ports = runPortOutputs({ output: sequenceValue("a") });

    expect(ports[0]?.kind).toBe("sequence");
    expect(ports[0]?.artifacts.map((artifact) => artifact.artifact_id)).toEqual(
      ["artifact-a", "second-a"],
    );
    // The sequence itself is the value, so a card can count its items without
    // reading them one by one.
    expect(ports[0]?.value).toEqual(sequenceValue("a"));
  });

  it("reads a result with no outputs, and a port with nothing on it, as nothing", () => {
    expect(runPortOutputs(null)).toEqual([]);
    // A port the server stored with nothing on it is not a result port.
    expect(runPortOutputs({ output: null as unknown as ArtifactRef })).toEqual(
      [],
    );
    expect(runPortOutputs({ output: "not-a-reference" as never })).toEqual([]);
  });

  it("refuses to invent a result for an instance that stored none", () => {
    expect(
      runNodeResultFromInstance(instanceResult("a", { fingerprint: null })),
    ).toBe(null);
  });

  it("publishes a stored result with the fingerprint it was stored under", () => {
    const result = runNodeResultFromInstance(instanceResult("a"));

    expect(result).toEqual({
      node_id: "a",
      status: "succeeded",
      error: null,
      outputs: runPortOutputs({ output: artifactValue("a") }),
      result_fingerprint: "result-a",
      created_at: "2026-07-20T08:00:00Z",
    });
  });

  it("publishes a failed instance as a failed result, with a sentence when the server gave none", () => {
    const detailed = runNodeResultFromInstance(
      instanceResult("a", { state: "failed", error: "boom", outputs: {} }),
    );
    expect(detailed?.status).toBe("failed");
    expect(detailed?.error).toBe("boom");

    const bare = runNodeResultFromInstance(
      instanceResult("a", {
        state: "failed",
        error: null,
        outputs: {},
        fingerprint: null,
      }),
    );
    expect(bare?.error).toBe("This node failed without error details.");
  });
});

describe("publishing instances onto the canvas", () => {
  it("moves only the nodes a snapshot names, and leaves the rest as they were", () => {
    const nodes = [workflowNode("a"), workflowNode("b")];
    const untouched = nodes[1];

    const next = withInstanceStates(
      nodes,
      instanceStateByNodeId([instance("a", "running")]),
    );

    expect(nodeById(next, "a").data.execution.status).toBe("running");
    // A node the snapshot does not name keeps its identity, so React Flow does
    // not repaint a card whose state nobody reported.
    expect(nodeById(next, "b")).toBe(untouched);
  });

  it("carries a failure's sentence onto the card", () => {
    const next = withInstanceStates(
      [workflowNode("a")],
      instanceStateByNodeId([instance("a", "failed", { error: "boom" })]),
    );

    expect(nodeById(next, "a").data.execution).toEqual({
      status: "failed",
      error: "boom",
    });
  });

  it("publishes a stored result onto its node without touching the others", () => {
    const nodes = [workflowNode("a"), workflowNode("b")];
    const result = runNodeResultFromInstance(instanceResult("a"));
    if (!result) throw new Error("Expected a stored result");

    const next = withInstanceResults(nodes, new Map([["a", result]]));

    expect(nodeById(next, "a").data.run).toBe(result);
    expect(nodeById(next, "b").data.run).toBeNull();
  });

  it("keeps the node when the result it already shows is the one read again", () => {
    const result = runNodeResultFromInstance(instanceResult("a"));
    if (!result) throw new Error("Expected a stored result");
    const nodes = [
      {
        ...workflowNode("a"),
        data: { ...workflowNode("a").data, run: result },
      },
    ];

    expect(withInstanceResults(nodes, new Map([["a", result]]))[0]).toBe(
      nodes[0],
    );
  });

  it("shows nothing on a card before any instance state has been read for it", () => {
    expect(IDLE_OVERLAY.status).toBe("idle");
  });
});

describe("reading a Graph's instances", () => {
  beforeEach(() => {
    listGraphInstances.mockReset();
    getInstanceResult.mockReset();
  });

  it("reads the list once and the results the list points at", async () => {
    listGraphInstances.mockResolvedValue({
      instances: [instance("a", "fresh"), instance("b", "stale")],
    });
    getInstanceResult.mockImplementation(
      async (
        _workspaceId: string,
        _projectId: string,
        key: { node_id: string },
      ) => instanceResult(key.node_id),
    );

    const snapshot = await loadInstanceSnapshot(
      "workspace-1",
      "project-1",
      "graph-1",
    );

    expect(listGraphInstances).toHaveBeenCalledWith(
      "workspace-1",
      "project-1",
      "graph-1",
      undefined,
    );
    expect(snapshot.instances).toHaveLength(2);
    expect(snapshot.results.map((result) => result.node_id).sort()).toEqual([
      "a",
      "b",
    ]);
    expect(getInstanceResult).toHaveBeenCalledWith(
      "workspace-1",
      "project-1",
      { graph_id: "graph-1", node_id: expect.any(String), call_path: [] },
      undefined,
    );
  });

  it("does not read an instance that stored no result, or one addressed through a call node", async () => {
    listGraphInstances.mockResolvedValue({
      instances: [
        instance("a", "stale", { fingerprint: null }),
        instance("b", "fresh", { callPath: ["call"] }),
      ],
    });

    const snapshot = await loadInstanceSnapshot(
      "workspace-1",
      "project-1",
      "graph-1",
    );

    expect(getInstanceResult).not.toHaveBeenCalled();
    expect(snapshot.results).toEqual([]);
  });

  it("reads only the nodes a caller named, and only the results that moved", async () => {
    listGraphInstances.mockResolvedValue({
      instances: [instance("a", "fresh"), instance("b", "fresh")],
    });
    getInstanceResult.mockImplementation(
      async (
        _workspaceId: string,
        _projectId: string,
        key: { node_id: string },
      ) => instanceResult(key.node_id),
    );

    await loadInstanceSnapshot("workspace-1", "project-1", "graph-1", {
      onlyNodeIds: new Set(["a"]),
      loadedFingerprints: new Map([["b", "result-b"]]),
    });

    expect(getInstanceResult).toHaveBeenCalledTimes(1);
    expect(getInstanceResult.mock.calls[0]?.[2]?.node_id).toBe("a");
  });

  it("re-reads a result the moment its fingerprint moves", async () => {
    listGraphInstances.mockResolvedValue({
      instances: [instance("a", "stale", { fingerprint: "result-a-2" })],
    });
    getInstanceResult.mockImplementation(
      async (
        _workspaceId: string,
        _projectId: string,
        key: { node_id: string },
      ) => instanceResult(key.node_id, { fingerprint: "result-a-2" }),
    );

    const snapshot = await loadInstanceSnapshot(
      "workspace-1",
      "project-1",
      "graph-1",
      {
        loadedFingerprints: new Map([["a", "result-a"]]),
      },
    );

    expect(snapshot.results[0]?.result_fingerprint).toBe("result-a-2");
  });
});

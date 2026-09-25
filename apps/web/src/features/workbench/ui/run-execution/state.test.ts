import { describe, expect, it } from "vitest";

import type { NodeSpec, RunExecution, RunNodeResult } from "@/lib/api";
import type { WorkflowNode } from "../../model/execution-plan";
import {
  WORKFLOW_NODE_TYPE,
  type NodeExecution,
  createWorkflowNodeData,
} from "../../canvas/types";
import {
  nodeExecutionIsTerminal,
  withCurrentMaterializations,
  withSharedExecutionTerminalNodes,
} from "./state";

const executionId = "00000000-0000-4000-8000-000000000001";

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

function workflowNode(
  id: string,
  overrides: { execution?: NodeExecution; run?: RunNodeResult } = {},
): WorkflowNode {
  const data = createWorkflowNodeData(nodeSpec());
  return {
    id,
    type: WORKFLOW_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: {
      ...data,
      execution: overrides.execution ?? data.execution,
      run: overrides.run ?? null,
    },
  };
}

function succeededRun(nodeId: string): RunNodeResult {
  return {
    node_id: nodeId,
    status: "succeeded",
    error: null,
    outputs: [
      {
        port: "output",
        kind: "single",
        value: {
          artifact_id: `artifact-${nodeId}`,
          artifact_type: "text.plain",
          schema_version: 1,
        },
        artifacts: [],
      },
    ],
  };
}

function failedRun(nodeId: string, message: string): RunNodeResult {
  return { node_id: nodeId, status: "failed", error: message, outputs: [] };
}

function executionResponse(
  status: RunExecution["status"],
  overrides: Partial<RunExecution> = {},
): RunExecution {
  return {
    execution_id: executionId,
    status,
    active_node_id: null,
    result: null,
    error: null,
    ...overrides,
  };
}

function nodeById(nodes: readonly WorkflowNode[], id: string): WorkflowNode {
  const node = nodes.find((candidate) => candidate.id === id);
  if (!node) throw new Error(`Missing node ${id} in result`);
  return node;
}

describe("nodeExecutionIsTerminal", () => {
  it("treats finished node statuses as terminal", () => {
    expect(nodeExecutionIsTerminal("succeeded")).toBe(true);
    expect(nodeExecutionIsTerminal("failed")).toBe(true);
    expect(nodeExecutionIsTerminal("skipped")).toBe(true);
    expect(nodeExecutionIsTerminal("cancelled")).toBe(true);
  });

  it("treats idle and in-flight node statuses as not terminal", () => {
    expect(nodeExecutionIsTerminal("idle")).toBe(false);
    expect(nodeExecutionIsTerminal("queued")).toBe(false);
    expect(nodeExecutionIsTerminal("running")).toBe(false);
    expect(nodeExecutionIsTerminal("cancelling")).toBe(false);
  });
});

describe("withCurrentMaterializations", () => {
  it("attaches a materialized run to its node", () => {
    const materialization = succeededRun("node-1");
    const nodes = [
      workflowNode("node-1"),
      workflowNode("node-2", {
        execution: { status: "running" },
      }),
    ];

    const result = withCurrentMaterializations(nodes, [materialization]);

    expect(nodeById(result, "node-1").data.run).toEqual(materialization);
    expect(nodeById(result, "node-1").data.execution).toEqual({
      status: "succeeded",
    });
  });

  it("leaves a node without a materialized run unattached", () => {
    const nodes = [
      workflowNode("node-1"),
      workflowNode("node-2", { execution: { status: "running" } }),
    ];

    const result = withCurrentMaterializations(nodes, [succeededRun("node-1")]);

    const unattached = nodeById(result, "node-2");
    expect(unattached.data.run).toBeNull();
    expect(unattached.data.execution).toEqual({ status: "idle" });
  });

  it("restores the previous failure for a terminal node with no materialization", () => {
    const previousRun = failedRun("node-1", "upstream exploded");
    const nodes = [
      workflowNode("node-1", {
        execution: { status: "failed", error: "upstream exploded" },
        run: previousRun,
      }),
    ];

    const result = withCurrentMaterializations(nodes, []);

    expect(nodeById(result, "node-1").data.run).toEqual(previousRun);
    expect(nodeById(result, "node-1").data.execution).toEqual({
      status: "failed",
      error: "upstream exploded",
    });
  });

  it("keeps a stale succeeded run out of a terminal node", () => {
    const nodes = [
      workflowNode("node-1", {
        execution: { status: "cancelled" },
        run: succeededRun("node-1"),
      }),
    ];

    const result = withCurrentMaterializations(nodes, []);

    expect(nodeById(result, "node-1").data.run).toBeNull();
    expect(nodeById(result, "node-1").data.execution).toEqual({
      status: "cancelled",
    });
  });

  it("clears a previous success that is no longer materialized", () => {
    const nodes = [
      workflowNode("node-1", {
        execution: { status: "succeeded" },
        run: succeededRun("node-1"),
      }),
    ];

    const result = withCurrentMaterializations(nodes, []);

    expect(nodeById(result, "node-1").data.run).toBeNull();
    expect(nodeById(result, "node-1").data.execution).toEqual({
      status: "idle",
    });
  });
});

describe("withSharedExecutionTerminalNodes", () => {
  it("marks every in-flight node of a cancelled shared execution cancelled", () => {
    const unrelated = workflowNode("node-3", {
      execution: { status: "running" },
    });
    const nodes = [
      workflowNode("node-1", { execution: { status: "running" } }),
      workflowNode("node-2"),
      unrelated,
    ];

    const result = withSharedExecutionTerminalNodes(
      nodes,
      new Set(["node-1", "node-2"]),
      executionResponse("cancelled"),
    );

    expect(nodeById(result, "node-1").data.execution).toEqual({
      status: "cancelled",
    });
    expect(nodeById(result, "node-1").data.run).toBeNull();
    expect(nodeById(result, "node-2").data.execution).toEqual({
      status: "cancelled",
    });
    expect(nodeById(result, "node-3")).toBe(unrelated);
  });

  it("leaves an already terminal shared node alone when cancelling", () => {
    const finished = workflowNode("node-1", {
      execution: { status: "succeeded" },
      run: succeededRun("node-1"),
    });
    const nodes = [
      finished,
      workflowNode("node-2", { execution: { status: "queued" } }),
    ];

    const result = withSharedExecutionTerminalNodes(
      nodes,
      new Set(["node-1", "node-2"]),
      executionResponse("cancelled"),
    );

    expect(nodeById(result, "node-1")).toBe(finished);
    expect(nodeById(result, "node-2").data.execution).toEqual({
      status: "cancelled",
    });
  });

  it("applies returned node runs and skips members the server omitted", () => {
    const returned = succeededRun("node-1");
    const unrelated = workflowNode("node-3");
    const nodes = [
      workflowNode("node-1", { execution: { status: "running" } }),
      workflowNode("node-2", { execution: { status: "queued" } }),
      unrelated,
    ];

    const result = withSharedExecutionTerminalNodes(
      nodes,
      new Set(["node-1", "node-2"]),
      executionResponse("succeeded", {
        result: { status: "succeeded", node_runs: [returned] },
      }),
    );

    expect(nodeById(result, "node-1").data.run).toEqual(returned);
    expect(nodeById(result, "node-1").data.execution).toEqual({
      status: "succeeded",
      error: undefined,
    });
    expect(nodeById(result, "node-2").data.run).toBeNull();
    expect(nodeById(result, "node-2").data.execution).toEqual({
      status: "skipped",
      error: "The server did not return a result for this node.",
    });
    expect(nodeById(result, "node-3")).toBe(unrelated);
  });

  it("marks the active node failed when a shared result reports failure", () => {
    const failure = failedRun("node-1", "boom");
    const nodes = [
      workflowNode("node-1", { execution: { status: "running" } }),
      workflowNode("node-2", { execution: { status: "queued" } }),
    ];

    const result = withSharedExecutionTerminalNodes(
      nodes,
      new Set(["node-1", "node-2"]),
      executionResponse("failed", {
        result: { status: "failed", node_runs: [failure] },
      }),
    );

    expect(nodeById(result, "node-1").data.execution).toEqual({
      status: "failed",
      error: "boom",
    });
    expect(nodeById(result, "node-2").data.execution).toEqual({
      status: "skipped",
      error: "The server did not return a result for this node.",
    });
  });

  it("fills in an error for a failed node whose run carried none", () => {
    const nodes = [workflowNode("node-1")];

    const result = withSharedExecutionTerminalNodes(
      nodes,
      new Set(["node-1"]),
      executionResponse("failed", {
        result: {
          status: "failed",
          node_runs: [{ ...failedRun("node-1", ""), error: null }],
        },
      }),
    );

    expect(nodeById(result, "node-1").data.execution).toEqual({
      status: "failed",
      error: "This node failed without error details.",
    });
  });

  it("fails only the active node when a result-less execution failed", () => {
    const unrelated = workflowNode("node-3", {
      execution: { status: "running" },
    });
    const nodes = [
      workflowNode("node-1", { execution: { status: "running" } }),
      workflowNode("node-2", { execution: { status: "queued" } }),
      unrelated,
    ];

    const result = withSharedExecutionTerminalNodes(
      nodes,
      new Set(["node-1", "node-2"]),
      executionResponse("failed", {
        active_node_id: "node-1",
        error: "The worker died.",
      }),
    );

    expect(nodeById(result, "node-1").data.execution).toEqual({
      status: "failed",
      error: "The worker died.",
    });
    expect(nodeById(result, "node-1").data.run).toBeNull();
    expect(nodeById(result, "node-2").data.execution).toEqual({
      status: "idle",
    });
    expect(nodeById(result, "node-3")).toBe(unrelated);
  });

  it("fails every in-flight member when no active node is reported", () => {
    const nodes = [
      workflowNode("node-1", { execution: { status: "running" } }),
      workflowNode("node-2", { execution: { status: "queued" } }),
      workflowNode("node-3", { execution: { status: "failed" } }),
    ];

    const result = withSharedExecutionTerminalNodes(
      nodes,
      new Set(["node-1", "node-2", "node-3"]),
      executionResponse("failed"),
    );

    expect(nodeById(result, "node-1").data.execution).toEqual({
      status: "failed",
      error: "The execution ended without a workflow result.",
    });
    expect(nodeById(result, "node-2").data.execution).toEqual({
      status: "failed",
      error: "The execution ended without a workflow result.",
    });
    expect(nodeById(result, "node-3").data.execution).toEqual({
      status: "failed",
    });
  });
});

// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  ArtifactSummary,
  GraphExecutionDetail,
  GraphExecutionList,
  GraphExecutionNodeResult,
  GraphExecutionSummary,
  RunNodeResult,
  RunPortOutput,
} from "@/lib/api";
import type { WorkflowNodeProgressEntry } from "../types";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const apiMocks = vi.hoisted(() => ({
  getGraphExecution:
    vi.fn<
      (
        workspaceId: string,
        graphId: string,
        executionId: string,
      ) => Promise<GraphExecutionDetail>
    >(),
  listGraphExecutions:
    vi.fn<
      (
        workspaceId: string,
        graphId: string,
        options: { limit: number; nodeId: string },
      ) => Promise<GraphExecutionList>
    >(),
}));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("@/lib/api", () => ({
  getGraphExecution: apiMocks.getGraphExecution,
  listGraphExecutions: apiMocks.listGraphExecutions,
}));

import {
  NodeExecutionAppendix,
  type NodeExecutionAppendixProps,
} from "./NodeExecutionAppendix";

const mountedRoots = new Map<Root, HTMLElement>();

afterEach(async () => {
  for (const [root, container] of mountedRoots) {
    await React.act(async () => root.unmount());
    container.remove();
  }
  mountedRoots.clear();
  vi.clearAllMocks();
});

function progressEntry(
  sequence: number,
  message: string,
  overrides: Partial<WorkflowNodeProgressEntry> = {},
): WorkflowNodeProgressEntry {
  return {
    sequence,
    message,
    current: null,
    total: null,
    sourceNodePath: [],
    invocationIndex: null,
    invocationPath: [],
    ...overrides,
  };
}

function artifact(id: string): ArtifactSummary {
  return {
    artifact_id: id,
    artifact_type: "scalar.text",
    schema_version: 1,
    content_type: "text/plain",
  };
}

function output(port: string, artifactIds: readonly string[]): RunPortOutput {
  const artifacts = artifactIds.map(artifact);
  const refs = artifacts.map((item) => ({
    artifact_id: item.artifact_id,
    artifact_type: item.artifact_type,
    schema_version: item.schema_version,
  }));
  return {
    port,
    kind: artifactIds.length > 1 ? "sequence" : "single",
    value:
      artifactIds.length > 1
        ? {
            artifact_type: "scalar.text",
            schema_version: 1,
            index_key: "order_index",
            ordered: true,
            item_refs: refs,
          }
        : (refs[0] ?? {
            artifact_id: `${port}-missing`,
            artifact_type: "scalar.text",
            schema_version: 1,
          }),
    artifacts,
  };
}

function runWithArtifacts(
  nodeId: string,
  artifactIds: readonly string[],
): RunNodeResult {
  return {
    node_id: nodeId,
    status: "succeeded",
    error: null,
    outputs: artifactIds.length ? [output("result", artifactIds)] : [],
  };
}

function summary(
  executionId: string,
  overrides: Partial<GraphExecutionSummary> = {},
): GraphExecutionSummary {
  return {
    execution_id: executionId,
    graph_id: "graph-1",
    graph_revision: 7,
    status: "succeeded",
    scope: "selected",
    requested_node_ids: ["node-a"],
    created_at: "2026-07-20T08:00:00Z",
    started_at: "2026-07-20T08:00:01Z",
    finished_at: "2026-07-20T08:00:02Z",
    workflow_run_id: "workflow-1",
    error: null,
    node_count: 2,
    artifact_count: 10,
    ...overrides,
  };
}

function nodeResult(
  nodeId: string,
  outputs: readonly RunPortOutput[],
): GraphExecutionNodeResult {
  return {
    node_id: nodeId,
    position: 0,
    status: "succeeded",
    error: null,
    completed_at: "2026-07-20T08:00:02Z",
    outputs,
  };
}

function detail(
  execution: GraphExecutionSummary,
  nodeResults: readonly GraphExecutionNodeResult[],
): GraphExecutionDetail {
  return { ...execution, node_results: nodeResults };
}

async function renderAppendix(props: Partial<NodeExecutionAppendixProps> = {}) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.set(root, container);
  const swrConfig = {
    provider: () => new Map(),
    dedupingInterval: 0,
    revalidateOnFocus: false,
  };
  let currentProps: NodeExecutionAppendixProps = {
    nodeId: "node-a",
    nodeTitle: "Extract invoice",
    expanded: false,
    width: 320,
    execution: { status: "idle" },
    progress: null,
    run: null,
    historyContext: null,
    onOpenHistory: undefined,
    ...props,
  };
  const render = () => (
    <SWRConfig value={swrConfig}>
      <NodeExecutionAppendix {...currentProps} />
    </SWRConfig>
  );
  await React.act(async () => root.render(render()));
  const rerender = async (nextProps: Partial<NodeExecutionAppendixProps>) => {
    currentProps = { ...currentProps, ...nextProps };
    await React.act(async () => root.render(render()));
  };
  return { container, rerender };
}

function buttonWithText(
  container: HTMLElement,
  text: string,
): HTMLButtonElement {
  const button = [...container.querySelectorAll("button")].find(
    (candidate) => candidate.textContent?.trim() === text,
  );
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`Button ${text} was not rendered`);
  }
  return button;
}

describe("NodeExecutionAppendix", () => {
  it("stays off the canvas when a selected idle node has never run", async () => {
    const { container } = await renderAppendix({
      expanded: true,
      execution: { status: "idle" },
      progress: null,
      run: null,
    });
    expect(container.querySelector("aside")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("does not mount loading chrome while checking saved history for an idle node", async () => {
    let resolveHistory!: (value: GraphExecutionList) => void;
    apiMocks.listGraphExecutions.mockReturnValue(
      new Promise((resolve) => {
        resolveHistory = resolve;
      }),
    );
    const { container } = await renderAppendix({
      expanded: true,
      execution: { status: "idle" },
      progress: null,
      run: null,
      historyContext: {
        workspaceId: "workspace-1",
        graphId: "graph-1",
        isDirty: false,
      },
    });

    expect(apiMocks.listGraphExecutions).toHaveBeenCalledWith(
      "workspace-1",
      "graph-1",
      { limit: 5, nodeId: "node-a" },
    );
    expect(container.querySelector("aside")).toBeNull();
    expect(container.textContent).toBe("");

    await React.act(async () => {
      resolveHistory({ items: [], next_cursor: null });
    });

    expect(container.querySelector("aside")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("reveals durable saved history after the idle-node check completes", async () => {
    const previousExecution = summary("execution-1");
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [previousExecution],
      next_cursor: null,
    });
    apiMocks.getGraphExecution.mockResolvedValue(
      detail(previousExecution, [
        nodeResult("node-a", [output("result", ["historic-artifact"])]),
      ]),
    );

    const { container } = await renderAppendix({
      expanded: true,
      execution: { status: "idle" },
      progress: null,
      run: null,
      historyContext: {
        workspaceId: "workspace-1",
        graphId: "graph-1",
        isDirty: false,
      },
    });

    await vi.waitFor(() => {
      expect(container.textContent).toContain("History 1");
    });
    expect(container.querySelector("aside")).not.toBeNull();
  });

  it("renders one collapsed footprint for the latest event, error, or materialization", async () => {
    const { container, rerender } = await renderAppendix({
      execution: { status: "running" },
      progress: {
        omittedCount: 0,
        entries: [
          progressEntry(1, "Earlier event"),
          progressEntry(2, "Latest event"),
        ],
      },
    });

    expect(container.textContent).toContain("Latest event");
    expect(container.textContent).not.toContain("Earlier event");
    expect(container.querySelector('[role="tablist"]')).toBeNull();
    const summary = container.querySelector("aside");
    expect(summary?.classList).toContain("nodrag");
    expect(summary?.classList).toContain("nopan");
    expect(summary?.classList).toContain("nowheel");

    await rerender({
      execution: { status: "failed", error: "The node failed" },
    });
    expect(container.textContent).toBe("The node failed");
    expect(container.querySelector('[role="alert"]')).not.toBeNull();

    await rerender({
      execution: { status: "succeeded" },
      progress: null,
      run: runWithArtifacts("node-a", ["artifact-1", "artifact-2"]),
    });
    expect(container.textContent).toBe("Latest result · 2 artifacts");
  });

  it("renders nested events latest-first, discloses +N, and keeps message text inert", async () => {
    const unsafeMessage =
      '<script>window.__appendixXss = true</script> & "exact"';
    const { container } = await renderAppendix({
      expanded: true,
      execution: { status: "running" },
      progress: {
        omittedCount: 1,
        entries: [
          progressEntry(1, "Preparing"),
          progressEntry(2, "Fetching"),
          progressEntry(3, unsafeMessage, {
            current: 2,
            total: 5,
            sourceNodePath: ["module-a", "child-b"],
            invocationIndex: 1,
            invocationPath: [2, 1],
          }),
        ],
      },
    });

    expect(container.textContent).toContain("Events 4");
    expect(container.textContent).toContain("module-a › child-b · items 3 › 2");
    expect(container.textContent).toContain(unsafeMessage);
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).not.toContain("Preparing");
    expect(buttonWithText(container, "+2").getAttribute("aria-expanded")).toBe(
      "false",
    );

    await React.act(async () => {
      buttonWithText(container, "+2").click();
    });
    expect(container.textContent).toContain("Fetching");
    expect(container.textContent).toContain("Preparing");
    expect(container.textContent).toContain("1 earlier update omitted");
  });

  it("loads expanded history, filters exact node materializations, and opens the exact execution", async () => {
    const first = summary("execution-1", { graph_revision: 9 });
    const second = summary("execution-2", { graph_revision: 8 });
    const third = summary("execution-3", { graph_revision: 7 });
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [first, second, third],
      next_cursor: null,
    });
    apiMocks.getGraphExecution.mockImplementation(
      (_workspaceId, _graphId, executionId) => {
        if (executionId === first.execution_id) {
          return Promise.resolve(
            detail(first, [
              nodeResult("node-a", [
                output("target", ["target-1", "target-2"]),
              ]),
              nodeResult("node-ab", [
                output("other", ["other-1", "other-2", "other-3"]),
              ]),
            ]),
          );
        }
        if (executionId === second.execution_id) {
          return Promise.resolve(
            detail(second, [nodeResult("node-a", [output("empty", [])])]),
          );
        }
        return Promise.resolve(
          detail(third, [
            nodeResult("other-node", [output("other", ["other-4"])]),
          ]),
        );
      },
    );
    const onOpenHistory = vi.fn();
    const { container } = await renderAppendix({
      expanded: true,
      execution: { status: "succeeded" },
      run: runWithArtifacts("node-a", ["temporary-1"]),
      historyContext: {
        workspaceId: "workspace-1",
        graphId: "graph-1",
        isDirty: true,
      },
      onOpenHistory,
    });

    await vi.waitFor(() => {
      expect(apiMocks.listGraphExecutions).toHaveBeenCalledWith(
        "workspace-1",
        "graph-1",
        { limit: 5, nodeId: "node-a" },
      );
      expect(container.textContent).toContain("History 2");
    });
    expect(apiMocks.getGraphExecution).toHaveBeenCalledTimes(3);
    expect(container.textContent).not.toContain("Current result · temporary");

    await React.act(async () => {
      buttonWithText(container, "History 2").click();
    });
    expect(container.textContent).toContain("Current result · temporary");
    expect(container.textContent).toContain("r9");
    expect(container.textContent).toContain("2 artifacts");
    expect(container.textContent).not.toContain("3 artifacts");
    const durableRows = container.querySelectorAll('button[role="listitem"]');
    expect(durableRows).toHaveLength(1);

    await React.act(async () => {
      (durableRows[0] as HTMLButtonElement).click();
    });
    expect(onOpenHistory).toHaveBeenCalledExactlyOnceWith(
      "node-a",
      "execution-1",
    );
  });

  it("marks an unsaved current result temporary without making a history request", async () => {
    const { container } = await renderAppendix({
      expanded: true,
      execution: { status: "succeeded" },
      run: runWithArtifacts("node-a", ["temporary-1", "temporary-2"]),
      historyContext: {
        workspaceId: "workspace-1",
        graphId: null,
        isDirty: true,
      },
    });

    expect(apiMocks.listGraphExecutions).not.toHaveBeenCalled();
    expect(container.textContent).toContain("History 1");
    await React.act(async () => {
      buttonWithText(container, "History 1").click();
    });
    expect(container.textContent).toContain("Current result · temporary");
    expect(container.textContent).toContain("2 artifacts");
    expect(container.textContent).toContain(
      "Save the graph to build durable history.",
    );
    expect(container.querySelector('button[role="listitem"]')).toBeNull();
  });

  it("revalidates expanded history when the current artifact revision changes", async () => {
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [],
      next_cursor: null,
    });
    const { rerender } = await renderAppendix({
      expanded: true,
      historyContext: {
        workspaceId: "workspace-1",
        graphId: "graph-1",
        isDirty: false,
      },
    });
    await vi.waitFor(() => {
      expect(apiMocks.listGraphExecutions).toHaveBeenCalledTimes(1);
    });

    await rerender({
      execution: { status: "succeeded" },
      run: runWithArtifacts("node-a", ["new-artifact"]),
    });
    await vi.waitFor(() => {
      expect(apiMocks.listGraphExecutions).toHaveBeenCalledTimes(2);
    });
  });
});

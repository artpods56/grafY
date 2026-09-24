// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  GraphExecutionDetail,
  GraphExecutionList,
  GraphExecutionSummary,
} from "@/lib/api";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const apiMocks = vi.hoisted(() => ({
  getGraphExecution:
    vi.fn<
      (graphId: string, executionId: string) => Promise<GraphExecutionDetail>
    >(),
  listGraphExecutions: vi.fn<() => Promise<GraphExecutionList>>(),
}));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("@/hooks/use-api", () => ({
  useNodeRegistry: () => ({ data: { artifact_types: [] } }),
}));

vi.mock("@/features/workspaces/WorkspaceLayout", () => ({
  useWorkspaceContext: () => ({
    workspace: {
      id: "workspace-1",
      slug: "team",
      name: "Local",
      kind: "personal",
      role: "owner",
      capabilities: [],
    },
    workspaces: [],
    refreshWorkspaces: async () => undefined,
  }),
}));

vi.mock("@/lib/api", () => ({
  artifactContentUrl: (
    _workspaceId: string,
    value: string | null | undefined,
  ) => value ?? null,
  getGraphExecution: apiMocks.getGraphExecution,
  listGraphExecutions: apiMocks.listGraphExecutions,
}));

import { ExecutionHistoryDrawer } from "./ExecutionHistoryDrawer";

const mountedRoots = new Map<Root, HTMLElement>();

afterEach(async () => {
  for (const [root, container] of mountedRoots) {
    await React.act(async () => root.unmount());
    container.remove();
  }
  mountedRoots.clear();
  document.body.replaceChildren();
  vi.clearAllMocks();
});

function summary(
  executionId: string,
  overrides: Partial<GraphExecutionSummary> = {},
): GraphExecutionSummary {
  return {
    execution_id: executionId,
    graph_id: "graph-1",
    graph_revision: 4,
    status: "succeeded",
    scope: "selected-with-dependencies",
    requested_node_ids: ["node-1"],
    created_at: "2026-07-18T08:00:00Z",
    started_at: "2026-07-18T08:00:01Z",
    finished_at: "2026-07-18T08:00:02Z",
    workflow_run_id: "workflow-1",
    error: null,
    node_count: 2,
    artifact_count: 1,
    ...overrides,
  };
}

function detail(execution: GraphExecutionSummary): GraphExecutionDetail {
  return {
    ...execution,
    node_results: [
      {
        node_id: "node-1",
        position: 0,
        status: "succeeded",
        error: null,
        completed_at: "2026-07-18T08:00:02Z",
        outputs: [
          {
            port: "document",
            kind: "single",
            value: {
              artifact_id: "artifact-1",
              artifact_type: "scalar.text",
              schema_version: 1,
            },
            artifacts: [
              {
                artifact_id: "artifact-1",
                artifact_type: "scalar.text",
                schema_version: 1,
                content_type: "text/plain",
                text: "historical value",
              },
            ],
          },
          {
            port: "lost_output",
            kind: "single",
            value: {
              artifact_id: "artifact-missing",
              artifact_type: "scalar.text",
              schema_version: 1,
            },
            artifacts: [],
          },
        ],
      },
    ],
  };
}

async function renderDrawer(
  props: Partial<React.ComponentProps<typeof ExecutionHistoryDrawer>> = {},
  cache = new Map(),
) {
  const container = document.createElement("div");
  document.body.append(container);
  const returnFocusElement = document.createElement("button");
  document.body.append(returnFocusElement);
  const root = createRoot(container);
  mountedRoots.set(root, container);
  const swrConfig = { provider: () => cache, dedupingInterval: 0 };
  let currentProps: React.ComponentProps<typeof ExecutionHistoryDrawer> = {
    workspaceId: "workspace-1",
    graphId: "graph-1",
    graphName: "Invoices",
    nodeId: null,
    initialExecutionId: null,
    nodeTitles: { "node-1": "Extract invoice" },
    executionRunning: false,
    isDirty: false,
    returnFocusRef: { current: returnFocusElement },
    onClose: () => undefined,
    ...props,
  };
  const rerender = async (
    nextProps: Partial<React.ComponentProps<typeof ExecutionHistoryDrawer>>,
  ) => {
    currentProps = { ...currentProps, ...nextProps };
    await React.act(async () => {
      root.render(
        <SWRConfig value={swrConfig}>
          <ExecutionHistoryDrawer {...currentProps} />
        </SWRConfig>,
      );
    });
  };
  await React.act(async () => {
    root.render(
      <SWRConfig value={swrConfig}>
        <ExecutionHistoryDrawer {...currentProps} />
      </SWRConfig>,
    );
  });
  const unmount = async () => {
    await React.act(async () => root.unmount());
    mountedRoots.delete(root);
    container.remove();
  };
  return { container, rerender, returnFocusElement, unmount };
}

function buttonNamed(container: HTMLElement, name: string): HTMLButtonElement {
  const button = [...container.querySelectorAll("button")].find(
    (candidate) =>
      candidate.textContent?.trim() === name ||
      candidate.getAttribute("aria-label") === name,
  );
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`Button ${name} was not rendered`);
  }
  return button;
}

describe("ExecutionHistoryDrawer", () => {
  it("closes on Escape after focus leaves the drawer and restores the trigger", async () => {
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [],
      next_cursor: null,
    });
    const onClose = vi.fn();
    const { container, returnFocusElement } = await renderDrawer({ onClose });

    const closeButton = buttonNamed(container, "Close execution history");
    expect(document.activeElement).toBe(closeButton);
    returnFocusElement.focus();

    await React.act(async () => {
      returnFocusElement.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
    });

    expect(onClose).toHaveBeenCalledOnce();
    expect(document.activeElement).toBe(returnFocusElement);
  });

  it("lists run provenance and renders historical artifacts without touching canvas state", async () => {
    const execution = summary("execution-1");
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [execution],
      next_cursor: null,
    });
    apiMocks.getGraphExecution.mockResolvedValue(detail(execution));

    const { container } = await renderDrawer();

    await vi.waitFor(() => {
      expect(container.textContent).toContain("selected with dependencies");
      expect(container.textContent).toContain(
        "1 requested node · 2 nodes · 1 artifact",
      );
      expect(container.textContent).toContain("Extract invoice");
      expect(container.textContent).toContain("document");
      expect(container.textContent).toContain("historical value");
      expect(container.textContent).toContain(
        "Historical artifact metadata is unavailable.",
      );
    });
    expect(apiMocks.listGraphExecutions).toHaveBeenCalledWith(
      "workspace-1",
      "graph-1",
      { limit: 20, nodeId: undefined },
    );
    expect(apiMocks.getGraphExecution).toHaveBeenCalledWith(
      "workspace-1",
      "graph-1",
      "execution-1",
    );
  });

  it("uses the same drawer as a node-filtered empty state", async () => {
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [],
      next_cursor: null,
    });

    const { container } = await renderDrawer({ nodeId: "node-1" });

    await vi.waitFor(() => {
      expect(container.textContent).toContain(
        "No recorded executions include Extract invoice.",
      );
    });
    expect(apiMocks.listGraphExecutions).toHaveBeenCalledWith(
      "workspace-1",
      "graph-1",
      { limit: 20, nodeId: "node-1" },
    );
    expect(apiMocks.getGraphExecution).not.toHaveBeenCalled();
  });

  it("selects the requested execution when it is present", async () => {
    const latest = summary("execution-latest");
    const requested = summary("execution-requested", {
      created_at: "2026-07-17T08:00:00Z",
      started_at: "2026-07-17T08:00:01Z",
      finished_at: "2026-07-17T08:00:02Z",
    });
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [latest, requested],
      next_cursor: null,
    });
    apiMocks.getGraphExecution.mockResolvedValue(detail(requested));

    const { container } = await renderDrawer({
      initialExecutionId: requested.execution_id,
    });

    await vi.waitFor(() => {
      expect(apiMocks.getGraphExecution).toHaveBeenCalledWith(
        "workspace-1",
        "graph-1",
        "execution-requested",
      );
      const executionButtons = [
        ...container.querySelectorAll('button[role="listitem"]'),
      ];
      expect(
        executionButtons
          .find((button) => button.textContent?.includes("execution-requested"))
          ?.getAttribute("aria-current"),
      ).toBe("true");
      expect(
        executionButtons
          .find((button) => button.textContent?.includes("execution-latest"))
          ?.getAttribute("aria-current"),
      ).toBeNull();
    });
  });

  it("loads the next cursor and closes through explicit actions", async () => {
    const first = summary("execution-1");
    const second = summary("execution-2", {
      created_at: "2026-07-17T08:00:00Z",
      started_at: null,
      finished_at: null,
    });
    apiMocks.listGraphExecutions
      .mockResolvedValueOnce({ items: [first], next_cursor: "page-2" })
      .mockResolvedValueOnce({ items: [first], next_cursor: "page-2" })
      .mockResolvedValueOnce({ items: [second], next_cursor: null });
    apiMocks.getGraphExecution.mockResolvedValue(detail(first));
    const onClose = vi.fn();
    const { container } = await renderDrawer({ onClose });

    await vi.waitFor(() =>
      expect(container.textContent).toContain("Load more"),
    );
    await React.act(async () => buttonNamed(container, "Load more").click());
    await vi.waitFor(() =>
      expect(container.textContent).toContain("execution-2"),
    );
    expect(apiMocks.listGraphExecutions).toHaveBeenNthCalledWith(
      3,
      "workspace-1",
      "graph-1",
      { limit: 20, cursor: "page-2", nodeId: undefined },
    );

    buttonNamed(container, "Close execution history").click();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("revalidates the cached first page when the drawer is reopened", async () => {
    const older = summary("execution-older");
    const newest = summary("execution-newest", {
      created_at: "2026-07-18T09:00:00Z",
      started_at: "2026-07-18T09:00:01Z",
      finished_at: "2026-07-18T09:00:02Z",
    });
    const cache = new Map();
    apiMocks.listGraphExecutions
      .mockResolvedValueOnce({ items: [older], next_cursor: null })
      .mockResolvedValue({ items: [newest], next_cursor: null });
    apiMocks.getGraphExecution.mockImplementation(
      async (_graphId, executionId) =>
        detail(executionId === newest.execution_id ? newest : older),
    );

    const firstDrawer = await renderDrawer({}, cache);
    await vi.waitFor(() => {
      expect(firstDrawer.container.textContent).toContain("execution-older");
      expect(apiMocks.listGraphExecutions).toHaveBeenCalledTimes(1);
    });
    await firstDrawer.unmount();

    const secondDrawer = await renderDrawer({}, cache);
    await vi.waitFor(() => {
      expect(apiMocks.listGraphExecutions).toHaveBeenCalledTimes(2);
      expect(secondDrawer.container.textContent).toContain("execution-newest");
    });
  });

  it("revalidates the bound list and detail once when an execution completes", async () => {
    const active = summary("execution-1", {
      status: "running",
      finished_at: null,
    });
    const completed = summary("execution-1");
    apiMocks.listGraphExecutions
      .mockResolvedValueOnce({ items: [active], next_cursor: null })
      .mockResolvedValue({ items: [completed], next_cursor: null });
    apiMocks.getGraphExecution
      .mockResolvedValueOnce(detail(active))
      .mockResolvedValue(detail(completed));

    const drawer = await renderDrawer({ executionRunning: true });
    await vi.waitFor(() => {
      expect(apiMocks.listGraphExecutions).toHaveBeenCalledTimes(1);
      expect(apiMocks.getGraphExecution).toHaveBeenCalledTimes(1);
    });

    await drawer.rerender({ executionRunning: false });
    await vi.waitFor(() => {
      expect(apiMocks.listGraphExecutions).toHaveBeenCalledTimes(2);
      expect(apiMocks.getGraphExecution).toHaveBeenCalledTimes(2);
    });

    await drawer.rerender({ executionRunning: false });
    await Promise.resolve();
    expect(apiMocks.listGraphExecutions).toHaveBeenCalledTimes(2);
    expect(apiMocks.getGraphExecution).toHaveBeenCalledTimes(2);
  });

  it("warns that runs from unsaved graph changes are not durable", async () => {
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [],
      next_cursor: null,
    });

    const { container } = await renderDrawer({ isDirty: true });

    await vi.waitFor(() => {
      expect(container.textContent).toContain(
        "Runs started with unsaved changes are temporary and are not recorded here.",
      );
      expect(container.textContent).toContain(
        "Save the graph first to keep durable execution history.",
      );
    });
  });

  it("renders a recoverable list error", async () => {
    apiMocks.listGraphExecutions
      .mockRejectedValueOnce(new Error("History unavailable"))
      .mockResolvedValueOnce({ items: [], next_cursor: null });
    const { container } = await renderDrawer();

    await vi.waitFor(() =>
      expect(container.textContent).toContain("History unavailable"),
    );
    await React.act(async () => buttonNamed(container, "Try again").click());
    await vi.waitFor(() =>
      expect(apiMocks.listGraphExecutions).toHaveBeenCalledTimes(2),
    );
  });
});

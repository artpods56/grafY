// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  GraphExecutionDetail,
  GraphExecutionList,
  GraphExecutionSummary,
  LibraryItem,
  LibraryList,
  SaveRunArtifactRequest,
} from "@/lib/api";
import { ARTIFACT_DROP_DATA_TYPE } from "../model/artifact-drop";

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
      (workspaceId: string, graphId: string) => Promise<GraphExecutionList>
    >(),
  listLibraryArtifacts: vi.fn<(workspaceId: string) => Promise<LibraryList>>(),
  saveRunArtifactToLibrary:
    vi.fn<
      (
        workspaceId: string,
        body: SaveRunArtifactRequest,
      ) => Promise<LibraryItem>
    >(),
}));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
  when: { ancestor: () => "" },
}));

vi.mock("@/lib/api", () => ({
  getGraphExecution: apiMocks.getGraphExecution,
  listGraphExecutions: apiMocks.listGraphExecutions,
  listLibraryArtifacts: apiMocks.listLibraryArtifacts,
  saveRunArtifactToLibrary: apiMocks.saveRunArtifactToLibrary,
}));

import { GeneratedDrawer } from "./GeneratedDrawer";

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

const REGISTRY = {
  artifact_types: [
    {
      key: { id: "table.data", schema_version: 1 },
      title: "Table",
    },
    {
      key: { id: "file.blob", schema_version: 1 },
      title: "Unrecognized file",
    },
  ],
  nodes: [],
  plugins: [],
} as unknown as React.ComponentProps<typeof GeneratedDrawer>["registry"];

function summary(
  executionId: string,
  overrides: Partial<GraphExecutionSummary> = {},
): GraphExecutionSummary {
  return {
    execution_id: executionId,
    graph_id: "graph-1",
    graph_revision: 4,
    status: "succeeded",
    scope: "all",
    requested_node_ids: ["resize-1"],
    created_at: "2026-07-18T08:00:00Z",
    started_at: "2026-07-18T08:00:01Z",
    finished_at: "2026-07-18T08:00:02Z",
    workflow_run_id: "workflow-1",
    error: null,
    node_count: 1,
    artifact_count: 1,
    ...overrides,
  };
}

function detail(
  execution: GraphExecutionSummary,
  nodeResults: GraphExecutionDetail["node_results"],
): GraphExecutionDetail {
  return { ...execution, node_results: nodeResults };
}

function tableOutput(
  artifactId: string,
  metadata: Readonly<Record<string, unknown>> = {},
) {
  return {
    port: "tables",
    kind: "single" as const,
    value: {
      artifact_id: artifactId,
      artifact_type: "table.data",
      schema_version: 1,
    },
    artifacts: [
      {
        artifact_id: artifactId,
        artifact_type: "table.data",
        schema_version: 1,
        content_type: "application/json",
        metadata,
        sha256: `sha-${artifactId}`,
      },
    ],
  };
}

const LATEST_RUN = summary("execution-2", { graph_revision: 4 });
const OLDER_RUN = summary("execution-1", {
  graph_revision: 3,
  finished_at: "2026-07-17T08:00:02Z",
});

const NODE_TITLES = {
  "resize-1": "Resize",
  "summarize-1": "Summarize",
};

function libraryItem(artifactId: string): LibraryItem {
  return {
    artifact: {
      artifact_id: artifactId,
      artifact_type: "table.data",
      schema_version: 1,
      content_type: "application/json",
    },
    name: "Table",
    provenance: {
      source: "run",
      saved_at: "2026-07-18T09:00:00Z",
      graph_id: "graph-1",
      graph_title: "Invoices",
      node_id: "resize-1",
      node_title: "Resize",
      graph_revision: 4,
      execution_id: "execution-2",
    },
    run: null,
  };
}

async function renderDrawer(
  props: Partial<React.ComponentProps<typeof GeneratedDrawer>> = {},
) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.set(root, container);
  const cache = new Map();
  const swrConfig = { provider: () => cache, dedupingInterval: 0 };
  let currentProps: React.ComponentProps<typeof GeneratedDrawer> = {
    workspaceId: "workspace-1",
    graphId: "graph-1",
    nodeTitles: NODE_TITLES,
    registry: REGISTRY,
    canSave: true,
    executionRunning: false,
    onClose: () => undefined,
    ...props,
  };
  const render = async () => {
    await React.act(async () => {
      root.render(
        <SWRConfig value={swrConfig}>
          <GeneratedDrawer {...currentProps} />
        </SWRConfig>,
      );
    });
  };
  await render();
  const rerender = async (
    nextProps: Partial<React.ComponentProps<typeof GeneratedDrawer>>,
  ) => {
    currentProps = { ...currentProps, ...nextProps };
    await render();
  };
  return { container, rerender };
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

function buttonContaining(
  container: HTMLElement,
  name: string,
): HTMLButtonElement {
  const button = [...container.querySelectorAll("button")].find((candidate) =>
    candidate.textContent?.includes(name),
  );
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`Button containing ${name} was not rendered`);
  }
  return button;
}

function rowFor(container: HTMLElement, artifactId: string): HTMLElement {
  const row = container.querySelector(`[data-artifact-row="${artifactId}"]`);
  if (!(row instanceof HTMLElement)) {
    throw new Error(`Row ${artifactId} was not rendered`);
  }
  return row;
}

/** A browser-style artifact drag: the row writes the payload the canvas reads. */
function dragPayload(row: HTMLElement): unknown {
  const store = new Map<string, string>();
  const event = new Event("dragstart", { bubbles: true });
  Object.defineProperty(event, "dataTransfer", {
    value: {
      setData: (type: string, value: string) => store.set(type, value),
      getData: (type: string) => store.get(type) ?? "",
      types: [...store.keys()],
      effectAllowed: "none",
    },
  });
  React.act(() => {
    row.dispatchEvent(event);
  });
  return JSON.parse(store.get(ARTIFACT_DROP_DATA_TYPE) ?? "null");
}

describe("GeneratedDrawer", () => {
  it("lists the newest run's artifacts grouped by the node that made them", async () => {
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [LATEST_RUN],
      next_cursor: null,
    });
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    apiMocks.getGraphExecution.mockResolvedValue(
      detail(LATEST_RUN, [
        {
          node_id: "resize-1",
          position: 1,
          status: "succeeded",
          error: null,
          completed_at: "2026-07-18T08:00:02Z",
          outputs: [tableOutput("artifact-latest")],
        },
        {
          node_id: "summarize-1",
          position: 0,
          status: "succeeded",
          error: null,
          completed_at: "2026-07-18T08:00:01Z",
          outputs: [
            tableOutput("artifact-summary", { download_name: "invoices.csv" }),
          ],
        },
      ]),
    );

    const { container } = await renderDrawer();

    expect(container.textContent).toContain("Latest run");
    expect(container.textContent).toContain("Resize");
    expect(container.textContent).toContain("Summarize");
    expect(container.textContent).toContain("rev 4");
    expect(rowFor(container, "artifact-latest")).toBeDefined();
    expect(rowFor(container, "artifact-summary")).toBeDefined();
    // A row carries the name the Library would give the artifact.
    expect(rowFor(container, "artifact-summary").textContent).toContain(
      "invoices.csv",
    );
    // Each group carries the time its node finished.
    expect(container.textContent).toContain("Jul 18, 2026");
  });

  it("lists an older output under Previous runs with its revision, still draggable", async () => {
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [LATEST_RUN, OLDER_RUN],
      next_cursor: null,
    });
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    apiMocks.getGraphExecution.mockImplementation(
      async (_workspaceId, _graphId, executionId) =>
        executionId === LATEST_RUN.execution_id
          ? detail(LATEST_RUN, [
              {
                node_id: "resize-1",
                position: 0,
                status: "succeeded",
                error: null,
                completed_at: "2026-07-18T08:00:02Z",
                outputs: [tableOutput("artifact-latest")],
              },
            ])
          : detail(OLDER_RUN, [
              {
                node_id: "resize-1",
                position: 0,
                status: "succeeded",
                error: null,
                completed_at: "2026-07-17T08:00:02Z",
                outputs: [tableOutput("artifact-older")],
              },
            ]),
    );

    const { container } = await renderDrawer();
    // The batch is closed, so an older run costs no detail request yet.
    expect(
      container.querySelector('[data-artifact-row="artifact-older"]'),
    ).toBeNull();

    await React.act(async () => {
      buttonContaining(container, "Previous runs").click();
    });

    const olderRow = rowFor(container, "artifact-older");
    expect(olderRow.getAttribute("draggable")).toBe("true");
    expect(olderRow.textContent).toContain("rev 3");
  });

  it("saves an artifact into the Library, keeps the run row, and marks it saved", async () => {
    const saved: LibraryItem[] = [];
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [LATEST_RUN],
      next_cursor: null,
    });
    apiMocks.listLibraryArtifacts.mockImplementation(async () => ({
      items: [...saved],
    }));
    apiMocks.saveRunArtifactToLibrary.mockImplementation(
      async (_workspaceId, body) => {
        const existing = saved.find(
          (item) => item.artifact.artifact_id === body.artifact_id,
        );
        if (existing) return existing;
        const item = libraryItem(body.artifact_id);
        saved.push(item);
        return item;
      },
    );
    apiMocks.getGraphExecution.mockResolvedValue(
      detail(LATEST_RUN, [
        {
          node_id: "resize-1",
          position: 0,
          status: "succeeded",
          error: null,
          completed_at: "2026-07-18T08:00:02Z",
          outputs: [tableOutput("artifact-latest")],
        },
      ]),
    );

    const { container } = await renderDrawer();
    const row = rowFor(container, "artifact-latest");
    expect(row.textContent).not.toContain("saved");

    await React.act(async () => {
      const save = [...row.querySelectorAll("button")].find(
        (button) => button.textContent?.trim() === "Save",
      );
      save?.click();
    });

    expect(apiMocks.saveRunArtifactToLibrary).toHaveBeenCalledWith(
      "workspace-1",
      {
        artifact_id: "artifact-latest",
        execution_id: "execution-2",
        node_id: "resize-1",
        node_title: "Resize",
      },
    );
    // The row stays in Runs; the same artifact now also sits in the Library.
    const keptRow = rowFor(container, "artifact-latest");
    expect(keptRow.textContent).toContain("saved");
  });

  it("keeps one Library item and the saved badge when the same identity is saved twice", async () => {
    const saved: LibraryItem[] = [];
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [LATEST_RUN],
      next_cursor: null,
    });
    apiMocks.listLibraryArtifacts.mockImplementation(async () => ({
      items: [...saved],
    }));
    apiMocks.saveRunArtifactToLibrary.mockImplementation(
      async (_workspaceId, body) => {
        const existing = saved.find(
          (item) => item.artifact.artifact_id === body.artifact_id,
        );
        if (existing) return existing;
        const item = libraryItem(body.artifact_id);
        saved.push(item);
        return item;
      },
    );
    apiMocks.getGraphExecution.mockResolvedValue(
      detail(LATEST_RUN, [
        {
          node_id: "resize-1",
          position: 0,
          status: "succeeded",
          error: null,
          completed_at: "2026-07-18T08:00:02Z",
          outputs: [tableOutput("artifact-latest")],
        },
      ]),
    );

    const { container } = await renderDrawer();
    const clickSave = async () => {
      const row = rowFor(container, "artifact-latest");
      await React.act(async () => {
        [...row.querySelectorAll("button")]
          .find((button) => button.textContent?.trim() === "Save")
          ?.click();
      });
    };
    await clickSave();
    await clickSave();

    expect(apiMocks.saveRunArtifactToLibrary).toHaveBeenCalledTimes(2);
    expect(saved).toHaveLength(1);
    expect(
      container.querySelectorAll('[data-artifact-row="artifact-latest"]'),
    ).toHaveLength(1);
    expect(
      [...container.querySelectorAll('[aria-label="Generated"] *')].filter(
        (node) => node.textContent?.trim() === "saved",
      ),
    ).toHaveLength(1);
  });

  it("writes the same artifact drop payload a Library row writes", async () => {
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [LATEST_RUN],
      next_cursor: null,
    });
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    apiMocks.getGraphExecution.mockResolvedValue(
      detail(LATEST_RUN, [
        {
          node_id: "resize-1",
          position: 0,
          status: "succeeded",
          error: null,
          completed_at: "2026-07-18T08:00:02Z",
          outputs: [tableOutput("artifact-latest")],
        },
      ]),
    );

    const { container } = await renderDrawer();

    expect(dragPayload(rowFor(container, "artifact-latest"))).toEqual({
      value: {
        artifact_id: "artifact-latest",
        artifact_type: "table.data",
        schema_version: 1,
        content_hash: "sha-artifact-latest",
      },
      shape: "one",
    });
  });

  it("keeps the ingest notice on a blob row", async () => {
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [LATEST_RUN],
      next_cursor: null,
    });
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    apiMocks.getGraphExecution.mockResolvedValue(
      detail(LATEST_RUN, [
        {
          node_id: "resize-1",
          position: 0,
          status: "succeeded",
          error: null,
          completed_at: "2026-07-18T08:00:02Z",
          outputs: [
            {
              port: "file",
              kind: "single",
              value: {
                artifact_id: "artifact-blob",
                artifact_type: "file.blob",
                schema_version: 1,
              },
              artifacts: [
                {
                  artifact_id: "artifact-blob",
                  artifact_type: "file.blob",
                  schema_version: 1,
                  content_type: "application/octet-stream",
                },
              ],
            },
          ],
        },
      ]),
    );

    const { container } = await renderDrawer();

    expect(container.textContent).toContain(
      "Format not recognized, stored as a blob.",
    );
  });

  it("re-reads the canvas runs once a run finishes", async () => {
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    apiMocks.getGraphExecution.mockResolvedValue(
      detail(LATEST_RUN, [
        {
          node_id: "resize-1",
          position: 0,
          status: "succeeded",
          error: null,
          completed_at: "2026-07-18T08:00:02Z",
          outputs: [tableOutput("artifact-latest")],
        },
      ]),
    );
    apiMocks.listGraphExecutions.mockResolvedValueOnce({
      items: [],
      next_cursor: null,
    });
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [LATEST_RUN],
      next_cursor: null,
    });

    const { container, rerender } = await renderDrawer({
      executionRunning: true,
    });
    expect(container.textContent).toContain(
      "No run of this canvas is recorded",
    );

    await rerender({ executionRunning: false });

    expect(rowFor(container, "artifact-latest")).toBeDefined();
  });

  it("says an unsaved canvas cannot record runs", async () => {
    const { container } = await renderDrawer({ graphId: null });

    expect(container.textContent).toContain(
      "Save this graph before browsing the Run artifacts",
    );
    expect(apiMocks.listGraphExecutions).not.toHaveBeenCalled();
    // No canvas means no rows, so the Library is not read either.
    expect(apiMocks.listLibraryArtifacts).not.toHaveBeenCalled();
  });

  it("reports a refused save without dropping the run row", async () => {
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [LATEST_RUN],
      next_cursor: null,
    });
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    apiMocks.saveRunArtifactToLibrary.mockRejectedValue(
      new Error("Artifact is not an output of node 'resize-1'"),
    );
    apiMocks.getGraphExecution.mockResolvedValue(
      detail(LATEST_RUN, [
        {
          node_id: "resize-1",
          position: 0,
          status: "succeeded",
          error: null,
          completed_at: "2026-07-18T08:00:02Z",
          outputs: [tableOutput("artifact-latest")],
        },
      ]),
    );

    const { container } = await renderDrawer();
    const row = rowFor(container, "artifact-latest");
    await React.act(async () => {
      [...row.querySelectorAll("button")]
        .find((button) => button.textContent?.trim() === "Save")
        ?.click();
    });

    expect(container.textContent).toContain(
      "Artifact is not an output of node 'resize-1'",
    );
    expect(rowFor(container, "artifact-latest").textContent).toContain("rev 4");
  });

  it("offers no working Save without edit access", async () => {
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [LATEST_RUN],
      next_cursor: null,
    });
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    apiMocks.getGraphExecution.mockResolvedValue(
      detail(LATEST_RUN, [
        {
          node_id: "resize-1",
          position: 0,
          status: "succeeded",
          error: null,
          completed_at: "2026-07-18T08:00:02Z",
          outputs: [tableOutput("artifact-latest")],
        },
      ]),
    );

    const { container } = await renderDrawer({ canSave: false });
    const row = rowFor(container, "artifact-latest");
    const save = [...row.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "Save",
    );
    if (!(save instanceof HTMLButtonElement)) {
      throw new Error("Save button was not rendered");
    }

    expect(save.disabled).toBe(true);
    expect(save.title).toBe("Saving into the Library needs edit access");
    await React.act(async () => {
      save.click();
    });
    expect(apiMocks.saveRunArtifactToLibrary).not.toHaveBeenCalled();
  });

  it("closes from its own control", async () => {
    apiMocks.listGraphExecutions.mockResolvedValue({
      items: [],
      next_cursor: null,
    });
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    const onClose = vi.fn();
    const { container } = await renderDrawer({ onClose });

    await React.act(async () => {
      buttonNamed(container, "Close Generated").click();
    });

    expect(onClose).toHaveBeenCalledOnce();
  });
});

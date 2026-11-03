// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  ArtifactOutputValue,
  ArtifactRef,
  InstanceResult,
  InstanceState,
  InstanceStateList,
  LibraryItem,
  LibraryList,
  SaveInstanceArtifactRequest,
} from "@/lib/api";
import { ARTIFACT_DROP_DATA_TYPE } from "../model/artifact-drop";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const apiMocks = vi.hoisted(() => ({
  listGraphInstances:
    vi.fn<
      (
        workspaceId: string,
        projectId: string,
        graphId: string,
      ) => Promise<InstanceStateList>
    >(),
  getInstanceResult: vi.fn<
    (
      workspaceId: string,
      projectId: string,
      instance: {
        graph_id: string;
        node_id: string;
        call_path?: readonly string[];
      },
    ) => Promise<InstanceResult>
  >(),
  listLibraryArtifacts: vi.fn<(workspaceId: string) => Promise<LibraryList>>(),
  saveInstanceArtifactToLibrary:
    vi.fn<
      (
        workspaceId: string,
        body: SaveInstanceArtifactRequest,
      ) => Promise<LibraryItem>
    >(),
}));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
  when: { ancestor: () => "" },
}));

vi.mock("@/lib/api", () => ({
  listGraphInstances: apiMocks.listGraphInstances,
  getInstanceResult: apiMocks.getInstanceResult,
  listLibraryArtifacts: apiMocks.listLibraryArtifacts,
  saveInstanceArtifactToLibrary: apiMocks.saveInstanceArtifactToLibrary,
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
  vi.unstubAllGlobals();
  // Reset, not clear: an unconsumed mockRejectedValueOnce would otherwise be
  // handed to the next test and fail it for a reason that is not its own.
  vi.resetAllMocks();
});

const REGISTRY = {
  artifact_types: [
    {
      key: { id: "table.data", schema_version: 1 },
      title: "Table",
      bundle: { format: "inline-json", version: 1 },
      payload_schema: {},
      field_projections: [],
    },
    {
      key: { id: "file.blob", schema_version: 1 },
      title: "Unrecognized file",
      bundle: { format: "inline-json", version: 1 },
      payload_schema: {},
      field_projections: [],
    },
  ],
  nodes: [],
  plugins: [],
  artifact_conversions: [],
} satisfies React.ComponentProps<typeof GeneratedDrawer>["registry"];

const PROJECT_ID = "project-1";
const GRAPH_ID = "graph-1";

const NODE_TITLES = {
  "resize-1": "Resize",
  "summarize-1": "Summarize",
  "call-invoices": "Invoices",
};

function instance(
  nodeId: string,
  overrides: Partial<InstanceState> = {},
  key: Partial<InstanceState["key"]> = {},
): InstanceState {
  return {
    key: {
      project_id: PROJECT_ID,
      graph_id: GRAPH_ID,
      call_path: [],
      node_id: nodeId,
      map_index: null,
      ...key,
    },
    state: "fresh",
    fingerprint: `fingerprint-${nodeId}`,
    last_result_fingerprint: `result-${nodeId}`,
    error: null,
    ...overrides,
  };
}

/** An instance that is demanded but has nothing stored yet. */
function pendingInstance(nodeId: string): InstanceState {
  return instance(nodeId, {
    state: "running",
    last_result_fingerprint: null,
  });
}

/** One stored artifact reference, as a result hands it back. */
function refOf(artifactId: string): ArtifactRef {
  return {
    artifact_id: artifactId,
    artifact_type: "table.data",
    schema_version: 1,
    content_hash: `sha-${artifactId}`,
  };
}

function tableValue(artifactId: string): ArtifactOutputValue {
  return refOf(artifactId);
}

function result(
  owner: InstanceState,
  outputs: Record<string, ArtifactOutputValue> | null,
  overrides: Partial<InstanceResult> = {},
): InstanceResult {
  return {
    instance: owner,
    outputs,
    result_fingerprint: owner.last_result_fingerprint,
    created_at: "2026-07-18T08:00:02Z",
    ...overrides,
  };
}

function libraryItem(artifactId: string, name = "Table"): LibraryItem {
  return {
    artifact: {
      artifact_id: artifactId,
      artifact_type: "table.data",
      schema_version: 1,
      content_type: "application/json",
    },
    name,
    provenance: {
      source: "instance",
      saved_at: "2026-07-18T09:00:00Z",
      project_id: PROJECT_ID,
      project_title: "Invoices project",
      graph_id: GRAPH_ID,
      graph_title: "Invoices",
      node_id: "resize-1",
      node_title: "Resize",
      call_path: [],
      result_fingerprint: "result-resize-1",
      output_port: "tables",
      item_index: null,
      name: "Table",
    },
  };
}

/** One SWR cache, so a second mount reads what the first one already loaded. */
function createSwrCache() {
  return new Map();
}

function alerts(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>('[role="alert"]')];
}

function alertMentioning(container: HTMLElement, text: string): HTMLElement {
  const alert = alerts(container).find((node) =>
    node.textContent?.includes(text),
  );
  if (!alert) {
    throw new Error(
      `No alert mentions ${text}. Alerts: ${JSON.stringify(
        alerts(container).map((node) => node.textContent),
      )}`,
    );
  }
  return alert as HTMLElement;
}

async function renderDrawer(
  props: Partial<React.ComponentProps<typeof GeneratedDrawer>> = {},
  options: { cache?: ReturnType<typeof createSwrCache> } = {},
) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.set(root, container);
  const cache = options.cache ?? createSwrCache();
  const swrConfig = { provider: () => cache, dedupingInterval: 0 };
  let currentProps: React.ComponentProps<typeof GeneratedDrawer> = {
    workspaceId: "workspace-1",
    projectId: PROJECT_ID,
    graphId: GRAPH_ID,
    nodeTitles: NODE_TITLES,
    registry: REGISTRY,
    canSave: true,
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
  /** Closing and reopening the panel: the cache survives, the component does not. */
  const unmount = async () => {
    mountedRoots.delete(root);
    await React.act(async () => root.unmount());
    container.remove();
  };
  return { container, rerender, unmount };
}

/**
 * SWR defers the revalidation of a key that already holds data to the next
 * animation frame, so a re-read only starts once a frame has passed.
 */
async function nextFrame() {
  await React.act(async () => {
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => resolve());
    });
  });
}

function libraryNameInput(): HTMLInputElement {
  const input = document.querySelector<HTMLInputElement>(
    'input[aria-label="Library name"]',
  );
  if (!input) throw new Error("The naming dialog was not shown");
  return input;
}

/** Clicks a row's Save and confirms the name the dialog offers. */
async function saveWithDefaultName(row: HTMLElement) {
  await React.act(async () => {
    saveIn(row).click();
  });
  const input = libraryNameInput();
  await React.act(async () => {
    input.form?.requestSubmit();
  });
}

async function submitLibraryName(input: HTMLInputElement, name: string) {
  const setValue = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  await React.act(async () => {
    setValue?.call(input, name);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await React.act(async () => {
    input.form?.requestSubmit();
  });
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

function saveIn(row: HTMLElement): HTMLButtonElement {
  const button = [...row.querySelectorAll("button")].find(
    (candidate) => candidate.textContent?.trim() === "Save",
  );
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error("Save button was not rendered");
  }
  return button;
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

/** One Graph whose `resize-1` node stored `artifactId`, plus anything else. */
function storedResults(
  entries: readonly {
    owner: InstanceState;
    outputs: Record<string, ArtifactOutputValue> | null;
    created_at?: string;
  }[],
) {
  apiMocks.listGraphInstances.mockResolvedValue({
    instances: entries.map((entry) => entry.owner),
  });
  apiMocks.getInstanceResult.mockImplementation(
    async (_workspace, _project, key) => {
      const entry = entries.find(
        (candidate) =>
          candidate.owner.key.node_id === key.node_id &&
          candidate.owner.key.graph_id === key.graph_id &&
          (candidate.owner.key.call_path ?? []).join(">") ===
            (key.call_path ?? []).join(">"),
      );
      if (!entry) throw new Error(`No result for ${key.node_id}`);
      return result(entry.owner, entry.outputs, {
        ...(entry.created_at ? { created_at: entry.created_at } : {}),
      });
    },
  );
}

describe("GeneratedDrawer", () => {
  it("lists each node instance that stored a result, with the state beside it", async () => {
    storedResults([
      {
        owner: instance("resize-1"),
        outputs: { tables: tableValue("artifact-resized") },
      },
      {
        owner: instance("summarize-1", {
          state: "stale",
          last_result_fingerprint: "result-summarize-old",
        }),
        outputs: { tables: tableValue("artifact-summary") },
        created_at: "2026-07-17T08:00:02Z",
      },
    ]);
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });

    const { container } = await renderDrawer();

    expect(container.textContent).toContain("Resize");
    expect(container.textContent).toContain("Summarize");
    // The first instance is open, so its rows are already on screen.
    expect(rowFor(container, "artifact-resized")).toBeDefined();
    expect(container.textContent).toContain("Fresh");
    expect(container.textContent).toContain("Stale");
    // The list is read for the open Graph, under its Project.
    expect(apiMocks.listGraphInstances).toHaveBeenCalledWith(
      "workspace-1",
      PROJECT_ID,
      GRAPH_ID,
    );
    // A row is named by its artifact type and carries its port identity.
    expect(rowFor(container, "artifact-resized").textContent).toContain(
      "Table",
    );
    expect(rowFor(container, "artifact-resized").textContent).toContain(
      "table.data@1",
    );
    // The stored time comes from the result itself.
    expect(container.textContent).toContain("stored");
    expect(container.textContent).toContain("Jul 18, 2026");
  });

  it("reads a callee's result by its call path and says how it is reached", async () => {
    const callee = instance(
      "resize-1",
      {},
      { graph_id: "graph-invoices", call_path: ["call-invoices"] },
    );
    storedResults([
      {
        owner: callee,
        outputs: { tables: tableValue("artifact-inside-call") },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });

    const { container } = await renderDrawer();

    expect(apiMocks.getInstanceResult).toHaveBeenCalledWith(
      "workspace-1",
      PROJECT_ID,
      {
        graph_id: "graph-invoices",
        node_id: "resize-1",
        call_path: ["call-invoices"],
      },
    );
    expect(rowFor(container, "artifact-inside-call")).toBeDefined();
    // The call nodes that reach the instance are named.
    expect(container.textContent).toContain("via Invoices");
  });

  it("reads nothing for a group until it is opened, and hides it again when closed", async () => {
    storedResults([
      {
        owner: instance("resize-1"),
        outputs: { tables: tableValue("artifact-resized") },
      },
      {
        owner: instance("summarize-1"),
        outputs: { tables: tableValue("artifact-summary") },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });

    const { container } = await renderDrawer();

    // A closed group is a name and a state, not a read.
    expect(apiMocks.getInstanceResult).toHaveBeenCalledTimes(1);
    expect(
      container.querySelector('[data-artifact-row="artifact-summary"]'),
    ).toBeNull();

    await React.act(async () => {
      buttonContaining(container, "Summarize").click();
    });

    expect(apiMocks.getInstanceResult).toHaveBeenCalledTimes(2);
    expect(rowFor(container, "artifact-summary")).toBeDefined();

    await React.act(async () => {
      buttonContaining(container, "Summarize").click();
    });

    expect(
      container.querySelector('[data-artifact-row="artifact-summary"]'),
    ).toBeNull();
  });

  it("passes over an instance with nothing stored, and says so when none stored", async () => {
    apiMocks.listGraphInstances.mockResolvedValue({
      instances: [pendingInstance("resize-1")],
    });
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });

    const { container } = await renderDrawer();

    expect(container.textContent).toContain("No node of this Graph has stored");
    expect(apiMocks.getInstanceResult).not.toHaveBeenCalled();
  });

  it("says an open Graph is needed before any result can be read", async () => {
    const { container } = await renderDrawer({ graphId: null });

    expect(container.textContent).toContain("Open a Graph to browse");
    expect(apiMocks.listGraphInstances).not.toHaveBeenCalled();
    // No Graph means no rows, so the Library is not read either.
    expect(apiMocks.listLibraryArtifacts).not.toHaveBeenCalled();
  });

  it("saves a result by its instance identity and marks the row saved", async () => {
    const saved: LibraryItem[] = [];
    storedResults([
      {
        owner: instance("resize-1"),
        outputs: { tables: tableValue("artifact-resized") },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockImplementation(async () => ({
      items: [...saved],
    }));
    apiMocks.saveInstanceArtifactToLibrary.mockImplementation(
      async (_workspaceId, body) => {
        const existing = saved.find(
          (item) => item.artifact.artifact_id === "artifact-resized",
        );
        if (existing) return existing;
        const item = libraryItem("artifact-resized", body.name);
        saved.push(item);
        return item;
      },
    );

    const { container } = await renderDrawer();
    const row = rowFor(container, "artifact-resized");
    expect(row.textContent).not.toContain("saved");

    await saveWithDefaultName(row);

    expect(apiMocks.saveInstanceArtifactToLibrary).toHaveBeenCalledWith(
      "workspace-1",
      {
        project_id: PROJECT_ID,
        graph_id: GRAPH_ID,
        node_id: "resize-1",
        output_port: "tables",
        name: "Table",
        result_fingerprint: "result-resize-1",
        call_path: [],
      },
    );
    // The row stays in Generated; the same artifact now also sits in the Library.
    expect(rowFor(container, "artifact-resized").textContent).toContain(
      "saved",
    );
  });

  it("saves one item of a sequence output by its index", async () => {
    storedResults([
      {
        owner: instance("resize-1"),
        outputs: {
          tables: {
            artifact_type: "table.data",
            schema_version: 1,
            index_key: "order_index",
            ordered: true,
            item_refs: [refOf("artifact-a"), refOf("artifact-b")],
          },
        },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    apiMocks.saveInstanceArtifactToLibrary.mockResolvedValue(
      libraryItem("artifact-b"),
    );

    const { container } = await renderDrawer();

    expect(rowFor(container, "artifact-b").textContent).toContain("tables[1]");

    await saveWithDefaultName(rowFor(container, "artifact-b"));

    expect(apiMocks.saveInstanceArtifactToLibrary).toHaveBeenCalledWith(
      "workspace-1",
      expect.objectContaining({
        output_port: "tables",
        item_index: 1,
        result_fingerprint: "result-resize-1",
      }),
    );
  });

  it("keeps one Library item and the saved badge when the same result is saved twice", async () => {
    const saved: LibraryItem[] = [];
    storedResults([
      {
        owner: instance("resize-1"),
        outputs: { tables: tableValue("artifact-resized") },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockImplementation(async () => ({
      items: [...saved],
    }));
    apiMocks.saveInstanceArtifactToLibrary.mockImplementation(
      async (_workspaceId, body) => {
        const existing = saved.find(
          (item) => item.artifact.artifact_id === "artifact-resized",
        );
        if (existing) return existing;
        const item = libraryItem("artifact-resized", body.name);
        saved.push(item);
        return item;
      },
    );

    const { container } = await renderDrawer();
    const clickSave = async () => {
      await saveWithDefaultName(rowFor(container, "artifact-resized"));
    };
    await clickSave();
    await clickSave();

    expect(apiMocks.saveInstanceArtifactToLibrary).toHaveBeenCalledTimes(2);
    expect(saved).toHaveLength(1);
    expect(
      container.querySelectorAll('[data-artifact-row="artifact-resized"]'),
    ).toHaveLength(1);
    expect(
      [
        ...container.querySelectorAll('[aria-label="Generated artifacts"] *'),
      ].filter((node) => node.textContent?.trim() === "saved"),
    ).toHaveLength(1);
  });

  it("writes the same artifact drop payload a Library row writes", async () => {
    storedResults([
      {
        owner: instance("resize-1"),
        outputs: { tables: tableValue("artifact-resized") },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });

    const { container } = await renderDrawer();

    expect(dragPayload(rowFor(container, "artifact-resized"))).toEqual({
      value: {
        artifact_id: "artifact-resized",
        artifact_type: "table.data",
        schema_version: 1,
        content_hash: "sha-artifact-resized",
      },
      shape: "one",
    });
  });

  it("keeps the ingest notice on a blob row", async () => {
    storedResults([
      {
        owner: instance("resize-1"),
        outputs: {
          file: {
            artifact_id: "artifact-blob",
            artifact_type: "file.blob",
            schema_version: 1,
            content_hash: null,
          },
        },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });

    const { container } = await renderDrawer();

    expect(container.textContent).toContain(
      "Format not recognized, stored as a blob.",
    );
    expect(rowFor(container, "artifact-blob").textContent).toContain(
      "Unrecognized file",
    );
  });

  it("says how far a stale result has fallen behind", async () => {
    storedResults([
      {
        owner: instance("resize-1", {
          state: "stale",
          last_result_fingerprint: "result-old",
        }),
        outputs: { tables: tableValue("artifact-old") },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });

    const { container } = await renderDrawer();

    expect(rowFor(container, "artifact-old")).toBeDefined();
    expect(container.textContent).toContain(
      "The node changed after this result was stored",
    );
  });

  it("names the failure beside a result that a failed attempt left behind", async () => {
    storedResults([
      {
        owner: instance("resize-1", {
          state: "failed",
          error: "the resize service refused the request",
        }),
        outputs: { tables: tableValue("artifact-old") },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });

    const { container } = await renderDrawer();

    expect(container.textContent).toContain("Failed");
    expect(container.textContent).toContain("the resize service refused");
    // What it last produced is still readable.
    expect(rowFor(container, "artifact-old")).toBeDefined();
  });

  it("re-reads the Graph's instances when the shell says a result may have changed", async () => {
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    apiMocks.listGraphInstances.mockResolvedValueOnce({ instances: [] });
    storedResults([
      {
        owner: instance("resize-1"),
        outputs: { tables: tableValue("artifact-resized") },
      },
    ]);

    const { container, rerender } = await renderDrawer({ refreshToken: 0 });
    expect(container.textContent).toContain("No node of this Graph has stored");

    await rerender({ refreshToken: 1 });

    expect(rowFor(container, "artifact-resized")).toBeDefined();
  });

  it("reports a refused save without dropping the row", async () => {
    storedResults([
      {
        owner: instance("resize-1"),
        outputs: { tables: tableValue("artifact-resized") },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    apiMocks.saveInstanceArtifactToLibrary.mockRejectedValue(
      new Error("Node result 'result-resize-1' does not have that output"),
    );

    const { container } = await renderDrawer();
    await saveWithDefaultName(rowFor(container, "artifact-resized"));

    expect(container.textContent).toContain(
      "Node result 'result-resize-1' does not have that output",
    );
    expect(rowFor(container, "artifact-resized")).toBeDefined();
  });

  it("offers no working Save without edit access", async () => {
    storedResults([
      {
        owner: instance("resize-1"),
        outputs: { tables: tableValue("artifact-resized") },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });

    const { container } = await renderDrawer({ canSave: false });
    const save = saveIn(rowFor(container, "artifact-resized"));

    expect(save.disabled).toBe(true);
    expect(save.title).toBe("Saving into the Library needs edit access");
    await React.act(async () => {
      save.click();
    });
    expect(apiMocks.saveInstanceArtifactToLibrary).not.toHaveBeenCalled();
  });

  it("asks for a name in a dialog, defaulting to the artifact label", async () => {
    storedResults([
      {
        owner: instance("resize-1"),
        outputs: { tables: tableValue("artifact-resized") },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    apiMocks.saveInstanceArtifactToLibrary.mockResolvedValue(
      libraryItem("artifact-resized"),
    );
    const { container } = await renderDrawer();

    await React.act(async () => {
      buttonNamed(container, "Save").click();
    });

    const input = libraryNameInput();
    expect(document.body.textContent).toContain("Save Table into the Library");
    expect(input.value).toBe("Table");
    expect(apiMocks.saveInstanceArtifactToLibrary).not.toHaveBeenCalled();

    await submitLibraryName(input, "  Report name  ");

    expect(apiMocks.saveInstanceArtifactToLibrary).toHaveBeenCalledWith(
      "workspace-1",
      expect.objectContaining({ name: "Report name" }),
    );
  });

  it("keeps the row when naming is cancelled", async () => {
    storedResults([
      {
        owner: instance("resize-1"),
        outputs: { tables: tableValue("artifact-resized") },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    const { container } = await renderDrawer();

    await React.act(async () => buttonNamed(container, "Save").click());
    await React.act(async () => buttonNamed(document.body, "Cancel").click());

    expect(document.querySelector('input[aria-label="Library name"]')).toBe(
      null,
    );
    expect(rowFor(container, "artifact-resized")).toBeDefined();
    expect(apiMocks.saveInstanceArtifactToLibrary).not.toHaveBeenCalled();
  });

  it("keeps the listed results when refreshing them fails, and reads again on request", async () => {
    storedResults([
      {
        owner: instance("resize-1"),
        outputs: { tables: tableValue("artifact-resized") },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    apiMocks.listGraphInstances.mockResolvedValueOnce({
      instances: [instance("resize-1")],
    });

    const { container } = await renderDrawer();
    expect(rowFor(container, "artifact-resized")).toBeDefined();

    apiMocks.listGraphInstances.mockRejectedValueOnce(
      new Error("the results are offline"),
    );
    await React.act(async () => {
      buttonNamed(container, "Refresh Generated artifacts").click();
    });

    // The read failed, the rows did not: what was on screen is still there.
    expect(rowFor(container, "artifact-resized")).toBeDefined();
    const notice = alertMentioning(container, "the results are offline");
    expect(notice.textContent).toContain("last successful read");
    // Asking again re-reads the list, and a good read clears the notice.
    const before = apiMocks.listGraphInstances.mock.calls.length;
    apiMocks.listGraphInstances.mockResolvedValueOnce({
      instances: [instance("resize-1")],
    });
    await React.act(async () => {
      buttonNamed(notice, "Try again").click();
    });

    expect(apiMocks.listGraphInstances.mock.calls.length).toBe(before + 1);
    expect(rowFor(container, "artifact-resized")).toBeDefined();
    expect(alerts(container)).toHaveLength(0);
  });

  it("reads the instances again when the first read fails", async () => {
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    apiMocks.listGraphInstances.mockRejectedValueOnce(
      new Error("the results are offline"),
    );

    const { container } = await renderDrawer();
    const notice = alertMentioning(container, "the results are offline");

    storedResults([
      {
        owner: instance("resize-1"),
        outputs: { tables: tableValue("artifact-resized") },
      },
    ]);
    await React.act(async () => {
      buttonNamed(notice, "Try again").click();
    });

    expect(rowFor(container, "artifact-resized")).toBeDefined();
    expect(alerts(container)).toHaveLength(0);
  });

  it("offers to read an instance again when its first read fails", async () => {
    apiMocks.listGraphInstances.mockResolvedValue({
      instances: [instance("resize-1")],
    });
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    apiMocks.getInstanceResult.mockRejectedValueOnce(
      new Error("this result is offline"),
    );

    const { container } = await renderDrawer();
    // Nothing was ever shown for this instance, so only the failure is on screen.
    expect(container.querySelector("[data-artifact-row]")).toBeNull();
    const notice = alertMentioning(container, "this result is offline");
    expect(notice.textContent).not.toContain("last successful read");

    apiMocks.getInstanceResult.mockResolvedValueOnce(
      result(instance("resize-1"), {
        tables: tableValue("artifact-resized"),
      }),
    );
    await React.act(async () => {
      buttonNamed(notice, "Try again").click();
    });

    expect(rowFor(container, "artifact-resized")).toBeDefined();
    expect(alerts(container)).toHaveLength(0);
  });

  it("keeps the rows already shown when reopening the panel cannot read them", async () => {
    storedResults([
      {
        owner: instance("resize-1"),
        outputs: { tables: tableValue("artifact-resized") },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });

    const cache = createSwrCache();
    const first = await renderDrawer({}, { cache });
    expect(rowFor(first.container, "artifact-resized")).toBeDefined();
    await first.unmount();

    apiMocks.getInstanceResult.mockRejectedValueOnce(
      new Error("this result is offline"),
    );
    const { container } = await renderDrawer({}, { cache });
    await nextFrame();

    expect(rowFor(container, "artifact-resized")).toBeDefined();
    const notice = alertMentioning(container, "this result is offline");
    expect(notice.textContent).toContain("last successful read");

    apiMocks.getInstanceResult.mockResolvedValueOnce(
      result(instance("resize-1"), {
        tables: tableValue("artifact-resized"),
      }),
    );
    const before = apiMocks.getInstanceResult.mock.calls.length;
    await React.act(async () => {
      buttonNamed(notice, "Try again").click();
    });

    expect(apiMocks.getInstanceResult.mock.calls.length).toBe(before + 1);
    expect(alerts(container)).toHaveLength(0);
  });

  it("closes the panel through its own control", async () => {
    storedResults([
      {
        owner: instance("resize-1"),
        outputs: { tables: tableValue("artifact-resized") },
      },
    ]);
    apiMocks.listLibraryArtifacts.mockResolvedValue({ items: [] });
    const onClose = vi.fn();

    const { container } = await renderDrawer({ onClose });

    await React.act(async () => {
      buttonNamed(container, "Close Generated artifacts").click();
    });

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

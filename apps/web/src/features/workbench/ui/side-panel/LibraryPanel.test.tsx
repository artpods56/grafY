// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LibraryPanel } from "./LibraryPanel";
import type { LibraryItem } from "@/lib/api";

const listLibraryArtifacts = vi.hoisted(() => vi.fn());
const uploadFile = vi.hoisted(() => vi.fn());
const saveUploadedArtifactToLibrary = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({
  listLibraryArtifacts,
  uploadFile,
  saveUploadedArtifactToLibrary,
  artifactContentUrl: (
    _workspaceId: string,
    contentUrl: string | null | undefined,
  ) => (contentUrl ? `/api/v1/${contentUrl}` : null),
}));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const RUN_ITEM: LibraryItem = {
  artifact: {
    artifact_id: "artifact-run",
    artifact_type: "table.data",
    schema_version: 1,
    content_type: "application/json",
    byte_size: 2048,
    sha256: "abcdef1234567890",
    content_url: "./artifacts/artifact-run/content",
    download_formats: [],
    metadata: {},
  },
  name: "sales-table",
  provenance: {
    source: "run",
    saved_at: "2026-09-11T12:00:00Z",
    graph_id: "graph-1",
    graph_title: "Sales",
    node_id: "resize-1",
    node_title: "Resize",
    graph_revision: 4,
    execution_id: "execution-1",
  },
  run: {
    execution_id: "execution-1",
    graph_id: "graph-1",
    finished_at: "2026-09-11T11:59:00Z",
  },
};

const UPLOAD_ITEM: LibraryItem = {
  artifact: {
    artifact_id: "artifact-upload",
    artifact_type: "file.jpeg",
    schema_version: 1,
    content_type: "image/jpeg",
    byte_size: 2_684_354_560,
    sha256: null,
    content_url: "./artifacts/artifact-upload/content",
    download_formats: [],
    metadata: {},
  },
  name: "PNG image",
  provenance: {
    source: "upload",
    saved_at: "2026-09-11T12:00:00Z",
    original_filename: "harbour-front.jpg",
  },
  run: null,
};

const BLOB_ITEM: LibraryItem = {
  artifact: {
    artifact_id: "artifact-blob",
    artifact_type: "file.blob",
    schema_version: 1,
    content_type: "application/octet-stream",
    byte_size: null,
    sha256: null,
    content_url: "./artifacts/artifact-blob/content",
    download_formats: [],
    metadata: {},
  },
  name: "scan.unknown",
  provenance: {
    source: "upload",
    saved_at: "2026-09-11T12:00:00Z",
    original_filename: "scan.unknown",
  },
  run: null,
};

const roots: ReturnType<typeof createRoot>[] = [];

function row(label: string): HTMLElement {
  const found = [
    ...document.querySelectorAll<HTMLElement>("[data-tree-key]"),
  ].find((element) => element.dataset.treeLabel === label);
  if (!found) throw new Error(`No tree row named ${label}`);
  return found;
}

function folderRow(id: string): HTMLElement {
  const found = document.querySelector<HTMLElement>(
    `[data-tree-key="folder:${id}"]`,
  );
  if (!found) throw new Error(`No folder row ${id}`);
  return found;
}

function dropRegion(): HTMLElement {
  const region = document.querySelector<HTMLElement>(
    '[aria-label="Workspace Library files"]',
  );
  if (!region) throw new Error("No Library file drop region");
  return region;
}

function press(element: HTMLElement, key: string): void {
  element.dispatchEvent(
    new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
  );
}

function dropFiles(target: HTMLElement, files: File[]): void {
  const dataTransfer = {
    files,
    types: ["Files"],
    dropEffect: "copy",
    effectAllowed: "all",
  };
  for (const type of ["dragenter", "dragover", "drop"]) {
    const event = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", { value: dataTransfer });
    target.dispatchEvent(event);
  }
}

/** jsdom's storage is shadowed by Node's experimental one, so provide our own. */
function installMemoryStorage(): Map<string, string> {
  const store = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => store.clear(),
  });
  return store;
}

let workspaceCounter = 0;

async function renderPanel(
  items: LibraryItem[],
  onOpenRun = vi.fn(),
): Promise<{ onOpenRun: ReturnType<typeof vi.fn>; workspaceId: string }> {
  listLibraryArtifacts.mockResolvedValue({ items });
  workspaceCounter += 1;
  const workspaceId = `workspace-${workspaceCounter}`;
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  await React.act(async () => {
    root.render(<LibraryPanel workspaceId={workspaceId} onOpenRun={onOpenRun} />);
  });
  await React.act(async () => {
    await vi.waitFor(() =>
      expect(document.body.textContent).not.toContain("Loading the Library"),
    );
  });
  return { onOpenRun, workspaceId };
}

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  document.body.replaceChildren();
  vi.unstubAllGlobals();
  listLibraryArtifacts.mockReset();
  uploadFile.mockReset();
  saveUploadedArtifactToLibrary.mockReset();
});

describe("LibraryPanel", () => {
  beforeEach(() => {
    installMemoryStorage();
  });

  it("shows the five standing folders of an empty Library", async () => {
    await renderPanel([]);

    expect(
      [...document.querySelectorAll<HTMLElement>("[data-tree-key]")].map(
        (element) => element.dataset.treeLabel,
      ),
    ).toEqual(["images", "tables", "text", "models", "other"]);
    expect(document.body.textContent).toContain("The Library is empty");
    expect(document.body.textContent).toContain("0 artifacts");
  });

  it("files each artifact under its type folder", async () => {
    await renderPanel([RUN_ITEM, UPLOAD_ITEM, BLOB_ITEM]);

    expect(folderRow("images").getAttribute("aria-expanded")).toBe("true");
    expect(row("harbour-front.jpg").closest('[role="group"]')).not.toBeNull();
    expect(row("sales-table").getAttribute("aria-level")).toBe("2");
    expect(document.body.textContent).toContain("2.5 GB · uploaded");
  });

  it("writes the typed artifact drag payload from a file row", async () => {
    await renderPanel([RUN_ITEM]);
    const dataTransfer = { setData: vi.fn(), effectAllowed: "" };
    const event = new Event("dragstart", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", { value: dataTransfer });
    row("sales-table").dispatchEvent(event);

    expect(dataTransfer.effectAllowed).toBe("copy");
    expect(dataTransfer.setData).toHaveBeenCalledWith(
      "application/x-grafy-artifact",
      JSON.stringify({
        value: {
          artifact_id: "artifact-run",
          artifact_type: "table.data",
          schema_version: 1,
          content_hash: "abcdef1234567890",
        },
        shape: "one",
      }),
    );
  });

  it("keeps the provenance line and the run link in the inspector", async () => {
    const { onOpenRun } = await renderPanel([RUN_ITEM, UPLOAD_ITEM]);

    await React.act(async () => {
      row("sales-table").click();
    });

    const inspector = document.querySelector('[aria-label="Selected artifact"]');
    expect(inspector?.textContent).toContain(
      "Sales · Resize · revision 4 · from a run",
    );
    expect(inspector?.textContent).toContain("table.data@1 · abcdef123456");

    const link = [...document.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Execution history"),
    );
    await React.act(async () => {
      link?.click();
    });
    expect(onOpenRun).toHaveBeenCalledWith("graph-1", "execution-1");

    await React.act(async () => {
      row("harbour-front.jpg").click();
    });
    expect(
      [...document.querySelectorAll("button")].some((button) =>
        button.textContent?.includes("Execution history"),
      ),
    ).toBe(false);
  });

  it("keeps the blob ingest notice on a blob row", async () => {
    await renderPanel([BLOB_ITEM]);

    expect(document.body.textContent).toContain(
      "Format not recognized, stored as a blob.",
    );
  });

  it("falls back to the folder icon when a thumbnail cannot load", async () => {
    await renderPanel([UPLOAD_ITEM]);
    const thumbnail = row("harbour-front.jpg").querySelector("img");
    expect(thumbnail?.getAttribute("src")).toContain(
      "/artifacts/artifact-upload/content",
    );

    await React.act(async () => {
      thumbnail?.dispatchEvent(new Event("error"));
    });

    expect(
      row("harbour-front.jpg").querySelector("img"),
    ).toBeNull();
  });

  it("collapses a folder and remembers the choice", async () => {
    await renderPanel([RUN_ITEM]);

    await React.act(async () => {
      folderRow("tables").click();
    });

    expect(folderRow("tables").getAttribute("aria-expanded")).toBe("false");
    expect(
      window.localStorage.getItem("grafy-library-folders-collapsed"),
    ).toContain("folder:tables");
    expect(document.querySelector("[data-tree-key='file:artifact-run']")).toBe(
      null,
    );
  });

  it("reopens a collapsed folder and drops the stored exception", async () => {
    await renderPanel([RUN_ITEM]);

    await React.act(async () => {
      folderRow("tables").click();
    });
    await React.act(async () => {
      folderRow("tables").click();
    });

    expect(folderRow("tables").getAttribute("aria-expanded")).toBe("true");
    expect(
      window.localStorage.getItem("grafy-library-folders-collapsed"),
    ).not.toContain("folder:tables");
    expect(
      document.querySelector("[data-tree-key='file:artifact-run']"),
    ).not.toBeNull();
  });

  it("filters the tree and hides the folders with no match", async () => {
    await renderPanel([RUN_ITEM, UPLOAD_ITEM]);
    const filter = document.querySelector<HTMLInputElement>(
      'input[aria-label="Filter Library artifacts"]',
    );

    await React.act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!;
      setter.call(filter, "harbour");
      filter?.dispatchEvent(new Event("input", { bubbles: true }));
    });

    expect(row("harbour-front.jpg")).toBeDefined();
    expect(document.querySelector("[data-tree-key='folder:tables']")).toBeNull();
    expect(document.body.textContent).toContain("images");
  });

  it("uploads files dropped anywhere in the panel", async () => {
    uploadFile.mockResolvedValue({
      artifact_id: "artifact-new",
      filename: "notes.txt",
    });
    saveUploadedArtifactToLibrary.mockResolvedValue({});
    const { workspaceId } = await renderPanel([]);

    await React.act(async () => {
      dropFiles(dropRegion(), [new File(["a"], "notes.txt")]);
    });
    await React.act(async () => {
      await vi.waitFor(() =>
        expect(saveUploadedArtifactToLibrary).toHaveBeenCalledWith(workspaceId, {
          artifact_id: "artifact-new",
          original_filename: "notes.txt",
        }),
      );
    });
  });

  it("walks the tree with the keyboard", async () => {
    await renderPanel([RUN_ITEM, UPLOAD_ITEM]);
    const images = folderRow("images");
    images.focus();

    await React.act(async () => {
      press(images, "ArrowLeft");
    });
    expect(folderRow("images").getAttribute("aria-expanded")).toBe("false");

    await React.act(async () => {
      press(folderRow("images"), "ArrowRight");
    });
    expect(folderRow("images").getAttribute("aria-expanded")).toBe("true");

    await React.act(async () => {
      press(document.activeElement as HTMLElement, "ArrowDown");
    });
    expect(document.activeElement).toBe(row("harbour-front.jpg"));

    await React.act(async () => {
      press(document.activeElement as HTMLElement, "ArrowDown");
    });
    expect(document.activeElement).toBe(folderRow("tables"));

    await React.act(async () => {
      press(document.activeElement as HTMLElement, "End");
    });
    expect(document.activeElement).toBe(folderRow("other"));

    await React.act(async () => {
      row("sales-table").focus();
      press(row("sales-table"), "ArrowLeft");
    });
    expect(document.activeElement).toBe(folderRow("tables"));
  });

  it("selects one row at a time with the pointer", async () => {
    await renderPanel([RUN_ITEM, UPLOAD_ITEM]);

    await React.act(async () => {
      row("sales-table").click();
    });
    expect(row("sales-table").getAttribute("aria-selected")).toBe("true");

    await React.act(async () => {
      row("harbour-front.jpg").click();
    });
    expect(row("sales-table").getAttribute("aria-selected")).toBe("false");
    expect(row("harbour-front.jpg").getAttribute("aria-selected")).toBe("true");
  });
});

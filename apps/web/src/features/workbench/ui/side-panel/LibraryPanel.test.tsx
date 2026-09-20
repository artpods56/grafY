// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LibraryPanel } from "./LibraryPanel";
import { BLOB_ARTIFACT_NOTICE } from "../../model/blob-notice";
import type { LibraryFolder, PlacedLibraryItem } from "@/lib/api";

const listTree = vi.hoisted(() => vi.fn());
const createFolder = vi.hoisted(() => vi.fn());
const renameFolder = vi.hoisted(() => vi.fn());
const deleteFolder = vi.hoisted(() => vi.fn());
const moveFolder = vi.hoisted(() => vi.fn());
const moveItems = vi.hoisted(() => vi.fn());
const uploadFile = vi.hoisted(() => vi.fn());
const saveUploadedArtifactToLibrary = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@/lib/api");
  return {
    ...actual,
    libraryFoldersApi: {
      listTree,
      createFolder,
      renameFolder,
      deleteFolder,
      moveFolder,
      moveItems,
    },
    uploadFile,
    saveUploadedArtifactToLibrary,
    artifactContentUrl: (
      _workspaceId: string,
      contentUrl: string | null | undefined,
    ) => (contentUrl ? `/api/v1/${contentUrl}` : null),
  };
});

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const FIELDWORK: LibraryFolder = {
  folder_id: "fieldwork",
  workspace_id: "workspace",
  parent_id: null,
  name: "Fieldwork",
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

const SEPTEMBER: LibraryFolder = {
  ...FIELDWORK,
  folder_id: "september",
  parent_id: "fieldwork",
  name: "September",
};

const EMPTY_FOLDER: LibraryFolder = {
  ...FIELDWORK,
  folder_id: "archive",
  name: "Archive",
};

const RUN_ITEM: PlacedLibraryItem = {
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
  folder_id: "september",
};

const UPLOAD_ITEM: PlacedLibraryItem = {
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
  folder_id: null,
};

const BLOB_ITEM: PlacedLibraryItem = {
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
  folder_id: null,
};

const roots: ReturnType<typeof createRoot>[] = [];

function rows(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>("[data-tree-key]")];
}

function folderRow(id: string): HTMLElement {
  const found = document.querySelector<HTMLElement>(
    `[data-tree-key="folder:${id}"]`,
  );
  if (!found) throw new Error(`No folder row ${id}`);
  return found;
}

function fileRow(id: string): HTMLElement {
  const found = document.querySelector<HTMLElement>(
    `[data-tree-key="file:${id}"]`,
  );
  if (!found) throw new Error(`No file row ${id}`);
  return found;
}

function dropRegion(): HTMLElement {
  const region = document.querySelector<HTMLElement>(
    '[aria-label="Workspace Library files"]',
  );
  if (!region) throw new Error("No Library file drop region");
  return region;
}

/** React tracks input values, so a controlled input only changes through its setter. */
function typeInto(input: HTMLInputElement, value: string): void {
  const setValue = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!;
  setValue.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function press(element: HTMLElement, key: string): void {
  element.dispatchEvent(
    new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
  );
}

/**
 * A drop with the payload shape the real drag carries. jsdom has no
 * DataTransfer, and the tree only ever reads `types` and `getData`.
 */
function dropPayload(target: HTMLElement, data: Record<string, string>): void {
  const dataTransfer = {
    files: [],
    types: Object.keys(data),
    getData: (type: string) => data[type] ?? "",
    setData: () => {},
    dropEffect: "move",
    effectAllowed: "all",
  };
  const event = new Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "dataTransfer", { value: dataTransfer });
  target.dispatchEvent(event);
}

function dropFiles(target: HTMLElement, files: File[]): void {
  const dataTransfer = {
    files,
    types: ["Files"],
    getData: () => "",
    setData: () => {},
    dropEffect: "copy",
    effectAllowed: "all",
  };
  for (const type of ["dragenter", "dragover", "drop"]) {
    const event = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", { value: dataTransfer });
    target.dispatchEvent(event);
  }
}

const ARTIFACT_DROP_TYPE = "application/x-grafy-artifact";
const FOLDER_DROP_TYPE = "application/x-grafy-library-folder";

function artifactDropValue(artifactId: string): string {
  return JSON.stringify({
    value: {
      artifact_id: artifactId,
      artifact_type: "file.png",
      schema_version: 1,
      content_hash: null,
    },
    shape: "one",
  });
}

/** jsdom's storage is shadowed by Node's experimental one, so provide our own. */
function installMemoryStorage(): void {
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
}

let workspaceCounter = 0;

async function renderPanel(
  tree: { folders: LibraryFolder[]; items: PlacedLibraryItem[] },
  onOpenRun = vi.fn(),
): Promise<{ onOpenRun: ReturnType<typeof vi.fn>; workspaceId: string }> {
  listTree.mockResolvedValue(tree);
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
  for (const call of [
    listTree,
    createFolder,
    renameFolder,
    deleteFolder,
    moveFolder,
    moveItems,
    uploadFile,
    saveUploadedArtifactToLibrary,
  ]) {
    call.mockReset();
  }
});

describe("LibraryPanel", () => {
  beforeEach(() => {
    installMemoryStorage();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ text: async () => "plot(x),y(x)\n1,2\n" })),
    );
  });

  it("paints the user's folders and the artifacts filed in them", async () => {
    await renderPanel({
      folders: [FIELDWORK, SEPTEMBER, EMPTY_FOLDER],
      items: [RUN_ITEM, UPLOAD_ITEM],
    });

    expect(rows().map((element) => element.dataset.treeLabel)).toEqual([
      "Archive",
      "Fieldwork",
      "September",
      "sales-table",
      "harbour-front.jpg",
    ]);
    expect(folderRow("fieldwork").getAttribute("aria-expanded")).toBe("true");
    expect(folderRow("fieldwork").textContent).toContain("1");
    expect(folderRow("archive").textContent).toContain("0");
  });

  it("marks where an artifact sits in the tree", async () => {
    await renderPanel({
      folders: [FIELDWORK, SEPTEMBER],
      items: [RUN_ITEM],
    });

    expect(fileRow("artifact-run").getAttribute("aria-level")).toBe("3");
    expect(folderRow("fieldwork").getAttribute("aria-level")).toBe("1");
  });

  it("says the Library is empty when there is nothing to file", async () => {
    await renderPanel({ folders: [], items: [] });

    expect(document.body.textContent).toContain("The Library is empty");
    expect(document.body.textContent).toContain("0 artifacts · 0 folders");
  });

  it("folds a folder away and remembers it", async () => {
    await renderPanel({
      folders: [FIELDWORK, SEPTEMBER],
      items: [RUN_ITEM],
    });

    await React.act(async () => {
      folderRow("fieldwork").click();
    });
    expect(document.querySelector('[data-tree-key="folder:september"]')).toBeNull();

    await React.act(async () => {
      folderRow("fieldwork").click();
    });
    expect(
      document.querySelector('[data-tree-key="folder:september"]'),
    ).not.toBeNull();
  });

  it("makes a folder from the toolbar and names it on the spot", async () => {
    createFolder.mockResolvedValue({ ...EMPTY_FOLDER, name: "New folder" });

    await renderPanel({ folders: [], items: [] });
    await React.act(async () => {
      document
        .querySelector<HTMLElement>('[aria-label="New folder"]')!
        .click();
    });

    expect(createFolder).toHaveBeenCalledWith({
      workspaceId: expect.any(String),
      name: "New folder",
      parentId: null,
    });
    expect(createFolder.mock.calls.length).toBe(1);
  });

  it("renames a folder with F2 and sends the new name", async () => {
    renameFolder.mockResolvedValue({ ...EMPTY_FOLDER, name: "Cold store" });

    await renderPanel({ folders: [EMPTY_FOLDER], items: [] });

    await React.act(async () => {
      folderRow("archive").focus();
      press(folderRow("archive"), "F2");
    });
    const input = document.querySelector<HTMLInputElement>(
      'input[aria-label="Folder name"]',
    );
    expect(input).not.toBeNull();

    await React.act(async () => {
      typeInto(input!, "Cold store");
    });
    await React.act(async () => {
      press(input!, "Enter");
    });

    expect(renameFolder).toHaveBeenCalledWith({
      workspaceId: expect.any(String),
      folderId: "archive",
      name: "Cold store",
    });
  });

  it("keeps the keyboard inside the tree", async () => {
    await renderPanel({
      folders: [FIELDWORK, SEPTEMBER],
      items: [RUN_ITEM],
    });

    await React.act(async () => {
      fileRow("artifact-run").focus();
      press(fileRow("artifact-run"), "ArrowLeft");
    });
    expect(document.activeElement).toBe(folderRow("september"));

    // A folder closes before the keyboard walks out of it, as in a file tree.
    await React.act(async () => {
      press(folderRow("september"), "ArrowLeft");
    });
    expect(folderRow("september").getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(folderRow("september"));

    await React.act(async () => {
      press(folderRow("september"), "ArrowLeft");
    });
    expect(document.activeElement).toBe(folderRow("fieldwork"));
  });

  it("filters the tree, not just the rows", async () => {
    await renderPanel({
      folders: [FIELDWORK, EMPTY_FOLDER],
      items: [RUN_ITEM, UPLOAD_ITEM],
    });

    const filter = document.querySelector<HTMLInputElement>(
      'input[aria-label="Filter the Library"]',
    )!;
    await React.act(async () => {
      typeInto(filter, "harbour");
    });

    expect(rows().map((element) => element.dataset.treeLabel)).toEqual([
      "harbour-front.jpg",
    ]);
  });

  it("files an artifact dropped on a folder", async () => {
    moveItems.mockResolvedValue(undefined);

    await renderPanel({ folders: [FIELDWORK], items: [UPLOAD_ITEM] });

    await React.act(async () => {
      dropPayload(folderRow("fieldwork"), {
        [ARTIFACT_DROP_TYPE]: artifactDropValue("artifact-upload"),
      });
    });

    expect(moveItems).toHaveBeenCalledWith({
      workspaceId: expect.any(String),
      artifactIds: ["artifact-upload"],
      folderId: "fieldwork",
    });
  });

  it("moves a folder dropped inside another folder", async () => {
    moveFolder.mockResolvedValue({ ...EMPTY_FOLDER, parent_id: "fieldwork" });

    await renderPanel({ folders: [FIELDWORK, EMPTY_FOLDER], items: [] });

    await React.act(async () => {
      dropPayload(folderRow("fieldwork"), { [FOLDER_DROP_TYPE]: "archive" });
    });

    expect(moveFolder).toHaveBeenCalledWith({
      workspaceId: expect.any(String),
      folderId: "archive",
      parentId: "fieldwork",
    });
  });

  it("uploads files dropped on a folder straight into it", async () => {
    uploadFile.mockResolvedValue({ artifact_id: "artifact-new", filename: "core.png" });
    saveUploadedArtifactToLibrary.mockResolvedValue({
      ...UPLOAD_ITEM,
      artifact: { ...UPLOAD_ITEM.artifact, artifact_id: "artifact-new" },
    });
    moveItems.mockResolvedValue(undefined);

    await renderPanel({ folders: [FIELDWORK], items: [] });

    await React.act(async () => {
      dropFiles(folderRow("fieldwork"), [new File(["x"], "core.png")]);
    });

    expect(saveUploadedArtifactToLibrary).toHaveBeenCalledWith(
      expect.any(String),
      { artifact_id: "artifact-new", original_filename: "core.png" },
    );
    expect(moveItems).toHaveBeenCalledWith({
      workspaceId: expect.any(String),
      artifactIds: ["artifact-new"],
      folderId: "fieldwork",
    });
  });

  it("frees an artifact dropped on the panel background", async () => {
    moveItems.mockResolvedValue(undefined);

    await renderPanel({ folders: [FIELDWORK], items: [RUN_ITEM] });

    await React.act(async () => {
      dropPayload(dropRegion(), {
        [ARTIFACT_DROP_TYPE]: artifactDropValue("artifact-run"),
      });
    });

    expect(moveItems).toHaveBeenCalledWith({
      workspaceId: expect.any(String),
      artifactIds: ["artifact-run"],
      folderId: null,
    });
  });

  it("previews the selected artifact on the tile under the browser", async () => {
    await renderPanel({ folders: [FIELDWORK, SEPTEMBER], items: [RUN_ITEM] });

    await React.act(async () => {
      fileRow("artifact-run").click();
    });

    const tile = document.querySelector<HTMLElement>('[aria-label="Selected artifact"]');
    expect(tile).not.toBeNull();
    expect(tile!.textContent).toContain("/Fieldwork/September");
    expect(tile!.textContent).toContain("Sales · Resize · revision 4 · from a run");
    expect(tile!.querySelector("pre")?.textContent).toContain("plot(x),y(x)");
  });

  it("opens the run a selected artifact came from", async () => {
    const { onOpenRun } = await renderPanel({
      folders: [FIELDWORK],
      items: [RUN_ITEM],
    });
    onOpenRun.mockClear();

    await React.act(async () => {
      fileRow("artifact-run").click();
    });
    await React.act(async () => {
      document
        .querySelector<HTMLElement>('[aria-label="Selected artifact"] button')!
        .click();
    });

    expect(onOpenRun).toHaveBeenCalledWith("graph-1", "execution-1");
  });

  it("falls back to the folder icon when a thumbnail cannot load", async () => {
    await renderPanel({ folders: [], items: [UPLOAD_ITEM] });

    const image = fileRow("artifact-upload").querySelector("img");
    expect(image).not.toBeNull();
    await React.act(async () => {
      image!.dispatchEvent(new Event("error", { bubbles: false }));
    });

    expect(fileRow("artifact-upload").querySelector("img")).toBeNull();
  });

  it("says an unreadable artifact will not open, without hiding the row", async () => {
    await renderPanel({ folders: [], items: [BLOB_ITEM] });

    expect(document.body.textContent).toContain("scan.unknown");
    expect(fileRow("artifact-blob").textContent).toContain(BLOB_ARTIFACT_NOTICE);
  });
});

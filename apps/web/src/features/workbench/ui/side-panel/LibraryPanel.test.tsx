// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LibraryPanel } from "./LibraryPanel";
import { BLOB_ARTIFACT_NOTICE } from "../../model/blob-notice";
import { ARTIFACT_GROUPS_DATA_TYPE } from "../../model/artifact-drop";
import { LIBRARY_MOVE_DATA_TYPE } from "./library-drag";
import {
  LibraryArtifactInUseError,
  LibraryFolderNotEmptyError,
  type LibraryFolder,
  type PlacedLibraryItem,
} from "@/lib/api";

const listTree = vi.hoisted(() => vi.fn());
const createFolder = vi.hoisted(() => vi.fn());
const renameFolder = vi.hoisted(() => vi.fn());
const deleteFolder = vi.hoisted(() => vi.fn());
const moveFolder = vi.hoisted(() => vi.fn());
const moveItems = vi.hoisted(() => vi.fn());
const deleteLibraryArtifact = vi.hoisted(() => vi.fn());
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
    deleteLibraryArtifact,
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
  defaultMarker: () => ({}),
  when: { ancestor: (pseudo: string) => pseudo },
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

const FOLDER_DROP_TYPE = "application/x-grafy-library-folder";

/**
 * Opens a folder's row menu and returns its Delete item so a test can state
 * whether the panel offered the delete. Base UI renders the menu in a portal on
 * `document.body`, never inside the row.
 */
async function deleteItemOfFolder(folderId: string): Promise<HTMLElement> {
  const label = folderRow(folderId).dataset.treeLabel ?? "";
  const trigger = folderRow(folderId).querySelector<HTMLElement>(
    `[aria-label="Actions for ${label}"]`,
  );
  if (!trigger) throw new Error(`No action trigger for folder ${folderId}`);
  await React.act(async () => {
    trigger.click();
  });
  const item = [
    ...document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
  ].find((element) => element.textContent?.startsWith("Delete folder"));
  if (!item) throw new Error(`No Delete item in the menu for ${folderId}`);
  return item;
}

/** The same for an artifact row, whose menu item names the Library. */
async function deleteItemOfArtifact(artifactId: string): Promise<HTMLElement> {
  const label = fileRow(artifactId).dataset.treeLabel ?? "";
  const trigger = fileRow(artifactId).querySelector<HTMLElement>(
    `[aria-label="Actions for ${label}"]`,
  );
  if (!trigger) throw new Error(`No action trigger for artifact ${artifactId}`);
  await React.act(async () => {
    trigger.click();
  });
  const item = [
    ...document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
  ].find((element) => element.textContent?.startsWith("Delete"));
  if (!item) throw new Error(`No Delete item in the menu for ${artifactId}`);
  return item;
}

/** The panel's delete confirmation, once it is up. */
function confirmDialog(): HTMLElement {
  const dialog = document.querySelector<HTMLElement>(
    '[role="dialog"], [role="alertdialog"]',
  );
  if (!dialog) throw new Error("No delete confirmation");
  return dialog;
}

function buttonIn(dialog: HTMLElement, label: string): HTMLElement {
  const button = [...dialog.querySelectorAll<HTMLElement>("button")].find(
    (element) => element.textContent?.trim() === label,
  );
  if (!button) throw new Error(`No ${label} button in the confirmation`);
  return button;
}

/** Opens the artifact menu, chooses Delete, and returns the confirmation. */
async function confirmArtifactDelete(artifactId: string): Promise<HTMLElement> {
  await selectMenuItem(await deleteItemOfArtifact(artifactId));
  await React.act(async () => {
    await vi.waitFor(() => expect(confirmDialog()).toBeDefined());
  });
  return confirmDialog();
}

/** Renders the same two-artifact Library most delete tests need, then asks. */
async function confirmArtifactDeleteViaRender(
  artifactId: string,
): Promise<HTMLElement> {
  await renderPanel({ folders: [FIELDWORK], items: [RUN_ITEM, UPLOAD_ITEM] });
  return confirmArtifactDelete(artifactId);
}

async function selectMenuItem(item: HTMLElement): Promise<void> {
  await React.act(async () => {
    item.click();
  });
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

function press(
  element: HTMLElement,
  key: string,
  modifiers: { shiftKey?: boolean; metaKey?: boolean } = {},
): void {
  element.dispatchEvent(
    new KeyboardEvent("keydown", {
      key,
      bubbles: true,
      cancelable: true,
      ...modifiers,
    }),
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
  panelProps: { canEdit?: boolean } = {},
): Promise<{ onOpenRun: ReturnType<typeof vi.fn>; workspaceId: string }> {
  listTree.mockResolvedValue(tree);
  workspaceCounter += 1;
  const workspaceId = `workspace-${workspaceCounter}`;
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  await React.act(async () => {
    root.render(
      <LibraryPanel
        workspaceId={workspaceId}
        onOpenRun={onOpenRun}
        canEdit={panelProps.canEdit}
      />,
    );
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
    deleteLibraryArtifact,
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
      vi.fn(async () => new Response("plot(x),y(x)\n1,2\n")),
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
    expect(
      document.querySelector('[data-tree-key="folder:september"]'),
    ).toBeNull();

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
      document.querySelector<HTMLElement>('[aria-label="New folder"]')!.click();
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

  it("refuses a folder delete and names what it still holds", async () => {
    deleteFolder.mockRejectedValue(new LibraryFolderNotEmptyError("fieldwork"));

    // Fieldwork holds nothing but the empty September folder, so its badge reads
    // 0 and the row offers Delete; the server counts the child folder instead.
    await renderPanel({ folders: [FIELDWORK, SEPTEMBER], items: [] });

    const deleteItem = await deleteItemOfFolder("fieldwork");
    expect(deleteItem.getAttribute("aria-disabled")).not.toBe("true");
    await selectMenuItem(deleteItem);

    await React.act(async () => {
      await vi.waitFor(() =>
        expect(document.body.textContent).toContain(
          "Move them out first — this folder still holds 1 folder.",
        ),
      );
    });
    expect(deleteFolder).toHaveBeenCalledWith({
      workspaceId: expect.any(String),
      folderId: "fieldwork",
    });
  });

  it("refuses a folder delete the panel cannot count", async () => {
    deleteFolder.mockRejectedValue(new LibraryFolderNotEmptyError("archive"));

    // The last listing saw Archive as empty, so there is no number to state —
    // another browser filed something in it. The refusal still says so.
    await renderPanel({ folders: [EMPTY_FOLDER], items: [] });

    await selectMenuItem(await deleteItemOfFolder("archive"));

    await React.act(async () => {
      await vi.waitFor(() =>
        expect(document.body.textContent).toContain(
          "Move them out first — this folder is not empty.",
        ),
      );
    });
    expect(document.body.textContent).not.toContain(
      "0 artifacts and 0 folders",
    );
  });

  it("names the artifact before it deletes anything", async () => {
    deleteLibraryArtifact.mockResolvedValue(undefined);

    const { workspaceId } = await renderPanel({
      folders: [FIELDWORK],
      items: [RUN_ITEM, UPLOAD_ITEM],
    });
    // Its tile is open, because a previewed artifact is the likeliest one to
    // decide against.
    await React.act(async () => {
      fileRow("artifact-upload").click();
    });

    const dialog = await confirmArtifactDelete("artifact-upload");

    // The row reads `harbour-front.jpg` because an upload is named by its file.
    expect(dialog.textContent).toContain("Delete harbour-front.jpg?");
    expect(deleteLibraryArtifact).not.toHaveBeenCalled();

    await React.act(async () => {
      buttonIn(dialog, "Delete").click();
    });

    expect(deleteLibraryArtifact).toHaveBeenCalledWith(
      workspaceId,
      "artifact-upload",
    );
    await React.act(async () => {
      await vi.waitFor(() =>
        expect(document.querySelector('[role="dialog"]')).toBeNull(),
      );
    });
    // The tree is reread the way every other Library change rereads it, and the
    // tile that was showing it goes with it.
    expect(listTree.mock.calls.length).toBeGreaterThan(1);
    expect(
      document.querySelector('[aria-label="Selected artifact"]'),
    ).toBeNull();
    expect(document.body.textContent).toContain("2 artifacts · 1 folder");
  });

  it("sends nothing when the artifact delete is answered Cancel", async () => {
    const dialog = await confirmArtifactDeleteViaRender("artifact-upload");

    await React.act(async () => {
      buttonIn(dialog, "Cancel").click();
    });

    expect(deleteLibraryArtifact).not.toHaveBeenCalled();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(fileRow("artifact-upload")).not.toBeNull();
  });

  it("shows the graphs the server named and keeps the artifact", async () => {
    deleteLibraryArtifact.mockRejectedValue(
      new LibraryArtifactInUseError(
        "artifact-run",
        "Still used by: Sales, Salt maps",
      ),
    );

    await renderPanel({ folders: [FIELDWORK], items: [RUN_ITEM, UPLOAD_ITEM] });
    await React.act(async () => {
      fileRow("artifact-run").click();
    });
    const dialog = await confirmArtifactDelete("artifact-run");

    await React.act(async () => {
      buttonIn(dialog, "Delete").click();
    });

    await React.act(async () => {
      await vi.waitFor(() =>
        expect(document.body.textContent).toContain(
          "Still used by: Sales, Salt maps",
        ),
      );
    });
    expect(fileRow("artifact-run")).not.toBeNull();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    // Nothing left, so the preview it was in stays open on the same artifact.
    expect(
      document.querySelector('[aria-label="Selected artifact"]'),
    ).not.toBeNull();
  });

  it("will not offer a delete to a member who cannot change the Library", async () => {
    await renderPanel({ folders: [], items: [UPLOAD_ITEM] }, vi.fn(), {
      canEdit: false,
    });

    const item = await deleteItemOfArtifact("artifact-upload");
    expect(item.getAttribute("aria-disabled")).toBe("true");
    expect(item.textContent).toContain("needs edit access");

    await selectMenuItem(item);
    expect(deleteLibraryArtifact).not.toHaveBeenCalled();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
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
    uploadFile.mockResolvedValue({
      artifact_id: "artifact-new",
      filename: "core.png",
    });
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

    const tile = document.querySelector<HTMLElement>(
      '[aria-label="Selected artifact"]',
    );
    expect(tile).not.toBeNull();
    expect(tile!.textContent).toContain("Library / Fieldwork / September");
    expect(tile!.textContent).toContain(
      "Sales · Resize · revision 4 · from a run",
    );
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
      [
        ...document.querySelectorAll<HTMLElement>(
          '[aria-label="Selected artifact"] button',
        ),
      ]
        .find((button) => button.textContent === "Execution history")!
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

  it("keeps a click on a row menu from folding its folder", async () => {
    await renderPanel({ folders: [FIELDWORK, SEPTEMBER], items: [RUN_ITEM] });

    const trigger = folderRow("fieldwork").querySelector<HTMLElement>(
      '[aria-label="Actions for Fieldwork"]',
    )!;
    await React.act(async () => {
      trigger.click();
    });
    expect(folderRow("fieldwork").getAttribute("aria-expanded")).toBe("true");

    const rename = [
      ...document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ].find((item) => item.textContent === "Rename")!;
    await selectMenuItem(rename);

    expect(folderRow("fieldwork").getAttribute("aria-expanded")).toBe("true");
    expect(
      document.querySelector('input[aria-label="Folder name"]'),
    ).not.toBeNull();
  });

  it("opens every folder while a filter is on, and restores the folds after", async () => {
    await renderPanel({ folders: [FIELDWORK, SEPTEMBER], items: [RUN_ITEM] });
    await React.act(async () => {
      folderRow("fieldwork").click();
    });
    expect(
      document.querySelector('[data-tree-key="file:artifact-run"]'),
    ).toBeNull();

    const filter = document.querySelector<HTMLInputElement>(
      'input[aria-label="Filter the Library"]',
    )!;
    await React.act(async () => {
      typeInto(filter, "sales");
    });
    expect(fileRow("artifact-run")).not.toBeNull();

    await React.act(async () => {
      typeInto(filter, "");
    });
    expect(folderRow("fieldwork").getAttribute("aria-expanded")).toBe("false");
  });

  it("says when a filter matches nothing", async () => {
    await renderPanel({ folders: [FIELDWORK], items: [RUN_ITEM] });

    await React.act(async () => {
      typeInto(
        document.querySelector<HTMLInputElement>(
          'input[aria-label="Filter the Library"]',
        )!,
        "kestrel",
      );
    });

    expect(rows()).toEqual([]);
    expect(document.body.textContent).toContain(
      "Nothing in the Library matches “kestrel”.",
    );
    expect(document.body.textContent).toContain("0 of 1 artifact");
  });

  it("files an artifact dropped on another into that one's folder", async () => {
    moveItems.mockResolvedValue(undefined);

    await renderPanel({
      folders: [FIELDWORK, SEPTEMBER],
      items: [RUN_ITEM, UPLOAD_ITEM],
    });

    await React.act(async () => {
      dropPayload(fileRow("artifact-run"), {
        [ARTIFACT_DROP_TYPE]: artifactDropValue("artifact-upload"),
      });
    });

    expect(moveItems).toHaveBeenCalledWith({
      workspaceId: expect.any(String),
      artifactIds: ["artifact-upload"],
      folderId: "september",
    });
  });

  it("sends nothing for a rename that keeps the name or clears it", async () => {
    await renderPanel({ folders: [EMPTY_FOLDER], items: [] });

    for (const value of ["Archive", "   "]) {
      await React.act(async () => {
        folderRow("archive").focus();
        press(folderRow("archive"), "F2");
      });
      const input = document.querySelector<HTMLInputElement>(
        'input[aria-label="Folder name"]',
      )!;
      await React.act(async () => {
        typeInto(input, value);
      });
      await React.act(async () => {
        press(input, "Enter");
      });
      expect(
        document.querySelector('input[aria-label="Folder name"]'),
      ).toBeNull();
      expect(document.activeElement).toBe(folderRow("archive"));
    }

    expect(renameFolder).not.toHaveBeenCalled();
  });

  it("closes the preview from its tile and with Escape", async () => {
    await renderPanel({ folders: [], items: [UPLOAD_ITEM] });
    const tile = () =>
      document.querySelector('[aria-label="Selected artifact"]');

    await React.act(async () => {
      fileRow("artifact-upload").click();
    });
    await React.act(async () => {
      document
        .querySelector<HTMLElement>('button[aria-label="Close preview"]')!
        .click();
    });
    expect(tile()).toBeNull();

    await React.act(async () => {
      fileRow("artifact-upload").click();
      fileRow("artifact-upload").focus();
    });
    expect(tile()).not.toBeNull();
    await React.act(async () => {
      press(fileRow("artifact-upload"), "Escape");
    });
    expect(tile()).toBeNull();
  });

  it("never previews an error page as the artifact's text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("Not found", { status: 404 })),
    );
    await renderPanel({ folders: [FIELDWORK, SEPTEMBER], items: [RUN_ITEM] });

    await React.act(async () => {
      fileRow("artifact-run").click();
    });
    await React.act(async () => {
      await vi.waitFor(() =>
        expect(document.body.textContent).not.toContain("Reading preview"),
      );
    });

    const tile = document.querySelector('[aria-label="Selected artifact"]')!;
    expect(tile.querySelector("pre")).toBeNull();
    expect(tile.textContent).not.toContain("Not found");
  });

  it("says the Library could not be loaded, and never that it is empty", async () => {
    listTree.mockRejectedValue(new Error("offline"));
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);
    await React.act(async () => {
      root.render(
        <LibraryPanel workspaceId="unreachable" onOpenRun={vi.fn()} />,
      );
    });
    await React.act(async () => {
      await vi.waitFor(() =>
        expect(document.body.textContent).toContain(
          "The Library could not be loaded.",
        ),
      );
    });

    expect(document.body.textContent).not.toContain("The Library is empty");
  });

  it("says an unreadable artifact will not open, without hiding the row", async () => {
    await renderPanel({ folders: [], items: [BLOB_ITEM] });

    expect(document.body.textContent).toContain("scan.unknown");
    expect(fileRow("artifact-blob").textContent).toContain(
      BLOB_ARTIFACT_NOTICE,
    );
  });
});

/**
 * Several artifacts selected at once: what the tree shows, what a drag carries,
 * and what one Delete asks for.
 */
describe("LibraryPanel multi-selection", () => {
  function upload(
    id: string,
    filename: string,
    artifactType = "file.png",
    folderId: string | null = null,
  ): PlacedLibraryItem {
    return {
      artifact: {
        artifact_id: id,
        artifact_type: artifactType,
        schema_version: 1,
        content_type: artifactType === "file.png" ? "image/png" : "text/csv",
        byte_size: 10,
        sha256: `hash-${id}`,
        content_url: `/api/v1/artifacts/${id}/content`,
        download_formats: [],
        metadata: {},
      },
      name: filename,
      provenance: {
        source: "upload",
        saved_at: "2026-09-11T12:00:00Z",
        original_filename: filename,
      },
      run: null,
      folder_id: folderId,
    };
  }

  const A = upload("art-a", "a.png");
  const B = upload("art-b", "b.png");
  const C = upload("art-c", "c.png");
  const D = upload("art-d", "d.csv", "file.csv");

  /** Every root artifact the panel lists, in the order the tree shows them. */
  function three() {
    return renderPanel({ folders: [], items: [C, A, B] });
  }

  function selectedLabels(): string[] {
    return rows()
      .filter((row) => row.getAttribute("aria-selected") === "true")
      .map((row) => row.dataset.treeLabel ?? "");
  }

  function click(
    rowId: string,
    modifiers: { metaKey?: boolean; shiftKey?: boolean } = {},
  ): Promise<void> {
    return React.act(async () => {
      fileRow(rowId).dispatchEvent(
        new MouseEvent("click", {
          bubbles: true,
          cancelable: true,
          ...modifiers,
        }),
      );
    });
  }

  function tile(): HTMLElement | null {
    return document.querySelector<HTMLElement>(
      '[aria-label="Selected artifact"]',
    );
  }

  /** The rows a drag starting on this row carries, as the tree wrote them. */
  async function dragFrom(rowId: string): Promise<Record<string, string>> {
    const written: Record<string, string> = {};
    const dataTransfer = {
      types: [] as string[],
      files: [],
      getData: (type: string) => written[type] ?? "",
      setData: (type: string, value: string) => {
        written[type] = value;
      },
      effectAllowed: "uninitialized",
      dropEffect: "none",
    };
    const event = new Event("dragstart", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", { value: dataTransfer });
    await React.act(async () => {
      fileRow(rowId).dispatchEvent(event);
    });
    return written;
  }

  function moveIds(written: Record<string, string>): string[] {
    return JSON.parse(written[LIBRARY_MOVE_DATA_TYPE] ?? "[]") as string[];
  }

  it("selects one row at a time until a second modifier says otherwise", async () => {
    await three();

    await click("art-a");
    expect(selectedLabels()).toEqual(["a.png"]);
    // One selected artifact is the one case the preview tile has anything to say
    // about, so it is up.
    expect(tile()).not.toBeNull();

    await click("art-b");
    expect(selectedLabels()).toEqual(["b.png"]);

    await click("art-c", { metaKey: true });
    expect(selectedLabels()).toEqual(["b.png", "c.png"]);
  });

  it("counts a shift range over the rows on screen and drops the preview", async () => {
    await renderPanel({ folders: [], items: [A, B, C, D] });

    await click("art-a");
    await click("art-c", { shiftKey: true });

    expect(selectedLabels()).toEqual(["a.png", "b.png", "c.png"]);
    // Two artifacts have no one preview, and a tile showing one of three would
    // claim to be what a drag or a delete means.
    expect(tile()).toBeNull();
    expect(document.body.textContent).toContain("3 selected");
    expect(document.body.textContent).toContain("4 artifacts · 0 folders");
  });

  it("counts a range upwards from the anchor just the same", async () => {
    await renderPanel({ folders: [], items: [A, B, C, D] });

    await click("art-d");
    await click("art-b", { shiftKey: true });

    expect(selectedLabels()).toEqual(["b.png", "c.png", "d.csv"]);
  });

  it("clears the selection on Escape, preview and all", async () => {
    await three();
    await click("art-a");
    await click("art-b", { shiftKey: true });
    expect(selectedLabels()).toHaveLength(2);

    await React.act(async () => {
      press(rows()[0]!, "Escape");
    });

    expect(selectedLabels()).toEqual([]);
    expect(tile()).toBeNull();
  });

  it("asks for the whole selection when the row asked about is part of it", async () => {
    await three();
    await click("art-a");
    await click("art-b", { metaKey: true });
    deleteLibraryArtifact.mockResolvedValue(undefined);

    const dialog = await confirmArtifactDelete("art-a");
    expect(dialog.textContent).toContain("Delete 2 artifacts?");

    await React.act(async () => {
      buttonIn(dialog, "Delete").click();
    });

    // Tree order, one call each, whatever order the rows were clicked in.
    await React.act(async () => {
      await vi.waitFor(() =>
        expect(deleteLibraryArtifact.mock.calls.length).toBe(2),
      );
    });
    expect(deleteLibraryArtifact.mock.calls.map(([, id]) => id)).toEqual([
      "art-a",
      "art-b",
    ]);
    expect(selectedLabels()).toEqual([]);
  });

  it("deletes one row when the row asked about is outside the selection", async () => {
    await renderPanel({ folders: [], items: [A, B, D] });
    deleteLibraryArtifact.mockResolvedValue(undefined);
    await click("art-a");
    await click("art-b", { metaKey: true });

    const dialog = await confirmArtifactDelete("art-d");
    expect(dialog.textContent).toContain("Delete d.csv?");

    await React.act(async () => {
      buttonIn(dialog, "Delete").click();
    });

    await React.act(async () => {
      await vi.waitFor(() =>
        expect(deleteLibraryArtifact.mock.calls).toEqual([
          [expect.any(String), "art-d"],
        ]),
      );
    });
    // The two rows the user had selected are nothing to do with that delete.
    expect(selectedLabels()).toEqual(["a.png", "b.png"]);
  });

  it("keeps the artifact that refused selected, and names it once", async () => {
    await renderPanel({ folders: [], items: [A, B, D] });
    deleteLibraryArtifact.mockImplementation(
      async (_workspaceId: string, artifactId: string) => {
        if (artifactId === "art-b") {
          throw new LibraryArtifactInUseError(
            artifactId,
            "Still used by: Salt maps",
          );
        }
      },
    );

    await click("art-a");
    await click("art-b", { metaKey: true });
    await click("art-d", { metaKey: true });

    const dialog = await confirmArtifactDelete("art-a");
    await React.act(async () => {
      buttonIn(dialog, "Delete").click();
    });

    await React.act(async () => {
      await vi.waitFor(() =>
        expect(document.body.textContent).toContain(
          "Deleted 2. 1 still used by: Salt maps",
        ),
      );
    });
    // A refusal never stops the artifact after it.
    expect(deleteLibraryArtifact.mock.calls.map(([, id]) => id)).toEqual([
      "art-a",
      "art-b",
      "art-d",
    ]);
    // What refused stays selected so the user can see it; what went away is gone
    // from the tree and from the selection with it.
    expect(selectedLabels()).toEqual(["b.png"]);
    expect(fileRow("art-b")).not.toBeNull();
  });

  it("offers the keyboard delete to a member who cannot edit and takes nothing", async () => {
    await renderPanel({ folders: [], items: [A, B] }, vi.fn(), {
      canEdit: false,
    });

    await click("art-a");
    await React.act(async () => {
      press(fileRow("art-a"), "Delete");
    });

    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(deleteLibraryArtifact).not.toHaveBeenCalled();
  });

  it("carries an arrow held with a modifier into the selection", async () => {
    await renderPanel({ folders: [], items: [A, B, D] });
    await click("art-a");

    await React.act(async () => {
      const row = fileRow("art-a");
      row.focus();
      press(row, "ArrowDown", { shiftKey: true });
    });

    // The arrow moved to the next row and took the run with it, exactly as
    // Shift-click on that row would have.
    expect(selectedLabels()).toEqual(["a.png", "b.png"]);
    expect(document.activeElement).toBe(fileRow("art-b"));
  });

  it("asks for the selection from the keyboard as well", async () => {
    await renderPanel({ folders: [], items: [A, B, D] });
    await click("art-a");
    await click("art-d", { metaKey: true });

    await React.act(async () => {
      fileRow("art-d").focus();
      press(fileRow("art-d"), "Backspace");
    });

    const dialog = confirmDialog();
    expect(dialog.textContent).toContain("Delete 2 artifacts?");
    expect(deleteLibraryArtifact).not.toHaveBeenCalled();
  });

  it("carries the whole selection in a drag from one of its rows", async () => {
    await renderPanel({ folders: [FIELDWORK], items: [A, B, D] });
    await click("art-a");
    await click("art-b", { metaKey: true });

    const written = await dragFrom("art-a");

    expect(moveIds(written)).toEqual(["art-a", "art-b"]);
    const drop = written[ARTIFACT_DROP_TYPE];
    if (!drop) throw new Error("expected a drop payload");
    // Two images, one sequence card, so there is nothing to group.
    expect(written[ARTIFACT_GROUPS_DATA_TYPE]).toBeUndefined();
    expect(JSON.parse(drop).value.item_refs).toHaveLength(2);
  });

  it("splits a selection of mixed kinds into one card each", async () => {
    await renderPanel({ folders: [], items: [A, B, D] });
    await click("art-a");
    await click("art-d", { metaKey: true });

    const written = await dragFrom("art-a");

    expect(moveIds(written)).toEqual(["art-a", "art-d"]);
    const groupsPayload = written[ARTIFACT_GROUPS_DATA_TYPE];
    if (!groupsPayload) throw new Error("expected drop groups");
    const groups = JSON.parse(groupsPayload);
    expect(
      groups.map((group: { value: Record<string, unknown>; shape: string }) => [
        group.value.artifact_type,
        group.shape,
      ]),
    ).toEqual([
      ["file.png", "one"],
      ["file.csv", "one"],
    ]);
    // A canvas that predates grouped drops still lands the first card.
    const drop = written[ARTIFACT_DROP_TYPE];
    if (!drop) throw new Error("expected a drop payload");
    expect(JSON.parse(drop).value.artifact_type).toBe("file.png");
  });

  it("carries one row when the dragged row is outside the selection", async () => {
    await renderPanel({ folders: [], items: [A, B, D] });
    await click("art-a");
    await click("art-b", { metaKey: true });

    const written = await dragFrom("art-d");

    expect(moveIds(written)).toEqual(["art-d"]);
    expect(written[ARTIFACT_GROUPS_DATA_TYPE]).toBeUndefined();
    // The panel follows the drag: what it has selected is what was dragged.
    expect(selectedLabels()).toEqual(["d.csv"]);
  });

  it("moves every artifact of a dropped selection into the folder it lands on", async () => {
    await renderPanel({ folders: [FIELDWORK], items: [A, B, D] });
    moveItems.mockResolvedValue(undefined);

    await React.act(async () => {
      dropPayload(folderRow("fieldwork"), {
        [LIBRARY_MOVE_DATA_TYPE]: JSON.stringify(["art-a", "art-b"]),
        [ARTIFACT_DROP_TYPE]: artifactDropValue("art-a"),
      });
    });

    expect(moveItems).toHaveBeenCalledWith({
      workspaceId: expect.any(String),
      artifactIds: ["art-a", "art-b"],
      folderId: "fieldwork",
    });
  });

  it("files an artifact dragged from the canvas, which carries no move list", async () => {
    await renderPanel({ folders: [FIELDWORK], items: [A] });
    moveItems.mockResolvedValue(undefined);

    await React.act(async () => {
      dropPayload(folderRow("fieldwork"), {
        [ARTIFACT_DROP_TYPE]: artifactDropValue("art-a"),
      });
    });

    expect(moveItems).toHaveBeenCalledWith({
      workspaceId: expect.any(String),
      artifactIds: ["art-a"],
      folderId: "fieldwork",
    });
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockLibraryFolders } from "./library-folders.mock";
import {
  LibraryFolderCycleError,
  LibraryFolderNotEmptyError,
} from "./library-folder-model";
import {
  buildLibraryTree,
  flattenLibraryRows,
} from "@/features/workbench/ui/side-panel/library-tree";

vi.mock("./library", () => ({
  listLibraryArtifacts: vi.fn(async () => ({
    items: [
      {
        artifact: {
          artifact_id: "artifact-1",
          artifact_type: "file.png",
          schema_version: 1,
          content_type: "image/png",
          byte_size: 10,
          content_url: "./artifacts/artifact-1/content",
        },
        name: "photo.png",
        provenance: {
          source: "upload",
          saved_at: "2026-09-11T12:00:00Z",
          original_filename: "photo.png",
        },
        run: null,
      },
    ],
  })),
}));

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

const WORKSPACE = "workspace-folders";

/** The rows of the tree the panel would paint, with their depth. */
async function paintedRows(): Promise<string[]> {
  const { folders, items } = await mockLibraryFolders.listTree(WORKSPACE);
  return flattenLibraryRows(buildLibraryTree({ folders, items })).map((node) =>
    node.kind === "folder" ? `${node.name}@${node.depth}` : `${node.item.name}@${node.depth}`,
  );
}

beforeEach(() => installMemoryStorage());

afterEach(() => vi.unstubAllGlobals());

describe("mockLibraryFolders", () => {
  it("starts with a folder tree the user can see", async () => {
    const { folders } = await mockLibraryFolders.listTree(WORKSPACE);
    expect(folders.map((folder) => folder.name)).toContain("Fieldwork");
  });

  it("nests a created subfolder under its parent", async () => {
    const parent = await mockLibraryFolders.createFolder({
      workspaceId: WORKSPACE,
      name: "Trench",
      parentId: null,
    });
    await mockLibraryFolders.createFolder({
      workspaceId: WORKSPACE,
      name: "Layer 2",
      parentId: parent.folder_id,
    });

    const rows = await paintedRows();
    expect(rows).toEqual(
      expect.arrayContaining(["Fieldwork@0", "Trench@0", "Layer 2@1"]),
    );
    expect(rows.indexOf("Layer 2@1")).toBe(rows.indexOf("Trench@0") + 1);
  });

  it("files an artifact where it is moved and lifts it back out", async () => {
    const folder = await mockLibraryFolders.createFolder({
      workspaceId: WORKSPACE,
      name: "Cold store",
      parentId: null,
    });
    await mockLibraryFolders.moveItems({
      workspaceId: WORKSPACE,
      artifactIds: ["artifact-1"],
      folderId: folder.folder_id,
    });

    let tree = await mockLibraryFolders.listTree(WORKSPACE);
    expect(tree.items[0]?.folder_id).toBe(folder.folder_id);

    await mockLibraryFolders.moveItems({
      workspaceId: WORKSPACE,
      artifactIds: ["artifact-1"],
      folderId: null,
    });
    tree = await mockLibraryFolders.listTree(WORKSPACE);
    expect(tree.items[0]?.folder_id).toBeNull();
  });

  it("refuses to delete a folder that still holds something", async () => {
    const parent = await mockLibraryFolders.createFolder({
      workspaceId: WORKSPACE,
      name: "Season",
      parentId: null,
    });
    await mockLibraryFolders.createFolder({
      workspaceId: WORKSPACE,
      name: "Inner",
      parentId: parent.folder_id,
    });

    await expect(
      mockLibraryFolders.deleteFolder({ workspaceId: WORKSPACE, folderId: parent.folder_id }),
    ).rejects.toBeInstanceOf(LibraryFolderNotEmptyError);

    await mockLibraryFolders.deleteFolder({
      workspaceId: WORKSPACE,
      folderId: (await mockLibraryFolders.listTree(WORKSPACE)).folders.find(
        (folder) => folder.name === "Inner",
      )!.folder_id,
    });
    const { folders } = await mockLibraryFolders.listTree(WORKSPACE);
    expect(folders.some((folder) => folder.name === "Inner")).toBe(false);
  });

  it("refuses to move a folder inside its own descendant", async () => {
    const parent = await mockLibraryFolders.createFolder({
      workspaceId: WORKSPACE,
      name: "Outer",
      parentId: null,
    });
    const child = await mockLibraryFolders.createFolder({
      workspaceId: WORKSPACE,
      name: "Middle",
      parentId: parent.folder_id,
    });
    const grandchild = await mockLibraryFolders.createFolder({
      workspaceId: WORKSPACE,
      name: "Deep",
      parentId: child.folder_id,
    });

    await expect(
      mockLibraryFolders.moveFolder({
        workspaceId: WORKSPACE,
        folderId: parent.folder_id,
        parentId: grandchild.folder_id,
      }),
    ).rejects.toBeInstanceOf(LibraryFolderCycleError);
  });

  it("keeps two folders in one parent apart", async () => {
    await mockLibraryFolders.createFolder({
      workspaceId: WORKSPACE,
      name: "Kestrel notes",
      parentId: null,
    });
    await expect(
      mockLibraryFolders.createFolder({
        workspaceId: WORKSPACE,
        name: "kestrel NOTES",
        parentId: null,
      }),
    ).rejects.toThrow(/already exists/);
  });
});

import type { LibraryItem } from "./contract";

/**
 * The Workspace Library folder model, shared by whichever implementation of
 * `LibraryFoldersApi` is wired up.
 *
 * The Library is a filesystem-like tree the user owns: folders nest to any
 * depth, an artifact either sits in a folder or sits at the root, and nothing
 * about the shape is derived from the artifact type.
 */

export type LibraryFolder = {
  folder_id: string;
  workspace_id: string;
  parent_id: string | null;
  name: string;
  created_at: string;
  updated_at: string;
};

/** A Library artifact and where it sits in the folder tree. */
export type PlacedLibraryItem = LibraryItem & { folder_id: string | null };

export type LibraryTreeData = {
  folders: LibraryFolder[];
  items: PlacedLibraryItem[];
};

export type LibraryFoldersApi = {
  listTree(workspaceId: string): Promise<LibraryTreeData>;
  createFolder(input: {
    workspaceId: string;
    name: string;
    parentId: string | null;
  }): Promise<LibraryFolder>;
  renameFolder(input: {
    workspaceId: string;
    folderId: string;
    name: string;
  }): Promise<LibraryFolder>;
  /** Rejects with `LibraryFolderNotEmptyError` while the folder has contents. */
  deleteFolder(input: { workspaceId: string; folderId: string }): Promise<void>;
  /** Rejects with `LibraryFolderCycleError` when a folder would land inside itself. */
  moveFolder(input: {
    workspaceId: string;
    folderId: string;
    parentId: string | null;
  }): Promise<LibraryFolder>;
  /** `folderId: null` files the artifacts at the root. */
  moveItems(input: {
    workspaceId: string;
    artifactIds: readonly string[];
    folderId: string | null;
  }): Promise<void>;
};

/** A folder still holds artifacts or child folders. */
export class LibraryFolderNotEmptyError extends Error {
  readonly folderId: string;
  readonly artifactCount: number;
  readonly childCount: number;

  constructor(input: {
    folderId: string;
    artifactCount: number;
    childCount: number;
  }) {
    super(
      `Folder ${input.folderId} holds ${input.artifactCount} artifact${
        input.artifactCount === 1 ? "" : "s"
      } and ${input.childCount} folder${input.childCount === 1 ? "" : "s"}.`,
    );
    this.name = "LibraryFolderNotEmptyError";
    this.folderId = input.folderId;
    this.artifactCount = input.artifactCount;
    this.childCount = input.childCount;
  }
}

/** A folder cannot be moved inside itself or one of its own descendants. */
export class LibraryFolderCycleError extends Error {
  readonly folderId: string;
  readonly parentId: string | null;

  constructor(folderId: string, parentId: string | null) {
    super(`Folder ${folderId} cannot be moved inside itself.`);
    this.name = "LibraryFolderCycleError";
    this.folderId = folderId;
    this.parentId = parentId;
  }
}

/** Another folder in the same parent already goes by that name. */
export class LibraryFolderNameTakenError extends Error {
  readonly name: string;
  readonly parentId: string | null;
  readonly folderName: string;

  constructor(input: { parentId: string | null; folderName: string }) {
    super(`A folder named ${input.folderName} already exists here.`);
    this.name = "LibraryFolderNameTakenError";
    this.parentId = input.parentId;
    this.folderName = input.folderName;
  }
}

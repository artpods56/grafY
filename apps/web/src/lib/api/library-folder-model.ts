import type { LibraryItem } from "./contract";

/**
 * The Workspace Library folder model: the rows the server holds and the three
 * rules its routes refuse to break.
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

/**
 * A folder still holds artifacts or child folders.
 *
 * The counts are not part of it: the server refuses the delete by code alone, and
 * the panel states the contents from the tree it already renders.
 */
export class LibraryFolderNotEmptyError extends Error {
  readonly folderId: string;

  constructor(folderId: string) {
    super(`Folder ${folderId} still holds artifacts or folders.`);
    this.name = "LibraryFolderNotEmptyError";
    this.folderId = folderId;
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
  override readonly name: string;
  readonly folderName: string;

  constructor(folderName: string) {
    super(`A folder named ${folderName} already exists here.`);
    this.name = "LibraryFolderNameTakenError";
    this.folderName = folderName;
  }
}

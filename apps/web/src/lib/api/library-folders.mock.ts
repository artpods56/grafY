import { listLibraryArtifacts } from "./library";
import {
  LibraryFolderCycleError,
  LibraryFolderNameTakenError,
  LibraryFolderNotEmptyError,
  type LibraryFolder,
  type LibraryFoldersApi,
  type LibraryTreeData,
  type PlacedLibraryItem,
} from "./library-folder-model";

/**
 * A browser-local stand-in for the Library folder API while the backend lands.
 *
 * Folder trees and artifact placements persist per workspace in localStorage;
 * the artifacts themselves still come from the real Library endpoint, so what
 * the panel shows is real data in a made-up tree. Deleting this file, and the
 * `libraryFoldersApi` branch that picks it, is the whole cleanup.
 */

type MockState = {
  folders: LibraryFolder[];
  /** artifact_id → folder_id. An absent key means the artifact is at the root. */
  placements: Record<string, string>;
};

const SEED_FOLDERS: readonly { id: string; name: string; parent: string | null }[] = [
  { id: "seed-fieldwork", name: "Fieldwork", parent: null },
  { id: "seed-september", name: "September", parent: "seed-fieldwork" },
  { id: "seed-raw-photos", name: "Raw photos", parent: "seed-september" },
  { id: "seed-reports", name: "Reports", parent: null },
];

function stateKey(workspaceId: string): string {
  return `grafy-library-folders-mock:${workspaceId}`;
}

function now(): string {
  return new Date().toISOString();
}

function newFolderId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `folder-${Date.now().toString(36)}`;
}

function readState(workspaceId: string): MockState {
  const store = globalThis.localStorage;
  if (!store) return { folders: [], placements: {} };
  try {
    const saved = store.getItem(stateKey(workspaceId));
    if (saved) return JSON.parse(saved) as MockState;
  } catch {
    // A corrupt scratch pad is worth less than a working tree: start over.
  }
  const stamp = now();
  const folders = SEED_FOLDERS.map((seed) => ({
    folder_id: seed.id,
    workspace_id: workspaceId,
    parent_id: seed.parent,
    name: seed.name,
    created_at: stamp,
    updated_at: stamp,
  }));
  return { folders, placements: {} };
}

function writeState(workspaceId: string, state: MockState): void {
  try {
    globalThis.localStorage?.setItem(stateKey(workspaceId), JSON.stringify(state));
  } catch {
    // Storage can be full or blocked; the in-memory tree still works.
  }
}

function byName(a: { name: string }, b: { name: string }): number {
  return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
}

function findFolder(state: MockState, folderId: string): LibraryFolder {
  const folder = state.folders.find((entry) => entry.folder_id === folderId);
  if (!folder) throw new Error(`Unknown Library folder ${folderId}.`);
  return folder;
}

function isDescendantOf(
  state: MockState,
  candidateId: string,
  ancestorId: string,
): boolean {
  let current: LibraryFolder | undefined = state.folders.find(
    (entry) => entry.folder_id === candidateId,
  );
  while (current) {
    if (current.parent_id === null) return false;
    if (current.parent_id === ancestorId) return true;
    const parentId = current.parent_id;
    current = state.folders.find((entry) => entry.folder_id === parentId);
  }
  return false;
}

function assertNameFree(
  state: MockState,
  parentId: string | null,
  name: string,
  exceptFolderId?: string,
): void {
  const taken = state.folders.some(
    (folder) =>
      folder.parent_id === parentId &&
      folder.folder_id !== exceptFolderId &&
      folder.name.trim().toLowerCase() === name.trim().toLowerCase(),
  );
  if (taken) throw new LibraryFolderNameTakenError({ parentId, folderName: name });
}

export const mockLibraryFolders: LibraryFoldersApi = {
  async listTree(workspaceId): Promise<LibraryTreeData> {
    const library = await listLibraryArtifacts(workspaceId);
    const state = readState(workspaceId);
    const folderIds = new Set(state.folders.map((folder) => folder.folder_id));

    // File anything whose folder or artifact has since disappeared at the root.
    const artifactIds = new Set(
      library.items.map((item) => item.artifact.artifact_id),
    );
    for (const [artifactId, folderId] of Object.entries(state.placements)) {
      if (!artifactIds.has(artifactId) || !folderIds.has(folderId)) {
        delete state.placements[artifactId];
      }
    }
    writeState(workspaceId, state);

    const items: PlacedLibraryItem[] = library.items.map((item) => ({
      ...item,
      folder_id: state.placements[item.artifact.artifact_id] ?? null,
    }));
    return {
      folders: [...state.folders].sort(byName),
      items,
    };
  },

  async createFolder({ workspaceId, name, parentId }) {
    const trimmed = name.trim();
    if (trimmed === "") {
      throw new Error("A Library folder needs a name.");
    }
    const state = readState(workspaceId);
    if (parentId !== null) findFolder(state, parentId);
    assertNameFree(state, parentId, trimmed);
    const stamp = now();
    const folder: LibraryFolder = {
      folder_id: newFolderId(),
      workspace_id: workspaceId,
      parent_id: parentId,
      name: trimmed,
      created_at: stamp,
      updated_at: stamp,
    };
    state.folders.push(folder);
    writeState(workspaceId, state);
    return folder;
  },

  async renameFolder({ workspaceId, folderId, name }) {
    const trimmed = name.trim();
    if (trimmed === "") {
      throw new Error("A Library folder needs a name.");
    }
    const state = readState(workspaceId);
    const folder = findFolder(state, folderId);
    assertNameFree(state, folder.parent_id, trimmed, folderId);
    folder.name = trimmed;
    folder.updated_at = now();
    writeState(workspaceId, state);
    return { ...folder };
  },

  async deleteFolder({ workspaceId, folderId }) {
    const state = readState(workspaceId);
    findFolder(state, folderId);
    const childCount = state.folders.filter(
      (entry) => entry.parent_id === folderId,
    ).length;
    const artifactCount = Object.values(state.placements).filter(
      (placed) => placed === folderId,
    ).length;
    if (childCount > 0 || artifactCount > 0) {
      throw new LibraryFolderNotEmptyError({
        folderId,
        artifactCount,
        childCount,
      });
    }
    state.folders = state.folders.filter(
      (entry) => entry.folder_id !== folderId,
    );
    writeState(workspaceId, state);
  },

  async moveFolder({ workspaceId, folderId, parentId }) {
    const state = readState(workspaceId);
    const folder = findFolder(state, folderId);
    if (parentId !== null) {
      findFolder(state, parentId);
      if (parentId === folderId || isDescendantOf(state, parentId, folderId)) {
        throw new LibraryFolderCycleError(folderId, parentId);
      }
    }
    assertNameFree(state, parentId, folder.name, folderId);
    folder.parent_id = parentId;
    folder.updated_at = now();
    writeState(workspaceId, state);
    return { ...folder };
  },

  async moveItems({ workspaceId, artifactIds, folderId }) {
    const state = readState(workspaceId);
    if (folderId !== null) findFolder(state, folderId);
    for (const artifactId of artifactIds) {
      if (folderId === null) delete state.placements[artifactId];
      else state.placements[artifactId] = folderId;
    }
    writeState(workspaceId, state);
  },
};

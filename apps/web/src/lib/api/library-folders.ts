import { ApiError, request } from "./client";
import { listLibraryArtifacts } from "./library";
import type {
  LibraryFolder,
  LibraryFoldersApi,
  LibraryTreeData,
  PlacedLibraryItem,
} from "./library-folder-model";
import {
  LibraryFolderCycleError,
  LibraryFolderNameTakenError,
  LibraryFolderNotEmptyError,
} from "./library-folder-model";

export * from "./library-folder-model";

/**
 * The Workspace Library folder tree: folders the user makes, and which folder
 * each Library artifact sits in.
 *
 * The tree itself is assembled on the client (`library-tree.ts`); the server
 * holds the rows and the three rules a signature cannot carry. It reports each
 * one as a failure code, and those codes become the error classes the panel
 * already knows how to phrase.
 */

const FOLDER_NAME_TAKEN = "library.folder_name_conflict";
const FOLDER_NOT_EMPTY = "library.folder_not_empty";
const FOLDER_CYCLE = "library.folder_cycle";

function foldersPath(workspaceId: string, suffix = ""): string {
  return `/v1/workspaces/${encodeURIComponent(workspaceId)}/library/folders${suffix}`;
}

/**
 * Turn one server refusal into the error the panel states.
 *
 * `name` and `folderId` come from the caller because the server names the
 * clash by its public message only, and the panel's sentence repeats what the
 * user just typed.
 */
function libraryFolderError(
  error: unknown,
  context: { folderId?: string; parentId?: string | null; name?: string },
): unknown {
  if (!(error instanceof ApiError)) return error;
  if (error.code === FOLDER_NOT_EMPTY && context.folderId !== undefined) {
    return new LibraryFolderNotEmptyError(context.folderId);
  }
  if (error.code === FOLDER_CYCLE && context.folderId !== undefined) {
    return new LibraryFolderCycleError(
      context.folderId,
      context.parentId ?? null,
    );
  }
  if (error.code === FOLDER_NAME_TAKEN) {
    return new LibraryFolderNameTakenError(context.name ?? "that name");
  }
  return error;
}

export const libraryFoldersApi: LibraryFoldersApi = {
  async listTree(workspaceId): Promise<LibraryTreeData> {
    const [folders, library] = await Promise.all([
      request<{ folders: LibraryFolder[] }>("GET", foldersPath(workspaceId)),
      listLibraryArtifacts(workspaceId),
    ]);
    const items: PlacedLibraryItem[] = library.items.map((item) => ({
      ...item,
      folder_id: item.folder_id ?? null,
    }));
    return { folders: folders.folders, items };
  },

  async createFolder({ workspaceId, name, parentId }) {
    try {
      return await request<LibraryFolder>("POST", foldersPath(workspaceId), {
        body: { name, parent_id: parentId },
      });
    } catch (error) {
      throw libraryFolderError(error, { name, parentId });
    }
  },

  async renameFolder({ workspaceId, folderId, name }) {
    try {
      return await request<LibraryFolder>(
        "PATCH",
        foldersPath(workspaceId, `/${encodeURIComponent(folderId)}`),
        { body: { name } },
      );
    } catch (error) {
      throw libraryFolderError(error, { folderId, name });
    }
  },

  async deleteFolder({ workspaceId, folderId }) {
    try {
      await request<never>(
        "DELETE",
        foldersPath(workspaceId, `/${encodeURIComponent(folderId)}`),
      );
    } catch (error) {
      throw libraryFolderError(error, { folderId });
    }
  },

  async moveFolder({ workspaceId, folderId, parentId }) {
    try {
      return await request<LibraryFolder>(
        "PUT",
        foldersPath(workspaceId, `/${encodeURIComponent(folderId)}/parent`),
        { body: { parent_id: parentId } },
      );
    } catch (error) {
      throw libraryFolderError(error, { folderId, parentId });
    }
  },

  async moveItems({ workspaceId, artifactIds, folderId }) {
    await request<never>(
      "PUT",
      `/v1/workspaces/${encodeURIComponent(workspaceId)}/library/placements`,
      { body: { artifact_ids: [...artifactIds], folder_id: folderId } },
    );
  },
};

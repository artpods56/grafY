import { request } from "./client";
import { listLibraryArtifacts } from "./library";
import { mockLibraryFolders } from "./library-folders.mock";
import type { LibraryFolder, LibraryFoldersApi } from "./library-folder-model";

export * from "./library-folder-model";

/**
 * Which Library folder API the app talks to.
 *
 * The backend routes do not exist yet, so `libraryFoldersApi` resolves to a
 * browser-local mock unless `NEXT_PUBLIC_LIBRARY_FOLDERS_API=real`. Flipping
 * that flag is the whole migration: the calls already match the shape the
 * routes will have. The mock lives in `library-folders.mock.ts` and nothing
 * else knows it is there.
 */

function foldersPath(workspaceId: string, suffix = ""): string {
  return `/v1/workspaces/${encodeURIComponent(workspaceId)}/library/folders${suffix}`;
}

/**
 * The real API. `folder_id` on a Library artifact is part of the same change,
 * so an artifact that predates it reads as filed at the root.
 */
const httpLibraryFolders: LibraryFoldersApi = {
  async listTree(workspaceId) {
    const [folders, library] = await Promise.all([
      request<{ folders: LibraryFolder[] }>("GET", foldersPath(workspaceId)),
      listLibraryArtifacts(workspaceId),
    ]);
    return {
      folders: folders.folders,
      items: library.items.map((item) => ({
        ...item,
        folder_id:
          (item as { folder_id?: string | null }).folder_id ?? null,
      })),
    };
  },

  createFolder({ workspaceId, name, parentId }) {
    return request<LibraryFolder>("POST", foldersPath(workspaceId), {
      body: { name, parent_id: parentId },
    });
  },

  renameFolder({ workspaceId, folderId, name }) {
    return request<LibraryFolder>(
      "PATCH",
      foldersPath(workspaceId, `/${encodeURIComponent(folderId)}`),
      { body: { name } },
    );
  },

  async deleteFolder({ workspaceId, folderId }) {
    await request<never>(
      "DELETE",
      foldersPath(workspaceId, `/${encodeURIComponent(folderId)}`),
    );
  },

  moveFolder({ workspaceId, folderId, parentId }) {
    return request<LibraryFolder>(
      "PUT",
      foldersPath(workspaceId, `/${encodeURIComponent(folderId)}/parent`),
      { body: { parent_id: parentId } },
    );
  },

  async moveItems({ workspaceId, artifactIds, folderId }) {
    await request<never>(
      "PUT",
      `/v1/workspaces/${encodeURIComponent(workspaceId)}/library/placements`,
      { body: { artifact_ids: [...artifactIds], folder_id: folderId } },
    );
  },
};

const useRealApi = process.env.NEXT_PUBLIC_LIBRARY_FOLDERS_API === "real";

/** The real routes once they exist; the browser mock until then. */
export const libraryFoldersApi: LibraryFoldersApi = useRealApi
  ? httpLibraryFolders
  : mockLibraryFolders;

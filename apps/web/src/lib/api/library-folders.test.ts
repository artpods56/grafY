import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./client";
import {
  LibraryFolderCycleError,
  LibraryFolderNameTakenError,
  LibraryFolderNotEmptyError,
  libraryFoldersApi,
} from "./library-folders";

/**
 * The seam between the six Library routes and the panel.
 *
 * The route tests prove the server refuses by code and the panel tests prove it
 * phrases an error class; this proves the middle link, that a code on the wire
 * becomes that class.
 */

const WORKSPACE = "workspace/1";
const FOLDERS_PATH = "/api/v1/workspaces/workspace%2F1/library/folders";
const ARTIFACTS_PATH = "/api/v1/workspaces/workspace%2F1/library/artifacts";
const PLACEMENTS_PATH = "/api/v1/workspaces/workspace%2F1/library/placements";

const FIELDWORK = {
  folder_id: "folder-fieldwork",
  workspace_id: WORKSPACE,
  parent_id: null,
  name: "Fieldwork",
  created_at: "2026-09-11T12:00:00Z",
  updated_at: "2026-09-11T12:00:00Z",
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** What a real refusal looks like on the wire: `{detail, code, error_id}`. */
function refusal(status: number, code: string, detail: string): Response {
  return jsonResponse({ detail, code, error_id: "error-1" }, status);
}

type RecordedRequest = { path: string; init: RequestInit };
const requests: RecordedRequest[] = [];

function stubServer(respond: (path: string) => Response): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit = {}) => {
      requests.push({ path, init });
      return respond(path);
    }),
  );
}

function lastRequest(): RecordedRequest {
  const request = requests.at(-1);
  if (!request) throw new Error("The seam made no request");
  return request;
}

function bodyOf(request: RecordedRequest): unknown {
  return JSON.parse(request.init.body as string);
}

afterEach(() => {
  vi.unstubAllGlobals();
  requests.length = 0;
});

describe("libraryFoldersApi", () => {
  it("reads the tree as every folder plus the artifacts already filed", async () => {
    stubServer((path) =>
      path === FOLDERS_PATH
        ? jsonResponse({ folders: [FIELDWORK] })
        : path === ARTIFACTS_PATH
          ? jsonResponse({
              items: [
                {
                  artifact: { artifact_id: "artifact-filed" },
                  folder_id: FIELDWORK.folder_id,
                },
                // An artifact saved before placements existed reads as root.
                { artifact: { artifact_id: "artifact-root" } },
              ],
            })
          : jsonResponse({ detail: "unhandled" }, 500),
    );

    const tree = await libraryFoldersApi.listTree(WORKSPACE);

    expect(requests.map((request) => request.path)).toEqual([
      FOLDERS_PATH,
      ARTIFACTS_PATH,
    ]);
    expect(tree.folders).toEqual([FIELDWORK]);
    expect(
      tree.items.map((item) => [item.artifact.artifact_id, item.folder_id]),
    ).toEqual([
      ["artifact-filed", FIELDWORK.folder_id],
      ["artifact-root", null],
    ]);
  });

  it("creates a nested folder by naming its parent", async () => {
    stubServer(() =>
      jsonResponse({ ...FIELDWORK, folder_id: "folder-september" }, 201),
    );

    const folder = await libraryFoldersApi.createFolder({
      workspaceId: WORKSPACE,
      name: "September",
      parentId: FIELDWORK.folder_id,
    });

    expect(lastRequest().path).toBe(FOLDERS_PATH);
    expect(lastRequest().init.method).toBe("POST");
    expect(bodyOf(lastRequest())).toEqual({
      name: "September",
      parent_id: FIELDWORK.folder_id,
    });
    expect(folder.folder_id).toBe("folder-september");
  });

  it("files every artifact of one drop in a single placement request", async () => {
    stubServer(() => new Response(null, { status: 204 }));

    await libraryFoldersApi.moveItems({
      workspaceId: WORKSPACE,
      artifactIds: ["artifact-1", "artifact-2"],
      folderId: FIELDWORK.folder_id,
    });

    expect(lastRequest().path).toBe(PLACEMENTS_PATH);
    expect(lastRequest().init.method).toBe("PUT");
    expect(bodyOf(lastRequest())).toEqual({
      artifact_ids: ["artifact-1", "artifact-2"],
      folder_id: FIELDWORK.folder_id,
    });
  });

  it("unfiles artifacts by naming no folder", async () => {
    stubServer(() => new Response(null, { status: 204 }));

    await libraryFoldersApi.moveItems({
      workspaceId: WORKSPACE,
      artifactIds: ["artifact-1"],
      folderId: null,
    });

    expect(lastRequest().path).toBe(PLACEMENTS_PATH);
    expect(bodyOf(lastRequest())).toEqual({
      artifact_ids: ["artifact-1"],
      folder_id: null,
    });
  });

  it("turns a refused delete into the error naming the folder", async () => {
    stubServer(() =>
      refusal(
        409,
        "library.folder_not_empty",
        "Move the contents out before deleting this folder",
      ),
    );

    const error = await libraryFoldersApi
      .deleteFolder({ workspaceId: WORKSPACE, folderId: FIELDWORK.folder_id })
      .then(() => null)
      .catch((raised: unknown) => raised);

    expect(error).toBeInstanceOf(LibraryFolderNotEmptyError);
    expect((error as LibraryFolderNotEmptyError).folderId).toBe(
      FIELDWORK.folder_id,
    );
  });

  it("turns a refused move into the error naming the folder and its parent", async () => {
    stubServer(() =>
      refusal(
        422,
        "library.folder_cycle",
        "A folder cannot be moved inside itself",
      ),
    );

    const error = await libraryFoldersApi
      .moveFolder({
        workspaceId: WORKSPACE,
        folderId: FIELDWORK.folder_id,
        parentId: "folder-september",
      })
      .then(() => null)
      .catch((raised: unknown) => raised);

    expect(error).toBeInstanceOf(LibraryFolderCycleError);
    expect([
      (error as LibraryFolderCycleError).folderId,
      (error as LibraryFolderCycleError).parentId,
    ]).toEqual([FIELDWORK.folder_id, "folder-september"]);
  });

  it("turns a taken sibling name into the error naming what the user typed", async () => {
    stubServer(() =>
      refusal(
        409,
        "library.folder_name_conflict",
        "A folder with this name already exists here",
      ),
    );

    const created = await libraryFoldersApi
      .createFolder({
        workspaceId: WORKSPACE,
        name: "fieldwork",
        parentId: null,
      })
      .then(() => null)
      .catch((raised: unknown) => raised);
    const renamed = await libraryFoldersApi
      .renameFolder({
        workspaceId: WORKSPACE,
        folderId: FIELDWORK.folder_id,
        name: "FIELDWORK",
      })
      .then(() => null)
      .catch((raised: unknown) => raised);

    expect(created).toBeInstanceOf(LibraryFolderNameTakenError);
    expect((created as LibraryFolderNameTakenError).folderName).toBe(
      "fieldwork",
    );
    expect(renamed).toBeInstanceOf(LibraryFolderNameTakenError);
    expect((renamed as LibraryFolderNameTakenError).folderName).toBe(
      "FIELDWORK",
    );
  });

  it("passes a failure that is not a folder rule through with its code", async () => {
    stubServer(() => refusal(404, "resource.not_found", "Not found"));

    const error = await libraryFoldersApi
      .renameFolder({
        workspaceId: WORKSPACE,
        folderId: "folder-gone",
        name: "Anything",
      })
      .then(() => null)
      .catch((raised: unknown) => raised);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
    expect((error as ApiError).code).toBe("resource.not_found");
  });
});

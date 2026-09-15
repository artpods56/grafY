import { request } from "./client";
import type {
  LibraryItem,
  LibraryList,
  SaveRunArtifactRequest,
  SaveUploadedArtifactRequest,
} from "./contract";

function libraryPath(workspaceId: string, suffix = ""): string {
  return `/v1/workspaces/${encodeURIComponent(workspaceId)}/library/artifacts${suffix}`;
}

export function listLibraryArtifacts(workspaceId: string) {
  return request<LibraryList>("GET", libraryPath(workspaceId));
}

export function saveRunArtifactToLibrary(
  workspaceId: string,
  body: SaveRunArtifactRequest,
) {
  return request<LibraryItem>("POST", libraryPath(workspaceId, "/from-run"), {
    body,
  });
}

export function saveUploadedArtifactToLibrary(
  workspaceId: string,
  body: SaveUploadedArtifactRequest,
) {
  return request<LibraryItem>("POST", libraryPath(workspaceId, "/from-upload"), {
    body,
  });
}

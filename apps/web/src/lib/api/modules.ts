import { request } from "./client";
import type {
  ModuleLibraryEntry,
  ModuleList,
  PublishModuleReleaseRequest,
} from "./contract";

export function listWorkspaceModules(workspaceId: string) {
  return request<ModuleList>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/modules`,
  );
}

export function publishModuleRelease(
  workspaceId: string,
  body: PublishModuleReleaseRequest,
) {
  return request<ModuleLibraryEntry>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/modules/publish`,
    { body },
  );
}

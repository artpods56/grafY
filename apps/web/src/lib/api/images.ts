import { API_BASE, request } from "./client";
import type { paths } from "./generated/grafy";

type InfoRoute =
  paths["/v1/workspaces/{workspace_id}/artifacts/{artifact_id}/image/info"]["get"];
export type ImageInfo =
  InfoRoute["responses"][200]["content"]["application/json"];
type TileRoute =
  paths["/v1/workspaces/{workspace_id}/artifacts/{artifact_id}/image/tiles/{z}/{x}/{y}.{extension}"]["get"];

export function imagePath(workspaceId: string, artifactId: string): string {
  return `/v1/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}/image`;
}

export function getImageInfo(path: string, page: number, signal: AbortSignal) {
  return request<ImageInfo>("GET", `${path}/info?page=${page}`, { signal });
}

export function imageTileUrl(
  path: string,
  page: number,
  tile: Pick<TileRoute["parameters"]["path"], "z" | "x" | "y" | "extension">,
) {
  return `${API_BASE}${path}/tiles/${tile.z}/${tile.x}/${tile.y}.${tile.extension}?page=${page}`;
}

export function imageThumbnailUrl(path: string, page: number) {
  return `${API_BASE}${path}/thumbnail?edge=512&page=${page}`;
}

import { API_BASE, putUploadBytes, request } from "./client";
import type {
  GeoFeatureQuery,
  GeoRenderDescriptor,
  TableCell,
  TablePage,
  TableSchema,
  UploadResponse,
  UploadTarget,
} from "./contract";

export type ArtifactInteractionScalar = string | number | boolean | null;

export interface TableExactMatchInput {
  values: Record<string, ArtifactInteractionScalar>;
}

export interface TableExactMatchGroupInput {
  rows: TableExactMatchInput[];
}

export interface TableQueryInput {
  filter_groups: TableExactMatchGroupInput[];
  highlight_groups: TableExactMatchGroupInput[];
  offset: number;
  limit: number;
  column_ids?: string[];
  max_cell_characters: number;
}

export interface GeoFeatureQueryInput {
  rows: TableExactMatchInput[];
}

export function artifactContentUrl(
  workspaceId: string,
  contentUrl: string | null | undefined,
): string | null {
  if (!contentUrl) return null;

  if (/^[a-z][a-z\d+.-]*:/i.test(contentUrl)) return contentUrl;
  if (contentUrl.startsWith("/api/")) return contentUrl;
  if (contentUrl.startsWith("/v1/")) return `${API_BASE}${contentUrl}`;

  const resolved = new URL(
    contentUrl,
    `https://grafy.invalid/api/v1/workspaces/${encodeURIComponent(workspaceId)}/`,
  );
  return `${resolved.pathname}${resolved.search}${resolved.hash}`;
}

/**
 * Resolve the download URL for an artifact in the given format. The artifact
 * summary carries `download_formats`; the caller picks one format and builds
 * the relative `/download` URL.
 */
/**
 * Resolve the URL that serves an artifact's own bytes, typed with its stored
 * content type. Unlike `/download`, it asks for no export format, so it shows
 * any artifact the caller can name by id — a library file or a run output.
 */
export function artifactInlineContentUrl(
  workspaceId: string,
  artifactId: string,
): string {
  return artifactContentUrl(
    workspaceId,
    `./artifacts/${encodeURIComponent(artifactId)}/content`,
  ) as string;
}

export function artifactDownloadUrl(
  workspaceId: string,
  artifactId: string,
  format: string,
): string {
  return artifactContentUrl(
    workspaceId,
    `./artifacts/${encodeURIComponent(artifactId)}/download?format=${encodeURIComponent(format)}`,
  ) as string;
}

export function getArtifactTablePage(
  workspaceId: string,
  artifactId: string,
  offset: number,
  limit: number,
  columnIds: readonly string[],
  maxCellCharacters: number,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
    max_cell_characters: String(maxCellCharacters),
  });
  for (const columnId of columnIds) {
    query.append("column_ids", columnId);
  }
  return request<TablePage>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}/table/page?${query}`,
    { signal },
  );
}

export function getArtifactTableSchema(
  workspaceId: string,
  artifactId: string,
  signal?: AbortSignal,
) {
  return request<TableSchema>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}/table/schema`,
    { signal },
  );
}

export function queryArtifactTablePage(
  workspaceId: string,
  artifactId: string,
  query: TableQueryInput,
  signal?: AbortSignal,
) {
  return request<TablePage>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}/table/query`,
    { body: query, signal },
  );
}

export function getArtifactGeoRender(
  workspaceId: string,
  artifactId: string,
  signal?: AbortSignal,
) {
  return request<GeoRenderDescriptor>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}/geo/render`,
    { signal },
  );
}

export function queryArtifactGeoFeatures(
  workspaceId: string,
  artifactId: string,
  query: GeoFeatureQueryInput,
  signal?: AbortSignal,
) {
  return request<GeoFeatureQuery>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}/geo/query`,
    { body: query, signal },
  );
}

export function getArtifactTableCell(
  workspaceId: string,
  artifactId: string,
  rowIndex: number,
  columnId: string,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    row_index: String(rowIndex),
    column_id: columnId,
  });
  return request<TableCell>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}/table/cell?${query}`,
    { signal },
  );
}

/**
 * Upload a file the person picked or dropped, and return what it became.
 *
 * Three calls, because the API decides who holds the bytes: reserve a target,
 * send the file to that target (this API, or object storage behind a signed URL),
 * then complete, which is where the file turns into an artifact. The caller then
 * decides whether the artifact joins the Library — an upload that lands in
 * storage is not yet something anyone else can see.
 */
export async function uploadFile(
  workspaceId: string,
  file: File,
  signal?: AbortSignal,
): Promise<UploadResponse> {
  const path = `/v1/workspaces/${encodeURIComponent(workspaceId)}/uploads`;
  const target = await request<UploadTarget>("POST", path, {
    body: {
      filename: file.name,
      byte_size: file.size,
      content_type: file.type || null,
    },
    signal,
  });
  await putUploadBytes(
    { ...target, url: uploadTargetUrl(target) },
    file,
    file.type || "application/octet-stream",
    signal,
  );
  return request<UploadResponse>(
    "POST",
    `${path}/${encodeURIComponent(target.upload_id)}/complete`,
    { body: {}, signal },
  );
}

/**
 * Where the bytes actually go. A storage target is a signed absolute URL; an
 * API-owned target is a path relative to the API base, and the base is this
 * client's business, not the server's.
 */
function uploadTargetUrl(target: UploadTarget): string {
  const url = target.url;
  if (/^[a-z][a-z0-9+.-]*:/i.test(url)) return url;
  return url.startsWith(API_BASE) ? url : `${API_BASE}${url}`;
}

import { request } from "./client";
import type {
  CreateTemplateRequest,
  GraphFolderList,
  GraphTemplate,
  InstantiateTemplateRequest,
  TemplateInstantiationResponse,
  TemplateList,
  UpdateTemplateMetadataRequest,
} from "./contract";

export function listWorkspaceGraphFolders(workspaceId: string) {
  return request<GraphFolderList>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/graph-folders`,
  );
}

export function listWorkspaceTemplates(
  workspaceId: string,
  options: { query?: string; includeArchived?: boolean } = {},
) {
  const params = new URLSearchParams();
  if (options.query?.trim()) params.set("q", options.query.trim());
  if (options.includeArchived) params.set("include_archived", "true");
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return request<TemplateList>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/templates${query}`,
  );
}

export function getWorkspaceTemplate(workspaceId: string, templateId: string) {
  return request<GraphTemplate>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/templates/${encodeURIComponent(templateId)}`,
  );
}

export function createWorkspaceTemplate(
  workspaceId: string,
  body: CreateTemplateRequest,
) {
  return request<GraphTemplate>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/templates`,
    { body },
  );
}

export function updateWorkspaceTemplate(
  workspaceId: string,
  templateId: string,
  body: UpdateTemplateMetadataRequest,
) {
  return request<GraphTemplate>(
    "PUT",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/templates/${encodeURIComponent(templateId)}`,
    { body },
  );
}

export function archiveWorkspaceTemplate(
  workspaceId: string,
  templateId: string,
) {
  return request<GraphTemplate>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/templates/${encodeURIComponent(templateId)}/archive`,
  );
}

export function instantiateWorkspaceTemplate(
  sourceWorkspaceId: string,
  templateId: string,
  body: InstantiateTemplateRequest,
) {
  return request<TemplateInstantiationResponse>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(sourceWorkspaceId)}/templates/${encodeURIComponent(templateId)}/instantiate`,
    { body },
  );
}

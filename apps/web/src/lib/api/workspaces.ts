import { request } from "./client";
import type {
  CatalogPack,
  SetPackSubscriptionRequest,
  PersonalAccessToken,
  PersonalAccessTokenCreated,
  PersonalAccessTokenCreateRequest,
  Workspace,
  WorkspaceCreateRequest,
  WorkspaceInvitation,
  WorkspaceInvitationCandidate,
  WorkspaceInvitationCandidateRequest,
  WorkspaceInvitationCreateRequest,
  WorkspaceInvitationForRecipient,
  WorkspaceMember,
  WorkspaceMemberRoleRequest,
} from "./contract";

export function workspacePacksPath(workspaceId: string): string {
  return `/v1/workspaces/${encodeURIComponent(workspaceId)}/packs`;
}

export function listWorkspacePacks(workspaceId: string) {
  return request<readonly CatalogPack[]>(
    "GET",
    workspacePacksPath(workspaceId),
  );
}

export function setWorkspacePack(
  workspaceId: string,
  slug: string,
  body: SetPackSubscriptionRequest,
) {
  return request<CatalogPack>(
    "PUT",
    `${workspacePacksPath(workspaceId)}/${encodeURIComponent(slug)}`,
    { body },
  );
}

export function listWorkspaces(signal?: AbortSignal) {
  return request<readonly Workspace[]>("GET", "/v1/workspaces", { signal });
}

export function createWorkspace(body: WorkspaceCreateRequest) {
  return request<Workspace>("POST", "/v1/workspaces", { body });
}

export function listWorkspaceMembers(
  workspaceId: string,
  signal?: AbortSignal,
) {
  return request<readonly WorkspaceMember[]>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/members`,
    { signal },
  );
}

export function resolveWorkspaceInvitationCandidate(
  workspaceId: string,
  body: WorkspaceInvitationCandidateRequest,
) {
  return request<WorkspaceInvitationCandidate>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/invitation-candidates/resolve`,
    { body },
  );
}

export function createWorkspaceInvitation(
  workspaceId: string,
  body: WorkspaceInvitationCreateRequest,
) {
  return request<WorkspaceInvitation>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/invitations`,
    { body },
  );
}

export function listWorkspaceInvitations(
  workspaceId: string,
  signal?: AbortSignal,
) {
  return request<readonly WorkspaceInvitation[]>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/invitations`,
    { signal },
  );
}

export function cancelWorkspaceInvitation(
  workspaceId: string,
  invitationId: string,
) {
  return request<undefined>(
    "DELETE",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/invitations/${encodeURIComponent(invitationId)}`,
  );
}

export function listMyWorkspaceInvitations(signal?: AbortSignal) {
  return request<readonly WorkspaceInvitationForRecipient[]>(
    "GET",
    "/v1/me/invitations",
    { signal },
  );
}

export function acceptWorkspaceInvitation(invitationId: string) {
  return request<Workspace>(
    "POST",
    `/v1/me/invitations/${encodeURIComponent(invitationId)}/accept`,
  );
}

export function declineWorkspaceInvitation(invitationId: string) {
  return request<undefined>(
    "POST",
    `/v1/me/invitations/${encodeURIComponent(invitationId)}/decline`,
  );
}

export function changeWorkspaceMemberRole(
  workspaceId: string,
  userId: string,
  body: WorkspaceMemberRoleRequest,
) {
  return request<WorkspaceMember>(
    "PATCH",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(userId)}`,
    { body },
  );
}

export function removeWorkspaceMember(workspaceId: string, userId: string) {
  return request<undefined>(
    "DELETE",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(userId)}`,
  );
}

export function listPersonalAccessTokens(
  workspaceId: string,
  signal?: AbortSignal,
) {
  return request<readonly PersonalAccessToken[]>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/personal-access-tokens`,
    { signal },
  );
}

export function createPersonalAccessToken(
  workspaceId: string,
  body: PersonalAccessTokenCreateRequest,
) {
  return request<PersonalAccessTokenCreated>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/personal-access-tokens`,
    { body },
  );
}

export function revokePersonalAccessToken(
  workspaceId: string,
  tokenId: string,
) {
  return request<undefined>(
    "DELETE",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/personal-access-tokens/${encodeURIComponent(tokenId)}`,
  );
}

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  acceptWorkspaceInvitation,
  cancelWorkspaceInvitation,
  changeWorkspaceMemberRole,
  createPersonalAccessToken,
  createWorkspaceInvitation,
  createWorkspace,
  declineWorkspaceInvitation,
  listMyWorkspaceInvitations,
  listPersonalAccessTokens,
  listWorkspaceMembers,
  listWorkspaceInvitations,
  listWorkspaces,
  removeWorkspaceMember,
  revokePersonalAccessToken,
  resolveWorkspaceInvitationCandidate,
} from "./workspaces";

afterEach(() => vi.unstubAllGlobals());

describe("workspace API client", () => {
  it("uses UUID workspace paths and generated request bodies", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((_: string, init: RequestInit) => {
        const status = init.method === "DELETE" ? 204 : 200;
        return Promise.resolve(
          new Response(status === 204 ? null : "{}", { status }),
        );
      });
    vi.stubGlobal("fetch", fetchMock);
    const workspaceId = "workspace-uuid";
    const userId = "user-uuid";

    await listWorkspaces();
    await createWorkspace({ name: "Shared", slug: "shared" });
    await listWorkspaceMembers(workspaceId);
    await resolveWorkspaceInvitationCandidate(workspaceId, {
      email: "person@example.com",
    });
    await createWorkspaceInvitation(workspaceId, {
      email: "person@example.com",
      role: "viewer",
    });
    await listWorkspaceInvitations(workspaceId);
    await cancelWorkspaceInvitation(workspaceId, "invite-uuid");
    await listMyWorkspaceInvitations();
    await acceptWorkspaceInvitation("invite-uuid");
    await declineWorkspaceInvitation("invite-uuid");
    await changeWorkspaceMemberRole(workspaceId, userId, { role: "editor" });
    await removeWorkspaceMember(workspaceId, userId);
    await listPersonalAccessTokens(workspaceId);
    await createPersonalAccessToken(workspaceId, {
      label: "Plugin publishing",
      scopes: ["publish_plugin"],
      expires_at: "2026-09-09T12:00:00Z",
    });
    await revokePersonalAccessToken(workspaceId, "token-uuid");

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      "/api/v1/workspaces",
      "/api/v1/workspaces",
      "/api/v1/workspaces/workspace-uuid/members",
      "/api/v1/workspaces/workspace-uuid/invitation-candidates/resolve",
      "/api/v1/workspaces/workspace-uuid/invitations",
      "/api/v1/workspaces/workspace-uuid/invitations",
      "/api/v1/workspaces/workspace-uuid/invitations/invite-uuid",
      "/api/v1/me/invitations",
      "/api/v1/me/invitations/invite-uuid/accept",
      "/api/v1/me/invitations/invite-uuid/decline",
      "/api/v1/workspaces/workspace-uuid/members/user-uuid",
      "/api/v1/workspaces/workspace-uuid/members/user-uuid",
      "/api/v1/workspaces/workspace-uuid/personal-access-tokens",
      "/api/v1/workspaces/workspace-uuid/personal-access-tokens",
      "/api/v1/workspaces/workspace-uuid/personal-access-tokens/token-uuid",
    ]);
    expect(JSON.parse(fetchMock.mock.calls[1]?.[1].body as string)).toEqual({
      name: "Shared",
      slug: "shared",
    });
    expect(JSON.parse(fetchMock.mock.calls[3]?.[1].body as string)).toEqual({
      email: "person@example.com",
    });
    expect(JSON.parse(fetchMock.mock.calls[4]?.[1].body as string)).toEqual({
      email: "person@example.com",
      role: "viewer",
    });
    expect(JSON.parse(fetchMock.mock.calls[10]?.[1].body as string)).toEqual({
      role: "editor",
    });
    expect(JSON.parse(fetchMock.mock.calls[13]?.[1].body as string)).toEqual({
      label: "Plugin publishing",
      scopes: ["publish_plugin"],
      expires_at: "2026-09-09T12:00:00Z",
    });
  });
});

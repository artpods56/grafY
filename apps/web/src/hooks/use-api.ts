"use client";

import * as React from "react";
import useSWR, { useSWRConfig, type ScopedMutator } from "swr";
import {
  listWorkspaceMembers,
  listWorkspaces,
  type NodeRegistry,
  type ProjectList,
  type Workspace,
  type WorkspaceInvitation,
  type WorkspaceInvitationForRecipient,
  type WorkspaceMember,
  listMyWorkspaceInvitations,
  listWorkspaceInvitations,
} from "@/lib/api";

/**
 * Keyed SWR hooks over the Grafy API (global fetcher is `apiFetcher`).
 *
 * Project summaries come from two endpoints that share one authoritative
 * contract: node and edge counts plus `updated_at` always describe the
 * collaborative draft head, `revision` is the durable checkpoint revision,
 * and `draft_pending` marks a head that is ahead of that checkpoint.
 */

/** Every Project the person can reach, across their Workspaces. */
export const ALL_PROJECTS_KEY = "/v1/me/projects";

/** The Projects of one Workspace. */
export function workspaceProjectsKey(workspaceId: string): string {
  return `/v1/workspaces/${encodeURIComponent(workspaceId)}/projects`;
}

/** Revalidate every discovery surface a Project mutation touches. */
export async function revalidateProjectSummaries(
  mutate: ScopedMutator,
  workspaceId?: string,
): Promise<void> {
  const keys = [
    workspaceId ? workspaceProjectsKey(workspaceId) : null,
    ALL_PROJECTS_KEY,
  ];
  await Promise.all(
    keys.filter((key) => key !== null).map((key) => mutate(key)),
  );
}

/** Revalidate both Project-list caches from any component. */
export function useProjectSummaryRefresh(): (
  workspaceId?: string,
) => Promise<void> {
  const { mutate } = useSWRConfig();
  return React.useCallback(
    (workspaceId?: string) => revalidateProjectSummaries(mutate, workspaceId),
    [mutate],
  );
}

export function useNodeRegistry(workspaceId?: string) {
  return useSWR<NodeRegistry>(
    workspaceId
      ? `/v1/workspaces/${encodeURIComponent(workspaceId)}/nodes`
      : null,
  );
}

export function useWorkspaceProjects(workspaceId?: string) {
  return useSWR<ProjectList>(
    workspaceId ? workspaceProjectsKey(workspaceId) : null,
  );
}

export function useWorkspaces(userId: string | undefined) {
  return useSWR<readonly Workspace[]>(
    userId ? ["workspaces", userId] : null,
    () => listWorkspaces(),
  );
}

export function useWorkspaceMembers(
  userId: string | undefined,
  workspaceId: string | undefined,
) {
  return useSWR<readonly WorkspaceMember[]>(
    userId && workspaceId ? ["workspace-members", userId, workspaceId] : null,
    () => listWorkspaceMembers(workspaceId!),
  );
}

export function useWorkspaceInvitations(
  userId: string | undefined,
  workspaceId: string | undefined,
) {
  return useSWR<readonly WorkspaceInvitation[]>(
    userId && workspaceId
      ? ["workspace-invitations", userId, workspaceId]
      : null,
    () => listWorkspaceInvitations(workspaceId!),
  );
}

export function useMyWorkspaceInvitations(userId: string | undefined) {
  return useSWR<readonly WorkspaceInvitationForRecipient[]>(
    userId ? ["my-workspace-invitations", userId] : null,
    () => listMyWorkspaceInvitations(),
  );
}

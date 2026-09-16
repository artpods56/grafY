"use client";

import * as React from "react";
import useSWR, { useSWRConfig, type ScopedMutator } from "swr";
import {
  type GraphBrowserGraph,
  type GraphBrowserList,
  listWorkspaceMembers,
  listWorkspaces,
  type NodeRegistry,
  type SavedGraphList,
  type Workspace,
  type WorkspaceInvitation,
  type WorkspaceInvitationForRecipient,
  type WorkspaceMember,
  listMyWorkspaceInvitations,
  listWorkspaceInvitations,
} from "@/lib/api";
import { request } from "@/lib/api/client";

/**
 * Keyed SWR hooks over the Grafy API (global fetcher is `apiFetcher`).
 *
 * Graph summaries come from two endpoints that share one authoritative
 * contract: node and edge counts plus `updated_at` always describe the
 * collaborative draft head, `revision` is the durable checkpoint revision,
 * and `draft_pending` marks a head that is ahead of that checkpoint.
 */

/** Every graph the user can reach, across workspaces. */
export const ALL_GRAPHS_KEY = "/v1/me/graphs";

/** Saved graphs inside one workspace. */
export function workspaceGraphsKey(workspaceId: string): string {
  return `/v1/workspaces/${encodeURIComponent(workspaceId)}/graphs`;
}

/** Revalidate every discovery surface affected by a graph mutation. */
export async function revalidateGraphSummaries(
  mutate: ScopedMutator,
  workspaceId?: string,
): Promise<void> {
  const keys = [
    workspaceId ? workspaceGraphsKey(workspaceId) : null,
    ALL_GRAPHS_KEY,
  ];
  await Promise.all(
    keys.filter((key) => key !== null).map((key) => mutate(key)),
  );
}

/** Revalidate both graph-list caches from any component. */
export function useGraphSummaryRefresh(): (
  workspaceId?: string,
) => Promise<void> {
  const { mutate } = useSWRConfig();
  return React.useCallback(
    (workspaceId?: string) => revalidateGraphSummaries(mutate, workspaceId),
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

export function useSavedGraphs(workspaceId?: string) {
  return useSWR<SavedGraphList>(
    workspaceId ? workspaceGraphsKey(workspaceId) : null,
  );
}

export function useWorkspaces(userId: string | undefined) {
  return useSWR<readonly Workspace[]>(
    userId ? ["workspaces", userId] : null,
    () => listWorkspaces(),
  );
}

export type LocatedGraph = GraphBrowserGraph;

export interface AllWorkspacesGraphsResult {
  graphs: readonly LocatedGraph[] | null;
  error: Error | null;
  isLoading: boolean;
  /** True while a revalidation is in flight over cached summaries. */
  isRefreshing: boolean;
  retry: () => Promise<void>;
}

export function useAllWorkspacesGraphs(
  workspaces: readonly Workspace[] | undefined,
): AllWorkspacesGraphsResult {
  const load = useSWR<GraphBrowserList>(
    workspaces && workspaces.length > 0 ? ALL_GRAPHS_KEY : null,
    (path: string) => request<GraphBrowserList>("GET", path),
    { shouldRetryOnError: false },
  );
  const graphs =
    !workspaces || (workspaces.length > 0 && !load.data)
      ? null
      : (load.data?.graphs ?? []);

  return {
    graphs,
    error: load.error instanceof Error ? load.error : null,
    isLoading: Boolean(workspaces?.length) && load.isLoading,
    isRefreshing: load.isValidating && !load.isLoading,
    retry: async () => {
      if (workspaces?.length) await load.mutate();
    },
  };
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

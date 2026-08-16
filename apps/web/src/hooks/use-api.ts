"use client";

import useSWR from "swr";
import {
  type GraphBrowserList,
  listWorkspaceMembers,
  listWorkspaces,
  type NodeRegistry,
  type SavedGraphList,
  type Workspace,
  type WorkspaceMember,
  type AgentEnvironmentList,
} from "@/lib/api";
import { request } from "@/lib/api/client";

/** Keyed SWR hooks over the Grafy API (global fetcher is `apiFetcher`). */

export function useNodeRegistry(workspaceId?: string) {
  return useSWR<NodeRegistry>(
    workspaceId
      ? `/v1/workspaces/${encodeURIComponent(workspaceId)}/nodes`
      : null,
  );
}

export function useAgentEnvironments(workspaceId?: string) {
  return useSWR<AgentEnvironmentList>(
    workspaceId
      ? `/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-authoring/environments`
      : null,
  );
}

export function useSavedGraphs(workspaceId?: string) {
  return useSWR<SavedGraphList>(
    workspaceId
      ? `/v1/workspaces/${encodeURIComponent(workspaceId)}/graphs`
      : null,
  );
}

export function useWorkspaces(userId: string | undefined) {
  return useSWR<readonly Workspace[]>(
    userId ? ["workspaces", userId] : null,
    () => listWorkspaces(),
  );
}

export type GraphLocation = Pick<
  Workspace,
  "id" | "slug" | "name" | "kind"
>;

export interface LocatedGraph {
  id: string;
  name: string;
  revision: number;
  node_count: number;
  edge_count: number;
  updated_at: string;
  location: GraphLocation;
  folder: { id: string; name: string } | null;
  archived: boolean;
  starred: boolean;
  last_opened_at: string | null;
}

export interface AllWorkspacesGraphsResult {
  graphs: readonly LocatedGraph[] | null;
  error: Error | null;
  isLoading: boolean;
  retry: () => Promise<void>;
}

export function useAllWorkspacesGraphs(
  workspaces: readonly Workspace[] | undefined,
): AllWorkspacesGraphsResult {
  const load = useSWR<GraphBrowserList>(
    workspaces && workspaces.length > 0 ? "/v1/me/graphs" : null,
    (path: string) => request<GraphBrowserList>("GET", path),
    { shouldRetryOnError: false },
  );
  const graphs =
    !workspaces || (workspaces.length > 0 && !load.data)
      ? null
      : (load.data?.graphs ?? []).map((graph) => ({
          id: graph.id,
          name: graph.draft.name,
          revision: graph.draft.checkpoint_revision,
          node_count: graph.draft.node_count,
          edge_count: graph.draft.edge_count,
          updated_at: graph.updated_at,
          location: graph.location,
          folder: graph.folder,
          archived: graph.archived,
          starred: graph.starred,
          last_opened_at: graph.last_opened_at,
        }));

  return {
    graphs,
    error: load.error instanceof Error ? load.error : null,
    isLoading: Boolean(workspaces?.length) && load.isLoading,
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
    userId && workspaceId
      ? ["workspace-members", userId, workspaceId]
      : null,
    () => listWorkspaceMembers(workspaceId!),
  );
}

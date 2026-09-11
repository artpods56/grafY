// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Workspace } from "@/lib/api/contract";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const apiMocks = vi.hoisted(() => ({
  request: vi.fn(),
  listWorkspaces: vi.fn(),
  listWorkspaceMembers: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  listWorkspaces: apiMocks.listWorkspaces,
  listWorkspaceMembers: apiMocks.listWorkspaceMembers,
}));

vi.mock("@/lib/api/client", () => ({
  request: apiMocks.request,
}));

import {
  ALL_GRAPHS_KEY,
  type AllWorkspacesGraphsResult,
  revalidateGraphSummaries,
  useAllWorkspacesGraphs,
  workspaceGraphsKey,
} from "./use-api";

const personal: Workspace = {
  id: "workspace-personal",
  name: "Personal workspace",
  slug: "personal",
  kind: "personal",
  role: "owner",
  capabilities: ["view_graph", "create_graph"],
};

const team: Workspace = {
  id: "workspace-team",
  name: "Atlas",
  slug: "atlas",
  kind: "shared",
  role: "editor",
  capabilities: ["view_graph", "create_graph"],
};

let latest: AllWorkspacesGraphsResult | undefined;

function captureLatest(value: AllWorkspacesGraphsResult) {
  latest = value;
}

function Harness({ workspaces }: { workspaces: readonly Workspace[] }) {
  const value = useAllWorkspacesGraphs(workspaces);
  React.useEffect(() => captureLatest(value), [value]);
  return <span>{value.graphs?.length ?? "loading"}</span>;
}

function browserGraph(
  id: string,
  sequence: { head_sequence: number; checkpoint_sequence: number },
) {
  return {
    id,
    location: {
      id: personal.id,
      slug: personal.slug,
      name: personal.name,
      kind: personal.kind,
    },
    folder: null,
    archived: false,
    archived_at: null,
    starred: false,
    last_opened_at: null,
    updated_at: "2026-08-10T12:00:00Z",
    draft: {
      name: id,
      checkpoint_revision: 1,
      updated_at: "2026-08-10T12:00:00Z",
      node_count: 2,
      edge_count: 1,
      ...sequence,
    },
    creator: null,
  };
}

async function renderGraphs(workspaces: readonly Workspace[]) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <SWRConfig
        value={{
          provider: () => new Map(),
          dedupingInterval: 0,
          revalidateOnFocus: false,
        }}
      >
        <Harness workspaces={workspaces} />
      </SWRConfig>,
    );
  });
  await vi.waitFor(() => expect(latest?.graphs).not.toBeNull());
  return root;
}

beforeEach(() => {
  latest = undefined;
  apiMocks.request.mockReset();
});

afterEach(() => {
  document.body.replaceChildren();
});

describe("useAllWorkspacesGraphs", () => {
  it("loads every authorized graph through one aggregate request", async () => {
    apiMocks.request.mockResolvedValue({
      graphs: [
        {
          id: "graph-1",
          location: {
            id: personal.id,
            slug: personal.slug,
            name: personal.name,
            kind: personal.kind,
          },
          folder: null,
          archived: false,
          archived_at: null,
          starred: true,
          last_opened_at: "2026-08-10T12:00:00Z",
          updated_at: "2026-08-10T12:00:00Z",
          draft: {
            name: "Invoice intake",
            head_sequence: 4,
            checkpoint_sequence: 3,
            checkpoint_revision: 3,
            updated_at: "2026-08-10T12:00:00Z",
            node_count: 2,
            edge_count: 1,
          },
          creator: null,
        },
      ],
    });

    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <SWRConfig
          value={{
            provider: () => new Map(),
            dedupingInterval: 0,
            revalidateOnFocus: false,
          }}
        >
          <Harness workspaces={[personal, team]} />
        </SWRConfig>,
      );
    });

    await vi.waitFor(() => expect(latest?.graphs).toHaveLength(1));
    expect(apiMocks.request).toHaveBeenCalledOnce();
    expect(apiMocks.request).toHaveBeenCalledWith("GET", "/v1/me/graphs");
    expect(latest?.graphs?.[0]?.location).toEqual({
      id: personal.id,
      slug: personal.slug,
      name: personal.name,
      kind: personal.kind,
    });
    expect(latest?.graphs?.[0]?.name).toBe("Invoice intake");
    expect(latest?.graphs?.[0]?.starred).toBe(true);
    expect(latest?.error).toBeNull();

    await act(async () => latest?.retry());
    await vi.waitFor(() => expect(apiMocks.request).toHaveBeenCalledTimes(2));

    await act(async () => root.unmount());
  });

  it("returns a settled true-empty result without issuing a malformed request", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <SWRConfig value={{ provider: () => new Map() }}>
          <Harness workspaces={[]} />
        </SWRConfig>,
      );
    });

    expect(latest?.graphs).toEqual([]);
    expect(latest?.isLoading).toBe(false);
    expect(apiMocks.request).not.toHaveBeenCalled();

    await act(async () => root.unmount());
  });

  it("labels a draft head that is ahead of the saved checkpoint", async () => {
    apiMocks.request.mockResolvedValue({
      graphs: [
        browserGraph("graph-pending", {
          head_sequence: 4,
          checkpoint_sequence: 3,
        }),
        browserGraph("graph-checkpointed", {
          head_sequence: 2,
          checkpoint_sequence: 2,
        }),
      ],
    });

    const root = await renderGraphs([personal]);

    expect(
      latest?.graphs?.map((graph) => [
        graph.name,
        graph.draft_pending,
        graph.revision,
      ]),
    ).toEqual([
      ["graph-pending", true, 1],
      ["graph-checkpointed", false, 1],
    ]);

    await act(async () => root.unmount());
  });
});

describe("graph summary cache invalidation", () => {
  it("refreshes every discovery surface affected by a workspace mutation", async () => {
    const mutate = vi.fn().mockResolvedValue(undefined);

    await revalidateGraphSummaries(mutate, personal.id);

    expect(mutate.mock.calls).toEqual([
      [workspaceGraphsKey(personal.id)],
      [ALL_GRAPHS_KEY],
    ]);
    expect(workspaceGraphsKey(personal.id)).toBe(
      "/v1/workspaces/workspace-personal/graphs",
    );
  });

  it("refreshes the cross-workspace list when no workspace is scoped", async () => {
    const mutate = vi.fn().mockResolvedValue(undefined);

    await revalidateGraphSummaries(mutate);

    expect(mutate.mock.calls).toEqual([[ALL_GRAPHS_KEY]]);
  });
});

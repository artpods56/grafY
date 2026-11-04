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
  ALL_PROJECTS_KEY,
  type AllWorkspacesProjectsResult,
  revalidateProjectSummaries,
  useAllWorkspacesProjects,
  workspaceProjectsKey,
} from "./use-api";

const personal: Workspace = {
  id: "workspace-personal",
  name: "Personal workspace",
  slug: "personal",
  kind: "personal",
  role: "owner",
  capabilities: ["view_project", "create_project"],
};

const team: Workspace = {
  id: "workspace-team",
  name: "Atlas",
  slug: "atlas",
  kind: "shared",
  role: "editor",
  capabilities: ["view_project", "create_project"],
};

let latest: AllWorkspacesProjectsResult | undefined;

function captureLatest(value: AllWorkspacesProjectsResult) {
  latest = value;
}

function Harness({ workspaces }: { workspaces: readonly Workspace[] }) {
  const value = useAllWorkspacesProjects(workspaces);
  React.useEffect(() => captureLatest(value), [value]);
  return <span>{value.projects?.length ?? "loading"}</span>;
}

function browserGraph(
  id: string,
  fields: { name?: string; draft_pending: boolean; revision?: number },
) {
  return {
    id,
    name: fields.name ?? id,
    revision: fields.revision ?? 1,
    node_count: 2,
    edge_count: 1,
    updated_at: "2026-08-10T12:00:00Z",
    draft_pending: fields.draft_pending,
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
  await vi.waitFor(() => expect(latest?.projects).not.toBeNull());
  return root;
}

beforeEach(() => {
  latest = undefined;
  apiMocks.request.mockReset();
});

afterEach(() => {
  document.body.replaceChildren();
});

describe("useAllWorkspacesProjects", () => {
  it("loads every authorized Project through one aggregate request", async () => {
    apiMocks.request.mockResolvedValue({
      projects: [
        {
          ...browserGraph("graph-1", {
            name: "Invoice intake",
            draft_pending: true,
            revision: 3,
          }),
          starred: true,
          last_opened_at: "2026-08-10T12:00:00Z",
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

    await vi.waitFor(() => expect(latest?.projects).toHaveLength(1));
    expect(apiMocks.request).toHaveBeenCalledOnce();
    expect(apiMocks.request).toHaveBeenCalledWith("GET", "/v1/me/projects");
    expect(latest?.projects?.[0]?.location).toEqual({
      id: personal.id,
      slug: personal.slug,
      name: personal.name,
      kind: personal.kind,
    });
    expect(latest?.projects?.[0]?.name).toBe("Invoice intake");
    expect(latest?.projects?.[0]?.starred).toBe(true);
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

    expect(latest?.projects).toEqual([]);
    expect(latest?.isLoading).toBe(false);
    expect(apiMocks.request).not.toHaveBeenCalled();

    await act(async () => root.unmount());
  });

  it("passes through the shared draft-head summary for a Project from /v1/me/projects", async () => {
    apiMocks.request.mockResolvedValue({
      projects: [
        browserGraph("graph-pending", { draft_pending: true }),
        browserGraph("graph-checkpointed", { draft_pending: false }),
      ],
    });

    const root = await renderGraphs([personal]);

    expect(
      latest?.projects?.map((project) => [
        project.name,
        project.draft_pending,
        project.revision,
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

    await revalidateProjectSummaries(mutate, personal.id);

    expect(mutate.mock.calls).toEqual([
      [workspaceProjectsKey(personal.id)],
      [ALL_PROJECTS_KEY],
    ]);
    expect(workspaceProjectsKey(personal.id)).toBe(
      "/v1/workspaces/workspace-personal/projects",
    );
  });

  it("refreshes the cross-workspace list when no workspace is scoped", async () => {
    const mutate = vi.fn().mockResolvedValue(undefined);

    await revalidateProjectSummaries(mutate);

    expect(mutate.mock.calls).toEqual([[ALL_PROJECTS_KEY]]);
  });
});

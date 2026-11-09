// @vitest-environment jsdom

import { describe, expect, it, vi } from "vitest";

import type { Workspace } from "@/lib/api/contract";
import {
  ALL_PROJECTS_KEY,
  revalidateProjectSummaries,
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

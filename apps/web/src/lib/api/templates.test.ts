import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createWorkspaceTemplate,
  instantiateWorkspaceTemplate,
  listWorkspaceTemplates,
} from "./templates";

afterEach(() => vi.unstubAllGlobals());

describe("template API client", () => {
  it("addresses source and destination through the typed copy contract", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async () =>
        new Response("{}", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await listWorkspaceTemplates("source/location", {
      query: "field survey",
      includeArchived: true,
    });
    await createWorkspaceTemplate("source/location", {
      source_graph_id: "source-graph",
      source_revision: 3,
      name: "Survey starter",
      description: null,
    });
    await instantiateWorkspaceTemplate("source/location", "template/1", {
      destination_workspace_id: "destination-location",
      name: "Independent survey",
      folder_id: "folder-fieldwork",
    });

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      "/api/v1/workspaces/source%2Flocation/templates?q=field+survey&include_archived=true",
      "/api/v1/workspaces/source%2Flocation/templates",
      "/api/v1/workspaces/source%2Flocation/templates/template%2F1/instantiate",
    ]);
    expect(JSON.parse(fetchMock.mock.calls[2]?.[1].body as string)).toEqual({
      destination_workspace_id: "destination-location",
      name: "Independent survey",
      folder_id: "folder-fieldwork",
    });
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";

import type { CopyExactHeadResponse } from "./contract";
import {
  checkpointGraph,
  copyExactHead,
  createSavedGraph,
  deleteSavedGraph,
  getSavedGraph,
  getArtifactGeoRender,
  getArtifactTableCell,
  getArtifactTablePage,
  getCollaborativeHead,
  getGraphExecution,
  listGraphExecutions,
  artifactContentUrl,
  artifactDownloadUrl,
  submitGraphCommand,
  updateSavedGraph,
  uploadFile,
} from "./workbench";

afterEach(() => vi.unstubAllGlobals());

const WORKSPACE_ID = "workspace/1";

describe("saved graph HTTP API", () => {
  it("writes and reads one canonical document shape", async () => {
    const document = {
      schema_version: 7 as const,
      nodes: [],
      edges: [],
      origins: [],
      presentation: {
        viewers: [],
        links: [],
        bindings: [],
        annotations: [],
      },
    };
    const saved = {
      id: "graph/1",
      name: "Vision graph",
      revision: 1,
      created_at: "2026-09-01T12:00:00Z",
      updated_at: "2026-09-01T12:00:00Z",
      document,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(saved), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(saved), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        ...saved,
        revision: 2,
        name: "Renamed vision graph",
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);

    await createSavedGraph(WORKSPACE_ID, {
      name: saved.name,
      document,
    });
    const loaded = await getSavedGraph(WORKSPACE_ID, saved.id);
    await updateSavedGraph(WORKSPACE_ID, saved.id, {
      name: "Renamed vision graph",
      document: loaded.document,
      expected_revision: loaded.revision,
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/workspaces/workspace%2F1/graphs",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ name: saved.name, document }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/workspaces/workspace%2F1/graphs/graph%2F1",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/v1/workspaces/workspace%2F1/graphs/graph%2F1",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          name: "Renamed vision graph",
          document,
          expected_revision: 1,
        }),
      }),
    );
  });
});

describe("collaboration HTTP API", () => {
  it("reads the live head and submits semantic commands", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            graph_id: "graph/1",
            room_epoch: "epoch-1",
            collaboration_sequence: 2,
            checkpoint_sequence: 1,
            checkpoint_revision: 1,
            name: "Draft",
            updated_at: "2026-08-07T00:00:00Z",
            document: { schema_version: 7, nodes: [], edges: [], origins: [] },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            head: {
              graph_id: "graph/1",
              room_epoch: "epoch-1",
              collaboration_sequence: 3,
              checkpoint_sequence: 1,
              checkpoint_revision: 1,
              name: "Renamed",
              updated_at: "2026-08-07T00:00:01Z",
              nodes: [],
              edges: [],
            },
            receipt: {
              command_id: "command-1",
              outcome: "accepted",
              accepted_sequence: 3,
              room_epoch: "epoch-1",
              deduplicated: false,
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await getCollaborativeHead(WORKSPACE_ID, "graph/1");
    await submitGraphCommand(WORKSPACE_ID, "graph/1", {
      command_id: "command-1",
      room_epoch: "epoch-1",
      observed_sequence: 2,
      command: {
        kind: "rename_graph",
        name: "Renamed",
        expected_name: "Draft",
      },
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/workspaces/workspace%2F1/graphs/graph%2F1/head/document",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/workspaces/workspace%2F1/graphs/graph%2F1/commands",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("checkpoints, copies, and deletes with exact-head confirmation", async () => {
    const copiedGraph = {
      id: "graph/2",
      name: "Copied",
      revision: 1,
      created_at: "2026-08-07T00:00:03Z",
      updated_at: "2026-08-07T00:00:03Z",
      document: {
        schema_version: 7,
        nodes: [],
        edges: [],
        origins: [],
      },
    } satisfies CopyExactHeadResponse;
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            head: {
              graph_id: "graph/1",
              room_epoch: "epoch-1",
              collaboration_sequence: 3,
              checkpoint_sequence: 3,
              checkpoint_revision: 2,
              name: "Renamed",
              updated_at: "2026-08-07T00:00:02Z",
              nodes: [],
              edges: [],
            },
            saved_revision: 2,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify(copiedGraph),
          { status: 201, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await checkpointGraph(WORKSPACE_ID, "graph/1", {
      expected_room_epoch: "epoch-1",
      expected_sequence: 3,
    });
    await copyExactHead("workspace/2", {
      source_workspace_id: WORKSPACE_ID,
      source_graph_id: "graph/1",
      expected_room_epoch: "epoch-1",
      expected_sequence: 3,
      command_id: "copy-1",
      name: "Copied",
    });
    await deleteSavedGraph(WORKSPACE_ID, "graph/1", 2, {
      expectedRoomEpoch: "epoch-1",
      expectedSequence: 3,
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/workspaces/workspace%2F1/graphs/graph%2F1/checkpoint",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/workspaces/workspace%2F2/graphs/copies",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/v1/workspaces/workspace%2F1/graphs/graph%2F1?expected_revision=2&expected_room_epoch=epoch-1&expected_sequence=3",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});

describe("execution history API", () => {
  it("serializes list filters and opaque cursors", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ items: [], next_cursor: null }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await listGraphExecutions(WORKSPACE_ID, "graph/1", {
      limit: 50,
      cursor: "timestamp+execution/id",
      graphRevision: 7,
      status: "failed",
      nodeId: "extract/1",
    }, controller.signal);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/workspaces/workspace%2F1/graphs/graph%2F1/executions?limit=50&cursor=timestamp%2Bexecution%2Fid&graph_revision=7&status=failed&node_id=extract%2F1",
      expect.objectContaining({ method: "GET", signal: controller.signal }),
    );
  });

  it("addresses one graph execution without conflating it with live polling", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ execution_id: "execution/1", node_results: [] }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);

    await getGraphExecution(WORKSPACE_ID, "graph/1", "execution/1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/workspaces/workspace%2F1/graphs/graph%2F1/executions/execution%2F1",
      expect.objectContaining({ method: "GET" }),
    );
  });
});

describe("table artifact API", () => {
  it("serializes page bounds and preview limits", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({
        columns: [],
        rows: [],
        offset: 50,
        limit: 25,
        total_rows: 0,
        column_offset: 10,
        column_limit: 20,
        total_columns: 0,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);

    await getArtifactTablePage(
      WORKSPACE_ID,
      "artifact/1",
      50,
      25,
      ["geometry/wkt", "source name"],
      256,
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/workspaces/workspace%2F1/artifacts/artifact%2F1/table/page?offset=50&limit=25&max_cell_characters=256&column_ids=geometry%2Fwkt&column_ids=source+name",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("keeps arbitrary column ids in the cell query", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({
        row_index: 3,
        column_id: "geometry/wkt",
        value: "full",
        encoding: "native",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);

    await getArtifactTableCell(WORKSPACE_ID, "artifact/1", 3, "geometry/wkt");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/workspaces/workspace%2F1/artifacts/artifact%2F1/table/cell?row_index=3&column_id=geometry%2Fwkt",
      expect.objectContaining({ method: "GET" }),
    );
  });
});

describe("GIS artifact API", () => {
  it("addresses the immutable render descriptor without paging", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({
        artifact_id: "artifact/1",
        kind: "map_document",
        basemap: "openstreetmap",
        initial_bounds: null,
        layers: [],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await getArtifactGeoRender(WORKSPACE_ID, "artifact/1", controller.signal);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/workspaces/workspace%2F1/artifacts/artifact%2F1/geo/render",
      expect.objectContaining({ method: "GET", signal: controller.signal }),
    );
  });
});

describe("file upload API", () => {
  it("streams the selected file as multipart form data", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ uploads: [] }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File([new Uint8Array([1, 2, 3])], "scan.tif", {
      type: "image/tiff",
    });

    await uploadFile(WORKSPACE_ID, file);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/workspaces/workspace%2F1/uploads");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ Accept: "application/json" });
    expect(init.body).toBeInstanceOf(FormData);
    const uploaded = (init.body as FormData).get("file") as File;
    expect(uploaded.name).toBe("scan.tif");
    expect(uploaded.type).toBe("image/tiff");
    expect(uploaded.size).toBe(3);
  });
});

describe("artifact content URLs", () => {
  it("resolves relative and API-owned paths under the workspace-scoped API base", () => {
    expect(artifactContentUrl(WORKSPACE_ID, "./artifacts/artifact-1/content"))
      .toBe("/api/v1/workspaces/workspace%2F1/artifacts/artifact-1/content");
    expect(artifactContentUrl(WORKSPACE_ID, "/v1/workspaces/workspace%2F1/artifacts/artifact-1/content"))
      .toBe("/api/v1/workspaces/workspace%2F1/artifacts/artifact-1/content");
  });

  it("preserves absolute HTTP and custom-scheme URLs", () => {
    expect(artifactContentUrl(WORKSPACE_ID, "https://private.example/artifact"))
      .toBe("https://private.example/artifact");
    expect(artifactContentUrl(WORKSPACE_ID, "pmtiles://private.example/archive.pmtiles"))
      .toBe("pmtiles://private.example/archive.pmtiles");
  });
});

describe("artifact download URLs", () => {
  it("resolves the download path with a format query under the API base", () => {
    expect(artifactDownloadUrl(WORKSPACE_ID, "artifact-1", "json"))
      .toBe("/api/v1/workspaces/workspace%2F1/artifacts/artifact-1/download?format=json");
    expect(artifactDownloadUrl(WORKSPACE_ID, "artifact-1", "txt"))
      .toBe("/api/v1/workspaces/workspace%2F1/artifacts/artifact-1/download?format=txt");
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  artifactContentUrl,
  artifactDownloadUrl,
  artifactInlineContentUrl,
  getArtifactGeoRender,
  getArtifactTableCell,
  getArtifactTablePage,
  getArtifactTableSchema,
  queryArtifactGeoFeatures,
  queryArtifactTablePage,
  uploadFile,
} from "./workbench";

/*
 * The workbench's artifact surface: read a table page, ask a GIS question,
 * resolve a content URL, and turn a picked file into an artifact. Projects,
 * their heads, commands, checkpoints, Runs and instances are addressed in
 * projects.test.ts, because that is where they live now.
 */

afterEach(() => vi.unstubAllGlobals());

const WORKSPACE_ID = "workspace/1";

describe("table artifact API", () => {
  it("serializes page bounds and preview limits", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
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
      ),
    );
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
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          row_index: 3,
          column_id: "geometry/wkt",
          value: "full",
          encoding: "native",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
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
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          artifact_id: "artifact/1",
          kind: "map_document",
          basemap: "openstreetmap",
          initial_bounds: null,
          layers: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
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
  const target = {
    kind: "api" as const,
    upload_id: "3f1a2b4c-5d6e-4f70-8192-a3b4c5d6e7f8",
    url: "/v1/workspaces/workspace%2F1/uploads/3f1a2b4c-5d6e-4f70-8192-a3b4c5d6e7f8/content",
    method: "PUT",
    expires_at: "2026-09-15T19:40:00Z",
    headers: {},
  };
  const completed = {
    upload_key: target.upload_id,
    filename: "scan.tif",
    byte_size: 3,
    artifact_type: "file.tiff@1",
    notice: null,
  };

  function jsonResponse(payload: unknown, status = 200): Response {
    return new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  it("reserves, sends the bytes to the target, then completes", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(target, 201))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(jsonResponse(completed));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File([new Uint8Array([1, 2, 3])], "scan.tif", {
      type: "image/tiff",
    });

    const item = await uploadFile(WORKSPACE_ID, file);

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const [reserveUrl, reserveInit] = fetchMock.mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(reserveUrl).toBe("/api/v1/workspaces/workspace%2F1/uploads");
    expect(reserveInit.method).toBe("POST");
    expect(JSON.parse(reserveInit.body as string)).toEqual({
      filename: "scan.tif",
      byte_size: 3,
      content_type: "image/tiff",
    });

    const [putUrl, putInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(putUrl).toBe(
      "/api/v1/workspaces/workspace%2F1/uploads/3f1a2b4c-5d6e-4f70-8192-a3b4c5d6e7f8/content",
    );
    expect(putInit.method).toBe("PUT");
    expect(putInit.body).toBe(file);
    expect(putInit.credentials).toBe("same-origin");
    expect((putInit.headers as Record<string, string>)["Content-Type"]).toBe(
      "image/tiff",
    );

    const [completeUrl, completeInit] = fetchMock.mock.calls[2] as [
      string,
      RequestInit,
    ];
    expect(completeUrl).toBe(
      "/api/v1/workspaces/workspace%2F1/uploads/3f1a2b4c-5d6e-4f70-8192-a3b4c5d6e7f8/complete",
    );
    expect(completeInit.method).toBe("POST");
    expect(item).toEqual(completed);
  });

  it("sends the bytes to a same-origin storage target without session credentials", async () => {
    const signed = {
      kind: "storage" as const,
      upload_id: target.upload_id,
      url: "https://example.test/objects/3f1a2b4c?X-Amz-Signature=abc",
      method: "PUT",
      expires_at: target.expires_at,
      headers: { "If-None-Match": "*" },
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(signed, 201))
      .mockResolvedValueOnce(new Response(null, { status: 200 }))
      .mockResolvedValueOnce(jsonResponse(completed));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "grafy_csrf=csrf-token" });
    const file = new File([new Uint8Array([1, 2, 3])], "scan.tif", {
      type: "image/tiff",
    });

    await uploadFile(WORKSPACE_ID, file);

    const [putUrl, putInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(putUrl).toBe(signed.url);
    expect(putInit.credentials).toBe("omit");
    expect(
      (putInit.headers as Record<string, string>)["X-CSRF-Token"],
    ).toBeUndefined();
    expect((putInit.headers as Record<string, string>)["If-None-Match"]).toBe(
      "*",
    );
    expect(putInit.body).toBe(file);
  });
});

describe("artifact content URLs", () => {
  it("resolves relative and API-owned paths under the workspace-scoped API base", () => {
    expect(
      artifactContentUrl(WORKSPACE_ID, "./artifacts/artifact-1/content"),
    ).toBe("/api/v1/workspaces/workspace%2F1/artifacts/artifact-1/content");
    expect(
      artifactContentUrl(
        WORKSPACE_ID,
        "/v1/workspaces/workspace%2F1/artifacts/artifact-1/content",
      ),
    ).toBe("/api/v1/workspaces/workspace%2F1/artifacts/artifact-1/content");
  });

  it("preserves absolute HTTP and custom-scheme URLs", () => {
    expect(
      artifactContentUrl(WORKSPACE_ID, "https://private.example/artifact"),
    ).toBe("https://private.example/artifact");
    expect(
      artifactContentUrl(
        WORKSPACE_ID,
        "pmtiles://private.example/archive.pmtiles",
      ),
    ).toBe("pmtiles://private.example/archive.pmtiles");
  });
});

describe("artifact download URLs", () => {
  it("resolves the download path with a format query under the API base", () => {
    expect(artifactDownloadUrl(WORKSPACE_ID, "artifact-1", "json")).toBe(
      "/api/v1/workspaces/workspace%2F1/artifacts/artifact-1/download?format=json",
    );
    expect(artifactDownloadUrl(WORKSPACE_ID, "artifact-1", "txt")).toBe(
      "/api/v1/workspaces/workspace%2F1/artifacts/artifact-1/download?format=txt",
    );
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createArtifact,
  createdArtifactToRef,
  fetchArtifactJsonPayload,
} from "./artifacts";

afterEach(() => vi.unstubAllGlobals());

const WORKSPACE_ID = "workspace/1";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("createArtifact", () => {
  it("posts the authored payload under the workspace", async () => {
    const created = {
      artifact_id: "11111111-1111-4111-8111-111111111111",
      artifact_type: "scalar.text",
      schema_version: 1,
      content_hash: "abc",
      derived_from_artifact_id: null,
      created_at: "2026-11-25T12:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(created, 201));
    vi.stubGlobal("fetch", fetchMock);

    const response = await createArtifact(WORKSPACE_ID, {
      artifact_type: "scalar.text",
      schema_version: 1,
      payload: { value: "Hello" },
      derived_from_artifact_id: null,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/workspaces/workspace%2F1/artifacts",
      expect.objectContaining({ method: "POST" }),
    );
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      artifact_type: "scalar.text",
      schema_version: 1,
      payload: { value: "Hello" },
      derived_from_artifact_id: null,
    });
    expect(response).toEqual(created);
  });
});

describe("createdArtifactToRef", () => {
  it("keeps the identity fields a canvas card needs", () => {
    expect(
      createdArtifactToRef({
        artifact_id: "22222222-2222-4222-8222-222222222222",
        artifact_type: "table.data",
        schema_version: 1,
        content_hash: "deadbeef",
        derived_from_artifact_id: "11111111-1111-4111-8111-111111111111",
        created_at: "2026-11-25T12:00:00Z",
      }),
    ).toEqual({
      artifact_id: "22222222-2222-4222-8222-222222222222",
      artifact_type: "table.data",
      schema_version: 1,
      content_hash: "deadbeef",
    });
  });

  it("normalizes a missing content hash to null", () => {
    expect(
      createdArtifactToRef({
        artifact_id: "33333333-3333-4333-8333-333333333333",
        artifact_type: "scalar.text",
        schema_version: 1,
        derived_from_artifact_id: null,
        created_at: "2026-11-25T12:00:00Z",
      }).content_hash,
    ).toBeNull();
  });
});

describe("fetchArtifactJsonPayload", () => {
  it("reads the artifact content object", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ value: "Draft" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      fetchArtifactJsonPayload(WORKSPACE_ID, "artifact/1"),
    ).resolves.toEqual({ value: "Draft" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/workspaces/workspace%2F1/artifacts/artifact%2F1/content",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("rejects content that is not a JSON object", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(["not", "object"]));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      fetchArtifactJsonPayload(WORKSPACE_ID, "artifact/1"),
    ).rejects.toThrow("Artifact content is not a JSON object");
  });
});

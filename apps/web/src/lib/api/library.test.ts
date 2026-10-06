import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./client";
import { deleteLibraryArtifact, LibraryArtifactInUseError } from "./library";

/**
 * The seam between the Library artifact routes and the panel.
 *
 * `library-folders.test.ts` proves the same link for the folder rules; this one
 * proves that the artifact delete's refusal code becomes the error class the
 * panel knows how to phrase, with the server's own sentence about the graphs
 * that still reference the artifact.
 */

const WORKSPACE = "workspace/1";
const ARTIFACTS_PATH = "/api/v1/workspaces/workspace%2F1/library/artifacts";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** What a real refusal looks like on the wire: `{detail, code, error_id}`. */
function refusal(status: number, code: string, detail: string): Response {
  return jsonResponse({ detail, code, error_id: "error-1" }, status);
}

type RecordedRequest = { path: string; init: RequestInit };
const requests: RecordedRequest[] = [];

function stubServer(respond: (path: string) => Response): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit = {}) => {
      requests.push({ path, init });
      return respond(path);
    }),
  );
}

function lastRequest(): RecordedRequest {
  const request = requests.at(-1);
  if (!request) throw new Error("The seam made no request");
  return request;
}

afterEach(() => {
  vi.unstubAllGlobals();
  requests.length = 0;
});

describe("deleteLibraryArtifact", () => {
  it("deletes one artifact by its own route", async () => {
    stubServer(() => new Response(null, { status: 204 }));

    await deleteLibraryArtifact(WORKSPACE, "artifact/1");

    expect(lastRequest().path).toBe(`${ARTIFACTS_PATH}/artifact%2F1`);
    expect(lastRequest().init.method).toBe("DELETE");
    expect(lastRequest().init.body).toBeUndefined();
  });

  it("turns an in-use refusal into the error carrying the server's sentence", async () => {
    const detail = "Still used by: Survey pipeline, Salt maps";
    stubServer(() => refusal(409, "library.artifact_in_use", detail));

    const error = await deleteLibraryArtifact(WORKSPACE, "artifact-1")
      .then(() => null)
      .catch((raised: unknown) => raised);

    expect(error).toBeInstanceOf(LibraryArtifactInUseError);
    const inUse = error as LibraryArtifactInUseError;
    expect(inUse.artifactId).toBe("artifact-1");
    expect(inUse.detail).toBe(detail);
    // The panel shows `error.message` for anything it does not phrase itself,
    // so the server's sentence has to be the message too.
    expect(inUse.message).toBe(detail);
  });

  it("passes a failure that is not the reference rule through with its code", async () => {
    stubServer(() => refusal(404, "resource.not_found", "Not found"));

    const error = await deleteLibraryArtifact(WORKSPACE, "artifact-gone")
      .then(() => null)
      .catch((raised: unknown) => raised);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
    expect((error as ApiError).code).toBe("resource.not_found");
  });
});

import { request } from "./client";
import type {
  ArtifactRef,
  CreateArtifactRequest,
  CreateArtifactResponse,
} from "./contract";

function isJsonObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Create an immutable authored artifact. Passing `derived_from_artifact_id`
 * records the source this version was edited from; the original is unchanged.
 */
export function createArtifact(
  workspaceId: string,
  body: CreateArtifactRequest,
  signal?: AbortSignal,
): Promise<CreateArtifactResponse> {
  return request<CreateArtifactResponse>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/artifacts`,
    { body, signal },
  );
}

/**
 * Read an artifact's JSON payload. Authorable types store an object the
 * editors can round-trip; anything else is rejected rather than silently
 * wrapped.
 */
export async function fetchArtifactJsonPayload(
  workspaceId: string,
  artifactId: string,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  const payload = await request<unknown>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}/content`,
    { signal },
  );
  if (!isJsonObject(payload)) {
    throw new Error("Artifact content is not a JSON object");
  }
  return payload;
}

/** The canvas card ref for a newly created artifact. */
export function createdArtifactToRef(
  created: CreateArtifactResponse,
): ArtifactRef {
  return {
    artifact_id: created.artifact_id,
    artifact_type: created.artifact_type,
    schema_version: created.schema_version,
    content_hash: created.content_hash ?? null,
  };
}

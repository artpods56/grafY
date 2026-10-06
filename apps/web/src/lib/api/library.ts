import { ApiError, request } from "./client";
import type {
  LibraryItem,
  LibraryList,
  SaveRunArtifactRequest,
  SaveUploadedArtifactRequest,
} from "./contract";

function libraryPath(workspaceId: string, suffix = ""): string {
  return `/v1/workspaces/${encodeURIComponent(workspaceId)}/library/artifacts${suffix}`;
}

/** The refusal code for an artifact a saved revision or run history still uses. */
const ARTIFACT_IN_USE = "library.artifact_in_use";

/**
 * A Library artifact another object still references.
 *
 * The server names the referencing graphs in `detail` and the panel shows that
 * text: only the server knows which saved revisions and which run history hold
 * the reference, and the panel holds neither.
 */
export class LibraryArtifactInUseError extends Error {
  readonly artifactId: string;
  /** The server's own sentence, naming the graphs that reference the artifact. */
  readonly detail: string;

  constructor(artifactId: string, detail: string) {
    super(detail);
    this.name = "LibraryArtifactInUseError";
    this.artifactId = artifactId;
    this.detail = detail;
  }
}

export function listLibraryArtifacts(workspaceId: string) {
  return request<LibraryList>("GET", libraryPath(workspaceId));
}

export function saveRunArtifactToLibrary(
  workspaceId: string,
  body: SaveRunArtifactRequest,
) {
  return request<LibraryItem>("POST", libraryPath(workspaceId, "/from-run"), {
    body,
  });
}

export function saveUploadedArtifactToLibrary(
  workspaceId: string,
  body: SaveUploadedArtifactRequest,
) {
  return request<LibraryItem>(
    "POST",
    libraryPath(workspaceId, "/from-upload"),
    {
      body,
    },
  );
}

/**
 * Remove an artifact from the Workspace Library.
 *
 * Rejects with `LibraryArtifactInUseError` while a saved graph revision or
 * execution history references it, and with the plain `ApiError` for anything
 * else, including an artifact this Library does not have.
 */
export async function deleteLibraryArtifact(
  workspaceId: string,
  artifactId: string,
): Promise<void> {
  try {
    await request<never>(
      "DELETE",
      libraryPath(workspaceId, `/${encodeURIComponent(artifactId)}`),
    );
  } catch (error) {
    if (error instanceof ApiError && error.code === ARTIFACT_IN_USE) {
      throw new LibraryArtifactInUseError(artifactId, error.detail);
    }
    throw error;
  }
}

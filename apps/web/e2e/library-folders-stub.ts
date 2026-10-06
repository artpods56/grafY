import { randomUUID } from "node:crypto";

import type { Page, Route } from "@playwright/test";

import type { LibraryList } from "../src/lib/api/contract";
import type { LibraryFolder } from "../src/lib/api/library-folder-model";

/**
 * The Workspace Library routes, answered inside the Node test process.
 *
 * The side panel reads and writes this tree through the real HTTP client, so
 * every workbench test needs an answer at `/library/folders` and
 * `/library/placements`. The fake keeps the rules the real routes keep — a
 * sibling name is taken whatever its case, a folder never lands inside itself, a
 * folder deletes only when empty, and an artifact a graph still references
 * refuses its delete — because a fake that only ever says yes cannot show a
 * refusal reaching the panel.
 *
 * The tree belongs to one page. Playwright builds a page per test and per retry,
 * so the folders a test names are gone before the next run names them again: no
 * folder this suite makes outlives the test that made it.
 */

/** What a real refusal looks like on the wire: { detail, code, error_id }. */
const NOT_FOUND = {
  status: 404,
  detail: "Not found",
  code: "resource.not_found",
};

const REFUSALS = {
  "library.folder_name_conflict": {
    status: 409,
    detail: "A folder with this name already exists here",
  },
  "library.folder_not_empty": {
    status: 409,
    detail: "Move the contents out before deleting this folder",
  },
  "library.folder_cycle": {
    status: 422,
    detail: "A folder cannot be moved inside itself",
  },
  "library.artifact_in_use": {
    status: 409,
    detail: "Still used by: Survey pipeline, Salt maps",
  },
} as const;

/**
 * The fixture artifact a saved graph is said to reference, so a delete has a
 * refusal to reach the panel with. The real server answers this by looking at
 * saved revisions and run history; this fake only has the one id, so it names
 * the same graphs the refusal sentence does.
 */
const REFERENCED_ARTIFACT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

type LibraryStubState = {
  /** The artifact list the Library lists, before placements place it anywhere. */
  artifacts: LibraryList;
  folders: LibraryFolder[];
  /** artifact id -> folder id. An artifact with no entry sits at the root. */
  placements: Map<string, string>;
};

export type LibraryStub = {
  /** Sets which artifacts the Library lists; placements still say where they sit. */
  artifacts(library: LibraryList): void;
};

const LIBRARY_GLOB = "**/api/v1/workspaces/*/library";
const stubStates = new WeakMap<Page, LibraryStubState>();

/**
 * Sibling names are unique without regard to case or the space around them. The
 * server casefolds; lowercasing covers every name this suite types.
 */
function nameKey(name: string): string {
  return name.trim().toLowerCase();
}

function envelope(detail: string, code: string): string {
  return JSON.stringify({ detail, code, error_id: randomUUID() });
}

/** `/api/v1/workspaces/{workspace_id}/library/...` */
function segmentOf(url: URL, index: number): string {
  return url.pathname.split("/")[index] ?? "";
}

function stubFor(state: LibraryStubState): LibraryStub {
  return {
    artifacts(library: LibraryList): void {
      state.artifacts = library;
    },
  };
}

export async function libraryStub(page: Page): Promise<LibraryStub> {
  const installed = stubStates.get(page);
  if (installed) return stubFor(installed);

  const state: LibraryStubState = {
    artifacts: { items: [] },
    folders: [],
    placements: new Map(),
  };
  stubStates.set(page, state);

  const notFound = async (route: Route): Promise<void> => {
    await route.fulfill({
      status: NOT_FOUND.status,
      contentType: "application/json",
      body: envelope(NOT_FOUND.detail, NOT_FOUND.code),
    });
  };

  const refusal = async (route: Route, code: keyof typeof REFUSALS) => {
    const spec = REFUSALS[code];
    await route.fulfill({
      status: spec.status,
      contentType: "application/json",
      body: envelope(spec.detail, code),
    });
  };

  const folderOf = (folderId: string): LibraryFolder | undefined =>
    state.folders.find((folder) => folder.folder_id === folderId);

  const takenName = (
    workspaceId: string,
    parentId: string | null,
    name: string,
    exceptFolderId?: string,
  ): LibraryFolder | undefined =>
    state.folders.find(
      (folder) =>
        folder.workspace_id === workspaceId &&
        folder.parent_id === parentId &&
        folder.folder_id !== exceptFolderId &&
        nameKey(folder.name) === nameKey(name),
    );

  /** Whether `folderId` is `candidateParent` itself or sits beneath it. */
  const isInside = (folderId: string, candidateParent: string): boolean => {
    const seen = new Set<string>();
    let current: string | null = candidateParent;
    while (current !== null && !seen.has(current)) {
      if (current === folderId) return true;
      seen.add(current);
      current = folderOf(current)?.parent_id ?? null;
    }
    return false;
  };

  const makeFolder = (
    workspaceId: string,
    name: string,
    parentId: string | null,
  ): LibraryFolder => {
    const now = new Date().toISOString();
    const folder: LibraryFolder = {
      folder_id: randomUUID(),
      workspace_id: workspaceId,
      parent_id: parentId,
      name: name.trim(),
      created_at: now,
      updated_at: now,
    };
    state.folders.push(folder);
    return folder;
  };

  // Registered after the fixture's catch-all, so these win for the Library paths
  // and anything else still reaches the unhandled-request report.
  await page.route(`${LIBRARY_GLOB}/artifacts`, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const items = state.artifacts.items.map((item) => ({
      ...item,
      folder_id: state.placements.get(item.artifact.artifact_id) ?? null,
    }));
    await route.fulfill({ json: { items } satisfies LibraryList });
  });

  await page.route(`${LIBRARY_GLOB}/artifacts/*`, async (route) => {
    const request = route.request();
    if (request.method() !== "DELETE") return route.fallback();
    const artifactId = segmentOf(new URL(request.url()), 7);
    const known = state.artifacts.items.some(
      (item) => item.artifact.artifact_id === artifactId,
    );
    if (!known) return notFound(route);
    if (artifactId === REFERENCED_ARTIFACT_ID) {
      return refusal(route, "library.artifact_in_use");
    }
    // The Library stops listing it, and its placement goes with it.
    state.artifacts = {
      items: state.artifacts.items.filter(
        (item) => item.artifact.artifact_id !== artifactId,
      ),
    };
    state.placements.delete(artifactId);
    await route.fulfill({ status: 204 });
  });

  await page.route(`${LIBRARY_GLOB}/placements`, async (route) => {
    const request = route.request();
    if (request.method() !== "PUT") return route.fallback();
    const body = request.postDataJSON() as {
      artifact_ids: string[];
      folder_id: string | null;
    };
    if (body.folder_id !== null && !folderOf(body.folder_id)) {
      return notFound(route);
    }
    // The server names an artifact this Library does not have; so does this fake,
    // or the panel would believe a placement no listing ever shows.
    for (const artifactId of body.artifact_ids) {
      const known = state.artifacts.items.some(
        (item) => item.artifact.artifact_id === artifactId,
      );
      if (!known) return notFound(route);
    }
    for (const artifactId of body.artifact_ids) {
      if (body.folder_id === null) state.placements.delete(artifactId);
      else state.placements.set(artifactId, body.folder_id);
    }
    await route.fulfill({ status: 204 });
  });

  await page.route(`${LIBRARY_GLOB}/folders`, async (route) => {
    const request = route.request();
    const workspaceId = segmentOf(new URL(request.url()), 4);
    if (request.method() === "GET") {
      const folders = state.folders.filter(
        (folder) => folder.workspace_id === workspaceId,
      );
      return route.fulfill({ json: { folders } });
    }
    if (request.method() !== "POST") return route.fallback();
    const body = request.postDataJSON() as {
      name: string;
      parent_id: string | null;
    };
    if (body.parent_id !== null && !folderOf(body.parent_id)) {
      return notFound(route);
    }
    if (takenName(workspaceId, body.parent_id, body.name)) {
      return refusal(route, "library.folder_name_conflict");
    }
    await route.fulfill({
      status: 201,
      json: makeFolder(workspaceId, body.name, body.parent_id),
    });
  });

  await page.route(`${LIBRARY_GLOB}/folders/*/parent`, async (route) => {
    const request = route.request();
    if (request.method() !== "PUT") return route.fallback();
    const folder = folderOf(segmentOf(new URL(request.url()), 7));
    if (!folder) return notFound(route);
    const body = request.postDataJSON() as { parent_id: string | null };
    if (body.parent_id !== null && !folderOf(body.parent_id)) {
      return notFound(route);
    }
    if (body.parent_id !== null && isInside(folder.folder_id, body.parent_id)) {
      return refusal(route, "library.folder_cycle");
    }
    const clashes = takenName(
      folder.workspace_id,
      body.parent_id,
      folder.name,
      folder.folder_id,
    );
    if (clashes) return refusal(route, "library.folder_name_conflict");
    folder.parent_id = body.parent_id;
    folder.updated_at = new Date().toISOString();
    return route.fulfill({ json: folder });
  });

  await page.route(`${LIBRARY_GLOB}/folders/*`, async (route) => {
    const request = route.request();
    const method = request.method();
    if (method !== "PATCH" && method !== "DELETE") return route.fallback();
    const folderId = segmentOf(new URL(request.url()), 7);
    const folder = folderOf(folderId);
    if (!folder) return notFound(route);

    if (method === "DELETE") {
      const holdsFolders = state.folders.some(
        (candidate) => candidate.parent_id === folderId,
      );
      const holdsArtifacts = [...state.placements.values()].includes(folderId);
      if (holdsFolders || holdsArtifacts) {
        return refusal(route, "library.folder_not_empty");
      }
      state.folders = state.folders.filter(
        (candidate) => candidate.folder_id !== folderId,
      );
      return route.fulfill({ status: 204 });
    }

    const body = request.postDataJSON() as { name: string };
    const clashes = takenName(
      folder.workspace_id,
      folder.parent_id,
      body.name,
      folder.folder_id,
    );
    if (clashes) return refusal(route, "library.folder_name_conflict");
    folder.name = body.name.trim();
    folder.updated_at = new Date().toISOString();
    return route.fulfill({ json: folder });
  });

  return stubFor(state);
}

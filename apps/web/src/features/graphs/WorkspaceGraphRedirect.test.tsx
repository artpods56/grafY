// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const redirectState = vi.hoisted(() => ({
  replace: vi.fn(),
  mutate: vi.fn(async () => undefined),
  workspaces: undefined as
    | Array<{
        id: string;
        name: string;
        slug: string;
        kind: "personal" | "shared";
      }>
    | undefined,
  error: undefined as Error | undefined,
  search: "",
}));

vi.mock("next/navigation", () => {
  // A stable router object, the way next/navigation hands one to a real page.
  const router = { replace: redirectState.replace };
  return {
    useRouter: () => router,
    useSearchParams: () => new URLSearchParams(redirectState.search),
  };
});

vi.mock("@/features/auth/AuthSessionBoundary", () => ({
  useAuthSession: () => ({ session: { user_id: "user-1" } }),
}));

vi.mock("@/features/workspaces/WorkspaceLayout", () => ({
  resolveSelectedWorkspace: (workspaces: typeof redirectState.workspaces) =>
    workspaces?.find((workspace) => workspace.kind === "personal"),
}));

vi.mock("@/hooks/use-api", () => ({
  useWorkspaces: () => ({
    data: redirectState.workspaces,
    error: redirectState.error,
    mutate: redirectState.mutate,
  }),
}));

import { WorkspaceGraphRedirect } from "./WorkspaceGraphRedirect";

const roots: Root[] = [];
let activeRoot: Root | null = null;

const LOCATIONS = [
  {
    id: "11111111-1111-4111-8111-111111111111",
    name: "Atlas",
    slug: "atlas",
    kind: "shared" as const,
  },
  {
    id: "22222222-2222-4222-8222-222222222222",
    name: "Personal",
    slug: "personal",
    kind: "personal" as const,
  },
];

async function renderRedirect(search = "") {
  redirectState.search = search.startsWith("?") ? search.slice(1) : search;
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  activeRoot = root;
  await act(async () => root.render(<WorkspaceGraphRedirect />));
  return container;
}

async function rerenderRedirect() {
  const root = activeRoot;
  if (!root) throw new Error("Nothing is mounted");
  await act(async () => root.render(<WorkspaceGraphRedirect />));
}

function target(): string {
  const calls = redirectState.replace.mock.calls;
  const last = calls.at(-1);
  if (!last) throw new Error("No redirect happened");
  return String(last[0]);
}

beforeEach(() => {
  redirectState.replace.mockReset();
  redirectState.mutate.mockClear();
  redirectState.workspaces = undefined;
  redirectState.error = undefined;
  redirectState.search = "";
});

afterEach(async () => {
  activeRoot = null;
  for (const root of roots.splice(0)) {
    await act(async () => root.unmount());
  }
  document.body.replaceChildren();
});

describe("legacy graph route redirect", () => {
  it("opens the personal workspace graph list", async () => {
    redirectState.workspaces = LOCATIONS;

    await renderRedirect();

    expect(redirectState.replace).toHaveBeenCalledWith(
      "/workspaces/personal/graphs",
    );
  });

  it("falls back to workspace administration when none are available", async () => {
    redirectState.workspaces = [];

    await renderRedirect();

    expect(redirectState.replace).toHaveBeenCalledWith("/workspaces");
  });

  it("keeps API failures retryable", async () => {
    redirectState.error = new Error("offline");
    const container = await renderRedirect();
    const retry = container.querySelector<HTMLButtonElement>("button")!;

    await act(async () => retry.click());

    expect(redirectState.replace).not.toHaveBeenCalled();
    expect(redirectState.mutate).toHaveBeenCalledOnce();
  });
});

describe("graph entry routes honour the address", () => {
  beforeEach(() => {
    redirectState.workspaces = LOCATIONS;
  });

  it("opens the location the address asked for", async () => {
    await renderRedirect("?location=atlas");

    expect(target()).toBe("/workspaces/atlas/graphs");
  });

  it("carries every filter to the location it chose", async () => {
    await renderRedirect("?location=atlas&q=intake&view=all&utm_source=email");

    expect(target()).toBe(
      "/workspaces/atlas/graphs?q=intake&view=all&utm_source=email",
    );
  });

  it("sets aside a location that no longer names one of theirs", async () => {
    // A renamed team, a revoked invitation, a stale bookmark: the filters are
    // still worth keeping, and the default location is the safe answer.
    await renderRedirect("?location=ghost-team&q=intake");

    expect(target()).toBe("/workspaces/personal/graphs?q=intake");
  });

  it("does not read a workspace id as a location", async () => {
    // Atlas is reachable, but only by slug: an id in the address is not a
    // claim on it, and must not become a navigation the app cannot justify.
    await renderRedirect(`?location=${LOCATIONS[0]!.id}`);

    expect(target()).toBe("/workspaces/personal/graphs");
  });

  it("keeps an empty location hint out of the way", async () => {
    await renderRedirect("?location=%20&view=all");

    expect(target()).toBe("/workspaces/personal/graphs?view=all");
  });

  it("sends a person with no locations to Teams and access", async () => {
    redirectState.workspaces = [];

    await renderRedirect("?location=atlas&q=intake&view=all");

    expect(target()).toBe("/workspaces");
  });

  it("redirects once per address, not once per render", async () => {
    await renderRedirect("?location=atlas");
    await rerenderRedirect();

    expect(redirectState.replace).toHaveBeenCalledTimes(1);
  });
});

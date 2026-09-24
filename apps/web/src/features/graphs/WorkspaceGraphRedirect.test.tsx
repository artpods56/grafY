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
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: redirectState.replace }),
}));

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

async function renderRedirect() {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  await act(async () => root.render(<WorkspaceGraphRedirect />));
  return container;
}

beforeEach(() => {
  redirectState.replace.mockReset();
  redirectState.mutate.mockClear();
  redirectState.workspaces = undefined;
  redirectState.error = undefined;
});

afterEach(async () => {
  for (const root of roots.splice(0)) {
    await act(async () => root.unmount());
  }
  document.body.replaceChildren();
});

describe("legacy graph route redirect", () => {
  it("opens the personal workspace graph list", async () => {
    redirectState.workspaces = [
      {
        id: "workspace-team",
        name: "Atlas",
        slug: "atlas",
        kind: "shared",
      },
      {
        id: "workspace-personal",
        name: "Personal",
        slug: "personal",
        kind: "personal",
      },
    ];

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

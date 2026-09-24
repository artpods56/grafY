// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const workspacePageState = vi.hoisted(() => ({
  push: vi.fn(),
  mutate: vi.fn(),
  workspaces: [
    {
      id: "location-personal",
      name: "Personal workspace",
      slug: "hidden-personal-slug",
      kind: "personal" as const,
      role: "owner" as const,
      capabilities: ["view_graph", "create_graph", "manage_members"],
    },
    {
      id: "location-team",
      name: "Atlas",
      slug: "hidden-team-slug",
      kind: "shared" as const,
      role: "editor" as const,
      capabilities: ["view_graph", "create_graph"],
    },
  ],
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: workspacePageState.push }),
}));

vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.ComponentProps<"a">) => (
    <a {...props}>{children}</a>
  ),
}));

vi.mock("@/features/auth/AuthSessionBoundary", () => ({
  useAuthSession: () => ({
    session: { user_id: "private-user-id" },
    logout: vi.fn(),
  }),
}));

vi.mock("@/features/workspaces/WorkspaceLayout", () => ({
  WorkspaceRail: () => <aside data-workspace-rail />,
  workspaceDisplayName: (workspace: { name: string; kind: string }) =>
    workspace.kind === "personal" ? "My graphs" : workspace.name,
}));

vi.mock("@/hooks/use-api", () => ({
  useWorkspaces: () => ({
    data: workspacePageState.workspaces,
    error: undefined,
    mutate: workspacePageState.mutate,
  }),
}));

vi.mock("@/lib/api", () => ({ createWorkspace: vi.fn() }));

import WorkspacesPage from "./page";

afterEach(() => {
  document.body.replaceChildren();
});

it("presents the workspace directory as separate administration", async () => {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<WorkspacesPage />));

  expect(container.querySelector("h1")?.textContent).toBe(
    "Workspace directory",
  );
  expect(container.textContent).toContain("My graphs");
  expect(container.textContent).toContain("Atlas");
  expect(container.textContent).not.toContain("hidden-personal-slug");
  expect(container.textContent).not.toContain("hidden-team-slug");
  expect(container.textContent).not.toContain("editor");
  expect(container.textContent).not.toContain("manage_members");
  expect(container.textContent).not.toContain("private-user-id");

  const joinButton = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.includes("Join a team"),
  )!;
  await act(async () =>
    joinButton.dispatchEvent(new MouseEvent("click", { bubbles: true })),
  );
  expect(container.textContent).toContain("Ask a team owner to add you.");
  expect(container.textContent).not.toContain("private-user-id");

  await act(async () => root.unmount());
});

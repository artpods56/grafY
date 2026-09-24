// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const workspaceState = vi.hoisted(() => ({
  workspace: {
    id: "workspace-1",
    name: "Operations",
    slug: "operations",
    kind: "shared" as const,
    role: "owner" as const,
    capabilities: ["manage_members"] as readonly string[],
  },
  session: { user_id: "user-1" },
}));

vi.mock("@/features/auth/AuthSessionBoundary", () => ({
  useAuthSession: () => ({ session: workspaceState.session }),
}));

vi.mock("./WorkspaceLayout", () => ({
  useWorkspaceContext: () => ({ workspace: workspaceState.workspace }),
  workspaceCanManageMembers: (workspace: typeof workspaceState.workspace) =>
    workspace.capabilities.includes("manage_members"),
  workspaceDisplayName: (workspace: { name: string; kind: string }) =>
    workspace.kind === "personal" ? "My graphs" : workspace.name,
}));

vi.mock("./WorkspaceMembersDialog", () => ({
  WorkspaceMembersDialog: () => <div data-member-dialog>member dialog</div>,
}));

vi.mock("./WorkspaceLibraryDialog", () => ({
  WorkspaceLibraryDialog: () => <div data-library-dialog>library dialog</div>,
}));

vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.ComponentProps<"a">) => (
    <a {...props}>{children}</a>
  ),
}));

import { WorkspaceOverview } from "./WorkspaceOverview";

afterEach(() => {
  workspaceState.workspace = {
    ...workspaceState.workspace,
    capabilities: ["manage_members"],
  };
});

describe("WorkspaceOverview capability transition", () => {
  it("unmounts member management when the server removes the capability", async () => {
    const container = document.createElement("div");
    const root = createRoot(container);

    await act(async () => root.render(<WorkspaceOverview />));
    expect(container.querySelector("[data-member-dialog]")).not.toBeNull();
    expect(container.textContent).not.toContain("/operations");
    expect(container.textContent).not.toContain("owner");
    expect(container.textContent).not.toContain("manage_members");
    expect(container.textContent).not.toContain("user-1");

    workspaceState.workspace = {
      ...workspaceState.workspace,
      capabilities: [],
    };
    await act(async () => root.render(<WorkspaceOverview />));
    expect(container.querySelector("[data-member-dialog]")).toBeNull();

    await act(async () => root.unmount());
  });
});

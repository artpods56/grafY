// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mocks = vi.hoisted(() => ({
  resolveCandidate: vi.fn(),
  createInvitation: vi.fn(),
  cancelInvitation: vi.fn(),
  changeRole: vi.fn(),
  removeMember: vi.fn(),
  mutateMembers: vi.fn(),
  mutateInvitations: vi.fn(),
  refreshWorkspaces: vi.fn(),
  members: [
    {
      user: {
        id: "user-2",
        display_name: "Second User",
        email: "second@example.com",
        active: true,
      },
      role: "viewer",
      authorization_version: 1,
      revoked_at: null,
    },
  ],
  workspace: {
    id: "workspace-1",
    name: "Operations",
    slug: "operations",
    kind: "shared",
    role: "owner",
    capabilities: ["manage_members"],
  },
  session: { user_id: "user-1" },
}));

vi.mock("@/lib/api", () => ({
  resolveWorkspaceInvitationCandidate: mocks.resolveCandidate,
  createWorkspaceInvitation: mocks.createInvitation,
  cancelWorkspaceInvitation: mocks.cancelInvitation,
  changeWorkspaceMemberRole: mocks.changeRole,
  removeWorkspaceMember: mocks.removeMember,
}));

vi.mock("@/hooks/use-api", () => ({
  useWorkspaceMembers: () => ({
    data: mocks.members,
    error: undefined,
    mutate: mocks.mutateMembers,
  }),
  useWorkspaceInvitations: () => ({
    data: [],
    error: undefined,
    mutate: mocks.mutateInvitations,
  }),
}));

vi.mock("@/features/auth/AuthSessionBoundary", () => ({
  useAuthSession: () => ({ session: mocks.session }),
}));

vi.mock("./WorkspaceLayout", () => ({
  useWorkspaceContext: () => ({
    workspace: mocks.workspace,
    refreshWorkspaces: mocks.refreshWorkspaces,
  }),
}));

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ open, children }: { open: boolean; children: React.ReactNode }) =>
    open ? <div role="dialog">{children}</div> : null,
  DialogBody: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  DialogContent: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  DialogDescription: ({ children }: { children: React.ReactNode }) => (
    <p>{children}</p>
  ),
  DialogHeader: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  DialogTitle: ({ children }: { children: React.ReactNode }) => (
    <h2>{children}</h2>
  ),
}));

import { WorkspaceMembersDialog } from "./WorkspaceMembersDialog";

function renderDialog() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

async function openDialog(container: HTMLElement) {
  await act(async () => {
    container.querySelector("button")?.click();
    await Promise.resolve();
  });
}

function fillEmail(value: string) {
  const input = document.body.querySelector(
    'input[placeholder="person@example.com"]',
  );
  expect(input).toBeInstanceOf(HTMLInputElement);
  Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set?.call(input, value);
  input?.dispatchEvent(new Event("input", { bubbles: true }));
}

async function submitForm() {
  await act(async () => {
    document.body
      .querySelector("form")
      ?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await Promise.resolve();
  });
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.clearAllMocks();
});

beforeEach(() => {
  mocks.resolveCandidate.mockResolvedValue({
    recipient: { display_name: "Invitee", email: "invitee@example.com" },
  });
  mocks.createInvitation.mockResolvedValue(undefined);
  mocks.cancelInvitation.mockResolvedValue(undefined);
  mocks.changeRole.mockResolvedValue(undefined);
  mocks.removeMember.mockResolvedValue(undefined);
  mocks.mutateMembers.mockResolvedValue(mocks.members);
  mocks.mutateInvitations.mockResolvedValue([]);
  mocks.refreshWorkspaces.mockResolvedValue([mocks.workspace]);
});

describe("WorkspaceMembersDialog invitation behavior", () => {
  it("announces and focuses an empty required email", async () => {
    const { container, root } = renderDialog();
    await act(async () => root.render(<WorkspaceMembersDialog />));
    await openDialog(container);
    await submitForm();

    const input = document.body.querySelector('input[type="email"]');
    expect(document.body.textContent).toContain("Enter the verified email");
    expect(input?.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(input);
    expect(mocks.resolveCandidate).not.toHaveBeenCalled();

    await act(async () => root.unmount());
  });

  it("requires candidate confirmation before sending an invitation", async () => {
    const { container, root } = renderDialog();
    await act(async () => root.render(<WorkspaceMembersDialog />));
    await openDialog(container);
    fillEmail("invitee@example.com");
    await submitForm();

    expect(mocks.resolveCandidate).toHaveBeenCalledWith("workspace-1", {
      email: "invitee@example.com",
    });
    expect(mocks.createInvitation).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain(
      "grants no access until accepted",
    );

    const send = [...document.body.querySelectorAll("button")].find(
      (button) => button.textContent === "Send invitation",
    );
    await act(async () => {
      send?.click();
      await Promise.resolve();
    });

    expect(mocks.createInvitation).toHaveBeenCalledWith("workspace-1", {
      email: "invitee@example.com",
      role: "viewer",
    });
    expect(mocks.mutateInvitations).toHaveBeenCalledOnce();
    expect(document.body.textContent).toContain(
      "Access will begin only after it is accepted",
    );

    await act(async () => root.unmount());
  });

  it("confirms a named role change before mutating membership", async () => {
    const { container, root } = renderDialog();
    await act(async () => root.render(<WorkspaceMembersDialog />));
    await openDialog(container);

    const select = document.body.querySelector(
      'select[aria-label="Role for Second User"]',
    );
    expect(select).toBeInstanceOf(HTMLSelectElement);
    Object.getOwnPropertyDescriptor(
      HTMLSelectElement.prototype,
      "value",
    )?.set?.call(select, "editor");
    await act(async () => {
      select?.dispatchEvent(new Event("change", { bubbles: true }));
      await Promise.resolve();
    });

    expect(mocks.changeRole).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain(
      "Confirm change for Second User",
    );
    const confirm = [...document.body.querySelectorAll("button")].find(
      (button) => button.textContent === "Confirm change",
    );
    await act(async () => {
      confirm?.click();
      await Promise.resolve();
    });

    expect(mocks.changeRole).toHaveBeenCalledWith("workspace-1", "user-2", {
      role: "editor",
    });
    expect(mocks.mutateMembers).toHaveBeenCalledOnce();
    expect(mocks.refreshWorkspaces).not.toHaveBeenCalled();

    await act(async () => root.unmount());
  });
});

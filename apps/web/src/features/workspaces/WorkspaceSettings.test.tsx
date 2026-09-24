// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  PersonalAccessToken,
  PersonalAccessTokenCreated,
  Workspace,
} from "@/lib/api";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mocks = vi.hoisted(() => ({
  createToken: vi.fn(),
  listTokens: vi.fn(),
  revokeToken: vi.fn(),
  clipboardWrite: vi.fn(),
  workspace: null as Workspace | null,
}));

vi.mock("@/lib/api", () => ({
  createPersonalAccessToken: mocks.createToken,
  listPersonalAccessTokens: mocks.listTokens,
  revokePersonalAccessToken: mocks.revokeToken,
}));

vi.mock("./WorkspaceLayout", () => ({
  useWorkspaceContext: () => ({ workspace: mocks.workspace }),
  workspaceCanManageMembers: (workspace: Workspace) =>
    workspace.capabilities.includes("manage_members"),
  workspaceDisplayName: (workspace: Workspace) => workspace.name,
}));

vi.mock("./WorkspaceMembersDialog", () => ({
  WorkspaceMembersDialog: () => <button type="button">Manage members</button>,
}));

vi.mock("./WorkspaceLibraryDialog", () => ({
  WorkspaceLibraryDialog: ({ triggerLabel }: { triggerLabel: string }) => (
    <button type="button">{triggerLabel}</button>
  ),
}));

import { WorkspaceSettings } from "./WorkspaceSettings";

const roots = new Set<Root>();

function workspace(overrides: Partial<Workspace> = {}): Workspace {
  return {
    id: "workspace-1",
    name: "Operations",
    slug: "operations",
    kind: "shared",
    role: "owner",
    capabilities: [
      "view_graph",
      "view_artifacts",
      "view_materializations",
      "view_history",
      "view_execution",
      "create_graph",
      "edit_graph",
      "checkpoint_graph",
      "execute_graph",
      "cancel_execution",
      "manage_secrets",
      "publish_plugin",
      "manage_members",
      "manage_module_library",
    ],
    ...overrides,
  };
}

function token(
  overrides: Partial<PersonalAccessToken> = {},
): PersonalAccessToken {
  return {
    id: "token-1",
    workspace_id: "workspace-1",
    public_prefix: "nrt_existing",
    label: "Existing publisher",
    scopes: ["publish_plugin"],
    created_at: "2026-09-01T09:00:00Z",
    last_used_at: null,
    expires_at: "2026-09-20T09:00:00Z",
    revoked_at: null,
    ...overrides,
  };
}

async function renderSettings() {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.add(root);
  await React.act(async () => {
    root.render(
      <SWRConfig
        value={{
          provider: () => new Map(),
          dedupingInterval: 0,
          revalidateOnFocus: false,
        }}
      >
        <WorkspaceSettings />
      </SWRConfig>,
    );
  });
  return container;
}

function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

afterEach(async () => {
  for (const root of roots) {
    await React.act(async () => root.unmount());
  }
  roots.clear();
  document.body.replaceChildren();
  vi.useRealTimers();
  vi.clearAllMocks();
});

beforeEach(() => {
  mocks.workspace = workspace();
  mocks.listTokens.mockResolvedValue([token()]);
  mocks.revokeToken.mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: mocks.clipboardWrite },
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("WorkspaceSettings", () => {
  it("creates, reveals, copies, and revokes a graph automation PAT", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-02T12:00:00Z"));
    const created: PersonalAccessTokenCreated = {
      ...token({
        id: "token-created",
        public_prefix: "nrt_created",
        label: "Notarius publisher",
        created_at: "2026-09-02T12:00:00Z",
        expires_at: "2026-09-09T12:00:00Z",
      }),
      token: "nrt_created.secret-value",
    };
    mocks.createToken.mockResolvedValue(created);

    const container = await renderSettings();
    expect(container.querySelector("h1")?.textContent).toBe("Settings");
    expect(container.textContent).toContain("Operations");
    expect(container.textContent).toContain("Existing publisher");

    const labelInput = container.querySelector<HTMLInputElement>(
      "input[maxlength='160']",
    );
    if (!labelInput) throw new Error("Token label input was not rendered");
    await React.act(async () =>
      setInputValue(labelInput, "Notarius publisher"),
    );

    const form = container.querySelector<HTMLFormElement>(
      ".grafy-workspace-settings__token-form",
    );
    if (!form) throw new Error("Token form was not rendered");
    await React.act(async () => {
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });

    expect(mocks.createToken).toHaveBeenCalledWith("workspace-1", {
      label: "Notarius publisher",
      scopes: [
        "view_graph",
        "view_artifacts",
        "view_materializations",
        "view_history",
        "view_execution",
        "create_graph",
        "edit_graph",
        "checkpoint_graph",
        "execute_graph",
        "cancel_execution",
        "manage_secrets",
      ],
      expires_at: "2026-09-09T12:00:00.000Z",
    });
    expect(container.textContent).toContain("nrt_created.secret-value");

    const copyButton = container.querySelector<HTMLButtonElement>(
      "[aria-label='Copy personal access token']",
    );
    await React.act(async () => copyButton?.click());
    expect(mocks.clipboardWrite).toHaveBeenCalledWith(
      "nrt_created.secret-value",
    );

    const revokeButton = container.querySelector<HTMLButtonElement>(
      "[aria-label='Revoke Existing publisher']",
    );
    await React.act(async () => revokeButton?.click());
    expect(mocks.revokeToken).toHaveBeenCalledWith("workspace-1", "token-1");
  });

  it("can issue a publishing-only PAT when graph automation is unavailable", async () => {
    mocks.workspace = workspace({
      role: "owner",
      capabilities: ["publish_plugin"],
    });
    mocks.createToken.mockResolvedValue({
      ...token(),
      token: "nrt_created.secret-value",
    });

    const container = await renderSettings();
    expect(container.textContent).toContain("Plugin publishing");

    const form = container.querySelector<HTMLFormElement>(
      ".grafy-workspace-settings__token-form",
    );
    if (!form) throw new Error("Token form was not rendered");
    await React.act(async () => {
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });

    expect(mocks.createToken).toHaveBeenCalledWith("workspace-1", {
      label: "Plugin publishing",
      scopes: ["publish_plugin"],
      expires_at: expect.any(String),
    });
  });

  it("does not offer token creation without a supported purpose", async () => {
    mocks.workspace = workspace({
      role: "viewer",
      capabilities: ["view_graph"],
    });

    const container = await renderSettings();

    expect(container.textContent).toContain(
      "Your role does not allow the supported automation workflows",
    );
    expect(container.querySelector("form")).toBeNull();
  });
});

// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  Credential,
  PersonalAccessToken,
  PersonalAccessTokenCreated,
  Workspace,
} from "@/lib/api";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mocks = vi.hoisted(() => ({
  listCredentials: vi.fn(),
  deleteCredential: vi.fn(),
  reverifyCredential: vi.fn(),
  updateCredential: vi.fn(),
  createToken: vi.fn(),
  listTokens: vi.fn(),
  revokeToken: vi.fn(),
  clipboardWrite: vi.fn(),
  workspace: null as Workspace | null,
}));

vi.mock("@/lib/api", () => ({
  listCredentials: mocks.listCredentials,
  deleteCredential: mocks.deleteCredential,
  reverifyCredential: mocks.reverifyCredential,
  updateCredential: mocks.updateCredential,
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
      "view_project",
      "view_artifacts",
      "view_runs",
      "view_runs",
      "view_runs",
      "create_project",
      "edit_project",
      "checkpoint_project",
      "start_run",
      "cancel_run",
      "manage_secrets",
      "edit_project",
      "manage_members",
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
    scopes: ["edit_project"],
    created_at: "2026-09-01T09:00:00Z",
    last_used_at: null,
    expires_at: "2026-09-20T09:00:00Z",
    revoked_at: null,
    ...overrides,
  };
}

function credential(overrides: Partial<Credential> = {}): Credential {
  return {
    id: "team-key",
    scope: "shared",
    provider_kind: "openai_compatible",
    label: "Team key",
    key_hint: "••••abcd",
    usable: true,
    supports_verification: true,
    verification_status: "valid",
    verification_message: null,
    verification_hint: null,
    verified_at: null,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
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
  mocks.listCredentials.mockResolvedValue([]);
  mocks.revokeToken.mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: mocks.clipboardWrite },
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("WorkspaceSettings", () => {
  it("lists a Personal credential and re-verifies it from Settings", async () => {
    const row: Credential = {
      id: "provider-key",
      scope: "personal",
      provider_kind: "mistral",
      label: "My OCR key",
      key_hint: "••••1234",
      usable: true,
      supports_verification: true,
      verification_status: "unverified",
      verification_message: null,
      verification_hint: null,
      verified_at: null,
      created_at: "2026-09-01T10:00:00Z",
      updated_at: "2026-09-01T10:00:00Z",
    };
    mocks.listCredentials.mockImplementation(
      ({ scope }: { scope: Credential["scope"] }) =>
        Promise.resolve(scope === "personal" ? [row] : []),
    );
    mocks.reverifyCredential.mockResolvedValue({
      ...row,
      verification_status: "valid",
      verification_message: "Verified Mistral key.",
    });
    const container = await renderSettings();
    const panel = container.querySelector(
      '[aria-labelledby="credentials-personal-heading"]',
    );
    expect(panel?.textContent).toContain("My OCR key");
    expect(panel?.textContent).toContain("Mistral");
    expect(panel?.textContent).toContain("••••1234");
    expect(panel?.textContent).toContain("Unverified");
    const reverify = panel?.querySelector<HTMLButtonElement>(
      '[aria-label="Re-verify My OCR key"]',
    );
    expect(reverify).not.toBeNull();
    await React.act(async () => reverify?.click());
    expect(mocks.reverifyCredential).toHaveBeenCalledWith(
      { scope: "personal" },
      "provider-key",
    );
    expect(panel?.textContent).toContain("Verified Mistral key.");
  });

  it("deletes a credential only after an inline confirm", async () => {
    mocks.listCredentials.mockImplementation(
      ({ scope }: { scope: Credential["scope"] }) =>
        Promise.resolve(scope === "shared" ? [credential()] : []),
    );
    mocks.deleteCredential.mockResolvedValue(undefined);
    const container = await renderSettings();
    const panel = container.querySelector(
      '[aria-labelledby="credentials-shared-heading"]',
    )!;
    expect(panel.textContent).toContain("Owners manage these keys.");
    await React.act(async () =>
      panel
        .querySelector<HTMLButtonElement>('[aria-label="Delete Team key"]')
        ?.click(),
    );
    expect(mocks.deleteCredential).not.toHaveBeenCalled();
    const cancel = [...panel.querySelectorAll("button")].find(
      (button) => button.textContent === "Cancel",
    );
    await React.act(async () => cancel?.click());
    expect(panel.textContent).not.toContain("Confirm delete");
    await React.act(async () =>
      panel
        .querySelector<HTMLButtonElement>('[aria-label="Delete Team key"]')
        ?.click(),
    );
    const confirm = [...panel.querySelectorAll("button")].find(
      (button) => button.textContent === "Confirm delete",
    );
    await React.act(async () => confirm?.click());
    expect(mocks.deleteCredential).toHaveBeenCalledWith(
      { scope: "shared", workspaceId: "workspace-1" },
      "team-key",
    );
  });

  it("renames and rotates a credential inline", async () => {
    mocks.listCredentials.mockImplementation(
      ({ scope }: { scope: Credential["scope"] }) =>
        Promise.resolve(scope === "shared" ? [credential()] : []),
    );
    mocks.updateCredential.mockResolvedValue(
      credential({
        label: "Ops key",
        verification_message: "Rotated and verified.",
      }),
    );
    const container = await renderSettings();
    const panel = container.querySelector(
      '[aria-labelledby="credentials-shared-heading"]',
    )!;
    await React.act(async () =>
      panel
        .querySelector<HTMLButtonElement>('[aria-label="Edit Team key"]')
        ?.click(),
    );
    const form = panel.querySelector<HTMLFormElement>(
      'form[aria-label="Edit Team key"]',
    )!;
    expect(form).not.toBeNull();
    await React.act(async () => {
      setInputValue(
        form.querySelector<HTMLInputElement>('input[name="label"]')!,
        "Ops key",
      );
      setInputValue(
        form.querySelector<HTMLInputElement>('input[name="value"]')!,
        "new-secret",
      );
    });
    await React.act(async () =>
      form.querySelector<HTMLButtonElement>('button[type="submit"]')?.click(),
    );
    expect(mocks.updateCredential).toHaveBeenCalledWith(
      { scope: "shared", workspaceId: "workspace-1" },
      "team-key",
      {
        label: "Ops key",
        value: "new-secret",
        verify: true,
        save_if_unverified: false,
      },
    );
    expect(panel.textContent).toContain("Rotated and verified.");
    expect(panel.querySelector('form[aria-label="Edit Team key"]')).toBeNull();
  });

  it("says so when no credential is saved yet", async () => {
    const container = await renderSettings();
    expect(
      container.querySelector(
        '[aria-labelledby="credentials-personal-heading"]',
      )?.textContent,
    ).toContain("No personal keys yet.");
  });

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
        "view_project",
        "view_artifacts",
        "view_runs",
        "create_project",
        "edit_project",
        "checkpoint_project",
        "start_run",
        "cancel_run",
        "manage_secrets",
      ],
      expires_at: "2026-09-09T12:00:00.000Z",
    });
    expect(container.textContent).toContain("nrt_created.secret-value");
    expect(container.querySelector("[role='status']")?.textContent).toContain(
      "Copy this token now",
    );

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

  it("announces a token that could not be revoked as an alert", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-02T12:00:00Z"));
    mocks.revokeToken.mockRejectedValueOnce(new Error("offline"));

    const container = await renderSettings();
    const revokeButton = container.querySelector<HTMLButtonElement>(
      "[aria-label='Revoke Existing publisher']",
    );
    await React.act(async () => revokeButton?.click());

    expect(container.querySelector("[role='alert']")?.textContent).toContain(
      "The token could not be revoked.",
    );
  });

  it("can issue a module-publishing PAT when graph automation is unavailable", async () => {
    mocks.workspace = workspace({
      role: "owner",
      capabilities: ["edit_project"],
    });
    mocks.createToken.mockResolvedValue({
      ...token(),
      token: "nrt_created.secret-value",
    });

    const container = await renderSettings();
    expect(container.textContent).toContain("Module publishing");

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
      label: "Module publishing",
      scopes: ["edit_project"],
      expires_at: expect.any(String),
    });
  });

  it("names the purpose and expiry selects by their own labels", async () => {
    const container = await renderSettings();
    const selects = [
      ...container.querySelectorAll<HTMLSelectElement>(
        ".grafy-workspace-settings__token-form select",
      ),
    ];
    expect(selects).toHaveLength(2);
    for (const select of selects) {
      // A `Field` ties its label to the control with an id, which is what the
      // hand-written `<label>` row used to do by nesting.
      const label = container.querySelector(`label[for="${select.id}"]`);
      expect(label?.textContent?.trim()).toContain(
        select === selects[0] ? "Purpose" : "Expires in",
      );
    }
    expect(selects[1]?.value).toBe("7");
  });

  it("does not offer token creation without a supported purpose", async () => {
    mocks.workspace = workspace({
      role: "viewer",
      capabilities: ["view_project"],
    });

    const container = await renderSettings();

    expect(container.textContent).toContain(
      "Your role does not allow the supported automation workflows",
    );
    expect(container.querySelector("form")).toBeNull();
  });
});

// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CatalogPack,
  Credential,
  PersonalAccessToken,
  PersonalAccessTokenCreated,
  Workspace,
} from "@/lib/api";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mocks = vi.hoisted(() => ({
  listPacks: vi.fn(),
  setPack: vi.fn(),
  request: vi.fn(),
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
  workspacePacksPath: (id: string) => `/v1/workspaces/${id}/packs`,
  listWorkspacePacks: mocks.listPacks,
  setWorkspacePack: mocks.setPack,
  listCredentials: mocks.listCredentials,
  deleteCredential: mocks.deleteCredential,
  reverifyCredential: mocks.reverifyCredential,
  updateCredential: mocks.updateCredential,
  createPersonalAccessToken: mocks.createToken,
  listPersonalAccessTokens: mocks.listTokens,
  revokePersonalAccessToken: mocks.revokeToken,
}));

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  request: mocks.request,
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
      "manage_packs",
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

async function renderSettings(cache = new Map<string, { data?: unknown }>()) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.add(root);
  await React.act(async () => {
    root.render(
      <SWRConfig
        value={{
          provider: () => cache,
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
  mocks.listPacks.mockResolvedValue([]);
  mocks.listCredentials.mockResolvedValue([]);
  mocks.revokeToken.mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: mocks.clipboardWrite },
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

const essentials: CatalogPack = {
  slug: "essentials",
  title: "Essentials",
  description: "Import tables and work with images.",
  always_on: true,
  subscribed: true,
  operator_count: 8,
  provider_count: 0,
  includes_project_graphs: false,
};
const maps: CatalogPack = {
  ...essentials,
  slug: "maps",
  title: "Maps & GIS",
  description: "Assemble map layers.",
  always_on: false,
  subscribed: false,
  operator_count: 10,
};

function packSwitch(container: HTMLElement, title: string): HTMLElement {
  const control = [
    ...container.querySelectorAll<HTMLElement>('[role="switch"]'),
  ].find((element) => {
    const label = element.getAttribute("aria-labelledby");
    return label && document.getElementById(label)?.textContent === title;
  });
  if (!control) throw new Error(`Expected pack switch for ${title}`);
  return control;
}

describe("WorkspaceSettings", () => {
  it("updates a Pack subscription and refreshes the Workspace node registry", async () => {
    mocks.listPacks.mockResolvedValue([essentials, maps]);
    mocks.setPack.mockImplementation(async () => {
      const subscribed = { ...maps, subscribed: true };
      mocks.listPacks.mockResolvedValue([essentials, subscribed]);
      return subscribed;
    });
    const registry = {
      packs: [essentials, { ...maps, subscribed: true }],
      plugins: [],
      nodes: [],
      artifact_types: [],
      artifact_conversions: [],
    };
    mocks.request.mockResolvedValue(registry);
    const cache = new Map<string, { data?: unknown }>();
    const container = await renderSettings(cache);
    expect(container.querySelector("#tool-packs")?.textContent).toContain(
      "Always on",
    );
    const required = packSwitch(container, "Essentials");
    expect(required.getAttribute("aria-checked")).toBe("true");
    expect(required.hasAttribute("data-disabled")).toBe(true);

    const optional = packSwitch(container, "Maps & GIS");
    expect(optional.getAttribute("aria-checked")).toBe("false");
    await React.act(async () => optional.click());

    expect(mocks.setPack).toHaveBeenCalledWith("workspace-1", "maps", {
      subscribed: true,
    });
    expect(cache.get("/v1/workspaces/workspace-1/nodes")?.data).toEqual(
      registry,
    );
    expect(optional.getAttribute("aria-checked")).toBe("true");
  });

  it("shows read-only Pack subscriptions to members without manage_packs", async () => {
    mocks.workspace = workspace({
      role: "editor",
      capabilities: ["view_project"],
    });
    mocks.listPacks.mockResolvedValue([essentials, maps]);
    const container = await renderSettings();
    const optional = packSwitch(container, "Maps & GIS");
    expect(optional.hasAttribute("data-disabled")).toBe(true);
    await React.act(async () => optional.click());
    expect(mocks.setPack).not.toHaveBeenCalled();
  });

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

    const form = labelInput.closest("form");
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

    const submit = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Create token",
    );
    const form = submit?.closest("form");
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
    const submit = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Create token",
    );
    const form = submit?.closest("form");
    const selects = [
      ...(form?.querySelectorAll<HTMLSelectElement>("select") ?? []),
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

  it("navigates sections via the settings subsidebar and omits Members for personal workspaces", async () => {
    const container = await renderSettings();
    const subnav = container.querySelector(
      'nav[aria-label="Settings sections"]',
    );
    expect(subnav).not.toBeNull();

    const labels = [...(subnav?.querySelectorAll("button") ?? [])].map((btn) =>
      btn.textContent?.trim(),
    );
    expect(labels).toEqual([
      "General",
      "Tool packs",
      "Provider credentials",
      "Members",
      "Access tokens",
    ]);

    const generalButton = subnav?.querySelector<HTMLButtonElement>(
      'button[data-section-id="general"]',
    );
    const packsButton = subnav?.querySelector<HTMLButtonElement>(
      'button[data-section-id="tool-packs"]',
    );
    expect(generalButton?.getAttribute("data-active")).toBe("true");
    expect(packsButton?.getAttribute("data-active")).toBeNull();

    const packsSection = container.querySelector<HTMLElement>("#tool-packs");
    const scrollIntoView = vi.fn();
    if (packsSection) {
      packsSection.scrollIntoView = scrollIntoView;
    }

    await React.act(async () => packsButton?.click());

    expect(packsButton?.getAttribute("data-active")).toBe("true");
    expect(packsButton?.getAttribute("aria-current")).toBe("location");
    expect(generalButton?.getAttribute("data-active")).toBeNull();
    expect(scrollIntoView).toHaveBeenCalledTimes(1);

    mocks.workspace = workspace({
      kind: "personal",
      name: "Personal workspace",
    });
    const personalContainer = await renderSettings();
    const personalSubnav = personalContainer.querySelector(
      'nav[aria-label="Settings sections"]',
    );
    const personalLabels = [
      ...(personalSubnav?.querySelectorAll("button") ?? []),
    ].map((btn) => btn.textContent?.trim());
    expect(personalLabels).toEqual([
      "General",
      "Tool packs",
      "Provider credentials",
      "Access tokens",
    ]);
    expect(personalContainer.querySelector("#members")).toBeNull();
  });
});

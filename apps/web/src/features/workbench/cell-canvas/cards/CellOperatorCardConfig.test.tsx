// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Credential, CredentialVerification, NodeSpec } from "@/lib/api";

import {
  askModelSpec,
  fixtureDocument,
  fixtureNode,
  richRegistry,
  vectorLayerSpec,
} from "../cell-config-fixtures.test-support";
import type { CellSecretInputSpec } from "../cell-contracts";
import { buildOperatorCardsAndSurfaces } from "../cell-operator-adapter";
import {
  CellOperatorCard,
  type CellOperatorCardProps,
} from "./CellOperatorCard";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const roots: ReturnType<typeof createRoot>[] = [];

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  document.body.replaceChildren();
});

function mount(
  spec: NodeSpec,
  config: Record<string, unknown>,
  props: Partial<CellOperatorCardProps> = {},
  secretInputs?: readonly CellSecretInputSpec[],
) {
  const registry = {
    ...richRegistry,
    nodes: richRegistry.nodes.map((node) =>
      node.operator_id === spec.operator_id ? spec : node,
    ),
  };
  const { cards, surfaces } = buildOperatorCardsAndSurfaces(
    fixtureDocument([fixtureNode("node", spec, config)]),
    registry,
  );
  const surface = surfaces.get("node");
  if (surface?.kind !== "operator") throw new Error("operator surface");
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  React.act(() => {
    root.render(
      <CellOperatorCard
        card={cards[0]!}
        surface={secretInputs ? { ...surface, secretInputs } : surface}
        selected
        dragging={false}
        {...props}
      />,
    );
  });
  return container;
}

function click(element: Element | null) {
  expect(element).not.toBeNull();
  React.act(() => {
    (element as HTMLElement).click();
  });
}

function type(input: HTMLInputElement | null, value: string) {
  expect(input).not.toBeNull();
  React.act(() => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set?.call(input, value);
    input!.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("CellOperatorCard config interactions", () => {
  it("asks to open the advanced fold for its own card", () => {
    const onToggleConfigSection = vi.fn();
    const container = mount(
      vectorLayerSpec,
      { title: "Roads" },
      { onToggleConfigSection, onConfigChange: vi.fn() },
    );
    click(container.querySelector('[data-config-section="advanced"]'));
    expect(onToggleConfigSection).toHaveBeenCalledWith(
      "node",
      "advanced",
      true,
    );
  });

  it("commits the whole `Style` value when the branch changes", () => {
    const onConfigChange = vi.fn();
    const container = mount(
      vectorLayerSpec,
      { title: "Roads" },
      { onConfigChange },
    );
    const byCategory = [
      ...container.querySelectorAll('[aria-label="Style mode"] [role="radio"]'),
    ].find((radio) => radio.textContent === "By category");
    click(byCategory ?? null);
    expect(onConfigChange).toHaveBeenCalledTimes(1);
    const [cardId, fieldId, value] = onConfigChange.mock.calls[0]!;
    expect([cardId, fieldId]).toEqual(["node", "style"]);
    expect(value).toMatchObject({
      kind: "categorized_points",
      categories: [{ title: "Category 1", color: "#ff8800" }],
    });
  });

  it("draws a dense select when the `Style` branch titles are class names", () => {
    const longTitles = structuredClone(vectorLayerSpec);
    const defs = longTitles.config_schema.$defs as Record<
      string,
      { title?: string }
    >;
    defs.GeoVectorStyle!.title = "GeoVectorStyle";
    defs.GeoCategorizedPointStyle!.title = "GeoCategorizedPointStyle";
    const onConfigChange = vi.fn();
    const container = mount(longTitles, { title: "Roads" }, { onConfigChange });
    const union = container.querySelector('[data-config-union="style"]');
    expect(union?.querySelector('[role="radio"]')).toBeNull();
    const picker = union?.querySelector<HTMLSelectElement>(
      'select[aria-label="Style mode"]',
    );
    expect(picker?.title).toBe("GeoVectorStyle");
    expect([...(picker?.options ?? [])].map((option) => option.text)).toEqual([
      "GeoVectorStyle",
      "GeoCategorizedPointStyle",
    ]);
    React.act(() => {
      picker!.value = "categorized_points";
      picker!.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(onConfigChange).toHaveBeenCalledWith(
      "node",
      "style",
      expect.objectContaining({ kind: "categorized_points" }),
    );
  });

  it("keeps short `Style` branch titles as truncating segments", () => {
    const container = mount(vectorLayerSpec, { title: "Roads" });
    const labels = [
      ...container.querySelectorAll(
        '[aria-label="Style mode"] [role="radio"] span[title]',
      ),
    ].map((label) => label.getAttribute("title"));
    expect(labels).toEqual(["Simple", "By category"]);
  });

  it("adds an item to an object list with a fresh id and a numbered title", () => {
    const onConfigChange = vi.fn();
    const style = {
      kind: "categorized_points",
      categories: [{ id: "c1", title: "Roads", color: "#ff0000" }],
    };
    const container = mount(
      vectorLayerSpec,
      { title: "Roads", style },
      { onConfigChange },
    );
    const add = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Add category",
    );
    click(add ?? null);
    const [, fieldId, value] = onConfigChange.mock.calls[0]!;
    expect(fieldId).toBe("style");
    const categories = (value as typeof style).categories;
    expect(categories).toHaveLength(2);
    expect(categories[1]).toMatchObject({ title: "Category 2" });
    expect(typeof (categories[1] as { id?: unknown }).id).toBe("string");
  });

  it("commits a nested colour once its hex is whole", () => {
    const onConfigChange = vi.fn();
    const container = mount(
      vectorLayerSpec,
      { title: "Roads" },
      { onConfigChange },
    );
    const hex = container.querySelector<HTMLInputElement>(
      'input[aria-label="Fill hex"]',
    );
    type(hex, "#12");
    expect(onConfigChange).not.toHaveBeenCalled();
    type(hex, "#1188FF");
    expect(onConfigChange).toHaveBeenLastCalledWith(
      "node",
      "style",
      expect.objectContaining({ kind: "simple", fill: "#1188ff" }),
    );
  });

  it("draws every control disabled on a card that cannot be edited", () => {
    const container = mount(vectorLayerSpec, { title: "Roads" });
    const title = container.querySelector<HTMLInputElement>(
      '[data-config-field="title"] input',
    );
    expect(title?.disabled).toBe(true);
  });
});

describe("CellOperatorCard credentials popover", () => {
  const configured: CellSecretInputSpec = {
    name: "api_key",
    title: "API key",
    state: "configured",
    ready: true,
    revision: "graph:1",
  };

  function openPopover(
    inputs: readonly CellSecretInputSpec[],
    props: Partial<CellOperatorCardProps> = {},
  ) {
    const container = mount(askModelSpec, {}, props, inputs);
    click(container.querySelector("[data-credentials-trigger]"));
    const popup = document.querySelector('[data-credentials-popover="node"]');
    expect(popup).not.toBeNull();
    return { container, popup: popup as HTMLElement };
  }

  const sharedKey: Credential = {
    id: "vault-key",
    scope: "shared",
    provider_kind: "openai_compatible",
    label: "Team gateway",
    key_hint: "••••1234",
    usable: true,
    supports_verification: true,
    verification_status: "valid",
    verification_message: "Verified OpenAI-compatible key.",
    verification_hint: null,
    verified_at: "2026-09-01T10:00:00Z",
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
  };

  function vaultInput(
    status: Partial<NonNullable<CellSecretInputSpec["vault"]>["status"]> = {},
    vault: Partial<NonNullable<CellSecretInputSpec["vault"]>> = {},
  ): CellSecretInputSpec {
    return {
      ...configured,
      vault: {
        workspaceId: "workspace",
        canEditShared: true,
        canSelectPersonal: true,
        canManageShared: false,
        credentials: [sharedKey],
        provider: { kind: "openai_compatible", fields: ["base_url"] },
        select: vi.fn(async () => {}),
        verify: vi.fn(async (): Promise<CredentialVerification> => ({
          status: "valid",
          message: "Verified.",
          account_hint: null,
        })),
        refresh: vi.fn(async () => {}),
        ...vault,
        status: {
          node_id: "node",
          name: "api_key",
          configured: true,
          provider_kind: "openai_compatible",
          supports_verification: true,
          effective_source: "shared_credential",
          effective_credential_id: sharedKey.id,
          effective_credential_label: sharedKey.label,
          effective_verification_status: "valid",
          shared_binding_mode: "credential",
          shared_credential_id: sharedKey.id,
          shared_credential_label: sharedKey.label,
          shared_credential_missing: false,
          personal_override_mode: "none",
          deployment_default_available: false,
          ...status,
        },
      },
    };
  }

  function buttonNamed(root: ParentNode, text: string) {
    return (
      [...root.querySelectorAll("button")].find(
        (button) => button.textContent === text,
      ) ?? null
    );
  }

  it("leads with the key that runs the node and binds the graph default", async () => {
    const input = vaultInput();
    const { container, popup } = openPopover([input]);
    expect(
      container.querySelector('[data-credentials-trigger="configured"]'),
    ).not.toBeNull();
    const summary = popup.querySelector("[data-credential-source]");
    expect(summary?.getAttribute("data-credential-source")).toBe(
      "shared_credential",
    );
    expect(summary?.textContent).toContain("Shared");
    expect(summary?.textContent).toContain("Team gateway");
    expect(summary?.textContent).toContain("••••1234");
    expect(
      summary?.querySelector('[data-verification="valid"]')?.textContent,
    ).toBe("Verified");
    expect(popup.textContent).toContain("OpenAI-compatible");
    expect(
      popup.querySelector('[aria-label="Re-verify API key"]'),
    ).not.toBeNull();

    // One picker at a time: "My run" first, "Graph default" behind its tab.
    const personal = popup.querySelector<HTMLSelectElement>(
      '[aria-label="API key personal selection"]',
    );
    expect(personal?.value).toBe("none");
    expect(
      [...(personal?.querySelectorAll("optgroup") ?? [])].map(
        (group) => group.label,
      ),
    ).toEqual(["Default", "Shared (workspace)"]);
    expect(
      popup.querySelector('[aria-label="API key graph binding"]'),
    ).toBeNull();
    expect(popup.textContent).toContain("Overrides only your runs.");
    const graphTab = [
      ...popup.querySelectorAll(
        '[aria-label="API key selection scope"] [role="radio"]',
      ),
    ].find((radio) => radio.textContent === "Graph default");
    click(graphTab ?? null);
    const graphBinding = popup.querySelector<HTMLSelectElement>(
      '[aria-label="API key graph binding"]',
    );
    expect(graphBinding?.value).toBe("credential:vault-key");
    expect(popup.textContent).toContain(
      "Default for everyone who runs this graph.",
    );
    if (!graphBinding) throw new Error("Graph binding picker is missing");
    await React.act(async () => {
      graphBinding.value = "personal";
      graphBinding.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(input.vault?.select).toHaveBeenCalledWith({
      scope: "shared",
      binding: { mode: "personal" },
    });
  });

  it("saves an unreachable Personal key anyway and selects it for my runs", async () => {
    const input = vaultInput();
    const { popup } = openPopover([input]);
    click(buttonNamed(popup, "Add credential"));
    expect(popup.querySelector('[aria-label="Credential scope"]')).toBeNull();
    type(
      popup.querySelector<HTMLInputElement>('input[name="value"]'),
      "synthetic-personal-key",
    );
    type(
      popup.querySelector<HTMLInputElement>('input[name="label"]'),
      "My key",
    );

    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        Response.json(
          {
            detail: {
              can_save_unverified: true,
              verification: {
                status: "unreachable",
                message: "Provider unreachable.",
                account_hint: null,
              },
            },
          },
          { status: 422 },
        ),
      )
      .mockResolvedValueOnce(
        Response.json(
          {
            ...sharedKey,
            id: "my-key",
            label: "My key",
            scope: "personal",
            verification_status: "unreachable",
            verification_message: "Saved without verification.",
          },
          { status: 201 },
        ),
      );
    vi.stubGlobal("fetch", fetcher);
    try {
      await React.act(async () => {
        popup
          .querySelector<HTMLButtonElement>('button[type="submit"]')
          ?.click();
      });
      expect(popup.textContent).toContain("Provider unreachable.");
      const saveAnyway = buttonNamed(popup, "Save anyway");
      expect(saveAnyway).not.toBeNull();
      await React.act(async () => saveAnyway?.click());
      expect(fetcher).toHaveBeenLastCalledWith(
        "/api/v1/me/credentials",
        expect.objectContaining({
          body: expect.stringContaining('"save_if_unverified":true'),
        }),
      );
      expect(popup.textContent).toContain("Saved without verification.");
      expect(popup.querySelector('input[name="value"]')).toBeNull();
      expect(input.vault?.select).toHaveBeenCalledWith({
        scope: "personal",
        binding: { mode: "credential", credential_id: "my-key" },
      });
      expect(input.vault?.refresh).toHaveBeenCalled();
      expect(popup.textContent).toContain("Now using “My key”.");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("makes a new Shared key the graph default and drops my override", async () => {
    const input = vaultInput(
      { personal_override_mode: "deployment_default" },
      { canManageShared: true },
    );
    const { popup } = openPopover([input]);
    click(buttonNamed(popup, "Add credential"));
    const shared = [
      ...popup.querySelectorAll(
        '[aria-label="Credential scope"] [role="radio"]',
      ),
    ].find((radio) => radio.textContent === "Shared");
    click(shared ?? null);
    type(popup.querySelector<HTMLInputElement>('input[name="value"]'), "k");
    type(popup.querySelector<HTMLInputElement>('input[name="label"]'), "Ops");
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        Response.json(
          { ...sharedKey, id: "ops", label: "Ops" },
          { status: 201 },
        ),
      );
    vi.stubGlobal("fetch", fetcher);
    try {
      await React.act(async () => {
        popup
          .querySelector<HTMLButtonElement>('button[type="submit"]')
          ?.click();
      });
      expect(fetcher).toHaveBeenCalledWith(
        "/api/v1/workspaces/workspace/credentials",
        expect.anything(),
      );
      expect(input.vault?.select).toHaveBeenNthCalledWith(1, {
        scope: "shared",
        binding: { mode: "credential", credential_id: "ops" },
      });
      expect(input.vault?.select).toHaveBeenNthCalledWith(2, {
        scope: "personal",
        binding: { mode: "none" },
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("tests a pasted key without saving it", async () => {
    const { popup } = openPopover([vaultInput()]);
    click(buttonNamed(popup, "Add credential"));
    type(popup.querySelector<HTMLInputElement>('input[name="value"]'), "k");
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(
      Response.json({
        status: "valid",
        message: "42 models available",
        account_hint: null,
      }),
    );
    vi.stubGlobal("fetch", fetcher);
    try {
      await React.act(async () => buttonNamed(popup, "Test key")?.click());
      expect(fetcher).toHaveBeenCalledWith(
        "/api/v1/me/credentials/verify",
        expect.objectContaining({
          body: expect.stringContaining('"provider_kind":"openai_compatible"'),
        }),
      );
      expect(
        popup.querySelector('[data-credential-callout="success"]')?.textContent,
      ).toBe("Verified · 42 models available");
      // Renaming keeps the result; a new key clears it.
      type(popup.querySelector<HTMLInputElement>('input[name="label"]'), "A");
      expect(popup.querySelector("[data-credential-callout]")).not.toBeNull();
      type(popup.querySelector<HTMLInputElement>('input[name="value"]'), "k2");
      expect(popup.querySelector("[data-credential-callout]")).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("marks the header key red for a refused or missing key", () => {
    const invalid = mount(askModelSpec, {}, {}, [
      vaultInput({ effective_verification_status: "invalid" }),
    ]);
    expect(
      invalid.querySelector('[data-credentials-trigger="error"]'),
    ).not.toBeNull();
    const missing = mount(askModelSpec, {}, {}, [
      vaultInput({ shared_credential_missing: true }),
    ]);
    expect(
      missing.querySelector('[data-credentials-trigger="error"]'),
    ).not.toBeNull();
    const unreachable = mount(askModelSpec, {}, {}, [
      vaultInput({ effective_verification_status: "unreachable" }),
    ]);
    expect(
      unreachable.querySelector('[data-credentials-trigger="needed"]'),
    ).not.toBeNull();
    const unset = mount(askModelSpec, {}, {}, [
      vaultInput({
        configured: false,
        effective_source: "none",
        effective_verification_status: null,
      }),
    ]);
    expect(
      unset.querySelector('[data-credentials-trigger="needed"]'),
    ).not.toBeNull();
  });

  it("opens from the header key and lists each key with its status", () => {
    const { container, popup } = openPopover([configured]);
    expect(
      container.querySelector('[data-credentials-trigger="configured"]'),
    ).not.toBeNull();
    expect(popup.textContent).toContain("Credentials");
    expect(popup.textContent).toContain("API key");
    expect(
      popup.querySelector('[data-secret-status="configured"]')?.textContent,
    ).toBe("Configured");
    const input = popup.querySelector<HTMLInputElement>(
      'input[type="password"]',
    );
    expect(input?.value).toBe("");
    expect(input?.autocomplete).toBe("off");
  });

  it("applies a pasted key and clears the input once it is saved", async () => {
    let resolve: (applied: boolean) => void = () => {};
    const applied = new Promise<boolean>((done) => {
      resolve = done;
    });
    const onApplySecret = vi.fn(() => applied);
    const { popup } = openPopover([{ ...configured, state: "unconfigured" }], {
      onApplySecret,
    });
    expect(popup.textContent).toContain("Not set");
    const input = popup.querySelector<HTMLInputElement>(
      'input[type="password"]',
    );
    type(input, "sk-test");
    const apply = [...popup.querySelectorAll("button")].find(
      (button) => button.textContent === "Apply",
    );
    expect(apply?.disabled).toBe(false);
    click(apply ?? null);
    expect(onApplySecret).toHaveBeenCalledWith("node", "api_key", "sk-test");
    await React.act(async () => {
      resolve(true);
      await applied;
    });
    expect(input?.value).toBe("");
  });

  it("removes a configured key", () => {
    const onRemoveSecret = vi.fn(() => Promise.resolve(true));
    const { popup } = openPopover([configured], { onRemoveSecret });
    const remove = [...popup.querySelectorAll("button")].find(
      (button) => button.textContent === "Remove",
    );
    expect(remove?.disabled).toBe(false);
    click(remove ?? null);
    expect(onRemoveSecret).toHaveBeenCalledWith("node", "api_key");
  });

  it("asks for a save before a key can be written to an unsaved node", () => {
    const { container, popup } = openPopover(
      [{ ...configured, state: "unknown", ready: false }],
      { onApplySecret: vi.fn(), onRemoveSecret: vi.fn() },
    );
    expect(
      container.querySelector('[data-credentials-trigger="needed"]'),
    ).not.toBeNull();
    expect(popup.textContent).toContain("Save node first");
    expect(popup.textContent).toContain("Save this node before adding a key.");
    expect(
      popup.querySelector<HTMLInputElement>('input[type="password"]')?.disabled,
    ).toBe(true);
    const remove = [...popup.querySelectorAll("button")].find(
      (button) => button.textContent === "Remove",
    );
    expect(remove?.disabled).toBe(true);
  });

  it("closes on Escape", () => {
    const { popup } = openPopover([configured]);
    React.act(() => {
      popup.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
    });
    expect(
      document.querySelector('[data-credentials-popover="node"]'),
    ).toBeNull();
  });
});

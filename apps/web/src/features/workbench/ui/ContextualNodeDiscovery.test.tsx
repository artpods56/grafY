// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import { encodeHandleId } from "../canvas/handles";
import { portMetaForPort } from "../canvas/types";
import {
  downstreamCandidatesFromOutput,
  upstreamCandidatesFromInput,
} from "../model/node-catalog";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  keyframes: () => "spin",
  props: () => ({}),
}));

vi.mock("@xyflow/react", () => ({
  ViewportPortal: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="canvas-preview">{children}</div>
  ),
  useStore: (selector: (state: { nodeLookup: Map<string, unknown> }) => unknown) =>
    selector({ nodeLookup: new Map() }),
}));

import {
  ContextualNodeDiscovery,
  popupPositionBesidePreview,
  type ContextualDiscoverySession,
  type ContextualGenerationRequest,
} from "./ContextualNodeDiscovery";

const roots = new Map<Root, HTMLElement>();

beforeEach(() => {
  document.documentElement.style.setProperty("--grafy-mobile-overlay-top", "68px");
});

function port(
  name: string,
  direction: Port["direction"],
  artifactTypeId = "scalar.text",
): Port {
  return {
    name,
    title: name[0]?.toUpperCase() + name.slice(1),
    description: null,
    direction,
    artifact_type: { id: artifactTypeId, schema_version: 1 },
    artifact_type_variable: null,
    shape: "one",
    accepted_shapes: ["one"],
    instance_plugs: false,
    variadic: false,
    required: true,
  };
}

function node(
  operatorId: string,
  title: string,
  inputs: readonly Port[],
  outputs: readonly Port[],
): NodeSpec {
  return {
    operator_id: operatorId,
    operator_version: 1,
    plugin_slug: "builtin",
    title,
    description: `${title} description`,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs,
    outputs,
    catalog_visible: true,
  };
}

function registry(): NodeRegistry {
  const textIn = port("text", "input");
  const textOut = port("text", "output");
  const altIn = port("body", "input");
  return {
    plugins: [{ slug: "builtin", title: "Built-in", origin: "builtin" }],
    artifact_types: [
      {
        key: { id: "scalar.text", schema_version: 1 },
        title: "Text",
        payload_schema: {},
        field_projections: [],
      },
    ],
    artifact_conversions: [],
    nodes: [
      node("text.replace", "Replace text", [textIn], [textOut]),
      node("text.annotate", "Annotate text", [textIn, altIn], [textOut]),
    ],
  };
}

function sessionFor(
  registryValue: NodeRegistry,
): ContextualDiscoverySession {
  const source = port("text", "output");
  const sourceHandle = encodeHandleId(portMetaForPort(source));
  const candidates = downstreamCandidatesFromOutput({
    sourcePort: source as Port & { readonly direction: "output" },
    sourceHandle,
    registry: registryValue,
    nodes: registryValue.nodes,
  });
  return {
    sourceNodeId: "source-1",
    sourceHandle,
    sourcePortTitle: "Text",
    sourceArtifactType: { id: "scalar.text", schema_version: 1 },
    sourceShape: "one",
    direction: "downstream",
    clientAnchor: { x: 120, y: 140 },
    flowPosition: { x: 400, y: 300 },
    candidates,
    graphId: null,
  };
}

function upstreamSessionFor(
  registryValue: NodeRegistry,
): ContextualDiscoverySession {
  const target = port("text", "input");
  const targetHandle = encodeHandleId(portMetaForPort(target));
  const candidates = upstreamCandidatesFromInput({
    targetPort: target as Port & { readonly direction: "input" },
    targetHandle,
    registry: registryValue,
    nodes: registryValue.nodes,
  });
  return {
    sourceNodeId: "source-1",
    sourceHandle: targetHandle,
    sourcePortTitle: "Text",
    sourceArtifactType: { id: "scalar.text", schema_version: 1 },
    sourceShape: "one",
    direction: "upstream",
    clientAnchor: { x: 120, y: 140 },
    flowPosition: { x: 400, y: 300 },
    candidates,
    graphId: null,
  };
}

async function renderDiscovery(
  overrides: Partial<React.ComponentProps<typeof ContextualNodeDiscovery>> = {},
) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.set(root, container);
  const registryValue = registry();
  await React.act(async () => {
    root.render(
      <ContextualNodeDiscovery
        session={overrides.session ?? sessionFor(registryValue)}
        registry={registryValue}
        canInsert
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        {...overrides}
      />,
    );
    await Promise.resolve();
  });
  return { container, root, registry: registryValue };
}

function enterControlValue(
  control: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement,
  value: string,
): void {
  const prototype = control instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : control instanceof HTMLSelectElement
      ? HTMLSelectElement.prototype
      : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  if (!setter) throw new Error("Form control value setter is unavailable");
  setter.call(control, value);
  control.dispatchEvent(
    new Event(control instanceof HTMLSelectElement ? "change" : "input", {
      bubbles: true,
    }),
  );
}

afterEach(async () => {
  for (const [root, container] of roots) {
    await React.act(async () => root.unmount());
    container.remove();
  }
  roots.clear();
  document.body.innerHTML = "";
  document.documentElement.style.removeProperty("--grafy-mobile-overlay-top");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("popupPositionBesidePreview", () => {
  it("places the menu to the right of the canvas preview when there is room", () => {
    expect(
      popupPositionBesidePreview(
        { left: 80, top: 120, right: 380, width: 300 },
        { x: 80, y: 120 },
        340,
        480,
        { width: 1200, height: 800 },
      ),
    ).toEqual({ left: 396, top: 120 });
  });

  it("flips to the left when the preview sits near the right edge", () => {
    expect(
      popupPositionBesidePreview(
        { left: 900, top: 80, right: 1200, width: 300 },
        { x: 900, y: 80 },
        340,
        480,
        { width: 1280, height: 800 },
      ),
    ).toEqual({ left: 544, top: 80 });
  });

  it("keeps a compact menu inside a phone viewport", () => {
    expect(
      popupPositionBesidePreview(
        null,
        { x: 300, y: 460 },
        296,
        456,
        { width: 320, height: 480 },
      ),
    ).toEqual({ left: 12, top: 12 });
  });
});

describe("ContextualNodeDiscovery", () => {
  it.each([
    { matches: true, shouldFocus: true },
    { matches: false, shouldFocus: false },
  ])(
    "focuses search only for fine pointers: $matches",
    async ({ matches, shouldFocus }) => {
      vi.stubGlobal(
        "matchMedia",
        vi.fn(
          (query: string): MediaQueryList =>
            ({
              matches: query === "(pointer: fine)" && matches,
              media: query,
              onchange: null,
              addEventListener: vi.fn(),
              removeEventListener: vi.fn(),
              addListener: vi.fn(),
              removeListener: vi.fn(),
              dispatchEvent: vi.fn(),
            }) satisfies MediaQueryList,
        ),
      );
      const { container } = await renderDiscovery();
      const search = container.querySelector<HTMLInputElement>(
        '[aria-label="Search compatible nodes"]',
      );

      await vi.waitFor(() => {
        expect(document.activeElement === search).toBe(shouldFocus);
      });
      expect(container.textContent).toContain(
        shouldFocus ? "Hover to preview · Enter adds" : "Tap to choose a node",
      );
    },
  );

  it("does not steal focus when pointer capability changes during a session", async () => {
    let matches = false;
    const listeners = new Set<EventListener>();
    vi.stubGlobal(
      "matchMedia",
      vi.fn(
        (query: string): MediaQueryList =>
          ({
            get matches() {
              return query === "(pointer: fine)" && matches;
            },
            media: query,
            onchange: null,
            addEventListener: ((_type: string, listener: EventListener) => {
              listeners.add(listener);
            }) as MediaQueryList["addEventListener"],
            removeEventListener: ((_type: string, listener: EventListener) => {
              listeners.delete(listener);
            }) as MediaQueryList["removeEventListener"],
            addListener: vi.fn(),
            removeListener: vi.fn(),
            dispatchEvent: vi.fn(),
          }) satisfies MediaQueryList,
      ),
    );
    const { container } = await renderDiscovery();
    const cancelButton = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Cancel",
    );
    cancelButton?.focus();

    matches = true;
    await React.act(async () => {
      for (const listener of listeners) listener(new Event("change"));
    });

    expect(document.activeElement).toBe(cancelButton);
  });

  it("uses the root mobile overlay token for compact geometry", async () => {
    document.documentElement.style.setProperty("--grafy-mobile-overlay-top", "92px");
    vi.stubGlobal("innerWidth", 320);
    vi.stubGlobal("innerHeight", 480);

    const { container } = await renderDiscovery();
    const dialog = container.querySelector<HTMLElement>('[role="dialog"]');

    expect(dialog?.style.top).toContain("92px");
    expect(dialog?.style.maxHeight).toContain("376px");
  });

  it("reclamps to visual viewport height changes without a safe-area probe", async () => {
    vi.stubGlobal("innerWidth", 320);
    vi.stubGlobal("innerHeight", 480);
    const viewportEvents = new EventTarget();
    let visualHeight = 480;
    vi.stubGlobal("visualViewport", {
      get height() {
        return visualHeight;
      },
      offsetTop: 0,
      addEventListener: viewportEvents.addEventListener.bind(viewportEvents),
      removeEventListener:
        viewportEvents.removeEventListener.bind(viewportEvents),
    });
    const { container } = await renderDiscovery();
    const dialog = container.querySelector<HTMLElement>('[role="dialog"]');
    expect(dialog?.style.maxHeight).toContain("400px");
    expect(container.firstElementChild?.getAttribute("data-testid")).toBe(
      "canvas-preview",
    );

    await React.act(async () => {
      visualHeight = 300;
      viewportEvents.dispatchEvent(new Event("resize"));
      await Promise.resolve();
    });

    expect(dialog?.style.maxHeight).toContain("220px");
    expect(dialog?.style.top).toContain("safe-area-inset-top");
  });

  it("creates immediately when a candidate has one route", async () => {
    const onConfirm = vi.fn();
    await renderDiscovery({ onConfirm });

    const replace = [...document.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Replace text"),
    );
    expect(replace).toBeTruthy();
    await React.act(async () => replace?.click());

    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onConfirm.mock.calls[0]?.[0].spec.operator_id).toBe("text.replace");
  });

  it("offers generation even when no installed node is compatible", async () => {
    const registryValue = registry();
    const emptySession = {
      ...sessionFor(registryValue),
      candidates: [],
    };
    await renderDiscovery({
      session: emptySession,
      onGenerate: vi.fn(async () => undefined),
    });

    expect(document.body.textContent).toContain("Generate a new node");
    expect(document.body.textContent).toContain("No compatible nodes match");
  });

  it("keeps generation available while catalog search has no matches", async () => {
    await renderDiscovery({ onGenerate: vi.fn(async () => undefined) });
    const search = document.querySelector<HTMLInputElement>(
      '[aria-label="Search compatible nodes"]',
    );
    expect(search).toBeTruthy();
    await React.act(async () => {
      if (!search) return;
      enterControlValue(search, "nothing-installed-here");
    });

    expect(document.body.textContent).toContain("Generate a new node");
    expect(document.body.textContent).not.toContain("Replace text description");
  });

  it("creates a durable draft in the selected environment", async () => {
    const onGenerate = vi.fn(
      async (request: ContextualGenerationRequest, signal: AbortSignal) => {
        void request;
        void signal;
      },
    );
    await renderDiscovery({
      onGenerate,
      environments: [
        { id: "env-python", name: "Python lab", profile: "Python 3.12" },
      ],
    });
    const generate = [...document.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Generate a new node"),
    );
    await React.act(async () => generate?.click());

    const textarea = document.querySelector<HTMLTextAreaElement>(
      '[aria-label="Describe what this node should do"]',
    );
    const environment = document.querySelector<HTMLSelectElement>(
      '[aria-label="Agent environment"]',
    );
    expect(document.body.textContent).toContain("scalar.text → Generated node");
    await React.act(async () => {
      if (!textarea || !environment) return;
      enterControlValue(textarea, "Append the API category to every value");
      enterControlValue(environment, "env-python");
    });
    const submit = [...document.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Create draft"),
    );
    await React.act(async () => submit?.click());

    expect(onGenerate).toHaveBeenCalledOnce();
    expect(onGenerate.mock.calls[0]?.[0]).toEqual({
      prompt: "Append the API category to every value",
      threadId: null,
      environmentId: "env-python",
      createEnvironment: false,
    });
    expect(onGenerate.mock.calls[0]?.[1]).toBeInstanceOf(AbortSignal);
  });

  it("inherits the active thread environment instead of asking again", async () => {
    const onGenerate = vi.fn(
      async (request: ContextualGenerationRequest, signal: AbortSignal) => {
        void request;
        void signal;
      },
    );
    await renderDiscovery({
      onGenerate,
      activeThread: {
        id: "thread-1",
        environmentId: "env-shared",
        environmentName: "Shared agent lab",
      },
    });
    const generate = [...document.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Generate a new node"),
    );
    await React.act(async () => generate?.click());
    expect(document.querySelector('[aria-label="Agent environment"]')).toBeNull();
    expect(document.body.textContent).toContain("Shared agent lab · current thread");

    const textarea = document.querySelector<HTMLTextAreaElement>("textarea");
    await React.act(async () => {
      if (!textarea) return;
      enterControlValue(textarea, "Build another node in this thread");
    });
    const submit = [...document.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Create draft"),
    );
    await React.act(async () => submit?.click());

    expect(onGenerate.mock.calls[0]?.[0]).toMatchObject({
      threadId: "thread-1",
      environmentId: "env-shared",
      createEnvironment: false,
    });
  });

  it("requires an intentional choice to start a new thread in the same environment", async () => {
    const onGenerate = vi.fn(
      async (request: ContextualGenerationRequest, signal: AbortSignal) => {
        void request;
        void signal;
      },
    );
    await renderDiscovery({
      onGenerate,
      activeThread: {
        id: "thread-1",
        environmentId: "env-shared",
        environmentName: "Shared agent lab",
      },
    });
    const generate = [...document.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Generate a new node"),
    );
    await React.act(async () => generate?.click());
    const thread = document.querySelector<HTMLSelectElement>(
      '[aria-label="Agent thread"]',
    );
    const textarea = document.querySelector<HTMLTextAreaElement>("textarea");
    await React.act(async () => {
      if (!thread || !textarea) return;
      enterControlValue(thread, "new");
      enterControlValue(textarea, "Start clean for this node");
    });
    const submit = [...document.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Create draft"),
    );
    await React.act(async () => submit?.click());

    expect(document.body.textContent).toContain("Shared agent lab · new thread");
    expect(onGenerate.mock.calls[0]?.[0]).toEqual({
      prompt: "Start clean for this node",
      threadId: null,
      environmentId: "env-shared",
      createEnvironment: false,
    });
  });

  it("retains the prompt and exposes a retryable generation error", async () => {
    const onGenerate = vi.fn(async (
      request: ContextualGenerationRequest,
      signal: AbortSignal,
    ) => {
      void request;
      void signal;
      throw new Error("Environment capacity is temporarily exhausted");
    });
    await renderDiscovery({ onGenerate });
    const generate = [...document.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Generate a new node"),
    );
    await React.act(async () => generate?.click());
    const textarea = document.querySelector<HTMLTextAreaElement>("textarea");
    await React.act(async () => {
      if (!textarea) return;
      enterControlValue(textarea, "Try this again");
    });
    const submit = [...document.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Create draft"),
    );
    await React.act(async () => submit?.click());

    expect(document.querySelector('[role="alert"]')?.textContent).toContain(
      "Environment capacity is temporarily exhausted",
    );
    expect(textarea?.value).toBe("Try this again");
    expect(submit?.hasAttribute("disabled")).toBe(false);
  });

  it("requires a second step when multiple routes exist", async () => {
    const onConfirm = vi.fn();
    await renderDiscovery({ onConfirm });

    const annotate = [...document.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Annotate text"),
    );
    await React.act(async () => annotate?.click());
    expect(onConfirm).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain("Connect Annotate text");

    const bodyRoute = [...document.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Body"),
    );
    await React.act(async () => bodyRoute?.click());
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onConfirm.mock.calls[0]?.[1].candidatePort.name).toBe("body");
  });

  it("lists purpose copy and previews the first node on the canvas", async () => {
    await renderDiscovery();

    expect(document.body.textContent).toContain("Replace text description");
    expect(document.body.textContent).toContain("Annotate text description");
    expect(document.body.textContent).not.toContain("Built-in ·");
    const preview = document.querySelector('[data-testid="canvas-preview"] article');
    expect(preview).toBeTruthy();
    expect(preview?.getAttribute("aria-label")).toMatch(/text/i);
  });

  it("moves the canvas preview when another candidate is hovered", async () => {
    await renderDiscovery();

    const annotate = [...document.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Annotate text"),
    );
    await React.act(async () => {
      annotate?.dispatchEvent(
        new MouseEvent("mouseenter", { bubbles: true }),
      );
    });

    const preview = document.querySelector('[data-testid="canvas-preview"]');
    expect(preview?.textContent).toContain("Annotate text");
  });

  it("closes on Escape without confirming", async () => {
    const onClose = vi.fn();
    await renderDiscovery({ onClose });
    await React.act(async () => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("upstream drag offers nodes whose outputs feed the input", async () => {
    const onConfirm = vi.fn();
    const registryValue = registry();
    await renderDiscovery({
      session: upstreamSessionFor(registryValue),
      onConfirm,
    });

    expect(document.body.textContent).toContain("Continue from Text");
    expect(document.body.textContent).toContain("Replace text");
    expect(document.body.textContent).toContain("Annotate text");

    const replace = [...document.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Replace text"),
    );
    await React.act(async () => replace?.click());

    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onConfirm.mock.calls[0]?.[0].spec.operator_id).toBe("text.replace");
    expect(onConfirm.mock.calls[0]?.[1].candidatePort.direction).toBe("output");
  });
});

// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ModuleLibraryEntry, Workspace } from "@/lib/api";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mocks = vi.hoisted(() => ({
  listWorkspaceModules: vi.fn(),
  routerPush: vi.fn(),
  artifactTypes: [] as {
    key: { id: string; schema_version: number };
    title: string;
  }[],
}));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.routerPush }),
}));

vi.mock("@/lib/api", () => ({
  listWorkspaceModules: mocks.listWorkspaceModules,
}));

vi.mock("@/hooks/use-api", () => ({
  useNodeRegistry: () => ({ data: { artifact_types: mocks.artifactTypes } }),
}));

import {
  filterWorkspaceModules,
  WorkspaceModuleLibrary,
} from "./WorkspaceLibraryDialog";

const roots = new Map<Root, HTMLElement>();

function workspace(overrides: Partial<Workspace> = {}): Workspace {
  return {
    id: "workspace-1",
    name: "Operations",
    slug: "operations",
    kind: "shared",
    role: "owner",
    capabilities: ["view_graph", "create_graph", "publish_module"],
    ...overrides,
  };
}

function moduleEntry(
  overrides: Partial<ModuleLibraryEntry> = {},
): ModuleLibraryEntry {
  return {
    id: "module-1",
    workspace_id: "workspace-1",
    source_graph_id: "graph-1",
    name: "Invoice normalizer",
    description: "Normalize invoice rows.",
    publication_state: "published",
    current_library_release: 4,
    created_at: "2026-08-01T10:00:00Z",
    updated_at: "2026-08-04T10:00:00Z",
    releases: [
      {
        revision: 3,
        source_graph_id: "graph-1",
        published_at: "2026-08-03T10:00:00Z",
        is_current_library_release: false,
      },
      {
        revision: 4,
        source_graph_id: "graph-1",
        published_at: "2026-08-04T10:00:00Z",
        is_current_library_release: true,
      },
    ],
    inputs: [
      {
        name: "invoice",
        direction: "input",
        artifact_type: { id: "table.data", schema_version: 1 },
        required: true,
        description: "Invoice rows",
      },
    ],
    outputs: [
      {
        name: "normalized",
        direction: "output",
        artifact_type: { id: "table.data", schema_version: 1 },
        required: true,
        description: null,
      },
    ],
    ...overrides,
  };
}

async function renderLibrary(activeWorkspace: Workspace = workspace()) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.set(root, container);
  await React.act(async () => {
    root.render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <WorkspaceModuleLibrary workspace={activeWorkspace} />
      </SWRConfig>,
    );
  });
  return container;
}

function buttonNamed(container: HTMLElement, name: string): HTMLButtonElement {
  const button = [...container.querySelectorAll("button")].find(
    (candidate) => candidate.textContent?.trim() === name,
  );
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`Button ${name} was not rendered`);
  }
  return button;
}

function enterInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

afterEach(async () => {
  for (const [root, container] of roots) {
    await React.act(async () => root.unmount());
    container.remove();
  }
  roots.clear();
  vi.clearAllMocks();
  mocks.artifactTypes = [];
});

beforeEach(() => {
  mocks.listWorkspaceModules.mockResolvedValue({ modules: [] });
});

describe("filterWorkspaceModules", () => {
  it("searches names, contract ports, artifact types, releases, and source ids", () => {
    const invoice = moduleEntry();
    const geocoder = moduleEntry({
      id: "module-2",
      source_graph_id: "graph-geo",
      name: "Address geocoder",
      description: null,
      current_library_release: 8,
      inputs: [],
      outputs: [],
    });

    expect(filterWorkspaceModules([invoice, geocoder], "normalized")).toEqual([
      invoice,
    ]);
    expect(filterWorkspaceModules([invoice, geocoder], "graph-geo")).toEqual([
      geocoder,
    ]);
  });
});

describe("WorkspaceModuleLibrary", () => {
  it("keeps load failures recoverable in the library surface", async () => {
    mocks.listWorkspaceModules.mockRejectedValueOnce(new Error("offline"));
    const container = await renderLibrary();

    await vi.waitFor(() => {
      expect(container.textContent).toContain("Couldn’t load Modules");
    });
    await React.act(async () =>
      buttonNamed(container, "Retry loading Modules").click(),
    );
    await vi.waitFor(() => {
      expect(container.textContent).toContain("No published Modules yet");
    });
  });

  it("provides useful empty library guidance and the publishing permission blocker", async () => {
    const container = await renderLibrary(
      workspace({ role: "viewer", capabilities: ["view_graph"] }),
    );

    await vi.waitFor(() => {
      expect(container.textContent).toContain("No published Modules yet");
    });
    expect(container.textContent).toContain(
      "Add and connect at least one Module Output boundary",
    );
    expect(container.textContent).toContain(
      "Publishing requires Editor or Owner access",
    );
  });

  it("renders the current release, contract, and source graph, and filters without a dead end", async () => {
    mocks.artifactTypes = [
      { key: { id: "table.data", schema_version: 1 }, title: "Table data" },
    ];
    mocks.listWorkspaceModules.mockResolvedValue({ modules: [moduleEntry()] });
    const container = await renderLibrary();

    await vi.waitFor(() => {
      expect(container.textContent).toContain("Invoice normalizer");
    });
    expect(container.textContent).toContain("Current release 4");
    expect(container.textContent).toContain("2 immutable releases");
    expect(container.textContent).toContain("invoice · Table data · required");
    expect(container.textContent).toContain("normalized · Table data");
    // The contract names the type; the identity it carries stays on hover.
    expect(container.querySelectorAll('[title="table.data@1"]').length).toBe(2);
    expect(container.textContent).toContain("Source graph graph-1");
    // Nothing advertises a lifecycle action: a published release is the only state.
    expect(container.textContent).not.toContain("published");
    expect(container.textContent).not.toContain("Deprecate");
    expect(container.textContent).not.toContain("Withdraw");
    expect(container.textContent).not.toContain("Import");

    const search = container.querySelector('[aria-label="Search Modules"]');
    expect(search).toBeInstanceOf(HTMLInputElement);
    React.act(() => enterInputValue(search as HTMLInputElement, "geocoder"));
    expect(container.textContent).toContain("No Modules match “geocoder”");
    React.act(() => buttonNamed(container, "Clear search").click());
    expect(container.textContent).toContain("Invoice normalizer");
  });

  it("opens the source graph behind a Module", async () => {
    mocks.listWorkspaceModules.mockResolvedValue({ modules: [moduleEntry()] });
    const container = await renderLibrary();

    await vi.waitFor(() => {
      expect(container.textContent).toContain("Invoice normalizer");
    });
    await React.act(async () =>
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("Open source graph"))
        ?.click(),
    );

    expect(mocks.routerPush).toHaveBeenCalledWith(
      "/workspaces/operations/graphs/graph-1",
    );
  });
});

// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ModuleLibraryEntry } from "@/lib/api";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mocks = vi.hoisted(() => ({
  listWorkspaceModules: vi.fn(),
  publishModuleRelease: vi.fn(),
}));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("@/lib/api", () => ({
  listWorkspaceModules: mocks.listWorkspaceModules,
  publishModuleRelease: mocks.publishModuleRelease,
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

import {
  moduleSetupReadiness,
  PublishModuleDialog,
  type ModuleBoundarySummary,
} from "./PublishModuleDialog";

const roots = new Map<Root, HTMLElement>();

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
    current_library_release: 2,
    created_at: "2026-08-01T10:00:00Z",
    updated_at: "2026-08-02T10:00:00Z",
    releases: [
      {
        revision: 2,
        source_graph_id: "graph-1",
        published_at: "2026-08-02T10:00:00Z",
        is_current_library_release: true,
      },
    ],
    inputs: [],
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

const outputBoundary: ModuleBoundarySummary = {
  id: "module-output",
  direction: "output",
  portName: "normalized",
  description: null,
  artifactType: "table.data@1",
  connectionCount: 1,
};

async function renderSetup(
  overrides: Partial<React.ComponentProps<typeof PublishModuleDialog>> = {},
) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.set(root, container);
  const props: React.ComponentProps<typeof PublishModuleDialog> = {
    open: true,
    onOpenChange: vi.fn(),
    workspaceId: "workspace-1",
    sourceGraphId: "graph-1",
    graphName: "Invoice normalizer",
    revision: 3,
    isDirty: false,
    canPublish: true,
    canEdit: true,
    boundaries: [outputBoundary],
    canAddInputBoundary: true,
    canAddOutputBoundary: true,
    ...overrides,
  };
  await React.act(async () => {
    root.render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <PublishModuleDialog {...props} />
      </SWRConfig>,
    );
  });
  return { container, props };
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

afterEach(async () => {
  for (const [root, container] of roots) {
    await React.act(async () => root.unmount());
    container.remove();
  }
  roots.clear();
  vi.clearAllMocks();
});

beforeEach(() => {
  mocks.listWorkspaceModules.mockResolvedValue({ modules: [] });
});

describe("moduleSetupReadiness", () => {
  it("reports exact authoring blockers without claiming browser-side contract validation", () => {
    const checks = moduleSetupReadiness({
      graphSaved: false,
      revisionCurrent: false,
      canPublish: false,
      outputBoundaryCount: 0,
      contractValidation: "unchecked",
      publishedRelease: null,
    });

    expect(checks.map((check) => [check.id, check.status])).toEqual([
      ["saved", "blocked"],
      ["revision", "blocked"],
      ["permission", "blocked"],
      ["interface", "blocked"],
      ["validation", "pending"],
      ["publication", "blocked"],
    ]);
    expect(checks.find((check) => check.id === "validation")?.detail).toContain(
      "server validates",
    );
  });

  it("marks a saved, current, authorized graph ready for server validation and publish", () => {
    const checks = moduleSetupReadiness({
      graphSaved: true,
      revisionCurrent: true,
      canPublish: true,
      outputBoundaryCount: 1,
      contractValidation: "unchecked",
      publishedRelease: null,
    });

    expect(checks.find((check) => check.id === "saved")?.status).toBe(
      "complete",
    );
    expect(checks.find((check) => check.id === "revision")?.status).toBe(
      "complete",
    );
    expect(checks.find((check) => check.id === "permission")?.status).toBe(
      "complete",
    );
    expect(checks.find((check) => check.id === "interface")?.status).toBe(
      "complete",
    );
    expect(checks.find((check) => check.id === "validation")?.status).toBe(
      "pending",
    );
    expect(checks.find((check) => check.id === "publication")?.detail).toBe(
      "Ready for server validation and publication.",
    );
  });
});

describe("PublishModuleDialog", () => {
  it("keeps Module setup discoverable while publishing is blocked", async () => {
    const { container } = await renderSetup({
      sourceGraphId: null,
      revision: null,
      isDirty: true,
      canPublish: false,
      boundaries: [],
    });

    expect(container.textContent).toContain(
      "Save this graph before it can become a Module.",
    );
    expect(container.textContent).toContain(
      "Publishing requires Editor or Owner access here",
    );
    expect(container.textContent).toContain(
      "Add and connect at least one Module Output boundary",
    );
    expect(buttonNamed(container, "Publish release").disabled).toBe(true);
  });

  it("adds and opens boundary nodes through the owned canvas callbacks", async () => {
    const onAddBoundary = vi.fn();
    const onSelectBoundary = vi.fn();
    const onOpenChange = vi.fn();
    const { container } = await renderSetup({
      onAddBoundary,
      onSelectBoundary,
      onOpenChange,
    });

    buttonNamed(container, "Add input").click();
    buttonNamed(container, "Edit on canvas").click();

    expect(onAddBoundary).toHaveBeenCalledWith("input");
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSelectBoundary).toHaveBeenCalledWith("module-output");
  });

  it("shows authoritative validation failures and keeps the revision unpublished", async () => {
    mocks.publishModuleRelease.mockRejectedValue(
      new Error("Module Output boundary requires exactly one incoming edge."),
    );
    const { container } = await renderSetup();

    await React.act(async () =>
      buttonNamed(container, "Publish release").click(),
    );

    await vi.waitFor(() => {
      expect(container.querySelector('[role="alert"]')?.textContent).toContain(
        "requires exactly one incoming edge",
      );
    });
    const validationRow = [...container.querySelectorAll("[data-status]")].find(
      (candidate) => candidate.textContent?.includes("Contract validation"),
    );
    expect(validationRow?.getAttribute("data-status")).toBe("blocked");
    expect(container.textContent).not.toContain("Published release 3");
  });

  it("publishes the first release with details and replaces window alerts with inline success", async () => {
    const published = moduleEntry({
      current_library_release: 3,
      releases: [
        {
          revision: 3,
          source_graph_id: "graph-1",
          published_at: "2026-08-03T10:00:00Z",
          is_current_library_release: true,
        },
      ],
    });
    mocks.publishModuleRelease.mockResolvedValue(published);
    const alertSpy = vi
      .spyOn(window, "alert")
      .mockImplementation(() => undefined);
    const onPublished = vi.fn();
    const onViewModule = vi.fn();
    const onOpenSourceGraph = vi.fn();
    const { container } = await renderSetup({
      onPublished,
      onViewModule,
      onOpenSourceGraph,
    });

    await React.act(async () =>
      buttonNamed(container, "Publish release").click(),
    );

    await vi.waitFor(() => {
      expect(container.textContent).toContain("Published release 3");
    });
    expect(mocks.publishModuleRelease).toHaveBeenCalledWith("workspace-1", {
      source_graph_id: "graph-1",
      revision: 3,
      name: "Invoice normalizer",
      description: null,
    });
    expect(onPublished).toHaveBeenCalledWith(published);
    expect(alertSpy).not.toHaveBeenCalled();

    buttonNamed(container, "View module").click();
    buttonNamed(container, "Open source").click();
    expect(onViewModule).toHaveBeenCalledWith("module-1");
    expect(onOpenSourceGraph).toHaveBeenCalledWith("graph-1");
  });

  it("publishes a later immutable release without silently renaming the Module", async () => {
    const existing = moduleEntry();
    const published = moduleEntry({
      current_library_release: 3,
      releases: [
        ...(existing.releases ?? []).map((release) => ({
          ...release,
          is_current_library_release: false,
        })),
        {
          revision: 3,
          source_graph_id: "graph-1",
          published_at: "2026-08-03T10:00:00Z",
          is_current_library_release: true,
        },
      ],
    });
    mocks.listWorkspaceModules.mockResolvedValue({ modules: [existing] });
    mocks.publishModuleRelease.mockResolvedValue(published);
    const { container } = await renderSetup();

    await vi.waitFor(() => {
      expect(container.textContent).toContain(
        "Existing callers stay pinned to release 2",
      );
    });
    expect(container.querySelector("input")).toBeNull();

    await React.act(async () =>
      buttonNamed(container, "Publish release").click(),
    );

    expect(mocks.publishModuleRelease).toHaveBeenCalledWith("workspace-1", {
      source_graph_id: "graph-1",
      revision: 3,
    });
    await vi.waitFor(() => {
      expect(container.textContent).toContain("Published release 3");
      expect(container.textContent).toContain(
        "Existing pinned calls were not changed.",
      );
    });
  });
});

// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkbenchSidePanel } from "./WorkbenchSidePanel";
import type { WorkbenchSidePanelState } from "./workbench-side-panel-state";

const listLibraryArtifacts = vi.hoisted(() => vi.fn());
const listWorkspaceTemplates = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({
  getGraphExecution: vi.fn(),
  listGraphExecutions: vi.fn(),
  listLibraryArtifacts,
  listWorkspaceTemplates,
  saveRunArtifactToLibrary: vi.fn(),
  uploadFile: vi.fn(),
  saveUploadedArtifactToLibrary: vi.fn(),
  instantiateWorkspaceTemplate: vi.fn(),
  artifactContentUrl: (
    _workspaceId: string,
    contentUrl: string | null | undefined,
  ) => (contentUrl ? `/api/v1/${contentUrl}` : null),
}));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
  when: { ancestor: () => "" },
}));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const roots: ReturnType<typeof createRoot>[] = [];

function state(
  overrides: Partial<WorkbenchSidePanelState> = {},
): WorkbenchSidePanelState {
  return {
    docked: true,
    open: true,
    width: 276,
    view: "artifacts",
    setOpen: vi.fn(),
    toggle: vi.fn(),
    setWidth: vi.fn(),
    setView: vi.fn(),
    ...overrides,
  };
}

async function renderPanel(sidePanel: WorkbenchSidePanelState): Promise<void> {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  await React.act(async () => {
    root.render(
      <WorkbenchSidePanel
        workspaceId="workspace-1"
        sidePanel={sidePanel}
        graphId={null}
        nodeTitles={{}}
        registry={null}
        canSave={false}
        executionRunning={false}
        onOpenRun={vi.fn()}
        onOpenGraph={vi.fn()}
      />,
    );
  });
  if (!sidePanel.open) return;
  await React.act(async () => {
    await vi.waitFor(() =>
      expect(
        document.querySelector('[role="tabpanel"], [role="dialog"]'),
      ).not.toBeNull(),
    );
  });
}

function panel(): HTMLElement | null {
  return document.querySelector<HTMLElement>(
    '[aria-label="Workbench side panel"]',
  );
}

function tab(id: string): HTMLElement | null {
  return document.getElementById(`grafy-side-panel-tab-${id}`);
}

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  document.body.replaceChildren();
  vi.unstubAllGlobals();
  listLibraryArtifacts.mockReset();
  listWorkspaceTemplates.mockReset();
});

beforeEach(() => {
  listLibraryArtifacts.mockResolvedValue({ items: [] });
  listWorkspaceTemplates.mockResolvedValue({ templates: [] });
});

describe("WorkbenchSidePanel", () => {
  it("renders nothing while closed", async () => {
    await renderPanel(state({ open: false }));

    expect(panel()).toBeNull();
  });

  it("docks beside the canvas with one tab per work surface", async () => {
    await renderPanel(state());

    expect(panel()).not.toBeNull();
    expect(tab("artifacts")?.getAttribute("aria-selected")).toBe("true");
    expect(tab("templates")?.getAttribute("aria-selected")).toBe("false");
    expect(document.body.textContent).toContain("The Library is empty");
    expect(
      document.querySelector('[role="tree"][aria-label="Workspace Library"]'),
    ).not.toBeNull();
  });

  it("shows the selected view in the tab panel", async () => {
    await renderPanel(state({ view: "templates" }));

    expect(tab("templates")?.getAttribute("aria-selected")).toBe("true");
    expect(document.body.textContent).toContain("No graph templates");
    expect(
      document
        .getElementById("grafy-side-panel-view")
        ?.getAttribute("aria-labelledby"),
    ).toBe("grafy-side-panel-tab-templates");
  });

  it("shows Generated inside the existing side panel", async () => {
    await renderPanel(state({ view: "generated" }));

    expect(panel()).not.toBeNull();
    expect(tab("generated")?.getAttribute("aria-selected")).toBe("true");
    expect(document.body.textContent).toContain("Run artifacts");
    expect(
      document.querySelector('[aria-label="Generated artifacts"]'),
    ).not.toBeNull();
  });

  it("switches views from the tab strip and with the arrow keys", async () => {
    const sidePanel = state();
    await renderPanel(sidePanel);

    await React.act(async () => {
      tab("templates")?.click();
    });
    expect(sidePanel.setView).toHaveBeenCalledWith("templates");

    await React.act(async () => {
      tab("artifacts")?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }),
      );
    });
    expect(sidePanel.setView).toHaveBeenLastCalledWith("templates");
  });

  it("hosts Generated in the same slide-over on narrow screens", async () => {
    await renderPanel(state({ docked: false, view: "generated" }));

    expect(panel()).toBeNull();
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    expect(tab("generated")?.getAttribute("aria-selected")).toBe("true");
    expect(document.body.textContent).toContain("Run artifacts");
  });

  it("collapses the panel from its header", async () => {
    const sidePanel = state();
    await renderPanel(sidePanel);

    await React.act(async () => {
      panel()
        ?.querySelector<HTMLButtonElement>(
          'button[aria-label="Collapse side panel"]',
        )
        ?.click();
    });

    expect(sidePanel.setOpen).toHaveBeenCalledWith(false);
  });

  it("resizes by keyboard from the separator", async () => {
    const sidePanel = state();
    await renderPanel(sidePanel);
    const separator = panel()?.querySelector<HTMLElement>('[role="separator"]');

    await React.act(async () => {
      separator?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }),
      );
    });
    expect(sidePanel.setWidth).toHaveBeenLastCalledWith(292);

    await React.act(async () => {
      separator?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }),
      );
    });
    expect(sidePanel.setWidth).toHaveBeenLastCalledWith(260);
  });

  it("slides over the canvas when the viewport cannot dock it", async () => {
    const sidePanel = state({ docked: false });
    await renderPanel(sidePanel);

    expect(panel()).toBeNull();
    expect(
      document.querySelector('[role="dialog"], [role="presentation"]'),
    ).not.toBeNull();
    expect(document.body.textContent).toContain("The Library is empty");
  });
});

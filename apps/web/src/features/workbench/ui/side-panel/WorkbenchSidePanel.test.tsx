// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkbenchSidePanel } from "./WorkbenchSidePanel";
import {
  SIDE_PANEL_MOTION_MS,
  type WorkbenchSidePanelState,
} from "./workbench-side-panel-state";

const listTree = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@/lib/api");
  return {
    ...actual,
    libraryFoldersApi: { listTree },
    uploadFile: vi.fn(),
    saveUploadedArtifactToLibrary: vi.fn(),
  };
});

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
  defaultMarker: () => ({}),
  when: { ancestor: (pseudo: string) => pseudo },
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
    setOpen: vi.fn(),
    toggle: vi.fn(),
    setWidth: vi.fn(),
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
        onOpenRun={vi.fn()}
      />,
    );
  });
  if (!sidePanel.open) return;
  await React.act(async () => {
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain("The Library is empty"),
    );
  });
}

function panel(): HTMLElement | null {
  return document.querySelector<HTMLElement>(
    'aside[aria-label="Workbench side panel"]',
  );
}

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  document.body.replaceChildren();
  vi.unstubAllGlobals();
  listTree.mockReset();
});

beforeEach(() => {
  listTree.mockResolvedValue({ folders: [], items: [] });
});

describe("WorkbenchSidePanel", () => {
  it("parks an empty, inert column while closed", async () => {
    await renderPanel(state({ open: false }));

    expect(panel()?.hasAttribute("inert")).toBe(true);
    expect(panel()?.dataset.state).toBe("closed");
    expect(panel()?.childElementCount).toBe(0);
  });

  it("keeps its contents through the closing slide, then lets them go", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      const sidePanel = state();
      const container = document.createElement("div");
      document.body.append(container);
      const root = createRoot(container);
      roots.push(root);
      const render = (open: boolean) =>
        root.render(
          <WorkbenchSidePanel
            workspaceId="workspace-1"
            sidePanel={{ ...sidePanel, open }}
            onOpenRun={vi.fn()}
          />,
        );
      await React.act(async () => render(true));
      await React.act(async () => render(false));

      expect(panel()?.dataset.state).toBe("closed");
      expect(panel()?.hasAttribute("inert")).toBe(true);
      expect(panel()?.querySelector('[role="tree"]')).not.toBeNull();

      await React.act(async () => {
        vi.advanceTimersByTime(SIDE_PANEL_MOTION_MS);
      });
      expect(panel()?.querySelector('[role="tree"]')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("docks beside the canvas with the Workspace Library", async () => {
    await renderPanel(state());

    expect(panel()).not.toBeNull();
    expect(panel()?.querySelector("h2")?.textContent).toBe("Artifacts");
    expect(document.querySelector('[role="tablist"]')).toBeNull();
    expect(
      document.querySelector('[role="tree"][aria-label="Workspace Library"]'),
    ).not.toBeNull();
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

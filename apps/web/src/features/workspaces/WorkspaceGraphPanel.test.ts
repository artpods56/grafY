// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SavedGraphSummary } from "@/lib/api";
import {
  WorkspaceGraphPanel,
  filterGraphsByQuery,
  graphAgeLabel,
  graphCountLabel,
  sortGraphsByRecency,
} from "./WorkspaceGraphPanel";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const testState = vi.hoisted(() => ({
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: testState.push }),
}));

const panelState = vi.hoisted(() => ({
  graphs: [
    {
      id: "graph-invoice",
      name: "Invoice intake",
      node_count: 2,
      edge_count: 1,
      revision: 1,
      updated_at: "2026-08-10T12:00:00Z",
      draft_pending: false,
    },
  ],
  isValidating: false,
}));

vi.mock("@/hooks/use-api", () => ({
  useSavedGraphs: () => ({
    data: { graphs: panelState.graphs },
    isLoading: false,
    isValidating: panelState.isValidating,
  }),
}));

vi.mock("./GraphRowMenu", () => ({
  GraphRowMenu: () => null,
}));

const mountedRoots = new Set<Root>();

afterEach(async () => {
  for (const root of mountedRoots) {
    await act(async () => root.unmount());
  }
  mountedRoots.clear();
  document.body.replaceChildren();
  vi.unstubAllGlobals();
  testState.push.mockReset();
  panelState.graphs = [
    {
      id: "graph-invoice",
      name: "Invoice intake",
      node_count: 2,
      edge_count: 1,
      revision: 1,
      updated_at: "2026-08-10T12:00:00Z",
      draft_pending: false,
    },
  ];
  panelState.isValidating = false;
});

const graph = (
  name: string,
  updatedAt: string,
  overrides: Partial<SavedGraphSummary> = {},
): SavedGraphSummary => ({
  id: `graph-${name}`,
  name,
  node_count: 2,
  edge_count: 1,
  revision: 1,
  updated_at: updatedAt,
  draft_pending: false,
  ...overrides,
});

describe("workspace graph panel listing", () => {
  it("orders graphs by most recently updated", () => {
    const ordered = sortGraphsByRecency([
      graph("Older", "2026-08-01T10:00:00Z"),
      graph("Newest", "2026-08-09T10:00:00Z"),
      graph("Middle", "2026-08-05T10:00:00Z"),
    ]);

    expect(ordered.map((entry) => entry.name)).toEqual([
      "Newest",
      "Middle",
      "Older",
    ]);
  });

  it("matches graph names case-insensitively and keeps every graph for a blank query", () => {
    const graphs = [
      graph("Invoice intake", "2026-08-01T10:00:00Z"),
      graph("Payroll", "2026-08-02T10:00:00Z"),
    ];

    expect(filterGraphsByQuery(graphs, "invoice").map((e) => e.name)).toEqual([
      "Invoice intake",
    ]);
    expect(filterGraphsByQuery(graphs, "   ")).toHaveLength(2);
    expect(filterGraphsByQuery(graphs, "nothing")).toHaveLength(0);
  });

  it("summarises graph age in coarse buckets", () => {
    const now = Date.parse("2026-08-10T12:00:00Z");
    expect(graphAgeLabel("2026-08-10T11:59:30Z", now)).toBe("just now");
    expect(graphAgeLabel("2026-08-10T11:15:00Z", now)).toBe("45m ago");
    expect(graphAgeLabel("2026-08-10T09:00:00Z", now)).toBe("3h ago");
    expect(graphAgeLabel("2026-08-06T12:00:00Z", now)).toBe("4d ago");
  });

  it("labels every graph summary with the same node and edge wording", () => {
    expect(graphCountLabel({ node_count: 1, edge_count: 0 })).toBe(
      "1 node · 0 edges",
    );
    expect(graphCountLabel({ node_count: 2, edge_count: 1 })).toBe(
      "2 nodes · 1 edge",
    );
  });

  it("labels a draft head that is ahead of the saved checkpoint", () => {
    expect(
      graphCountLabel({ node_count: 0, edge_count: 0, draft_pending: true }),
    ).toBe("0 nodes · 0 edges · unsaved draft");
  });
});

describe("workspace graph panel interactions", () => {
  async function renderPanel(onClose = vi.fn()) {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    mountedRoots.add(root);
    await act(async () => {
      root.render(
        React.createElement(WorkspaceGraphPanel, {
          workspaceId: "workspace-1",
          workspaceSlug: "operations",
          activeGraphId: null,
          onRename: vi.fn(),
          onDelete: vi.fn(),
          onClose,
        }),
      );
    });
    return { container, onClose };
  }

  it.each([
    {
      name: "keyboard dismissal",
      dismiss: () =>
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })),
      reason: "escape",
    },
    {
      name: "outside pointer dismissal",
      dismiss: () =>
        document.body.dispatchEvent(new Event("pointerdown", { bubbles: true })),
      reason: "outside-pointer",
    },
  ] as const)("reports $name", async ({ dismiss, reason }) => {
    const { onClose } = await renderPanel();

    dismiss();

    expect(onClose).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledWith(reason);
  });

  it("ignores pointer events owned by its trigger and the account menu", async () => {
    const trigger = document.createElement("button");
    trigger.dataset.graphPanelTrigger = "";
    document.body.append(trigger);
    const accountMenu = document.createElement("div");
    accountMenu.className = "grafy-workspace-rail__account-menu";
    document.body.append(accountMenu);
    const { onClose } = await renderPanel();

    trigger.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    accountMenu.dispatchEvent(new Event("pointerdown", { bubbles: true }));

    expect(onClose).not.toHaveBeenCalled();
  });

  it("shows a refreshing indicator instead of a confidently stale count", async () => {
    panelState.isValidating = true;
    const { container } = await renderPanel();

    const status = container.querySelector("[role='status']");

    expect(status?.textContent).toBe("Refreshing…");
  });

  it("labels a graph whose live draft is ahead of its saved checkpoint", async () => {
    panelState.graphs = [
      {
        id: "graph-draft",
        name: "Draft ahead",
        node_count: 0,
        edge_count: 0,
        revision: 1,
        updated_at: "2026-08-10T12:00:00Z",
        draft_pending: true,
      },
    ];
    const { container } = await renderPanel();

    expect(
      container.querySelector(".grafy-graph-panel__row-meta")?.textContent,
    ).toContain("0 nodes · 0 edges · unsaved draft");
  });

  it("reports an explicit close", async () => {
    const { container, onClose } = await renderPanel();
    const close = container.querySelector<HTMLButtonElement>(
      "[aria-label='Close quick graph switcher']",
    );

    await act(async () => close?.click());

    expect(onClose).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledWith("close-button");
  });

  it("navigates before reporting graph selection", async () => {
    const { container, onClose } = await renderPanel();
    const graph = container.querySelector<HTMLButtonElement>(
      ".grafy-graph-panel__row-open",
    );

    await act(async () => graph?.click());

    expect(onClose).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledWith("graph-selected");
    expect(testState.push).toHaveBeenCalledWith(
      "/workspaces/operations/graphs/graph-invoice",
    );
  });

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
      const { container } = await renderPanel();
      const search = container.querySelector<HTMLInputElement>(
        '[aria-label="Search graphs"]',
      );

      expect(document.activeElement === search).toBe(shouldFocus);
    },
  );

  it("does not steal focus when pointer capability changes after opening", async () => {
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
    const { container } = await renderPanel();
    const graphButton = container.querySelector<HTMLButtonElement>(
      ".grafy-graph-panel__row-open",
    );
    graphButton?.focus();

    matches = true;
    await act(async () => {
      for (const listener of listeners) listener(new Event("change"));
    });

    expect(document.activeElement).toBe(graphButton);
  });
});

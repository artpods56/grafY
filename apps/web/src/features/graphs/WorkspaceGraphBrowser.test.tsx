// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SavedGraphSummary, Workspace } from "@/lib/api";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const browserState = vi.hoisted(() => ({
  push: vi.fn(),
  mutate: vi.fn(async () => undefined),
  data: { graphs: [] as SavedGraphSummary[] } as
    | { graphs: SavedGraphSummary[] }
    | undefined,
  error: undefined as Error | undefined,
  isLoading: false,
  workspace: {
    id: "workspace-atlas",
    name: "Atlas",
    slug: "atlas",
    kind: "shared" as const,
    role: "editor" as const,
    capabilities: ["view_graph", "create_graph"],
  } satisfies Workspace,
}));

const apiMocks = vi.hoisted(() => ({
  useSavedGraphs: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: browserState.push }),
}));

vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.ComponentProps<"a">) => (
    <a {...props}>{children}</a>
  ),
}));

vi.mock("@/features/workspaces/WorkspaceLayout", () => ({
  useWorkspaceContext: () => ({ workspace: browserState.workspace }),
  workspaceDisplayName: (workspace: { name: string; kind: string }) =>
    workspace.kind === "personal" ? "My graphs" : workspace.name,
}));

vi.mock("@/hooks/use-api", () => ({
  useSavedGraphs: apiMocks.useSavedGraphs,
}));

import { WorkspaceGraphBrowser } from "./WorkspaceGraphBrowser";

const roots: Root[] = [];

function graph(
  id: string,
  name: string,
  updatedAt = "2026-08-10T10:00:00Z",
): SavedGraphSummary {
  return {
    id,
    name,
    node_count: 3,
    edge_count: 2,
    revision: 4,
    updated_at: updatedAt,
    draft_pending: false,
  };
}

async function renderBrowser() {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  await act(async () => root.render(<WorkspaceGraphBrowser />));
  return container;
}

function button(container: ParentNode, name: string): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.includes(name),
  );
  if (!match) throw new Error(`Button not found: ${name}`);
  return match;
}

async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

async function change(element: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(
      element,
      value,
    );
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

beforeEach(() => {
  browserState.push.mockReset();
  browserState.mutate.mockClear();
  browserState.data = { graphs: [] };
  browserState.error = undefined;
  browserState.isLoading = false;
  browserState.workspace = {
    id: "workspace-atlas",
    name: "Atlas",
    slug: "atlas",
    kind: "shared",
    role: "editor",
    capabilities: ["view_graph", "create_graph"],
  };
  apiMocks.useSavedGraphs.mockImplementation(() => ({
    data: browserState.data,
    error: browserState.error,
    isLoading: browserState.isLoading,
    mutate: browserState.mutate,
  }));
});

afterEach(async () => {
  for (const root of roots.splice(0)) {
    await act(async () => root.unmount());
  }
  document.body.replaceChildren();
});

describe("workspace graph browser", () => {
  it("loads and links only the active workspace's graphs", async () => {
    browserState.data = {
      graphs: Array.from({ length: 9 }, (_, index) =>
        graph(
          `graph-${index}`,
          `Graph ${index}`,
          `2026-08-${String(index + 1).padStart(2, "0")}T10:00:00Z`,
        ),
      ),
    };
    const container = await renderBrowser();

    expect(apiMocks.useSavedGraphs).toHaveBeenCalledWith("workspace-atlas");
    expect(container.textContent).toContain("Atlas");
    expect(container.querySelector('[aria-label="Filter by location"]')).toBeNull();
    expect(container.querySelectorAll(".grafy-graphs__row")).toHaveLength(8);

    await click(button(container, "All"));
    expect(container.querySelectorAll(".grafy-graphs__row")).toHaveLength(9);
    expect(
      container
        .querySelector<HTMLAnchorElement>('[aria-label="Open Graph 8 in Atlas"]')
        ?.getAttribute("href"),
    ).toBe("/workspaces/atlas/graphs/graph-8");
  });

  it("searches graph names and distinguishes no results from an empty workspace", async () => {
    browserState.data = {
      graphs: [graph("graph-1", "Invoice intake")],
    };
    const container = await renderBrowser();
    const search = container.querySelector<HTMLInputElement>(
      'input[aria-label="Search graphs"]',
    )!;

    await change(search, "missing");
    expect(container.textContent).toContain("No graphs match your search");
    expect(container.textContent).not.toContain("No graphs yet");
  });

  it("creates a graph directly in the active workspace", async () => {
    const container = await renderBrowser();

    await click(button(container, "New graph"));

    expect(browserState.push).toHaveBeenCalledWith(
      "/workspaces/atlas/graphs/new",
    );
    expect(container.textContent).not.toContain("Choose a location");
  });

  it("shows loading, failure with retry, and true empty states", async () => {
    browserState.data = undefined;
    browserState.isLoading = true;
    const loading = await renderBrowser();
    expect(loading.textContent).toContain("Loading graphs…");

    browserState.isLoading = false;
    browserState.error = new Error("offline");
    const failed = await renderBrowser();
    expect(failed.textContent).toContain("Graphs couldn't be loaded");
    await click(button(failed, "Retry"));
    expect(browserState.mutate).toHaveBeenCalledOnce();

    browserState.data = { graphs: [] };
    browserState.error = undefined;
    const empty = await renderBrowser();
    expect(empty.textContent).toContain("No graphs yet");
  });
});

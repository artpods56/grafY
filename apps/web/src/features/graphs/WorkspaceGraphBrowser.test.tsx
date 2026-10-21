// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SavedGraphSummary, Workspace } from "@/lib/api";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const browserState = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  mutate: vi.fn(async () => undefined),
  data: { graphs: [] as SavedGraphSummary[] } as
    { graphs: SavedGraphSummary[] } | undefined,
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
  /** The address the page is mounted on, as the browser would report it. */
  pathname: "/workspaces/atlas/graphs",
  search: "",
  /** False holds the address still, so a write that has not landed can be seen. */
  landWrites: true,
}));

const apiMocks = vi.hoisted(() => ({
  useSavedGraphs: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: browserState.push, replace: browserState.replace }),
  usePathname: () => browserState.pathname,
  useSearchParams: () => new URLSearchParams(browserState.search),
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
let activeRoot: Root | null = null;

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

const INTAKE_GRAPHS: SavedGraphSummary[] = [
  graph("graph-invoice", "Invoice intake", "2026-08-12T10:00:00Z"),
  graph("graph-archive", "Invoice archive audit", "2026-08-11T10:00:00Z"),
  graph("graph-sync", "Nightly sync", "2026-08-10T10:00:00Z"),
];

/** A write that reaches the address turns into a re-render, as it does live. */
function landWrite(href: unknown) {
  if (!browserState.landWrites || typeof href !== "string") return;
  const [, search = ""] = href.split("?");
  browserState.search = search;
}

function replaceCalls(): string[] {
  return browserState.replace.mock.calls.map(([href]) => String(href));
}

function lastWrite(): string {
  const calls = replaceCalls();
  if (calls.length === 0) throw new Error("No address write happened");
  return calls[calls.length - 1]!;
}

/** Move the address by hand: what reload, Back, and Forward do to this page. */
async function setUrl(search: string) {
  browserState.search = search.startsWith("?") ? search.slice(1) : search;
  await rerender();
}

async function rerender() {
  const root = activeRoot;
  if (!root) throw new Error("Nothing is mounted");
  await act(async () => {
    root.render(<WorkspaceGraphBrowser />);
  });
}

async function renderBrowser(search = "") {
  browserState.search = search.startsWith("?") ? search.slice(1) : search;
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  activeRoot = root;
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

function searchInput(container: ParentNode): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>(
    'input[aria-label="Search graphs"]',
  );
  if (!input) throw new Error("Search input not found");
  return input;
}

function rowTitles(container: ParentNode): string[] {
  return Array.from(container.querySelectorAll(".grafy-graphs__row-title")).map(
    (title) => title.textContent ?? "",
  );
}

function pressed(container: ParentNode, name: string): string | null {
  return button(container, name).getAttribute("aria-pressed");
}

async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    activeRoot?.render(<WorkspaceGraphBrowser />);
  });
}

async function change(element: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set?.call(element, value);
    element.dispatchEvent(new Event("change", { bubbles: true }));
    activeRoot?.render(<WorkspaceGraphBrowser />);
  });
}

beforeEach(() => {
  browserState.push.mockReset();
  browserState.replace.mockReset();
  browserState.replace.mockImplementation(landWrite);
  browserState.mutate.mockClear();
  browserState.data = { graphs: [] };
  browserState.error = undefined;
  browserState.isLoading = false;
  browserState.landWrites = true;
  browserState.pathname = "/workspaces/atlas/graphs";
  browserState.search = "";
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
  activeRoot = null;
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
    expect(
      container.querySelector('[aria-label="Filter by location"]'),
    ).toBeNull();
    expect(container.querySelectorAll(".grafy-graphs__row")).toHaveLength(8);

    await click(button(container, "All"));
    expect(container.querySelectorAll(".grafy-graphs__row")).toHaveLength(9);
    expect(
      container
        .querySelector<HTMLAnchorElement>(
          '[aria-label="Open Graph 8 in Atlas"]',
        )
        ?.getAttribute("href"),
    ).toBe("/workspaces/atlas/graphs/graph-8");
  });

  it("searches graph names and distinguishes no results from an empty workspace", async () => {
    browserState.data = {
      graphs: [graph("graph-1", "Invoice intake")],
    };
    const container = await renderBrowser();
    const search = searchInput(container);

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

describe("workspace graph browser address filters", () => {
  beforeEach(() => {
    browserState.data = { graphs: INTAKE_GRAPHS };
  });

  it("restores the filters, the controls, and the list from the address", async () => {
    const container = await renderBrowser("?q=invoice&view=all");

    expect(searchInput(container).value).toBe("invoice");
    expect(pressed(container, "All")).toBe("true");
    expect(pressed(container, "Recent")).toBe("false");
    expect(rowTitles(container)).toEqual([
      "Invoice intake",
      "Invoice archive audit",
    ]);
    expect(container.textContent).toContain("2 graphs");
  });

  it("limits a filtered list to Recent until the address asks for All", async () => {
    browserState.data = {
      graphs: Array.from({ length: 9 }, (_, index) =>
        graph(`graph-${index}`, `Invoice ${index}`),
      ),
    };
    const recent = await renderBrowser("?q=invoice");
    expect(rowTitles(recent)).toHaveLength(8);

    await setUrl("?q=invoice&view=all");
    expect(rowTitles(recent)).toHaveLength(9);
  });

  it("reads a filter it does not offer as the default", async () => {
    const container = await renderBrowser("?view=archive&q=");

    expect(searchInput(container).value).toBe("");
    expect(pressed(container, "Recent")).toBe("true");
    expect(rowTitles(container)).toEqual([
      "Invoice intake",
      "Invoice archive audit",
      "Nightly sync",
    ]);
    expect(browserState.replace).not.toHaveBeenCalled();
  });

  it("commits the search text to the address instead of holding it locally", async () => {
    const container = await renderBrowser();
    const input = searchInput(container);

    await change(input, "nightly");

    expect(lastWrite()).toBe("/workspaces/atlas/graphs?q=nightly");
    expect(input.value).toBe("nightly");
    expect(rowTitles(container)).toEqual(["Nightly sync"]);
  });

  it("omits defaults and keeps parameters this browser does not own", async () => {
    const container = await renderBrowser("?utm_source=email");
    const input = searchInput(container);

    await change(input, "invoice");
    expect(lastWrite()).toBe(
      "/workspaces/atlas/graphs?utm_source=email&q=invoice",
    );

    await change(input, "");
    expect(lastWrite()).toBe("/workspaces/atlas/graphs?utm_source=email");
    expect(rowTitles(container)).toHaveLength(3);
  });

  it("commits the view choice and takes it back out of the address", async () => {
    browserState.data = {
      graphs: Array.from({ length: 9 }, (_, index) =>
        graph(`graph-${index}`, `Graph ${index}`),
      ),
    };
    const container = await renderBrowser();

    await click(button(container, "All"));
    expect(lastWrite()).toBe("/workspaces/atlas/graphs?view=all");
    expect(pressed(container, "All")).toBe("true");

    await click(button(container, "Recent"));
    expect(lastWrite()).toBe("/workspaces/atlas/graphs");
    expect(pressed(container, "Recent")).toBe("true");
  });

  it("clears the address through the empty state's own action", async () => {
    const container = await renderBrowser("?q=missing");
    expect(container.textContent).toContain("No graphs match your search");

    await click(button(container, "Clear search"));

    expect(lastWrite()).toBe("/workspaces/atlas/graphs");
    expect(searchInput(container).value).toBe("");
    expect(rowTitles(container)).toHaveLength(3);
  });

  it("keeps a keystroke the address has not absorbed yet", async () => {
    browserState.landWrites = false;
    const container = await renderBrowser();
    const input = searchInput(container);

    await change(input, "in");
    expect(lastWrite()).toBe("/workspaces/atlas/graphs?q=in");
    await change(input, "inv");
    expect(lastWrite()).toBe("/workspaces/atlas/graphs?q=inv");

    // The first write is the one that finally reaches the address. The field
    // holds the second keystroke and the list describes the address, and
    // neither is dragged back to the word that was typed past.
    await setUrl("?q=in");
    expect(input.value).toBe("inv");
    expect(rowTitles(container)).toEqual([
      "Invoice intake",
      "Invoice archive audit",
    ]);
    expect(replaceCalls()).toEqual([
      "/workspaces/atlas/graphs?q=in",
      "/workspaces/atlas/graphs?q=inv",
    ]);

    await setUrl("?q=inv");
    expect(input.value).toBe("inv");
    expect(rowTitles(container)).toEqual([
      "Invoice intake",
      "Invoice archive audit",
    ]);
    expect(replaceCalls()).toHaveLength(2);
  });

  it("writes the field when a control changes the filter it holds", async () => {
    browserState.landWrites = false;
    const container = await renderBrowser();
    const input = searchInput(container);

    await change(input, "nightly");
    await click(button(container, "All"));

    // A view change carries the search this page asked for, not the one the
    // address has reached, and the field keeps what the person typed.
    expect(lastWrite()).toBe("/workspaces/atlas/graphs?q=nightly&view=all");
    expect(input.value).toBe("nightly");
  });

  it("gives the address the last word when history moves it", async () => {
    const container = await renderBrowser("?q=nightly");
    expect(searchInput(container).value).toBe("nightly");

    // Back, then Forward: neither is a write this page made.
    await setUrl("");
    expect(searchInput(container).value).toBe("");
    expect(rowTitles(container)).toHaveLength(3);

    await setUrl("?q=nightly&view=all");
    expect(searchInput(container).value).toBe("nightly");
    expect(pressed(container, "All")).toBe("true");
    expect(browserState.replace).not.toHaveBeenCalled();
  });
});

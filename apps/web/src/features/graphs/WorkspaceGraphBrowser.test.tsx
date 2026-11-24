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
  data: undefined as { projects: SavedGraphSummary[] } | undefined,
  error: undefined as Error | undefined,
  isLoading: false,
  workspace: {
    id: "workspace-atlas",
    name: "Atlas",
    slug: "atlas",
    kind: "shared",
    role: "editor",
    capabilities: ["view_project", "create_project"],
  } as Workspace,
  /** The address the page is mounted on, as the browser would report it. */
  pathname: "/workspaces/atlas/projects",
  search: "",
  /** False holds the address still, so a write that has not landed can be seen. */
  landWrites: true,
}));

const apiMocks = vi.hoisted(() => ({
  useWorkspaceProjects: vi.fn(),
  useWorkspacePacks: vi.fn(),
  useProjectSummaryRefresh: vi.fn(),
  createStarterProject: vi.fn(),
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
    workspace.kind === "personal" ? "My projects" : workspace.name,
}));

vi.mock("@/hooks/use-api", () => ({
  useWorkspaceProjects: apiMocks.useWorkspaceProjects,
  useWorkspacePacks: apiMocks.useWorkspacePacks,
  useProjectSummaryRefresh: apiMocks.useProjectSummaryRefresh,
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    createStarterProject: apiMocks.createStarterProject,
  };
});

import { WorkspaceGraphBrowser } from "./WorkspaceGraphBrowser";

const roots: Root[] = [];
let activeRoot: Root | null = null;

/** A browser row is a Project: one summary per Project, not per Graph. */
function project(
  id: string,
  name: string,
  updatedAt = "2026-08-10T10:00:00Z",
): SavedGraphSummary {
  return {
    id,
    name,
    node_count: 3,
    edge_count: 2,
    graph_count: 1,
    revision: 4,
    updated_at: updatedAt,
    draft_pending: false,
  };
}

const INTAKE_PROJECTS: SavedGraphSummary[] = [
  project("project-invoice", "Invoice intake", "2026-08-12T10:00:00Z"),
  project("project-archive", "Invoice archive audit", "2026-08-11T10:00:00Z"),
  project("project-sync", "Nightly sync", "2026-08-10T10:00:00Z"),
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
    'input[aria-label="Search projects"]',
  );
  if (!input) throw new Error("Search input not found");
  return input;
}

/**
 * One row per Project: the link inside a list item of the labelled project list.
 * Rows are read off the accessible structure rather than a class name, because
 * the list's styling is StyleX and carries no hook to select.
 */
function rowLinks(container: ParentNode): HTMLAnchorElement[] {
  return Array.from(
    container.querySelectorAll<HTMLAnchorElement>(
      '[aria-label="Recent projects"] > li > a, [aria-label="All projects"] > li > a',
    ),
  );
}

/** The project name leads the row; only the icon span ahead of it is hidden. */
function rowTitles(container: ParentNode): string[] {
  return rowLinks(container).map(
    (row) => row.querySelector("span:not([aria-hidden])")?.textContent ?? "",
  );
}

/**
 * Recent/All is one labelled radio group rather than a pair of toggle buttons,
 * so its state is read off `aria-checked`.
 */
function viewOption(container: ParentNode, label: string): HTMLElement {
  const group = container.querySelector('[role="radiogroup"]');
  if (!group) throw new Error("Project view radio group not found");
  expect(group.getAttribute("aria-label")).toBe("Project views");
  const match = Array.from(
    group.querySelectorAll<HTMLElement>('[role="radio"]'),
  ).find((option) => option.textContent?.includes(label));
  if (!match) throw new Error(`Project view option not found: ${label}`);
  return match;
}

function viewChecked(container: ParentNode, label: string): string | null {
  return viewOption(container, label).getAttribute("aria-checked");
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
  browserState.data = { projects: [] };
  browserState.error = undefined;
  browserState.isLoading = false;
  browserState.landWrites = true;
  browserState.pathname = "/workspaces/atlas/projects";
  browserState.search = "";
  browserState.workspace = {
    id: "workspace-atlas",
    name: "Atlas",
    slug: "atlas",
    kind: "shared",
    role: "editor",
    capabilities: ["view_project", "create_project"],
  };
  apiMocks.useWorkspaceProjects.mockImplementation(() => ({
    data: browserState.data,
    error: browserState.error,
    isLoading: browserState.isLoading,
    mutate: browserState.mutate,
  }));
  apiMocks.useWorkspacePacks.mockReturnValue({ data: undefined });
  apiMocks.useProjectSummaryRefresh.mockReturnValue(async () => undefined);
  apiMocks.createStarterProject.mockReset();
});

afterEach(async () => {
  activeRoot = null;
  for (const root of roots.splice(0)) {
    await act(async () => root.unmount());
  }
  document.body.replaceChildren();
});

describe("workspace graph browser", () => {
  it("loads and links only the active workspace's projects", async () => {
    browserState.data = {
      projects: Array.from({ length: 9 }, (_, index) =>
        project(
          `project-${index}`,
          `Project ${index}`,
          `2026-08-${String(index + 1).padStart(2, "0")}T10:00:00Z`,
        ),
      ),
    };
    const container = await renderBrowser();

    expect(apiMocks.useWorkspaceProjects).toHaveBeenCalledWith(
      "workspace-atlas",
    );
    expect(container.textContent).toContain("Atlas");
    expect(
      container.querySelector('[aria-label="Filter by location"]'),
    ).toBeNull();
    expect(rowLinks(container)).toHaveLength(8);

    await click(viewOption(container, "All"));
    expect(rowLinks(container)).toHaveLength(9);
    expect(
      container
        .querySelector<HTMLAnchorElement>(
          '[aria-label="Open Project 8 in Atlas"]',
        )
        ?.getAttribute("href"),
    ).toBe("/workspaces/atlas/projects/project-8");
  });

  it("searches project names and distinguishes no results from an empty workspace", async () => {
    browserState.data = {
      projects: [project("project-1", "Invoice intake")],
    };
    const container = await renderBrowser();
    const search = searchInput(container);

    await change(search, "missing");
    expect(container.textContent).toContain("No projects match your search");
    expect(container.textContent).not.toContain("No projects yet");
  });

  it("creates a project directly in the active workspace", async () => {
    const container = await renderBrowser();

    await click(button(container, "New project"));

    expect(browserState.push).toHaveBeenCalledWith(
      "/workspaces/atlas/projects/new",
    );
    expect(container.textContent).not.toContain("Choose a location");
  });

  it("shows loading, failure with retry, and true empty states", async () => {
    browserState.data = undefined;
    browserState.isLoading = true;
    const loading = await renderBrowser();
    expect(loading.textContent).toContain("Loading projects…");

    browserState.isLoading = false;
    browserState.error = new Error("offline");
    const failed = await renderBrowser();
    expect(failed.textContent).toContain("Projects couldn't be loaded");
    await click(button(failed, "Retry"));
    expect(browserState.mutate).toHaveBeenCalledOnce();

    browserState.data = { projects: [] };
    browserState.error = undefined;
    const empty = await renderBrowser();
    expect(empty.textContent).toContain("No projects yet");
  });

  it("keeps the loaded list and announces a failed refresh with its own retry", async () => {
    browserState.data = { projects: [project("project-1", "Invoice intake")] };
    browserState.error = new Error("offline");
    const container = await renderBrowser();

    const strip = container.querySelector('[role="status"]');
    expect(strip?.textContent).toContain(
      "The latest project list could not be refreshed.",
    );
    expect(rowTitles(container)).toEqual(["Invoice intake"]);

    if (!strip) throw new Error("Refresh failure was not announced");
    await click(button(strip, "Retry"));
    expect(browserState.mutate).toHaveBeenCalledOnce();
  });

  it("hides starter recipes until Document OCR is subscribed", async () => {
    const container = await renderBrowser();
    expect(container.textContent).not.toContain("Start from a recipe");
  });

  it("starts a transcription project from a recipe", async () => {
    apiMocks.useWorkspacePacks.mockReturnValue({
      data: [{ slug: "document_ocr", subscribed: true }],
    });
    apiMocks.createStarterProject.mockResolvedValue({
      id: "project-transcription",
      name: "Transcribe a scanned page",
      created_at: "2026-08-12T10:00:00Z",
      updated_at: "2026-08-12T10:00:00Z",
    });
    const container = await renderBrowser();

    expect(container.textContent).toContain("Start from a recipe");
    expect(container.textContent).toContain(
      "Scan or PDF → Document OCR → Text",
    );
    expect(container.textContent).toContain(
      "Scan → Document OCR → Spreadsheet table",
    );

    await click(button(container, "Transcribe a scanned page"));

    expect(apiMocks.createStarterProject).toHaveBeenCalledWith(
      "workspace-atlas",
      "transcribe_page",
    );
    expect(browserState.push).toHaveBeenCalledWith(
      "/workspaces/atlas/projects/project-transcription",
    );
  });

  it("shows Personal badge and step count without repeating the workspace column on rows", async () => {
    browserState.workspace = {
      id: "workspace-personal",
      name: "Personal workspace",
      slug: "personal",
      kind: "personal",
      role: "owner",
      capabilities: ["view_project", "create_project"],
    };
    browserState.data = {
      projects: [project("project-1", "Parish register transcription")],
    };
    const container = await renderBrowser();

    expect(container.querySelector("header")?.textContent).toContain(
      "Personal",
    );
    const link = rowLinks(container)[0];
    expect(link?.textContent).toContain("Parish register transcription");
    expect(link?.textContent).toContain("3 steps");
    expect(link?.textContent).not.toContain("My projects");
  });
});

describe("workspace graph browser address filters", () => {
  beforeEach(() => {
    browserState.data = { projects: INTAKE_PROJECTS };
  });

  it("restores the filters, the controls, and the list from the address", async () => {
    const container = await renderBrowser("?q=invoice&view=all");

    expect(searchInput(container).value).toBe("invoice");
    expect(viewChecked(container, "All")).toBe("true");
    expect(viewChecked(container, "Recent")).toBe("false");
    expect(rowTitles(container)).toEqual([
      "Invoice intake",
      "Invoice archive audit",
    ]);
    expect(container.textContent).toContain("2 projects");
  });

  it("limits a filtered list to Recent until the address asks for All", async () => {
    browserState.data = {
      projects: Array.from({ length: 9 }, (_, index) =>
        project(`project-${index}`, `Invoice ${index}`),
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
    expect(viewChecked(container, "Recent")).toBe("true");
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

    expect(lastWrite()).toBe("/workspaces/atlas/projects?q=nightly");
    expect(input.value).toBe("nightly");
    expect(rowTitles(container)).toEqual(["Nightly sync"]);
  });

  it("omits defaults and keeps parameters this browser does not own", async () => {
    const container = await renderBrowser("?utm_source=email");
    const input = searchInput(container);

    await change(input, "invoice");
    expect(lastWrite()).toBe(
      "/workspaces/atlas/projects?utm_source=email&q=invoice",
    );

    await change(input, "");
    expect(lastWrite()).toBe("/workspaces/atlas/projects?utm_source=email");
    expect(rowTitles(container)).toHaveLength(3);
  });

  it("commits the view choice and takes it back out of the address", async () => {
    browserState.data = {
      projects: Array.from({ length: 9 }, (_, index) =>
        project(`project-${index}`, `Project ${index}`),
      ),
    };
    const container = await renderBrowser();

    await click(viewOption(container, "All"));
    expect(lastWrite()).toBe("/workspaces/atlas/projects?view=all");
    expect(viewChecked(container, "All")).toBe("true");

    await click(viewOption(container, "Recent"));
    expect(lastWrite()).toBe("/workspaces/atlas/projects");
    expect(viewChecked(container, "Recent")).toBe("true");
  });

  it("clears the address through the empty state's own action", async () => {
    const container = await renderBrowser("?q=missing");
    expect(container.textContent).toContain("No projects match your search");

    await click(button(container, "Clear search"));

    expect(lastWrite()).toBe("/workspaces/atlas/projects");
    expect(searchInput(container).value).toBe("");
    expect(rowTitles(container)).toHaveLength(3);
  });

  it("keeps a keystroke the address has not absorbed yet", async () => {
    browserState.landWrites = false;
    const container = await renderBrowser();
    const input = searchInput(container);

    await change(input, "in");
    expect(lastWrite()).toBe("/workspaces/atlas/projects?q=in");
    await change(input, "inv");
    expect(lastWrite()).toBe("/workspaces/atlas/projects?q=inv");

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
      "/workspaces/atlas/projects?q=in",
      "/workspaces/atlas/projects?q=inv",
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
    await click(viewOption(container, "All"));

    // A view change carries the search this page asked for, not the one the
    // address has reached, and the field keeps what the person typed.
    expect(lastWrite()).toBe("/workspaces/atlas/projects?q=nightly&view=all");
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
    expect(viewChecked(container, "All")).toBe("true");
    expect(browserState.replace).not.toHaveBeenCalled();
  });
});

// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LocatedProject } from "@/hooks/use-api";
import type { Workspace } from "@/lib/api";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const browserState = vi.hoisted(() => ({
  push: vi.fn(),
  retryProjects: vi.fn(async () => undefined),
  retryWorkspaces: vi.fn(async () => undefined),
  workspaces: [] as Workspace[],
  workspacesError: undefined as Error | undefined,
  projects: null as LocatedProject[] | null,
  projectsError: null as Error | null,
  isLoading: false,
  isRefreshing: false,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: browserState.push }),
}));

vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.ComponentProps<"a">) => (
    <a {...props}>{children}</a>
  ),
}));

vi.mock("@/features/auth/AuthSessionBoundary", () => ({
  useAuthSession: () => ({
    session: { user_id: "user-private-id" },
    logout: vi.fn(),
  }),
}));

vi.mock("@/features/workspaces/WorkspaceLayout", () => ({
  WorkspaceRail: () => <aside data-workspace-rail />,
  workspaceDisplayName: (workspace: { name: string; kind: string }) =>
    workspace.kind === "personal" ? "My graphs" : workspace.name,
}));

vi.mock("@/hooks/use-api", () => ({
  useWorkspaces: () => ({
    data: browserState.workspaces,
    error: browserState.workspacesError,
    mutate: browserState.retryWorkspaces,
  }),
  useAllWorkspacesProjects: () => ({
    projects: browserState.projects,
    error: browserState.projectsError,
    isLoading: browserState.isLoading,
    isRefreshing: browserState.isRefreshing,
    retry: browserState.retryProjects,
  }),
}));

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ open, children }: { open: boolean; children: React.ReactNode }) =>
    open ? <>{children}</> : null,
  DialogContent: ({ children }: { children: React.ReactNode }) => (
    <section role="dialog">{children}</section>
  ),
  DialogHeader: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
  DialogTitle: ({ children }: { children: React.ReactNode }) => (
    <h2>{children}</h2>
  ),
  DialogDescription: ({ children }: { children: React.ReactNode }) => (
    <p>{children}</p>
  ),
  DialogBody: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import { GraphBrowser } from "./GraphBrowser";

const roots: Root[] = [];

const personal = {
  id: "location-personal",
  name: "Personal workspace",
  slug: "private-slug",
  kind: "personal" as const,
  role: "owner" as const,
  capabilities: ["view_project", "create_project"],
} satisfies Workspace;

const team = {
  id: "location-team",
  name: "Atlas",
  slug: "secret-team-slug",
  kind: "shared" as const,
  role: "editor" as const,
  capabilities: ["view_project", "create_project"],
} satisfies Workspace;

/** One row of the cross-workspace feed: a Project, plus where it lives. */
function project(
  id: string,
  name: string,
  location: Workspace,
  updatedAt = "2026-08-10T10:00:00Z",
): LocatedProject {
  return {
    id,
    name,
    node_count: 3,
    edge_count: 2,
    graph_count: 1,
    revision: 4,
    updated_at: updatedAt,
    draft_pending: false,
    archived: false,
    archived_at: null,
    creator: null,
    folder: null,
    last_opened_at: null,
    starred: false,
    location: {
      id: location.id,
      name: location.name,
      slug: location.slug,
      kind: location.kind,
    },
  };
}

async function renderBrowser() {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  await act(async () => root.render(<GraphBrowser />));
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

async function change(
  element: HTMLInputElement | HTMLSelectElement,
  value: string,
) {
  await act(async () => {
    const prototype =
      element instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value")?.set?.call(
      element,
      value,
    );
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

beforeEach(() => {
  browserState.push.mockReset();
  browserState.retryProjects.mockClear();
  browserState.retryWorkspaces.mockClear();
  browserState.workspaces = [personal, team];
  browserState.workspacesError = undefined;
  browserState.projects = [
    project("project-personal", "Invoice intake", personal),
    project("project-team", "Quarterly plan", team),
  ];
  browserState.projectsError = null;
  browserState.isLoading = false;
  browserState.isRefreshing = false;
});

afterEach(async () => {
  for (const root of roots.splice(0)) {
    await act(async () => root.unmount());
  }
  document.body.replaceChildren();
});

describe("graph-first browser", () => {
  it("orients the signed-in user around projects and opens one directly", async () => {
    const container = await renderBrowser();

    expect(container.querySelector("h1")?.textContent).toBe("Graphs");
    expect(container.textContent).toContain("Recent");
    expect(container.textContent).toContain("All");
    expect(container.textContent).toContain("My graphs");
    expect(container.textContent).toContain("Atlas");
    expect(container.textContent).not.toContain("private-slug");
    expect(container.textContent).not.toContain("editor");
    expect(container.textContent).not.toContain("user-private-id");

    const link = container.querySelector<HTMLAnchorElement>(
      'a[aria-label="Open Quarterly plan in Atlas"]',
    );
    expect(link?.getAttribute("href")).toBe(
      "/workspaces/secret-team-slug/projects/project-team",
    );
  });

  it("searches project names and location names, then distinguishes no results", async () => {
    const container = await renderBrowser();
    const search = container.querySelector<HTMLInputElement>(
      'input[aria-label="Search graphs"]',
    )!;

    await change(search, "Atlas");
    expect(container.textContent).toContain("Quarterly plan");
    expect(container.textContent).not.toContain("Invoice intake");

    await change(search, "missing graph");
    expect(container.textContent).toContain("No graphs match your search");
    expect(container.textContent).not.toContain("No graphs yet");
  });

  it("filters by location and exposes the complete All view", async () => {
    browserState.projects = Array.from({ length: 9 }, (_, index) =>
      project(
        `project-${index}`,
        `Project ${index}`,
        index === 8 ? team : personal,
      ),
    );
    const container = await renderBrowser();

    expect(container.querySelectorAll(".grafy-graphs__row")).toHaveLength(8);
    await click(button(container, "All"));
    expect(container.querySelectorAll(".grafy-graphs__row")).toHaveLength(9);

    const location = container.querySelector<HTMLSelectElement>(
      'select[aria-label="Filter by location"]',
    )!;
    await change(location, team.id);
    expect(container.querySelectorAll(".grafy-graphs__row")).toHaveLength(1);
    expect(container.textContent).toContain("Project 8");
  });

  it("counts the listed projects and marks a refresh over cached ones", async () => {
    const container = await renderBrowser();
    expect(container.textContent).toContain("2 graphs");

    browserState.isRefreshing = true;
    const refreshing = await renderBrowser();
    expect(refreshing.textContent).toContain("2 graphs · refreshing…");
  });

  it("shows loading, total failure, and explicit retry states", async () => {
    browserState.projects = null;
    browserState.isLoading = true;
    const loading = await renderBrowser();
    expect(loading.textContent).toContain("Loading graphs…");

    browserState.projects = null;
    browserState.isLoading = false;
    browserState.projectsError = new Error("offline");
    const failed = await renderBrowser();
    expect(failed.textContent).toContain("Graphs couldn't be loaded");
    expect(failed.textContent).not.toContain("Loading graphs…");
    await click(button(failed, "Retry"));
    expect(browserState.retryProjects).toHaveBeenCalledOnce();
  });

  it("shows a true empty state when every loaded location has no projects", async () => {
    browserState.projects = [];
    const container = await renderBrowser();

    expect(container.textContent).toContain("No graphs yet");
    expect(container.textContent).not.toContain("No graphs match your search");
  });

  it("asks for a location only when more than one creation location exists", async () => {
    const multiple = await renderBrowser();
    await click(button(multiple, "New graph"));
    expect(document.body.textContent).toContain("Choose a location");
    await click(button(document.body, "Atlas"));
    expect(browserState.push).toHaveBeenCalledWith(
      "/workspaces/secret-team-slug/projects/new",
    );

    browserState.push.mockReset();
    browserState.workspaces = [personal];
    browserState.projects = [];
    const single = await renderBrowser();
    await click(button(single, "New graph"));
    expect(browserState.push).toHaveBeenCalledWith(
      "/workspaces/private-slug/projects/new",
    );
    expect(single.textContent).not.toContain("Choose a location");
  });
});

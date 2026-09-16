// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Session, Workspace } from "@/lib/api";
import {
  WorkspaceRail,
  resolveSelectedWorkspace,
  sessionDisplayName,
  sessionInitials,
  workspaceCanManageMembers,
  workspaceDisplayName,
  workspaceMobileContextLabel,
  workspaceRouteAccessState,
  workspaceRouteGraphId,
  workspaceSelectorLabel,
} from "./WorkspaceLayout";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const testState = vi.hoisted(() => ({
  pathname: "/workspaces/operations/graphs/graph-a",
  push: vi.fn(),
  savedGraphs: [] as Array<{
    id: string;
    name: string;
    revision: number;
    node_count: number;
    edge_count: number;
    updated_at: string;
  }>,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ workspaceSlug: "operations" }),
  usePathname: () => testState.pathname,
  useRouter: () => ({ push: testState.push }),
}));

vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.ComponentProps<"a">) =>
    React.createElement("a", props, children),
}));

vi.mock("@/components/brand", () => ({
  BrandIcon: () => React.createElement("span"),
  BrandWordmark: () => React.createElement("span"),
}));

vi.mock("@/components/theme", () => ({
  useTheme: () => ({ cycleTheme: vi.fn(), preference: "system" }),
}));

vi.mock("@/components/threshold-status", () => ({
  ThresholdStatus: () => null,
}));

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ open, children }: { open: boolean; children: React.ReactNode }) =>
    open ? React.createElement("div", { role: "dialog" }, children) : null,
  DialogBody: ({ children }: { children: React.ReactNode }) => React.createElement("div", null, children),
  DialogContent: ({ children }: { children: React.ReactNode }) => React.createElement("div", null, children),
  DialogDescription: ({ children }: { children: React.ReactNode }) => React.createElement("p", null, children),
  DialogHeader: ({ children }: { children: React.ReactNode }) => React.createElement("div", null, children),
  DialogTitle: ({ children }: { children: React.ReactNode }) => React.createElement("h2", null, children),
}));

vi.mock("swr", () => ({
  useSWRConfig: () => ({ mutate: vi.fn() }),
}));

vi.mock("@/features/auth/AuthSessionBoundary", () => ({
  useAuthSession: () => ({ session: testSession, logout: vi.fn() }),
}));

vi.mock("@/features/workbench/ui/WorkbenchChromeContext", () => ({
  useWorkbenchChrome: () => null,
}));

vi.mock("@/hooks/use-api", () => ({
  useSavedGraphs: () => ({
    data: { graphs: testState.savedGraphs },
    mutate: vi.fn(),
  }),
  useGraphSummaryRefresh: () => vi.fn(),
  useWorkspaces: () => ({ data: [] }),
  useMyWorkspaceInvitations: () => ({ data: [], mutate: vi.fn() }),
}));

const mountedRoots = new Set<Root>();

afterEach(async () => {
  for (const root of mountedRoots) {
    await act(async () => root.unmount());
  }
  mountedRoots.clear();
  document.body.replaceChildren();
  testState.pathname = "/workspaces/operations/graphs/graph-a";
  testState.push.mockReset();
  testState.savedGraphs = [];
  vi.unstubAllGlobals();
});

const workspace = (
  capabilities: readonly Workspace["capabilities"][number][],
  overrides: Partial<Workspace> = {},
): Workspace => ({
  id: "workspace-1",
  name: "Operations",
  slug: "operations",
  kind: "shared",
  role: "owner",
  capabilities,
  ...overrides,
});

const testSession: Session = {
  id: "session-1",
  user_id: "user-1",
  display_name: "Ada Lovelace",
  email: "ada@example.test",
  current: true,
  created_at: "2026-08-15T00:00:00Z",
  expires_at: "2026-08-16T00:00:00Z",
  last_used_at: null,
  revoked_at: null,
};

async function renderWorkspaceRail(
  workspaces: readonly Workspace[] = [workspace([])],
): Promise<{
  container: HTMLDivElement;
  rerender: () => Promise<void>;
}> {
  const media = {
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  };
  vi.stubGlobal("matchMedia", vi.fn(() => media));
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());

  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.add(root);
  const rerender = async () => {
    await act(async () => {
      root.render(
        React.createElement(WorkspaceRail, {
          workspaces,
          activeSlug: "operations",
          session: testSession,
          onLogout: vi.fn(),
        }),
      );
    });
  };
  await rerender();
  return { container, rerender };
}

describe("workspace route and capability state", () => {
  it("distinguishes direct missing routes from revoked access", () => {
    expect(workspaceRouteAccessState("unknown", undefined, undefined)).toBe(
      "missing",
    );
    expect(
      workspaceRouteAccessState("operations", undefined, {
        slug: "operations",
        id: "workspace-1",
      }),
    ).toBe("revoked");
    expect(
      workspaceRouteAccessState("operations", workspace([]), {
        slug: "operations",
        id: "workspace-1",
      }),
    ).toBe("available");
  });

  it("only exposes member management while the server capability is present", () => {
    expect(workspaceCanManageMembers(workspace(["manage_members"]))).toBe(true);
    expect(workspaceCanManageMembers(workspace([]))).toBe(false);
  });

  it("resolves the open graph so the rail can highlight it", () => {
    expect(workspaceRouteGraphId("/workspaces/team")).toBeNull();
    expect(workspaceRouteGraphId("/workspaces/team/graphs/new")).toBeNull();
    expect(
      workspaceRouteGraphId(
        "/workspaces/team/graphs/00000000-0000-0000-0000-000000000001",
      ),
    ).toBe("00000000-0000-0000-0000-000000000001");
    expect(
      workspaceRouteGraphId(
        "/workspaces/team/graphs/00000000-0000-0000-0000-000000000001/runs",
      ),
    ).toBe("00000000-0000-0000-0000-000000000001");
  });

  it("labels a personal workspace as My graphs in the UI", () => {
    expect(
      workspaceDisplayName(
        workspace([], { kind: "personal", name: "Personal workspace" }),
      ),
    ).toBe("My graphs");
    expect(workspaceDisplayName(workspace([], { name: "Operations" }))).toBe(
      "Operations",
    );
  });

  it("labels the workspace switcher as Personal by default", () => {
    expect(workspaceSelectorLabel(undefined)).toBe("Personal");
    expect(
      workspaceSelectorLabel(
        workspace([], { kind: "personal", name: "Personal workspace" }),
      ),
    ).toBe("Personal");
    expect(workspaceSelectorLabel(workspace([], { name: "Operations" }))).toBe(
      "Operations",
    );
  });

  it("labels the mobile header with route context instead of a fallback workspace", () => {
    const personal = workspace([], {
      kind: "personal",
      name: "Personal workspace",
    });

    expect(workspaceMobileContextLabel("/graphs", personal)).toBe("Graphs");
    expect(workspaceMobileContextLabel("/templates", personal)).toBe(
      "Templates",
    );
    expect(workspaceMobileContextLabel("/templates/new", personal)).toBe(
      "Save template",
    );
    expect(workspaceMobileContextLabel("/workspaces", personal)).toBe(
      "Teams & access",
    );
    expect(
      workspaceMobileContextLabel("/workspaces/operations/settings", personal),
    ).toBe("Settings");
    expect(
      workspaceMobileContextLabel(
        "/workspaces/operations/graphs/graph-1",
        workspace([], { name: "Operations" }),
      ),
    ).toBe("Operations");
    expect(workspaceMobileContextLabel("/unknown", personal)).toBe("Graphs");
  });

  it("resolves the selected workspace to the active slug, else personal", () => {
    const personal = workspace([], {
      kind: "personal",
      id: "workspace-personal",
      slug: "personal",
    });
    const team = workspace([], {
      id: "workspace-team",
      slug: "operations",
      name: "Operations",
    });
    expect(resolveSelectedWorkspace([personal, team], "operations")).toBe(team);
    expect(resolveSelectedWorkspace([personal, team], "missing")).toBe(
      personal,
    );
    expect(resolveSelectedWorkspace([personal, team], undefined)).toBe(
      personal,
    );
    expect(resolveSelectedWorkspace(undefined, undefined)).toBeUndefined();
  });

  it("derives account label and initials from the session profile", () => {
    expect(
      sessionDisplayName({
        display_name: "Ada Lovelace",
        email: "ada@example.test",
        user_id: "user-1",
      }),
    ).toBe("Ada Lovelace");
    expect(
      sessionInitials({
        display_name: "Ada Lovelace",
        email: "ada@example.test",
        user_id: "user-1",
      }),
    ).toBe("AL");
    expect(
      sessionInitials({
        display_name: null,
        email: "ada@example.test",
        user_id: "user-1",
      }),
    ).toBe("AD");
  });
});

describe("workspace rail route lifecycle", () => {
  it("opens the graph list in the selected workspace", async () => {
    testState.pathname = "/workspaces/operations/graphs";
    const { container } = await renderWorkspaceRail();
    const allGraphs = [...container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "All graphs",
    );

    expect(allGraphs?.classList.contains("is-active")).toBe(true);
    await act(async () => allGraphs?.click());

    expect(testState.push).toHaveBeenCalledWith(
      "/workspaces/operations/graphs",
    );
  });

  it("switches workspace while preserving the current section", async () => {
    const atlas = workspace([], {
      id: "workspace-2",
      name: "Atlas",
      slug: "atlas",
    });
    testState.pathname = "/workspaces/operations/settings";
    const { container, rerender } = await renderWorkspaceRail([
      workspace([]),
      atlas,
    ]);
    const selector = container.querySelector<HTMLSelectElement>(
      'select[aria-label="Switch workspace"]',
    )!;

    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLSelectElement.prototype,
        "value",
      )?.set?.call(selector, "atlas");
      selector.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(testState.push).toHaveBeenCalledWith("/workspaces/atlas/settings");

    testState.push.mockReset();
    testState.pathname = "/workspaces/operations/graphs/graph-a";
    await rerender();
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLSelectElement.prototype,
        "value",
      )?.set?.call(selector, "atlas");
      selector.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(testState.push).toHaveBeenCalledWith("/workspaces/atlas/graphs");
  });

  it("opens settings for the active workspace", async () => {
    const { container } = await renderWorkspaceRail();
    const settings = [...container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "Settings",
    );

    await act(async () => settings?.click());

    expect(testState.push).toHaveBeenCalledWith(
      "/workspaces/operations/settings",
    );
  });

  it("does not reopen a mobile drawer after navigating away and back", async () => {
    const { container, rerender } = await renderWorkspaceRail();
    const openNavigation = container.querySelector<HTMLButtonElement>(
      "[aria-label='Open navigation']",
    );

    await act(async () => openNavigation?.click());
    expect(
      container.querySelector(".grafy-workspace-rail.is-mobile-open"),
    ).not.toBeNull();

    testState.pathname = "/workspaces/operations/graphs/graph-b";
    await rerender();
    expect(
      container.querySelector(".grafy-workspace-rail.is-mobile-open"),
    ).toBeNull();

    testState.pathname = "/workspaces/operations/graphs/graph-a";
    await rerender();
    expect(
      container.querySelector(".grafy-workspace-rail.is-mobile-open"),
    ).toBeNull();
  });

  it("keeps recent graphs without redundant sidebar controls or icons", async () => {
    testState.savedGraphs = [
      {
        id: "graph-a",
        name: "Monthly extraction",
        revision: 1,
        node_count: 2,
        edge_count: 1,
        updated_at: "2026-09-01T12:00:00Z",
      },
    ];
    const { container } = await renderWorkspaceRail();
    const recentGraph = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Monthly extraction"]',
    );

    expect(container.textContent).not.toContain("Quick switch");
    expect(container.querySelector('[aria-label="Graph location"]')).toBeNull();
    expect(recentGraph).not.toBeNull();
    expect(recentGraph?.querySelector("svg")).toBeNull();
  });
});

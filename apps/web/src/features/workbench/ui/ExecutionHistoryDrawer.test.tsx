// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Run, RunList, WorkspaceMember } from "@/lib/api";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const apiMocks = vi.hoisted(() => ({
  listRuns: vi.fn<() => Promise<RunList>>(),
  listWorkspaceMembers: vi.fn<() => Promise<readonly WorkspaceMember[]>>(),
}));

vi.mock("@/lib/api", () => ({
  listRuns: apiMocks.listRuns,
  listWorkspaceMembers: apiMocks.listWorkspaceMembers,
}));

import { ExecutionHistoryDrawer } from "./ExecutionHistoryDrawer";

const OPEN_GRAPH_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_GRAPH_ID = "44444444-4444-4444-8444-444444444444";
const ADA_ID = "55555555-5555-4555-8555-555555555555";

const mountedRoots = new Map<Root, HTMLElement>();

afterEach(async () => {
  for (const [root, container] of mountedRoots) {
    await React.act(async () => root.unmount());
    container.remove();
  }
  mountedRoots.clear();
  document.body.replaceChildren();
  vi.clearAllMocks();
});

/**
 * The checked-in schema still omits the `cancelled` Run status ADR 0020 defines,
 * so a fixture is allowed to name it and the cast happens once, here.
 */
type RunOverrides = Partial<Run> & { readonly status?: string };

function run(overrides: RunOverrides = {}): Run {
  return {
    id: "00000000-0000-4000-8000-0000000000a1",
    status: "succeeded",
    graph_id: OPEN_GRAPH_ID,
    targets: [{ node_id: "node-1", call_path: [] }],
    started_by_user_id: ADA_ID,
    created_at: "2026-07-18T08:00:00Z",
    finished_at: "2026-07-18T08:00:02Z",
    error: null,
    project_id: "project-1",
    workspace_id: "workspace-1",
    ...overrides,
  } as Run;
}

function runList(...runs: readonly Run[]): RunList {
  return { runs };
}

function member(id: string, displayName: string): WorkspaceMember {
  return {
    authorization_version: 1,
    revoked_at: null,
    role: "editor",
    user: { active: true, display_name: displayName, email: null, id },
  };
}

/**
 * The drawer formats with the viewer's locale, so the expectation is built the
 * same way instead of hardcoding one locale's spelling.
 */
function formatted(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

async function renderDrawer(
  props: Partial<React.ComponentProps<typeof ExecutionHistoryDrawer>> = {},
  cache = new Map(),
) {
  const container = document.createElement("div");
  document.body.append(container);
  const returnFocusElement = document.createElement("button");
  document.body.append(returnFocusElement);
  const root = createRoot(container);
  mountedRoots.set(root, container);
  const swrConfig = { provider: () => cache, dedupingInterval: 0 };
  let currentProps: React.ComponentProps<typeof ExecutionHistoryDrawer> = {
    workspaceId: "workspace-1",
    projectId: "project-1",
    graphId: OPEN_GRAPH_ID,
    returnFocusRef: { current: returnFocusElement },
    onClose: () => undefined,
    ...props,
  };
  const rerender = async (
    nextProps: Partial<React.ComponentProps<typeof ExecutionHistoryDrawer>>,
  ) => {
    currentProps = { ...currentProps, ...nextProps };
    await React.act(async () => {
      root.render(
        <SWRConfig value={swrConfig}>
          <ExecutionHistoryDrawer {...currentProps} />
        </SWRConfig>,
      );
    });
  };
  await React.act(async () => {
    root.render(
      <SWRConfig value={swrConfig}>
        <ExecutionHistoryDrawer {...currentProps} />
      </SWRConfig>,
    );
  });
  const unmount = async () => {
    await React.act(async () => root.unmount());
    mountedRoots.delete(root);
    container.remove();
  };
  return { container, rerender, returnFocusElement, unmount };
}

function buttonNamed(container: HTMLElement, name: string): HTMLButtonElement {
  const button = [...container.querySelectorAll("button")].find(
    (candidate) =>
      candidate.textContent?.trim() === name ||
      candidate.getAttribute("aria-label") === name,
  );
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`Button ${name} was not rendered`);
  }
  return button;
}

function rows(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>('[role="listitem"]')];
}

/** The Notice that carries `text`, so a message cannot silently lose its role. */
function alertMentioning(container: HTMLElement, text: string): HTMLElement {
  const alert = [
    ...container.querySelectorAll<HTMLElement>('[role="alert"]'),
  ].find((node) => node.textContent?.includes(text));
  if (!alert) {
    throw new Error(`No alert mentions ${text}`);
  }
  return alert;
}

/** The row at `index`, or a failure that names what the list left out. */
function rowAt(container: HTMLElement, index: number): HTMLElement {
  const row = rows(container)[index];
  if (!row) throw new Error(`Run row ${index + 1} was not rendered`);
  return row;
}

describe("ExecutionHistoryDrawer", () => {
  it("is a labelled Runs dialog rather than an execution history", async () => {
    apiMocks.listRuns.mockResolvedValue(runList());

    const { container } = await renderDrawer();

    const dialog = container.querySelector('[role="dialog"]');
    expect(dialog?.getAttribute("aria-label")).toBe("Runs");
    expect(container.textContent).toContain("Runs");
    expect(container.textContent).not.toContain("Execution history");
  });

  it("lists the project's runs with status, start, starter and targets", async () => {
    const newest = run({
      id: "run-newest",
      created_at: "2026-07-18T09:00:00Z",
      finished_at: "2026-07-18T09:00:05Z",
      targets: [
        { node_id: "node-1", call_path: [] },
        { node_id: "node-3", call_path: ["total"] },
      ],
    });
    const older = run({
      id: "run-older",
      status: "running",
      created_at: "2026-07-18T08:00:00Z",
      finished_at: null,
      started_by_user_id: "55555555-5555-4555-8555-000000000000",
    });
    apiMocks.listRuns.mockResolvedValue(runList(newest, older));
    apiMocks.listWorkspaceMembers.mockResolvedValue([
      member(ADA_ID, "Ada Lovelace"),
    ]);

    const { container } = await renderDrawer();

    await vi.waitFor(() => {
      expect(rows(container)).toHaveLength(2);
    });
    const first = rowAt(container, 0);
    const second = rowAt(container, 1);
    expect(first.textContent).toContain("run-newest");
    expect(first.textContent).toContain(formatted("2026-07-18T09:00:00Z"));
    expect(first.textContent).toContain("succeeded");
    expect(first.textContent).toContain("Ada Lovelace");
    expect(first.textContent).toContain(formatted("2026-07-18T09:00:05Z"));
    expect(first.textContent).toContain("2 targets: node-1, node-3 via total");
    expect(container.textContent).toContain("1 running now");
    expect(second.textContent).toContain("run-older");
    expect(second.textContent).toContain("running");
    // A starter the roster does not know is still a person, never an id.
    expect(second.textContent).toContain("Started by a Team member");
    expect(second.textContent).not.toContain("000000000000");

    expect(apiMocks.listRuns).toHaveBeenCalledWith("workspace-1", "project-1");
  });

  it("tells the open graph's runs from another graph's runs", async () => {
    apiMocks.listRuns.mockResolvedValue(
      runList(
        run({ id: "run-here", graph_id: OPEN_GRAPH_ID }),
        run({ id: "run-there", graph_id: OTHER_GRAPH_ID }),
      ),
    );
    apiMocks.listWorkspaceMembers.mockResolvedValue([]);

    const { container } = await renderDrawer();

    await vi.waitFor(() => {
      expect(rows(container)).toHaveLength(2);
    });
    const here = rowAt(container, 0);
    const there = rowAt(container, 1);
    expect(here.textContent).toContain("this graph");
    expect(there.textContent).toContain("graph 44444444");
    expect(there.textContent).not.toContain("this graph");
  });

  it("keeps listing runs when the team roster cannot be read", async () => {
    apiMocks.listRuns.mockResolvedValue(runList(run({ id: "run-1" })));
    apiMocks.listWorkspaceMembers.mockRejectedValue(
      new Error("Members are not visible here"),
    );

    const { container } = await renderDrawer();

    await vi.waitFor(() => {
      expect(container.textContent).toContain("run-1");
      expect(container.textContent).toContain("Started by a Team member");
    });
    expect(container.textContent).not.toContain("Members are not visible here");
  });

  it("does not read the roster when no run names a starter", async () => {
    apiMocks.listRuns.mockResolvedValue(runList());

    const { container } = await renderDrawer();

    await vi.waitFor(() =>
      expect(container.textContent).toContain(
        "No run has been started in this project yet.",
      ),
    );
    expect(apiMocks.listWorkspaceMembers).not.toHaveBeenCalled();
  });

  it("shows why a failed run stopped and when it did", async () => {
    apiMocks.listRuns.mockResolvedValue(
      runList(
        run({
          id: "run-failed",
          status: "failed",
          finished_at: "2026-07-18T08:30:00Z",
          error: "operator gis.buffer@2 is not registered",
        }),
      ),
    );
    apiMocks.listWorkspaceMembers.mockResolvedValue([
      member(ADA_ID, "Ada Lovelace"),
    ]);

    const { container } = await renderDrawer();

    await vi.waitFor(() => {
      expect(container.textContent).toContain(
        "operator gis.buffer@2 is not registered",
      );
      expect(container.textContent).toContain(
        "ended " + formatted("2026-07-18T08:30:00Z"),
      );
      expect(container.textContent).toContain("Started by Ada Lovelace");
    });
  });

  it("asks for nothing without a project, and says so", async () => {
    const { container } = await renderDrawer({ projectId: null });

    await vi.waitFor(() => {
      expect(container.textContent).toContain("Runs belong to a project.");
    });
    expect(apiMocks.listRuns).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain("Loading runs");
  });

  it("revalidates the cached list when the drawer is reopened", async () => {
    const cache = new Map();
    apiMocks.listRuns
      .mockResolvedValueOnce(runList(run({ id: "run-older" })))
      .mockResolvedValue(runList(run({ id: "run-newest" })));
    apiMocks.listWorkspaceMembers.mockResolvedValue([]);

    const firstDrawer = await renderDrawer({}, cache);
    await vi.waitFor(() => {
      expect(firstDrawer.container.textContent).toContain("run-older");
      expect(apiMocks.listRuns).toHaveBeenCalledTimes(1);
    });
    await firstDrawer.unmount();

    const secondDrawer = await renderDrawer({}, cache);
    await vi.waitFor(() => {
      expect(apiMocks.listRuns).toHaveBeenCalledTimes(2);
      expect(secondDrawer.container.textContent).toContain("run-newest");
    });
  });

  it("re-reads the list when the drawer moves to another project", async () => {
    apiMocks.listRuns
      .mockResolvedValueOnce(runList(run({ id: "run-here" })))
      .mockResolvedValueOnce(runList(run({ id: "run-there" })));
    apiMocks.listWorkspaceMembers.mockResolvedValue([]);

    const drawer = await renderDrawer();
    await vi.waitFor(() => expect(rows(drawer.container)).toHaveLength(1));

    await drawer.rerender({ projectId: "project-2" });

    await vi.waitFor(() => {
      expect(drawer.container.textContent).toContain("run-there");
      expect(drawer.container.textContent).not.toContain("run-here");
    });
    expect(apiMocks.listRuns).toHaveBeenLastCalledWith(
      "workspace-1",
      "project-2",
    );
  });

  it("loads the list again through the refresh action", async () => {
    apiMocks.listRuns.mockResolvedValue(runList(run({ id: "run-1" })));
    apiMocks.listWorkspaceMembers.mockResolvedValue([]);

    const { container } = await renderDrawer();
    await vi.waitFor(() => expect(rows(container)).toHaveLength(1));

    await React.act(async () => {
      buttonNamed(container, "Refresh runs").click();
    });

    await vi.waitFor(() => expect(apiMocks.listRuns).toHaveBeenCalledTimes(2));
  });

  it("announces the list as it reads it", async () => {
    apiMocks.listRuns.mockImplementation(() => new Promise(() => undefined));

    const { container } = await renderDrawer();

    const status = container.querySelector('[role="status"]');
    expect(status?.textContent).toContain("Loading runs…");
  });

  it("reports a failed load and retries it", async () => {
    apiMocks.listRuns
      .mockRejectedValueOnce(new Error("Runs unavailable"))
      .mockResolvedValue(runList());

    const { container } = await renderDrawer();

    await vi.waitFor(() => {
      expect(() =>
        alertMentioning(container, "Runs unavailable"),
      ).not.toThrow();
    });
    await React.act(async () => {
      buttonNamed(
        alertMentioning(container, "Runs unavailable"),
        "Try again",
      ).click();
    });
    await vi.waitFor(() => expect(apiMocks.listRuns).toHaveBeenCalledTimes(2));
  });

  it("focuses its close button on open and hands focus back on close", async () => {
    apiMocks.listRuns.mockResolvedValue(runList());

    const onClose = vi.fn();
    const { container, returnFocusElement } = await renderDrawer({ onClose });

    const closeButton = buttonNamed(container, "Close runs");
    expect(document.activeElement).toBe(closeButton);

    await React.act(async () => {
      closeButton.click();
    });

    expect(onClose).toHaveBeenCalledOnce();
    expect(document.activeElement).toBe(returnFocusElement);
  });

  it("closes on Escape after focus leaves the drawer and restores the trigger", async () => {
    apiMocks.listRuns.mockResolvedValue(runList());
    const onClose = vi.fn();
    const { returnFocusElement } = await renderDrawer({ onClose });

    returnFocusElement.focus();

    await React.act(async () => {
      returnFocusElement.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
    });

    expect(onClose).toHaveBeenCalledOnce();
    expect(document.activeElement).toBe(returnFocusElement);
  });

  it("hands focus back when the drawer closes with focus inside it", async () => {
    apiMocks.listRuns.mockResolvedValue(runList(run({ id: "run-1" })));
    apiMocks.listWorkspaceMembers.mockResolvedValue([]);

    const { container, returnFocusElement, unmount } = await renderDrawer();
    await vi.waitFor(() => expect(rows(container)).toHaveLength(1));
    buttonNamed(container, "Refresh runs").focus();
    expect(document.activeElement?.getAttribute("aria-label")).toBe(
      "Refresh runs",
    );

    await unmount();

    expect(document.activeElement).toBe(returnFocusElement);
  });

  it("keeps the retired execution-history vocabulary out of its copy", async () => {
    apiMocks.listRuns.mockResolvedValue(
      runList(run({ id: "run-1", graph_id: OPEN_GRAPH_ID })),
    );
    apiMocks.listWorkspaceMembers.mockResolvedValue([]);

    const { container } = await renderDrawer();

    await vi.waitFor(() => expect(rows(container)).toHaveLength(1));

    // The retired shapes are gone from the copy, not just from the props.
    expect(container.textContent).not.toContain("Extract invoice");
    expect(container.textContent).not.toContain("Invoices");
    expect(container.textContent).not.toContain("graph revision");
    expect(container.textContent).not.toContain("requested node");
    expect(container.textContent).not.toContain("unsaved changes");
    expect(container.textContent).not.toContain("execution");
    expect(apiMocks.listRuns).toHaveBeenCalledWith("workspace-1", "project-1");
  });

  it("keeps showing the list while a revalidation is in flight", async () => {
    let resolveSecond: ((value: RunList) => void) | undefined;
    apiMocks.listRuns
      .mockResolvedValueOnce(runList(run({ id: "run-1" })))
      .mockImplementationOnce(
        () =>
          new Promise<RunList>((resolve) => {
            resolveSecond = resolve;
          }),
      );
    apiMocks.listWorkspaceMembers.mockResolvedValue([]);

    const drawer = await renderDrawer();
    await vi.waitFor(() => expect(rows(drawer.container)).toHaveLength(1));

    await React.act(async () => {
      buttonNamed(drawer.container, "Refresh runs").click();
    });

    expect(drawer.container.textContent).toContain("run-1");
    expect(buttonNamed(drawer.container, "Refresh runs").disabled).toBe(true);

    await React.act(async () => {
      resolveSecond?.(runList(run({ id: "run-1" }), run({ id: "run-2" })));
    });

    await vi.waitFor(() => expect(rows(drawer.container)).toHaveLength(2));
    expect(buttonNamed(drawer.container, "Refresh runs").disabled).toBe(false);
  });
});

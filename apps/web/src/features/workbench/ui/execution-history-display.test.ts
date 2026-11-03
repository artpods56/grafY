import { describe, expect, it, vi } from "vitest";

import type { Run, RunTargetInput, WorkspaceMember } from "@/lib/api";

// Vitest has no StyleX Babel pass, so `stylex.create` throws at runtime. Same
// substitution as `ExecutionHistoryDrawer.test.tsx`: each rule keeps its own
// identity, which is what these assertions compare.
vi.mock("@stylexjs/stylex", () => ({
  create: <Styles>(styles: Styles) => styles,
  props: () => ({}),
}));

import { executionHistoryDrawerStyles } from "./ExecutionHistoryDrawer.styles";
import {
  errorMessage,
  graphLabel,
  isActiveRun,
  runFinishLabel,
  runStartLabel,
  runStarterNames,
  runTargetsSummary,
  starterLabel,
  statusStyle,
} from "./execution-history-display";

/**
 * The checked-in schema still omits the `cancelled` Run status ADR 0020 defines,
 * so a fixture is allowed to name it and the cast happens once, here.
 */
type RunOverrides = Partial<Run> & { readonly status?: string };

function run(overrides: RunOverrides = {}): Run {
  return {
    id: "00000000-0000-4000-8000-0000000000a1",
    status: "succeeded",
    graph_id: "11111111-1111-4111-8111-111111111111",
    targets: [{ node_id: "node-1", call_path: [] }],
    started_by_user_id: "user-1",
    created_at: "2026-07-18T08:00:00Z",
    finished_at: "2026-07-18T08:09:00Z",
    error: null,
    project_id: "22222222-2222-4222-8222-222222222222",
    workspace_id: "33333333-3333-4333-8333-333333333333",
    ...overrides,
  } as Run;
}

function member(id: string, displayName: string | null): WorkspaceMember {
  return {
    authorization_version: 1,
    revoked_at: null,
    role: "editor",
    user: { active: true, display_name: displayName, email: null, id },
  };
}

function target(
  nodeId: string,
  callPath: readonly string[] = [],
): RunTargetInput {
  return { node_id: nodeId, call_path: callPath };
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

describe("runStartLabel", () => {
  it("shows when the Run asked for freshness", () => {
    expect(runStartLabel(run())).toBe(formatted("2026-07-18T08:00:00Z"));
  });

  it("shows an unreadable timestamp as it arrived instead of Invalid Date", () => {
    expect(runStartLabel(run({ created_at: "08:00 on the 18th" }))).toBe(
      "08:00 on the 18th",
    );
  });
});

describe("runFinishLabel", () => {
  it("shows when a finished Run gave up its demand", () => {
    expect(runFinishLabel(run())).toBe(formatted("2026-07-18T08:09:00Z"));
  });

  it("shows nothing while the Run still holds its demand", () => {
    expect(
      runFinishLabel(run({ status: "running", finished_at: null })),
    ).toBeNull();
  });
});

describe("statusStyle", () => {
  it("gives each terminal status its own badge rule", () => {
    expect(statusStyle("succeeded")).toBe(
      executionHistoryDrawerStyles.statusSuccess,
    );
    expect(statusStyle("failed")).toBe(
      executionHistoryDrawerStyles.statusFailure,
    );
    expect(statusStyle("cancelled")).toBe(
      executionHistoryDrawerStyles.statusCancelled,
    );
  });

  it("marks a Run the API owner lost as neither a success nor a failure", () => {
    expect(statusStyle("interrupted")).toBe(
      executionHistoryDrawerStyles.statusCancelled,
    );
  });

  it("shows the one status that is not terminal as active", () => {
    expect(statusStyle("running")).toBe(
      executionHistoryDrawerStyles.statusActive,
    );
  });

  it("never renders a missing badge rule", () => {
    for (const status of [
      "running",
      "succeeded",
      "failed",
      "cancelled",
      "interrupted",
    ] as const) {
      expect(statusStyle(status)).toBeDefined();
    }
  });
});

describe("isActiveRun", () => {
  it("counts only a Run that still holds its demand as active", () => {
    expect(isActiveRun(run({ status: "running" }))).toBe(true);
    for (const status of [
      "succeeded",
      "failed",
      "cancelled",
      "interrupted",
    ] as const) {
      expect(isActiveRun(run({ status }))).toBe(false);
    }
  });
});

describe("graphLabel", () => {
  it("names the Run's Graph by the one the author has open", () => {
    const open = run({ graph_id: "44444444-4444-4444-8444-444444444444" });

    expect(graphLabel(open.graph_id, open.graph_id)).toBe("this graph");
  });

  it("falls back to a short id for a Run of another Graph", () => {
    expect(
      graphLabel("44444444-4444-4444-8444-444444444444", "graph-open"),
    ).toBe("graph 44444444");
    expect(graphLabel("44444444-4444-4444-8444-444444444444", null)).toBe(
      "graph 44444444",
    );
  });

  it("shows a short id in full, because there is nothing to shorten", () => {
    expect(graphLabel("graphs-1", null)).toBe("graph graphs-1");
  });
});

describe("runTargetsSummary", () => {
  it("says plainly when a Run names no target", () => {
    expect(runTargetsSummary([])).toBe("no targets");
  });

  it("counts the targets and lists the node instances", () => {
    expect(runTargetsSummary([target("node-1")])).toBe("1 target: node-1");
    expect(runTargetsSummary([target("node-1"), target("node-2")])).toBe(
      "2 targets: node-1, node-2",
    );
  });

  it("names the call path that makes a nested node a different instance", () => {
    expect(runTargetsSummary([target("node-3", ["total", "totals"])])).toBe(
      "1 target: node-3 via total/totals",
    );
  });

  it("truncates a long target list rather than filling the row", () => {
    const targets = [
      target("node-1"),
      target("node-2"),
      target("node-3"),
      target("node-4"),
      target("node-5"),
    ];

    expect(runTargetsSummary(targets)).toBe(
      "5 targets: node-1, node-2, node-3 +2 more",
    );
    expect(runTargetsSummary(targets, 1)).toBe("5 targets: node-1 +4 more");
    expect(runTargetsSummary(targets, 5)).toBe(
      "5 targets: node-1, node-2, node-3, node-4, node-5",
    );
  });
});

describe("starterLabel", () => {
  it("names the member who started the Run", () => {
    const names = runStarterNames([member("user-1", "Ada Lovelace")]);

    expect(starterLabel(run({ started_by_user_id: "user-1" }), names)).toBe(
      "Ada Lovelace",
    );
  });

  it("never prints a user id for a person it cannot name", () => {
    const names = runStarterNames([member("user-1", "Ada Lovelace")]);

    expect(starterLabel(run({ started_by_user_id: "user-gone" }), names)).toBe(
      "a Team member",
    );
    expect(starterLabel(run({ started_by_user_id: null }), names)).toBe(
      "an unknown member",
    );
  });

  it("leaves a member without a display name unlabelled rather than inventing one", () => {
    const names = runStarterNames([member("user-2", null)]);

    expect([...names.keys()]).toEqual([]);
    expect(starterLabel(run({ started_by_user_id: "user-2" }), names)).toBe(
      "a Team member",
    );
  });

  it("works before the roster has arrived", () => {
    expect(starterLabel(run(), runStarterNames(undefined))).toBe(
      "a Team member",
    );
  });
});

describe("errorMessage", () => {
  it("shows what the server said when there is an error to show", () => {
    expect(errorMessage(new Error("run 41 vanished"), "Unknown error")).toBe(
      "run 41 vanished",
    );
  });

  it("falls back when the failure is not an error object", () => {
    expect(errorMessage("run 41 vanished", "Unknown error")).toBe(
      "Unknown error",
    );
    expect(errorMessage(undefined, "Unknown error")).toBe("Unknown error");
  });
});

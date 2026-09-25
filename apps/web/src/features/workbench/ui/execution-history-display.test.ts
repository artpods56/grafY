import { describe, expect, it, vi } from "vitest";

import type { GraphExecutionSummary } from "@/lib/api";

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
  executionTimestamp,
  statusStyle,
} from "./execution-history-display";

function summary(
  overrides: Partial<GraphExecutionSummary> = {},
): GraphExecutionSummary {
  return {
    execution_id: "00000000-0000-4000-8000-0000000000e1",
    graph_id: "graph-1",
    graph_revision: 4,
    status: "succeeded",
    scope: "selected-with-dependencies",
    requested_node_ids: ["node-1"],
    created_at: "2026-07-18T08:00:00Z",
    started_at: "2026-07-18T08:05:00Z",
    finished_at: "2026-07-18T08:09:00Z",
    workflow_run_id: "workflow-1",
    error: null,
    node_count: 2,
    artifact_count: 1,
    ...overrides,
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

describe("executionTimestamp", () => {
  it("shows when the execution finished", () => {
    expect(executionTimestamp(summary())).toBe(
      formatted("2026-07-18T08:09:00Z"),
    );
  });

  it("falls back to the start time while an execution is still running", () => {
    const running = executionTimestamp(
      summary({ status: "running", finished_at: null }),
    );

    expect(running).toBe(formatted("2026-07-18T08:05:00Z"));
    // The short time style resolves to minutes, so these stay distinguishable.
    expect(running).not.toBe(formatted("2026-07-18T08:00:00Z"));
    expect(running).not.toBe(formatted("2026-07-18T08:09:00Z"));
  });

  it("falls back to the creation time for a queued execution", () => {
    expect(
      executionTimestamp(
        summary({ status: "queued", started_at: null, finished_at: null }),
      ),
    ).toBe(formatted("2026-07-18T08:00:00Z"));
  });

  it("shows an unreadable timestamp as it arrived instead of Invalid Date", () => {
    expect(
      executionTimestamp(summary({ finished_at: "08:00 on the 18th" })),
    ).toBe("08:00 on the 18th");
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

  it("treats a cancellation in progress like a cancelled run", () => {
    expect(statusStyle("cancelling")).toBe(statusStyle("cancelled"));
  });

  it("shows every execution that has not finished as active", () => {
    expect(statusStyle("queued")).toBe(
      executionHistoryDrawerStyles.statusActive,
    );
    expect(statusStyle("running")).toBe(
      executionHistoryDrawerStyles.statusActive,
    );
  });

  it("never renders a missing badge rule", () => {
    for (const status of [
      "queued",
      "running",
      "cancelling",
      "cancelled",
      "succeeded",
      "failed",
    ] as const) {
      expect(statusStyle(status)).toBeDefined();
    }
  });
});

describe("errorMessage", () => {
  it("shows what the server said when there is an error to show", () => {
    expect(
      errorMessage(new Error("execution 41 vanished"), "Unknown error"),
    ).toBe("execution 41 vanished");
  });

  it("falls back when the failure is not an error object", () => {
    expect(errorMessage("execution 41 vanished", "Unknown error")).toBe(
      "Unknown error",
    );
    expect(errorMessage(undefined, "Unknown error")).toBe("Unknown error");
  });
});

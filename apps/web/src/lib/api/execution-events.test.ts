// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import type { RunExecutionEvent } from "./contract";
import { subscribeRunExecutionEvents } from "./workbench";

const validExecutionId = "00000000-0000-4000-8000-000000000001";
const validNodeRunId = "00000000-0000-4000-8000-000000000002";

class FakeEventSource extends EventTarget {
  static instances: FakeEventSource[] = [];

  readonly url: string;
  readonly close = vi.fn();

  constructor(url: string | URL) {
    super();
    this.url = String(url);
    FakeEventSource.instances.push(this);
  }
}

afterEach(() => {
  FakeEventSource.instances = [];
  vi.unstubAllGlobals();
});

describe("live execution event API", () => {
  it("subscribes to named events, validates JSON, and closes cleanly", () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const events: RunExecutionEvent[] = [];
    const errors: Array<Event | Error> = [];
    const onOpen = vi.fn();

    const subscription = subscribeRunExecutionEvents(
      "workspace-1",
      "execution/1",
      {
        onEvent: (event) => events.push(event),
        onError: (error) => errors.push(error),
        onOpen,
      },
    );
    const source = FakeEventSource.instances[0];
    expect(source?.url).toBe(
      "/api/v1/workspaces/workspace-1/executions/execution%2F1/events",
    );

    source?.dispatchEvent(new Event("open"));
    source?.dispatchEvent(
      new MessageEvent("node.progress", {
        data: JSON.stringify({
          kind: "node.progress",
          sequence: 7,
          execution_id: validExecutionId,
          occurred_at: "2026-07-19T12:00:00Z",
          node_path: ["module-1", "inner-1"],
          node_id: "inner-1",
          node_run_id: validNodeRunId,
          invocation_index: null,
          invocation_path: [2, 1],
          message: "Preparing the payload",
          current: 2,
          total: 5,
        }),
      }),
    );

    expect(onOpen).toHaveBeenCalledOnce();
    expect(events).toEqual([
      expect.objectContaining({
        kind: "node.progress",
        sequence: 7,
        node_path: ["module-1", "inner-1"],
        message: "Preparing the payload",
      }),
    ]);

    source?.dispatchEvent(
      new MessageEvent("node.status", {
        data: JSON.stringify({
          kind: "node.status",
          sequence: "not-a-number",
          execution_id: "execution/1",
          occurred_at: "2026-07-19T12:00:01Z",
        }),
      }),
    );
    source?.dispatchEvent(new Event("error"));
    expect(errors[0]).toBeInstanceOf(Error);
    expect(errors[1]).toBeInstanceOf(Event);

    subscription.close();
    subscription.close();
    expect(source?.close).toHaveBeenCalledOnce();

    source?.dispatchEvent(
      new MessageEvent("node.progress", {
        data: JSON.stringify({
          kind: "node.progress",
          sequence: 8,
          execution_id: validExecutionId,
          occurred_at: "2026-07-19T12:00:02Z",
          node_path: ["module-1"],
          node_id: "module-1",
          node_run_id: null,
          invocation_index: null,
          invocation_path: [],
          message: "Ignored after close",
          current: null,
          total: null,
        }),
      }),
    );
    expect(events).toHaveLength(1);
  });

  it("rejects invalid sequence, paths, counters, and node statuses", () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const events: RunExecutionEvent[] = [];
    const errors: Array<Event | Error> = [];
    subscribeRunExecutionEvents("workspace-1", "execution-1", {
      onEvent: (event) => events.push(event),
      onError: (error) => errors.push(error),
    });
    const source = FakeEventSource.instances[0];
    const progress = {
      kind: "node.progress",
      sequence: 1,
      execution_id: validExecutionId,
      occurred_at: "2026-07-19T12:00:00Z",
      node_path: ["node-1"],
      node_id: "node-1",
      node_run_id: null,
      invocation_index: null,
      invocation_path: [],
      message: "Working",
      current: 1,
      total: 2,
    };
    const invalidProgress = [
      { ...progress, sequence: 0 },
      { ...progress, execution_id: "not-a-uuid" },
      { ...progress, occurred_at: "not-a-date-time" },
      { ...progress, occurred_at: "2026-02-30T12:00:00Z" },
      { ...progress, node_path: [] },
      {
        ...progress,
        node_path: Array.from({ length: 65 }, (_, index) => `node-${index}`),
      },
      { ...progress, node_path: ["  "] },
      { ...progress, node_path: ["x".repeat(256)] },
      { ...progress, node_id: "  " },
      { ...progress, node_id: "x".repeat(256) },
      { ...progress, node_run_id: "not-a-uuid" },
      { ...progress, invocation_index: -1 },
      { ...progress, invocation_path: [-1] },
      {
        ...progress,
        invocation_path: Array.from({ length: 65 }, () => 0),
      },
      { ...progress, message: "   " },
      { ...progress, message: "x".repeat(1_001) },
      { ...progress, current: -1 },
      { ...progress, total: 1.5 },
      { ...progress, current: 3, total: 2 },
    ];
    for (const payload of invalidProgress) {
      source?.dispatchEvent(
        new MessageEvent("node.progress", {
          data: JSON.stringify(payload),
        }),
      );
    }
    source?.dispatchEvent(
      new MessageEvent("node.status", {
        data: JSON.stringify({
          ...progress,
          kind: "node.status",
          status: "queued",
        }),
      }),
    );
    for (const activeNodeId of ["  ", "x".repeat(256)]) {
      source?.dispatchEvent(
        new MessageEvent("execution.status", {
          data: JSON.stringify({
            kind: "execution.status",
            sequence: 2,
            execution_id: validExecutionId,
            occurred_at: "2026-07-19T12:00:01Z",
            status: "running",
            active_node_id: activeNodeId,
          }),
        }),
      );
    }

    expect(events).toEqual([]);
    expect(errors).toHaveLength(22);
    expect(errors.every((error) => error instanceof Error)).toBe(true);
  });

  it("reports construction failures so callers can continue with polling", () => {
    class FailingEventSource {
      constructor() {
        throw new Error("EventSource unavailable");
      }
    }
    vi.stubGlobal("EventSource", FailingEventSource);
    const onError = vi.fn();

    const subscription = subscribeRunExecutionEvents(
      "workspace-1",
      "execution-1",
      {
        onEvent: vi.fn(),
        onError,
      },
    );

    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({ message: "EventSource unavailable" }),
    );
    expect(() => subscription.close()).not.toThrow();
  });
});

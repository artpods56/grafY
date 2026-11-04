// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import type { RunNodeResult, RunPortArtifact, RunPortOutput } from "@/lib/api";
import type { WorkflowNodeProgressEntry } from "../types";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

import {
  NodeExecutionAppendix,
  type NodeExecutionAppendixProps,
} from "./NodeExecutionAppendix";

const mountedRoots = new Map<Root, HTMLElement>();

afterEach(async () => {
  for (const [root, container] of mountedRoots) {
    await React.act(async () => root.unmount());
    container.remove();
  }
  mountedRoots.clear();
});

function progressEntry(
  sequence: number,
  message: string,
  overrides: Partial<WorkflowNodeProgressEntry> = {},
): WorkflowNodeProgressEntry {
  return {
    sequence,
    message,
    current: null,
    total: null,
    sourceNodePath: [],
    invocationIndex: null,
    invocationPath: [],
    ...overrides,
  };
}

/** What a stored result says about one of its artifacts: a reference. */
function reference(id: string): RunPortArtifact {
  return {
    artifact_id: id,
    artifact_type: "scalar.text",
    schema_version: 1,
    content_hash: null,
  };
}

function output(port: string, artifactIds: readonly string[]): RunPortOutput {
  const artifacts = artifactIds.map(reference);
  const refs = artifacts.map((item) => ({
    artifact_id: item.artifact_id,
    artifact_type: item.artifact_type,
    schema_version: item.schema_version,
  }));
  return {
    port,
    kind: artifactIds.length > 1 ? "sequence" : "single",
    value:
      artifactIds.length > 1
        ? {
            artifact_type: "scalar.text",
            schema_version: 1,
            index_key: "order_index",
            ordered: true,
            item_refs: refs,
          }
        : (refs[0] ?? {
            artifact_id: `${port}-missing`,
            artifact_type: "scalar.text",
            schema_version: 1,
          }),
    artifacts,
  };
}

function storedResult(
  overrides: Partial<RunNodeResult> = {},
  artifactIds: readonly string[] = ["artifact-1"],
): RunNodeResult {
  return {
    node_id: "node-a",
    status: "succeeded",
    error: null,
    result_fingerprint: "9f2b61c0d4a7b5e8",
    created_at: "2026-07-20T08:00:02Z",
    outputs: artifactIds.length ? [output("result", artifactIds)] : [],
    ...overrides,
  };
}

async function renderAppendix(props: Partial<NodeExecutionAppendixProps> = {}) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.set(root, container);
  let currentProps: NodeExecutionAppendixProps = {
    nodeId: "node-a",
    nodeTitle: "Extract invoice",
    expanded: false,
    width: 320,
    execution: { status: "idle" },
    progress: null,
    run: null,
    historyContext: null,
    instanceState: null,
    ...props,
  };
  await React.act(async () =>
    root.render(<NodeExecutionAppendix {...currentProps} />),
  );
  const rerender = async (nextProps: Partial<NodeExecutionAppendixProps>) => {
    currentProps = { ...currentProps, ...nextProps };
    await React.act(async () =>
      root.render(<NodeExecutionAppendix {...currentProps} />),
    );
  };
  return { container, rerender };
}

function buttonWithText(
  container: HTMLElement,
  text: string,
): HTMLButtonElement {
  const button = [...container.querySelectorAll("button")].find((candidate) =>
    (candidate.textContent ?? "").trim().startsWith(text),
  );
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`Button ${text} was not rendered`);
  }
  return button;
}

describe("NodeExecutionAppendix", () => {
  it("stays off the canvas when a node has never run and never stored a result", async () => {
    const { container } = await renderAppendix({ expanded: true });

    expect(container.querySelector("aside")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("shows the derived instance state and the result its instance stored", async () => {
    const { container } = await renderAppendix({
      expanded: true,
      execution: { status: "succeeded" },
      instanceState: "stale",
      run: storedResult({}, ["artifact-1", "artifact-2"]),
    });

    expect(container.textContent).toContain("Result 2");
    await React.act(async () => {
      buttonWithText(container, "Result").click();
    });
    expect(container.textContent).toContain("Stale");
    expect(container.textContent).toContain(
      "The graph changed since this instance last computed.",
    );
    expect(container.textContent).toContain("2 artifacts");
    expect(container.textContent).toContain("9f2b61c0d4a7");
  });

  it("names a fresh instance by its stored result, not by a run", async () => {
    const { container } = await renderAppendix({
      instanceState: "fresh",
      run: storedResult(),
    });

    expect(container.textContent).toContain("Fresh result · 1 artifact");
  });

  it("keeps a failed instance's own error visible", async () => {
    const { container } = await renderAppendix({
      expanded: true,
      execution: { status: "failed", error: "the node said no" },
      instanceState: "failed",
      run: storedResult({ status: "failed", error: "the node said no" }, []),
    });

    expect(container.textContent).toContain("the node said no");
    await React.act(async () => {
      buttonWithText(container, "Result").click();
    });
    expect(container.textContent).toContain("Failed");
  });

  it("says so when an instance is queued but has nothing stored yet", async () => {
    const { container } = await renderAppendix({
      expanded: true,
      execution: { status: "queued" },
      instanceState: "queued",
    });

    await React.act(async () => {
      buttonWithText(container, "Result").click();
    });
    expect(container.textContent).toContain("Queued");
    expect(container.textContent).toContain(
      "No stored result for this instance.",
    );
  });

  it("derives a running instance from the canvas overlay alone", async () => {
    const { container } = await renderAppendix({
      expanded: true,
      execution: { status: "running" },
      progress: {
        entries: [progressEntry(1, "reading pages")],
        omittedCount: 0,
      },
    });

    await React.act(async () => {
      buttonWithText(container, "Result").click();
    });
    expect(container.textContent).toContain("Running");
    expect(container.textContent).toContain(
      "A computation for it is in flight.",
    );
  });

  it("reads the stored result of an idle node as stale, never as a history entry", async () => {
    const { container } = await renderAppendix({
      expanded: true,
      execution: { status: "idle" },
      run: storedResult(),
    });

    expect(container.textContent).toContain("Result 2");
    await React.act(async () => {
      buttonWithText(container, "Result").click();
    });
    expect(container.textContent).toContain("Stale");
    expect(container.textContent).not.toContain("History");
  });

  it("keeps the collapsed footprint on the latest event while a Run works", async () => {
    const { container } = await renderAppendix({
      execution: { status: "running" },
      progress: {
        entries: [progressEntry(3, "reading pages", { current: 2, total: 5 })],
        omittedCount: 0,
      },
    });

    expect(container.textContent).toContain("reading pages");
    expect(container.textContent).toContain("Extract invoice");
  });

  it("counts the omitted events a Run stopped publishing", async () => {
    const { container } = await renderAppendix({
      expanded: true,
      execution: { status: "running" },
      progress: {
        entries: [progressEntry(9, "reading pages", { current: 2, total: 5 })],
        omittedCount: 4,
      },
    });

    expect(container.textContent).toContain("4 earlier updates omitted");
    expect(container.textContent).toContain("2 / 5");
  });

  it("shows the error in the footprint when the node's own attempt failed", async () => {
    const { container } = await renderAppendix({
      execution: { status: "failed", error: "upstream gone" },
    });

    expect(container.textContent).toContain("upstream gone");
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
  });
});

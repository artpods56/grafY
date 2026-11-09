// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import type { components } from "@/lib/api/generated/grafy";
import { ARTIFACT_DROP_DATA_TYPE } from "../model/artifact-drop";

import {
  ArtifactChip,
  ConfirmationRow,
  ThinkingRow,
  ToolCallRow,
  ToolResultRow,
} from "./ToolEvents";

type S = components["schemas"];

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mountedRoots = new Set<ReturnType<typeof createRoot>>();

afterEach(async () => {
  await act(async () => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.clear();
  document.body.replaceChildren();
});

async function mount(element: React.ReactElement) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.add(root);
  await act(async () => root.render(element));
  return container;
}

function group(container: HTMLElement): Element {
  const element = container.querySelector('[role="group"]');
  if (!element) throw new Error("expected the row to carry role=group");
  return element;
}

/** The one line a row reads as when folded: its summary, or the row itself. */
function line(container: HTMLElement): string {
  return (
    (container.querySelector("summary") ?? group(container)).textContent ?? ""
  );
}

function chip(container: HTMLElement): Element {
  const element = container.querySelector('[draggable="true"]');
  if (!element) throw new Error("expected a draggable chip");
  return element;
}

const callRow = (
  args: S["ToolCallPayload"]["arguments"],
): S["ToolCallPayload"] => ({
  kind: "tool_call",
  call_id: "call-1",
  tool_id: "tool-1",
  tool_name: "run_query",
  arguments: args,
});

const okResult = (
  artifacts: readonly S["ToolResultArtifact"][],
): S["ToolResultPayload"] => ({
  kind: "tool_result",
  call_id: "call-1",
  tool_id: "tool-1",
  tool_name: "read_table",
  ok: true,
  fingerprint: "fp",
  artifacts,
  model_view: "one row",
  error: null,
});

const ref = (artifactId: string, artifactType: string): S["ArtifactRef"] => ({
  artifact_id: artifactId,
  artifact_type: artifactType,
  schema_version: 1,
});

it("shows the tool the model called and the arguments it gave", async () => {
  const container = await mount(
    <ToolCallRow payload={callRow({ query: "dear sir", limit: 3 })} />,
  );
  const row = group(container);
  expect(row.getAttribute("aria-label")).toBe("Tool call: run_query");
  expect(row.textContent).toContain("Called");
  expect(row.querySelector("code")?.textContent).toBe("run_query");
  expect(line(container)).toContain("query: dear sir");
  expect(line(container)).toContain("limit: 3");
});

it("keeps the whole call one click away, folded", async () => {
  const container = await mount(
    <ToolCallRow payload={callRow({ query: "x".repeat(200), limit: 3 })} />,
  );
  const details = container.querySelector("details");
  expect(details).not.toBeNull();
  expect(details?.open).toBe(false);
  expect(details?.querySelector("pre")?.textContent).toBe(
    JSON.stringify({ query: "x".repeat(200), limit: 3 }, null, 2),
  );
});

it("cuts a long argument to 60 characters and the whole summary to 160", async () => {
  const long = "x".repeat(200);
  const container = await mount(
    <ToolCallRow
      payload={callRow({
        query: long,
        note: long,
        where: long,
        reason: long,
      })}
    />,
  );
  const text = line(container);
  const at = text.indexOf(" with ");
  expect(at).toBeGreaterThan(-1);
  const summary = text.slice(at + " with ".length);
  // One pair is its `key: ` prefix plus the value, cut at 60 characters and marked.
  expect(summary.startsWith(`query: ${"x".repeat(53)}…`)).toBe(true);
  // No value survived un-cut: the longest run any pair can hold is 54.
  expect(summary).not.toContain("x".repeat(60));
  // The joined summary keeps its own cap: 160 characters plus the ellipsis.
  expect(summary.length).toBe(160 + 1);
  expect(summary.endsWith("…")).toBe(true);
});

it("leaves the separator out when the call took no arguments", async () => {
  const omitted = await mount(<ToolCallRow payload={callRow(undefined)} />);
  expect(group(omitted).textContent).toBe("Called run_query");
  const empty = await mount(<ToolCallRow payload={callRow({})} />);
  expect(group(empty).textContent).not.toContain(" with ");
});

it("shows a lone plain result as a draggable chip", async () => {
  const container = await mount(
    <ToolResultRow
      artifactTypes={null}
      payload={okResult([
        { port: "text", artifact: ref("art-1", "scalar.text") },
      ])}
    />,
  );
  const row = group(container);
  expect(row.getAttribute("aria-label")).toBe("Tool result: read_table");
  // What the model was shown is kept folded beside the chip.
  expect(row.querySelector("details summary")?.textContent).toBe(
    "What the model saw",
  );
  expect(row.querySelector("details pre")?.textContent).toBe("one row");
  const chips = Array.from(row.querySelectorAll('[draggable="true"]'));
  expect(chips.map((item) => item.getAttribute("aria-label"))).toEqual([
    "text: scalar.text@1",
  ]);
  expect(chips[0]?.getAttribute("title")).toBe(
    "Drag onto the canvas, an input or the Library",
  );
});

it("offers several results, or one with parts, through the picker", async () => {
  const several = await mount(
    <ToolResultRow
      artifactTypes={null}
      payload={okResult([
        { port: "text", artifact: ref("art-1", "scalar.text") },
        { port: "count", artifact: ref("art-2", "scalar.integer") },
      ])}
    />,
  );
  expect(group(several).querySelector("button")?.textContent).toContain(
    "2 results",
  );
  expect(group(several).querySelector('[draggable="true"]')).toBeNull();
  const table = await mount(
    <ToolResultRow
      artifactTypes={null}
      payload={okResult([
        { port: "blocks", artifact: ref("art-3", "table.data") },
      ])}
    />,
  );
  expect(group(table).querySelector("button")?.textContent).toContain(
    "1 result",
  );
});

it("names a sequence artifact with the sequence form", async () => {
  const container = await mount(
    <ArtifactChip
      artifactTypes={null}
      port="rows"
      artifact={{
        artifact_type: "scalar.text",
        schema_version: 2,
        item_refs: [ref("art-1", "scalar.text")],
        index_key: "order_index",
        ordered: true,
        sequence_id: "seq-1",
      }}
    />,
  );
  const chipRow = chip(container);
  expect(chipRow.textContent).toContain("Sequence<scalar.text@2>");
  expect(chipRow.getAttribute("aria-label")).toBe(
    "rows: Sequence<scalar.text@2>",
  );
});

it("says a call returned nothing when it produced no artifacts", async () => {
  const container = await mount(
    <ToolResultRow artifactTypes={null} payload={okResult([])} />,
  );
  expect(group(container).textContent).toContain("returned nothing");
});

it("shows why a failed call failed, or that no reason came", async () => {
  const failed = await mount(
    <ToolResultRow
      artifactTypes={null}
      payload={{
        ...okResult([]),
        ok: false,
        error: "the table has no such column",
      }}
    />,
  );
  const status = failed.querySelector('[role="status"]');
  expect(status?.textContent).toContain("failed: the table has no such column");

  const silent = await mount(
    <ToolResultRow
      artifactTypes={null}
      payload={{ ...okResult([]), ok: false, error: null }}
    />,
  );
  expect(silent.querySelector('[role="status"]')?.textContent).toContain(
    "no reason given",
  );
});

it("puts the artifact on a drag so the canvas and an input can take it", async () => {
  const container = await mount(
    <ArtifactChip
      artifactTypes={null}
      port="text"
      artifact={ref("art-1", "scalar.text")}
    />,
  );
  const dragged = chip(container);
  const dataTransfer = {
    data: {} as Record<string, string>,
    setData(type: string, value: string) {
      this.data[type] = value;
    },
    effectAllowed: "",
  };
  const event = new Event("dragstart", { bubbles: true });
  Object.assign(event, { dataTransfer });
  await act(async () => {
    dragged.dispatchEvent(event);
  });
  const raw = dataTransfer.data[ARTIFACT_DROP_DATA_TYPE];
  expect(typeof raw).toBe("string");
  const written = JSON.parse(raw ?? "") as {
    value: { artifact_id: string };
    shape: string;
  };
  expect(written.value.artifact_id).toBe("art-1");
  expect(written.shape).toBe("one");
  expect(dataTransfer.effectAllowed).toBe("copy");
});

it("asks a person to carry on, and only an enabled button answers", async () => {
  const onContinue = vi.fn();
  const payload: S["ConfirmationRequestedPayload"] = {
    kind: "confirmation_requested",
    limit: 10,
    tool_calls: 10,
  };

  const open = await mount(
    <ConfirmationRow
      payload={payload}
      onContinue={onContinue}
      disabled={false}
    />,
  );
  const row = group(open);
  expect(row.getAttribute("aria-label")).toBe("Confirmation needed");
  expect(row.textContent).toContain("This turn made 10 tool calls. Carry on?");
  await act(async () => row.querySelector("button")?.click());
  expect(onContinue).toHaveBeenCalledTimes(1);

  const held = await mount(
    <ConfirmationRow
      payload={payload}
      onContinue={onContinue}
      disabled={true}
    />,
  );
  const heldButton = held.querySelector("button");
  expect(heldButton?.disabled).toBe(true);
  await act(async () => heldButton?.click());
  expect(onContinue).toHaveBeenCalledTimes(1);
});

it("shows a thought folded, and says what it is without opening it", async () => {
  const container = await mount(
    <ThinkingRow
      payload={{ kind: "assistant_thinking", text: "  First I check.\n" }}
    />,
  );
  const details = container.querySelector("details");
  expect(details?.getAttribute("aria-label")).toBe("Thought");
  expect(details?.open).toBe(false);
  expect(container.querySelector("summary")?.textContent).toBe("Thought");
  expect(container.querySelector("pre")?.textContent).toBe("First I check.");
});

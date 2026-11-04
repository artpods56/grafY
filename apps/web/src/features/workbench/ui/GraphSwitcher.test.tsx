// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GraphDefinition, SavedGraphNode } from "@/lib/api";

import { GraphSwitcher } from "./GraphSwitcher";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mountedRoots = new Set<Root>();

afterEach(async () => {
  await act(async () => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.clear();
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

/** Mounts the switcher and keeps the root, so a test can render it again. */
async function mount(element: React.ReactElement) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.add(root);
  await act(async () => root.render(element));
  return { container, root };
}

function graph(
  id: string,
  name: string,
  nodes: readonly SavedGraphNode[] = [],
): GraphDefinition {
  return {
    id,
    name,
    document: {
      schema_version: 7,
      nodes,
      edges: [],
      origins: [],
      agents: [],
      presentation: { viewers: [], links: [], bindings: [], annotations: [] },
    },
  };
}

/** A node that places the sibling Graph `calleeId` on the canvas. */
function callNode(id: string, calleeId: string): SavedGraphNode {
  return {
    id,
    kind: "call",
    operator_id: calleeId,
    operator_version: 1,
    position: { x: 0, y: 0 },
    config: {},
    input_plugs: [],
    artifact_type_bindings: [],
  };
}

function tabsIn(container: HTMLElement) {
  return [...container.querySelectorAll<HTMLElement>('[role="tab"]')];
}

function buttonsIn(container: HTMLElement) {
  return [...container.querySelectorAll<HTMLButtonElement>("button")];
}

describe("GraphSwitcher", () => {
  it("renders one tab per Graph in the given order and selects only the open one", async () => {
    const { container } = await mount(
      <GraphSwitcher
        graphs={[
          graph("g1", "First"),
          graph("g2", "Second"),
          graph("g3", "Third"),
        ]}
        openGraphId="g2"
        canEdit
        onOpen={() => undefined}
        onAdd={() => undefined}
        onRename={() => undefined}
        onDelete={() => undefined}
      />,
    );

    const tabs = tabsIn(container);
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "First",
      "Second",
      "Third",
    ]);
    expect(tabs.map((tab) => tab.getAttribute("aria-selected"))).toEqual([
      "false",
      "true",
      "false",
    ]);
  });

  it("opens an unselected tab and ignores a click on the selected one", async () => {
    const onOpen = vi.fn();
    const { container } = await mount(
      <GraphSwitcher
        graphs={[graph("g1", "First"), graph("g2", "Second")]}
        openGraphId="g1"
        canEdit
        onOpen={onOpen}
        onAdd={() => undefined}
        onRename={() => undefined}
        onDelete={() => undefined}
      />,
    );

    const [first, second] = tabsIn(container);
    await act(async () => second?.click());
    expect(onOpen).toHaveBeenCalledOnce();
    expect(onOpen).toHaveBeenCalledWith("g2");

    await act(async () => first?.click());
    expect(onOpen).toHaveBeenCalledOnce();
  });

  it("adds a Graph, and disables all three actions when the person may not edit", async () => {
    const onAdd = vi.fn();
    const { container } = await mount(
      <GraphSwitcher
        graphs={[graph("g1", "First")]}
        openGraphId="g1"
        canEdit
        onOpen={() => undefined}
        onAdd={onAdd}
        onRename={() => undefined}
        onDelete={() => undefined}
      />,
    );

    const add = container.querySelector<HTMLButtonElement>(
      '[aria-label="Add Graph"]',
    );
    await act(async () => add?.click());
    expect(onAdd).toHaveBeenCalledOnce();
    expect(add?.disabled).toBe(false);

    const { container: readOnly } = await mount(
      <GraphSwitcher
        graphs={[graph("g1", "First")]}
        openGraphId="g1"
        canEdit={false}
        onOpen={() => undefined}
        onAdd={() => undefined}
        onRename={() => undefined}
        onDelete={() => undefined}
      />,
    );
    for (const label of ["Add Graph", "Rename Graph", "Delete Graph"]) {
      expect(
        readOnly.querySelector<HTMLButtonElement>(`[aria-label="${label}"]`)
          ?.disabled,
        label,
      ).toBe(true);
    }
  });

  it("renames only when the answer is a new non-blank name", async () => {
    const onRename = vi.fn();
    const prompt = vi.spyOn(window, "prompt").mockReturnValue(" New name ");
    const { container } = await mount(
      <GraphSwitcher
        graphs={[graph("g1", "First")]}
        openGraphId="g1"
        canEdit
        onOpen={() => undefined}
        onAdd={() => undefined}
        onRename={onRename}
        onDelete={() => undefined}
      />,
    );
    const rename = container.querySelector<HTMLButtonElement>(
      '[aria-label="Rename Graph"]',
    );

    await act(async () => rename?.click());
    expect(prompt).toHaveBeenCalledWith("Rename Graph", "First");
    expect(onRename).toHaveBeenCalledOnce();
    expect(onRename).toHaveBeenCalledWith("g1", "New name");

    // Cancelled, unchanged, and blank answers all leave the Graph alone.
    for (const answer of [null, "First", "   "]) {
      prompt.mockReturnValue(answer);
      await act(async () => rename?.click());
    }
    expect(onRename).toHaveBeenCalledOnce();
  });

  it("asks before deleting an uncalled Graph and obeys the answer", async () => {
    const onDelete = vi.fn();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { container } = await mount(
      <GraphSwitcher
        graphs={[graph("g1", "First")]}
        openGraphId="g1"
        canEdit
        onOpen={() => undefined}
        onAdd={() => undefined}
        onRename={() => undefined}
        onDelete={onDelete}
      />,
    );
    const remove = container.querySelector<HTMLButtonElement>(
      '[aria-label="Delete Graph"]',
    );

    await act(async () => remove?.click());
    expect(confirm).toHaveBeenCalledWith(
      "Delete “First”? You can bring it back by restoring an earlier checkpoint.",
    );
    expect(onDelete).toHaveBeenCalledOnce();
    expect(onDelete).toHaveBeenCalledWith("g1");

    confirm.mockReturnValue(false);
    await act(async () => remove?.click());
    expect(onDelete).toHaveBeenCalledOnce();
  });

  it("refuses to delete a Graph another Graph calls, without asking", async () => {
    const onDelete = vi.fn();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { container } = await mount(
      <GraphSwitcher
        graphs={[
          graph("g1", "Caller", [callNode("c1", "g2")]),
          graph("g2", "Callee"),
        ]}
        openGraphId="g2"
        canEdit
        onOpen={() => undefined}
        onAdd={() => undefined}
        onRename={() => undefined}
        onDelete={onDelete}
      />,
    );

    const remove = container.querySelector<HTMLButtonElement>(
      '[aria-label="Delete Graph"]',
    );
    await act(async () => remove?.click());

    expect(onDelete).not.toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
    const alert = container.querySelector<HTMLElement>('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(alert?.textContent).toContain("is still called from");
    expect(alert?.textContent).toContain("“Caller”");
  });

  it("drops the refusal when another Graph is opened and when it is dismissed", async () => {
    const graphs = [
      graph("g1", "Caller", [callNode("c1", "g2")]),
      graph("g2", "Callee"),
    ];
    const switcher = (openGraphId: string) => (
      <GraphSwitcher
        graphs={graphs}
        openGraphId={openGraphId}
        canEdit
        onOpen={() => undefined}
        onAdd={() => undefined}
        onRename={() => undefined}
        onDelete={() => undefined}
      />
    );
    const { container, root } = await mount(switcher("g2"));
    const remove = container.querySelector<HTMLButtonElement>(
      '[aria-label="Delete Graph"]',
    );
    await act(async () => remove?.click());
    expect(container.querySelector('[role="alert"]')).not.toBeNull();

    await act(async () => root.render(switcher("g1")));
    expect(container.querySelector('[role="alert"]')).toBeNull();

    await act(async () => root.render(switcher("g2")));
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
    const dismiss = container.querySelector<HTMLElement>(
      '[role="alert"] [aria-label="Dismiss"]',
    );
    await act(async () => dismiss?.click());
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it("disables Rename and Delete with no Graph open, and selects no tab", async () => {
    const { container } = await mount(
      <GraphSwitcher
        graphs={[graph("g1", "First"), graph("g2", "Second")]}
        openGraphId={null}
        canEdit
        onOpen={() => undefined}
        onAdd={() => undefined}
        onRename={() => undefined}
        onDelete={() => undefined}
      />,
    );

    expect(
      container.querySelector<HTMLButtonElement>('[aria-label="Add Graph"]')
        ?.disabled,
    ).toBe(false);
    expect(
      container.querySelector<HTMLButtonElement>('[aria-label="Rename Graph"]')
        ?.disabled,
    ).toBe(true);
    expect(
      container.querySelector<HTMLButtonElement>('[aria-label="Delete Graph"]')
        ?.disabled,
    ).toBe(true);
    expect(
      tabsIn(container).map((tab) => tab.getAttribute("aria-selected")),
    ).toEqual(["false", "false"]);
  });

  it("still renders the bar with no Graphs at all", async () => {
    const onAdd = vi.fn();
    const { container } = await mount(
      <GraphSwitcher
        graphs={[]}
        openGraphId={null}
        canEdit
        onOpen={() => undefined}
        onAdd={onAdd}
        onRename={() => undefined}
        onDelete={() => undefined}
      />,
    );

    expect(tabsIn(container)).toEqual([]);
    expect(
      container.querySelector(
        '[role="tablist"][aria-label="Graphs in this Project"]',
      ),
    ).not.toBeNull();
    expect(
      container.querySelector<HTMLButtonElement>('[aria-label="Add Graph"]')
        ?.disabled,
    ).toBe(false);
  });

  it("offers to open the selected call, and never disables looking", async () => {
    const onOpenCall = vi.fn();
    const selectedCall = {
      nodeId: "call-1",
      calleeGraphId: "callee-id",
      calleeName: "Callee",
    };
    const { container } = await mount(
      <GraphSwitcher
        graphs={[graph("g1", "Caller"), graph("callee-id", "Callee")]}
        openGraphId="g1"
        canEdit
        onOpen={() => undefined}
        onAdd={() => undefined}
        onRename={() => undefined}
        onDelete={() => undefined}
        selectedCall={selectedCall}
        onOpenCall={onOpenCall}
      />,
    );

    const openCall = container.querySelector<HTMLButtonElement>(
      '[aria-label="Open call to “Callee”"]',
    );
    expect(openCall).not.toBeNull();
    // It sits in the bar, last, right after Delete.
    const bar = openCall?.closest("div") as HTMLElement | null;
    expect(bar?.lastElementChild).toBe(openCall);
    expect(
      bar?.querySelector('[aria-label="Delete Graph"]')?.nextElementSibling,
    ).toBe(openCall);

    await act(async () => openCall?.click());
    expect(onOpenCall).toHaveBeenCalledOnce();
    expect(onOpenCall).toHaveBeenCalledWith("call-1", "callee-id");

    // A read-only room may not edit, but it can still look into the callee.
    const { container: readOnly } = await mount(
      <GraphSwitcher
        graphs={[graph("g1", "Caller"), graph("callee-id", "Callee")]}
        openGraphId="g1"
        canEdit={false}
        onOpen={() => undefined}
        onAdd={() => undefined}
        onRename={() => undefined}
        onDelete={() => undefined}
        selectedCall={selectedCall}
        onOpenCall={onOpenCall}
      />,
    );
    expect(
      readOnly.querySelector<HTMLButtonElement>(
        '[aria-label="Open call to “Callee”"]',
      )?.disabled,
    ).toBe(false);
  });

  it("offers no Open call without a selected call, or without a way to open one", async () => {
    const { container } = await mount(
      <GraphSwitcher
        graphs={[graph("g1", "Caller"), graph("callee-id", "Callee")]}
        openGraphId="g1"
        canEdit
        onOpen={() => undefined}
        onAdd={() => undefined}
        onRename={() => undefined}
        onDelete={() => undefined}
        onOpenCall={() => undefined}
      />,
    );
    expect(
      container.querySelectorAll('[aria-label^="Open call to"]').length,
    ).toBe(0);

    const { container: noHandler } = await mount(
      <GraphSwitcher
        graphs={[graph("g1", "Caller"), graph("callee-id", "Callee")]}
        openGraphId="g1"
        canEdit
        onOpen={() => undefined}
        onAdd={() => undefined}
        onRename={() => undefined}
        onDelete={() => undefined}
        selectedCall={{
          nodeId: "call-1",
          calleeGraphId: "callee-id",
          calleeName: "Callee",
        }}
      />,
    );
    expect(
      noHandler.querySelectorAll('[aria-label^="Open call to"]').length,
    ).toBe(0);
  });

  it("goes back to the caller a Graph was opened from", async () => {
    const onBackFromCall = vi.fn();
    const { container } = await mount(
      <GraphSwitcher
        graphs={[graph("main", "Main"), graph("clean", "Clean")]}
        openGraphId="clean"
        canEdit
        onOpen={() => undefined}
        onAdd={() => undefined}
        onRename={() => undefined}
        onDelete={() => undefined}
        callTrail={[{ graphId: "main", nodeId: "call-1", name: "Main" }]}
        onBackFromCall={onBackFromCall}
      />,
    );

    const back = buttonsIn(container).find((button) =>
      button.textContent?.includes("Back to"),
    );
    expect(back?.textContent).toBe("Back to “Main”");
    // One caller needs no trail line: the button already names it.
    expect(container.textContent).not.toContain("›");

    await act(async () => back?.click());
    expect(onBackFromCall).toHaveBeenCalledOnce();
  });

  it("names the innermost caller and spells out a trail of two or more", async () => {
    const onBackFromCall = vi.fn();
    const { container } = await mount(
      <GraphSwitcher
        graphs={[graph("clean", "Clean")]}
        openGraphId="clean"
        canEdit
        onOpen={() => undefined}
        onAdd={() => undefined}
        onRename={() => undefined}
        onDelete={() => undefined}
        callTrail={[
          { graphId: "main", nodeId: "call-1", name: "Main" },
          { graphId: "report", nodeId: "call-2", name: "Report" },
        ]}
        onBackFromCall={onBackFromCall}
      />,
    );

    const back = buttonsIn(container).find((button) =>
      button.textContent?.includes("Back to"),
    );
    expect(back?.textContent).toBe("Back to “Report”");
    expect(container.textContent).toContain("Main › Report › Clean");

    await act(async () => back?.click());
    expect(onBackFromCall).toHaveBeenCalledOnce();
  });

  it("shows no Back row when the Graph was opened directly", async () => {
    const openedDirectly = await mount(
      <GraphSwitcher
        graphs={[graph("clean", "Clean")]}
        openGraphId="clean"
        canEdit
        onOpen={() => undefined}
        onAdd={() => undefined}
        onRename={() => undefined}
        onDelete={() => undefined}
        onBackFromCall={() => undefined}
      />,
    );
    const withEmptyTrail = await mount(
      <GraphSwitcher
        graphs={[graph("clean", "Clean")]}
        openGraphId="clean"
        canEdit
        onOpen={() => undefined}
        onAdd={() => undefined}
        onRename={() => undefined}
        onDelete={() => undefined}
        callTrail={[]}
        onBackFromCall={() => undefined}
      />,
    );

    for (const { container } of [openedDirectly, withEmptyTrail]) {
      expect(container.textContent).not.toContain("Back to");
      expect(
        buttonsIn(container).some((button) =>
          button.textContent?.includes("Back to"),
        ),
      ).toBe(false);
    }
  });
});

// @vitest-environment jsdom

import { act } from "react";
import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ArtifactViewerBinding } from "../artifact-interactions";
import { selectionLinkCapability } from "./selection-links-reducer";
import {
  useSelectionLinks,
  type UseSelectionLinksOptions,
} from "./useSelectionLinks";

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const tableCard = {
  id: "table",
  title: "Table",
  capability: selectionLinkCapability("table"),
};

const mapCard = {
  id: "map",
  title: "Map",
  capability: selectionLinkCapability("map"),
};

const bindingId = "link-table-map";

const binding: ArtifactViewerBinding = {
  id: bindingId,
  sourceViewerId: "table",
  targetViewerId: "map",
  mappings: [{ sourceField: "column_3", targetField: "centre" }],
  effects: ["focus"],
  emptySelection: "show_all",
};

describe("useSelectionLinks", () => {
  const roots: Root[] = [];

  afterEach(() => {
    for (const root of roots.splice(0)) {
      act(() => {
        root.unmount();
      });
    }
  });

  function mount(options: UseSelectionLinksOptions) {
    let latest: ReturnType<typeof useSelectionLinks> | null = null;

    function Harness(props: UseSelectionLinksOptions) {
      latest = useSelectionLinks(props);
      return null;
    }

    const root = createRoot(document.createElement("div"));
    roots.push(root);
    act(() => {
      root.render(<Harness {...options} />);
    });

    return {
      get current() {
        if (!latest) throw new Error("harness did not render");
        return latest;
      },
      rerender(next: UseSelectionLinksOptions) {
        act(() => {
          root.render(<Harness {...next} />);
        });
      },
    };
  }

  function options(
    overrides: Partial<UseSelectionLinksOptions> = {},
  ): UseSelectionLinksOptions {
    return {
      cards: [tableCard, mapCard],
      bindings: [binding],
      editable: true,
      saveBinding: vi.fn(),
      removeBinding: vi.fn(),
      onActivityChange: vi.fn(),
      ...overrides,
    };
  }

  it("carries a table selection onto the linked map", () => {
    const view = mount(options());
    const table = view.current.context.interactionFor("table");
    const map = view.current.context.interactionFor("map");

    expect(table).toBeDefined();
    expect(map).toBeDefined();
    expect(view.current.context.interactionFor("unknown")).toBeUndefined();

    act(() => {
      table?.onSelectionChange({
        kind: "key-selection",
        items: [{ values: { column_3: "м. Круглое" }, sourceIndex: 3 }],
      });
    });

    expect(view.current.context.interactionFor("map")?.incoming).toEqual([
      {
        bindingId,
        effects: ["focus"],
        sourceSelectionCount: 1,
        rows: [{ centre: "м. Круглое" }],
      },
    ]);
    expect(
      view.current.context.interactionFor("table")?.outgoingFields,
    ).toEqual(["column_3"]);
    expect(view.current.context.lines).toEqual([
      { id: bindingId, sourceCardId: "table", targetCardId: "map" },
    ]);
    expect(
      view.current.context.menuItemsFor("table").map((item) => item.label),
    ).toEqual(["Link selection…", "Edit link to “Map”"]);
    expect(
      view.current.context.menuItemsFor("map").map((item) => item.label),
    ).toContain("Edit link from “Table”");
  });

  it("saves a new link started from the card menu", () => {
    const saveBinding = vi.fn();
    const view = mount(options({ saveBinding }));
    const start = view.current.context
      .menuItemsFor("table")
      .find((item) => item.id === "selection-link-new");

    act(() => {
      start?.onSelect();
      view.current.dispatch({
        type: "mapping_changed",
        index: 0,
        mapping: { sourceField: "column_3", targetField: "centre" },
      });
      view.current.dispatch({
        type: "save_requested",
        newBindingId: "link-new",
      });
    });

    expect(saveBinding).toHaveBeenCalledTimes(1);
    expect(saveBinding.mock.calls[0]?.[0]).toMatchObject({
      sourceViewerId: "table",
    });
  });

  it("hides link actions when read-only and drops a line when a card leaves", () => {
    const props = options();
    const view = mount(props);

    view.rerender({ ...props, editable: false });
    expect(view.current.context.menuItemsFor("table")).toEqual([]);
    expect(view.current.context.menuItemsFor("map")).toEqual([]);

    view.rerender({ ...props, editable: false, cards: [tableCard] });
    expect(view.current.context.lines).toEqual([]);
  });
});

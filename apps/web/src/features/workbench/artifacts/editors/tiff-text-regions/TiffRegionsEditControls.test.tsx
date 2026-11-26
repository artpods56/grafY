// @vitest-environment jsdom

/**
 * The floating chrome is tested where it is used: mounted, on a real reducer state,
 * with real clicks and real keystrokes. What matters about it is which action a
 * gesture produces, which control is disabled while the host is writing, and which
 * keys it refuses to answer — none of which a static string can show.
 */

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createTiffTextRegionsEditorState,
  tiffTextRegionsEditorReducer,
  type TiffTextRegionsEditorAction,
  type TiffTextRegionsHistoryEntry,
  type TiffTextRegionsEditorState,
} from "./tiff-text-regions-editor-reducer";
import {
  TiffRegionsEditControls,
  type TiffRegionsEditControlsProps,
} from "./TiffRegionsEditControls";
import type {
  EditableTextRegion,
  PixelPoint,
  TiffTextRegionsPayload,
} from "./types";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const roots: ReturnType<typeof createRoot>[] = [];

/**
 * Drop every mounted editor.
 *
 * Shortcuts live on the document, so two editors on the page both answer the same
 * keystroke — a test that wants to know what one of them did unmounts the others.
 */
function clear(): void {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  document.body.replaceChildren();
}

afterEach(clear);

const BOX: readonly PixelPoint[] = [
  [10, 10],
  [60, 10],
  [60, 26],
  [10, 26],
];

const TRIANGLE: readonly PixelPoint[] = [
  [0, 0],
  [30, 0],
  [15, 20],
];

function region(
  text: string | null,
  polygon: readonly PixelPoint[] = BOX,
  extra: Readonly<Record<string, unknown>> = {},
): EditableTextRegion {
  return {
    polygon,
    reading: text === null ? null : { text, confidence: 0.94 },
    readingField: "reading",
    extra,
    readingExtra: text === null ? {} : { model: "paddleocr" },
  };
}

function payload(
  regions: readonly EditableTextRegion[],
): TiffTextRegionsPayload {
  return {
    source: {
      artifact_id: "4a1f",
      artifact_type: "file.tiff",
      schema_version: 1,
    },
    sourceExtra: {},
    window: { page: 0, col: 0, row: 0, width: 4_000, height: 3_000 },
    windowExtra: {},
    regions,
    extra: {},
  };
}

function state(
  overrides: Partial<TiffTextRegionsEditorState> = {},
): TiffTextRegionsEditorState {
  const base = createTiffTextRegionsEditorState(
    payload([region("Invoice 12"), region("Total 44.00")]),
  );
  return {
    ...base,
    selectedRegions: overrides.selection ? [overrides.selection.region] : [],
    ...overrides,
  };
}

/** A state already carrying one edit, so undo has something to give back. */
function dirtyWithHistory(
  overrides: Partial<TiffTextRegionsEditorState> = {},
): TiffTextRegionsEditorState {
  const base = state();
  const entry: TiffTextRegionsHistoryEntry = {
    payload: base.payload,
    selection: null,
    selectedRegions: [],
  };
  return state({
    isDirty: true,
    selection: { region: 1, vertex: null },
    past: [entry],
    ...overrides,
  });
}

/** Every region shift-picked at once, which is what the bulk controls act on. */
function multiSelected(
  count: number,
  overrides: Partial<TiffTextRegionsEditorState> = {},
): TiffTextRegionsEditorState {
  const regions = Array.from({ length: count }, (_, index) =>
    region(`Region ${index + 1}`),
  );
  const base = createTiffTextRegionsEditorState(payload(regions));
  return {
    ...base,
    selection: { region: 0, vertex: null },
    selectedRegions: regions.map((_, index) => index),
    ...overrides,
  };
}

/** What the editor actually asked for, run through the real reducer. */
function applied(
  from: TiffTextRegionsEditorState,
  actions: readonly TiffTextRegionsEditorAction[],
): TiffTextRegionsEditorState {
  return actions.reduce(tiffTextRegionsEditorReducer, from);
}

type Mounted = {
  container: HTMLElement;
  actions: TiffTextRegionsEditorAction[];
  dispatch: (action: TiffTextRegionsEditorAction) => void;
  onSave: ReturnType<typeof vi.fn>;
  onClose: ReturnType<typeof vi.fn>;
  rerender: (props: Partial<TiffRegionsEditControlsProps>) => void;
};

function mount(props: Partial<TiffRegionsEditControlsProps> = {}): Mounted {
  const actions: TiffTextRegionsEditorAction[] = [];
  const dispatch = vi.fn((action: TiffTextRegionsEditorAction) => {
    actions.push(action);
  });
  const onSave = vi.fn();
  const onClose = vi.fn();
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  const draw = (props: Partial<TiffRegionsEditControlsProps>) => {
    React.act(() => {
      root.render(
        <TiffRegionsEditControls
          state={state()}
          dispatch={dispatch}
          inModal
          shortcutsActive
          saving={false}
          error={null}
          onSave={onSave}
          onClose={onClose}
          {...props}
        />,
      );
    });
  };
  draw(props);
  return { container, actions, dispatch, onSave, onClose, rerender: draw };
}

function button(container: HTMLElement, name: string): HTMLButtonElement {
  const wanted = name.trim();
  const found = Array.from(container.querySelectorAll("button")).find(
    (element) =>
      element.getAttribute("aria-label") === wanted ||
      (element.textContent ?? "").trim() === wanted,
  );
  if (!found) throw new Error(`no control labelled "${name}"`);
  return found;
}

function click(element: HTMLElement): void {
  React.act(() => {
    element.click();
  });
}

function text(container: HTMLElement, name: string): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>(
    `input[aria-label="${name}"]`,
  );
  if (!input) throw new Error(`no field labelled "${name}"`);
  return input;
}

/** React tracks its own value, so a typed character goes in through the setter. */
function type(input: HTMLInputElement, value: string): void {
  const setValue = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  if (!setValue) throw new Error("no value setter on HTMLInputElement");
  React.act(() => {
    setValue.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function key(init: KeyboardEventInit, target: EventTarget = document): boolean {
  // `cancelable` is off by default, and a non-cancelable event shrugs off
  // `preventDefault`, which is the half of the contract being asserted here.
  const event = new KeyboardEvent("keydown", {
    bubbles: true,
    cancelable: true,
    ...init,
  });
  React.act(() => {
    target.dispatchEvent(event);
  });
  // `dispatchEvent` is the only place the prevented flag is readable afterwards.
  return event.defaultPrevented;
}

function pointerDown(element: HTMLElement): void {
  React.act(() => {
    element.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, cancelable: true }),
    );
  });
}

function textOf(container: HTMLElement): string {
  return container.textContent ?? "";
}

function classes(element: HTMLElement): string[] {
  return element.className.split(/\s+/);
}

describe("the tool rail", () => {
  it("offers the tools a person needs without a list of regions", () => {
    const { container } = mount();
    const labels = Array.from(container.querySelectorAll("button")).map(
      (element) => element.getAttribute("aria-label"),
    );
    expect(labels).toEqual([
      "Select region (Shift+click for multiple)",
      "Draw box",
      "Draw polygon",
      "Erase regions (E)",
      "Merge selected regions (M)",
      "Undo",
      "Redo",
      "Delete selected region",
      "Save new version",
      "Close editor",
    ]);
  });

  it("shows which tool is in hand and takes the next click", () => {
    const { container, actions } = mount({
      state: state({ mode: "draw_box" }),
    });
    expect(button(container, "Draw box").getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(
      button(
        container,
        "Select region (Shift+click for multiple)",
      ).getAttribute("aria-pressed"),
    ).toBe("false");

    click(button(container, "Draw polygon"));
    expect(actions).toEqual([{ type: "set_mode", mode: "draw_polygon" }]);
  });

  it("hands over the eraser, and says which of them is holding it", () => {
    const { container, actions } = mount();
    click(button(container, "Erase regions (E)"));
    expect(actions).toEqual([{ type: "set_mode", mode: "eraser" }]);

    const armed = mount({ state: state({ mode: "eraser" }) });
    expect(
      button(armed.container, "Erase regions (E)").getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      button(
        armed.container,
        "Select region (Shift+click for multiple)",
      ).getAttribute("aria-pressed"),
    ).toBe("false");
  });

  it("only offers to merge once more than one region is in hand", () => {
    const alone = mount();
    expect(button(alone.container, "Merge selected regions (M)").disabled).toBe(
      true,
    );

    // One region is nothing to merge: the tool would have to invent a partner.
    const single = mount({
      state: state({ selection: { region: 0, vertex: null } }),
    });
    expect(
      button(single.container, "Merge selected regions (M)").disabled,
    ).toBe(true);

    const pair = mount({ state: multiSelected(2) });
    const merge = button(pair.container, "Merge selected regions (M)");
    expect(merge.disabled).toBe(false);
    click(merge);
    expect(pair.actions).toEqual([{ type: "merge_selected_regions" }]);
  });

  it("counts what Delete is about to take", () => {
    const single = mount({
      state: state({ selection: { region: 1, vertex: null } }),
    });
    expect(button(single.container, "Delete selected region").disabled).toBe(
      false,
    );

    const three = mount({ state: multiSelected(3) });
    click(button(three.container, "Delete 3 selected regions"));
    expect(three.actions).toEqual([{ type: "delete_selected_region" }]);
  });

  it("shrinks its controls on the inline card and grows them in the modal", () => {
    const card = mount({ inModal: false });
    expect(classes(button(card.container, "Draw box"))).toContain("2xs");
    const modal = mount({ inModal: true });
    const drawn = classes(button(modal.container, "Draw box"));
    expect(drawn).toContain("xs");
    expect(drawn).not.toContain("2xs");
  });

  it("waits for something to act on before offering history and delete", () => {
    const empty = mount();
    expect(button(empty.container, "Undo").disabled).toBe(true);
    expect(button(empty.container, "Redo").disabled).toBe(true);
    expect(button(empty.container, "Delete selected region").disabled).toBe(
      true,
    );

    const full = mount({
      state: dirtyWithHistory({
        future: [
          { payload: state().payload, selection: null, selectedRegions: [] },
        ],
      }),
    });
    expect(button(full.container, "Undo").disabled).toBe(false);
    expect(button(full.container, "Redo").disabled).toBe(false);
    expect(button(full.container, "Delete selected region").disabled).toBe(
      false,
    );

    click(button(full.container, "Undo"));
    click(button(full.container, "Redo"));
    click(button(full.container, "Delete selected region"));
    expect(full.actions).toEqual([
      { type: "undo" },
      { type: "redo" },
      { type: "delete_selected_region" },
    ]);
  });

  it("locks the tools and renames Save while the host writes", () => {
    const { container, onSave } = mount({
      state: dirtyWithHistory(),
      saving: true,
    });
    for (const label of [
      "Select region (Shift+click for multiple)",
      "Draw box",
      "Draw polygon",
      "Erase regions (E)",
      "Merge selected regions (M)",
      "Undo",
      "Redo",
      "Delete selected region",
      "Close editor",
    ]) {
      expect(button(container, label).disabled, label).toBe(true);
    }
    // The save button says what is happening, and cannot be pressed into starting
    // a second write.
    expect(button(container, "Saving…").disabled).toBe(true);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("saves only what has actually changed", () => {
    const clean = mount();
    expect(button(clean.container, "Save new version").disabled).toBe(true);
    click(button(clean.container, "Save new version"));
    expect(clean.onSave).not.toHaveBeenCalled();

    const dirty = mount({ state: dirtyWithHistory() });
    expect(button(dirty.container, "Save new version").disabled).toBe(false);
    click(button(dirty.container, "Save new version"));
    expect(dirty.onSave).toHaveBeenCalledTimes(1);
  });

  it("closes straight away when there is nothing to lose", () => {
    const { container, onClose } = mount();
    click(button(container, "Close editor"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(textOf(container)).not.toContain("discard");
  });

  it("asks before throwing away unsaved edits, and only goes when told", () => {
    const { container, onClose } = mount({ state: dirtyWithHistory() });
    click(button(container, "Close editor"));
    expect(onClose).not.toHaveBeenCalled();
    expect(textOf(container)).toContain("Unsaved edits — discard?");

    click(button(container, "Keep editing"));
    expect(onClose).not.toHaveBeenCalled();
    expect(textOf(container)).not.toContain("Unsaved edits — discard?");

    click(button(container, "Close editor"));
    click(button(container, "Discard"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("gives the prompt back when the edits it warned about are gone", () => {
    const { container, rerender } = mount({ state: dirtyWithHistory() });
    click(button(container, "Close editor"));
    expect(textOf(container)).toContain("Unsaved edits — discard?");

    // The undo landed back on the saved bytes, so there is nothing left to throw
    // away and the warning is a lie.
    rerender({ state: state() });
    expect(textOf(container)).not.toContain("Unsaved edits — discard?");
  });

  it("never lets a click on a tool start a card drag or a pan", () => {
    const { container } = mount();
    // React's own listener sits on the root container, so the witness has to sit
    // above it: `stopPropagation` stops the climb, not the other handlers next door.
    const reached = vi.fn();
    document.body.addEventListener("pointerdown", reached);
    pointerDown(button(container, "Draw box"));
    expect(reached).not.toHaveBeenCalled();

    const rail = container.querySelector('[role="toolbar"]');
    expect(rail?.getAttribute("class")).toContain("nodrag");
    expect(rail?.getAttribute("class")).toContain("nopan");
  });
});

describe("the reading bar", () => {
  it("is not drawn when nothing has to be said", () => {
    const { container } = mount();
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("reports a failed write as an alert", () => {
    const { container } = mount({ error: "This scan changed under you." });
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("This scan changed under you.");
  });

  it("reads the selected region and edits it as it is typed", () => {
    const { container, actions } = mount({
      state: state({ selection: { region: 1, vertex: null } }),
    });
    expect(textOf(container)).toContain("#2");
    const input = text(container, "Region OCR text");
    expect(input.value).toBe("Total 44.00");
    expect(textOf(container)).toContain("94%");

    type(input, "Total 44.00 EUR");
    expect(actions).toEqual([
      {
        type: "set_reading_text",
        index: 1,
        text: "Total 44.00 EUR",
      },
    ]);
  });

  it("offers to clear words that are there, and not words that are not", () => {
    const written = mount({
      state: state({ selection: { region: 0, vertex: null } }),
    });
    click(button(written.container, "Clear text"));
    expect(written.actions).toEqual([{ type: "clear_reading", index: 0 }]);

    const blank = mount({
      state: state({
        payload: payload([region(null)]),
        selection: { region: 0, vertex: null },
      }),
    });
    expect(text(blank.container, "Region OCR text").value).toBe("");
    expect(
      Array.from(blank.container.querySelectorAll("button")).some(
        (element) => element.getAttribute("aria-label") === "Clear text",
      ),
    ).toBe(false);
    // Nothing scored a region with no words in it, so nothing claims a percentage.
    expect(textOf(blank.container)).not.toContain("%");
  });

  it("reports the score a detector wrote when no recognizer confidence came with it", () => {
    const { container } = mount({
      state: state({
        payload: payload([
          {
            polygon: BOX,
            reading: null,
            readingField: "text",
            extra: { score: 0.5 },
            readingExtra: {},
          },
        ]),
        selection: { region: 0, vertex: null },
      }),
    });
    expect(textOf(container)).toContain("50%");
  });

  it("waits for the write like every other control", () => {
    const { container } = mount({
      state: state({ selection: { region: 0, vertex: null } }),
      saving: true,
    });
    expect(text(container, "Region OCR text").disabled).toBe(true);
    expect(button(container, "Clear text").disabled).toBe(true);
  });

  it("keeps editing keys to itself and gives Escape back to the field", () => {
    const { container, actions } = mount({
      state: state({ selection: { region: 0, vertex: null } }),
    });
    const input = text(container, "Region OCR text");
    input.focus();

    expect(key({ key: "z", metaKey: true }, input)).toBe(false);
    expect(key({ key: "Backspace" }, input)).toBe(false);
    expect(actions).toEqual([]);

    key({ key: "Escape" }, input);
    expect(document.activeElement).not.toBe(input);
    // The pill answered Escape, so nothing further — not even the modal around it —
    // is told the key was pressed.
    expect(actions).toEqual([]);
  });
});

describe("the multi-selection bar", () => {
  it("trades one region's transcription for the verbs that mean these", () => {
    const { container, actions } = mount({ state: multiSelected(3) });
    expect(textOf(container)).toContain("3 regions selected");
    // Three OCR fields would be three lies about one box: the count is the report,
    // and the two verbs below it are the point of having picked all three.
    expect(
      container.querySelector('input[aria-label="Region OCR text"]'),
    ).toBeNull();

    click(button(container, "Merge"));
    click(button(container, "Delete"));
    click(button(container, "Clear selection"));
    expect(actions).toEqual([
      { type: "merge_selected_regions" },
      { type: "delete_selected_region" },
      { type: "clear_selection" },
    ]);
  });

  it("keeps the single region's reading when only one was picked", () => {
    const { container } = mount({ state: multiSelected(1) });
    expect(textOf(container)).not.toContain("1 regions selected");
    expect(text(container, "Region OCR text").value).toBe("Region 1");
    expect(textOf(container)).toContain("#1");
  });

  it("refuses to merge or delete the middle of a bulk while the host writes", () => {
    const { container } = mount({ state: multiSelected(2), saving: true });
    expect(textOf(container)).toContain("2 regions selected");
    expect(button(container, "Merge").disabled).toBe(true);
    expect(button(container, "Delete").disabled).toBe(true);
    expect(button(container, "Clear selection").disabled).toBe(true);
  });

  it("says so while the eraser is armed, and stands down when told", () => {
    const { container, actions } = mount({ state: state({ mode: "eraser" }) });
    expect(textOf(container)).toContain("Eraser: click any region to remove");
    click(button(container, "Done"));
    expect(actions).toEqual([{ type: "set_mode", mode: "select" }]);

    clear();
    // The reminder is for a mode the pointer cannot see. Once something is picked,
    // the bar has a subject, and a select-mode bar has no eraser to announce.
    const picked = mount({
      state: state({ mode: "eraser", selection: { region: 0, vertex: null } }),
    });
    expect(textOf(picked.container)).not.toContain(
      "click any region to remove",
    );

    clear();
    const selecting = mount();
    expect(textOf(selecting.container)).not.toContain(
      "click any region to remove",
    );
  });
});

describe("document shortcuts", () => {
  it("step through history on ⌘Z, ⌘⇧Z and Ctrl+Y", () => {
    const undo = mount({ state: dirtyWithHistory() });
    expect(key({ key: "z", metaKey: true })).toBe(true);
    expect(undo.actions).toEqual([{ type: "undo" }]);

    const shifted = mount({ state: dirtyWithHistory() });
    expect(key({ key: "Z", metaKey: true, shiftKey: true })).toBe(true);
    expect(shifted.actions).toEqual([{ type: "redo" }]);

    const ctrlY = mount({ state: dirtyWithHistory() });
    expect(key({ key: "y", ctrlKey: true })).toBe(true);
    expect(ctrlY.actions).toEqual([{ type: "redo" }]);
  });

  it("deletes the region a keystroke points at", () => {
    const { actions } = mount({
      state: dirtyWithHistory({ selection: { region: 1, vertex: null } }),
    });
    expect(key({ key: "Backspace" })).toBe(true);
    expect(actions).toEqual([{ type: "delete_selected_region" }]);
  });

  it("takes every region the multi-selection holds in one keystroke", () => {
    const source = multiSelected(3);
    const { container, actions } = mount({ state: source });
    expect(button(container, "Delete 3 selected regions").disabled).toBe(false);
    expect(key({ key: "Backspace" })).toBe(true);
    // One action, and through the real reducer it is one undo step that empties the
    // page — not three keystrokes' worth of history for one intention.
    const after = applied(source, actions);
    expect(after.payload.regions).toHaveLength(0);
    expect(after.past).toHaveLength(1);
  });

  it("merges what is selected on M, and leaves the key alone when there is nothing to merge", () => {
    const source = multiSelected(3);
    const { actions } = mount({ state: source });
    expect(key({ key: "m" })).toBe(true);
    expect(actions).toEqual([{ type: "merge_selected_regions" }]);
    // The reducer's half of the promise: three hulls become one region, in one step.
    expect(applied(source, actions).payload.regions).toHaveLength(1);

    clear();
    const alone = mount();
    expect(key({ key: "M" })).toBe(false);
    expect(alone.actions).toEqual([]);

    clear();
    const withCommand = mount({ state: multiSelected(2) });
    expect(key({ key: "m", metaKey: true })).toBe(false);
    expect(key({ key: "m", ctrlKey: true })).toBe(false);
    expect(key({ key: "m", altKey: true })).toBe(false);
    expect(withCommand.actions).toEqual([]);
  });

  it("arms and disarms the eraser on E", () => {
    const selecting = mount();
    expect(key({ key: "e" })).toBe(true);
    expect(selecting.actions).toEqual([{ type: "set_mode", mode: "eraser" }]);

    clear();
    const armed = mount({ state: state({ mode: "eraser" }) });
    expect(key({ key: "E" })).toBe(true);
    expect(armed.actions).toEqual([{ type: "set_mode", mode: "select" }]);

    clear();
    const withCommand = mount();
    expect(key({ key: "e", metaKey: true })).toBe(false);
    expect(withCommand.actions).toEqual([]);
  });

  it("prefers the corner when the polygon can survive losing one", () => {
    const quad = mount({
      state: dirtyWithHistory({ selection: { region: 0, vertex: 2 } }),
    });
    expect(key({ key: "Delete" })).toBe(true);
    expect(quad.actions).toEqual([
      { type: "delete_vertex", region: 0, vertex: 2 },
    ]);

    // A triangle is the smallest polygon the contract accepts, so the keystroke
    // falls back to the whole region rather than leaving a line behind.
    const triangle = mount({
      state: dirtyWithHistory({
        payload: payload([region("A", TRIANGLE)]),
        selection: { region: 0, vertex: 1 },
      }),
    });
    expect(key({ key: "Delete" })).toBe(true);
    expect(triangle.actions).toEqual([{ type: "delete_selected_region" }]);
  });

  it("does nothing to a region when none is selected", () => {
    const { actions } = mount();
    expect(key({ key: "Backspace" })).toBe(false);
    expect(actions).toEqual([]);
  });

  it("peels one layer off per Escape, in this order", () => {
    const drawing = mount({
      state: state({
        mode: "draw_polygon",
        draft: { kind: "polygon", points: [[0, 0]], cursor: null },
        selection: { region: 0, vertex: null },
      }),
    });
    expect(key({ key: "Escape" })).toBe(true);
    expect(drawing.actions).toEqual([{ type: "cancel_draft" }]);

    const selected = mount({
      state: state({ selection: { region: 1, vertex: null } }),
    });
    expect(key({ key: "Escape" })).toBe(true);
    expect(selected.actions).toEqual([{ type: "clear_selection" }]);

    const arming = mount({ state: state({ mode: "draw_box" }) });
    expect(key({ key: "Escape" })).toBe(true);
    expect(arming.actions).toEqual([{ type: "set_mode", mode: "select" }]);
  });

  it("leaves Escape alone when there is nothing left to cancel", () => {
    const { actions } = mount();
    expect(key({ key: "Escape" })).toBe(false);
    expect(actions).toEqual([]);
  });

  it("answers an open discard prompt before it touches the selection", () => {
    const { container, actions } = mount({ state: dirtyWithHistory() });
    click(button(container, "Close editor"));
    expect(textOf(container)).toContain("Unsaved edits — discard?");

    expect(key({ key: "Escape" })).toBe(true);
    expect(actions).toEqual([]);
    expect(textOf(container)).not.toContain("Unsaved edits — discard?");
  });

  it("is not the owner of a key typed into a field", () => {
    const { actions } = mount({ state: dirtyWithHistory() });
    const elsewhere = document.createElement("input");
    document.body.appendChild(elsewhere);
    expect(key({ key: "z", metaKey: true }, elsewhere)).toBe(false);
    expect(key({ key: "Backspace" }, elsewhere)).toBe(false);
    expect(key({ key: "e" }, elsewhere)).toBe(false);
    expect(key({ key: "m" }, elsewhere)).toBe(false);

    const note = document.createElement("div");
    note.setAttribute("contenteditable", "true");
    // jsdom never reports a live `isContentEditable`, so the flag the browser would
    // set is given to it here rather than guessed at from the attribute.
    Object.defineProperty(note, "isContentEditable", { value: true });
    document.body.appendChild(note);
    expect(key({ key: "Backspace" }, note)).toBe(false);
    expect(actions).toEqual([]);
  });

  it("listens only while it is the frontmost editor, and never while saving", () => {
    const behind = mount({
      state: dirtyWithHistory(),
      shortcutsActive: false,
    });
    expect(key({ key: "z", metaKey: true })).toBe(false);
    expect(behind.actions).toEqual([]);

    const writing = mount({ state: dirtyWithHistory(), saving: true });
    expect(key({ key: "z", metaKey: true })).toBe(false);
    expect(key({ key: "Backspace" })).toBe(false);
    expect(key({ key: "e" })).toBe(false);
    expect(key({ key: "m" })).toBe(false);
    expect(writing.actions).toEqual([]);
  });
});

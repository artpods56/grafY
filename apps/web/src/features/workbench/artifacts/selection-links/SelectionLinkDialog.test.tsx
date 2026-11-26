// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ArtifactInteractionField } from "../artifact-interactions";
import { SelectionLinkDialog } from "./SelectionLinkDialog";
import {
  MAX_SELECTION_LINK_MAPPINGS,
  selectionLinkCapability,
  type SelectionLinkCard,
  type SelectionLinkDraft,
  type SelectionLinkEditor,
  type SelectionLinksAction,
} from "./selection-links-reducer";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mountedRoots = new Set<Root>();

afterEach(async () => {
  await act(async () => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.clear();
  document.body.replaceChildren();
});

const parcels: SelectionLinkCard = {
  id: "parcels",
  title: "Parcels",
  capability: selectionLinkCapability("table"),
};
const map: SelectionLinkCard = {
  id: "map",
  title: "Map",
  capability: selectionLinkCapability("map"),
};
const notes: SelectionLinkCard = {
  id: "notes",
  title: "Notes",
  capability: selectionLinkCapability("text"),
};
const cards = [parcels, map, notes];

const publishedFields: Record<string, readonly ArtifactInteractionField[]> = {
  parcels: [
    { id: "parcel_id", title: "Parcel", valueType: "string" },
    { id: "owner", title: "Owner", valueType: "string" },
  ],
  map: [
    { id: "feature_id", title: "Feature", valueType: "string" },
    { id: "name", title: "Name", valueType: "string" },
  ],
};

function draft(
  overrides: Partial<SelectionLinkDraft> = {},
): SelectionLinkDraft {
  return {
    bindingId: null,
    sourceCardId: parcels.id,
    targetCardId: null,
    mappings: [{ sourceField: "parcel_id", targetField: "" }],
    effects: [],
    ...overrides,
  };
}

function editing(
  overrides: Partial<SelectionLinkDraft> = {},
  error: string | null = null,
): SelectionLinkEditor {
  return { phase: "editing", draft: draft(overrides), error };
}

async function renderDialog(
  editor: SelectionLinkEditor,
  fields: Readonly<
    Record<string, readonly ArtifactInteractionField[]>
  > = publishedFields,
) {
  const dispatch = vi.fn<(action: SelectionLinksAction) => void>();
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.add(root);
  await act(async () => {
    root.render(
      <SelectionLinkDialog
        editor={editor}
        cards={cards}
        fields={fields}
        dispatch={dispatch}
      />,
    );
  });
  return dispatch;
}

function buttonNamed(label: string): HTMLButtonElement | undefined {
  return Array.from(document.querySelectorAll("button")).find((candidate) => {
    const text = candidate.textContent?.trim() ?? "";
    return text === label || candidate.getAttribute("aria-label") === label;
  });
}

function requireButton(label: string): HTMLButtonElement {
  const found = buttonNamed(label);
  if (found == null) throw new Error(`no button ${label}`);
  return found;
}

function selectByLabel(label: string): HTMLSelectElement {
  const found = document.querySelector<HTMLSelectElement>(
    `select[aria-label="${label}"]`,
  );
  if (found == null) {
    const names = Array.from(document.querySelectorAll("select"), (select) =>
      select.getAttribute("aria-label"),
    );
    throw new Error(`no select labelled ${label}; saw ${names.join(", ")}`);
  }
  return found;
}

function selectWithOption(label: string): HTMLSelectElement {
  const found = Array.from(document.querySelectorAll("select")).find((select) =>
    Array.from(select.options).some((option) => option.text === label),
  );
  if (found == null) throw new Error(`no select with option ${label}`);
  return found;
}

async function choose(select: HTMLSelectElement, value: string) {
  await act(async () => {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function clickButton(label: string) {
  await act(async () => {
    requireButton(label).click();
  });
}

describe("SelectionLinkDialog", () => {
  it("renders no dialog content when the editor is closed", async () => {
    await renderDialog({ phase: "closed" });
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(document.body.textContent).not.toContain("Link selection");
  });

  it("renders no dialog content when the source card is gone", async () => {
    await renderDialog(editing({ sourceCardId: "gone" }));
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it("offers only other cards that can show a selection", async () => {
    await renderDialog(editing());
    expect(document.body.textContent).toContain("Link selection");
    expect(document.body.textContent).toContain(
      "Selecting a row or feature in “Parcels” shows it in another card.",
    );
    const target = selectWithOption("Choose a card…");
    expect(target.value).toBe("");
    expect(Array.from(target.options, (option) => option.value)).toEqual([
      "",
      map.id,
    ]);
    expect(Array.from(target.options, (option) => option.text)).toEqual([
      "Choose a card…",
      "Map",
    ]);
  });

  it("dispatches target_chosen when a card is chosen", async () => {
    const dispatch = await renderDialog(editing());
    await choose(selectWithOption("Choose a card…"), map.id);
    expect(dispatch).toHaveBeenCalledWith({
      type: "target_chosen",
      targetCardId: map.id,
    });
  });

  it("dispatches mapping_changed with the other field kept", async () => {
    const dispatch = await renderDialog(
      editing({
        targetCardId: map.id,
        mappings: [{ sourceField: "parcel_id", targetField: "feature_id" }],
      }),
    );
    await choose(selectByLabel("Field in Parcels"), "owner");
    expect(dispatch).toHaveBeenCalledWith({
      type: "mapping_changed",
      index: 0,
      mapping: { sourceField: "owner", targetField: "feature_id" },
    });

    dispatch.mockClear();
    await choose(selectByLabel("Field in Map"), "name");
    expect(dispatch).toHaveBeenCalledWith({
      type: "mapping_changed",
      index: 0,
      mapping: { sourceField: "parcel_id", targetField: "name" },
    });
  });

  it("adds a field pair and hides the remove control while there is one row", async () => {
    const dispatch = await renderDialog(editing());
    expect(buttonNamed("Remove field pair")).toBeUndefined();
    await clickButton("Add field pair");
    expect(dispatch).toHaveBeenCalledWith({ type: "mapping_added" });
  });

  it("removes a field pair by its row", async () => {
    const dispatch = await renderDialog(
      editing({
        targetCardId: map.id,
        mappings: [
          { sourceField: "parcel_id", targetField: "feature_id" },
          { sourceField: "owner", targetField: "name" },
        ],
      }),
    );
    expect(selectByLabel("Field in Parcels, pair 2").value).toBe("owner");
    expect(selectByLabel("Field in Map, pair 2").value).toBe("name");
    const remove = Array.from(
      document.querySelectorAll<HTMLButtonElement>(
        'button[aria-label="Remove field pair"]',
      ),
    );
    expect(remove).toHaveLength(2);
    await act(async () => {
      remove[1]?.click();
    });
    expect(dispatch).toHaveBeenCalledWith({
      type: "mapping_removed",
      index: 1,
    });
  });

  it("shows Add field pair until the draft is one under the maximum", async () => {
    await renderDialog(
      editing({
        mappings: Array.from(
          { length: MAX_SELECTION_LINK_MAPPINGS - 1 },
          () => ({ sourceField: "", targetField: "" }),
        ),
      }),
    );
    expect(buttonNamed("Add field pair")).toBeDefined();
  });

  it("hides Add field pair at the maximum and still removes a row", async () => {
    await renderDialog(
      editing({
        mappings: Array.from({ length: MAX_SELECTION_LINK_MAPPINGS }, () => ({
          sourceField: "",
          targetField: "",
        })),
      }),
    );
    expect(buttonNamed("Add field pair")).toBeUndefined();
    expect(
      document.querySelectorAll('button[aria-label="Remove field pair"]'),
    ).toHaveLength(MAX_SELECTION_LINK_MAPPINGS);
  });

  it("lists the target's effects and dispatches effect_toggled", async () => {
    await renderDialog(editing());
    expect(document.querySelector('[role="checkbox"]')).toBeNull();
    expect(document.body.textContent).not.toContain("When a row is selected");

    const dispatch = await renderDialog(
      editing({ targetCardId: map.id, effects: ["focus"] }),
    );
    const labels = Array.from(
      document.querySelectorAll('[role="checkbox"]'),
      (box) => {
        const id = box.getAttribute("aria-labelledby");
        return id == null ? null : document.getElementById(id)?.textContent;
      },
    );
    expect(labels).toEqual([
      "Zoom to it",
      "Show only matching",
      "Highlight it",
    ]);
    const checked = Array.from(
      document.querySelectorAll('[role="checkbox"]'),
      (box) => box.getAttribute("aria-checked"),
    );
    expect(checked).toEqual(["true", "false", "false"]);

    const filter = Array.from(document.querySelectorAll("span")).find(
      (span) => span.textContent === "Show only matching",
    );
    if (filter == null) throw new Error("expected the filter label");
    await act(async () => {
      filter.click();
    });
    expect(dispatch).toHaveBeenCalledWith({
      type: "effect_toggled",
      effect: "filter",
    });
  });

  it("shows the editor error", async () => {
    await renderDialog(editing({}, "Choose fields on both cards."));
    const alert = document.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("Choose fields on both cards.");
  });

  it("offers Remove link only while editing a stored link", async () => {
    await renderDialog(editing());
    expect(buttonNamed("Remove link")).toBeUndefined();
    expect(document.body.textContent).toContain("Link selection");

    const dispatch = await renderDialog(
      editing({ bindingId: "artifact-viewer-binding-stored" }),
    );
    expect(document.body.textContent).toContain("Edit selection link");
    await clickButton("Remove link");
    expect(dispatch).toHaveBeenCalledWith({ type: "remove_requested" });
  });

  it("saves a new binding id and cancels from the button or the close control", async () => {
    const dispatch = await renderDialog(editing());
    await clickButton("Save link");
    expect(dispatch).toHaveBeenCalledWith({
      type: "save_requested",
      newBindingId: expect.stringMatching(/^artifact-viewer-binding-/),
    });

    await clickButton("Cancel");
    expect(dispatch).toHaveBeenLastCalledWith({ type: "cancelled" });

    await clickButton("Close");
    expect(dispatch).toHaveBeenLastCalledWith({ type: "cancelled" });
  });

  it("keeps a stored field that the card no longer publishes", async () => {
    await renderDialog(
      editing({
        targetCardId: map.id,
        mappings: [{ sourceField: "legacy_id", targetField: "legacy_geom" }],
      }),
    );
    const source = selectByLabel("Field in Parcels");
    const target = selectByLabel("Field in Map");
    expect(source.value).toBe("legacy_id");
    expect(Array.from(source.options, (option) => option.value)).toContain(
      "legacy_id",
    );
    expect(target.value).toBe("legacy_geom");
    expect(Array.from(target.options, (option) => option.value)).toContain(
      "legacy_geom",
    );
  });

  it("says when a card has not published fields yet", async () => {
    await renderDialog(editing({ targetCardId: map.id }), {});
    expect(document.body.textContent).toContain(
      "Fields appear once “Parcels” has loaded.",
    );
    expect(document.body.textContent).toContain(
      "Fields appear once “Map” has loaded.",
    );
  });
});

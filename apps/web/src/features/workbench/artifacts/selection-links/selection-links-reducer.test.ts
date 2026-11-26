import { describe, expect, it } from "vitest";

import {
  EMPTY_ARTIFACT_KEY_SELECTION,
  type ArtifactInteractionField,
  type ArtifactKeySelection,
  type ArtifactViewerBinding,
} from "../artifact-interactions";
import {
  INITIAL_SELECTION_LINKS_STATE,
  MAX_SELECTION_LINK_MAPPINGS,
  NO_SELECTION_LINKS,
  incomingForCard,
  outgoingFieldsForCard,
  reduceSelectionLinks,
  selectionLinkCapability,
  suggestMapping,
  type SelectionLinkCard,
  type SelectionLinkDraft,
  type SelectionLinksAction,
  type SelectionLinksEffect,
  type SelectionLinksState,
} from "./selection-links-reducer";

const TABLE: SelectionLinkCard = {
  id: "table",
  title: "Volost list",
  capability: selectionLinkCapability("table"),
};
const TABLE_B: SelectionLinkCard = {
  id: "table-b",
  title: "Second list",
  capability: selectionLinkCapability("table"),
};
const MAP: SelectionLinkCard = {
  id: "map",
  title: "Map",
  capability: selectionLinkCapability("map"),
};
const NOTE: SelectionLinkCard = {
  id: "note",
  title: "Note",
  capability: NO_SELECTION_LINKS,
};

/** A 1897 volost list: a governed-number column and a settlement column. */
const TABLE_FIELDS: readonly ArtifactInteractionField[] = [
  { id: "column_1", title: "№ по губерніи.", valueType: "text" },
  {
    id: "column_3",
    title: "Мѣстонахожденіе волостныхъ правленій.",
    valueType: "text",
  },
];
/** The map's fields are named for the columns it can be fed. */
const MAP_FIELDS: readonly ArtifactInteractionField[] = [
  { id: "№ по губерніи.", title: "№ по губерніи.", valueType: "mixed" },
  {
    id: "Мѣстонахожденіе волостныхъ правленій.",
    title: "Мѣстонахожденіе волостныхъ правленій.",
    valueType: "text",
  },
];

const LINK_TABLE_TO_MAP: ArtifactViewerBinding = {
  id: "link-1",
  sourceViewerId: "table",
  targetViewerId: "map",
  mappings: [
    {
      sourceField: "column_3",
      targetField: "Мѣстонахожденіе волостныхъ правленій.",
    },
  ],
  effects: ["focus", "highlight"],
  emptySelection: "show_all",
};
const LINK_TABLE_B_TO_MAP: ArtifactViewerBinding = {
  id: "link-2",
  sourceViewerId: "table-b",
  targetViewerId: "map",
  mappings: [
    {
      sourceField: "name",
      targetField: "Мѣстонахожденіе волостныхъ правленій.",
    },
  ],
  effects: ["filter"],
  emptySelection: "show_all",
};
const LINK_MAP_TO_TABLE: ArtifactViewerBinding = {
  id: "link-3",
  sourceViewerId: "map",
  targetViewerId: "table",
  mappings: [{ sourceField: "name", targetField: "column_1" }],
  effects: ["highlight"],
  emptySelection: "show_all",
};

function run(
  state: SelectionLinksState,
  ...actions: SelectionLinksAction[]
): {
  readonly state: SelectionLinksState;
  readonly effects: SelectionLinksEffect[];
} {
  const effects: SelectionLinksEffect[] = [];
  let current = state;
  for (const action of actions) {
    current = reduceSelectionLinks(current, action, (effect) => {
      effects.push(effect);
    });
  }
  return { state: current, effects };
}

function draftOf(state: SelectionLinksState): SelectionLinkDraft {
  if (state.editor.phase !== "editing") {
    throw new Error("expected the editor to be open");
  }
  return state.editor.draft;
}

function errorOf(state: SelectionLinksState): string | null {
  if (state.editor.phase !== "editing") {
    throw new Error("expected the editor to be open");
  }
  return state.editor.error;
}

function savedBinding(
  effects: readonly SelectionLinksEffect[],
): ArtifactViewerBinding {
  const effect = effects[0];
  if (effect?.type !== "save_link") {
    throw new Error("expected a save_link effect");
  }
  return effect.binding;
}

function canvasOf(
  cards: readonly SelectionLinkCard[],
  fields: SelectionLinksState["fields"] = {},
  selections: SelectionLinksState["selections"] = {},
): SelectionLinksState {
  return { ...INITIAL_SELECTION_LINKS_STATE, cards, fields, selections };
}

function selectionOf(
  rows: Array<Record<string, string | number>>,
): ArtifactKeySelection {
  return {
    kind: "key-selection",
    items: rows.map((values, index) => ({ values, sourceIndex: index })),
  };
}

/** A table → map editor left open by the single eligible target, pair suggested. */
function openEditor(): SelectionLinksState {
  return run(canvasOf([TABLE, MAP], { table: TABLE_FIELDS, map: MAP_FIELDS }), {
    type: "new_link_started",
    sourceCardId: "table",
  }).state;
}

/** That editor with every effect switched back off. */
function openWithoutEffects(): SelectionLinksState {
  return run(
    openEditor(),
    { type: "effect_toggled", effect: "focus" },
    { type: "effect_toggled", effect: "highlight" },
  ).state;
}

/** A stored link with nothing in it but its two cards. */
const BARE_LINK: ArtifactViewerBinding = {
  ...LINK_TABLE_TO_MAP,
  mappings: [],
  effects: [],
};

describe("published fields and selections", () => {
  it("keeps the state while republished fields say the same thing", () => {
    const canvas = canvasOf([TABLE]);
    const published = run(canvas, {
      type: "fields_published",
      cardId: "table",
      fields: TABLE_FIELDS,
    }).state;
    expect(published).not.toBe(canvas);
    expect(published.fields["table"]).toEqual(TABLE_FIELDS);

    const republished = run(published, {
      type: "fields_published",
      cardId: "table",
      fields: TABLE_FIELDS.map((field) => ({ ...field })),
    });
    expect(republished.state).toBe(published);
    expect(republished.effects).toEqual([]);

    const retyped = run(published, {
      type: "fields_published",
      cardId: "table",
      fields: [
        { id: "column_1", title: "№ по губерніи.", valueType: "number" },
      ],
    });
    expect(retyped.state).not.toBe(published);
    expect(retyped.state.fields["table"]).toHaveLength(1);
  });

  it("keeps the state while the same rows stay selected", () => {
    const canvas = canvasOf([TABLE]);
    const chosen = run(canvas, {
      type: "selection_changed",
      cardId: "table",
      selection: selectionOf([{ column_1: 4 }]),
    }).state;
    expect(chosen).not.toBe(canvas);

    expect(
      run(chosen, {
        type: "selection_changed",
        cardId: "table",
        selection: selectionOf([{ column_1: 4 }]),
      }).state,
    ).toBe(chosen);

    // The same row further down the list, and a number that became a string,
    // are both news.
    expect(
      run(chosen, {
        type: "selection_changed",
        cardId: "table",
        selection: {
          kind: "key-selection",
          items: [{ values: { column_1: 4 }, sourceIndex: 9 }],
        },
      }).state,
    ).not.toBe(chosen);
    expect(
      run(chosen, {
        type: "selection_changed",
        cardId: "table",
        selection: selectionOf([{ column_1: "4" }]),
      }).state,
    ).not.toBe(chosen);
    expect(
      run(chosen, {
        type: "selection_changed",
        cardId: "table",
        selection: selectionOf([{ column_1: 4, column_3: "Volost A" }]),
      }).state,
    ).not.toBe(chosen);

    // A card that never selected anything saying "nothing is selected" is quiet.
    expect(
      run(canvas, {
        type: "selection_changed",
        cardId: "table",
        selection: EMPTY_ARTIFACT_KEY_SELECTION,
      }).state,
    ).toBe(canvas);
  });
});

describe("canvas changes", () => {
  it("keeps the state when the canvas says the same thing again", () => {
    const current = {
      ...canvasOf(
        [TABLE, MAP],
        { table: TABLE_FIELDS },
        { table: selectionOf([{ column_1: 1 }]) },
      ),
      bindingIds: ["link-1"],
    };

    const again = run(current, {
      type: "canvas_changed",
      cards: [TABLE, MAP].map((card) => ({
        ...card,
        capability: {
          source: card.capability.source,
          effects: [...card.capability.effects],
        },
      })),
      bindingIds: ["link-1"],
    });

    expect(again.state).toBe(current);
    expect(again.effects).toEqual([]);
  });

  it("notices a card that can now do its effects in a different order", () => {
    const current = canvasOf([MAP]);
    const reordered: SelectionLinkCard = {
      ...MAP,
      capability: { source: true, effects: ["highlight", "focus", "filter"] },
    };

    expect(
      run(current, {
        type: "canvas_changed",
        cards: [reordered],
        bindingIds: [],
      }).state,
    ).not.toBe(current);
  });

  it("forgets the fields and selections of cards that left the canvas", () => {
    const current = canvasOf(
      [TABLE, MAP],
      { table: TABLE_FIELDS, map: MAP_FIELDS },
      {
        table: selectionOf([{ column_1: 1 }]),
        map: selectionOf([{ name: "R" }]),
      },
    );

    const next = run(current, {
      type: "canvas_changed",
      cards: [MAP],
      bindingIds: [],
    }).state;

    expect(Object.keys(next.selections)).toEqual(["map"]);
    expect(Object.keys(next.fields)).toEqual(["map"]);
  });

  it("closes an editor whose source, target, or stored link has gone", () => {
    const opened = openEditor();
    expect(draftOf(opened).targetCardId).toBe("map");

    expect(
      run(opened, {
        type: "canvas_changed",
        cards: [TABLE, NOTE],
        bindingIds: [],
      }).state.editor.phase,
    ).toBe("closed");
    expect(
      run(opened, { type: "canvas_changed", cards: [MAP], bindingIds: [] })
        .state.editor.phase,
    ).toBe("closed");

    const editingStoredLink = run(
      { ...canvasOf([TABLE, MAP]), bindingIds: ["link-1"] },
      { type: "link_edit_started", binding: LINK_TABLE_TO_MAP },
    ).state;
    expect(draftOf(editingStoredLink).bindingId).toBe("link-1");

    expect(
      run(editingStoredLink, {
        type: "canvas_changed",
        cards: [TABLE, MAP],
        bindingIds: [],
      }).state.editor.phase,
    ).toBe("closed");
    expect(
      run(editingStoredLink, {
        type: "canvas_changed",
        cards: [TABLE, MAP],
        bindingIds: ["link-1", "link-9"],
      }).state.editor.phase,
    ).toBe("editing");
  });
});

describe("opening an editor", () => {
  it("takes the only eligible target and suggests its pair", () => {
    expect(draftOf(openEditor())).toEqual({
      bindingId: null,
      sourceCardId: "table",
      targetCardId: "map",
      mappings: [
        {
          sourceField: "column_3",
          targetField: "Мѣстонахожденіе волостныхъ правленій.",
        },
      ],
      effects: ["focus", "highlight"],
    });
  });

  it("asks for a target when more than one card could take the selection", () => {
    const draft = draftOf(
      run(canvasOf([TABLE, MAP, TABLE_B], { table: TABLE_FIELDS }), {
        type: "new_link_started",
        sourceCardId: "table",
      }).state,
    );

    expect(draft.targetCardId).toBeNull();
    expect(draft.effects).toEqual([]);
    expect(draft.mappings).toEqual([{ sourceField: "", targetField: "" }]);
  });

  it("ignores a card that cannot publish a selection", () => {
    const current = canvasOf([TABLE, MAP, NOTE]);

    expect(
      run(current, { type: "new_link_started", sourceCardId: "note" }).state,
    ).toBe(current);
    expect(
      run(current, { type: "new_link_started", sourceCardId: "gone" }).state,
    ).toBe(current);
  });

  it("starts from the stored link when editing one", () => {
    const opened = run(canvasOf([TABLE, MAP]), {
      type: "link_edit_started",
      binding: LINK_TABLE_TO_MAP,
    });
    const draft = draftOf(opened.state);

    expect(draft.bindingId).toBe("link-1");
    expect(draft.sourceCardId).toBe("table");
    expect(draft.targetCardId).toBe("map");
    expect(draft.mappings).toEqual(LINK_TABLE_TO_MAP.mappings);
    expect(draft.effects).toEqual(["focus", "highlight"]);
    // The draft is a copy, so typing in it cannot reach the stored link.
    expect(draft.mappings[0]).not.toBe(LINK_TABLE_TO_MAP.mappings[0]);
    expect(draft.effects).not.toBe(LINK_TABLE_TO_MAP.effects);

    const bare = draftOf(
      run(canvasOf([TABLE, MAP]), {
        type: "link_edit_started",
        binding: BARE_LINK,
      }).state,
    );
    expect(bare.mappings).toEqual([{ sourceField: "", targetField: "" }]);
    expect(bare.effects).toEqual([]);
  });
});

describe("choosing a target", () => {
  it("does nothing outside the editor", () => {
    const closed = canvasOf([TABLE, MAP]);

    expect(
      run(closed, { type: "target_chosen", targetCardId: "map" }).state,
    ).toBe(closed);
  });

  it("defaults to focus and highlight on a map, highlight on a table", () => {
    const opened = run(
      canvasOf([TABLE, MAP, TABLE_B], {
        table: TABLE_FIELDS,
        map: MAP_FIELDS,
        "table-b": TABLE_FIELDS,
      }),
      { type: "link_edit_started", binding: BARE_LINK },
      { type: "target_chosen", targetCardId: "map" },
    );
    expect(draftOf(opened.state).effects).toEqual(["focus", "highlight"]);

    const toTable = run(opened.state, {
      type: "target_chosen",
      targetCardId: "table-b",
    }).state;
    expect(draftOf(toTable).targetCardId).toBe("table-b");
    expect(draftOf(toTable).effects).toEqual(["highlight"]);
  });

  it("clears the target when the choice is taken back", () => {
    const opened = openEditor();
    const cleared = run(opened, { type: "target_chosen", targetCardId: "" });

    expect(draftOf(cleared.state).targetCardId).toBeNull();
    expect(draftOf(cleared.state).effects).toEqual([]);
    expect(draftOf(cleared.state).mappings).toEqual(draftOf(opened).mappings);
    expect(cleared.effects).toEqual([]);
  });

  it("ignores a target that is unknown, itself, or unable to react", () => {
    const opened = openEditor();

    for (const targetCardId of ["gone", "table", "note"]) {
      expect(run(opened, { type: "target_chosen", targetCardId }).state).toBe(
        opened,
      );
    }
  });

  it("re-suggests the pair for a new target and keeps it for the old one", () => {
    const opened = run(
      canvasOf([TABLE, MAP, TABLE_B], {
        table: TABLE_FIELDS,
        map: MAP_FIELDS,
        "table-b": MAP_FIELDS,
      }),
      { type: "link_edit_started", binding: BARE_LINK },
    ).state;
    // A bare stored link has no pair of its own, so none is carried in.
    expect(draftOf(opened).mappings).toEqual([
      { sourceField: "", targetField: "" },
    ]);

    const toMap = run(opened, {
      type: "target_chosen",
      targetCardId: "map",
    }).state;
    expect(draftOf(toMap).mappings).toEqual([
      {
        sourceField: "column_3",
        targetField: "Мѣстонахожденіе волостныхъ правленій.",
      },
    ]);

    const rewritten = run(toMap, {
      type: "mapping_changed",
      index: 0,
      mapping: { sourceField: "column_1", targetField: "№ по губерніи." },
    }).state;

    // The same target again: what the person wrote stands.
    expect(
      draftOf(
        run(rewritten, { type: "target_chosen", targetCardId: "map" }).state,
      ).mappings,
    ).toEqual([{ sourceField: "column_1", targetField: "№ по губерніи." }]);

    // Another target: the written pair named a field the old target had.
    expect(
      draftOf(
        run(rewritten, { type: "target_chosen", targetCardId: "table-b" })
          .state,
      ).mappings,
    ).toEqual([
      {
        sourceField: "column_3",
        targetField: "Мѣстонахожденіе волостныхъ правленій.",
      },
    ]);
  });

  it("suggests as soon as the pair has been emptied, even for the same target", () => {
    const opened = run(
      canvasOf([TABLE, MAP], { table: TABLE_FIELDS, map: MAP_FIELDS }),
      { type: "link_edit_started", binding: BARE_LINK },
      { type: "target_chosen", targetCardId: "map" },
    ).state;
    expect(draftOf(opened).mappings).toEqual([
      {
        sourceField: "column_3",
        targetField: "Мѣстонахожденіе волостныхъ правленій.",
      },
    ]);

    const emptied = run(opened, {
      type: "mapping_changed",
      index: 0,
      mapping: { sourceField: "  ", targetField: "\t" },
    }).state;
    expect(draftOf(emptied).mappings).toEqual([
      { sourceField: "  ", targetField: "\t" },
    ]);

    expect(
      draftOf(
        run(emptied, { type: "target_chosen", targetCardId: "map" }).state,
      ).mappings,
    ).toEqual([
      {
        sourceField: "column_3",
        targetField: "Мѣстонахожденіе волостныхъ правленій.",
      },
    ]);
  });
});

describe("field pairs", () => {
  it("adds pairs up to the document's limit and removes them down to one", () => {
    const opened = run(canvasOf([TABLE, MAP]), {
      type: "new_link_started",
      sourceCardId: "table",
    }).state;

    const filling: SelectionLinksAction[] = [];
    for (let index = 0; index < MAX_SELECTION_LINK_MAPPINGS; index += 1) {
      filling.push({ type: "mapping_added" });
    }
    const filled = run(opened, ...filling);
    expect(draftOf(filled.state).mappings).toHaveLength(
      MAX_SELECTION_LINK_MAPPINGS,
    );
    expect(filled.effects).toEqual([]);

    const overfull = run(filled.state, { type: "mapping_added" });
    expect(overfull.state).toBe(filled.state);

    let onePair = filled.state;
    for (let index = 0; index < MAX_SELECTION_LINK_MAPPINGS; index += 1) {
      const next = run(onePair, { type: "mapping_removed", index: 0 }).state;
      if (next === onePair) break;
      onePair = next;
    }
    expect(draftOf(onePair).mappings).toHaveLength(1);
    expect(run(onePair, { type: "mapping_removed", index: 0 }).state).toBe(
      onePair,
    );
  });

  it("rewrites the addressed pair and ignores one that is not there", () => {
    const closed = canvasOf([TABLE, MAP]);
    const opened = openEditor();

    const changed = run(opened, {
      type: "mapping_changed",
      index: 0,
      mapping: { sourceField: "column_1", targetField: "name" },
    }).state;
    expect(draftOf(changed).mappings).toEqual([
      { sourceField: "column_1", targetField: "name" },
    ]);
    expect(run(closed, { type: "mapping_added" }).state).toBe(closed);

    for (const index of [-1, 1]) {
      expect(
        run(changed, {
          type: "mapping_changed",
          index,
          mapping: { sourceField: "a", targetField: "b" },
        }).state,
      ).toBe(changed);
      expect(run(changed, { type: "mapping_removed", index }).state).toBe(
        changed,
      );
    }
  });

  it("keeps the chosen effects in the order the target lists them", () => {
    const opened = openEditor();
    expect(draftOf(opened).effects).toEqual(["focus", "highlight"]);

    const filtered = run(opened, {
      type: "effect_toggled",
      effect: "filter",
    }).state;
    expect(draftOf(filtered).effects).toEqual(["focus", "filter", "highlight"]);

    const unfocused = run(filtered, {
      type: "effect_toggled",
      effect: "focus",
    }).state;
    expect(draftOf(unfocused).effects).toEqual(["filter", "highlight"]);

    // Toggling it back returns it to its place, not to the end.
    expect(
      draftOf(run(unfocused, { type: "effect_toggled", effect: "focus" }).state)
        .effects,
    ).toEqual(["focus", "filter", "highlight"]);

    // A target that left the editor's reach cannot be asked for an effect.
    expect(
      run(unfocused, { type: "target_chosen", targetCardId: "note" }).state,
    ).toBe(unfocused);
  });

  it("ignores an effect the target cannot do and a draft with no target", () => {
    const opened = run(
      canvasOf([TABLE, MAP, TABLE_B], {
        table: TABLE_FIELDS,
        "table-b": TABLE_FIELDS,
      }),
      { type: "link_edit_started", binding: BARE_LINK },
      { type: "target_chosen", targetCardId: "" },
    );
    expect(draftOf(opened.state).targetCardId).toBeNull();
    expect(
      run(opened.state, { type: "effect_toggled", effect: "highlight" }).state,
    ).toBe(opened.state);

    const toTable = run(opened.state, {
      type: "target_chosen",
      targetCardId: "table-b",
    }).state;
    expect(draftOf(toTable).effects).toEqual(["highlight"]);
    expect(
      run(toTable, { type: "effect_toggled", effect: "focus" }).state,
    ).toBe(toTable);
  });
});

describe("saving", () => {
  it("says what is missing, in the order a person meets it", () => {
    const noTarget = run(
      canvasOf([TABLE, MAP, TABLE_B]),
      { type: "link_edit_started", binding: BARE_LINK },
      { type: "target_chosen", targetCardId: "" },
    );
    expect(errorOf(noTarget.state)).toBeNull();
    const noTargetYet = run(noTarget.state, {
      type: "save_requested",
      newBindingId: "link-new",
    });
    expect(noTargetYet.effects).toEqual([]);
    expect(errorOf(noTargetYet.state)).toBe(
      "Choose the card that shows the selection.",
    );

    // A half-written pair is reported before the missing pair and the missing
    // effect it happens to cause as well.
    const unfinished = run(
      openWithoutEffects(),
      {
        type: "mapping_changed",
        index: 0,
        mapping: { sourceField: "column_1", targetField: "   " },
      },
      { type: "save_requested", newBindingId: "link-new" },
    );
    expect(errorOf(unfinished.state)).toBe(
      "Finish or remove the unfinished field pair.",
    );

    const noPair = run(
      openWithoutEffects(),
      {
        type: "mapping_changed",
        index: 0,
        mapping: { sourceField: "", targetField: "" },
      },
      { type: "save_requested", newBindingId: "link-new" },
    );
    expect(errorOf(noPair.state)).toBe("Pair at least one field.");

    const noEffect = run(
      openWithoutEffects(),
      {
        type: "mapping_changed",
        index: 0,
        mapping: { sourceField: "column_1", targetField: "name" },
      },
      { type: "save_requested", newBindingId: "link-new" },
    );
    expect(errorOf(noEffect.state)).toBe("Choose what the selection does.");
    expect(noEffect.effects).toEqual([]);
  });

  it("clears the complaint as soon as the draft is edited again", () => {
    const complained = run(openWithoutEffects(), {
      type: "save_requested",
      newBindingId: "link-new",
    }).state;
    expect(errorOf(complained)).not.toBeNull();

    const edited = run(complained, {
      type: "mapping_changed",
      index: 0,
      mapping: { sourceField: "column_1", targetField: "name" },
    }).state;
    expect(errorOf(edited)).toBeNull();
  });

  it("saves a new link under the id it is given, with trimmed pairs", () => {
    const opened = run(
      canvasOf([TABLE, MAP], { table: TABLE_FIELDS, map: MAP_FIELDS }),
      { type: "new_link_started", sourceCardId: "table" },
      { type: "mapping_added" },
      {
        type: "mapping_changed",
        index: 1,
        mapping: { sourceField: " column_1 ", targetField: " № по губерніи. " },
      },
    );
    expect(errorOf(opened.state)).toBeNull();

    const saved = run(opened.state, {
      type: "save_requested",
      newBindingId: "link-new",
    });

    expect(saved.effects).toEqual([
      {
        type: "save_link",
        binding: {
          id: "link-new",
          sourceViewerId: "table",
          targetViewerId: "map",
          mappings: [
            {
              sourceField: "column_3",
              targetField: "Мѣстонахожденіе волостныхъ правленій.",
            },
            { sourceField: "column_1", targetField: "№ по губерніи." },
          ],
          effects: ["focus", "highlight"],
          emptySelection: "show_all",
        },
      },
    ]);
    expect(saved.state.editor.phase).toBe("closed");
  });

  it("saves an edited link over the one it came from", () => {
    const editing = run(canvasOf([TABLE, MAP], { table: TABLE_FIELDS }), {
      type: "link_edit_started",
      binding: LINK_TABLE_TO_MAP,
    }).state;

    const saved = run(editing, {
      type: "save_requested",
      newBindingId: "link-new",
    });

    expect(saved.effects).toHaveLength(1);
    expect(savedBinding(saved.effects).id).toBe("link-1");
    expect(savedBinding(saved.effects).mappings).toEqual(
      LINK_TABLE_TO_MAP.mappings,
    );
    expect(savedBinding(saved.effects).targetViewerId).toBe("map");
  });

  it("saves nothing while the editor is closed", () => {
    const closed = canvasOf([TABLE, MAP]);
    const none = run(closed, {
      type: "save_requested",
      newBindingId: "link-1",
    });

    expect(none.state).toBe(closed);
    expect(none.effects).toEqual([]);
  });

  it("removes only a link that is already stored", () => {
    const stored = canvasOf([TABLE, MAP], {}, {});
    const editing = run(
      { ...stored, bindingIds: ["link-1"] },
      {
        type: "link_edit_started",
        binding: LINK_TABLE_TO_MAP,
      },
    ).state;

    const removed = run(editing, { type: "remove_requested" });
    expect(removed.effects).toEqual([
      { type: "remove_link", bindingId: "link-1" },
    ]);
    expect(removed.state.editor.phase).toBe("closed");

    const newLink = run(stored, {
      type: "new_link_started",
      sourceCardId: "table",
    }).state;
    const refused = run(newLink, { type: "remove_requested" });
    expect(refused.state).toBe(newLink);
    expect(refused.effects).toEqual([]);

    expect(run(stored, { type: "remove_requested" }).state).toBe(stored);
  });

  it("closes the editor when the work is given up", () => {
    const opened = openEditor();
    const closed = canvasOf([TABLE, MAP]);

    expect(run(opened, { type: "cancelled" }).state.editor.phase).toBe(
      "closed",
    );
    expect(run(closed, { type: "cancelled" }).state).toBe(closed);
  });
});

describe("suggestMapping", () => {
  const field = (
    id: string,
    title: string,
    valueType = "text",
  ): ArtifactInteractionField => ({ id, title, valueType });

  it("prefers an id match over a title match", () => {
    expect(
      suggestMapping(
        [field("name", "Name"), field("other", "Settlement")],
        [
          field("settlement", "Name"),
          field("name", "The name column", "number"),
        ],
      ),
    ).toEqual({ sourceField: "name", targetField: "name" });
  });

  it("ignores case and the trailing dot of a nineteenth-century heading", () => {
    expect(
      suggestMapping(
        [field("column_1", " № по Губерніи. ", "number")],
        [field("num", "№ по губерніи", "number")],
      ),
    ).toEqual({ sourceField: "column_1", targetField: "num" });
  });

  it("takes a pair of two text fields over an earlier match", () => {
    expect(
      suggestMapping(
        [field("a", "Name", "number"), field("b", "Settlement")],
        [field("Name", "Name", "mixed"), field("Settlement", "Settlement")],
      ),
    ).toEqual({ sourceField: "b", targetField: "Settlement" });
  });

  it("returns an empty pair when nothing has either field in common", () => {
    expect(
      suggestMapping([field("a", "", "image")], [field("z", "Z")]),
    ).toEqual({
      sourceField: "",
      targetField: "",
    });
    expect(suggestMapping([], [field("z", "Z")])).toEqual({
      sourceField: "",
      targetField: "",
    });
  });

  it("pairs a volost list with the map that can draw it", () => {
    expect(suggestMapping(TABLE_FIELDS, MAP_FIELDS)).toEqual({
      sourceField: "column_3",
      targetField: "Мѣстонахожденіе волостныхъ правленій.",
    });
  });
});

describe("reading links out for a card", () => {
  const selections: Record<string, ArtifactKeySelection> = {
    table: selectionOf([
      { column_3: "Volost A" },
      { column_1: 12, column_3: "Volost B" },
    ]),
    "table-b": selectionOf([{ other: "not the mapped field" }]),
  };

  it("lists what a card receives from every link that targets it", () => {
    const incoming = incomingForCard(
      "map",
      [LINK_MAP_TO_TABLE, LINK_TABLE_TO_MAP, LINK_TABLE_B_TO_MAP],
      selections,
    );

    expect(incoming).toEqual([
      {
        bindingId: "link-1",
        effects: ["focus", "highlight"],
        sourceSelectionCount: 2,
        rows: [
          { "Мѣстонахожденіе волостныхъ правленій.": "Volost A" },
          { "Мѣстонахожденіе волостныхъ правленій.": "Volost B" },
        ],
      },
      {
        bindingId: "link-2",
        effects: ["filter"],
        sourceSelectionCount: 1,
        // Its source has selected a row, but not one carrying the mapped field.
        rows: [],
      },
    ]);
    expect(incoming[0]?.effects).not.toBe(LINK_TABLE_TO_MAP.effects);
    expect(incomingForCard("note", [LINK_TABLE_TO_MAP], selections)).toEqual(
      [],
    );

    // A source that has selected nothing is still a link, with nothing to show.
    expect(incomingForCard("map", [LINK_TABLE_TO_MAP], {})).toEqual([
      {
        bindingId: "link-1",
        effects: ["focus", "highlight"],
        sourceSelectionCount: 0,
        rows: [],
      },
    ]);
  });

  it("lists each source field once, in link order", () => {
    const tableToSecondList: ArtifactViewerBinding = {
      ...LINK_TABLE_TO_MAP,
      id: "link-4",
      targetViewerId: "table-b",
      mappings: [
        {
          sourceField: "column_3",
          targetField: "Мѣстонахожденіе волостныхъ правленій.",
        },
        { sourceField: "column_1", targetField: "№ по губерніи." },
      ],
    };

    expect(
      outgoingFieldsForCard("table", [
        LINK_TABLE_TO_MAP,
        tableToSecondList,
        LINK_MAP_TO_TABLE,
      ]),
    ).toEqual(["column_3", "column_1"]);
    expect(outgoingFieldsForCard("note", [LINK_TABLE_TO_MAP])).toEqual([]);
  });
});

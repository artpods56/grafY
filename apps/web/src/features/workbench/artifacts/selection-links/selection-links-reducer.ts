/**
 * Selection links: one card's selected rows or features shown in another card.
 *
 * A stored link is a presentation binding (`ArtifactViewerBinding`): source
 * card, target card, field pairs and effects. It lives in the graph document and
 * is not held here. This module owns what is not stored: each card's published
 * fields and current selection, and the editor a person uses to create, change
 * or remove a link. It is pure: no React, no DOM, no fetch. Persisting a link is
 * an effect the adapter hook carries out.
 */
import type { ArtifactPreviewKind } from "@/lib/api";

import {
  EMPTY_ARTIFACT_KEY_SELECTION,
  targetRowsForBinding,
  type ArtifactInteractionField,
  type ArtifactKeySelection,
  type ArtifactViewerBinding,
  type ArtifactViewerEffect,
  type ArtifactViewerIncomingBinding,
} from "../artifact-interactions";

/** The graph document accepts at most this many field pairs per link. */
export const MAX_SELECTION_LINK_MAPPINGS = 8;

/** What a card's preview can do in a selection link. */
export interface SelectionLinkCapability {
  /** It publishes its fields and a selection of rows or features. */
  readonly source: boolean;
  /** What it does with rows selected in another card. Empty: never a target. */
  readonly effects: readonly ArtifactViewerEffect[];
}

export const NO_SELECTION_LINKS: SelectionLinkCapability = {
  source: false,
  effects: [],
};

/**
 * The one place that says which previews take part. A new preview joins by
 * implementing `ArtifactViewerInteractionContext` and gaining a case here.
 */
export function selectionLinkCapability(
  previewKind: ArtifactPreviewKind,
): SelectionLinkCapability {
  switch (previewKind) {
    case "table":
      return { source: true, effects: ["filter", "highlight"] };
    case "map":
      return { source: true, effects: ["focus", "filter", "highlight"] };
    default:
      return NO_SELECTION_LINKS;
  }
}

/** One card that may take part in a link, as the editor lists it. */
export interface SelectionLinkCard {
  readonly id: string;
  readonly title: string;
  readonly capability: SelectionLinkCapability;
}

export interface SelectionLinkMappingDraft {
  readonly sourceField: string;
  readonly targetField: string;
}

export interface SelectionLinkDraft {
  /** The stored link being edited, or null for a new one. */
  readonly bindingId: string | null;
  readonly sourceCardId: string;
  readonly targetCardId: string | null;
  readonly mappings: readonly SelectionLinkMappingDraft[];
  readonly effects: readonly ArtifactViewerEffect[];
}

export type SelectionLinkEditor =
  | { readonly phase: "closed" }
  | {
      readonly phase: "editing";
      readonly draft: SelectionLinkDraft;
      readonly error: string | null;
    };

export interface SelectionLinksState {
  /** The linkable cards on the canvas, from the last `canvas_changed`. */
  readonly cards: readonly SelectionLinkCard[];
  /** Ids of the stored links, from the last `canvas_changed`. */
  readonly bindingIds: readonly string[];
  readonly selections: Readonly<Record<string, ArtifactKeySelection>>;
  readonly fields: Readonly<
    Record<string, readonly ArtifactInteractionField[]>
  >;
  readonly editor: SelectionLinkEditor;
}

export const INITIAL_SELECTION_LINKS_STATE: SelectionLinksState = {
  cards: [],
  bindingIds: [],
  selections: {},
  fields: {},
  editor: { phase: "closed" },
};

export type SelectionLinksAction =
  | {
      readonly type: "fields_published";
      readonly cardId: string;
      readonly fields: readonly ArtifactInteractionField[];
    }
  | {
      readonly type: "selection_changed";
      readonly cardId: string;
      readonly selection: ArtifactKeySelection;
    }
  | {
      readonly type: "canvas_changed";
      readonly cards: readonly SelectionLinkCard[];
      readonly bindingIds: readonly string[];
    }
  | { readonly type: "new_link_started"; readonly sourceCardId: string }
  | {
      readonly type: "link_edit_started";
      readonly binding: ArtifactViewerBinding;
    }
  | { readonly type: "target_chosen"; readonly targetCardId: string }
  | {
      readonly type: "mapping_changed";
      readonly index: number;
      readonly mapping: SelectionLinkMappingDraft;
    }
  | { readonly type: "mapping_added" }
  | { readonly type: "mapping_removed"; readonly index: number }
  | { readonly type: "effect_toggled"; readonly effect: ArtifactViewerEffect }
  /** `newBindingId` is used only when the draft is a new link. */
  | { readonly type: "save_requested"; readonly newBindingId: string }
  | { readonly type: "remove_requested" }
  | { readonly type: "cancelled" };

export type SelectionLinksEffect =
  | { readonly type: "save_link"; readonly binding: ArtifactViewerBinding }
  | { readonly type: "remove_link"; readonly bindingId: string };

/** The empty row a new link starts with, and the row a cleared pair becomes. */
const BLANK_MAPPING: SelectionLinkMappingDraft = {
  sourceField: "",
  targetField: "",
};

/**
 * What a target is asked to do when a link to it is made: focus and highlight
 * where it can, otherwise the one effect it has.
 */
function defaultEffects(
  capability: SelectionLinkCapability,
): ArtifactViewerEffect[] {
  const chosen: ArtifactViewerEffect[] = [];
  for (const effect of ["focus", "highlight"] as const) {
    if (capability.effects.includes(effect)) chosen.push(effect);
  }
  if (chosen.length > 0) return chosen;
  return capability.effects.slice(0, 1);
}

export function reduceSelectionLinks(
  state: SelectionLinksState,
  action: SelectionLinksAction,
  exec: (effect: SelectionLinksEffect) => void,
): SelectionLinksState {
  switch (action.type) {
    case "fields_published": {
      const published = state.fields[action.cardId];
      const unchanged =
        published !== undefined &&
        published.length === action.fields.length &&
        published.every((field, index) => {
          const next = action.fields[index];
          return (
            next !== undefined &&
            next.id === field.id &&
            next.title === field.title &&
            next.valueType === field.valueType
          );
        });
      if (unchanged) return state;
      return {
        ...state,
        fields: { ...state.fields, [action.cardId]: action.fields },
      };
    }

    case "selection_changed": {
      const current =
        state.selections[action.cardId] ?? EMPTY_ARTIFACT_KEY_SELECTION;
      const unchanged =
        current.items.length === action.selection.items.length &&
        current.items.every((item, index) => {
          const next = action.selection.items[index];
          if (!next || item.sourceIndex !== next.sourceIndex) return false;
          const keys = Object.keys(item.values);
          return (
            keys.length === Object.keys(next.values).length &&
            keys.every(
              (key) =>
                Object.hasOwn(next.values, key) &&
                Object.is(item.values[key], next.values[key]),
            )
          );
        });
      if (unchanged) return state;
      return {
        ...state,
        selections: { ...state.selections, [action.cardId]: action.selection },
      };
    }

    case "canvas_changed": {
      const sameCards =
        action.cards.length === state.cards.length &&
        action.cards.every((card, index) => {
          const previous = state.cards[index];
          return (
            previous !== undefined &&
            previous.id === card.id &&
            previous.title === card.title &&
            previous.capability.source === card.capability.source &&
            previous.capability.effects.length ===
              card.capability.effects.length &&
            previous.capability.effects.every(
              (effect, effectIndex) =>
                effect === card.capability.effects[effectIndex],
            )
          );
        });
      const sameBindingIds =
        action.bindingIds.length === state.bindingIds.length &&
        action.bindingIds.every((id, index) => state.bindingIds[index] === id);

      // A card that left the canvas takes its published fields and its selection
      // with it; nothing else may keep feeding the editor.
      const cardIds = new Set(action.cards.map((card) => card.id));
      const selections: Record<string, ArtifactKeySelection> = {};
      const fields: Record<string, readonly ArtifactInteractionField[]> = {};
      let dropped = false;
      for (const [cardId, selection] of Object.entries(state.selections)) {
        if (cardIds.has(cardId)) selections[cardId] = selection;
        else dropped = true;
      }
      for (const [cardId, published] of Object.entries(state.fields)) {
        if (cardIds.has(cardId)) fields[cardId] = published;
        else dropped = true;
      }

      // An editor whose source, target, or stored link has gone cannot be saved
      // and has nothing left to show, so it closes rather than errors.
      let editor = state.editor;
      if (state.editor.phase === "editing") {
        const { sourceCardId, targetCardId, bindingId } = state.editor.draft;
        const stillWirable =
          cardIds.has(sourceCardId) &&
          (targetCardId === null || cardIds.has(targetCardId)) &&
          (bindingId === null || action.bindingIds.includes(bindingId));
        if (!stillWirable) editor = { phase: "closed" };
      }

      if (sameCards && sameBindingIds && !dropped && editor === state.editor) {
        return state;
      }
      return {
        ...state,
        cards: action.cards,
        bindingIds: action.bindingIds,
        selections,
        fields,
        editor,
      };
    }

    case "new_link_started": {
      const source = state.cards.find(
        (card) => card.id === action.sourceCardId,
      );
      if (!source || !source.capability.source) return state;

      // One possible target is not a choice worth asking for: take it, and with
      // it the default effects and the suggested pair, as `target_chosen` would.
      const targets = state.cards.filter(
        (card) =>
          card.id !== action.sourceCardId && card.capability.effects.length > 0,
      );
      const onlyTarget = targets.length === 1 ? targets[0] : undefined;
      const draft: SelectionLinkDraft = {
        bindingId: null,
        sourceCardId: action.sourceCardId,
        targetCardId: onlyTarget ? onlyTarget.id : null,
        effects: onlyTarget ? defaultEffects(onlyTarget.capability) : [],
        mappings: [
          onlyTarget
            ? suggestMapping(
                state.fields[action.sourceCardId] ?? [],
                state.fields[onlyTarget.id] ?? [],
              )
            : BLANK_MAPPING,
        ],
      };
      return { ...state, editor: { phase: "editing", draft, error: null } };
    }

    case "link_edit_started": {
      const binding = action.binding;
      return {
        ...state,
        editor: {
          phase: "editing",
          error: null,
          draft: {
            bindingId: binding.id,
            sourceCardId: binding.sourceViewerId,
            targetCardId: binding.targetViewerId,
            mappings:
              binding.mappings.length === 0
                ? [BLANK_MAPPING]
                : binding.mappings.map((mapping) => ({
                    sourceField: mapping.sourceField,
                    targetField: mapping.targetField,
                  })),
            effects: [...binding.effects],
          },
        },
      };
    }

    case "target_chosen": {
      if (state.editor.phase !== "editing") return state;
      const draft = state.editor.draft;
      if (action.targetCardId === "") {
        return {
          ...state,
          editor: {
            phase: "editing",
            error: null,
            draft: { ...draft, targetCardId: null, effects: [] },
          },
        };
      }
      const target = state.cards.find(
        (card) => card.id === action.targetCardId,
      );
      if (
        !target ||
        target.id === draft.sourceCardId ||
        target.capability.effects.length === 0
      ) {
        return state;
      }
      // A different target invalidates the old pairs; user rows survive only a
      // re-choice of the target they were written for.
      const everyPairBlank = draft.mappings.every(
        (mapping) =>
          mapping.sourceField.trim() === "" &&
          mapping.targetField.trim() === "",
      );
      const mappings =
        draft.targetCardId !== target.id || everyPairBlank
          ? [
              suggestMapping(
                state.fields[draft.sourceCardId] ?? [],
                state.fields[target.id] ?? [],
              ),
            ]
          : draft.mappings;
      return {
        ...state,
        editor: {
          phase: "editing",
          error: null,
          draft: {
            ...draft,
            targetCardId: target.id,
            effects: defaultEffects(target.capability),
            mappings,
          },
        },
      };
    }

    case "mapping_changed": {
      if (state.editor.phase !== "editing") return state;
      const draft = state.editor.draft;
      if (action.index < 0 || action.index >= draft.mappings.length) {
        return state;
      }
      return {
        ...state,
        editor: {
          phase: "editing",
          error: null,
          draft: {
            ...draft,
            mappings: draft.mappings.map((mapping, index) =>
              index === action.index ? action.mapping : mapping,
            ),
          },
        },
      };
    }

    case "mapping_added": {
      if (state.editor.phase !== "editing") return state;
      const draft = state.editor.draft;
      if (draft.mappings.length >= MAX_SELECTION_LINK_MAPPINGS) return state;
      return {
        ...state,
        editor: {
          phase: "editing",
          error: null,
          draft: { ...draft, mappings: [...draft.mappings, BLANK_MAPPING] },
        },
      };
    }

    case "mapping_removed": {
      if (state.editor.phase !== "editing") return state;
      const draft = state.editor.draft;
      if (
        action.index < 0 ||
        action.index >= draft.mappings.length ||
        draft.mappings.length === 1
      ) {
        return state;
      }
      return {
        ...state,
        editor: {
          phase: "editing",
          error: null,
          draft: {
            ...draft,
            mappings: draft.mappings.filter(
              (_mapping, index) => index !== action.index,
            ),
          },
        },
      };
    }

    case "effect_toggled": {
      if (state.editor.phase !== "editing") return state;
      const draft = state.editor.draft;
      const target = state.cards.find((card) => card.id === draft.targetCardId);
      if (!target || !target.capability.effects.includes(action.effect)) {
        return state;
      }
      // The row order a person sees is the capability's order, so the set of
      // chosen effects is kept in it too.
      const chosen = target.capability.effects.filter((effect) =>
        effect === action.effect
          ? !draft.effects.includes(effect)
          : draft.effects.includes(effect),
      );
      return {
        ...state,
        editor: {
          phase: "editing",
          error: null,
          draft: { ...draft, effects: chosen },
        },
      };
    }

    case "save_requested": {
      if (state.editor.phase !== "editing") return state;
      const draft = state.editor.draft;
      const invalidate = (message: string): SelectionLinksState => ({
        ...state,
        editor: { phase: "editing", draft, error: message },
      });

      if (draft.targetCardId === null) {
        return invalidate("Choose the card that shows the selection.");
      }
      const complete: SelectionLinkMappingDraft[] = [];
      let unfinished = false;
      for (const mapping of draft.mappings) {
        const sourceField = mapping.sourceField.trim();
        const targetField = mapping.targetField.trim();
        if (sourceField === "" && targetField === "") continue;
        if (sourceField === "" || targetField === "") unfinished = true;
        else complete.push({ sourceField, targetField });
      }
      if (unfinished) {
        return invalidate("Finish or remove the unfinished field pair.");
      }
      if (complete.length === 0) return invalidate("Pair at least one field.");
      if (draft.effects.length === 0) {
        return invalidate("Choose what the selection does.");
      }

      exec({
        type: "save_link",
        binding: {
          id: draft.bindingId ?? action.newBindingId,
          sourceViewerId: draft.sourceCardId,
          targetViewerId: draft.targetCardId,
          mappings: complete,
          effects: [...draft.effects],
          emptySelection: "show_all",
        },
      });
      return { ...state, editor: { phase: "closed" } };
    }

    case "remove_requested": {
      if (state.editor.phase !== "editing") return state;
      const bindingId = state.editor.draft.bindingId;
      if (bindingId === null) return state;
      exec({ type: "remove_link", bindingId });
      return { ...state, editor: { phase: "closed" } };
    }

    case "cancelled": {
      if (state.editor.phase !== "editing") return state;
      return { ...state, editor: { phase: "closed" } };
    }

    default: {
      const unhandled: never = action;
      return unhandled;
    }
  }
}

/**
 * The field pair a new link starts with: a source field whose id, or else whose
 * title, matches a target field. Pairs of two text fields rank first.
 */
export function suggestMapping(
  sourceFields: readonly ArtifactInteractionField[],
  targetFields: readonly ArtifactInteractionField[],
): SelectionLinkMappingDraft {
  const normalisedTitle = (title: string) =>
    title.trim().toLowerCase().replace(/\.+$/, "");

  const candidates: Array<{
    source: ArtifactInteractionField;
    target: ArtifactInteractionField;
  }> = [];
  for (const source of sourceFields) {
    const title = normalisedTitle(source.title);
    const target =
      targetFields.find((candidate) => candidate.id === source.id) ??
      (title === ""
        ? undefined
        : targetFields.find(
            (candidate) => normalisedTitle(candidate.title) === title,
          ));
    if (target) candidates.push({ source, target });
  }

  const pair =
    candidates.find(
      ({ source, target }) =>
        source.valueType === "text" && target.valueType === "text",
    ) ?? candidates[0];
  if (!pair) return BLANK_MAPPING;
  return { sourceField: pair.source.id, targetField: pair.target.id };
}

/** What one card receives from every link that targets it. */
export function incomingForCard(
  cardId: string,
  bindings: readonly ArtifactViewerBinding[],
  selections: Readonly<Record<string, ArtifactKeySelection>>,
): ArtifactViewerIncomingBinding[] {
  const incoming: ArtifactViewerIncomingBinding[] = [];
  for (const binding of bindings) {
    if (binding.targetViewerId !== cardId) continue;
    const selection =
      selections[binding.sourceViewerId] ?? EMPTY_ARTIFACT_KEY_SELECTION;
    incoming.push({
      bindingId: binding.id,
      effects: [...binding.effects],
      sourceSelectionCount: selection.items.length,
      rows: targetRowsForBinding(binding, selection),
    });
  }
  return incoming;
}

/** The fields a source card has to put in each selection, in link order. */
export function outgoingFieldsForCard(
  cardId: string,
  bindings: readonly ArtifactViewerBinding[],
): string[] {
  const fields: string[] = [];
  for (const binding of bindings) {
    if (binding.sourceViewerId !== cardId) continue;
    for (const mapping of binding.mappings) {
      if (!fields.includes(mapping.sourceField))
        fields.push(mapping.sourceField);
    }
  }
  return fields;
}

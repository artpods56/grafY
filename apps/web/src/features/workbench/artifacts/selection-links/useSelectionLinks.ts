import * as React from "react";

import { useEffectReducer } from "@/lib/state/use-effect-reducer";

import {
  EMPTY_ARTIFACT_KEY_SELECTION,
  type ArtifactViewerActivity,
  type ArtifactViewerBinding,
  type ArtifactViewerInteractionContext,
} from "../artifact-interactions";
import {
  incomingForCard,
  INITIAL_SELECTION_LINKS_STATE,
  outgoingFieldsForCard,
  reduceSelectionLinks,
  type SelectionLinkCard,
  type SelectionLinksAction,
  type SelectionLinksState,
} from "./selection-links-reducer";
import type {
  SelectionLinkLine,
  SelectionLinkMenuItem,
  SelectionLinksContextValue,
} from "./SelectionLinksContext";

export interface UseSelectionLinksOptions {
  cards: readonly SelectionLinkCard[];
  bindings: readonly ArtifactViewerBinding[];
  editable: boolean;
  saveBinding: (binding: ArtifactViewerBinding) => void;
  removeBinding: (bindingId: string) => void;
  onActivityChange: (
    cardId: string,
    activity: ArtifactViewerActivity | null,
  ) => void;
}

export function useSelectionLinks({
  cards,
  bindings,
  editable,
  saveBinding,
  removeBinding,
  onActivityChange,
}: UseSelectionLinksOptions): {
  context: SelectionLinksContextValue;
  editor: SelectionLinksState["editor"];
  cards: SelectionLinksState["cards"];
  fields: SelectionLinksState["fields"];
  dispatch: (action: SelectionLinksAction) => void;
} {
  const [state, dispatch] = useEffectReducer(
    reduceSelectionLinks,
    INITIAL_SELECTION_LINKS_STATE,
    (effect) => {
      switch (effect.type) {
        case "save_link":
          saveBinding(effect.binding);
          return;
        case "remove_link":
          removeBinding(effect.bindingId);
          return;
        default: {
          const unhandled: never = effect;
          return unhandled;
        }
      }
    },
  );

  React.useEffect(() => {
    dispatch({
      type: "canvas_changed",
      cards,
      bindingIds: bindings.map((binding) => binding.id),
    });
  }, [cards, bindings, dispatch]);

  // Published fields are not part of a context. Rebuilding on each publish
  // would hand the preview a new context, and it would publish again.
  const interactions = React.useMemo(() => {
    const contexts = new Map<string, ArtifactViewerInteractionContext>();
    for (const card of state.cards) {
      const cardId = card.id;
      contexts.set(cardId, {
        outgoingFields: outgoingFieldsForCard(cardId, bindings),
        selection: state.selections[cardId] ?? EMPTY_ARTIFACT_KEY_SELECTION,
        incoming: incomingForCard(cardId, bindings, state.selections),
        onFieldsChange: (fields) => {
          dispatch({ type: "fields_published", cardId, fields });
        },
        onSelectionChange: (selection) => {
          dispatch({ type: "selection_changed", cardId, selection });
        },
        onActivityChange: (activity) => {
          onActivityChange(cardId, activity);
        },
      });
    }
    return contexts;
  }, [bindings, dispatch, onActivityChange, state.cards, state.selections]);

  const lines = React.useMemo<readonly SelectionLinkLine[]>(() => {
    const present = new Set(state.cards.map((card) => card.id));
    return bindings.flatMap((binding) =>
      present.has(binding.sourceViewerId) && present.has(binding.targetViewerId)
        ? [
            {
              id: binding.id,
              sourceCardId: binding.sourceViewerId,
              targetCardId: binding.targetViewerId,
            },
          ]
        : [],
    );
  }, [bindings, state.cards]);

  const context = React.useMemo<SelectionLinksContextValue>(() => {
    return {
      interactionFor(cardId) {
        return interactions.get(cardId);
      },
      menuItemsFor(cardId): readonly SelectionLinkMenuItem[] {
        if (!editable) return [];
        const card = state.cards.find((candidate) => candidate.id === cardId);
        if (!card) return [];
        const items: SelectionLinkMenuItem[] = [];
        if (card.capability.source) {
          items.push({
            id: "selection-link-new",
            label: "Link selection…",
            onSelect: () => {
              dispatch({ type: "new_link_started", sourceCardId: cardId });
            },
          });
        }
        for (const binding of bindings) {
          const isSource = binding.sourceViewerId === cardId;
          const isTarget = binding.targetViewerId === cardId;
          if (!isSource && !isTarget) continue;
          const otherId = isSource
            ? binding.targetViewerId
            : binding.sourceViewerId;
          const other = state.cards.find(
            (candidate) => candidate.id === otherId,
          );
          if (!other) continue;
          items.push({
            id: `selection-link-${binding.id}`,
            label: isSource
              ? `Edit link to “${other.title}”`
              : `Edit link from “${other.title}”`,
            onSelect: () => {
              dispatch({ type: "link_edit_started", binding });
            },
          });
        }
        return items;
      },
      lines,
    };
  }, [bindings, dispatch, editable, interactions, lines, state.cards]);

  return {
    context,
    editor: state.editor,
    cards: state.cards,
    fields: state.fields,
    dispatch,
  };
}

"use client";

import * as React from "react";

import type { ArtifactViewerInteractionContext } from "../artifact-interactions";

export interface SelectionLinkMenuItem {
  id: string;
  label: string;
  onSelect: () => void;
}

export interface SelectionLinkLine {
  id: string;
  sourceCardId: string;
  targetCardId: string;
}

export interface SelectionLinksContextValue {
  /** The context a card's table or map preview takes; undefined when the card cannot take part. */
  interactionFor(cardId: string): ArtifactViewerInteractionContext | undefined;
  /** Card-menu entries for this card's links (empty in a read-only session). */
  menuItemsFor(cardId: string): readonly SelectionLinkMenuItem[];
  /** One line per stored link whose two cards are on the canvas. */
  readonly lines: readonly SelectionLinkLine[];
}

export const SelectionLinksContext =
  React.createContext<SelectionLinksContextValue | null>(null);

export function useSelectionLinksContext(): SelectionLinksContextValue | null {
  return React.useContext(SelectionLinksContext);
}

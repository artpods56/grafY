import * as React from "react";
import { changeOriginCardReferences } from "../model/origin-card-commands";

import { createUuid } from "@/features/workbench/model/uuid";

import type { NodeSpec } from "@/lib/api";

import {
  DEFAULT_ARTIFACT_CARD_WIDTH,
  artifactCardMediaHeight,
  artifactCardValue,
  canMergeIntoCard,
  cardArtifactRefs,
  originBelongsToCard,
  type ArtifactCardValue,
} from "../canvas/artifact-card";
import {
  CELL_SIZE,
  cellToWorldOrigin,
  type CellCoord,
} from "../cell-canvas/cell-model";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_INPUT_HANDLE,
  ARTIFACT_VIEWER_NODE_TYPE,
  type ArtifactViewerCanvasState,
  type ArtifactViewerEdge,
  type ArtifactViewerNode,
} from "../canvas/artifact-viewer";
import type { WorkflowNode } from "../canvas/nodes/workflow/node-type";
import type { WorkflowEdge } from "../canvas/types";
import type {
  AuthoredGraphOrigin,
  GraphCommand,
} from "../model/graph-document";
import {
  collectArtifactCards,
  tidyArtifactCards,
  ungroupArtifactCard,
} from "../model/artifact-grouping";
import {
  collectCardsCommands,
  collectionMembers,
  isCollectionNode,
  ungroupCollectionDisabledReason,
  ungroupedCollectionCards,
  type CollectionSource,
} from "../model/collection";
import { createWorkflowNodeData } from "../canvas/types";
import {
  withoutPresentationSelection,
  type CanvasSelectionCommands,
} from "./workbench-canvas-selection";

/**
 * What the card commands need to make and unmake collections. With the
 * collection operator available, "Collect" gathers Library cards and cards on a
 * node's output into one node instead of a card stack.
 */
export type CollectionCommandDeps = {
  spec: NodeSpec | null;
  /** Why the current selection cannot be collected, or null when it can. */
  disabledReason: string | null;
  sources: readonly CollectionSource[];
  nodes: readonly WorkflowNode[];
  edges: readonly WorkflowEdge[];
  /** Called with the new collection's id, so the caller can select it. */
  onCollected: (collectionId: string) => void;
};

export type ArtifactCardCommandDeps = {
  artifactViewers: ArtifactViewerCanvasState;
  applyAuthoringCommands: (commands: readonly GraphCommand[]) => void;
  /** Only `origins` is read: a card and the origin that fed it move together. */
  authoredDocumentRef: React.RefObject<{
    readonly origins: readonly AuthoredGraphOrigin[];
  }>;
  /** Answers whether the state landed, so a refusal leaves the selection where it was. */
  commitArtifactViewers: (
    updater: (current: ArtifactViewerCanvasState) => ArtifactViewerCanvasState,
  ) => boolean;
  groupingDisabledReason: string | null;
  localAuthoringEnabled: boolean;
  collection: CollectionCommandDeps;
  /**
   * The value a card passes on. A card that follows a producer has no stored
   * ref; this reads the output it is showing so Collect can snapshot it.
   */
  resolveCardValue?: (node: ArtifactViewerNode) => ArtifactCardValue | null;
  /** Lets go of the nodes and edges so the cards just placed are the whole selection. */
  selection: Pick<CanvasSelectionCommands, "clearWorkflowSelection">;
};

/**
 * Cards: the node-less viewer entries that present artifacts on the canvas.
 *
 * A card is placed deselected-from-everything-else, it carries the artifact order it was
 * handed, and the origin that fed it is rewritten whenever the card is reordered, because
 * the card is the only place a person can see what was passed in.
 */
export function useArtifactCardCommands(deps: ArtifactCardCommandDeps) {
  const {
    applyAuthoringCommands,
    artifactViewers,
    authoredDocumentRef,
    commitArtifactViewers,
    collection,
    groupingDisabledReason,
    localAuthoringEnabled,
    resolveCardValue,
    selection,
  } = deps;

  const addArtifactCards = React.useCallback(
    (
      cards: readonly {
        value: ArtifactCardValue;
        position: { x: number; y: number };
        layout?: ArtifactViewerNode["data"]["layout"];
      }[],
    ) => {
      if (cards.length === 0) return;
      // One commit, so a drop of several cards is one change to the canvas and
      // one presentation sync rather than a cascade the room replays.
      const added: ArtifactViewerNode[] = cards.map(
        ({ value, position, layout }) => ({
          id: `artifact-viewer-${createUuid()}`,
          type: ARTIFACT_VIEWER_NODE_TYPE,
          position,
          selected: true,
          data: {
            // No width unless inherited from a parent sequence: the card takes
            // the one that suits its artifact.
            layout: layout ? { ...layout } : null,
            mode: null,
            artifactRef: value,
          },
        }),
      );
      const committed = commitArtifactViewers((current) => {
        const cleared = withoutPresentationSelection(current);
        return { ...cleared, nodes: [...cleared.nodes, ...added] };
      });
      // A held node is not held with the card: the drop is the end of the old
      // selection, or nothing changes when the commit was refused.
      if (committed) selection.clearWorkflowSelection();
    },
    [commitArtifactViewers, selection],
  );

  const addArtifactCard = React.useCallback(
    (
      value: ArtifactCardValue,
      position: { x: number; y: number },
      layout?: ArtifactViewerNode["data"]["layout"],
    ) => {
      addArtifactCards([{ value, position, layout }]);
    },
    [addArtifactCards],
  );

  const collectSelectedArtifacts = React.useCallback(() => {
    if (!localAuthoringEnabled) return;
    if (collection.spec) {
      if (collection.disabledReason) return;
      const plan = collectCardsCommands({
        sources: collection.sources,
        nodes: collection.nodes,
        collectSpec: collection.spec,
        createNodeData: (spec, plugs) => createWorkflowNodeData(spec, plugs),
      });
      if (!plan) return;
      const removed = new Set(plan.removedCardIds);
      applyAuthoringCommands(plan.commands);
      commitArtifactViewers((current) => ({
        ...current,
        nodes: current.nodes.filter((node) => !removed.has(node.id)),
        edges: current.edges.filter(
          (edge) => !removed.has(edge.source) && !removed.has(edge.target),
        ),
      }));
      collection.onCollected(plan.collectionId);
      return;
    }
    if (groupingDisabledReason) return;
    const values: Record<string, ArtifactCardValue> = {};
    for (const node of artifactViewers.nodes) {
      if (!node.selected) continue;
      const value = resolveCardValue?.(node) ?? node.data.artifactRef;
      if (value) values[node.id] = value;
    }
    commitArtifactViewers((state) =>
      collectArtifactCards({
        state,
        origins: authoredDocumentRef.current.origins,
        values,
      }),
    );
  }, [
    applyAuthoringCommands,
    artifactViewers.nodes,
    authoredDocumentRef,
    collection,
    commitArtifactViewers,
    groupingDisabledReason,
    localAuthoringEnabled,
    resolveCardValue,
  ]);

  /**
   * A collection becomes its members again: Library members as cards holding
   * their artifacts, output members as cards following that output.
   */
  const ungroupCollection = React.useCallback(
    (nodeId: string) => {
      const node = collection.nodes.find(
        (candidate) => candidate.id === nodeId,
      );
      if (
        !node ||
        !isCollectionNode(node) ||
        ungroupCollectionDisabledReason(nodeId, collection.edges)
      ) {
        return;
      }
      const cards = ungroupedCollectionCards(
        node.position,
        collectionMembers(
          node,
          collection.nodes,
          collection.edges,
          authoredDocumentRef.current.origins,
        ),
        DEFAULT_ARTIFACT_CARD_WIDTH,
        artifactCardMediaHeight(DEFAULT_ARTIFACT_CARD_WIDTH),
      );
      // Removing the collection node retires the card links it sourced, applied where the
      // command lands. The links added below are sourced from the nodes that fed the
      // collection, so this order is what keeps those new cards wired.
      applyAuthoringCommands([{ kind: "remove_nodes", node_ids: [nodeId] }]);
      const added = cards.map((card) => ({
        card,
        id: `artifact-viewer-${createUuid()}`,
      }));
      const committed = commitArtifactViewers((current) => {
        const cleared = withoutPresentationSelection(current);
        return {
          ...cleared,
          nodes: [
            ...cleared.nodes,
            ...added.map(({ card, id }): ArtifactViewerNode => ({
              id,
              type: ARTIFACT_VIEWER_NODE_TYPE,
              position: card.position,
              selected: true,
              data:
                card.kind === "library"
                  ? { layout: null, mode: null, artifactRef: card.value }
                  : { layout: null, mode: "artifact", artifactRef: null },
            })),
          ],
          edges: [
            ...cleared.edges,
            ...added.flatMap(({ card, id }): ArtifactViewerEdge[] =>
              card.kind === "output"
                ? [
                    {
                      id: `artifact-viewer-edge-${createUuid()}`,
                      type: ARTIFACT_VIEWER_EDGE_TYPE,
                      source: card.sourceNodeId,
                      target: id,
                      targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
                      data: { sourcePortName: card.sourcePortName },
                    },
                  ]
                : [],
            ),
          ],
        };
      });
      if (committed) selection.clearWorkflowSelection();
    },
    [
      applyAuthoringCommands,
      authoredDocumentRef,
      collection.edges,
      collection.nodes,
      commitArtifactViewers,
      selection,
    ],
  );

  const ungroupArtifacts = React.useCallback(
    (nodeId: string) => {
      commitArtifactViewers((state) =>
        ungroupArtifactCard({
          state,
          origins: authoredDocumentRef.current.origins,
          nodeId,
        }),
      );
    },
    [authoredDocumentRef, commitArtifactViewers],
  );

  const tidySelectedArtifacts = React.useCallback(() => {
    commitArtifactViewers(tidyArtifactCards);
  }, [commitArtifactViewers]);

  /**
   * The card owns the order its artifacts are passed in, and an origin carries
   * what it was handed, so a reorder rewrites the origin beside the card.
   */
  const updateArtifactCardRefs = React.useCallback(
    (nodeId: string, value: ArtifactCardValue | null) => {
      const card = artifactViewers.nodes.find((node) => node.id === nodeId);
      if (!card) return;
      const carried = authoredDocumentRef.current.origins.filter((origin) =>
        originBelongsToCard(origin, card.id, card.data.artifactRef),
      );
      commitArtifactViewers((current) => ({
        ...current,
        nodes: value
          ? current.nodes.map((node) =>
              node.id === nodeId
                ? { ...node, data: { ...node.data, artifactRef: value } }
                : node,
            )
          : current.nodes.filter((node) => node.id !== nodeId),
      }));
      if (!carried.length) return;
      applyAuthoringCommands(
        carried.flatMap((origin) =>
          changeOriginCardReferences(origin, new Set([nodeId]), value),
        ),
      );
    },
    [
      applyAuthoringCommands,
      artifactViewers.nodes,
      authoredDocumentRef,
      commitArtifactViewers,
    ],
  );

  /**
   * A card that holds its own artifacts: not one following a producer's
   * output, whose value is the producer's to change.
   */
  const standaloneCard = React.useCallback(
    (cardId: string) => {
      const card = artifactViewers.nodes.find((node) => node.id === cardId);
      if (!card?.data.artifactRef) return null;
      if (artifactViewers.edges.some((edge) => edge.target === cardId)) {
        return null;
      }
      return card;
    },
    [artifactViewers.edges, artifactViewers.nodes],
  );

  /**
   * Whether one card's artifacts can join another's sequence. The card that
   * goes away must not be passed into an input: its wire would be lost with it.
   */
  const canMergeArtifactCards = React.useCallback(
    (sourceCardId: string, targetCardId: string) => {
      if (!localAuthoringEnabled || sourceCardId === targetCardId) return false;
      const source = standaloneCard(sourceCardId);
      const target = standaloneCard(targetCardId);
      if (!source || !target) return false;
      if (!canMergeIntoCard(target.data.artifactRef, source.data.artifactRef)) {
        return false;
      }
      const wired = authoredDocumentRef.current.origins.some((origin) =>
        originBelongsToCard(origin, source.id, source.data.artifactRef),
      );
      return !wired;
    },
    [authoredDocumentRef, localAuthoringEnabled, standaloneCard],
  );

  /**
   * Several cards become one sequence on `targetCardId`: their artifacts in
   * the order the cards are given, each artifact once. Every other card goes,
   * the target is what a person holds, and whatever the target was passed
   * into now carries the whole sequence. One commit and one origin rewrite,
   * however many cards join.
   */
  const mergeArtifactCardRun = React.useCallback(
    (cardIds: readonly string[], targetCardId: string) => {
      if (!localAuthoringEnabled || !cardIds.includes(targetCardId)) return;
      const target = standaloneCard(targetCardId);
      if (!target) return;
      const sources = cardIds.filter((id) => id !== targetCardId);
      if (sources.length === 0) return;
      const cards: ArtifactViewerNode[] = [];
      for (const id of cardIds) {
        if (id !== targetCardId && !canMergeArtifactCards(id, targetCardId)) {
          return;
        }
        const card = standaloneCard(id);
        if (!card) return;
        cards.push(card);
      }
      const targetValue = target.data.artifactRef;
      const seen = new Set<string>();
      const refs: ReturnType<typeof cardArtifactRefs> = [];
      for (const card of cards) {
        for (const ref of cardArtifactRefs(card.data.artifactRef)) {
          if (seen.has(ref.artifact_id)) continue;
          seen.add(ref.artifact_id);
          refs.push(ref);
        }
      }
      // Nothing new would join: the cards would go for no change.
      if (refs.length <= cardArtifactRefs(targetValue).length) return;
      const merged = artifactCardValue(refs, targetValue, { asSequence: true });
      if (!merged) return;
      const anchor = cards[0];
      if (!anchor) return;
      const removed = new Set(sources);
      const carried = authoredDocumentRef.current.origins.filter((origin) =>
        originBelongsToCard(origin, target.id, targetValue),
      );
      const committed = commitArtifactViewers((current) => {
        const cleared = withoutPresentationSelection(current);
        return {
          ...cleared,
          nodes: cleared.nodes
            .filter((node) => !removed.has(node.id))
            .map((node) =>
              node.id === targetCardId
                ? {
                    ...node,
                    position: { ...anchor.position },
                    selected: true,
                    data: {
                      ...node.data,
                      layout: anchor.data.layout ?? node.data.layout,
                      artifactRef: merged,
                    },
                  }
                : node,
            ),
          edges: cleared.edges.filter(
            (edge) => !removed.has(edge.source) && !removed.has(edge.target),
          ),
        };
      });
      if (!committed) return;
      selection.clearWorkflowSelection();
      if (!carried.length) return;
      applyAuthoringCommands(
        carried.flatMap((origin) =>
          changeOriginCardReferences(origin, new Set([targetCardId]), merged),
        ),
      );
    },
    [
      applyAuthoringCommands,
      authoredDocumentRef,
      canMergeArtifactCards,
      commitArtifactViewers,
      localAuthoringEnabled,
      selection,
      standaloneCard,
    ],
  );

  /**
   * One card dropped onto another: the target's artifacts then the source's,
   * or the source's first when it sits to the target's left.
   */
  const mergeArtifactCards = React.useCallback(
    (
      sourceCardId: string,
      targetCardId: string,
      order: "target-first" | "source-first" = "target-first",
    ) => {
      mergeArtifactCardRun(
        order === "target-first"
          ? [targetCardId, sourceCardId]
          : [sourceCardId, targetCardId],
        targetCardId,
      );
    },
    [mergeArtifactCardRun],
  );

  /**
   * A compatible unwired card dragged from the canvas into an open spread at a
   * specific slot index: splices its artifacts in at `insertIndex` (deduping
   * already-present artifacts) and removes the source card in one commit.
   */
  const insertArtifactCardIntoSequence = React.useCallback(
    (sourceCardId: string, targetCardId: string, insertIndex: number) => {
      if (!canMergeArtifactCards(sourceCardId, targetCardId)) return;
      const source = standaloneCard(sourceCardId);
      const target = standaloneCard(targetCardId);
      if (!source || !target) return;
      const targetValue = target.data.artifactRef;
      const targetRefs = cardArtifactRefs(targetValue);
      const existing = new Set(targetRefs.map((ref) => ref.artifact_id));
      const addedRefs = cardArtifactRefs(source.data.artifactRef).filter(
        (ref) => !existing.has(ref.artifact_id),
      );
      if (addedRefs.length === 0) return;
      const at = Math.max(0, Math.min(targetRefs.length, insertIndex));
      const nextRefs = [...targetRefs];
      nextRefs.splice(at, 0, ...addedRefs);
      const merged = artifactCardValue(nextRefs, targetValue, {
        asSequence: true,
      });
      if (!merged) return;
      const carried = authoredDocumentRef.current.origins.filter((origin) =>
        originBelongsToCard(origin, target.id, targetValue),
      );
      const committed = commitArtifactViewers((current) => {
        const cleared = withoutPresentationSelection(current);
        return {
          ...cleared,
          nodes: cleared.nodes
            .filter((node) => node.id !== sourceCardId)
            .map((node) =>
              node.id === targetCardId
                ? {
                    ...node,
                    selected: true,
                    data: { ...node.data, artifactRef: merged },
                  }
                : node,
            ),
          edges: cleared.edges.filter(
            (edge) =>
              edge.source !== sourceCardId && edge.target !== sourceCardId,
          ),
        };
      });
      if (!committed) return;
      selection.clearWorkflowSelection();
      if (!carried.length) return;
      applyAuthoringCommands(
        carried.flatMap((origin) =>
          changeOriginCardReferences(origin, new Set([targetCardId]), merged),
        ),
      );
    },
    [
      applyAuthoringCommands,
      authoredDocumentRef,
      canMergeArtifactCards,
      commitArtifactViewers,
      selection,
      standaloneCard,
    ],
  );

  /** One artifact moved to another place in the card's sequence. */
  const reorderArtifactCardItem = React.useCallback(
    (cardId: string, fromIndex: number, toIndex: number) => {
      const card = standaloneCard(cardId);
      if (!card || !localAuthoringEnabled) return;
      const refs = cardArtifactRefs(card.data.artifactRef);
      if (
        fromIndex === toIndex ||
        fromIndex < 0 ||
        fromIndex >= refs.length ||
        toIndex < 0 ||
        toIndex >= refs.length
      ) {
        return;
      }
      const next = [...refs];
      const [moved] = next.splice(fromIndex, 1);
      if (!moved) return;
      next.splice(toIndex, 0, moved);
      const value = artifactCardValue(next, card.data.artifactRef);
      if (value) updateArtifactCardRefs(cardId, value);
    },
    [localAuthoringEnabled, standaloneCard, updateArtifactCardRefs],
  );

  /**
   * One artifact taken out of a sequence onto its own card: at `targetCell`
   * when it was dropped there, otherwise a cell to the right. What is left
   * stays a sequence, or a single card when one remains.
   */
  const extractArtifactCardItem = React.useCallback(
    (cardId: string, index: number, targetCell?: CellCoord) => {
      const card = standaloneCard(cardId);
      if (!card || !localAuthoringEnabled) return;
      const refs = cardArtifactRefs(card.data.artifactRef);
      const extracted = refs[index];
      if (!extracted || refs.length < 2) return;
      const remaining = refs.filter((_, at) => at !== index);
      const kept = artifactCardValue(
        remaining,
        remaining.length > 1 ? card.data.artifactRef : null,
      );
      if (!kept) return;
      updateArtifactCardRefs(cardId, kept);
      const inheritedLayout = card.data.layout ? { ...card.data.layout } : null;
      if (targetCell) {
        addArtifactCard(
          extracted,
          cellToWorldOrigin(targetCell.col, targetCell.row),
          inheritedLayout,
        );
        return;
      }
      const footprint = artifactCardFootprint(card);
      addArtifactCard(
        extracted,
        {
          x: card.position.x + footprint.width + CELL_SIZE,
          y: card.position.y,
        },
        inheritedLayout,
      );
    },
    [
      addArtifactCard,
      localAuthoringEnabled,
      standaloneCard,
      updateArtifactCardRefs,
    ],
  );

  /**
   * One artifact taken out of a sequence and off the canvas. One left makes
   * a single card again; none left removes the card.
   */
  const removeArtifactCardItem = React.useCallback(
    (cardId: string, index: number) => {
      const card = standaloneCard(cardId);
      if (!card || !localAuthoringEnabled) return;
      const refs = cardArtifactRefs(card.data.artifactRef);
      if (index < 0 || index >= refs.length) return;
      const remaining = refs.filter((_, at) => at !== index);
      const kept = artifactCardValue(
        remaining,
        remaining.length > 1 ? card.data.artifactRef : null,
      );
      updateArtifactCardRefs(cardId, kept);
    },
    [localAuthoringEnabled, standaloneCard, updateArtifactCardRefs],
  );

  return {
    addArtifactCard,
    addArtifactCards,
    canMergeArtifactCards,
    extractArtifactCardItem,
    insertArtifactCardIntoSequence,
    mergeArtifactCardRun,
    mergeArtifactCards,
    removeArtifactCardItem,
    reorderArtifactCardItem,
    collectSelectedArtifacts,
    tidySelectedArtifacts,
    ungroupArtifacts,
    ungroupCollection,
    updateArtifactCardRefs,
  };
}

/**
 * The canvas box a card takes, as the cell canvas lays it out: at least eight
 * cells wide and six tall, each side snapped to whole cells.
 */
export function artifactCardFootprint(card: Pick<ArtifactViewerNode, "data">): {
  width: number;
  height: number;
} {
  const widthCells = Math.max(
    8,
    Math.round(
      (card.data.layout?.width ?? DEFAULT_ARTIFACT_CARD_WIDTH) / CELL_SIZE,
    ),
  );
  const heightCells = Math.max(
    6,
    Math.round((card.data.layout?.bodyHeight ?? 150) / CELL_SIZE),
  );
  return { width: widthCells * CELL_SIZE, height: heightCells * CELL_SIZE };
}

/** Where a dropped card lands: centred on the cursor, taller when it carries a set. */
export function artifactCardDropPosition(
  center: { x: number; y: number },
  artifactCount: number,
  width = DEFAULT_ARTIFACT_CARD_WIDTH,
): { x: number; y: number } {
  return {
    x: center.x - width / 2,
    y: center.y - (artifactCount > 1 ? 76 : 24),
  };
}

/**
 * The gutter between cards that land from one drop.
 *
 * Each card contributes its own width, so a table and an image do not overlap.
 */
export const ARTIFACT_CARD_DROP_GUTTER = 24;

/**
 * Where a set of cards dropped together lands: one row, centred on the cursor.
 *
 * Each card is placed by the same rule as a single drop — centred horizontally,
 * pushed up when it carries a set — and the row as a whole is centred on where
 * the pointer was released, so a two-card drop does not appear offset to one
 * side of the cursor.
 */
export function artifactCardDropPositions(
  center: { x: number; y: number },
  cards: readonly { artifactCount: number; width: number }[],
): { x: number; y: number }[] {
  const span =
    cards.reduce((sum, card) => sum + card.width, 0) +
    Math.max(0, cards.length - 1) * ARTIFACT_CARD_DROP_GUTTER;
  let left = center.x - span / 2;
  return cards.map(({ artifactCount, width }) => {
    const position = artifactCardDropPosition(
      { x: left + width / 2, y: center.y },
      artifactCount,
      width,
    );
    left += width + ARTIFACT_CARD_DROP_GUTTER;
    return position;
  });
}

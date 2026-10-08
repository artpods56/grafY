import * as React from "react";

import { createUuid } from "@/features/workbench/model/uuid";

import type { NodeSpec } from "@/lib/api";

import {
  DEFAULT_ARTIFACT_CARD_WIDTH,
  artifactCardMediaHeight,
  artifactCardValue,
  cardArtifactRefs,
  originCarriesCardArtifacts,
  type ArtifactCardValue,
} from "../canvas/artifact-card";
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
  commitArtifactViewers: (
    updater: (current: ArtifactViewerCanvasState) => ArtifactViewerCanvasState,
  ) => void;
  groupingDisabledReason: string | null;
  localAuthoringEnabled: boolean;
  collection: CollectionCommandDeps;
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
  } = deps;

  const addArtifactCards = React.useCallback(
    (
      cards: readonly {
        value: ArtifactCardValue;
        position: { x: number; y: number };
      }[],
    ) => {
      if (cards.length === 0) return;
      // One commit, so a drop of several cards is one change to the canvas and
      // one presentation sync rather than a cascade the room replays.
      commitArtifactViewers((current) => ({
        ...current,
        nodes: [
          ...current.nodes.map((node) => ({ ...node, selected: false })),
          ...cards.map(({ value, position }): ArtifactViewerNode => ({
            id: `artifact-viewer-${createUuid()}`,
            type: ARTIFACT_VIEWER_NODE_TYPE,
            position,
            selected: true,
            data: {
              // No width: the card takes the one that suits its artifact.
              layout: null,
              mode: null,
              artifactRef: value,
            },
          })),
        ],
      }));
    },
    [commitArtifactViewers],
  );

  const addArtifactCard = React.useCallback(
    (value: ArtifactCardValue, position: { x: number; y: number }) => {
      addArtifactCards([{ value, position }]);
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
    commitArtifactViewers((state) =>
      collectArtifactCards({
        state,
        origins: authoredDocumentRef.current.origins,
      }),
    );
  }, [
    applyAuthoringCommands,
    authoredDocumentRef,
    collection,
    commitArtifactViewers,
    groupingDisabledReason,
    localAuthoringEnabled,
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
      applyAuthoringCommands([{ kind: "remove_nodes", node_ids: [nodeId] }]);
      const added = cards.map((card) => ({
        card,
        id: `artifact-viewer-${createUuid()}`,
      }));
      commitArtifactViewers((current) => ({
        ...current,
        nodes: [
          ...current.nodes.map((viewer) => ({ ...viewer, selected: false })),
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
          ...current.edges,
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
      }));
    },
    [
      applyAuthoringCommands,
      authoredDocumentRef,
      collection.edges,
      collection.nodes,
      commitArtifactViewers,
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
        originCarriesCardArtifacts(origin.value, card.data.artifactRef),
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
      if (!value || !carried.length) return;
      applyAuthoringCommands(
        carried.flatMap((origin) => {
          const next = artifactCardValue(cardArtifactRefs(value), origin.value);
          return next
            ? [
                {
                  kind: "update_origin" as const,
                  origin_id: origin.id,
                  update: { value: next },
                },
              ]
            : [];
        }),
      );
    },
    [
      applyAuthoringCommands,
      artifactViewers.nodes,
      authoredDocumentRef,
      commitArtifactViewers,
    ],
  );

  return {
    addArtifactCard,
    addArtifactCards,
    collectSelectedArtifacts,
    tidySelectedArtifacts,
    ungroupArtifacts,
    ungroupCollection,
    updateArtifactCardRefs,
  };
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

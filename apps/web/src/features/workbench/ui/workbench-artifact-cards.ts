import * as React from "react";

import { createUuid } from "@/features/workbench/model/uuid";

import {
  DEFAULT_ARTIFACT_CARD_WIDTH,
  artifactCardValue,
  cardArtifactRefs,
  originCarriesCardArtifacts,
  type ArtifactCardValue,
} from "../canvas/artifact-card";
import {
  ARTIFACT_VIEWER_NODE_TYPE,
  type ArtifactViewerCanvasState,
} from "../canvas/artifact-viewer";
import type {
  AuthoredGraphOrigin,
  GraphCommand,
} from "../model/graph-document";
import {
  collectArtifactCards,
  tidyArtifactCards,
  ungroupArtifactCard,
} from "../model/artifact-grouping";

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
    groupingDisabledReason,
    localAuthoringEnabled,
  } = deps;

  const addArtifactCard = React.useCallback(
    (value: ArtifactCardValue, position: { x: number; y: number }) => {
      commitArtifactViewers((current) => ({
        ...current,
        nodes: [
          ...current.nodes.map((node) => ({ ...node, selected: false })),
          {
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
          },
        ],
      }));
    },
    [commitArtifactViewers],
  );

  const collectSelectedArtifacts = React.useCallback(() => {
    if (!localAuthoringEnabled || groupingDisabledReason) return;
    commitArtifactViewers((state) =>
      collectArtifactCards({
        state,
        origins: authoredDocumentRef.current.origins,
      }),
    );
  }, [
    authoredDocumentRef,
    commitArtifactViewers,
    groupingDisabledReason,
    localAuthoringEnabled,
  ]);

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
    collectSelectedArtifacts,
    tidySelectedArtifacts,
    ungroupArtifacts,
    updateArtifactCardRefs,
  };
}

/** Where a dropped card lands: centred on the cursor, taller when it carries a set. */
export function artifactCardDropPosition(
  center: { x: number; y: number },
  artifactCount: number,
): { x: number; y: number } {
  return {
    x: center.x - DEFAULT_ARTIFACT_CARD_WIDTH / 2,
    y: center.y - (artifactCount > 1 ? 76 : 24),
  };
}

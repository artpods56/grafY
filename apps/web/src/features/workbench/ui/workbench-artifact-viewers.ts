import * as React from "react";

import { originCarriesCardArtifacts } from "../canvas/artifact-card";
import type { AnnotationColor, AnnotationLayout } from "../canvas/annotations";
import {
  withAnnotationColor,
  withAnnotationLayout,
  withAnnotationText,
  withoutAnnotation,
  withViewerBinding,
  withViewerEdge,
  withViewerEdgeRoute,
  withViewerLayout,
  withViewerMode,
  withoutViewer,
} from "../canvas/artifact-viewer-edits";
import type {
  ArtifactViewerCanvasState,
  ArtifactViewerEdgeUpdate,
  ArtifactViewerNode,
} from "../canvas/artifact-viewer";
import type {
  ArtifactInteractionField,
  ArtifactKeySelection,
  ArtifactViewerActivity,
  ArtifactViewerBinding,
} from "../canvas/artifact-interactions";
import type { WorkflowEdgeRouteOffset } from "../canvas/types";
import type {
  AuthoredGraphOrigin,
  GraphCommand,
} from "../model/graph-document";

/**
 * The room side of the artifact-viewer layer. The workbench owns the socket and hands
 * this ref to the hook; the hook never learns how a command reaches the server.
 */
export type ArtifactViewerRoomSync = {
  submitReplace: (state: ArtifactViewerCanvasState) => void;
};

export type ArtifactViewerCommandDeps = {
  artifactViewers: ArtifactViewerCanvasState;
  /** Only `origins` is read: a removed card takes the constants it fed with it. */
  authoredDocumentRef: React.RefObject<{
    readonly origins: readonly AuthoredGraphOrigin[];
  }>;
  applyAuthoringCommands: (commands: readonly GraphCommand[]) => void;
  localAuthoringEnabledRef: React.RefObject<boolean>;
  localAuthoringBlockedMessageRef: React.RefObject<string>;
  presentationRoomSyncRef: React.RefObject<ArtifactViewerRoomSync>;
  artifactViewerActivityRevisionRef: React.RefObject<number>;
  setRunError: React.Dispatch<React.SetStateAction<string | null>>;
  setArtifactViewers: React.Dispatch<
    React.SetStateAction<ArtifactViewerCanvasState>
  >;
  setArtifactViewerSelections: React.Dispatch<
    React.SetStateAction<Record<string, ArtifactKeySelection>>
  >;
  setArtifactViewerFields: React.Dispatch<
    React.SetStateAction<Record<string, ArtifactInteractionField[]>>
  >;
  setArtifactViewerActivities: React.Dispatch<
    React.SetStateAction<
      Record<string, { activity: ArtifactViewerActivity; revision: number }>
    >
  >;
};

/**
 * Edits to the artifact-viewer layer: the mapping from a user gesture to a committed
 * `ArtifactViewerCanvasState`, plus the per-node interaction state that travels with it.
 *
 * Every committed edit takes the same path: refuse while local authoring is blocked, then
 * publish the whole state to the room on a microtask.
 * The state itself stays in the workbench, because room synchronisation, deletion and
 * selection write to it directly; what lives here is the commit rule, not the storage.
 *
 * A commit answers whether it landed. Selection lives partly outside this state, so a
 * gesture that moves it after placing something needs to know that a refusal left the
 * canvas as it was — otherwise a drop the server refused would quietly take the
 * selection away from whatever the person already held.
 */
export function useArtifactViewerCommands(deps: ArtifactViewerCommandDeps) {
  const {
    artifactViewers,
    artifactViewerActivityRevisionRef,
    applyAuthoringCommands,
    authoredDocumentRef,
    localAuthoringBlockedMessageRef,
    localAuthoringEnabledRef,
    presentationRoomSyncRef,
    setArtifactViewerActivities,
    setArtifactViewerFields,
    setArtifactViewerSelections,
    setArtifactViewers,
    setRunError,
  } = deps;

  const commitArtifactViewers = React.useCallback(
    (
      updater: (
        current: ArtifactViewerCanvasState,
      ) => ArtifactViewerCanvasState,
    ) => {
      if (!localAuthoringEnabledRef.current) {
        setRunError(localAuthoringBlockedMessageRef.current);
        return false;
      }
      setArtifactViewers((current) => {
        const next = updater(current);
        queueMicrotask(() => {
          presentationRoomSyncRef.current.submitReplace(next);
        });
        return next;
      });
      return true;
    },
    [
      localAuthoringBlockedMessageRef,
      localAuthoringEnabledRef,
      presentationRoomSyncRef,
      setArtifactViewers,
      setRunError,
    ],
  );

  const updateArtifactViewerLayout = React.useCallback(
    (nodeId: string, layout: ArtifactViewerNode["data"]["layout"]) => {
      commitArtifactViewers((current) =>
        withViewerLayout(current, nodeId, layout),
      );
    },
    [commitArtifactViewers],
  );

  const updateArtifactViewerEdge = React.useCallback(
    (edgeId: string, update: ArtifactViewerEdgeUpdate) => {
      commitArtifactViewers((current) =>
        withViewerEdge(current, edgeId, update),
      );
    },
    [commitArtifactViewers],
  );

  const updateArtifactViewerEdgeRoute = React.useCallback(
    (edgeId: string, routeOffset: WorkflowEdgeRouteOffset) => {
      commitArtifactViewers((current) =>
        withViewerEdgeRoute(current, edgeId, routeOffset),
      );
    },
    [commitArtifactViewers],
  );

  const updateArtifactViewerMode = React.useCallback(
    (nodeId: string, mode: string) => {
      commitArtifactViewers((current) => withViewerMode(current, nodeId, mode));
    },
    [commitArtifactViewers],
  );

  const updateArtifactViewerSelection = React.useCallback(
    (nodeId: string, selection: ArtifactKeySelection) => {
      setArtifactViewerSelections((current) => ({
        ...current,
        [nodeId]: selection,
      }));
    },
    [setArtifactViewerSelections],
  );

  const updateArtifactViewerFields = React.useCallback(
    (nodeId: string, fields: ArtifactInteractionField[]) => {
      setArtifactViewerFields((current) => {
        if (JSON.stringify(current[nodeId] ?? []) === JSON.stringify(fields)) {
          return current;
        }
        return { ...current, [nodeId]: fields };
      });
    },
    [setArtifactViewerFields],
  );

  const updateArtifactViewerActivity = React.useCallback(
    (nodeId: string, activity: ArtifactViewerActivity | null) => {
      if (!activity) {
        setArtifactViewerActivities((current) => {
          if (!current[nodeId]) return current;
          const next = { ...current };
          delete next[nodeId];
          return next;
        });
        return;
      }
      const revision = artifactViewerActivityRevisionRef.current + 1;
      artifactViewerActivityRevisionRef.current = revision;
      setArtifactViewerActivities((current) => {
        return {
          ...current,
          [nodeId]: {
            activity,
            revision,
          },
        };
      });
    },
    [artifactViewerActivityRevisionRef, setArtifactViewerActivities],
  );

  const updateArtifactViewerBinding = React.useCallback(
    (bindingId: string, binding: ArtifactViewerBinding) => {
      commitArtifactViewers((current) =>
        withViewerBinding(current, bindingId, binding),
      );
    },
    [commitArtifactViewers],
  );

  /**
   * A card is the only visible handle on the inputs it fed, so removing the card
   * removes what it passed in. An origin left behind is a constant on a node
   * input with nothing on the canvas that says where it came from.
   */
  const dropOriginsCarriedByCards = React.useCallback(
    (cards: readonly (ArtifactViewerNode | undefined)[]) => {
      const originIds = authoredDocumentRef.current.origins
        .filter((origin) =>
          cards.some((card) =>
            card
              ? originCarriesCardArtifacts(origin.value, card.data.artifactRef)
              : false,
          ),
        )
        .map((origin) => origin.id);
      if (originIds.length) {
        applyAuthoringCommands([
          { kind: "remove_origins", origin_ids: originIds },
        ]);
      }
    },
    [applyAuthoringCommands, authoredDocumentRef],
  );

  const removeArtifactViewer = React.useCallback(
    (nodeId: string) => {
      dropOriginsCarriedByCards([
        artifactViewers.nodes.find((node) => node.id === nodeId),
      ]);
      commitArtifactViewers((current) => withoutViewer(current, nodeId));
      setArtifactViewerSelections((current) => {
        const next = { ...current };
        delete next[nodeId];
        return next;
      });
      setArtifactViewerFields((current) => {
        const next = { ...current };
        delete next[nodeId];
        return next;
      });
      setArtifactViewerActivities((current) => {
        if (!current[nodeId]) return current;
        const next = { ...current };
        delete next[nodeId];
        return next;
      });
    },
    [
      artifactViewers.nodes,
      commitArtifactViewers,
      dropOriginsCarriedByCards,
      setArtifactViewerActivities,
      setArtifactViewerFields,
      setArtifactViewerSelections,
    ],
  );

  const updateAnnotationLayout = React.useCallback(
    (nodeId: string, layout: AnnotationLayout) => {
      commitArtifactViewers((current) =>
        withAnnotationLayout(current, nodeId, layout),
      );
    },
    [commitArtifactViewers],
  );

  const updateAnnotationText = React.useCallback(
    (nodeId: string, text: string) => {
      commitArtifactViewers((current) =>
        withAnnotationText(current, nodeId, text),
      );
    },
    [commitArtifactViewers],
  );

  const updateAnnotationColor = React.useCallback(
    (nodeId: string, color: AnnotationColor) => {
      commitArtifactViewers((current) =>
        withAnnotationColor(current, nodeId, color),
      );
    },
    [commitArtifactViewers],
  );

  const removeAnnotation = React.useCallback(
    (nodeId: string) => {
      commitArtifactViewers((current) => withoutAnnotation(current, nodeId));
    },
    [commitArtifactViewers],
  );

  return {
    commitArtifactViewers,
    dropOriginsCarriedByCards,
    removeAnnotation,
    removeArtifactViewer,
    updateAnnotationColor,
    updateAnnotationLayout,
    updateAnnotationText,
    updateArtifactViewerActivity,
    updateArtifactViewerBinding,
    updateArtifactViewerEdge,
    updateArtifactViewerEdgeRoute,
    updateArtifactViewerFields,
    updateArtifactViewerLayout,
    updateArtifactViewerMode,
    updateArtifactViewerSelection,
  };
}

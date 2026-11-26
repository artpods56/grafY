import * as React from "react";
import { changeOriginCardReferences } from "../artifacts/origin-card-commands";

import { originBelongsToCard } from "../artifacts/artifact-card";
import type {
  AnnotationColor,
  AnnotationLayout,
} from "../authoring/annotations";
import {
  withAnnotationColor,
  withAnnotationLayout,
  withAnnotationText,
  withoutAnnotation,
  withViewerBindingSaved,
  withViewerEdge,
  withViewerEdgeRoute,
  withViewerLayout,
  withViewerMode,
  withoutViewer,
  withoutViewerBinding,
} from "../artifacts/artifact-viewer-edits";
import type {
  ArtifactViewerCanvasState,
  ArtifactViewerEdgeUpdate,
  ArtifactViewerNode,
} from "../artifacts/artifact-viewer";
import type {
  ArtifactViewerActivity,
  ArtifactViewerBinding,
} from "../artifacts/artifact-interactions";
import type { WorkflowEdgeRouteOffset } from "../authoring/types";
import type {
  AuthoredGraphOrigin,
  GraphCommand,
} from "../authoring/graph-document";

/**
 * The room side of the artifact-viewer layer. The workbench owns the socket and hands
 * this ref to the hook; the hook never learns how a command reaches the server.
 */
export type ArtifactViewerRoomSync = {
  submitReplace: (state: ArtifactViewerCanvasState) => void;
};

/** Keep queued canvas edits visible to the next gesture in the same event. */
export function useArtifactViewerState(
  initial: ArtifactViewerCanvasState | (() => ArtifactViewerCanvasState),
) {
  const [state, setState] = React.useState(initial);
  const stateRef = React.useRef(state);
  const setArtifactViewers = React.useCallback<
    React.Dispatch<React.SetStateAction<ArtifactViewerCanvasState>>
  >((action) => {
    const next =
      typeof action === "function" ? action(stateRef.current) : action;
    stateRef.current = next;
    setState(next);
  }, []);
  return [state, setArtifactViewers, stateRef] as const;
}

export type ArtifactViewerCommandDeps = {
  artifactViewers: ArtifactViewerCanvasState;
  artifactViewersRef: React.RefObject<ArtifactViewerCanvasState>;
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
    artifactViewersRef,
    artifactViewerActivityRevisionRef,
    applyAuthoringCommands,
    authoredDocumentRef,
    localAuthoringBlockedMessageRef,
    localAuthoringEnabledRef,
    presentationRoomSyncRef,
    setArtifactViewerActivities,
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
      const next = updater(artifactViewersRef.current);
      setArtifactViewers(next);
      queueMicrotask(() => {
        presentationRoomSyncRef.current.submitReplace(next);
      });
      return true;
    },
    [
      artifactViewersRef,
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

  const saveArtifactViewerBinding = React.useCallback(
    (binding: ArtifactViewerBinding) => {
      commitArtifactViewers((current) =>
        withViewerBindingSaved(current, binding),
      );
    },
    [commitArtifactViewers],
  );

  const removeArtifactViewerBinding = React.useCallback(
    (bindingId: string) => {
      commitArtifactViewers((current) =>
        withoutViewerBinding(current, bindingId),
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
      const cardIds = new Set(cards.flatMap((card) => (card ? [card.id] : [])));
      const commands = authoredDocumentRef.current.origins
        .filter((origin) =>
          cards.some((card) =>
            card
              ? originBelongsToCard(origin, card.id, card.data.artifactRef)
              : false,
          ),
        )
        .flatMap((origin) => changeOriginCardReferences(origin, cardIds));
      if (commands.length) applyAuthoringCommands(commands);
    },
    [applyAuthoringCommands, authoredDocumentRef],
  );

  const removeArtifactViewer = React.useCallback(
    (nodeId: string) => {
      dropOriginsCarriedByCards([
        artifactViewers.nodes.find((node) => node.id === nodeId),
      ]);
      commitArtifactViewers((current) => withoutViewer(current, nodeId));
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
    removeArtifactViewerBinding,
    saveArtifactViewerBinding,
    updateArtifactViewerActivity,
    updateArtifactViewerEdge,
    updateArtifactViewerEdgeRoute,
    updateArtifactViewerLayout,
    updateArtifactViewerMode,
  };
}

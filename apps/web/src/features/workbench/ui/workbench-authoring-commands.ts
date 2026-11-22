import * as React from "react";

import type { NodeRegistry } from "@/lib/api";
import { withoutViewerEdgesFromNodes } from "../canvas/artifact-viewer-edits";
import type { ArtifactViewerCanvasState } from "../canvas/artifact-viewer";
import { collectionModeRepairCommands } from "../canvas/edge-collection-modes";
import {
  applyGraphCommandNormalized,
  type AuthoredGraphDocument,
  type GraphCommand,
} from "../model/graph-document";
import {
  reduceWorkbenchAuthoringState,
  type WorkbenchAuthoringAction,
} from "../canvas/graph-document-adapter";
import type { PendingConnectionRoute } from "./ConnectionRouteDialog";
import {
  shouldBlockAuthoringCommand,
  type AuthoringCommandOptions,
} from "./authoring-command-guard";

/**
 * The room side of a locally-originated command. The workbench owns the socket and
 * hands this ref to the hook; the hook never learns how a command reaches the server.
 */
export type WorkbenchRoomCommandSync = {
  submitLocal: (
    commands: readonly GraphCommand[],
    before: AuthoredGraphDocument,
  ) => void;
};

export type WorkbenchAuthoringCommandDeps = {
  authoredDocument: AuthoredGraphDocument;
  authoredDocumentRef: React.RefObject<AuthoredGraphDocument>;
  dispatchAuthoringState: React.Dispatch<WorkbenchAuthoringAction>;
  localAuthoringBlockedMessageRef: React.RefObject<string>;
  localAuthoringEnabledRef: React.RefObject<boolean>;
  nodeRegistry: NodeRegistry | null;
  roomCommandSyncRef: React.RefObject<WorkbenchRoomCommandSync>;
  setArtifactViewers: React.Dispatch<
    React.SetStateAction<ArtifactViewerCanvasState>
  >;
  setPendingConnectionRoute: React.Dispatch<
    React.SetStateAction<PendingConnectionRoute | null>
  >;
  setPositionOverrides: React.Dispatch<
    React.SetStateAction<Record<string, { x: number; y: number }>>
  >;
  setRunError: React.Dispatch<React.SetStateAction<string | null>>;
  setSelectedEdgeIdSet: React.Dispatch<
    React.SetStateAction<ReadonlySet<string>>
  >;
  setSelectedNodeIdSet: React.Dispatch<
    React.SetStateAction<ReadonlySet<string>>
  >;
};

/**
 * Apply one batch of authored graph commands: the single place a local gesture or a
 * replayed remote command changes the document.
 *
 * Everything that has to follow a command follows it here, once, for every caller.
 * `remove_nodes` is the reason that matters: a deleted workflow node also retires every
 * artifact-card link sourced from it, whichever gesture deleted the node: the node's
 * own remove button, the canvas Delete key, or an ungroup
 * that replaces a collection node with cards. Pruning anywhere else would leave a
 * gesture that forgets it, and the next save of that graph would offer the server a
 * link against a node the document no longer has.
 *
 * Collection modes follow the same rule and the same batch. A connection's mode says
 * how many values it carries, which is decided by the map connections of the step it
 * leaves, so deleting one connection can move the modes of the connections after it.
 * Repairing them here is what keeps the saved document a graph the runner accepts.
 */
export function useWorkbenchAuthoringCommands(
  deps: WorkbenchAuthoringCommandDeps,
) {
  const {
    authoredDocument,
    authoredDocumentRef,
    dispatchAuthoringState,
    localAuthoringBlockedMessageRef,
    localAuthoringEnabledRef,
    nodeRegistry,
    roomCommandSyncRef,
    setArtifactViewers,
    setPendingConnectionRoute,
    setPositionOverrides,
    setRunError,
    setSelectedEdgeIdSet,
    setSelectedNodeIdSet,
  } = deps;

  const applyAuthoringCommands = React.useCallback(
    (commands: readonly GraphCommand[], options?: AuthoringCommandOptions) => {
      if (!commands.length) return;
      if (
        shouldBlockAuthoringCommand(localAuthoringEnabledRef.current, options)
      ) {
        setRunError(localAuthoringBlockedMessageRef.current);
        return;
      }
      const before = authoredDocumentRef.current;
      // Gestures can submit several batches before React renders again.
      // Each batch reads the document produced by the preceding batch.
      const edited = reduceWorkbenchAuthoringState(
        { document: before, nodeOverlays: {}, error: null },
        { kind: "apply_commands", commands },
      ).document;
      const repairs = collectionModeRepairCommands(edited, nodeRegistry);
      // A repair only ever lands on a connection the document already carried
      // before this batch: the mode of a connection a batch adds is chosen from
      // the shapes its source step has at that moment, so only a removal or a
      // mode change can leave a mode behind. That is what lets these repairs ride
      // the same room submission as the gesture that moved the shapes, since a
      // submission describes every command against the document from before the
      // batch.
      let after = edited;
      for (const repair of repairs) {
        after = applyGraphCommandNormalized(after, repair);
      }
      authoredDocumentRef.current = after;
      dispatchAuthoringState({ kind: "apply_commands", commands });
      if (repairs.length) {
        dispatchAuthoringState({ kind: "apply_commands", commands: repairs });
      }
      setPositionOverrides({});
      setSelectedNodeIdSet(
        (current) =>
          new Set(
            [...current].filter((nodeId) =>
              authoredDocument.nodes.some((node) => node.id === nodeId),
            ),
          ),
      );
      setSelectedEdgeIdSet(
        (current) =>
          new Set(
            [...current].filter((edgeId) =>
              authoredDocument.edges.some((edge) => edge.id === edgeId),
            ),
          ),
      );
      for (const command of commands) {
        if (command.kind !== "remove_nodes") continue;
        setArtifactViewers((current) =>
          withoutViewerEdgesFromNodes(current, command.node_ids),
        );
      }
      setPendingConnectionRoute(null);
      setRunError(null);
      if (options?.syncRoom !== false) {
        roomCommandSyncRef.current.submitLocal(
          repairs.length ? [...commands, ...repairs] : commands,
          before,
        );
      }
    },
    [
      authoredDocument.edges,
      authoredDocument.nodes,
      authoredDocumentRef,
      dispatchAuthoringState,
      localAuthoringBlockedMessageRef,
      localAuthoringEnabledRef,
      nodeRegistry,
      roomCommandSyncRef,
      setArtifactViewers,
      setPendingConnectionRoute,
      setPositionOverrides,
      setRunError,
      setSelectedEdgeIdSet,
      setSelectedNodeIdSet,
    ],
  );

  return { applyAuthoringCommands };
}

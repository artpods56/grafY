"use client";

import * as React from "react";

import type { NodeRegistry } from "@/lib/api";
import { useEffectReducer } from "@/lib/state/use-effect-reducer";
import { withoutViewerEdgesFromNodes } from "../artifacts/artifact-viewer-edits";
import type { ArtifactViewerCanvasState } from "../artifacts/artifact-viewer";
import type { AuthoringCommandOptions } from "./authoring-command-guard";
import type { PendingConnectionRoute } from "./ConnectionRouteDialog";
import type { AuthoredGraphDocument, GraphCommand } from "./graph-document";
import type { NodeOverlays } from "./graph-document-adapter";
import type { XYPosition } from "./types";
import type { WorkbenchRoomCommandSync } from "./workbench-authoring-commands";
import {
  initialWorkbenchAuthoringUiState,
  workbenchAuthoringUiReducer,
  type InspectedPipeState,
  type PendingFolderDropState,
  type WorkbenchAuthoringUiAction,
  type WorkbenchAuthoringUiEffect,
  type WorkbenchAuthoringUiState,
} from "./workbench-authoring-reducer";

export interface WorkbenchAuthoringReducerDeps {
  readonly localAuthoringEnabledRef: React.RefObject<boolean>;
  readonly localAuthoringBlockedMessageRef: React.RefObject<string>;
  readonly nodeRegistryRef?: React.RefObject<NodeRegistry | null>;
  readonly nodeRegistry?: NodeRegistry | null;
  readonly roomCommandSyncRef: React.RefObject<WorkbenchRoomCommandSync>;
  readonly setArtifactViewers: React.Dispatch<
    React.SetStateAction<ArtifactViewerCanvasState>
  >;
  readonly setRunError: React.Dispatch<React.SetStateAction<string | null>>;
  readonly onClearRunError?: () => void;
  readonly onCloseGraphBrowser: () => void;
  readonly onCloseGridPanel: () => void;
}

interface LiveAuthoringDeps {
  readonly localAuthoringEnabledRef: React.RefObject<boolean>;
  readonly localAuthoringBlockedMessageRef: React.RefObject<string>;
  readonly nodeRegistryRef: React.RefObject<NodeRegistry | null> | undefined;
  readonly nodeRegistry: NodeRegistry | null;
  readonly roomCommandSyncRef: React.RefObject<WorkbenchRoomCommandSync>;
  readonly setArtifactViewers: React.Dispatch<
    React.SetStateAction<ArtifactViewerCanvasState>
  >;
  readonly setRunError: React.Dispatch<React.SetStateAction<string | null>>;
  readonly onClearRunError: (() => void) | undefined;
  readonly onCloseGraphBrowser: () => void;
  readonly onCloseGridPanel: () => void;
}

export interface WorkbenchAuthoringReducerApi<
  TDiscovery = unknown,
  TContextMenu = unknown,
> {
  readonly state: WorkbenchAuthoringUiState<TDiscovery, TContextMenu>;
  readonly dispatch: React.Dispatch<
    WorkbenchAuthoringUiAction<TDiscovery, TContextMenu>
  >;
  readonly authoredDocument: AuthoredGraphDocument;
  readonly nodeOverlays: NodeOverlays;
  readonly authoringError: string | null;
  readonly authoredDocumentRef: React.RefObject<AuthoredGraphDocument>;
  readonly nodeOverlaysRef: React.RefObject<NodeOverlays>;
  readonly applyAuthoringCommands: (
    commands: readonly GraphCommand[],
    options?: AuthoringCommandOptions,
  ) => void;
  readonly replaceDocument: (
    document: AuthoredGraphDocument,
    nodeOverlays?: NodeOverlays,
  ) => void;
  readonly applyNodesSnapshot: (snapshot: {
    readonly selectedNodeIds: ReadonlySet<string>;
    readonly positionOverrides: Readonly<Record<string, XYPosition>>;
    readonly nodeOverlays: NodeOverlays;
  }) => void;
  readonly selectedNodeIdSet: ReadonlySet<string>;
  readonly setSelectedNodeIdSet: React.Dispatch<
    React.SetStateAction<ReadonlySet<string>>
  >;
  readonly selectedEdgeIdSet: ReadonlySet<string>;
  readonly setSelectedEdgeIdSet: React.Dispatch<
    React.SetStateAction<ReadonlySet<string>>
  >;
  readonly selectedAgentIds: ReadonlySet<string>;
  readonly setSelectedAgentIds: React.Dispatch<
    React.SetStateAction<ReadonlySet<string>>
  >;
  readonly positionOverrides: Readonly<Record<string, XYPosition>>;
  readonly setPositionOverrides: React.Dispatch<
    React.SetStateAction<Readonly<Record<string, XYPosition>>>
  >;
  readonly collapsedAppendices: ReadonlySet<string>;
  readonly toggleAppendix: (cardId: string) => void;
  readonly configSections: WorkbenchAuthoringUiState["configSections"];
  readonly setConfigSection: (
    cardId: string,
    sectionKey: string,
    open: boolean,
  ) => void;
  readonly fitRevision: number;
  readonly requestCanvasRefit: () => void;
  readonly canvasUpload: string | null;
  readonly setCanvasUpload: (status: string | null) => void;
  readonly libraryOpen: boolean;
  readonly libraryInsertAt: XYPosition | null;
  readonly toggleLibrary: (insertAt?: XYPosition | null) => void;
  readonly setLibraryOpen: (
    open: boolean,
    insertAt?: XYPosition | null,
  ) => void;
  readonly shapesMenuOpen: boolean;
  readonly toggleShapesMenu: () => void;
  readonly setShapesMenuOpen: (open: boolean) => void;
  readonly contextualDiscovery: TDiscovery | null;
  readonly openContextualDiscovery: (session: TDiscovery) => void;
  readonly closeContextualDiscovery: () => void;
  readonly inspectedPipe: InspectedPipeState | null;
  readonly toggleInspectedPipe: (
    graphId: string | null,
    pipeId: string,
    anchor: XYPosition,
  ) => void;
  readonly closeInspectedPipe: () => void;
  readonly pruneInspectedPipes: (pipeIds: readonly string[]) => void;
  readonly canvasMenu: TContextMenu | null;
  readonly openContextMenu: (request: TContextMenu) => void;
  readonly closeContextMenu: () => void;
  readonly closeCanvasPopovers: (closeExternal?: boolean) => void;
  readonly pendingConnectionRoute: PendingConnectionRoute | null;
  readonly setPendingConnectionRoute: React.Dispatch<
    React.SetStateAction<PendingConnectionRoute | null>
  >;
  readonly pendingFolderDrop: PendingFolderDropState | null;
  readonly setPendingFolderDrop: (drop: PendingFolderDropState | null) => void;
  readonly clearAuthoringError: () => void;
  readonly dismissAuthoringError: (message: string) => void;
}

function isStateUpdater<T>(
  update: React.SetStateAction<T>,
): update is (prevState: T) => T {
  return typeof update === "function";
}

function resolveSetState<T>(update: React.SetStateAction<T>, current: T): T {
  if (isStateUpdater(update)) return update(current);
  return update;
}

function runAuthoringEffect(
  effect: WorkbenchAuthoringUiEffect,
  deps: LiveAuthoringDeps,
): void {
  switch (effect.kind) {
    case "reportBlockedError":
      deps.setRunError(effect.message);
      return;
    case "clearRunError":
      deps.setRunError(null);
      deps.onClearRunError?.();
      return;
    case "pruneArtifactViewerEdges":
      deps.setArtifactViewers((current) =>
        withoutViewerEdgesFromNodes(current, effect.nodeIds),
      );
      return;
    case "syncRoomCommands":
      deps.roomCommandSyncRef.current.submitLocal(
        effect.commands,
        effect.before,
      );
      return;
    case "closeGraphBrowser":
      deps.onCloseGraphBrowser();
      return;
    case "closeGridPanel":
      deps.onCloseGridPanel();
      return;
    default: {
      const unreachable: never = effect;
      return unreachable;
    }
  }
}

export function useWorkbenchAuthoringReducer<
  TDiscovery = unknown,
  TContextMenu = unknown,
>(
  deps: WorkbenchAuthoringReducerDeps,
): WorkbenchAuthoringReducerApi<TDiscovery, TContextMenu> {
  const {
    localAuthoringEnabledRef,
    localAuthoringBlockedMessageRef,
    nodeRegistryRef,
    nodeRegistry = null,
    roomCommandSyncRef,
    setArtifactViewers,
    setRunError,
    onClearRunError,
    onCloseGraphBrowser,
    onCloseGridPanel,
  } = deps;

  const [initialState] = React.useState(() =>
    initialWorkbenchAuthoringUiState<TDiscovery, TContextMenu>(),
  );
  const stateRef = React.useRef(initialState);
  const authoredDocumentRef = React.useRef(initialState.document);
  const nodeOverlaysRef = React.useRef(initialState.nodeOverlays);
  const commandEffectsRef = React.useRef<WorkbenchAuthoringUiEffect[]>([]);
  const liveDepsRef = React.useRef<LiveAuthoringDeps>({
    localAuthoringEnabledRef,
    localAuthoringBlockedMessageRef,
    nodeRegistryRef,
    nodeRegistry,
    roomCommandSyncRef,
    setArtifactViewers,
    setRunError,
    onClearRunError,
    onCloseGraphBrowser,
    onCloseGridPanel,
  });

  // Writes the refs inside the reducer call, which runs on dispatch, so a
  // later command in the same turn reads the document the previous one produced.
  const reducer = React.useCallback(
    (
      state: WorkbenchAuthoringUiState<TDiscovery, TContextMenu>,
      action: WorkbenchAuthoringUiAction<TDiscovery, TContextMenu>,
      exec: (effect: WorkbenchAuthoringUiEffect) => void,
    ) => {
      const next = workbenchAuthoringUiReducer<TDiscovery, TContextMenu>(
        state,
        action,
        action.kind === "applyCommands"
          ? (effect) => commandEffectsRef.current.push(effect)
          : exec,
      );
      stateRef.current = next;
      authoredDocumentRef.current = next.document;
      nodeOverlaysRef.current = next.nodeOverlays;
      return next;
    },
    [],
  );

  const runEffect = React.useCallback((effect: WorkbenchAuthoringUiEffect) => {
    runAuthoringEffect(effect, liveDepsRef.current);
  }, []);

  const [state, dispatch] = useEffectReducer(reducer, initialState, runEffect);

  const dispatchAction = React.useCallback(
    (action: WorkbenchAuthoringUiAction<TDiscovery, TContextMenu>) => {
      liveDepsRef.current = {
        localAuthoringEnabledRef,
        localAuthoringBlockedMessageRef,
        nodeRegistryRef,
        nodeRegistry,
        roomCommandSyncRef,
        setArtifactViewers,
        setRunError,
        onClearRunError,
        onCloseGraphBrowser,
        onCloseGridPanel,
      };
      let commandEffects: WorkbenchAuthoringUiEffect[] = [];
      let dispatched = false;
      try {
        dispatch(action);
        dispatched = true;
      } finally {
        if (action.kind === "applyCommands") {
          // A gesture can submit graph commands and then presentation changes.
          // Submit the graph batch before control returns to that gesture.
          commandEffects = commandEffectsRef.current.splice(0);
        }
      }
      if (dispatched && commandEffects.length > 0) {
        for (const effect of commandEffects) {
          runAuthoringEffect(effect, liveDepsRef.current);
        }
      }
    },
    [
      dispatch,
      localAuthoringBlockedMessageRef,
      localAuthoringEnabledRef,
      nodeRegistry,
      nodeRegistryRef,
      onClearRunError,
      onCloseGraphBrowser,
      onCloseGridPanel,
      roomCommandSyncRef,
      setArtifactViewers,
      setRunError,
    ],
  );

  const applyAuthoringCommands = React.useCallback(
    (commands: readonly GraphCommand[], options?: AuthoringCommandOptions) => {
      const registry = nodeRegistryRef ? nodeRegistryRef.current : nodeRegistry;
      dispatchAction({
        kind: "applyCommands",
        commands,
        options,
        localAuthoringEnabled: localAuthoringEnabledRef.current,
        blockedMessage: localAuthoringBlockedMessageRef.current,
        nodeRegistry: registry,
      });
    },
    [
      dispatchAction,
      localAuthoringBlockedMessageRef,
      localAuthoringEnabledRef,
      nodeRegistry,
      nodeRegistryRef,
    ],
  );

  const replaceDocument = React.useCallback(
    (document: AuthoredGraphDocument, nodeOverlays?: NodeOverlays) => {
      dispatchAction(
        nodeOverlays === undefined
          ? { kind: "replaceDocument", document }
          : { kind: "replaceDocument", document, nodeOverlays },
      );
    },
    [dispatchAction],
  );

  const applyNodesSnapshot = React.useCallback(
    (snapshot: {
      readonly selectedNodeIds: ReadonlySet<string>;
      readonly positionOverrides: Readonly<Record<string, XYPosition>>;
      readonly nodeOverlays: NodeOverlays;
    }) => {
      dispatchAction({ kind: "applyNodesSnapshot", ...snapshot });
    },
    [dispatchAction],
  );

  const setSelectedNodeIdSet = React.useCallback<
    React.Dispatch<React.SetStateAction<ReadonlySet<string>>>
  >(
    (update) => {
      dispatchAction({
        kind: "setSelectedNodeIds",
        ids: resolveSetState(update, stateRef.current.selectedNodeIds),
      });
    },
    [dispatchAction],
  );

  const setSelectedEdgeIdSet = React.useCallback<
    React.Dispatch<React.SetStateAction<ReadonlySet<string>>>
  >(
    (update) => {
      dispatchAction({
        kind: "setSelectedEdgeIds",
        ids: resolveSetState(update, stateRef.current.selectedEdgeIds),
      });
    },
    [dispatchAction],
  );

  const setSelectedAgentIds = React.useCallback<
    React.Dispatch<React.SetStateAction<ReadonlySet<string>>>
  >(
    (update) => {
      dispatchAction({
        kind: "setSelectedAgentIds",
        ids: resolveSetState(update, stateRef.current.selectedAgentIds),
      });
    },
    [dispatchAction],
  );

  const setPositionOverrides = React.useCallback<
    React.Dispatch<React.SetStateAction<Readonly<Record<string, XYPosition>>>>
  >(
    (update) => {
      dispatchAction({
        kind: "setPositionOverrides",
        overrides: resolveSetState(update, stateRef.current.positionOverrides),
      });
    },
    [dispatchAction],
  );

  const toggleAppendix = React.useCallback(
    (cardId: string) => {
      dispatchAction({ kind: "toggleAppendix", cardId });
    },
    [dispatchAction],
  );

  const setConfigSection = React.useCallback(
    (cardId: string, sectionKey: string, open: boolean) => {
      dispatchAction({ kind: "setConfigSection", cardId, sectionKey, open });
    },
    [dispatchAction],
  );

  const requestCanvasRefit = React.useCallback(() => {
    dispatchAction({ kind: "requestCanvasRefit" });
  }, [dispatchAction]);

  const setCanvasUpload = React.useCallback(
    (status: string | null) => {
      dispatchAction({ kind: "setCanvasUpload", status });
    },
    [dispatchAction],
  );

  const toggleLibrary = React.useCallback(
    (insertAt?: XYPosition | null) => {
      dispatchAction({ kind: "toggleLibrary", insertAt });
    },
    [dispatchAction],
  );

  const setLibraryOpen = React.useCallback(
    (open: boolean, insertAt?: XYPosition | null) => {
      dispatchAction({ kind: "setLibraryOpen", open, insertAt });
    },
    [dispatchAction],
  );

  const toggleShapesMenu = React.useCallback(() => {
    dispatchAction({ kind: "toggleShapesMenu" });
  }, [dispatchAction]);

  const setShapesMenuOpen = React.useCallback(
    (open: boolean) => {
      dispatchAction({ kind: "setShapesMenuOpen", open });
    },
    [dispatchAction],
  );

  const openContextualDiscovery = React.useCallback(
    (session: TDiscovery) => {
      dispatchAction({ kind: "openContextualDiscovery", session });
    },
    [dispatchAction],
  );

  const closeContextualDiscovery = React.useCallback(() => {
    dispatchAction({ kind: "closeContextualDiscovery" });
  }, [dispatchAction]);

  const toggleInspectedPipe = React.useCallback(
    (graphId: string | null, pipeId: string, anchor: XYPosition) => {
      dispatchAction({
        kind: "toggleInspectedPipe",
        graphId,
        pipeId,
        anchor,
      });
    },
    [dispatchAction],
  );

  const closeInspectedPipe = React.useCallback(() => {
    dispatchAction({ kind: "closeInspectedPipe" });
  }, [dispatchAction]);

  const pruneInspectedPipes = React.useCallback(
    (pipeIds: readonly string[]) => {
      dispatchAction({ kind: "pruneInspectedPipes", pipeIds });
    },
    [dispatchAction],
  );

  const openContextMenu = React.useCallback(
    (request: TContextMenu) => {
      dispatchAction({ kind: "openContextMenu", request });
    },
    [dispatchAction],
  );

  const closeContextMenu = React.useCallback(() => {
    dispatchAction({ kind: "closeContextMenu" });
  }, [dispatchAction]);

  const closeCanvasPopovers = React.useCallback(
    (closeExternal?: boolean) => {
      dispatchAction({ kind: "closeAllPopovers", closeExternal });
    },
    [dispatchAction],
  );

  const setPendingConnectionRoute = React.useCallback<
    React.Dispatch<React.SetStateAction<PendingConnectionRoute | null>>
  >(
    (update) => {
      dispatchAction({
        kind: "setPendingConnectionRoute",
        route: resolveSetState(update, stateRef.current.pendingConnectionRoute),
      });
    },
    [dispatchAction],
  );

  const setPendingFolderDrop = React.useCallback(
    (drop: PendingFolderDropState | null) => {
      dispatchAction({ kind: "setPendingFolderDrop", drop });
    },
    [dispatchAction],
  );

  const clearAuthoringError = React.useCallback(() => {
    dispatchAction({ kind: "clearError" });
  }, [dispatchAction]);

  const dismissAuthoringError = React.useCallback(
    (message: string) => {
      dispatchAction({ kind: "dismissError", message });
      setRunError((current) => (current === message ? null : current));
    },
    [dispatchAction, setRunError],
  );

  const popover = state.popover;
  const libraryOpen = popover.kind === "library";
  const shapesMenuOpen = popover.kind === "shapesMenu";

  return {
    state,
    dispatch: dispatchAction,
    authoredDocument: state.document,
    nodeOverlays: state.nodeOverlays,
    authoringError: state.error,
    authoredDocumentRef,
    nodeOverlaysRef,
    applyAuthoringCommands,
    replaceDocument,
    applyNodesSnapshot,
    selectedNodeIdSet: state.selectedNodeIds,
    setSelectedNodeIdSet,
    selectedEdgeIdSet: state.selectedEdgeIds,
    setSelectedEdgeIdSet,
    selectedAgentIds: state.selectedAgentIds,
    setSelectedAgentIds,
    positionOverrides: state.positionOverrides,
    setPositionOverrides,
    collapsedAppendices: state.collapsedAppendices,
    toggleAppendix,
    configSections: state.configSections,
    setConfigSection,
    fitRevision: state.fitRevision,
    requestCanvasRefit,
    canvasUpload: state.canvasUpload,
    setCanvasUpload,
    libraryOpen,
    libraryInsertAt: libraryOpen ? popover.insertAt : null,
    toggleLibrary,
    setLibraryOpen,
    shapesMenuOpen,
    toggleShapesMenu,
    setShapesMenuOpen,
    contextualDiscovery:
      popover.kind === "contextualDiscovery" ? popover.session : null,
    openContextualDiscovery,
    closeContextualDiscovery,
    inspectedPipe:
      popover.kind === "inspectedPipe"
        ? {
            graphId: popover.graphId,
            pipeId: popover.pipeId,
            anchor: popover.anchor,
          }
        : null,
    toggleInspectedPipe,
    closeInspectedPipe,
    pruneInspectedPipes,
    canvasMenu: popover.kind === "contextMenu" ? popover.request : null,
    openContextMenu,
    closeContextMenu,
    closeCanvasPopovers,
    pendingConnectionRoute: state.pendingConnectionRoute,
    setPendingConnectionRoute,
    pendingFolderDrop: state.pendingFolderDrop,
    setPendingFolderDrop,
    clearAuthoringError,
    dismissAuthoringError,
  };
}

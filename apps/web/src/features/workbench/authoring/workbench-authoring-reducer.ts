import type { NodeRegistry } from "@/lib/api";
import type { ExecEffect } from "@/lib/state/effect-reducer";

import type { ArtifactDropTarget } from "../artifacts/artifact-drop";
import type { PendingFolderDrop } from "../artifacts/ArtifactFolderDropDialog";
import {
  shouldBlockAuthoringCommand,
  type AuthoringCommandOptions,
} from "./authoring-command-guard";
import type { PendingConnectionRoute } from "./ConnectionRouteDialog";
import {
  collectionModeRepairCommands,
  foldCollectionModeRepairs,
} from "./edge-collection-modes";
import type { AuthoredGraphDocument, GraphCommand } from "./graph-document";
import {
  reduceWorkbenchAuthoringState,
  type NodeOverlays,
} from "./graph-document-adapter";
import type { XYPosition } from "./types";

/**
 * Pure authoring UI state for one open graph.
 *
 * Canvas popovers are one slot, so opening one closes the others. Discovery
 * sessions and context-menu requests stay generic: this slice must not import
 * the canvas or the shell that own those shapes.
 */
export interface PendingFolderDropState {
  readonly drop: PendingFolderDrop;
  readonly destination:
    | { readonly kind: "canvas"; readonly point: XYPosition }
    | { readonly kind: "input"; readonly target: ArtifactDropTarget };
}

export interface InspectedPipeState {
  readonly graphId: string | null;
  readonly pipeId: string;
  readonly anchor: XYPosition;
}

export type CanvasPopoverState<TDiscovery = unknown, TContextMenu = unknown> =
  | { readonly kind: "none" }
  | { readonly kind: "library"; readonly insertAt: XYPosition | null }
  | { readonly kind: "shapesMenu" }
  | { readonly kind: "contextualDiscovery"; readonly session: TDiscovery }
  | {
      readonly kind: "inspectedPipe";
      readonly graphId: string | null;
      readonly pipeId: string;
      readonly anchor: XYPosition;
    }
  | { readonly kind: "contextMenu"; readonly request: TContextMenu };

export interface WorkbenchAuthoringUiState<
  TDiscovery = unknown,
  TContextMenu = unknown,
> {
  readonly document: AuthoredGraphDocument;
  readonly nodeOverlays: NodeOverlays;
  readonly error: string | null;
  readonly selectedNodeIds: ReadonlySet<string>;
  readonly selectedEdgeIds: ReadonlySet<string>;
  readonly selectedAgentIds: ReadonlySet<string>;
  readonly positionOverrides: Readonly<Record<string, XYPosition>>;
  readonly collapsedAppendices: ReadonlySet<string>;
  /**
   * Config sections a person opened or closed on a card — a group, the
   * advanced fold, a nested object — by node id, then by section key. Only a
   * view of the card: it never reaches the document.
   */
  readonly configSections: Readonly<
    Record<string, Readonly<Record<string, boolean>>>
  >;
  readonly fitRevision: number;
  readonly canvasUpload: string | null;
  readonly popover: CanvasPopoverState<TDiscovery, TContextMenu>;
  readonly pendingConnectionRoute: PendingConnectionRoute | null;
  readonly pendingFolderDrop: PendingFolderDropState | null;
}

export type WorkbenchAuthoringUiAction<
  TDiscovery = unknown,
  TContextMenu = unknown,
> =
  | {
      readonly kind: "applyCommands";
      readonly commands: readonly GraphCommand[];
      readonly options?: AuthoringCommandOptions;
      readonly localAuthoringEnabled: boolean;
      readonly blockedMessage: string;
      readonly nodeRegistry: NodeRegistry | null;
    }
  | {
      readonly kind: "replaceDocument";
      readonly document: AuthoredGraphDocument;
      readonly nodeOverlays?: NodeOverlays;
    }
  | { readonly kind: "updateOverlays"; readonly update: NodeOverlays }
  | {
      readonly kind: "applyNodesSnapshot";
      readonly selectedNodeIds: ReadonlySet<string>;
      readonly positionOverrides: Readonly<Record<string, XYPosition>>;
      readonly nodeOverlays: NodeOverlays;
    }
  | { readonly kind: "setSelectedNodeIds"; readonly ids: ReadonlySet<string> }
  | { readonly kind: "setSelectedEdgeIds"; readonly ids: ReadonlySet<string> }
  | { readonly kind: "setSelectedAgentIds"; readonly ids: ReadonlySet<string> }
  | {
      readonly kind: "setPositionOverrides";
      readonly overrides: Readonly<Record<string, XYPosition>>;
    }
  | { readonly kind: "toggleAppendix"; readonly cardId: string }
  | {
      readonly kind: "setConfigSection";
      readonly cardId: string;
      readonly sectionKey: string;
      readonly open: boolean;
    }
  | { readonly kind: "requestCanvasRefit" }
  | { readonly kind: "setCanvasUpload"; readonly status: string | null }
  | {
      readonly kind: "toggleLibrary";
      readonly insertAt?: XYPosition | null;
    }
  | {
      readonly kind: "setLibraryOpen";
      readonly open: boolean;
      readonly insertAt?: XYPosition | null;
    }
  | { readonly kind: "toggleShapesMenu" }
  | { readonly kind: "setShapesMenuOpen"; readonly open: boolean }
  | { readonly kind: "openContextualDiscovery"; readonly session: TDiscovery }
  | { readonly kind: "closeContextualDiscovery" }
  | {
      readonly kind: "toggleInspectedPipe";
      readonly graphId: string | null;
      readonly pipeId: string;
      readonly anchor: XYPosition;
    }
  | { readonly kind: "closeInspectedPipe" }
  | {
      readonly kind: "pruneInspectedPipes";
      readonly pipeIds: readonly string[];
    }
  | { readonly kind: "openContextMenu"; readonly request: TContextMenu }
  | { readonly kind: "closeContextMenu" }
  | { readonly kind: "closeAllPopovers"; readonly closeExternal?: boolean }
  | {
      readonly kind: "setPendingConnectionRoute";
      readonly route: PendingConnectionRoute | null;
    }
  | {
      readonly kind: "setPendingFolderDrop";
      readonly drop: PendingFolderDropState | null;
    }
  | { readonly kind: "clearError" }
  | { readonly kind: "dismissError"; readonly message: string };

export type WorkbenchAuthoringUiEffect =
  | { readonly kind: "reportBlockedError"; readonly message: string }
  | { readonly kind: "clearRunError" }
  | {
      readonly kind: "pruneArtifactViewerEdges";
      readonly nodeIds: readonly string[];
    }
  | {
      readonly kind: "syncRoomCommands";
      readonly commands: readonly GraphCommand[];
      readonly before: AuthoredGraphDocument;
    }
  | { readonly kind: "closeGraphBrowser" }
  | { readonly kind: "closeGridPanel" };

export const DEFAULT_AUTHORED_DOCUMENT: AuthoredGraphDocument = {
  name: "Untitled workflow",
  nodes: [],
  edges: [],
  origins: [],
  agents: [],
};

const EMPTY_IDS: ReadonlySet<string> = new Set();
const EMPTY_CONFIG_SECTIONS: WorkbenchAuthoringUiState["configSections"] = {};
const EMPTY_OVERRIDES: Readonly<Record<string, XYPosition>> = {};
const EMPTY_OVERLAYS: NodeOverlays = {};
const CLOSED_POPOVER: { readonly kind: "none" } = { kind: "none" };
const SHAPES_POPOVER: { readonly kind: "shapesMenu" } = { kind: "shapesMenu" };

export function initialWorkbenchAuthoringUiState<
  TDiscovery = unknown,
  TContextMenu = unknown,
>(): WorkbenchAuthoringUiState<TDiscovery, TContextMenu> {
  return {
    document: DEFAULT_AUTHORED_DOCUMENT,
    nodeOverlays: EMPTY_OVERLAYS,
    error: null,
    selectedNodeIds: EMPTY_IDS,
    selectedEdgeIds: EMPTY_IDS,
    selectedAgentIds: EMPTY_IDS,
    positionOverrides: EMPTY_OVERRIDES,
    collapsedAppendices: EMPTY_IDS,
    configSections: EMPTY_CONFIG_SECTIONS,
    fitRevision: 0,
    canvasUpload: null,
    popover: CLOSED_POPOVER,
    pendingConnectionRoute: null,
    pendingFolderDrop: null,
  };
}

type AuthoringExec = ExecEffect<WorkbenchAuthoringUiEffect>;

export function workbenchAuthoringUiReducer<
  TDiscovery = unknown,
  TContextMenu = unknown,
>(
  state: WorkbenchAuthoringUiState<TDiscovery, TContextMenu>,
  action: WorkbenchAuthoringUiAction<TDiscovery, TContextMenu>,
  exec: AuthoringExec,
): WorkbenchAuthoringUiState<TDiscovery, TContextMenu> {
  switch (action.kind) {
    case "applyCommands":
      return applyCommands(state, action, exec);
    case "replaceDocument":
      return replaceDocument(state, action);
    case "updateOverlays":
      if (action.update === state.nodeOverlays) return state;
      return { ...state, nodeOverlays: action.update };
    case "applyNodesSnapshot":
      if (
        action.selectedNodeIds === state.selectedNodeIds &&
        action.positionOverrides === state.positionOverrides &&
        action.nodeOverlays === state.nodeOverlays
      ) {
        return state;
      }
      return {
        ...state,
        selectedNodeIds: action.selectedNodeIds,
        positionOverrides: action.positionOverrides,
        nodeOverlays: action.nodeOverlays,
      };
    case "setSelectedNodeIds":
      if (action.ids === state.selectedNodeIds) return state;
      return { ...state, selectedNodeIds: action.ids };
    case "setSelectedEdgeIds":
      if (action.ids === state.selectedEdgeIds) return state;
      return { ...state, selectedEdgeIds: action.ids };
    case "setSelectedAgentIds":
      if (action.ids === state.selectedAgentIds) return state;
      return { ...state, selectedAgentIds: action.ids };
    case "setPositionOverrides":
      if (action.overrides === state.positionOverrides) return state;
      return { ...state, positionOverrides: action.overrides };
    case "toggleAppendix":
      return {
        ...state,
        collapsedAppendices: toggledSet(
          state.collapsedAppendices,
          action.cardId,
        ),
      };
    case "setConfigSection": {
      const card = state.configSections[action.cardId];
      if (card?.[action.sectionKey] === action.open) return state;
      return {
        ...state,
        configSections: {
          ...state.configSections,
          [action.cardId]: { ...card, [action.sectionKey]: action.open },
        },
      };
    }
    case "requestCanvasRefit":
      return { ...state, fitRevision: state.fitRevision + 1 };
    case "setCanvasUpload":
      if (action.status === state.canvasUpload) return state;
      return { ...state, canvasUpload: action.status };
    case "toggleLibrary":
      if (state.popover.kind === "library") {
        return { ...state, popover: CLOSED_POPOVER };
      }
      return openExclusivePopover(state, libraryPopover(action.insertAt), exec);
    case "setLibraryOpen":
      if (!action.open) return closePopoverKind(state, "library");
      return openLibrary(state, action.insertAt, exec);
    case "toggleShapesMenu":
      if (state.popover.kind === "shapesMenu") {
        return { ...state, popover: CLOSED_POPOVER };
      }
      return openExclusivePopover(state, SHAPES_POPOVER, exec);
    case "setShapesMenuOpen":
      if (!action.open) return closePopoverKind(state, "shapesMenu");
      return openExclusivePopover(state, SHAPES_POPOVER, exec);
    case "openContextualDiscovery":
      if (
        state.popover.kind === "contextualDiscovery" &&
        Object.is(state.popover.session, action.session)
      ) {
        return state;
      }
      return {
        ...state,
        popover: { kind: "contextualDiscovery", session: action.session },
      };
    case "closeContextualDiscovery":
      return closePopoverKind(state, "contextualDiscovery");
    case "toggleInspectedPipe":
      if (
        state.popover.kind === "inspectedPipe" &&
        state.popover.pipeId === action.pipeId
      ) {
        return { ...state, popover: CLOSED_POPOVER };
      }
      return {
        ...state,
        popover: {
          kind: "inspectedPipe",
          graphId: action.graphId,
          pipeId: action.pipeId,
          anchor: action.anchor,
        },
      };
    case "closeInspectedPipe":
      return closePopoverKind(state, "inspectedPipe");
    case "pruneInspectedPipes":
      if (
        state.popover.kind === "inspectedPipe" &&
        action.pipeIds.includes(state.popover.pipeId)
      ) {
        return { ...state, popover: CLOSED_POPOVER };
      }
      return state;
    case "openContextMenu":
      return openExclusivePopover(
        state,
        { kind: "contextMenu", request: action.request },
        exec,
      );
    case "closeContextMenu":
      return closePopoverKind(state, "contextMenu");
    case "closeAllPopovers":
      if (action.closeExternal !== false) emitExternalCloses(exec);
      if (state.popover.kind === "none") return state;
      return { ...state, popover: CLOSED_POPOVER };
    case "setPendingConnectionRoute":
      if (action.route === state.pendingConnectionRoute) return state;
      return { ...state, pendingConnectionRoute: action.route };
    case "setPendingFolderDrop":
      if (action.drop === state.pendingFolderDrop) return state;
      return { ...state, pendingFolderDrop: action.drop };
    case "clearError":
      if (state.error === null) return state;
      return { ...state, error: null };
    case "dismissError":
      if (state.error !== action.message) return state;
      return { ...state, error: null };
    default: {
      const unreachable: never = action;
      return unreachable;
    }
  }
}

function applyCommands<TDiscovery, TContextMenu>(
  state: WorkbenchAuthoringUiState<TDiscovery, TContextMenu>,
  action: Extract<
    WorkbenchAuthoringUiAction<TDiscovery, TContextMenu>,
    { kind: "applyCommands" }
  >,
  exec: AuthoringExec,
): WorkbenchAuthoringUiState<TDiscovery, TContextMenu> {
  if (action.commands.length === 0) return state;
  if (
    shouldBlockAuthoringCommand(action.localAuthoringEnabled, action.options)
  ) {
    exec({ kind: "reportBlockedError", message: action.blockedMessage });
    return state;
  }

  const reduced = reduceWorkbenchAuthoringState(
    { document: state.document, nodeOverlays: state.nodeOverlays, error: null },
    { kind: "apply_commands", commands: action.commands },
  );
  if (reduced.error !== null) {
    return { ...state, error: reduced.error };
  }

  const repairs = collectionModeRepairCommands(
    reduced.document,
    action.nodeRegistry,
  );
  const after =
    repairs.length > 0
      ? reduceWorkbenchAuthoringState(reduced, {
          kind: "apply_commands",
          commands: repairs,
        })
      : reduced;

  const removedNodes = removedNodeIds(action.commands);
  if (removedNodes.length > 0) {
    exec({ kind: "pruneArtifactViewerEdges", nodeIds: removedNodes });
  }
  exec({ kind: "clearRunError" });
  if (action.options?.syncRoom !== false) {
    exec({
      kind: "syncRoomCommands",
      commands: foldCollectionModeRepairs(action.commands, repairs),
      before: state.document,
    });
  }

  return {
    ...state,
    document: after.document,
    nodeOverlays: after.nodeOverlays,
    error: after.error,
    selectedNodeIds: pruneIdSet(
      state.selectedNodeIds,
      idsOf(after.document.nodes),
    ),
    selectedEdgeIds: pruneIdSet(
      state.selectedEdgeIds,
      idsOf(after.document.edges),
    ),
    selectedAgentIds: pruneIdSet(
      state.selectedAgentIds,
      idsOf(after.document.agents),
    ),
    positionOverrides: EMPTY_OVERRIDES,
    pendingConnectionRoute: null,
  };
}

function replaceDocument<TDiscovery, TContextMenu>(
  state: WorkbenchAuthoringUiState<TDiscovery, TContextMenu>,
  action: Extract<
    WorkbenchAuthoringUiAction<TDiscovery, TContextMenu>,
    { kind: "replaceDocument" }
  >,
): WorkbenchAuthoringUiState<TDiscovery, TContextMenu> {
  const providedOverlays = action.nodeOverlays ?? EMPTY_OVERLAYS;
  const normalized = reduceWorkbenchAuthoringState(
    {
      document: action.document,
      nodeOverlays: providedOverlays,
      error: null,
    },
    {
      kind: "replace_document",
      document: action.document,
      nodeOverlays: providedOverlays,
    },
  );
  const nodeOverlays =
    action.nodeOverlays === undefined
      ? overlaysPresentOnNodes(state.nodeOverlays, normalized.document.nodes)
      : normalized.nodeOverlays;
  return {
    ...state,
    document: normalized.document,
    nodeOverlays,
    error: null,
    selectedNodeIds: EMPTY_IDS,
    selectedEdgeIds: EMPTY_IDS,
    selectedAgentIds: EMPTY_IDS,
    positionOverrides: EMPTY_OVERRIDES,
  };
}

function openLibrary<TDiscovery, TContextMenu>(
  state: WorkbenchAuthoringUiState<TDiscovery, TContextMenu>,
  insertAt: XYPosition | null | undefined,
  exec: AuthoringExec,
): WorkbenchAuthoringUiState<TDiscovery, TContextMenu> {
  const nextInsertAt = insertAt ?? null;
  const unchanged =
    state.popover.kind === "library" &&
    samePoint(state.popover.insertAt, nextInsertAt);
  emitExternalCloses(exec);
  if (unchanged) return state;
  return { ...state, popover: libraryPopover(nextInsertAt) };
}

function openExclusivePopover<TDiscovery, TContextMenu>(
  state: WorkbenchAuthoringUiState<TDiscovery, TContextMenu>,
  popover: CanvasPopoverState<TDiscovery, TContextMenu>,
  exec: AuthoringExec,
): WorkbenchAuthoringUiState<TDiscovery, TContextMenu> {
  emitExternalCloses(exec);
  if (state.popover.kind === "shapesMenu" && popover.kind === "shapesMenu") {
    return state;
  }
  return { ...state, popover };
}

function emitExternalCloses(exec: AuthoringExec): void {
  exec({ kind: "closeGraphBrowser" });
  exec({ kind: "closeGridPanel" });
}

function closePopoverKind<TDiscovery, TContextMenu>(
  state: WorkbenchAuthoringUiState<TDiscovery, TContextMenu>,
  kind: CanvasPopoverState<TDiscovery, TContextMenu>["kind"],
): WorkbenchAuthoringUiState<TDiscovery, TContextMenu> {
  if (state.popover.kind !== kind) return state;
  return { ...state, popover: CLOSED_POPOVER };
}

function libraryPopover(insertAt: XYPosition | null | undefined): {
  readonly kind: "library";
  readonly insertAt: XYPosition | null;
} {
  return { kind: "library", insertAt: insertAt ?? null };
}

function samePoint(left: XYPosition | null, right: XYPosition | null): boolean {
  if (left === right) return true;
  if (left === null || right === null) return false;
  return left.x === right.x && left.y === right.y;
}

function removedNodeIds(commands: readonly GraphCommand[]): string[] {
  const nodeIds: string[] = [];
  for (const command of commands) {
    if (command.kind !== "remove_nodes") continue;
    for (const nodeId of command.node_ids) nodeIds.push(nodeId);
  }
  return nodeIds;
}

function idsOf(items: readonly { readonly id: string }[]): Set<string> {
  const ids = new Set<string>();
  for (const item of items) ids.add(item.id);
  return ids;
}

function pruneIdSet(
  selected: ReadonlySet<string>,
  liveIds: ReadonlySet<string>,
): ReadonlySet<string> {
  for (const id of selected) {
    if (!liveIds.has(id)) {
      const next = new Set<string>();
      for (const candidate of selected) {
        if (liveIds.has(candidate)) next.add(candidate);
      }
      return next;
    }
  }
  return selected;
}

function toggledSet(
  current: ReadonlySet<string>,
  id: string,
): ReadonlySet<string> {
  const next = new Set(current);
  if (!next.delete(id)) next.add(id);
  return next;
}

function overlaysPresentOnNodes(
  overlays: NodeOverlays,
  nodes: AuthoredGraphDocument["nodes"],
): NodeOverlays {
  const live = idsOf(nodes);
  let dropped = false;
  const next: NodeOverlays = {};
  for (const [nodeId, overlay] of Object.entries(overlays)) {
    if (!live.has(nodeId)) {
      dropped = true;
      continue;
    }
    next[nodeId] = overlay;
  }
  return dropped ? next : overlays;
}

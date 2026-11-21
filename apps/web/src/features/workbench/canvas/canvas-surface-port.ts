import type {
  CellConnectDropEmptyEvent,
  CellViewportApi,
} from "../cell-canvas/cell-contracts";
import type { WorldPoint } from "../cell-canvas/cell-model";
import type { WorldBounds } from "../cell-canvas/use-cell-viewport";
import type { GraphCommand } from "../model/graph-document";

export type WorkbenchCanvasEngineKind = "react-flow" | "cell-canvas";

export const DEFAULT_WORKBENCH_CANVAS_ENGINE: WorkbenchCanvasEngineKind =
  "cell-canvas";

export const WORKBENCH_CANVAS_ENGINE_STORAGE_KEY =
  "grafy.workbench.canvasEngine";

export function isWorkbenchCanvasEngineKind(
  value: unknown,
): value is WorkbenchCanvasEngineKind {
  return value === "react-flow" || value === "cell-canvas";
}

function browserStorage(): Storage | null {
  return typeof window === "undefined" ? null : window.localStorage;
}

export function readCanvasEnginePreference(
  storage?: Pick<Storage, "getItem"> | null,
): WorkbenchCanvasEngineKind {
  try {
    const target = storage === undefined ? browserStorage() : storage;
    const value = target?.getItem(WORKBENCH_CANVAS_ENGINE_STORAGE_KEY);
    if (isWorkbenchCanvasEngineKind(value)) return value;
  } catch {
    // The browser can restrict access to device-local preferences.
  }
  return DEFAULT_WORKBENCH_CANVAS_ENGINE;
}

export function writeCanvasEnginePreference(
  kind: WorkbenchCanvasEngineKind,
  storage?: Pick<Storage, "setItem"> | null,
): void {
  try {
    const target = storage === undefined ? browserStorage() : storage;
    target?.setItem(WORKBENCH_CANVAS_ENGINE_STORAGE_KEY, kind);
  } catch {
    // A storage failure does not prevent switching engines in memory.
  }
}

export interface WorkbenchCanvasViewportHandle {
  getViewport(): { x: number; y: number; zoom: number };
  fitBounds(bounds: WorldBounds, paddingRatio?: number, maxZoom?: number): void;
  screenToWorld(clientX: number, clientY: number): WorldPoint;
  worldToScreen(world: WorldPoint): WorldPoint;
  zoomBy(factor: number): void;
}

export interface WorkbenchCanvasSurfaceCapabilities {
  readonly supportsGroupDrag: boolean;
  readonly supportsCellResize: boolean;
  readonly supportsDockedJoins: boolean;
  readonly supportsRemoteCursors: boolean;
  readonly supportsUnderCardsAnnotations: boolean;
}

export interface WorkbenchCanvasSurfaceCallbacks {
  onCommitCommands?: (commands: readonly GraphCommand[]) => void;
  onConnectDropEmpty?: (event: CellConnectDropEmptyEvent) => void;
  onSelectEdgeAttachment?: (pipeId: string, anchor?: WorldPoint) => void;
  onRemoveEdgeAttachment?: (pipeId: string) => void;
  onRunNode?: (cardId: string) => void;
}

export function createViewportHandleFromCellApi(
  api: CellViewportApi,
): WorkbenchCanvasViewportHandle {
  return {
    getViewport() {
      const { x, y, zoom } = api.viewport;
      return { x, y, zoom };
    },
    fitBounds(bounds, paddingRatio, maxZoom) {
      api.fitRect(bounds, paddingRatio, maxZoom);
    },
    screenToWorld(clientX, clientY) {
      return api.screenToWorld(clientX, clientY);
    },
    worldToScreen(world) {
      return api.worldToScreen(world);
    },
    zoomBy(factor) {
      api.zoomBy(factor);
    },
  };
}

export function defaultCapabilitiesForEngine(
  kind: WorkbenchCanvasEngineKind,
): WorkbenchCanvasSurfaceCapabilities {
  return {
    supportsGroupDrag: true,
    supportsCellResize: kind === "cell-canvas",
    supportsDockedJoins: kind === "cell-canvas",
    supportsRemoteCursors: true,
    supportsUnderCardsAnnotations: true,
  };
}

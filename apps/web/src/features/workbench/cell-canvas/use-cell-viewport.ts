"use client";

import * as React from "react";

import type { StageViewport } from "./cell-glass-stage";
import type { WorldPoint } from "./cell-model";

/**
 * Pan and zoom for the cell canvas, applied by the caller as a CSS transform
 * (`translate(x, y) scale(zoom)`) on the world plane inside `containerRef`.
 *
 * The latest viewport also lives in a ref, so pointer and wheel handlers and
 * {@link UseCellViewportResult.screenToWorld} never read a stale render.
 */

export interface WorldBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface UseCellViewportOptions {
  /** Default 0.15. */
  minZoom?: number;
  /** Default 2. */
  maxZoom?: number;
  /** Default `{ x: 0, y: 0, zoom: 1 }`. */
  initialViewport?: StageViewport;
  /**
   * Extra left inset (in screen pixels) preserved on wide canvases (> 800px),
   * e.g. for a docked floating inspector panel on the left. Default `0`.
   */
  fitLeftClearance?: number;
}

export interface UseCellViewportResult {
  viewport: StageViewport;
  panning: boolean;
  setViewport: React.Dispatch<React.SetStateAction<StageViewport>>;
  zoomAtCenter: (nextZoom: number) => void;
  zoomBy: (factor: number) => void;
  fitRect: (
    bounds: WorldBounds,
    paddingRatio?: number,
    maxZoom?: number,
  ) => void;
  viewAt: (
    worldX: number,
    worldY: number,
    zoom: number,
    screenX?: number,
    screenY?: number,
  ) => StageViewport;
  screenToWorld: (clientX: number, clientY: number) => WorldPoint;
  worldToScreen: (world: WorldPoint) => WorldPoint;
  onBackgroundPointerDown: (event: React.PointerEvent<HTMLElement>) => void;
}

const DEFAULT_VIEWPORT: StageViewport = { x: 0, y: 0, zoom: 1 };
/** Container size assumed before it is mounted or laid out. */
const FALLBACK_WIDTH = 1400;
const FALLBACK_HEIGHT = 860;
const RIGHT_MARGIN = 32;
const WIDE_CANVAS = 800;
/** Zoom change per wheel pixel when pinching or holding Ctrl/Cmd. */
const WHEEL_ZOOM_RATE = 0.01;
/** Caps one wheel notch so a mouse zooms in steps, not jumps. */
const WHEEL_ZOOM_MAX_DELTA = 60;
const LINE_HEIGHT_PX = 16;

interface ContainerBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

function containerBox(element: HTMLElement | null): ContainerBox | null {
  if (!element) return null;
  const rect = element.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;
  return {
    left: rect.left,
    top: rect.top,
    width: rect.width,
    height: rect.height,
  };
}

/** Wheel deltas in pixels, whatever unit the device reported. */
function wheelPixels(event: WheelEvent, pageHeight: number): WorldPoint {
  const scale =
    event.deltaMode === WheelEvent.DOM_DELTA_LINE
      ? LINE_HEIGHT_PX
      : event.deltaMode === WheelEvent.DOM_DELTA_PAGE
        ? pageHeight
        : 1;
  return { x: event.deltaX * scale, y: event.deltaY * scale };
}

/** The viewport that keeps the screen point `(sx, sy)` over the same world point. */
function zoomAround(
  view: StageViewport,
  zoom: number,
  sx: number,
  sy: number,
): StageViewport {
  const worldX = (sx - view.x) / view.zoom;
  const worldY = (sy - view.y) / view.zoom;
  return { x: sx - worldX * zoom, y: sy - worldY * zoom, zoom };
}

export function useCellViewport(
  containerRef: React.RefObject<HTMLElement | null>,
  options: UseCellViewportOptions = {},
): UseCellViewportResult {
  const {
    minZoom = 0.15,
    maxZoom = 2,
    initialViewport,
    fitLeftClearance = 0,
  } = options;
  const [viewport, setViewportState] = React.useState<StageViewport>(
    () => initialViewport ?? DEFAULT_VIEWPORT,
  );
  const [panning, setPanning] = React.useState(false);
  const viewportRef = React.useRef(viewport);
  const stopPanRef = React.useRef<(() => void) | null>(null);

  const clampZoom = React.useCallback(
    (zoom: number) => {
      if (!Number.isFinite(zoom)) return viewportRef.current.zoom;
      return Math.min(Math.max(zoom, minZoom), maxZoom);
    },
    [minZoom, maxZoom],
  );

  const apply = React.useCallback((next: StageViewport) => {
    viewportRef.current = next;
    setViewportState(next);
  }, []);

  const setViewport = React.useCallback<
    React.Dispatch<React.SetStateAction<StageViewport>>
  >(
    (action) => {
      const next =
        typeof action === "function" ? action(viewportRef.current) : action;
      apply({ ...next, zoom: clampZoom(next.zoom) });
    },
    [apply, clampZoom],
  );

  React.useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = element.getBoundingClientRect();
      const delta = wheelPixels(event, rect.height || FALLBACK_HEIGHT);
      const current = viewportRef.current;
      if (event.ctrlKey || event.metaKey) {
        const step = Math.min(
          Math.max(delta.y, -WHEEL_ZOOM_MAX_DELTA),
          WHEEL_ZOOM_MAX_DELTA,
        );
        const zoom = clampZoom(
          current.zoom * Math.exp(-step * WHEEL_ZOOM_RATE),
        );
        if (zoom === current.zoom) return;
        apply(
          zoomAround(
            current,
            zoom,
            event.clientX - rect.left,
            event.clientY - rect.top,
          ),
        );
        return;
      }
      apply({ ...current, x: current.x - delta.x, y: current.y - delta.y });
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [containerRef, apply, clampZoom]);

  // A pan in flight releases its window listeners with the canvas.
  React.useEffect(() => () => stopPanRef.current?.(), []);

  const onBackgroundPointerDown = React.useCallback(
    (event: React.PointerEvent<HTMLElement>) => {
      if (event.button !== 0 && event.button !== 1) return;
      // The middle button would otherwise start the browser's autoscroll.
      if (event.button === 1) event.preventDefault();
      stopPanRef.current?.();

      const pointerId = event.pointerId;
      let lastX = event.clientX;
      let lastY = event.clientY;
      function onMove(move: PointerEvent) {
        if (move.pointerId !== pointerId) return;
        const dx = move.clientX - lastX;
        const dy = move.clientY - lastY;
        lastX = move.clientX;
        lastY = move.clientY;
        if (dx === 0 && dy === 0) return;
        const current = viewportRef.current;
        apply({ ...current, x: current.x + dx, y: current.y + dy });
      }
      function onEnd(end: PointerEvent) {
        if (end.pointerId === pointerId) stop();
      }
      function stop() {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onEnd);
        window.removeEventListener("pointercancel", onEnd);
        if (stopPanRef.current === stop) stopPanRef.current = null;
        setPanning(false);
      }
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onEnd);
      window.addEventListener("pointercancel", onEnd);
      stopPanRef.current = stop;
      setPanning(true);
    },
    [apply],
  );

  const viewAt = React.useCallback(
    (
      worldX: number,
      worldY: number,
      zoom: number,
      screenX?: number,
      screenY?: number,
    ): StageViewport => {
      const box = containerBox(containerRef.current);
      const sx = screenX ?? (box ? box.width / 2 : 700);
      const sy = screenY ?? (box ? box.height / 2 : 430);
      const z = clampZoom(zoom);
      const next = { x: sx - worldX * z, y: sy - worldY * z, zoom: z };
      apply(next);
      return next;
    },
    [containerRef, apply, clampZoom],
  );

  const zoomAtCenter = React.useCallback(
    (nextZoom: number) => {
      const box = containerBox(containerRef.current);
      const width = box?.width ?? FALLBACK_WIDTH;
      const height = box?.height ?? FALLBACK_HEIGHT;
      apply(
        zoomAround(
          viewportRef.current,
          clampZoom(nextZoom),
          width / 2,
          height / 2,
        ),
      );
    },
    [containerRef, apply, clampZoom],
  );

  const zoomBy = React.useCallback(
    (factor: number) => zoomAtCenter(viewportRef.current.zoom * factor),
    [zoomAtCenter],
  );

  const fitRect = React.useCallback(
    (bounds: WorldBounds, paddingRatio = 0.14, fitMaxZoom = 0.92) => {
      const box = containerBox(containerRef.current);
      const width = box?.width ?? FALLBACK_WIDTH;
      const height = box?.height ?? FALLBACK_HEIGHT;
      // On a wide canvas, honor any left clearance (such as a floating panel).
      const wide = width > WIDE_CANVAS;
      const left = wide ? fitLeftClearance : 0;
      const right = wide ? width - RIGHT_MARGIN : width;
      const usable = 1 - Math.min(Math.max(paddingRatio, 0), 0.9);
      const zoom = Math.min(
        ((right - left) * usable) / Math.max(bounds.width, 1),
        (height * usable) / Math.max(bounds.height, 1),
        fitMaxZoom,
      );
      viewAt(
        bounds.x + bounds.width / 2,
        bounds.y + bounds.height / 2,
        zoom,
        (left + right) / 2,
        height / 2,
      );
    },
    [containerRef, fitLeftClearance, viewAt],
  );

  const screenToWorld = React.useCallback(
    (clientX: number, clientY: number): WorldPoint => {
      const rect = containerRef.current?.getBoundingClientRect();
      const { x, y, zoom } = viewportRef.current;
      return {
        x: (clientX - (rect?.left ?? 0) - x) / zoom,
        y: (clientY - (rect?.top ?? 0) - y) / zoom,
      };
    },
    [containerRef],
  );

  const worldToScreen = React.useCallback(
    (world: WorldPoint): WorldPoint => {
      const box = containerBox(containerRef.current);
      const left = box?.left ?? 0;
      const top = box?.top ?? 0;
      const view = viewportRef.current;
      return {
        x: left + view.x + world.x * view.zoom,
        y: top + view.y + world.y * view.zoom,
      };
    },
    [containerRef],
  );

  return {
    viewport,
    panning,
    setViewport,
    zoomAtCenter,
    zoomBy,
    fitRect,
    viewAt,
    screenToWorld,
    worldToScreen,
    onBackgroundPointerDown,
  };
}

"use client";

import { useEffect, useRef, useState, type PointerEvent } from "react";
import { createPortal } from "react-dom";
import * as stylex from "@stylexjs/stylex";
import type OpenSeadragon from "openseadragon";
import { tokens } from "@/lib/stylex/tokens.stylex";

const MAX_WINDOW_PIXELS = 1_000_000;

const s = stylex.create({
  target: {
    position: "absolute",
    inset: 0,
    zIndex: 1,
    touchAction: "none",
    cursor: "crosshair",
  },
  hint: {
    position: "absolute",
    top: 4,
    left: 4,
    right: 4,
    zIndex: 2,
    pointerEvents: "none",
    padding: "4px 6px",
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
});

export type TiffWindow = {
  page: number;
  col: number;
  row: number;
  width: number;
  height: number;
};

export type TiffWindowSelection = {
  window: TiffWindow;
  wholePage?: boolean;
  singleCrop?: boolean;
  onChange: (window: TiffWindow) => void;
};

export function readTiffWindow(
  config: Record<string, unknown>,
): TiffWindow | null {
  const { page, col, row, width, height } = config;
  const pixel = (value: unknown): value is number =>
    typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
  if (
    !pixel(page) ||
    !pixel(col) ||
    !pixel(row) ||
    !pixel(width) ||
    width === 0 ||
    !pixel(height) ||
    height === 0
  )
    return null;
  return { page, col, row, width, height };
}

type Size = { width: number; height: number };
type Point = { x: number; y: number };
type Drag = {
  pointerId: number;
  start: Point;
  original: TiffWindow;
  move: boolean;
};

const clamp = (value: number, max: number) => Math.min(max, Math.max(0, value));

function sameWindow(a: TiffWindow, b: TiffWindow) {
  return (
    a.page === b.page &&
    a.col === b.col &&
    a.row === b.row &&
    a.width === b.width &&
    a.height === b.height
  );
}

function windowFromDrag(drag: Drag, point: Point, size: Size): TiffWindow {
  const { start, original } = drag;
  if (drag.move) {
    return {
      ...original,
      col: clamp(original.col + point.x - start.x, size.width - original.width),
      row: clamp(
        original.row + point.y - start.y,
        size.height - original.height,
      ),
    };
  }
  const x = clamp(point.x, size.width);
  const y = clamp(point.y, size.height);
  return {
    page: original.page,
    col: Math.min(start.x, x),
    row: Math.min(start.y, y),
    width: Math.abs(x - start.x),
    height: Math.abs(y - start.y),
  };
}

export function TiffWindowSelector({
  viewer,
  PixelPoint,
  size,
  selection,
  editing,
}: {
  viewer: OpenSeadragon.Viewer;
  PixelPoint: typeof OpenSeadragon.Point;
  size: Size;
  selection: TiffWindowSelection;
  editing: boolean;
}) {
  const [layer] = useState(() => {
    const element = document.createElement("div");
    element.style.pointerEvents = "none";
    return element;
  });
  const drag = useRef<Drag | null>(null);
  const target = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState<TiffWindow | null>(null);
  const [tooLarge, setTooLarge] = useState(false);
  const window = selection.window;

  useEffect(() => {
    const image = viewer.world.getItemAt(0);
    viewer.addOverlay(
      layer,
      image.imageToViewportRectangle(0, 0, size.width, size.height),
    );
    return () => {
      viewer.removeOverlay(layer);
    };
  }, [viewer, layer, size.width, size.height]);

  function pixelAt(event: PointerEvent<HTMLDivElement>): Point | null {
    const image = viewer.world.getItemAt(0);
    const element = event.currentTarget;
    const bounds = element.getBoundingClientRect();
    if (!image || !bounds.width || !bounds.height) return null;
    // Client coordinates include React Flow's canvas zoom. OSD uses the
    // viewer's unscaled layout pixels.
    const point = image.viewerElementToImageCoordinates(
      new PixelPoint(
        ((event.clientX - bounds.left) * element.clientWidth) / bounds.width,
        ((event.clientY - bounds.top) * element.clientHeight) / bounds.height,
      ),
    );
    return { x: Math.round(point.x), y: Math.round(point.y) };
  }

  function clearDrag() {
    const active = drag.current;
    drag.current = null;
    setDraft(null);
    if (active && target.current?.hasPointerCapture(active.pointerId)) {
      target.current.releasePointerCapture(active.pointerId);
    }
  }

  function startDrag(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || drag.current) return;
    const start = pixelAt(event);
    if (
      !start ||
      start.x < 0 ||
      start.y < 0 ||
      start.x >= size.width ||
      start.y >= size.height
    )
      return;
    event.stopPropagation();
    event.currentTarget.focus({ preventScroll: true });
    event.currentTarget.setPointerCapture(event.pointerId);
    setTooLarge(false);
    drag.current = {
      pointerId: event.pointerId,
      start,
      original: window,
      move:
        start.x >= window.col &&
        start.x < window.col + window.width &&
        start.y >= window.row &&
        start.y < window.row + window.height &&
        window.col + window.width <= size.width &&
        window.row + window.height <= size.height,
    };
  }

  function updateDrag(event: PointerEvent<HTMLDivElement>, commit: boolean) {
    const active = drag.current;
    if (active?.pointerId !== event.pointerId) return;
    event.stopPropagation();
    const point = pixelAt(event);
    if (!point || !sameWindow(active.original, window)) {
      clearDrag();
      return;
    }
    const next = windowFromDrag(active, point, size);
    if (!commit) {
      setDraft(next);
      return;
    }
    clearDrag();
    if (selection.singleCrop && next.width * next.height > MAX_WINDOW_PIXELS) {
      setTooLarge(true);
    } else if (next.width > 0 && next.height > 0 && !sameWindow(next, window)) {
      selection.onChange(next);
    }
  }

  const shown = (editing && draft) || window;
  return (
    <>
      {createPortal(
        <svg
          viewBox={`0 0 ${size.width} ${size.height}`}
          width="100%"
          height="100%"
          role="img"
          aria-label="Detection window"
        >
          <rect
            x={shown.col}
            y={shown.row}
            width={shown.width}
            height={shown.height}
            fill="deepskyblue"
            fillOpacity={editing ? 0.14 : 0.04}
            stroke="deepskyblue"
            strokeWidth={2}
            vectorEffect="non-scaling-stroke"
          />
        </svg>,
        layer,
      )}
      {editing && (
        <>
          <div
            ref={target}
            {...stylex.props(s.target)}
            tabIndex={-1}
            aria-label="Draw or move the detection window"
            onPointerDown={startDrag}
            onPointerMove={(event) => updateDrag(event, false)}
            onPointerUp={(event) => updateDrag(event, true)}
            onPointerCancel={(event) => {
              if (event.pointerId === drag.current?.pointerId) clearDrag();
            }}
            onLostPointerCapture={(event) => {
              if (event.pointerId === drag.current?.pointerId) clearDrag();
            }}
          />
          <div role="status" {...stylex.props(s.hint)}>
            {tooLarge
              ? "Single crop supports up to 1,000,000 pixels. Choose Automatic for a larger area."
              : `${shown.width} × ${shown.height} px · Drag inside to move, outside to draw`}
          </div>
        </>
      )}
    </>
  );
}

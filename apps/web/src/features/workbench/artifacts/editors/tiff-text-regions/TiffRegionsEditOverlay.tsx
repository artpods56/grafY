"use client";

import {
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent,
} from "react";
import { createPortal } from "react-dom";
import * as stylex from "@stylexjs/stylex";
import type OpenSeadragon from "openseadragon";

import { readingLabel, svgNamespace } from "../../tiff-reading-label";
import {
  draftPolygon,
  type TiffPageSize,
  type TiffTextRegionsEditorAction,
  type TiffTextRegionsEditorState,
} from "./tiff-text-regions-editor-reducer";
import {
  MIN_POLYGON_VERTICES,
  type EditableTextRegion,
  type PixelPoint,
} from "./types";

export interface TiffRegionsEditOverlayProps {
  viewer: OpenSeadragon.Viewer;
  PixelPoint: typeof OpenSeadragon.Point;
  pageSize: TiffPageSize;
  state: TiffTextRegionsEditorState;
  dispatch: React.Dispatch<TiffTextRegionsEditorAction>;
}

const scaleEvents = ["zoom", "pan", "animation", "resize", "open"] as const;
const highlight = "#2563eb";
const midpointScale = 0.7;

const s = stylex.create({
  drawTarget: {
    position: "absolute",
    inset: 0,
    zIndex: 1,
    touchAction: "none",
    cursor: "crosshair",
  },
});

type Drag =
  | { kind: "box"; pointerId: number }
  | {
      kind: "vertex";
      pointerId: number;
      region: number;
      vertex: number;
      start: PixelPoint;
      original: PixelPoint;
    }
  | { kind: "polygon"; pointerId: number; region: number; last: PixelPoint };

function newLayer() {
  const layer = document.createElement("div");
  layer.style.pointerEvents = "none";
  return layer;
}

function pointsAttribute(points: readonly PixelPoint[]) {
  return points.map(([x, y]) => `${x},${y}`).join(" ");
}

function makeStaticSvg(width: number, height: number) {
  const svg = document.createElementNS(svgNamespace, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", "100%");
  svg.setAttribute("height", "100%");
  return svg;
}

function fillStaticSvg(
  svg: SVGSVGElement,
  regions: readonly EditableTextRegion[],
  selectedSet: ReadonlySet<number>,
  interactive: boolean,
) {
  const shapes = document.createDocumentFragment();
  for (const [index, region] of regions.entries()) {
    if (selectedSet.has(index)) continue;
    const polygon = document.createElementNS(svgNamespace, "polygon");
    polygon.setAttribute("points", pointsAttribute(region.polygon));
    polygon.setAttribute("fill", "gold");
    polygon.setAttribute("fill-opacity", "0.2");
    polygon.setAttribute("stroke", "darkorange");
    polygon.setAttribute("stroke-width", "2");
    polygon.setAttribute("vector-effect", "non-scaling-stroke");
    polygon.setAttribute("data-region-index", String(index));
    polygon.style.pointerEvents = interactive ? "visiblePainted" : "none";
    if (interactive) polygon.style.cursor = "pointer";
    shapes.append(polygon);
    const label = readingLabel(
      region.polygon,
      region.readingField === "reading" ? region.reading?.text : null,
    );
    if (label) shapes.append(label);
  }
  svg.replaceChildren(shapes);
}

function sameUnselectedRegions(
  previous: readonly EditableTextRegion[],
  next: readonly EditableTextRegion[],
  selectedSet: ReadonlySet<number>,
) {
  return (
    previous === next ||
    (previous.length === next.length &&
      next.every(
        (region, index) => selectedSet.has(index) || region === previous[index],
      ))
  );
}

function computeHandleRadius(
  viewer: OpenSeadragon.Viewer,
  layer: HTMLDivElement,
  pageWidth: number,
) {
  const width = layer.getBoundingClientRect().width;
  if (width > 0) return (6 * pageWidth) / width;

  const containerWidth =
    viewer.container?.clientWidth || viewer.element?.clientWidth || 600;
  const zoom = viewer.viewport?.getZoom?.(true) || 1;
  const approximateRadius = (6 * pageWidth) / (containerWidth * zoom);
  return Math.max(0.5, Math.min(pageWidth * 0.05, approximateRadius));
}

function sizeHandles(
  viewer: OpenSeadragon.Viewer,
  layer: HTMLDivElement,
  pageWidth: number,
) {
  const handles = layer.querySelectorAll(
    "[data-vertex-handle], [data-midpoint-handle]",
  );
  if (handles.length === 0) return;
  const radius = computeHandleRadius(viewer, layer, pageWidth);
  for (const handle of handles) {
    const midpoint = handle.hasAttribute("data-midpoint-handle");
    handle.setAttribute(
      "r",
      String(midpoint ? radius * midpointScale : radius),
    );
    handle.setAttribute("stroke-width", midpoint ? "1.5" : "2");
  }
}

function regionHit(event: Event, selector: string) {
  return event.target instanceof Element
    ? event.target.closest(selector)
    : null;
}

const activePaint = {
  stroke: highlight,
  strokeWidth: 2,
  vectorEffect: "non-scaling-stroke",
};

export function TiffRegionsEditOverlay({
  viewer,
  PixelPoint,
  pageSize: { width, height },
  state,
  dispatch,
}: TiffRegionsEditOverlayProps) {
  const [staticLayer] = useState(newLayer);
  const [activeLayer] = useState(newLayer);
  const [staticSvg] = useState(() => makeStaticSvg(width, height));
  const previousRegions = useRef<{
    regions: readonly EditableTextRegion[];
    selectedSet: ReadonlySet<number>;
    mode: TiffTextRegionsEditorState["mode"];
  } | null>(null);
  const drag = useRef<(Drag & { captureTarget: Element }) | null>(null);
  const {
    mode,
    selection,
    selectedRegions,
    draft,
    payload: { regions },
  } = state;
  const selectedSet = useMemo(
    () => new Set(selectedRegions),
    [selectedRegions],
  );
  const selectable = mode === "select";
  const erasable = mode === "eraser";
  const interactive = selectable || erasable;
  const singleSelected = selectable && selectedRegions.length === 1;
  const showingDrawTarget = mode === "draw_box" || mode === "draw_polygon";
  const draftVertexCount = draft?.kind === "polygon" ? draft.points.length : 0;
  const initialRadius =
    singleSelected || draftVertexCount > 0
      ? computeHandleRadius(viewer, activeLayer, width)
      : 0.5;

  useLayoutEffect(() => {
    const image = viewer.world.getItemAt(0);
    if (!image) return;
    staticSvg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    staticLayer.append(staticSvg);
    const placement = image.imageToViewportRectangle(0, 0, width, height);
    for (const layer of [staticLayer, activeLayer]) {
      viewer.addOverlay(layer, placement);
      // OpenSeadragon wraps each layer in a page-sized div. Without this, the
      // active wrapper intercepts hits meant for static polygons beneath it.
      const wrapper = layer.parentElement;
      if (wrapper?.classList.contains("openseadragon-overlay-wrapper")) {
        wrapper.style.pointerEvents = "none";
      }
    }
    const resize = () => sizeHandles(viewer, activeLayer, width);
    for (const event of scaleEvents) viewer.addHandler(event, resize);
    previousRegions.current = null;
    return () => {
      for (const event of scaleEvents) viewer.removeHandler(event, resize);
      viewer.removeOverlay(activeLayer);
      viewer.removeOverlay(staticLayer);
    };
  }, [viewer, staticLayer, staticSvg, activeLayer, width, height]);

  useLayoutEffect(() => {
    const previous = previousRegions.current;
    if (
      !previous ||
      previous.selectedSet !== selectedSet ||
      previous.mode !== mode ||
      !sameUnselectedRegions(previous.regions, regions, selectedSet)
    ) {
      fillStaticSvg(staticSvg, regions, selectedSet, interactive);
    }
    previousRegions.current = { regions, selectedSet, mode };
  }, [
    viewer,
    staticSvg,
    width,
    height,
    regions,
    selectedSet,
    mode,
    interactive,
  ]);

  useLayoutEffect(() => {
    sizeHandles(viewer, activeLayer, width);
  }, [viewer, activeLayer, selection, draftVertexCount, mode, width, height]);

  useLayoutEffect(() => {
    if (!interactive) return;
    const stopActivePress = (event: Event) => {
      if (regionHit(event, "[data-active-region]")) event.stopPropagation();
    };
    const stopStaticMousePress = (event: MouseEvent) => {
      if (regionHit(event, "[data-region-index]")) event.stopPropagation();
    };
    const pressStatic = (event: PointerEvent["nativeEvent"]) => {
      const index = regionHit(event, "[data-region-index]")?.getAttribute(
        "data-region-index",
      );
      if (index == null) return;
      event.stopPropagation();
      if (event.button !== 0) return;
      // Selection or deletion can replace the hit node before the compatibility
      // mousedown, leaving the viewer canvas itself under the pointer.
      event.preventDefault();
      const type = erasable
        ? "delete_region"
        : event.shiftKey
          ? "toggle_select_region"
          : "select_region";
      dispatch({ type, index: Number(index) });
    };

    // The overlays sit inside viewer.canvas. Stop both native press events at
    // the overlay boundary, including the compatibility event sent by a mouse.
    activeLayer.addEventListener("pointerdown", stopActivePress);
    activeLayer.addEventListener("mousedown", stopActivePress);
    staticSvg.addEventListener("pointerdown", pressStatic);
    staticSvg.addEventListener("mousedown", stopStaticMousePress);
    return () => {
      activeLayer.removeEventListener("pointerdown", stopActivePress);
      activeLayer.removeEventListener("mousedown", stopActivePress);
      staticSvg.removeEventListener("pointerdown", pressStatic);
      staticSvg.removeEventListener("mousedown", stopStaticMousePress);
    };
  }, [activeLayer, staticSvg, dispatch, erasable, interactive]);

  useLayoutEffect(() => {
    if (!selectable) return;
    const host = viewer.element;
    let emptyPress: { id: number; x: number; y: number } | null = null;
    const startEmpty = (event: PointerEvent["nativeEvent"]) => {
      if (regionHit(event, "[data-region-index], [data-active-region]")) return;
      if (event.button === 0 && !emptyPress) {
        emptyPress = {
          id: event.pointerId,
          x: event.clientX,
          y: event.clientY,
        };
      }
    };
    const trackEmpty = (event: PointerEvent["nativeEvent"]) => {
      if (
        emptyPress?.id === event.pointerId &&
        Math.hypot(event.clientX - emptyPress.x, event.clientY - emptyPress.y) >
          4
      )
        emptyPress = null;
    };
    const endEmpty = (event: PointerEvent["nativeEvent"]) => {
      trackEmpty(event);
      if (emptyPress?.id !== event.pointerId) return;
      emptyPress = null;
      dispatch({ type: "clear_selection" });
    };
    const cancelEmpty = (event: PointerEvent["nativeEvent"]) => {
      if (emptyPress?.id === event.pointerId) emptyPress = null;
    };
    host.addEventListener("pointerdown", startEmpty, true);
    host.addEventListener("pointermove", trackEmpty, true);
    host.addEventListener("pointerup", endEmpty, true);
    host.addEventListener("pointercancel", cancelEmpty, true);
    host.addEventListener("pointerleave", cancelEmpty);
    return () => {
      host.removeEventListener("pointerdown", startEmpty, true);
      host.removeEventListener("pointermove", trackEmpty, true);
      host.removeEventListener("pointerup", endEmpty, true);
      host.removeEventListener("pointercancel", cancelEmpty, true);
      host.removeEventListener("pointerleave", cancelEmpty);
    };
  }, [viewer, dispatch, selectable]);

  useLayoutEffect(() => {
    return () => {
      const active = drag.current;
      if (!active) return;
      drag.current = null;
      viewer.setMouseNavEnabled?.(true);
      if (active.captureTarget.hasPointerCapture?.(active.pointerId)) {
        active.captureTarget.releasePointerCapture(active.pointerId);
      }
      dispatch({
        type: active.kind === "box" ? "cancel_draft" : "end_gesture",
      });
    };
  }, [viewer, mode, dispatch]);

  function pixelAt(event: {
    clientX: number;
    clientY: number;
  }): PixelPoint | null {
    const image = viewer.world.getItemAt(0);
    const host = viewer.element;
    const bounds = host.getBoundingClientRect();
    if (!image || !bounds.width || !bounds.height) return null;
    const point = image.viewerElementToImageCoordinates(
      new PixelPoint(
        ((event.clientX - bounds.left) * host.clientWidth) / bounds.width,
        ((event.clientY - bounds.top) * host.clientHeight) / bounds.height,
      ),
    );
    return [point.x, point.y];
  }

  function startGesture(
    event: PointerEvent<Element>,
    next: Drag,
    captureTarget = event.currentTarget,
  ) {
    captureTarget.setPointerCapture(event.pointerId);
    drag.current = { ...next, captureTarget };
    viewer.setMouseNavEnabled?.(false);
  }

  function pressPolygon(event: PointerEvent<SVGPolygonElement>, index: number) {
    if (!interactive || event.button !== 0 || drag.current) return;
    event.preventDefault();
    if (erasable) {
      dispatch({ type: "delete_region", index });
      return;
    }
    if (event.shiftKey) {
      dispatch({ type: "toggle_select_region", index });
      return;
    }
    if (!singleSelected) {
      dispatch({ type: "select_region", index });
      return;
    }
    const point = pixelAt(event);
    if (!point) return;
    startGesture(event, {
      kind: "polygon",
      region: index,
      pointerId: event.pointerId,
      last: point,
    });
  }

  function pressHandle(
    event: PointerEvent<SVGCircleElement>,
    region: number,
    index: number,
    original: PixelPoint,
    kind: "vertex" | "midpoint",
  ) {
    if (event.button !== 0 || drag.current) return;
    const start = pixelAt(event);
    const svg = event.currentTarget.ownerSVGElement;
    if (!start || !svg) return;
    event.preventDefault();
    const vertex = kind === "midpoint" ? index + 1 : index;
    // The midpoint can move under the pointer after insertion. Keep the capture
    // on the SVG so the new corner receives the rest of this gesture.
    startGesture(
      event,
      {
        kind: "vertex",
        region,
        vertex,
        pointerId: event.pointerId,
        start,
        original,
      },
      svg,
    );
    if (kind === "midpoint") {
      const [x, y] = original;
      dispatch({ type: "insert_vertex", region, edge: index, x, y });
    } else {
      dispatch({ type: "select_vertex", vertex });
    }
  }

  function nearFirstVertex(event: PointerEvent<Element>, first: PixelPoint) {
    const image = viewer.world.getItemAt(0);
    const host = viewer.element;
    if (!image || !host.clientWidth || !host.clientHeight) return false;
    const bounds = host.getBoundingClientRect();
    const point = image.imageToViewerElementCoordinates(
      new PixelPoint(first[0], first[1]),
    );
    return (
      Math.hypot(
        event.clientX -
          bounds.left -
          (point.x * bounds.width) / host.clientWidth,
        event.clientY -
          bounds.top -
          (point.y * bounds.height) / host.clientHeight,
      ) <= 10
    );
  }

  function startDraw(event: PointerEvent<HTMLDivElement>) {
    event.stopPropagation();
    if (event.button !== 0 || drag.current) return;
    const point = pixelAt(event);
    if (!point) return;
    const [x, y] = point;
    event.currentTarget.focus({ preventScroll: true });
    if (mode === "draw_box") {
      startGesture(event, { kind: "box", pointerId: event.pointerId });
      dispatch({ type: "begin_draft", x, y });
    } else if (draft?.kind === "polygon") {
      const first = draft.points[0];
      if (draft.points.length >= 3 && first && nearFirstVertex(event, first)) {
        dispatch({ type: "commit_draft" });
      } else {
        dispatch({ type: "add_draft_point", x, y });
      }
    } else {
      dispatch({ type: "begin_draft", x, y });
    }
  }

  function move(event: PointerEvent<Element>) {
    const active = drag.current;
    if (
      active
        ? active.pointerId !== event.pointerId
        : mode !== "draw_polygon" || !draft
    )
      return;
    event.stopPropagation();
    const point = pixelAt(event);
    if (!point) return;
    const [x, y] = point;
    if (active?.kind === "vertex") {
      dispatch({
        type: "move_vertex",
        region: active.region,
        vertex: active.vertex,
        x: active.original[0] + (x - active.start[0]),
        y: active.original[1] + (y - active.start[1]),
      });
    } else if (active?.kind === "polygon") {
      const [lastX, lastY] = active.last;
      active.last = point;
      dispatch({
        type: "translate_polygon",
        region: active.region,
        dx: x - lastX,
        dy: y - lastY,
      });
    } else {
      dispatch({ type: "move_draft", x, y });
    }
  }

  function end(event: PointerEvent<Element>, cancelled = false) {
    const active = drag.current;
    if (active?.pointerId !== event.pointerId) return;
    event.stopPropagation();
    if (!cancelled) move(event);
    drag.current = null;
    viewer.setMouseNavEnabled?.(true);
    if (active.kind === "box") {
      dispatch({ type: cancelled ? "cancel_draft" : "commit_draft" });
    } else {
      dispatch({ type: "end_gesture" });
    }
  }

  const gestureEvents = {
    onPointerMoveCapture: move,
    onPointerUpCapture: (event: PointerEvent<Element>) => end(event),
    onPointerCancelCapture: (event: PointerEvent<Element>) => end(event, true),
    onLostPointerCapture: (event: PointerEvent<Element>) => end(event, true),
  };
  const draftPoints = draft ? draftPolygon(draft) : [];
  const lastDraftPoint = draftPoints[draftPoints.length - 1];
  const drawTarget = stylex.props(s.drawTarget);

  return (
    <>
      {createPortal(
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          height="100%"
          aria-hidden="true"
          {...gestureEvents}
        >
          {selectedRegions.map((index) => {
            const polygon = regions[index]?.polygon;
            if (!polygon) return null;
            return (
              <g key={index} data-active-region={index}>
                <polygon
                  {...activePaint}
                  points={pointsAttribute(polygon)}
                  fill={highlight}
                  fillOpacity={selectedRegions.length >= 2 ? 0.22 : 0.16}
                  style={
                    interactive
                      ? {
                          pointerEvents: "visiblePainted",
                          cursor: singleSelected ? "move" : "pointer",
                          touchAction: "none",
                        }
                      : undefined
                  }
                  onPointerDownCapture={(event) => pressPolygon(event, index)}
                />
                {singleSelected &&
                  polygon.map(([x, y], edge) => {
                    const next = polygon[(edge + 1) % polygon.length];
                    if (!next) return null;
                    const midpoint: PixelPoint = [
                      (x + next[0]) / 2,
                      (y + next[1]) / 2,
                    ];
                    return (
                      <circle
                        key={edge}
                        data-midpoint-handle={edge}
                        cx={midpoint[0]}
                        cy={midpoint[1]}
                        r={initialRadius * midpointScale}
                        fill={highlight}
                        fillOpacity={0.75}
                        stroke="white"
                        strokeWidth={1.5}
                        vectorEffect="non-scaling-stroke"
                        style={{
                          pointerEvents: "visiblePainted",
                          cursor: "copy",
                          touchAction: "none",
                        }}
                        onPointerDownCapture={(event) =>
                          pressHandle(event, index, edge, midpoint, "midpoint")
                        }
                      />
                    );
                  })}
                {singleSelected &&
                  polygon.map((point, vertex) => (
                    <circle
                      key={vertex}
                      {...activePaint}
                      data-vertex-handle={vertex}
                      cx={point[0]}
                      cy={point[1]}
                      r={initialRadius}
                      fill={selection?.vertex === vertex ? highlight : "white"}
                      style={{
                        pointerEvents: "visiblePainted",
                        cursor: "grab",
                        touchAction: "none",
                      }}
                      onPointerDownCapture={(event) =>
                        pressHandle(event, index, vertex, point, "vertex")
                      }
                      onContextMenu={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        if (polygon.length > MIN_POLYGON_VERTICES) {
                          dispatch({
                            type: "delete_vertex",
                            region: index,
                            vertex,
                          });
                        }
                      }}
                    />
                  ))}
              </g>
            );
          })}
          {draft?.kind === "box" && (
            <polygon
              {...activePaint}
              fill={highlight}
              fillOpacity={0.16}
              points={pointsAttribute(draftPoints)}
            />
          )}
          {draft?.kind === "polygon" && (
            <g>
              <polyline
                {...activePaint}
                fill="none"
                points={pointsAttribute(draftPoints)}
              />
              {draftPoints.map(([x, y], index) => (
                <circle
                  key={index}
                  data-vertex-handle
                  cx={x}
                  cy={y}
                  r={initialRadius}
                  fill={highlight}
                />
              ))}
              {draft.cursor && lastDraftPoint && (
                <line
                  {...activePaint}
                  strokeDasharray="4 4"
                  x1={lastDraftPoint[0]}
                  y1={lastDraftPoint[1]}
                  x2={draft.cursor[0]}
                  y2={draft.cursor[1]}
                />
              )}
            </g>
          )}
        </svg>,
        activeLayer,
      )}
      {showingDrawTarget && (
        <div
          {...drawTarget}
          className={`nodrag nopan ${drawTarget.className ?? ""}`}
          tabIndex={-1}
          aria-label="Draw text region"
          onPointerDownCapture={startDraw}
          onDoubleClick={(event) => {
            event.stopPropagation();
            if (mode === "draw_polygon") dispatch({ type: "commit_draft" });
          }}
          {...gestureEvents}
        />
      )}
    </>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import type OpenSeadragon from "openseadragon";
import * as stylex from "@stylexjs/stylex";
import {
  ChevronLeft,
  ChevronRight,
  Crop,
  Maximize,
  Minus,
  Plus,
  RotateCw,
} from "lucide-react";
import { IconButton } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import {
  getImageInfo,
  imagePath,
  imageThumbnailUrl,
  imageTileUrl,
  type ImageInfo,
} from "@/lib/api/images";
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  TiffWindowSelector,
  type TiffWindowSelection,
} from "./TiffWindowSelector";

const s = stylex.create({
  root: {
    position: "relative",
    width: "100%",
    height: "100%",
    backgroundColor: tokens.colorSurface,
  },
  // The tile surface is its own layer. The controls are a later sibling, so
  // they stay above the canvas OpenSeadragon appends into this element.
  viewport: {
    position: "absolute",
    inset: 0,
    zIndex: 0,
    overflow: "hidden",
  },
  thumbnail: {
    position: "absolute",
    width: "100%",
    height: "100%",
    objectFit: "contain",
    zIndex: 0,
  },
  controls: {
    position: "absolute",
    bottom: 4,
    left: 4,
    right: 4,
    zIndex: 1,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    backgroundColor: tokens.colorSurface,
    borderRadius: tokens.radiusSm,
    fontSize: tokens.fontSizeXs,
  },
  reading: {
    position: "absolute",
    top: 4,
    left: 4,
    right: 4,
    zIndex: 1,
    width: "fit-content",
    maxWidth: "calc(100% - 8px)",
    overflowWrap: "anywhere",
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    borderRadius: tokens.radiusSm,
    padding: "6px 9px",
    fontSize: tokens.fontSizeXs,
  },
  status: {
    position: "absolute",
    top: 4,
    left: 4,
    right: 4,
    zIndex: 1,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    padding: 6,
  },
});

export function imageFailure(status: number): string {
  if (status === 503 || status === 501)
    return "Image service unavailable. Try again shortly.";
  if (status === 401 || status === 403 || status === 404)
    return "This image is no longer available to you.";
  if (status === 415 || status === 422) return "This file cannot be displayed.";
  return "Could not load this image. Try again.";
}

export type PixelPolygon = readonly (readonly [number, number])[];

type TiffOverlay = {
  page: number;
  polygons: readonly PixelPolygon[];
  readings?: readonly (string | null)[];
  bounds: { col: number; row: number; width: number; height: number };
};

// The frame may grow to four times the size at which the whole page fits
// before the page starts magnifying again. OpenSeadragon reads its minimum zoom
// as a fraction of home (the whole page in the frame), so this is a fraction of
// the frame whatever the frame and whatever the page's shape.
const PAGE_SHRINK_FLOOR = 0.25;

/**
 * Grow or shrink the tile surface without changing how big the scan is drawn.
 *
 * A card's frame is a window onto the page: a bigger frame shows more page, not
 * the same page bigger. OpenSeadragon's own resize does the opposite, because
 * its zoom is a magnification relative to the frame (`getBounds().width` is
 * `1 / zoom`), so holding that number across a resize redraws the page
 * proportionally wider. What has to stay fixed is screen pixels per page, which
 * means dividing the held zoom by the width the surface just gained — and it has
 * to stay fixed under the top-left, the corner opposite the grip a card is
 * dragged by, so the page does not slide out from under the pointer.
 */
export function keepScaleOnSurfaceResize({
  viewer,
  Point,
  element,
}: {
  viewer: OpenSeadragon.Viewer;
  Point: typeof OpenSeadragon.Point;
  element: HTMLElement;
}): void {
  const viewport = viewer.viewport;
  const size = new Point(element.clientWidth || 1, element.clientHeight || 1);
  const previous = viewport.getContainerSize();
  // An observer fires once as soon as it starts watching, and a drag commits a
  // layout the surface has already been given.
  if (previous.equals(size)) return;
  const held = viewport.getBounds(true);
  const zoom = viewport.getZoom(true) * (previous.x / size.x);
  viewport.resize(size, false);
  viewport.zoomTo(zoom, undefined, true);
  const moved = viewport.getBounds(true);
  viewport.panBy(new Point(held.x - moved.x, held.y - moved.y), true);
  // Then let the page stop at the frame's edge, and stop shrinking at the
  // floor, instead of floating loose until the next gesture touches it.
  viewport.applyConstraints(true);
}

const svgNamespace = "http://www.w3.org/2000/svg";

type ReadingEdge = {
  /** The corner this edge is walked from, once it has been pointed rightwards. */
  x: number;
  y: number;
  run: number;
  rise: number;
  span: number;
};

type ReadingFrame = {
  x: number;
  y: number;
  degrees: number;
  depth: number;
};

function rightwardEdge(
  from: readonly [number, number],
  to: readonly [number, number],
): ReadingEdge {
  const [fromX, fromY] = from;
  const [toX, toY] = to;
  if (toX < fromX || (toX === fromX && toY < fromY)) {
    // Words read left to right whichever corner the detector started from, so an
    // edge that runs back across the page is walked the other way round.
    return {
      x: toX,
      y: toY,
      run: fromX - toX,
      rise: fromY - toY,
      span: Math.hypot(fromX - toX, fromY - toY),
    };
  }
  return {
    x: fromX,
    y: fromY,
    run: toX - fromX,
    rise: toY - fromY,
    span: Math.hypot(toX - fromX, toY - fromY),
  };
}

/**
 * The line a reading is written along, in page pixels.
 *
 * A scan is rarely square to the text it carries, and the detector returns each
 * region as the quadrangle it found, tilted with the writing. So a baseline
 * cannot be assumed: it is one of the region's long edges, pointed left to right
 * because words read that way whichever corner the detector started at, and the
 * higher of them because the reading is written above what it labels. Depth is
 * measured across that edge rather than down the page, so a region turned 45°
 * does not borrow its own diagonal as a cap height.
 */
function readingFrame(points: PixelPolygon): ReadingFrame | null {
  const edges: ReadingEdge[] = [];
  let first: readonly [number, number] | undefined;
  let previous: readonly [number, number] | undefined;
  for (const corner of points) {
    first ??= corner;
    if (previous) edges.push(rightwardEdge(previous, corner));
    previous = corner;
  }
  if (first && previous && first !== previous) {
    edges.push(rightwardEdge(previous, first));
  }
  let longest: ReadingEdge | null = null;
  for (const edge of edges) {
    if (!longest || edge.span > longest.span) longest = edge;
  }
  if (!longest) return null;
  let baseline: ReadingEdge = longest;
  for (const edge of edges) {
    // The edge under the writing is as long as the edge over it and belongs to
    // the line below, so the highest edge of the region is the one to write on.
    if (edge.span < longest.span * 0.9) continue;
    if (edge.y < baseline.y) baseline = edge;
  }
  const length = baseline.span || 1;
  const along = baseline.run / length;
  const across = baseline.rise / length;
  let depth = 0;
  for (const [x, y] of points) {
    // Positive this way is the side the region's body lies on, that is, below
    // the writing when it runs left to right.
    const down = (x - baseline.x) * -across + (y - baseline.y) * along;
    if (down > depth) depth = down;
  }
  return {
    x: baseline.x,
    y: baseline.y,
    degrees: (Math.atan2(baseline.rise, baseline.run) * 180) / Math.PI,
    depth,
  };
}

function readingLabel(
  points: PixelPolygon,
  reading: string | null | undefined,
): SVGTextElement | null {
  const text = reading?.trim();
  if (!text) return null;
  const frame = readingFrame(points);
  if (!frame) return null;
  const { x, y, degrees, depth } = frame;
  const label = document.createElementNS(svgNamespace, "text");
  label.textContent = text;
  label.setAttribute("x", String(x));
  label.setAttribute("y", String(y));
  label.setAttribute("fill", "darkorange");
  // Half the region's depth, so a page full of readings stays legible as notes
  // on the spans instead of competing with the scan itself. The floor is what a
  // label has to be in page pixels to survive being drawn at all.
  label.setAttribute("font-size", String(Math.max(4, depth * 0.4)));
  label.setAttribute("dominant-baseline", "auto");
  if (degrees) {
    // Turned about the corner it starts from, so the first letter stays on the
    // span and the rest of the word follows the tilt away from it.
    label.setAttribute(
      "transform",
      `rotate(${Number(degrees.toFixed(2))} ${x} ${y})`,
    );
  }
  label.style.pointerEvents = "none";
  return label;
}

export function createTiffOverlay(
  width: number,
  height: number,
  polygons: readonly PixelPolygon[],
  inspection?: {
    readings: readonly (string | null)[];
    onSelect: (text: string) => void;
  },
): HTMLDivElement {
  const layer = document.createElement("div");
  layer.style.pointerEvents = "none";
  const svg = document.createElementNS(svgNamespace, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", "100%");
  svg.setAttribute("height", "100%");
  svg.setAttribute(
    "aria-label",
    `${polygons.length} ${inspection ? "recognized" : "detected"} text regions`,
  );
  svg.setAttribute("role", inspection ? "group" : "img");
  for (const [index, points] of polygons.entries()) {
    const polygon = document.createElementNS(svgNamespace, "polygon");
    polygon.setAttribute(
      "points",
      points.map(([x, y]) => `${x},${y}`).join(" "),
    );
    polygon.setAttribute("fill", "gold");
    polygon.setAttribute("fill-opacity", "0.2");
    polygon.setAttribute("stroke", "darkorange");
    polygon.setAttribute("stroke-width", "2");
    polygon.setAttribute("vector-effect", "non-scaling-stroke");
    if (inspection) {
      const reading = inspection.readings[index] ?? "No text recognized";
      polygon.setAttribute("role", "button");
      polygon.setAttribute("tabindex", "0");
      polygon.setAttribute("aria-label", reading);
      polygon.style.pointerEvents = "visiblePainted";
      polygon.style.cursor = "pointer";
      const tooltip = document.createElementNS(svgNamespace, "title");
      tooltip.textContent = reading;
      polygon.append(tooltip);
      polygon.addEventListener("click", () => inspection.onSelect(reading));
      polygon.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        event.stopPropagation();
        inspection.onSelect(reading);
      });
      const label = readingLabel(points, inspection.readings[index]);
      svg.append(polygon);
      if (label) svg.append(label);
      continue;
    }
    svg.append(polygon);
  }
  layer.append(svg);
  return layer;
}

export function TiffArtifactView({
  workspaceId,
  artifactId,
  name,
  overlay,
  selection,
  onSize,
}: {
  workspaceId: string;
  artifactId: string;
  name: string;
  overlay?: TiffOverlay;
  selection?: TiffWindowSelection;
  /** The page's pixel size, once its tile pyramid describes it. */
  onSize?: (width: number, height: number) => void;
}) {
  const [currentPage, setPage] = useState(0);
  const page = selection?.window.page ?? overlay?.page ?? currentPage;
  const [attempt, setAttempt] = useState(0);
  return (
    <TiffPage
      key={`${workspaceId}:${artifactId}:${page}:${attempt}`}
      path={imagePath(workspaceId, artifactId)}
      page={page}
      name={name}
      onPage={(next) => {
        if (selection) selection.onChange({ ...selection.window, page: next });
        else setPage(next);
      }}
      overlay={overlay?.page === page ? overlay : undefined}
      selection={selection}
      allowPageChange={Boolean(selection || !overlay)}
      onSize={onSize}
      onRetry={() => setAttempt(attempt + 1)}
    />
  );
}

function TiffPage({
  path,
  page,
  name,
  onPage,
  onRetry,
  overlay,
  selection,
  allowPageChange,
  onSize,
}: {
  path: string;
  page: number;
  name: string;
  onPage: (page: number) => void;
  onRetry: () => void;
  onSize?: (width: number, height: number) => void;
  overlay?: TiffOverlay;
  selection?: TiffWindowSelection;
  allowPageChange: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<OpenSeadragon.Viewer | null>(null);
  const [opened, setOpened] = useState<{
    viewer: OpenSeadragon.Viewer;
    Point: typeof OpenSeadragon.Point;
  } | null>(null);
  const hasFramedResult = useRef(false);
  const [info, setInfo] = useState<ImageInfo | null>(null);
  const [thumbnailReady, setThumbnailReady] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [selectedReading, setSelectedReading] = useState<{
    overlay: TiffOverlay;
    text: string;
  } | null>(null);
  const editableSelection = selection?.wholePage ? undefined : selection;
  // A card hands over a fresh callback every render, while the page is fetched
  // by path and page number. The size goes to whichever callback is current.
  const reportSize = useRef(onSize);
  useEffect(() => {
    reportSize.current = onSize;
  }, [onSize]);

  useEffect(() => {
    const controller = new AbortController();
    getImageInfo(path, page, controller.signal)
      .then((next) => {
        setInfo(next);
        reportSize.current?.(next.width, next.height);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(
            imageFailure(failure instanceof ApiError ? failure.status : 0),
          );
      });
    return () => controller.abort();
  }, [path, page]);

  useEffect(() => {
    if (!info || !thumbnailReady) return;
    let disposed = false;
    let surfaceResize: ResizeObserver | undefined;
    import("openseadragon")
      .then(({ default: osd }) => {
        if (disposed || !host.current) return;
        const element = host.current;
        const instance = osd({
          element,
          showNavigationControl: false,
          showNavigator: false,
          loadTilesWithAjax: true,
          ajaxWithCredentials: true,
          imageLoaderLimit: 4,
          immediateRender: true,
          blendTime: 0,
          animationTime: 0.2,
          visibilityRatio: 1,
          minZoomImageRatio: PAGE_SHRINK_FLOOR,
          constrainDuringPan: true,
          maxZoomPixelRatio: 2,
          // Its own resize holds the zoom, and so magnifies the page with the
          // card. This surface is watched here instead.
          autoResize: false,
          gestureSettingsMouse: { clickToZoom: false, dblClickToZoom: true },
          tileSources: {
            width: info.width,
            height: info.height,
            tileSize: info.tile_size,
            minLevel: info.min_level,
            maxLevel: info.max_level,
            tileOverlap: 0,
            getTileUrl: (z: number, x: number, y: number) =>
              imageTileUrl(path, page, {
                z,
                x,
                y,
                extension: info.tile_format,
              }),
          },
        });
        viewer.current = instance;
        instance.addHandler("open", () => {
          setOpened({ viewer: instance, Point: osd.Point });
        });
        instance.addHandler("tile-loaded", () => setLoaded(true));
        instance.addHandler("tile-load-failed", (event) =>
          setError(imageFailure(event.tileRequest?.status ?? 0)),
        );
        if (typeof ResizeObserver !== "undefined") {
          surfaceResize = new ResizeObserver(() =>
            keepScaleOnSurfaceResize({
              viewer: instance,
              Point: osd.Point,
              element,
            }),
          );
          surfaceResize.observe(element);
        }
      })
      .catch(() => {
        if (!disposed) setError(imageFailure(0));
      });
    return () => {
      disposed = true;
      surfaceResize?.disconnect();
      viewer.current?.destroy();
      viewer.current = null;
    };
  }, [info, thumbnailReady, path, page]);

  useEffect(() => {
    if (!opened || !info || !overlay) return;
    const { viewer } = opened;
    const image = viewer.world.getItemAt(0);
    const layer = createTiffOverlay(
      info.width,
      info.height,
      overlay.polygons,
      overlay.readings
        ? {
            readings: overlay.readings,
            onSelect: (text) => setSelectedReading({ overlay, text }),
          }
        : undefined,
    );
    viewer.addOverlay(
      layer,
      image.imageToViewportRectangle(0, 0, info.width, info.height),
    );
    if (!hasFramedResult.current) {
      hasFramedResult.current = true;
      const { col, row, width, height } = overlay.bounds;
      viewer.viewport.fitBounds(
        image.imageToViewportRectangle(col, row, width, height),
        true,
      );
    }
    return () => {
      viewer.removeOverlay(layer);
    };
  }, [opened, info, overlay]);

  const root = stylex.props(s.root);
  const viewport = stylex.props(s.viewport);
  const status = stylex.props(s.status);
  const controls = stylex.props(s.controls);
  return (
    <section
      aria-label={`${name} scan`}
      className={`nodrag nopan nowheel ${root.className ?? ""}`}
      style={root.style}
      onKeyDown={(event) => {
        if (event.key === "Escape" && selectedReading) setSelectedReading(null);
        if (editing && event.key === "Escape") {
          event.stopPropagation();
          setEditing(false);
        }
      }}
    >
      {!loaded && (
        <img /* eslint-disable-line @next/next/no-img-element -- authenticated thumbnail */
          src={imageThumbnailUrl(path, page)}
          alt={name}
          {...stylex.props(s.thumbnail)}
          onLoad={() => setThumbnailReady(true)}
          onError={() => setThumbnailReady(true)}
        />
      )}
      <div
        ref={host}
        data-tiff-viewport
        data-page={page}
        className={viewport.className}
        style={{ ...viewport.style, zIndex: 0 }}
      />
      {editableSelection && info && opened && loaded && (
        <TiffWindowSelector
          key={String(editing)}
          viewer={opened.viewer}
          PixelPoint={opened.Point}
          size={info}
          selection={editableSelection}
          editing={editing}
        />
      )}
      {loaded &&
        !error &&
        selectedReading &&
        selectedReading.overlay === overlay && (
          <div role="status" {...stylex.props(s.reading)}>
            {selectedReading.text}
          </div>
        )}
      {error || !loaded ? (
        <div
          role="status"
          className={status.className}
          style={{ ...status.style, zIndex: 2 }}
        >
          {error ?? "Loading image…"}
        </div>
      ) : null}
      <div
        className={controls.className}
        style={{ ...controls.style, zIndex: 2 }}
      >
        <IconButton
          size="2xs"
          label="Zoom out"
          onClick={() => viewer.current?.viewport.zoomBy(0.5)}
        >
          <Minus size={14} />
        </IconButton>
        <IconButton
          size="2xs"
          label="Zoom in"
          onClick={() => viewer.current?.viewport.zoomBy(2)}
        >
          <Plus size={14} />
        </IconButton>
        <IconButton
          size="2xs"
          label="Fit image"
          onClick={() => viewer.current?.viewport.goHome()}
        >
          <Maximize size={14} />
        </IconButton>
        {editableSelection && (
          <IconButton
            size="2xs"
            label="Edit detection window"
            pressed={editing}
            disabled={!loaded}
            onClick={() => setEditing(!editing)}
          >
            <Crop size={14} />
          </IconButton>
        )}
        {allowPageChange && info && info.page_count > 1 && (
          <>
            <IconButton
              size="2xs"
              label="Previous page"
              disabled={page === 0}
              onClick={() => onPage(page - 1)}
            >
              <ChevronLeft size={14} />
            </IconButton>
            <span>
              Page {page + 1} of {info.page_count}
            </span>
            <IconButton
              size="2xs"
              label="Next page"
              disabled={page + 1 === info.page_count}
              onClick={() => onPage(page + 1)}
            >
              <ChevronRight size={14} />
            </IconButton>
          </>
        )}
        {error && (
          <IconButton size="2xs" label="Retry image" onClick={onRetry}>
            <RotateCw size={14} />
          </IconButton>
        )}
      </div>
    </section>
  );
}

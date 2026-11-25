"use client";

import { useEffect, useRef, useState } from "react";
import type OpenSeadragon from "openseadragon";
import * as stylex from "@stylexjs/stylex";
import {
  ChevronLeft,
  ChevronRight,
  Crop,
  Image as ImageIcon,
  Map as MapIcon,
  Maximize,
  Maximize2,
  Minus,
  Plus,
  RotateCw,
} from "lucide-react";
import { IconButton } from "@/components/ui/button";
import { ApiError, notifyUnauthorized } from "@/lib/api/client";
import {
  getImageInfo,
  imagePath,
  imageThumbnailUrl,
  imageTileUrl,
  type ImageInfo,
} from "@/lib/api/images";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { WorkbenchModal } from "../authoring/WorkbenchModal";
import {
  TiffWindowSelector,
  type TiffWindowSelection,
} from "./TiffWindowSelector";
import { GeoMapArtifactRenderer } from "./geo-map-artifact-renderer";
import { mapInteractionProps } from "./geo-map/map-interaction-props";

const CONTROL_HEIGHT = 20; // IconButton's 2xs size.
const CONTROL_INSET = 4;

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
  mapViewport: {
    bottom: CONTROL_HEIGHT + CONTROL_INSET * 2,
    overflow: "auto",
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
    bottom: CONTROL_INSET,
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
  // The fullscreen modal's body host: the viewer fills it edge to edge.
  fullscreenHost: {
    position: "relative",
    width: "100%",
    height: "100%",
    minHeight: 0,
    flex: 1,
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
  inModal = false,
  initialPage,
  onPageChange,
}: {
  workspaceId: string;
  artifactId: string;
  name: string;
  overlay?: TiffOverlay;
  selection?: TiffWindowSelection;
  /** The page's pixel size, once its tile pyramid describes it. */
  onSize?: (width: number, height: number) => void;
  /** True inside a fullscreen modal: no nested fullscreen button or modal. */
  inModal?: boolean;
  /** The page to open on; a fullscreen copy also follows later changes. */
  initialPage?: number;
  /** Called whenever the viewer pages, so a fullscreen copy can sync its card. */
  onPageChange?: (page: number) => void;
}) {
  const [pageState, setPageState] = useState({
    source: initialPage,
    page: initialPage ?? 0,
  });
  // A fullscreen copy is handed the card's page as `initialPage` and reports
  // its own paging back through `onPageChange`, so the two views follow each
  // other: adopt a changed `initialPage` while rendering, the same way the
  // rest of the workbench adopts a changed prop.
  if (initialPage !== pageState.source) {
    setPageState({ source: initialPage, page: initialPage ?? 0 });
  }
  const page = selection?.window.page ?? overlay?.page ?? pageState.page;
  const [attempt, setAttempt] = useState(0);
  const [fullscreenOpen, setFullscreenOpen] = useState(false);
  const changePage = (next: number) => {
    if (selection) selection.onChange({ ...selection.window, page: next });
    else {
      setPageState((previous) => ({ source: previous.source, page: next }));
      onPageChange?.(next);
    }
  };
  return (
    <>
      <TiffPage
        key={`${workspaceId}:${artifactId}:${page}:${attempt}`}
        artifactId={artifactId}
        path={imagePath(workspaceId, artifactId)}
        page={page}
        name={name}
        onPage={changePage}
        overlay={overlay?.page === page ? overlay : undefined}
        selection={selection}
        allowPageChange={Boolean(selection || !overlay)}
        onSize={onSize}
        onRetry={() => setAttempt(attempt + 1)}
        onOpenFullscreen={inModal ? undefined : () => setFullscreenOpen(true)}
      />
      {!inModal && fullscreenOpen ? (
        <WorkbenchModal
          open={fullscreenOpen}
          onOpenChange={setFullscreenOpen}
          title={name}
          size="viewport"
          bodyLayout="fill"
        >
          <div {...stylex.props(s.fullscreenHost)}>
            <TiffArtifactView
              workspaceId={workspaceId}
              artifactId={artifactId}
              name={name}
              overlay={overlay}
              selection={selection}
              inModal
              initialPage={page}
              onPageChange={changePage}
            />
          </div>
        </WorkbenchModal>
      ) : null}
    </>
  );
}

function TiffPage({
  artifactId,
  path,
  page,
  name,
  onPage,
  onRetry,
  overlay,
  selection,
  allowPageChange,
  onSize,
  onOpenFullscreen,
}: {
  artifactId: string;
  path: string;
  page: number;
  name: string;
  onPage: (page: number) => void;
  onRetry: () => void;
  onSize?: (width: number, height: number) => void;
  overlay?: TiffOverlay;
  selection?: TiffWindowSelection;
  allowPageChange: boolean;
  onOpenFullscreen?: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<OpenSeadragon.Viewer | null>(null);
  const [opened, setOpened] = useState<{
    viewer: OpenSeadragon.Viewer;
    Point: typeof OpenSeadragon.Point;
  } | null>(null);
  const hasFramedResult = useRef(false);
  const [info, setInfo] = useState<ImageInfo | null>(null);
  const [showMap, setShowMap] = useState(false);
  const [mapHeight, setMapHeight] = useState<number>();
  const canShowMap =
    info !== null && "georeferenced" in info && info.georeferenced === true;
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
    if (showMap || !info || !thumbnailReady) return;
    let disposed = false;
    let surfaceResize: ResizeObserver | undefined;
    import("openseadragon")
      .then(({ default: osd }) => {
        if (disposed || !host.current) return;
        const element = host.current;
        const instance = osd({
          element,
          // Firefox caps WebGL contexts per tab, so use the 2D canvas drawer.
          drawer: "canvas",
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
        instance.addHandler("tile-load-failed", (event) => {
          const status = event.tileRequest?.status ?? 0;
          if (status === 401) notifyUnauthorized();
          setError(imageFailure(status));
        });
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
  }, [showMap, info, thumbnailReady, path, page]);

  useEffect(() => {
    if (!showMap || !host.current || typeof ResizeObserver === "undefined")
      return;
    const element = host.current;
    const observer = new ResizeObserver(() =>
      setMapHeight(element.clientHeight),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [showMap]);

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
  function toggleMap() {
    setShowMap(!showMap);
    if (showMap) return;
    setOpened(null);
    setLoaded(false);
    setError(null);
    setEditing(false);
    setSelectedReading(null);
    hasFramedResult.current = false;
  }
  return (
    <section
      aria-label={`${name} scan`}
      className={`nodrag nopan nowheel ${root.className ?? ""}`}
      style={root.style}
      onKeyDown={(event) => {
        if (event.key === "Escape" && selectedReading) {
          // The reading was dismissed by this view, so the keypress must not
          // reach the fullscreen modal around it and close it.
          event.stopPropagation();
          setSelectedReading(null);
        }
        if (editing && event.key === "Escape") {
          event.stopPropagation();
          setEditing(false);
        }
      }}
    >
      {!showMap && !loaded && (
        <img /* eslint-disable-line @next/next/no-img-element -- authenticated thumbnail */
          src={imageThumbnailUrl(path, page)}
          alt={name}
          {...stylex.props(s.thumbnail)}
          onLoad={() => setThumbnailReady(true)}
          onError={() => setThumbnailReady(true)}
        />
      )}
      {showMap ? (
        <div
          key="map"
          ref={host}
          {...mapInteractionProps(stylex.props(s.viewport, s.mapViewport))}
        >
          <GeoMapArtifactRenderer
            artifact={{ artifact_id: artifactId }}
            mode="map"
            autoLoad
            availableHeight={mapHeight}
          />
        </div>
      ) : (
        <div
          key="image"
          ref={host}
          data-tiff-viewport
          data-page={page}
          className={viewport.className}
          style={{ ...viewport.style, zIndex: 0 }}
        />
      )}
      {!showMap && editableSelection && info && opened && loaded && (
        <TiffWindowSelector
          key={String(editing)}
          viewer={opened.viewer}
          PixelPoint={opened.Point}
          size={info}
          selection={editableSelection}
          editing={editing}
        />
      )}
      {!showMap &&
        loaded &&
        !error &&
        selectedReading &&
        selectedReading.overlay === overlay && (
          <div role="status" {...stylex.props(s.reading)}>
            {selectedReading.text}
          </div>
        )}
      {!showMap && (error || !loaded) ? (
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
        {canShowMap && (
          <IconButton
            size="2xs"
            label={showMap ? "Show image" : "Show map"}
            className="nodrag nopan"
            onClick={toggleMap}
          >
            {showMap ? <ImageIcon size={14} /> : <MapIcon size={14} />}
          </IconButton>
        )}
        {onOpenFullscreen && (
          <IconButton
            size="2xs"
            label="Open fullscreen"
            className="nodrag nopan"
            onClick={onOpenFullscreen}
          >
            <Maximize2 size={14} />
          </IconButton>
        )}
        {!showMap && (
          <>
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
          </>
        )}
      </div>
    </section>
  );
}

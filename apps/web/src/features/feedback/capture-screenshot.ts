import type { FeedbackElement } from "@/lib/api/contract";

import { elementAtPoint, FEEDBACK_UI_ATTRIBUTE } from "./element-description";

/** Room around the picked element, in CSS pixels, so the shot shows where it sits. */
const CROP_PADDING = 48;
/** The server refuses more than 2 MiB. */
const MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024;
/** Longest side of the image, in device pixels: a large crop is drawn smaller. */
const MAX_OUTPUT_SIDE = 1800;
const JPEG_QUALITIES = [0.85, 0.7, 0.55] as const;
const CAPTURE_TIMEOUT_MS = 20_000;
/** Outline colour drawn into the image itself, not page styling. */
const OUTLINE_COLOUR = "#e5484d";
/** What a light retry leaves out: the content that makes a redraw stall or fail. */
const HEAVY_TAGS = new Set(["IMG", "PICTURE", "CANVAS", "IFRAME", "VIDEO"]);

export interface Box {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface CapturedScreenshot {
  readonly blob: Blob;
  readonly mayMissCanvas: boolean;
}

/** The element's box with room around it, kept inside the viewport. */
export function screenshotCrop(
  rect: Box,
  viewport: { readonly width: number; readonly height: number },
): Box {
  const left = Math.max(0, Math.floor(rect.x - CROP_PADDING));
  const top = Math.max(0, Math.floor(rect.y - CROP_PADDING));
  const right = Math.min(
    viewport.width,
    Math.ceil(rect.x + rect.width + CROP_PADDING),
  );
  const bottom = Math.min(
    viewport.height,
    Math.ceil(rect.y + rect.height + CROP_PADDING),
  );
  return {
    x: left,
    y: top,
    width: Math.max(1, right - left),
    height: Math.max(1, bottom - top),
  };
}

function canvasBlob(
  canvas: HTMLCanvasElement,
  type: "image/png" | "image/jpeg",
  quality?: number,
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) =>
        blob
          ? resolve(blob)
          : reject(new Error("Could not encode the screenshot")),
      type,
      quality,
    );
  });
}

function overlapsCrop(box: DOMRect, crop: Box): boolean {
  return (
    box.right > crop.x &&
    box.left < crop.x + crop.width &&
    box.bottom > crop.y &&
    box.top < crop.y + crop.height
  );
}

/**
 * Whether the redraw needs `node`. An element taken out of flow (a canvas card, a
 * popover) is left out when it does not reach into the crop: dropping it cannot
 * move anything else, and it is where scans, maps and tables live. A box under
 * 2px is a wrapper such as the canvas's 1px world plane, whose cards hang outside
 * it, so its children are judged one by one. A light retry also drops every image,
 * canvas and frame, accepting that in-flow content may shift.
 */
function redrawNeeds(node: Node, crop: Box, light: boolean): boolean {
  if (!(node instanceof Element)) return true;
  if (node.hasAttribute(FEEDBACK_UI_ATTRIBUTE)) return false;
  if (light && HEAVY_TAGS.has(node.tagName)) return false;
  const box = node.getBoundingClientRect();
  if (box.width < 2 || box.height < 2) return true;
  if (overlapsCrop(box, crop)) return true;
  const position = getComputedStyle(node).position;
  return position !== "absolute" && position !== "fixed";
}

/**
 * Where the redraw starts: the nearest ancestor of what was picked that clips its
 * content and can hold the crop, such as the canvas. Nothing outside a clipping
 * region shows inside it, and Firefox took a minute to draw a whole workbench page
 * of 10k elements, so the rest of the page is left out.
 */
function redrawRoot(element: FeedbackElement, crop: Box): Element {
  const { rect } = element;
  let node = elementAtPoint(
    Math.min(Math.max(rect.x + rect.width / 2, 0), window.innerWidth - 1),
    Math.min(Math.max(rect.y + rect.height / 2, 0), window.innerHeight - 1),
  );
  for (; node && node !== document.body; node = node.parentElement) {
    const box = node.getBoundingClientRect();
    if (box.width < crop.width || box.height < crop.height) continue;
    const { overflowX, overflowY } = getComputedStyle(node);
    if (overflowX === "visible" && overflowY === "visible") continue;
    return node;
  }
  return document.body;
}

async function screenshotOf(
  element: FeedbackElement,
  crop: Box,
  scale: number,
  light: boolean,
): Promise<Blob> {
  const root = redrawRoot(element, crop);
  const frame: Box =
    root === document.body
      ? { x: 0, y: 0, width: window.innerWidth, height: window.innerHeight }
      : root.getBoundingClientRect();
  // The part of the crop the redrawn region covers, in viewport coordinates.
  const left = Math.max(crop.x, frame.x);
  const top = Math.max(crop.y, frame.y);
  const area: Box = {
    x: left,
    y: top,
    width: Math.max(
      1,
      Math.min(crop.x + crop.width, frame.x + frame.width) - left,
    ),
    height: Math.max(
      1,
      Math.min(crop.y + crop.height, frame.y + frame.height) - top,
    ),
  };

  const { domToCanvas } = await import("modern-screenshot");
  const page = await Promise.race([
    domToCanvas(root, {
      width: frame.width,
      height: frame.height,
      scale,
      backgroundColor: getComputedStyle(document.body).backgroundColor,
      filter: (node) => redrawNeeds(node, area, light),
      timeout: CAPTURE_TIMEOUT_MS,
      features: { restoreScrollPosition: true },
      ...(light ? { font: false as const } : {}),
    }),
    new Promise<never>((_, reject) => {
      window.setTimeout(
        () => reject(new Error("The screenshot took too long")),
        CAPTURE_TIMEOUT_MS,
      );
    }),
  ]);

  const output = document.createElement("canvas");
  output.width = Math.round(area.width * scale);
  output.height = Math.round(area.height * scale);
  const context = output.getContext("2d");
  if (!context) throw new Error("Canvas 2D is unavailable");
  context.drawImage(
    page,
    (area.x - frame.x) * scale,
    (area.y - frame.y) * scale,
    output.width,
    output.height,
    0,
    0,
    output.width,
    output.height,
  );
  // Outline what was picked, so the image reads without the element description.
  context.strokeStyle = OUTLINE_COLOUR;
  context.lineWidth = 2 * scale;
  context.strokeRect(
    (element.rect.x - area.x) * scale,
    (element.rect.y - area.y) * scale,
    element.rect.width * scale,
    element.rect.height * scale,
  );

  const png = await canvasBlob(output, "image/png");
  if (png.size <= MAX_SCREENSHOT_BYTES) return png;
  for (const quality of JPEG_QUALITIES) {
    const jpeg = await canvasBlob(output, "image/jpeg", quality);
    if (jpeg.size <= MAX_SCREENSHOT_BYTES) return jpeg;
  }
  throw new Error("The screenshot is larger than the upload limit");
}

/**
 * Photograph the region around `element`, outline it, and encode it under the
 * upload limit. The DOM is redrawn rather than read back from the screen, so
 * WebGL maps and scans can come out blank. When the redraw fails, one light retry
 * leaves images, canvases and frames out rather than sending nothing.
 */
export async function captureElementScreenshot(
  element: FeedbackElement,
): Promise<CapturedScreenshot> {
  const crop = screenshotCrop(element.rect, {
    width: window.innerWidth,
    height: window.innerHeight,
  });
  const scale = Math.min(
    window.devicePixelRatio || 1,
    2,
    MAX_OUTPUT_SIDE / Math.max(crop.width, crop.height),
  );
  try {
    const blob = await screenshotOf(element, crop, scale, false);
    const mayMissCanvas = [...document.querySelectorAll("canvas")].some(
      (canvas) => overlapsCrop(canvas.getBoundingClientRect(), crop),
    );
    return { blob, mayMissCanvas };
  } catch (error) {
    console.warn(
      "Feedback screenshot failed; retrying without images, canvases and frames.",
      error,
    );
  }
  const blob = await screenshotOf(element, crop, scale, true);
  return { blob, mayMissCanvas: true };
}

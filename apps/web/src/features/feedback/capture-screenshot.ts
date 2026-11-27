import type { FeedbackElement } from "@/lib/api/contract";

import { FEEDBACK_UI_ATTRIBUTE } from "./element-description";

/** Room around the picked element, in CSS pixels, so the shot shows where it sits. */
const CROP_PADDING = 48;
/** The server refuses more than 2 MiB. */
const MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024;
const CAPTURE_TIMEOUT_MS = 10_000;
/** Outline colour drawn into the image itself, not page styling. */
const OUTLINE_COLOUR = "#e5484d";

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

/**
 * Photograph the viewport around `element`, outline it, and encode it under the
 * upload limit. The DOM is redrawn rather than read back from the screen, so
 * WebGL maps and scans can come out blank and scrolled lists show their top.
 */
export async function captureElementScreenshot(
  element: FeedbackElement,
): Promise<CapturedScreenshot> {
  const viewport = { width: window.innerWidth, height: window.innerHeight };
  const crop = screenshotCrop(element.rect, viewport);
  const scale = Math.min(window.devicePixelRatio || 1, 2);
  const { domToCanvas } = await import("modern-screenshot");
  const page = await Promise.race([
    domToCanvas(document.body, {
      width: viewport.width,
      height: viewport.height,
      scale,
      backgroundColor: getComputedStyle(document.body).backgroundColor,
      filter: (node) =>
        !(node instanceof Element && node.hasAttribute(FEEDBACK_UI_ATTRIBUTE)),
      timeout: CAPTURE_TIMEOUT_MS,
    }),
    new Promise<never>((_, reject) => {
      window.setTimeout(
        () => reject(new Error("The screenshot took too long")),
        CAPTURE_TIMEOUT_MS,
      );
    }),
  ]);

  const output = document.createElement("canvas");
  output.width = Math.round(crop.width * scale);
  output.height = Math.round(crop.height * scale);
  const context = output.getContext("2d");
  if (!context) throw new Error("Canvas 2D is unavailable");
  context.drawImage(
    page,
    crop.x * scale,
    crop.y * scale,
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
    (element.rect.x - crop.x) * scale,
    (element.rect.y - crop.y) * scale,
    element.rect.width * scale,
    element.rect.height * scale,
  );

  let blob = await canvasBlob(output, "image/png");
  if (blob.size > MAX_SCREENSHOT_BYTES) {
    blob = await canvasBlob(output, "image/jpeg", 0.85);
  }
  if (blob.size > MAX_SCREENSHOT_BYTES) {
    throw new Error("The screenshot is larger than the upload limit");
  }

  const mayMissCanvas = [...document.querySelectorAll("canvas")].some(
    (canvas) => {
      const box = canvas.getBoundingClientRect();
      return (
        box.right > crop.x &&
        box.left < crop.x + crop.width &&
        box.bottom > crop.y &&
        box.top < crop.y + crop.height
      );
    },
  );
  return { blob, mayMissCanvas };
}

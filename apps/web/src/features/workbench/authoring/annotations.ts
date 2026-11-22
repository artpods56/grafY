import { createUuid } from "@/features/workbench/authoring/uuid";
import type { XYPosition } from "./types";

export type AnnotationKind = "text" | "rectangle" | "ellipse";
/** `#RRGGBB` stroke/text color for an annotation. */
export type AnnotationColor = string;

export const ANNOTATION_NODE_TYPE = "grafyAnnotationNode";
export const DEFAULT_ANNOTATION_COLOR = "#475569";
/**
 * Stay under default workflow nodes (z=0) even when React Flow adds
 * SELECTED_NODE_Z (1000) on selection: -1001 + 1000 = -1.
 */
export const ANNOTATION_Z_INDEX = -1001;

/**
 * Curated swatches for the annotation color popover (readable on canvas).
 */
export const ANNOTATION_COLOR_SWATCHES: readonly AnnotationColor[] = [
  "#475569",
  "#b45309",
  "#be123c",
  "#047857",
  "#0369a1",
  "#6d28d9",
  "#171717",
  "#78716c",
];

const HEX_COLOR = /^#[0-9A-Fa-f]{6}$/;

export interface AnnotationLayout {
  width: number;
  height: number;
}

/** Durable presentation annotation payload (mirrors domain / OpenAPI). */
export interface SerializedAnnotation {
  id: string;
  kind: AnnotationKind;
  position: { x: number; y: number };
  layout: AnnotationLayout;
  text: string;
  color: AnnotationColor;
}

export interface AnnotationNodeData {
  kind: AnnotationKind;
  layout: AnnotationLayout;
  text: string;
  color: AnnotationColor;
}

export interface AnnotationNode {
  id: string;
  type?: typeof ANNOTATION_NODE_TYPE;
  position: XYPosition;
  zIndex?: number;
  selected?: boolean;
  data: AnnotationNodeData;
}

export const DEFAULT_ANNOTATION_LAYOUT: Record<
  AnnotationKind,
  AnnotationLayout
> = {
  text: { width: 240, height: 120 },
  rectangle: { width: 160, height: 120 },
  ellipse: { width: 160, height: 160 },
};

const LAYOUT_MIN = 24;
const LAYOUT_MAX = 16_384;
const TEXT_MAX = 8_000;

export function normalizeAnnotationColor(
  value: string | null | undefined,
): AnnotationColor {
  if (!value) return DEFAULT_ANNOTATION_COLOR;
  if (HEX_COLOR.test(value)) return value.toLowerCase();
  return DEFAULT_ANNOTATION_COLOR;
}

export function clampAnnotationLayout(
  layout: AnnotationLayout,
): AnnotationLayout {
  return {
    width: Math.min(LAYOUT_MAX, Math.max(LAYOUT_MIN, layout.width)),
    height: Math.min(LAYOUT_MAX, Math.max(LAYOUT_MIN, layout.height)),
  };
}

export function annotationsFromPresentation(
  presentation:
    | {
        readonly annotations?: readonly SerializedAnnotation[] | null;
      }
    | null
    | undefined,
): AnnotationNode[] {
  const nodes: AnnotationNode[] = [];
  const seen = new Set<string>();
  for (const annotation of presentation?.annotations ?? []) {
    if (!annotation?.id || seen.has(annotation.id)) continue;
    if (
      annotation.kind !== "text" &&
      annotation.kind !== "rectangle" &&
      annotation.kind !== "ellipse"
    ) {
      continue;
    }
    const x = annotation.position?.x;
    const y = annotation.position?.y;
    const width = annotation.layout?.width;
    const height = annotation.layout?.height;
    if (
      typeof x !== "number" ||
      !Number.isFinite(x) ||
      typeof y !== "number" ||
      !Number.isFinite(y) ||
      typeof width !== "number" ||
      !Number.isFinite(width) ||
      typeof height !== "number" ||
      !Number.isFinite(height)
    ) {
      continue;
    }
    seen.add(annotation.id);
    nodes.push({
      id: annotation.id,
      type: ANNOTATION_NODE_TYPE,
      position: { x, y },
      zIndex: ANNOTATION_Z_INDEX,
      data: {
        kind: annotation.kind,
        layout: clampAnnotationLayout({ width, height }),
        text: annotation.kind === "text" ? (annotation.text ?? "") : "",
        color: normalizeAnnotationColor(annotation.color),
      },
    });
  }
  return nodes;
}

export function serializeAnnotations(
  nodes: readonly AnnotationNode[],
): SerializedAnnotation[] {
  return nodes.map((node) => {
    const layout = clampAnnotationLayout(node.data.layout);
    const text =
      node.data.kind === "text" ? node.data.text.slice(0, TEXT_MAX) : "";
    return {
      id: node.id,
      kind: node.data.kind,
      position: { x: node.position.x, y: node.position.y },
      layout: { width: layout.width, height: layout.height },
      text,
      color: normalizeAnnotationColor(node.data.color),
    };
  });
}

export function createAnnotationNode(
  kind: AnnotationKind,
  position: { x: number; y: number },
  id = `annotation-${createUuid()}`,
): AnnotationNode {
  return {
    id,
    type: ANNOTATION_NODE_TYPE,
    position,
    zIndex: ANNOTATION_Z_INDEX,
    selected: true,
    data: {
      kind,
      layout: { ...DEFAULT_ANNOTATION_LAYOUT[kind] },
      text:
        kind === "text" ? "## Note\n\nDescribe this part of the graph." : "",
      color: DEFAULT_ANNOTATION_COLOR,
    },
  };
}

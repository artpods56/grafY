export const DEFAULT_NODE_WIDTH = 300;
/** Approximate chrome height used when placing nodes from canvas drop points. */
export const DEFAULT_NODE_PLACEMENT_HEIGHT = 220;
export const DEFAULT_BODY_HEIGHT = 96;
export const DEFAULT_APPENDIX_HEIGHT = 230;

/** Floors keep node chrome (ports, textarea, appendix) usable. */
export const NODE_WIDTH_MIN = 260;
export const BODY_HEIGHT_MIN = 96;
export const APPENDIX_HEIGHT_MIN = 120;

/**
 * Shared ceiling for width / body / appendix. Anchored to the common
 * browser/GPU max texture dimension; larger layers can fail to composite.
 */
export const LAYOUT_DIMENSION_MAX = 16_384;

export interface WorkflowNodeLayout {
  width?: number;
  bodyHeight?: number;
  appendixHeight?: number;
}

export interface SavedNodeLayout {
  width?: number | null;
  body_height?: number | null;
  appendix_height?: number | null;
}

export interface LayoutClampBounds {
  readonly minWidth?: number;
  readonly maxWidth?: number;
  readonly minBodyHeight?: number;
  readonly maxBodyHeight?: number;
  readonly minAppendixHeight?: number;
  readonly maxAppendixHeight?: number;
}

function clamp(
  value: number | undefined,
  min: number,
  max: number,
): number | undefined {
  if (value === undefined || !Number.isFinite(value)) return undefined;
  return Math.min(max, Math.max(min, value));
}

/** Clamp layout dimensions; returns null when nothing remains set. */
export function clampNodeLayout(
  layout: WorkflowNodeLayout | null | undefined,
  bounds?: LayoutClampBounds,
): WorkflowNodeLayout | null {
  if (!layout) return null;
  const next: WorkflowNodeLayout = {};
  const width = clamp(
    layout.width,
    bounds?.minWidth ?? NODE_WIDTH_MIN,
    bounds?.maxWidth ?? LAYOUT_DIMENSION_MAX,
  );
  const bodyHeight = clamp(
    layout.bodyHeight,
    bounds?.minBodyHeight ?? BODY_HEIGHT_MIN,
    bounds?.maxBodyHeight ?? LAYOUT_DIMENSION_MAX,
  );
  const appendixHeight = clamp(
    layout.appendixHeight,
    bounds?.minAppendixHeight ?? APPENDIX_HEIGHT_MIN,
    bounds?.maxAppendixHeight ?? LAYOUT_DIMENSION_MAX,
  );
  if (width !== undefined) next.width = width;
  if (bodyHeight !== undefined) next.bodyHeight = bodyHeight;
  if (appendixHeight !== undefined) next.appendixHeight = appendixHeight;
  return next.width !== undefined ||
    next.bodyHeight !== undefined ||
    next.appendixHeight !== undefined
    ? next
    : null;
}

export function mergeNodeLayout(
  current: WorkflowNodeLayout | null | undefined,
  patch: WorkflowNodeLayout,
  bounds?: LayoutClampBounds,
): WorkflowNodeLayout | null {
  return clampNodeLayout(
    {
      width: patch.width ?? current?.width,
      bodyHeight: patch.bodyHeight ?? current?.bodyHeight,
      appendixHeight: patch.appendixHeight ?? current?.appendixHeight,
    },
    bounds,
  );
}

export function serializeNodeLayout(
  layout: WorkflowNodeLayout | null | undefined,
  bounds?: LayoutClampBounds,
): SavedNodeLayout | null {
  const clamped = clampNodeLayout(layout, bounds);
  if (!clamped) return null;
  return {
    width: clamped.width ?? null,
    body_height: clamped.bodyHeight ?? null,
    appendix_height: clamped.appendixHeight ?? null,
  };
}

/**
 * Clearance between a service consumer and the provider placed on its input
 * side. One sixth of the shared card width, so the pair stays readable without
 * a second magic gap.
 */
export const SERVICE_PROVIDER_GAP = DEFAULT_NODE_WIDTH / 6;

export interface NodeTopLeft {
  readonly x: number;
  readonly y: number;
}

/** Top-left of a provider card sitting to the left of a consumer. */
export function serviceProviderPositionLeftOf(
  consumer: NodeTopLeft,
): NodeTopLeft {
  return {
    x: consumer.x - DEFAULT_NODE_WIDTH - SERVICE_PROVIDER_GAP,
    y: consumer.y,
  };
}

/**
 * Discovery treats `flowPosition.y` as the card's vertical center and subtracts
 * half {@link DEFAULT_NODE_PLACEMENT_HEIGHT} when it commits. This is the flow
 * point whose ghost and placed card land on `topLeft` and stay clear of the
 * consumer.
 */
export function serviceProviderFlowPosition(topLeft: NodeTopLeft): NodeTopLeft {
  return {
    x: topLeft.x,
    y: topLeft.y + DEFAULT_NODE_PLACEMENT_HEIGHT / 2,
  };
}

export function hydrateNodeLayout(
  layout: SavedNodeLayout | null | undefined,
  bounds?: LayoutClampBounds,
): WorkflowNodeLayout | null {
  if (!layout) return null;
  return clampNodeLayout(
    {
      width: layout.width ?? undefined,
      bodyHeight: layout.body_height ?? undefined,
      appendixHeight: layout.appendix_height ?? undefined,
    },
    bounds,
  );
}

export function resolvedNodeWidth(
  layout: WorkflowNodeLayout | null | undefined,
): number {
  return layout?.width ?? DEFAULT_NODE_WIDTH;
}

export function resolvedBodyHeight(
  layout: WorkflowNodeLayout | null | undefined,
): number | null {
  return layout?.bodyHeight ?? null;
}

export function resolvedAppendixHeight(
  layout: WorkflowNodeLayout | null | undefined,
): number {
  return layout?.appendixHeight ?? DEFAULT_APPENDIX_HEIGHT;
}

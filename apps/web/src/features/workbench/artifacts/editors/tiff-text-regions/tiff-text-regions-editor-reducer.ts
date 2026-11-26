/**
 * Every editing decision for the TIFF text-regions editor, with no React, no DOM,
 * and no fetch in it.
 *
 * The editor is a polygon drawing tool, so the interesting parts of it are the
 * parts a renderer cannot be trusted with: which coordinates a drag is allowed to
 * leave a vertex at, how one pointer gesture becomes one undo step, and what the
 * payload looks like the moment before a save. Those are answered here, against
 * plain data, and the viewer translates pointer events into actions.
 */

import {
  MIN_POLYGON_VERTICES,
  newEditableRegion,
  regionText,
  sameTiffRegions,
  type EditableTextRegion,
  type PixelPoint,
  type RegionReading,
  type RegionReadingField,
  type TiffTextRegionsPayload,
} from "./types";

export type TiffTextRegionsEditorMode =
  "select" | "draw_polygon" | "draw_box" | "eraser";

/** How the side list chooses which regions a person is looking at. */
export type TiffTextRegionsEditorFilter =
  | { readonly kind: "all" }
  | { readonly kind: "unread" }
  | { readonly kind: "query"; readonly query: string };

/**
 * The shape a person is drawing but has not committed.
 *
 * A box is two corners because it is dragged, so its second corner is where the
 * pointer is. A polygon is a chain plus a cursor because it is clicked, so the
 * rubber band between its last vertex and the pointer is a preview and nothing
 * more.
 */
export type TiffTextRegionsDraft =
  | { readonly kind: "box"; readonly from: PixelPoint; readonly to: PixelPoint }
  | {
      readonly kind: "polygon";
      readonly points: readonly PixelPoint[];
      readonly cursor: PixelPoint | null;
    };

export type TiffTextRegionsSelection = {
  readonly region: number;
  readonly vertex: number | null;
};

/** The page in pixels, once its tile pyramid describes it. Coordinates clamp to it. */
export type TiffPageSize = { readonly width: number; readonly height: number };

export type TiffTextRegionsHistoryEntry = {
  readonly payload: TiffTextRegionsPayload;
  readonly selection: TiffTextRegionsSelection | null;
  readonly selectedRegions: readonly number[];
};

type RegionSelection = Pick<
  TiffTextRegionsHistoryEntry,
  "selection" | "selectedRegions"
>;

export type TiffTextRegionsEditorState = {
  readonly payload: TiffTextRegionsPayload;
  /** What the artifact held when the editor opened: what `reset` returns to. */
  readonly baseline: TiffTextRegionsPayload;
  readonly newRegionReadingField: RegionReadingField;
  readonly isDirty: boolean;
  readonly mode: TiffTextRegionsEditorMode;
  readonly selection: TiffTextRegionsSelection | null;
  readonly selectedRegions: readonly number[];
  readonly draft: TiffTextRegionsDraft | null;
  readonly filter: TiffTextRegionsEditorFilter;
  readonly pageSize: TiffPageSize | null;
  readonly past: readonly TiffTextRegionsHistoryEntry[];
  readonly future: readonly TiffTextRegionsHistoryEntry[];
  /**
   * The edit a live gesture is in the middle of. Repeating it folds into one undo
   * step instead of one step per pointer sample.
   */
  readonly coalesce: string | null;
};

export type TiffTextRegionsEditorAction =
  | { readonly type: "set_mode"; readonly mode: TiffTextRegionsEditorMode }
  | { readonly type: "select_region"; readonly index: number }
  | { readonly type: "toggle_select_region"; readonly index: number }
  | { readonly type: "select_vertex"; readonly vertex: number }
  | { readonly type: "clear_selection" }
  | {
      readonly type: "set_page_size";
      readonly width: number;
      readonly height: number;
    }
  | {
      readonly type: "set_reading_text";
      readonly index: number;
      readonly text: string;
    }
  | { readonly type: "clear_reading"; readonly index: number }
  | {
      readonly type: "move_vertex";
      readonly region: number;
      readonly vertex: number;
      readonly x: number;
      readonly y: number;
    }
  | {
      readonly type: "insert_vertex";
      readonly region: number;
      /** Inserts between this vertex and the next one, wrapping at the end. */
      readonly edge: number;
      readonly x: number;
      readonly y: number;
    }
  | {
      readonly type: "delete_vertex";
      readonly region: number;
      readonly vertex: number;
    }
  | {
      readonly type: "translate_polygon";
      readonly region: number;
      readonly dx: number;
      readonly dy: number;
    }
  | { readonly type: "begin_draft"; readonly x: number; readonly y: number }
  | { readonly type: "move_draft"; readonly x: number; readonly y: number }
  | { readonly type: "add_draft_point"; readonly x: number; readonly y: number }
  | { readonly type: "commit_draft" }
  | { readonly type: "cancel_draft" }
  | { readonly type: "delete_selected_region" }
  | { readonly type: "delete_region"; readonly index: number }
  | { readonly type: "merge_selected_regions" }
  | {
      readonly type: "set_filter";
      readonly filter: TiffTextRegionsEditorFilter;
    }
  /** A pointer gesture let go: the next drag on the same handle is its own undo step. */
  | { readonly type: "end_gesture" }
  | { readonly type: "undo" }
  | { readonly type: "redo" }
  | { readonly type: "reset" };

/**
 * Undo depth. A page of regions is a few hundred polygons, and a session that
 * remembers every one of them is a session that grows without bound, so the oldest
 * steps fall out.
 */
export const MAX_HISTORY_ENTRIES = 100;

export function createTiffTextRegionsEditorState(
  payload: TiffTextRegionsPayload,
  newRegionReadingField: RegionReadingField = payload.regions[0]
    ?.readingField ?? "text",
): TiffTextRegionsEditorState {
  return {
    payload,
    baseline: payload,
    newRegionReadingField,
    isDirty: false,
    mode: "select",
    selection: null,
    selectedRegions: [],
    draft: null,
    filter: { kind: "all" },
    pageSize: null,
    past: [],
    future: [],
    coalesce: null,
  };
}

function pageSizeOf(state: TiffTextRegionsEditorState): TiffPageSize {
  return (
    state.pageSize ?? {
      width: Number.MAX_SAFE_INTEGER,
      height: Number.MAX_SAFE_INTEGER,
    }
  );
}

/** Page pixels are never negative, and never past the page the scan describes. */
function clampAxis(value: number, max: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(Math.max(0, value), max);
}

function clampPoint(
  state: TiffTextRegionsEditorState,
  x: number,
  y: number,
): PixelPoint {
  const page = pageSizeOf(state);
  return [clampAxis(x, page.width), clampAxis(y, page.height)];
}

function polygonBounds(polygon: readonly PixelPoint[]) {
  let left = Number.POSITIVE_INFINITY;
  let top = Number.POSITIVE_INFINITY;
  let right = Number.NEGATIVE_INFINITY;
  let bottom = Number.NEGATIVE_INFINITY;
  for (const [x, y] of polygon) {
    left = Math.min(left, x);
    top = Math.min(top, y);
    right = Math.max(right, x);
    bottom = Math.max(bottom, y);
  }
  return { left, top, right, bottom };
}

/**
 * Apply a drag to a whole polygon without letting any corner leave the page.
 *
 * The delta a person moved by is the wish; the delta the page allows is what the
 * polygon gets, so a region shoved off the left edge stops at the edge instead of
 * turning into coordinates the contract refuses.
 */
function clampTranslation(
  state: TiffTextRegionsEditorState,
  polygon: readonly PixelPoint[],
  dx: number,
  dy: number,
): [number, number] {
  const page = pageSizeOf(state);
  const { left, top, right, bottom } = polygonBounds(polygon);
  const appliedX = Math.min(Math.max(dx, -left), page.width - right);
  const appliedY = Math.min(Math.max(dy, -top), page.height - bottom);
  return [appliedX, appliedY];
}

function regionAt(
  state: TiffTextRegionsEditorState,
  index: number,
): EditableTextRegion | null {
  if (index < 0 || index >= state.payload.regions.length) return null;
  return state.payload.regions[index] ?? null;
}

function withRegions(
  state: TiffTextRegionsEditorState,
  regions: readonly EditableTextRegion[],
): TiffTextRegionsPayload {
  return { ...state.payload, regions };
}

function replaceRegion(
  state: TiffTextRegionsEditorState,
  index: number,
  region: EditableTextRegion,
): TiffTextRegionsPayload {
  const regions = state.payload.regions.slice();
  regions[index] = region;
  return withRegions(state, regions);
}

/**
 * Take the step that changes the payload, folding a live gesture into the step it
 * started. `key` names the gesture: two `move_vertex` samples of the same handle
 * share one, so one undo gives the whole drag back.
 */
function commit(
  state: TiffTextRegionsEditorState,
  payload: TiffTextRegionsPayload,
  key: string | null,
  { selection, selectedRegions }: RegionSelection = state,
): TiffTextRegionsEditorState {
  const foldsIntoPrevious = key !== null && state.coalesce === key;
  const past = foldsIntoPrevious
    ? state.past
    : [...state.past, snapshot(state)].slice(-MAX_HISTORY_ENTRIES);
  return {
    ...state,
    payload,
    selection,
    selectedRegions,
    past,
    future: [],
    isDirty: !sameTiffRegions(state.baseline.regions, payload.regions),
    coalesce: key,
  };
}

function snapshot(
  state: TiffTextRegionsEditorState,
): TiffTextRegionsHistoryEntry {
  const { payload, selection, selectedRegions } = state;
  return { payload, selection, selectedRegions };
}

function singleSelection(
  region: number,
  vertex: number | null = null,
  current: readonly number[] = [],
): RegionSelection {
  return {
    selection: { region, vertex },
    selectedRegions:
      current.length === 1 && current[0] === region ? current : [region],
  };
}

function lastSelected(selectedRegions: readonly number[]) {
  const region = selectedRegions.at(-1);
  return region === undefined ? null : { region, vertex: null };
}

function vertexGesture(region: number, vertex: number) {
  return `vertex:${region}:${vertex}`;
}

function boxPolygon(from: PixelPoint, to: PixelPoint): readonly PixelPoint[] {
  const [ax, ay] = from;
  const [bx, by] = to;
  const left = Math.min(ax, bx);
  const right = Math.max(ax, bx);
  const top = Math.min(ay, by);
  const bottom = Math.max(ay, by);
  return [
    [left, top],
    [right, top],
    [right, bottom],
    [left, bottom],
  ];
}

/**
 * The corners of a drawn shape, minus a corner the pointer pressed twice.
 *
 * Closing a polygon is a double-click, and a double-click is a click too, so the
 * last corner arrives twice at the same page pixel. Only an exact repeat goes: two
 * clicks a pixel apart were meant to be two corners.
 */
function withoutRepeats(points: readonly PixelPoint[]): readonly PixelPoint[] {
  const kept: PixelPoint[] = [];
  for (const point of points) {
    const previous = kept[kept.length - 1];
    if (previous && previous[0] === point[0] && previous[1] === point[1])
      continue;
    kept.push(point);
  }
  return kept;
}

function updatedReading(
  region: EditableTextRegion,
  reading: RegionReading | null,
): EditableTextRegion {
  return { ...region, reading };
}

function selectionAfterDelete(
  { selection, selectedRegions }: RegionSelection,
  removed: number,
): RegionSelection {
  const remap = (index: number) => (index > removed ? index - 1 : index);
  const remaining = selectedRegions
    .filter((index) => index !== removed)
    .map(remap);
  return {
    selectedRegions: remaining,
    selection:
      selection && selection.region !== removed
        ? { ...selection, region: remap(selection.region) }
        : lastSelected(remaining),
  };
}

function convexHull(points: readonly PixelPoint[]): readonly PixelPoint[] {
  const sorted = withoutRepeats(
    [...points].sort(([ax, ay], [bx, by]) => ax - bx || ay - by),
  );
  if (sorted.length < MIN_POLYGON_VERTICES) return sorted;

  // Andrew's monotone chain discards collinear points along each hull edge.
  function half(vertices: readonly PixelPoint[]) {
    const hull: PixelPoint[] = [];
    for (const point of vertices) {
      while (hull.length >= 2) {
        const a = hull[hull.length - 2];
        const b = hull[hull.length - 1];
        if (!a || !b) break;
        const turn =
          (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0]);
        if (turn > 0) break;
        hull.pop();
      }
      hull.push(point);
    }
    return hull.slice(0, -1);
  }

  return [...half(sorted), ...half([...sorted].reverse())];
}

function mergedReading(
  regions: readonly EditableTextRegion[],
): RegionReading | null {
  const positions = regions.map((region) => {
    const { left, top, right, bottom } = polygonBounds(region.polygon);
    return {
      region,
      x: (left + right) / 2,
      y: (top + bottom) / 2,
      height: bottom - top,
    };
  });
  const rowTolerance =
    positions.reduce((sum, { height }) => sum + height, 0) /
    (2 * positions.length);
  positions.sort((a, b) => a.y - b.y);
  const words: string[] = [];
  for (let start = 0; start < positions.length;) {
    const first = positions[start];
    if (!first) break;
    let end = start + 1;
    while (end < positions.length) {
      const next = positions[end];
      if (!next || next.y - first.y > rowTolerance) break;
      end += 1;
    }
    for (const { region } of positions
      .slice(start, end)
      .sort((a, b) => a.x - b.x)) {
      const text = regionText(region).trim();
      if (text) words.push(text);
    }
    start = end;
  }
  if (words.length === 0) return null;

  const scores = regions.flatMap(({ reading }) =>
    reading?.confidence == null ? [] : [reading.confidence],
  );
  return {
    text: words.join(" "),
    confidence:
      scores.length === 0
        ? null
        : scores.reduce((sum, score) => sum + score, 0) / scores.length,
  };
}

export function tiffTextRegionsEditorReducer(
  state: TiffTextRegionsEditorState,
  action: TiffTextRegionsEditorAction,
): TiffTextRegionsEditorState {
  switch (action.type) {
    case "set_mode": {
      if (action.mode === state.mode) return state;
      // A half-drawn shape belongs to the mode it was drawn in.
      return { ...state, mode: action.mode, draft: null, coalesce: null };
    }

    case "select_region":
      return regionAt(state, action.index)
        ? { ...state, ...singleSelection(action.index), coalesce: null }
        : state;

    case "toggle_select_region": {
      const { index } = action;
      if (!regionAt(state, index)) return state;
      if (state.selectedRegions.includes(index)) {
        const selectedRegions = state.selectedRegions.filter(
          (selected) => selected !== index,
        );
        return {
          ...state,
          selectedRegions,
          selection: lastSelected(selectedRegions),
          coalesce: null,
        };
      }
      return {
        ...state,
        selectedRegions: [...state.selectedRegions, index].sort(
          (a, b) => a - b,
        ),
        selection: { region: index, vertex: null },
        coalesce: null,
      };
    }

    case "select_vertex": {
      const selection = state.selection;
      if (!selection) return state;
      const region = regionAt(state, selection.region);
      if (
        !region ||
        action.vertex < 0 ||
        action.vertex >= region.polygon.length
      ) {
        return state;
      }
      return {
        ...state,
        selection: { region: selection.region, vertex: action.vertex },
        coalesce: null,
      };
    }

    case "clear_selection":
      return state.selection === null
        ? state
        : { ...state, selection: null, selectedRegions: [], coalesce: null };

    case "set_page_size": {
      const width = clampAxis(action.width, Number.MAX_SAFE_INTEGER);
      const height = clampAxis(action.height, Number.MAX_SAFE_INTEGER);
      if (width <= 0 || height <= 0) return state;
      if (
        state.pageSize?.width === width &&
        state.pageSize?.height === height
      ) {
        return state;
      }
      return { ...state, pageSize: { width, height } };
    }

    case "set_reading_text": {
      const region = regionAt(state, action.index);
      if (!region) return state;
      const confidence = region.reading?.confidence ?? null;
      const next = replaceRegion(
        state,
        action.index,
        updatedReading(region, { text: action.text, confidence }),
      );
      return commit(state, next, `text:${action.index}`);
    }

    case "clear_reading": {
      const region = regionAt(state, action.index);
      if (!region || region.reading === null) return state;
      const next = replaceRegion(
        state,
        action.index,
        updatedReading(region, null),
      );
      return commit(state, next, null);
    }

    case "move_vertex": {
      const region = regionAt(state, action.region);
      if (!region) return state;
      const vertex = region.polygon[action.vertex];
      if (!vertex) return state;
      const [x, y] = clampPoint(state, action.x, action.y);
      if (vertex[0] === x && vertex[1] === y) return state;
      const polygon = region.polygon.slice();
      polygon[action.vertex] = [x, y];
      const next = replaceRegion(state, action.region, { ...region, polygon });
      const selection = state.selection;
      const keepsSelection =
        selection !== null && selection.region === action.region;
      return commit(state, next, vertexGesture(action.region, action.vertex), {
        selectedRegions: state.selectedRegions,
        selection: keepsSelection
          ? { ...selection, vertex: action.vertex }
          : selection,
      });
    }

    case "insert_vertex": {
      const region = regionAt(state, action.region);
      if (!region) return state;
      const count = region.polygon.length;
      if (
        !Number.isInteger(action.edge) ||
        action.edge < 0 ||
        action.edge >= count
      )
        return state;
      const [x, y] = clampPoint(state, action.x, action.y);
      const polygon = region.polygon.slice();
      const at = action.edge + 1;
      polygon.splice(at, 0, [x, y]);
      const next = replaceRegion(state, action.region, { ...region, polygon });
      return commit(
        { ...state, coalesce: null },
        next,
        vertexGesture(action.region, at),
        singleSelection(action.region, at, state.selectedRegions),
      );
    }

    case "delete_vertex": {
      const region = regionAt(state, action.region);
      if (!region) return state;
      if (region.polygon.length <= MIN_POLYGON_VERTICES) return state;
      if (!region.polygon[action.vertex]) return state;
      const polygon = region.polygon.slice();
      polygon.splice(action.vertex, 1);
      const next = replaceRegion(state, action.region, { ...region, polygon });
      return commit(
        state,
        next,
        null,
        singleSelection(action.region, null, state.selectedRegions),
      );
    }

    case "translate_polygon": {
      const region = regionAt(state, action.region);
      if (!region) return state;
      const [dx, dy] = clampTranslation(
        state,
        region.polygon,
        action.dx,
        action.dy,
      );
      if (dx === 0 && dy === 0) return state;
      const polygon = region.polygon.map(
        ([x, y]) => [x + dx, y + dy] as PixelPoint,
      );
      const next = replaceRegion(state, action.region, { ...region, polygon });
      return commit(state, next, `translate:${action.region}`);
    }

    case "begin_draft": {
      if (state.mode !== "draw_box" && state.mode !== "draw_polygon")
        return state;
      const [x, y] = clampPoint(state, action.x, action.y);
      const draft: TiffTextRegionsDraft =
        state.mode === "draw_polygon"
          ? { kind: "polygon", points: [[x, y]], cursor: null }
          : { kind: "box", from: [x, y], to: [x, y] };
      return { ...state, draft, coalesce: null };
    }

    case "move_draft": {
      const draft = state.draft;
      if (!draft) return state;
      const [x, y] = clampPoint(state, action.x, action.y);
      if (draft.kind === "box") {
        return { ...state, draft: { ...draft, to: [x, y] } };
      }
      return { ...state, draft: { ...draft, cursor: [x, y] } };
    }

    // The corner a person clicks in polygon mode. It stands on its own rather than
    // waiting for a `begin_draft`, because the press that decides it was made
    // against a render that may not have seen the corner before it yet.
    case "add_draft_point": {
      if (state.mode !== "draw_polygon") return state;
      const [x, y] = clampPoint(state, action.x, action.y);
      const corner: PixelPoint = [x, y];
      const points: PixelPoint[] =
        state.draft?.kind === "polygon"
          ? [...state.draft.points, corner]
          : [corner];
      return { ...state, draft: { kind: "polygon", points, cursor: null } };
    }

    case "commit_draft": {
      const draft = state.draft;
      if (!draft) return state;
      if (draft.kind === "box") {
        const [fromX, fromY] = draft.from;
        const [toX, toY] = draft.to;
        if (fromX === toX || fromY === toY) {
          // A click, not a drag: nothing was outlined, so nothing is added.
          return { ...state, draft: null, coalesce: null };
        }
        const region = newEditableRegion(
          boxPolygon(draft.from, draft.to),
          state.newRegionReadingField,
        );
        const index = state.payload.regions.length;
        const next = withRegions(state, [...state.payload.regions, region]);
        return {
          ...commit(state, next, null, singleSelection(index)),
          draft: null,
        };
      }
      const points = withoutRepeats(draft.points);
      if (points.length < MIN_POLYGON_VERTICES) return state;
      const region = newEditableRegion(points, state.newRegionReadingField);
      const index = state.payload.regions.length;
      const next = withRegions(state, [...state.payload.regions, region]);
      return {
        ...commit(state, next, null, singleSelection(index)),
        draft: null,
      };
    }

    case "cancel_draft":
      return state.draft === null
        ? state
        : { ...state, draft: null, coalesce: null };

    case "delete_selected_region": {
      const selected = new Set(state.selectedRegions);
      if (selected.size === 0) {
        if (!state.selection || !regionAt(state, state.selection.region))
          return state;
        selected.add(state.selection.region);
      }
      const regions = state.payload.regions.filter(
        (_, index) => !selected.has(index),
      );
      return commit(state, withRegions(state, regions), null, {
        selection: null,
        selectedRegions: [],
      });
    }

    case "delete_region": {
      const { index } = action;
      if (!regionAt(state, index)) return state;
      const regions = state.payload.regions.slice();
      regions.splice(index, 1);
      return commit(
        state,
        withRegions(state, regions),
        null,
        selectionAfterDelete(state, index),
      );
    }

    case "merge_selected_regions": {
      const target = state.selectedRegions[0];
      if (target === undefined || state.selectedRegions.length < 2)
        return state;
      const selected = new Set(state.selectedRegions);
      const inputs = state.payload.regions.filter((_, index) =>
        selected.has(index),
      );
      const base = inputs[0];
      if (!base) return state;
      const polygon = convexHull(inputs.flatMap((region) => region.polygon));
      if (polygon.length < MIN_POLYGON_VERTICES) return state;
      const merged: EditableTextRegion = {
        ...base,
        polygon,
        reading: mergedReading(inputs),
        readingExtra: {
          ...base.readingExtra,
          model: base.readingField === "reading" ? "manual" : null,
        },
      };
      const regions = replaceRegion(state, target, merged).regions.filter(
        (_, index) => index === target || !selected.has(index),
      );
      return commit(
        state,
        withRegions(state, regions),
        null,
        singleSelection(target),
      );
    }

    case "set_filter": {
      const filter = normalizeFilter(action.filter);
      if (
        filter.kind === state.filter.kind &&
        filterQuery(filter) === filterQuery(state.filter)
      ) {
        return state;
      }
      return { ...state, filter };
    }

    case "end_gesture":
      return state.coalesce === null ? state : { ...state, coalesce: null };

    case "undo": {
      const previous = state.past[state.past.length - 1];
      if (!previous) return state;
      return {
        ...state,
        ...previous,
        past: state.past.slice(0, -1),
        future: [...state.future, snapshot(state)],
        draft: null,
        isDirty: !sameTiffRegions(
          state.baseline.regions,
          previous.payload.regions,
        ),
        coalesce: null,
      };
    }

    case "redo": {
      const nextEntry = state.future[state.future.length - 1];
      if (!nextEntry) return state;
      return {
        ...state,
        ...nextEntry,
        past: [...state.past, snapshot(state)],
        future: state.future.slice(0, -1),
        draft: null,
        isDirty: !sameTiffRegions(
          state.baseline.regions,
          nextEntry.payload.regions,
        ),
        coalesce: null,
      };
    }

    case "reset": {
      if (!state.isDirty && state.draft === null) return state;
      return {
        ...state,
        payload: state.baseline,
        selection: null,
        selectedRegions: [],
        draft: null,
        past: [],
        future: [],
        isDirty: false,
        coalesce: null,
      };
    }
  }
}

/** A drag that ends where it began is not an edit, and must not become an undo step. */
export function canUndo(state: TiffTextRegionsEditorState): boolean {
  return state.past.length > 0;
}

export function canRedo(state: TiffTextRegionsEditorState): boolean {
  return state.future.length > 0;
}

function filterQuery(filter: TiffTextRegionsEditorFilter): string {
  return filter.kind === "query" ? filter.query : "";
}

function normalizeFilter(
  filter: TiffTextRegionsEditorFilter,
): TiffTextRegionsEditorFilter {
  if (filter.kind !== "query") return filter;
  const query = filter.query.trim();
  return query === "" ? { kind: "all" } : { kind: "query", query };
}

function regionMatches(
  region: EditableTextRegion,
  filter: TiffTextRegionsEditorFilter,
): boolean {
  const text = region.reading?.text ?? "";
  if (filter.kind === "unread") return text.trim() === "";
  if (filter.kind === "query") {
    return text.toLowerCase().includes(filterQuery(filter).toLowerCase());
  }
  return true;
}

/** Which regions the side list shows, as indexes into the payload, in payload order. */
export function visibleRegionIndexes(
  state: TiffTextRegionsEditorState,
): number[] {
  const filter = normalizeFilter(state.filter);
  const indexes: number[] = [];
  for (const [index, region] of state.payload.regions.entries()) {
    if (regionMatches(region, filter)) indexes.push(index);
  }
  return indexes;
}

/** The polygon the canvas should draw in the person's hand. */
export function draftPolygon(
  draft: TiffTextRegionsDraft,
): readonly PixelPoint[] {
  if (draft.kind === "box") return boxPolygon(draft.from, draft.to);
  return draft.points;
}

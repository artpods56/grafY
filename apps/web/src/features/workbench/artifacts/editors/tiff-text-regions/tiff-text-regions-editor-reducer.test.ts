import { describe, expect, it } from "vitest";

import {
  parseTiffTextRegionsPayload,
  serializeTiffTextRegionsPayload,
  MIN_POLYGON_VERTICES,
  type EditableTextRegion,
  type PixelPoint,
  type TiffTextRegionsPayload,
} from "./types";
import {
  MAX_HISTORY_ENTRIES,
  canRedo,
  canUndo,
  createTiffTextRegionsEditorState,
  draftPolygon,
  tiffTextRegionsEditorReducer as reduce,
  visibleRegionIndexes,
  type TiffTextRegionsEditorAction,
  type TiffTextRegionsEditorState,
} from "./tiff-text-regions-editor-reducer";

const BOX = [
  [10, 10],
  [60, 10],
  [60, 40],
  [10, 40],
];

const SOURCE = {
  artifact_id: "a0000000-0000-4000-8000-000000000001",
  artifact_type: "file.tiff",
  schema_version: 1,
  content_hash: "0".repeat(64),
};

const WINDOW = { page: 2, col: 100, row: 200, width: 512, height: 256 };

function payloadRaw(regions: unknown[]): Record<string, unknown> {
  return { source: SOURCE, window: WINDOW, regions };
}

function parsed(regions: unknown[]): TiffTextRegionsPayload {
  const result = parseTiffTextRegionsPayload(payloadRaw(regions));
  if (!result.ok) throw new Error(result.reason);
  return result.payload;
}

function parsedRaw(raw: unknown): TiffTextRegionsPayload {
  const result = parseTiffTextRegionsPayload(raw);
  if (!result.ok) throw new Error(result.reason);
  return result.payload;
}

function stateWith(...regions: unknown[]): TiffTextRegionsEditorState {
  return createTiffTextRegionsEditorState(parsed(regions));
}

function regionAt(
  state: TiffTextRegionsEditorState,
  index = 0,
): EditableTextRegion {
  const region = state.payload.regions[index];
  if (!region) throw new Error(`no region ${index}`);
  return region;
}

function polygonAt(state: TiffTextRegionsEditorState, index = 0): number[][] {
  return regionAt(state, index).polygon.map(([x, y]) => [x, y]);
}

describe("parseTiffTextRegionsPayload", () => {
  it("reads a detector's flat region and keeps the reference contract intact", () => {
    const payload = parsed([{ polygon: BOX, text: "Hiawatha", score: 0.75 }]);
    expect(payload.source).toEqual({
      artifact_id: SOURCE.artifact_id,
      artifact_type: "file.tiff",
      schema_version: 1,
    });
    expect(payload.sourceExtra).toEqual({ content_hash: SOURCE.content_hash });
    expect(payload.window).toEqual(WINDOW);
    expect(payload.regions[0]?.reading).toEqual({
      text: "Hiawatha",
      confidence: 0.75,
    });
    expect(payload.regions[0]?.readingField).toBe("text");
  });

  it("reads a recognizer's reading and leaves the model on the wire, not in the model", () => {
    const payload = parsed([
      {
        polygon: BOX,
        text: "detector guess",
        score: 0.2,
        reading: { text: "Hiawatha", confidence: 0.91, model: "paddle-v4" },
      },
    ]);
    const region = payload.regions[0];
    if (!region) throw new Error("expected a region");
    expect(region.readingField).toBe("reading");
    expect(region.reading).toEqual({ text: "Hiawatha", confidence: 0.91 });
    expect(region.readingExtra).toEqual({ model: "paddle-v4" });
    expect(region.extra).toEqual({ text: "detector guess", score: 0.2 });
  });

  it("keeps a region whose reading was never filled in", () => {
    const payload = parsed([{ polygon: BOX, text: null, reading: null }]);
    expect(payload.regions[0]?.reading).toBeNull();
    expect(payload.regions[0]?.readingField).toBe("reading");
  });

  it("round-trips a payload it did not touch, keys and all", () => {
    const raw = payloadRaw([
      {
        polygon: BOX,
        text: "Line one",
        score: null,
        quality: 3,
        tags: ["title"],
      },
    ]);
    raw.window = { ...WINDOW, dpi: 600 };
    const serialized = serializeTiffTextRegionsPayload(parsedRaw(raw));
    expect(serialized).toEqual({
      source: {
        artifact_id: SOURCE.artifact_id,
        artifact_type: "file.tiff",
        schema_version: 1,
        content_hash: SOURCE.content_hash,
      },
      window: {
        ...WINDOW,
        dpi: 600,
      },
      regions: [
        {
          polygon: BOX,
          text: "Line one",
          score: null,
          quality: 3,
          tags: ["title"],
        },
      ],
    });
  });

  it("keeps payload keys this schema version does not declare", () => {
    const raw = { ...payloadRaw([{ polygon: BOX }]), producer: "map_toponyms" };
    const serialized = serializeTiffTextRegionsPayload(parsedRaw(raw));
    expect(serialized.producer).toBe("map_toponyms");
  });

  it("refuses a payload that is not text regions, with a reason a person can read", () => {
    expect(parseTiffTextRegionsPayload(null)).toEqual({
      ok: false,
      reason: "This artifact is not a set of TIFF text regions.",
    });
    expect(
      parseTiffTextRegionsPayload({ window: WINDOW, regions: [] }),
    ).toEqual({
      ok: false,
      reason:
        "These text regions name no source scan, so they cannot be edited.",
    });
    expect(
      parseTiffTextRegionsPayload({ source: SOURCE, regions: [] }),
    ).toEqual({
      ok: false,
      reason:
        "These text regions are missing their page window or region list.",
    });
  });

  it("refuses a region the contract would reject rather than drop it on save", () => {
    expect(
      parseTiffTextRegionsPayload(
        payloadRaw([
          {
            polygon: [
              [0, 0],
              [1, 1],
            ],
          },
        ]),
      ),
    ).toEqual({
      ok: false,
      reason: "Region 1 has no polygon this editor can draw.",
    });
    expect(
      parseTiffTextRegionsPayload(
        payloadRaw([
          {
            polygon: [
              [0, 0],
              [1, 1],
              [-3, 2],
            ],
          },
        ]),
      ).ok,
    ).toBe(false);
  });
});

describe("serializeTiffTextRegionsPayload", () => {
  it("takes a whole editor state as readily as a payload", () => {
    const state = stateWith({ polygon: BOX, text: "Somewhere", score: 0.5 });
    expect(serializeTiffTextRegionsPayload(state)).toEqual(
      serializeTiffTextRegionsPayload(state.payload),
    );
  });

  it("writes an edited reading back into the field it came from", () => {
    let state = stateWith({
      polygon: BOX,
      reading: { text: "old", confidence: 0.4, model: "paddle-v4" },
    });
    state = reduce(state, { type: "set_reading_text", index: 0, text: "new" });
    const serialized = serializeTiffTextRegionsPayload(state);
    expect(serialized.regions).toEqual([
      {
        polygon: BOX,
        reading: { model: "paddle-v4", text: "new", confidence: 0.4 },
      },
    ]);
  });

  it("names the editor, not a recognizer, when a reading had nothing behind it", () => {
    let state = stateWith({ polygon: BOX, reading: null });
    state = reduce(state, {
      type: "set_reading_text",
      index: 0,
      text: "typed by hand",
    });
    expect(serializeTiffTextRegionsPayload(state).regions).toEqual([
      {
        polygon: BOX,
        reading: { model: "manual", text: "typed by hand", confidence: null },
      },
    ]);
  });

  it("gives a region it cleared a null reading, not an empty one", () => {
    let state = stateWith({ polygon: BOX, reading: { text: "old" } });
    state = reduce(state, { type: "clear_reading", index: 0 });
    expect(serializeTiffTextRegionsPayload(state).regions).toEqual([
      { polygon: BOX, reading: null },
    ]);
  });
});

describe("selection", () => {
  it("selects and deselects a region by index", () => {
    let state = stateWith({ polygon: BOX }, { polygon: BOX });
    state = reduce(state, { type: "select_region", index: 1 });
    expect(state.selection).toEqual({ region: 1, vertex: null });
    state = reduce(state, { type: "clear_selection" });
    expect(state.selection).toBeNull();
  });

  it("ignores an index that is not there, forwards or back", () => {
    const state = stateWith({ polygon: BOX });
    expect(
      reduce(state, { type: "select_region", index: 1 }).selection,
    ).toBeNull();
    expect(
      reduce(state, { type: "select_region", index: -1 }).selection,
    ).toBeNull();
  });

  it("moves a selection from a region to one of its vertices", () => {
    let state = stateWith({ polygon: BOX });
    state = reduce(state, { type: "select_region", index: 0 });
    state = reduce(state, { type: "select_vertex", vertex: 2 });
    expect(state.selection).toEqual({ region: 0, vertex: 2 });
    expect(
      reduce(state, { type: "select_vertex", vertex: 9 }).selection,
    ).toEqual({
      region: 0,
      vertex: 2,
    });
  });
});

describe("reading text", () => {
  it("types into a region that never had a reading", () => {
    let state = stateWith({ polygon: BOX });
    state = reduce(state, {
      type: "set_reading_text",
      index: 0,
      text: "Fort Garry",
    });
    expect(regionAt(state).reading).toEqual({
      text: "Fort Garry",
      confidence: null,
    });
    expect(state.isDirty).toBe(true);
  });

  it("keeps the score a recognizer gave while the words change", () => {
    let state = stateWith({ polygon: BOX, text: "Fort Garry", score: 0.88 });
    state = reduce(state, {
      type: "set_reading_text",
      index: 0,
      text: "Fort Whyte",
    });
    expect(regionAt(state).reading).toEqual({
      text: "Fort Whyte",
      confidence: 0.88,
    });
    expect(serializeTiffTextRegionsPayload(state).regions).toEqual([
      { polygon: BOX, text: "Fort Whyte", score: 0.88 },
    ]);
  });

  it("clears to no reading at all", () => {
    let state = stateWith({ polygon: BOX, text: "Fort Garry", score: 0.88 });
    state = reduce(state, { type: "clear_reading", index: 0 });
    expect(regionAt(state).reading).toBeNull();
    expect(serializeTiffTextRegionsPayload(state).regions).toEqual([
      { polygon: BOX, text: null, score: null },
    ]);
  });

  it("leaves the other regions alone", () => {
    let state = stateWith(
      { polygon: BOX, text: "one" },
      { polygon: BOX, text: "two" },
    );
    state = reduce(state, {
      type: "set_reading_text",
      index: 1,
      text: "changed",
    });
    expect(regionAt(state, 0).reading?.text).toBe("one");
    expect(regionAt(state, 1).reading?.text).toBe("changed");
  });
});

describe("polygon geometry", () => {
  it("moves one vertex and leaves its siblings", () => {
    let state = stateWith({ polygon: BOX });
    state = reduce(state, {
      type: "move_vertex",
      region: 0,
      vertex: 1,
      x: 70,
      y: 22,
    });
    expect(polygonAt(state)).toEqual([
      [10, 10],
      [70, 22],
      [60, 40],
      [10, 40],
    ]);
  });

  it("never leaves a vertex off the top-left of the page", () => {
    let state = stateWith({ polygon: BOX });
    state = reduce(state, {
      type: "move_vertex",
      region: 0,
      vertex: 0,
      x: -50,
      y: -12,
    });
    expect(polygonAt(state)[0]).toEqual([0, 0]);
  });

  it("keeps a vertex inside the page once the pyramid has said how big it is", () => {
    let state = stateWith({ polygon: BOX });
    state = reduce(state, { type: "set_page_size", width: 800, height: 600 });
    state = reduce(state, {
      type: "move_vertex",
      region: 0,
      vertex: 2,
      x: 9_999,
      y: 40,
    });
    expect(polygonAt(state)[2]).toEqual([800, 40]);
  });

  it("inserts a vertex on an edge, wrapping past the last corner", () => {
    let state = stateWith({ polygon: BOX });
    state = reduce(state, {
      type: "insert_vertex",
      region: 0,
      edge: 1,
      x: 65,
      y: 25,
    });
    expect(polygonAt(state)).toEqual([
      [10, 10],
      [60, 10],
      [65, 25],
      [60, 40],
      [10, 40],
    ]);
    expect(state.selection).toEqual({ region: 0, vertex: 2 });

    state = reduce(state, {
      type: "insert_vertex",
      region: 0,
      edge: 4,
      x: 5,
      y: 25,
    });
    expect(polygonAt(state)[5]).toEqual([5, 25]);
    const beyond = reduce(state, {
      type: "insert_vertex",
      region: 0,
      edge: 9,
      x: 1,
      y: 1,
    });
    expect(beyond).toBe(state);
    expect(polygonAt(state)).toHaveLength(6);
  });

  it("deletes a vertex but never the last three", () => {
    let state = stateWith({ polygon: BOX });
    state = reduce(state, { type: "delete_vertex", region: 0, vertex: 2 });
    expect(polygonAt(state)).toEqual([
      [10, 10],
      [60, 10],
      [10, 40],
    ]);
    state = reduce(state, { type: "delete_vertex", region: 0, vertex: 0 });
    expect(polygonAt(state)).toHaveLength(MIN_POLYGON_VERTICES);
    expect(state.isDirty).toBe(true);
  });

  it("slides a whole polygon and stops it at the page edge", () => {
    let state = stateWith({ polygon: BOX });
    state = reduce(state, {
      type: "translate_polygon",
      region: 0,
      dx: -100,
      dy: 5,
    });
    expect(polygonAt(state)).toEqual([
      [0, 15],
      [50, 15],
      [50, 45],
      [0, 45],
    ]);
    state = reduce(state, { type: "set_page_size", width: 100, height: 100 });
    state = reduce(state, {
      type: "translate_polygon",
      region: 0,
      dx: 90,
      dy: 90,
    });
    expect(polygonAt(state)).toEqual([
      [50, 70],
      [100, 70],
      [100, 100],
      [50, 100],
    ]);
  });

  it("refuses a translate that would push every corner off the page anyway", () => {
    const state = stateWith({ polygon: BOX });
    const untouched = reduce(state, {
      type: "translate_polygon",
      region: 0,
      dx: 0,
      dy: 0,
    });
    expect(untouched).toBe(state);
    expect(canUndo(untouched)).toBe(false);
  });
});

describe("drawing", () => {
  it("drags a box out of two corners, however the pointer travelled", () => {
    let state = stateWith();
    state = reduce(state, { type: "set_mode", mode: "draw_box" });
    state = reduce(state, { type: "begin_draft", x: 60, y: 40 });
    state = reduce(state, { type: "move_draft", x: 10, y: 10 });
    if (state.draft?.kind !== "box") throw new Error("expected a box draft");
    expect(draftPolygon(state.draft)).toEqual(BOX);
    state = reduce(state, { type: "commit_draft" });
    expect(polygonAt(state)).toEqual(BOX);
    expect(state.draft).toBeNull();
    expect(state.selection).toEqual({ region: 0, vertex: null });
    expect(state.selectedRegions).toEqual([0]);
    expect(state.isDirty).toBe(true);
  });

  it("adds nothing for a click that never became a drag", () => {
    let state = stateWith();
    state = reduce(state, { type: "set_mode", mode: "draw_box" });
    state = reduce(state, { type: "begin_draft", x: 30, y: 30 });
    state = reduce(state, { type: "commit_draft" });
    expect(state.payload.regions).toHaveLength(0);
    expect(state.isDirty).toBe(false);
    expect(state.draft).toBeNull();
  });

  it("clicks a polygon out vertex by vertex and closes it at three", () => {
    let state = stateWith();
    state = reduce(state, { type: "set_mode", mode: "draw_polygon" });
    // The first corner is a press like any other: no gesture opened it.
    state = reduce(state, { type: "add_draft_point", x: 0, y: 0 });
    state = reduce(state, { type: "add_draft_point", x: 50, y: 0 });
    expect(reduce(state, { type: "commit_draft" })).toBe(state);
    if (state.draft?.kind !== "polygon")
      throw new Error("expected a polygon draft");
    expect(state.draft.points).toHaveLength(2);
    state = reduce(state, { type: "add_draft_point", x: 25, y: 30 });
    state = reduce(state, { type: "commit_draft" });
    expect(polygonAt(state)).toEqual([
      [0, 0],
      [50, 0],
      [25, 30],
    ]);
    expect(state.draft).toBeNull();
  });

  it("previews the rubber band from the last vertex to the pointer", () => {
    let state = stateWith();
    state = reduce(state, { type: "set_mode", mode: "draw_polygon" });
    state = reduce(state, { type: "begin_draft", x: 0, y: 0 });
    state = reduce(state, { type: "move_draft", x: 12, y: 34 });
    if (state.draft?.kind !== "polygon")
      throw new Error("expected a polygon draft");
    expect(state.draft.cursor).toEqual([12, 34]);
    expect(state.draft.points).toEqual([[0, 0]]);
  });

  it("drops the corner a double-click to close pressed a second time", () => {
    let state = stateWith();
    state = reduce(state, { type: "set_mode", mode: "draw_polygon" });
    // The double-click that says "closed" is also the click of the last corner.
    const corners: PixelPoint[] = [
      [0, 0],
      [50, 0],
      [25, 30],
      [25, 30],
    ];
    for (const [x, y] of corners) {
      state = reduce(state, { type: "add_draft_point", x, y });
    }
    state = reduce(state, { type: "commit_draft" });
    expect(polygonAt(state)).toEqual([
      [0, 0],
      [50, 0],
      [25, 30],
    ]);
  });

  it("keeps two corners a pixel apart, which were meant as two corners", () => {
    let state = stateWith();
    state = reduce(state, { type: "set_mode", mode: "draw_polygon" });
    const corners: PixelPoint[] = [
      [0, 0],
      [50, 0],
      [25, 30],
      [26, 30],
    ];
    for (const [x, y] of corners) {
      state = reduce(state, { type: "add_draft_point", x, y });
    }
    state = reduce(state, { type: "commit_draft" });
    expect(polygonAt(state)).toHaveLength(4);
  });

  it("cancels a draft without leaving an edit behind", () => {
    let state = stateWith();
    state = reduce(state, { type: "set_mode", mode: "draw_box" });
    state = reduce(state, { type: "begin_draft", x: 1, y: 1 });
    state = reduce(state, { type: "move_draft", x: 9, y: 9 });
    state = reduce(state, { type: "cancel_draft" });
    expect(state.draft).toBeNull();
    expect(state.isDirty).toBe(false);
    expect(canUndo(state)).toBe(false);
  });

  it("drops a half-drawn shape when the mode changes", () => {
    let state = stateWith();
    state = reduce(state, { type: "set_mode", mode: "draw_polygon" });
    state = reduce(state, { type: "begin_draft", x: 1, y: 1 });
    state = reduce(state, { type: "set_mode", mode: "select" });
    expect(state.draft).toBeNull();
  });

  it("draws nothing while the pointer is in select mode", () => {
    let state = reduce(stateWith(), { type: "begin_draft", x: 1, y: 1 });
    expect(state.draft).toBeNull();
    state = reduce(state, { type: "add_draft_point", x: 2, y: 2 });
    expect(state.draft).toBeNull();
  });

  it("draws a region that speaks the shape the page already speaks", () => {
    let state = stateWith({
      polygon: BOX,
      reading: { text: "read", confidence: 0.5, model: "paddle-v4" },
    });
    state = reduce(state, { type: "set_mode", mode: "draw_box" });
    state = reduce(state, { type: "begin_draft", x: 200, y: 200 });
    state = reduce(state, { type: "move_draft", x: 300, y: 260 });
    state = reduce(state, { type: "commit_draft" });
    // A recognized artifact refuses a region with no `reading` at all.
    expect(serializeTiffTextRegionsPayload(state).regions).toEqual([
      {
        polygon: BOX,
        reading: { model: "paddle-v4", text: "read", confidence: 0.5 },
      },
      {
        polygon: [
          [200, 200],
          [300, 200],
          [300, 260],
          [200, 260],
        ],
        reading: null,
      },
    ]);
  });

  it("clamps a drawn corner to the page", () => {
    let state = stateWith();
    state = reduce(state, { type: "set_page_size", width: 40, height: 30 });
    state = reduce(state, { type: "set_mode", mode: "draw_box" });
    state = reduce(state, { type: "begin_draft", x: -10, y: -10 });
    state = reduce(state, { type: "move_draft", x: 500, y: 500 });
    state = reduce(state, { type: "commit_draft" });
    expect(polygonAt(state)).toEqual([
      [0, 0],
      [40, 0],
      [40, 30],
      [0, 30],
    ]);
  });
});

describe("deleting a region", () => {
  it("takes the selected region out and clears the selection", () => {
    let state = stateWith(
      { polygon: BOX, text: "a" },
      { polygon: BOX, text: "b" },
    );
    state = reduce(state, { type: "select_region", index: 0 });
    state = reduce(state, { type: "delete_selected_region" });
    expect(state.payload.regions).toHaveLength(1);
    expect(regionAt(state).reading?.text).toBe("b");
    expect(state.selection).toBeNull();
    expect(state.selectedRegions).toEqual([]);
  });

  it("remaps selected indices and keeps the primary vertex when erasing another region", () => {
    let state = stateWith(
      { polygon: BOX, text: "a" },
      { polygon: BOX, text: "b" },
      { polygon: BOX, text: "c" },
    );
    state = reduce(state, { type: "select_region", index: 0 });
    state = reduce(state, { type: "toggle_select_region", index: 2 });
    state = reduce(state, { type: "select_vertex", vertex: 2 });
    state = reduce(state, { type: "set_mode", mode: "eraser" });
    state = reduce(state, { type: "delete_region", index: 1 });
    expect(state.payload.regions.map((region) => region.reading?.text)).toEqual(
      ["a", "c"],
    );
    expect(state.selectedRegions).toEqual([0, 1]);
    expect(state.selection).toEqual({ region: 1, vertex: 2 });
    expect(state.past).toHaveLength(1);

    state = reduce(state, { type: "delete_region", index: 1 });
    expect(state.selectedRegions).toEqual([0]);
    expect(state.selection).toEqual({ region: 0, vertex: null });
    state = reduce(state, { type: "undo" });
    expect(state.selectedRegions).toEqual([0, 1]);
    expect(state.selection).toEqual({ region: 1, vertex: 2 });
    expect(state.mode).toBe("eraser");
    expect(reduce(state, { type: "delete_region", index: 2 })).toBe(state);
  });

  it("deletes all selected regions in one undo step and restores the full selection", () => {
    let state = stateWith(
      { polygon: BOX, text: "a" },
      { polygon: BOX, text: "b" },
      { polygon: BOX, text: "c" },
    );
    state = reduce(state, { type: "select_region", index: 2 });
    state = reduce(state, { type: "toggle_select_region", index: 0 });
    state = reduce(state, { type: "delete_selected_region" });
    expect(state.payload.regions.map((region) => region.reading?.text)).toEqual(
      ["b"],
    );
    expect(state.selectedRegions).toEqual([]);
    expect(state.selection).toBeNull();
    expect(state.past).toHaveLength(1);

    state = reduce(state, { type: "undo" });
    expect(state.selectedRegions).toEqual([0, 2]);
    expect(state.selection).toEqual({ region: 0, vertex: null });
    expect(state.payload.regions.map((region) => region.reading?.text)).toEqual(
      ["a", "b", "c"],
    );
    state = reduce(state, { type: "redo" });
    expect(state.selectedRegions).toEqual([]);
    expect(state.selection).toBeNull();
    expect(state.payload.regions.map((region) => region.reading?.text)).toEqual(
      ["b"],
    );
  });

  it("has nothing to delete when nothing is selected", () => {
    const state = stateWith({ polygon: BOX });
    expect(reduce(state, { type: "delete_selected_region" })).toBe(state);
  });
});

describe("multi-selection", () => {
  it("toggles into sorted order, picks the last remaining index, and clears the last region", () => {
    let state = stateWith({ polygon: BOX }, { polygon: BOX }, { polygon: BOX });
    state = reduce(state, { type: "select_region", index: 2 });
    state = reduce(state, { type: "toggle_select_region", index: 0 });
    state = reduce(state, { type: "toggle_select_region", index: 1 });
    expect(state.selectedRegions).toEqual([0, 1, 2]);
    expect(state.selection).toEqual({ region: 1, vertex: null });
    expect(reduce(state, { type: "toggle_select_region", index: 1.5 })).toBe(
      state,
    );
    expect(reduce(state, { type: "toggle_select_region", index: 3 })).toBe(
      state,
    );

    state = reduce(state, { type: "toggle_select_region", index: 1 });
    expect(state.selectedRegions).toEqual([0, 2]);
    expect(state.selection).toEqual({ region: 2, vertex: null });
    state = reduce(state, { type: "toggle_select_region", index: 2 });
    state = reduce(state, { type: "toggle_select_region", index: 0 });
    expect(state.selectedRegions).toEqual([]);
    expect(state.selection).toBeNull();
    expect(canUndo(state)).toBe(false);
  });

  it("does not start a draft in eraser mode", () => {
    let state = stateWith();
    state = reduce(state, { type: "set_mode", mode: "draw_box" });
    state = reduce(state, { type: "begin_draft", x: 10, y: 20 });
    state = reduce(state, { type: "set_mode", mode: "eraser" });
    expect(state.draft).toBeNull();
    expect(reduce(state, { type: "begin_draft", x: 10, y: 20 })).toBe(state);
    expect(reduce(state, { type: "add_draft_point", x: 10, y: 20 })).toBe(
      state,
    );
  });
});

describe("merging selected regions", () => {
  it("keeps only the convex hull, merges OCR in reading order, and restores selection on undo", () => {
    const bottomLeft = {
      polygon: [
        [0, 60],
        [20, 60],
        [20, 80],
        [0, 80],
      ],
      reading: { text: " Bottom ", confidence: 0.5, model: "ocr" },
    };
    const topRight = {
      polygon: [
        [40, 8],
        [60, 8],
        [60, 28],
        [40, 28],
      ],
      text: " right ",
      score: 1,
    };
    const topLeft = {
      polygon: [
        [0, 10],
        [20, 10],
        [20, 30],
        [0, 30],
      ],
      text: " left ",
    };
    const interior = {
      polygon: [
        [10, 30],
        [20, 30],
        [15, 40],
      ],
      text: "  ",
    };
    const untouched = { polygon: BOX, text: "unselected" };
    let state = stateWith(
      untouched,
      bottomLeft,
      untouched,
      topRight,
      topLeft,
      interior,
    );
    const original = state.payload;
    for (const index of [5, 3, 1, 4]) {
      state = reduce(state, { type: "toggle_select_region", index });
    }
    state = reduce(state, { type: "merge_selected_regions" });
    expect(state.selectedRegions).toEqual([1]);
    expect(state.selection).toEqual({ region: 1, vertex: null });
    expect(serializeTiffTextRegionsPayload(state).regions).toEqual([
      { ...untouched, score: null },
      {
        polygon: [
          [0, 10],
          [40, 8],
          [60, 8],
          [60, 28],
          [20, 80],
          [0, 80],
        ],
        reading: {
          text: "left right Bottom",
          confidence: 0.75,
          model: "manual",
        },
      },
      { ...untouched, score: null },
    ]);
    expect(state.past).toHaveLength(1);
    state = reduce(state, { type: "undo" });
    expect(state.payload).toBe(original);
    expect(state.selectedRegions).toEqual([1, 3, 4, 5]);
    expect(state.selection).toEqual({ region: 4, vertex: null });
    state = reduce(state, { type: "redo" });
    expect(state.selectedRegions).toEqual([1]);
  });

  it("uses the lowest selected region's text wire format and discards collinear points", () => {
    const left = { polygon: BOX, text: "left" };
    const right = {
      polygon: [
        [60, 10],
        [100, 10],
        [100, 40],
        [60, 40],
      ],
      reading: { text: "right" },
    };
    let state = stateWith(left, right);
    state = reduce(state, { type: "select_region", index: 0 });
    state = reduce(state, { type: "toggle_select_region", index: 1 });
    state = reduce(state, { type: "merge_selected_regions" });
    expect(serializeTiffTextRegionsPayload(state).regions).toEqual([
      {
        polygon: [
          [10, 10],
          [100, 10],
          [100, 40],
          [10, 40],
        ],
        text: "left right",
        score: null,
      },
    ]);
  });

  it("leaves a single selection or a degenerate hull alone", () => {
    const polygon = [
      [0, 0],
      [10, 10],
      [20, 20],
    ];
    let state = stateWith({ polygon }, { polygon });
    state = reduce(state, { type: "select_region", index: 0 });
    expect(reduce(state, { type: "merge_selected_regions" })).toBe(state);
    state = reduce(state, { type: "toggle_select_region", index: 1 });
    expect(reduce(state, { type: "merge_selected_regions" })).toBe(state);
  });
});

describe("the region list filter", () => {
  const three = [
    { polygon: BOX, text: "Fort Garry" },
    { polygon: BOX, text: "   " },
    { polygon: BOX },
  ];

  it("shows everything by default", () => {
    expect(visibleRegionIndexes(stateWith(...three))).toEqual([0, 1, 2]);
  });

  it("shows only the regions nobody has read", () => {
    let state = stateWith(...three);
    state = reduce(state, { type: "set_filter", filter: { kind: "unread" } });
    expect(visibleRegionIndexes(state)).toEqual([1, 2]);
  });

  it("matches text case-insensitively", () => {
    let state = stateWith(...three);
    state = reduce(state, {
      type: "set_filter",
      filter: { kind: "query", query: "garry" },
    });
    expect(visibleRegionIndexes(state)).toEqual([0]);
  });

  it("treats a query of spaces as no query at all", () => {
    let state = stateWith(...three);
    state = reduce(state, {
      type: "set_filter",
      filter: { kind: "query", query: "garry" },
    });
    state = reduce(state, {
      type: "set_filter",
      filter: { kind: "query", query: "   " },
    });
    expect(state.filter).toEqual({ kind: "all" });
    expect(visibleRegionIndexes(state)).toEqual([0, 1, 2]);
  });

  it("does not claim a filter change that changed nothing", () => {
    const state = stateWith(...three);
    expect(
      reduce(state, {
        type: "set_filter",
        filter: { kind: "query", query: "  " },
      }),
    ).toBe(state);
  });
});

describe("history and dirtiness", () => {
  /** One editing gesture: the edit, then the pointer or the caret leaving it. */
  function edit(
    state: TiffTextRegionsEditorState,
    action: TiffTextRegionsEditorAction,
  ): TiffTextRegionsEditorState {
    return reduce(reduce(state, action), { type: "end_gesture" });
  }

  it("walks back and forward over the edits of a session", () => {
    let state = stateWith({ polygon: BOX, text: "one" });
    state = edit(state, { type: "set_reading_text", index: 0, text: "two" });
    state = edit(state, { type: "set_reading_text", index: 0, text: "three" });
    expect(state.isDirty).toBe(true);

    state = reduce(state, { type: "undo" });
    expect(regionAt(state).reading?.text).toBe("two");
    expect(canRedo(state)).toBe(true);

    state = reduce(state, { type: "undo" });
    expect(regionAt(state).reading?.text).toBe("one");
    expect(state.isDirty).toBe(false);
    expect(canUndo(state)).toBe(false);

    state = reduce(state, { type: "redo" });
    expect(regionAt(state).reading?.text).toBe("two");
    state = reduce(state, { type: "redo" });
    expect(regionAt(state).reading?.text).toBe("three");
    expect(canRedo(state)).toBe(false);
  });

  it("is clean the moment the artifact's own words come back", () => {
    let state = stateWith({ polygon: BOX, text: "one" });
    state = edit(state, { type: "set_reading_text", index: 0, text: "two" });
    expect(state.isDirty).toBe(true);
    state = edit(state, { type: "set_reading_text", index: 0, text: "one" });
    expect(state.isDirty).toBe(false);
    // Undo is still the way back through the steps that got there.
    expect(canUndo(state)).toBe(true);
  });

  it("folds one drag of one handle into one undo step", () => {
    let state = stateWith({ polygon: BOX });
    state = reduce(state, {
      type: "move_vertex",
      region: 0,
      vertex: 0,
      x: 12,
      y: 12,
    });
    state = reduce(state, {
      type: "move_vertex",
      region: 0,
      vertex: 0,
      x: 15,
      y: 18,
    });
    state = reduce(state, { type: "end_gesture" });
    state = reduce(state, {
      type: "move_vertex",
      region: 0,
      vertex: 0,
      x: 20,
      y: 20,
    });
    expect(state.past).toHaveLength(2);

    state = reduce(state, { type: "undo" });
    expect(polygonAt(state)[0]).toEqual([15, 18]);
    state = reduce(state, { type: "undo" });
    expect(polygonAt(state)[0]).toEqual([10, 10]);
  });

  it("folds a burst of typing into one undo step too", () => {
    let state = stateWith({ polygon: BOX, text: "" });
    for (const text of ["F", "Fo", "For", "Fort"]) {
      state = reduce(state, { type: "set_reading_text", index: 0, text });
    }
    expect(state.past).toHaveLength(1);
    state = reduce(state, { type: "undo" });
    expect(regionAt(state).reading?.text).toBe("");
  });

  it("starts a fresh undo step for a second gesture on the same handle", () => {
    let state = stateWith({ polygon: BOX });
    state = reduce(state, {
      type: "move_vertex",
      region: 0,
      vertex: 0,
      x: 12,
      y: 12,
    });
    state = reduce(state, { type: "end_gesture" });
    state = reduce(state, {
      type: "move_vertex",
      region: 0,
      vertex: 0,
      x: 18,
      y: 18,
    });
    expect(state.past).toHaveLength(2);
  });

  it("forgets the redo stack once a new edit branches off", () => {
    let state = stateWith({ polygon: BOX, text: "one" });
    state = edit(state, { type: "set_reading_text", index: 0, text: "two" });
    state = reduce(state, { type: "undo" });
    expect(canRedo(state)).toBe(true);
    state = edit(state, { type: "set_reading_text", index: 0, text: "branch" });
    expect(canRedo(state)).toBe(false);
  });

  it("keeps undo bounded however long the session runs", () => {
    let state = stateWith({ polygon: BOX });
    for (let step = 0; step < MAX_HISTORY_ENTRIES + 25; step += 1) {
      state = reduce(state, {
        type: "translate_polygon",
        region: 0,
        dx: step % 2 === 0 ? 1 : -1,
        dy: 0,
      });
      state = reduce(state, { type: "end_gesture" });
    }
    expect(state.past).toHaveLength(MAX_HISTORY_ENTRIES);
  });

  it("hands the baseline back on reset and says so in the dirty flag", () => {
    let state = stateWith({ polygon: BOX, text: "one" });
    state = edit(state, { type: "set_reading_text", index: 0, text: "two" });
    state = edit(state, {
      type: "move_vertex",
      region: 0,
      vertex: 0,
      x: 40,
      y: 40,
    });
    state = reduce(state, { type: "reset" });
    expect(serializeTiffTextRegionsPayload(state).regions).toEqual([
      { polygon: BOX, text: "one", score: null },
    ]);
    expect(state.isDirty).toBe(false);
    expect(canUndo(state)).toBe(false);
    expect(state.selection).toBeNull();
  });

  it("does nothing on reset while the artifact is untouched", () => {
    const state = stateWith({ polygon: BOX });
    expect(reduce(state, { type: "reset" })).toBe(state);
  });

  it("leaves a gesture that never moved the shape out of the history", () => {
    const state = stateWith({ polygon: BOX });
    const still = reduce(state, {
      type: "move_vertex",
      region: 0,
      vertex: 0,
      x: 10,
      y: 10,
    });
    expect(still).toBe(state);
  });
});

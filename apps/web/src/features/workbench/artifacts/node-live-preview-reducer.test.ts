import { describe, expect, it } from "vitest";
import {
  nodeLivePreviewInitialState,
  nodeLivePreviewReducer,
  type NodePreviewFrame,
} from "./node-live-preview-reducer";

function makeFrame(
  sequence: number,
  computationId = "comp-1",
): NodePreviewFrame {
  return {
    sequence,
    computation_id: computationId,
    label: `Sheet ${sequence}`,
    detail: "gpt-4.1-mini",
    content_type: "image/png",
    data_url: `data:image/png;base64,FRAME_${sequence}`,
    text: null,
    emitted_at: "2026-01-01T00:00:00Z",
  };
}

describe("nodeLivePreviewReducer", () => {
  it("appends frames, follows latest, and ignores stale stream keys", () => {
    let state = nodeLivePreviewInitialState("stream-a");
    expect(state.status).toBe("connecting");

    state = nodeLivePreviewReducer(state, {
      type: "connected",
      streamKey: "stream-other",
    });
    expect(state.status).toBe("connecting");

    state = nodeLivePreviewReducer(state, {
      type: "frame",
      streamKey: "stream-a",
      frame: makeFrame(1),
    });
    state = nodeLivePreviewReducer(state, {
      type: "frame",
      streamKey: "stream-a",
      frame: makeFrame(2),
    });
    expect(state.status).toBe("live");
    expect(state.frames.map((f) => f.sequence)).toEqual([1, 2]);
    expect(state.selectedIndex).toBe(1);

    // Replayed duplicate after SSE reconnect is ignored.
    state = nodeLivePreviewReducer(state, {
      type: "frame",
      streamKey: "stream-a",
      frame: makeFrame(2),
    });
    expect(state.frames.map((f) => f.sequence)).toEqual([1, 2]);
  });

  it("pauses followLatest when the user picks an earlier frame and resumes on toggle", () => {
    let state = nodeLivePreviewInitialState("stream-a");
    state = nodeLivePreviewReducer(state, {
      type: "frame",
      streamKey: "stream-a",
      frame: makeFrame(1),
    });
    state = nodeLivePreviewReducer(state, {
      type: "frame",
      streamKey: "stream-a",
      frame: makeFrame(2),
    });

    state = nodeLivePreviewReducer(state, { type: "select_frame", index: 0 });
    expect(state.followLatest).toBe(false);
    expect(state.selectedIndex).toBe(0);

    state = nodeLivePreviewReducer(state, {
      type: "frame",
      streamKey: "stream-a",
      frame: makeFrame(3),
    });
    expect(state.selectedIndex).toBe(0);
    expect(state.frames).toHaveLength(3);

    state = nodeLivePreviewReducer(state, { type: "toggle_follow" });
    expect(state.followLatest).toBe(true);
    expect(state.selectedIndex).toBe(2);
  });

  it("resets buffered frames when a new computation_id arrives", () => {
    let state = nodeLivePreviewInitialState("stream-a");
    state = nodeLivePreviewReducer(state, {
      type: "frame",
      streamKey: "stream-a",
      frame: makeFrame(1, "comp-1"),
    });
    state = nodeLivePreviewReducer(state, {
      type: "frame",
      streamKey: "stream-a",
      frame: makeFrame(2, "comp-1"),
    });
    state = nodeLivePreviewReducer(state, {
      type: "frame",
      streamKey: "stream-a",
      frame: makeFrame(1, "comp-2"),
    });

    expect(state.computationId).toBe("comp-2");
    expect(state.frames.map((f) => f.sequence)).toEqual([1]);
    expect(state.selectedIndex).toBe(0);
  });
});

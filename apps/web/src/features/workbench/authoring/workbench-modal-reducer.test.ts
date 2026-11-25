import { describe, expect, it } from "vitest";

import {
  workbenchModalInitialState,
  workbenchModalReducer,
  type WorkbenchModalState,
} from "./workbench-modal-reducer";

const closed: WorkbenchModalState = { phase: "closed" };
const open: WorkbenchModalState = { phase: "open" };
const confirming: WorkbenchModalState = { phase: "confirming_discard" };

describe("workbenchModalInitialState", () => {
  it("starts open or closed from the given flag", () => {
    expect(workbenchModalInitialState(true)).toEqual({ phase: "open" });
    expect(workbenchModalInitialState(false)).toEqual({ phase: "closed" });
  });
});

describe("workbenchModalReducer", () => {
  it("opens and closes with sync_open", () => {
    expect(
      workbenchModalReducer(closed, { type: "sync_open", open: true }),
    ).toEqual(open);
    expect(
      workbenchModalReducer(open, { type: "sync_open", open: false }),
    ).toEqual(closed);
    // Already in the requested phase: no new state.
    expect(workbenchModalReducer(open, { type: "sync_open", open: true })).toBe(
      open,
    );
    expect(
      workbenchModalReducer(closed, { type: "sync_open", open: false }),
    ).toBe(closed);
  });

  it("closes immediately on a clean request_close", () => {
    expect(
      workbenchModalReducer(open, { type: "request_close", dirty: false }),
    ).toEqual(closed);
  });

  it("asks before closing when the editor is dirty", () => {
    expect(
      workbenchModalReducer(open, { type: "request_close", dirty: true }),
    ).toEqual(confirming);
  });

  it("stays put on a repeated close request while confirming", () => {
    expect(
      workbenchModalReducer(confirming, {
        type: "request_close",
        dirty: true,
      }),
    ).toBe(confirming);
    expect(
      workbenchModalReducer(confirming, {
        type: "request_close",
        dirty: false,
      }),
    ).toBe(confirming);
  });

  it("ignores a close request when already closed", () => {
    expect(
      workbenchModalReducer(closed, { type: "request_close", dirty: true }),
    ).toBe(closed);
    expect(
      workbenchModalReducer(closed, { type: "request_close", dirty: false }),
    ).toBe(closed);
  });

  it("returns to open on keep_editing", () => {
    expect(workbenchModalReducer(confirming, { type: "keep_editing" })).toEqual(
      open,
    );
    expect(workbenchModalReducer(open, { type: "keep_editing" })).toBe(open);
  });

  it("closes on confirm_discard", () => {
    expect(
      workbenchModalReducer(confirming, { type: "confirm_discard" }),
    ).toEqual(closed);
    expect(workbenchModalReducer(open, { type: "confirm_discard" })).toEqual(
      closed,
    );
    expect(workbenchModalReducer(closed, { type: "confirm_discard" })).toBe(
      closed,
    );
  });

  it("lets the controlled prop override a pending discard question", () => {
    expect(
      workbenchModalReducer(confirming, { type: "sync_open", open: false }),
    ).toEqual(closed);
    expect(
      workbenchModalReducer(confirming, { type: "sync_open", open: true }),
    ).toEqual(open);
  });

  it("walks the whole dismiss-guard lifecycle", () => {
    let state = workbenchModalInitialState(false);
    state = workbenchModalReducer(state, { type: "sync_open", open: true });
    expect(state).toEqual(open);
    state = workbenchModalReducer(state, {
      type: "request_close",
      dirty: true,
    });
    expect(state).toEqual(confirming);
    state = workbenchModalReducer(state, { type: "keep_editing" });
    expect(state).toEqual(open);
    state = workbenchModalReducer(state, {
      type: "request_close",
      dirty: true,
    });
    expect(state).toEqual(confirming);
    state = workbenchModalReducer(state, { type: "confirm_discard" });
    expect(state).toEqual(closed);
  });
});

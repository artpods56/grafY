import { describe, expect, it } from "vitest";

import {
  credentialsDialogInitialState,
  credentialsDialogReducer,
  hasKeyDraft,
} from "./credentials-dialog-state";

const open = credentialsDialogInitialState(true);

function withDraft(name = "api_key") {
  return credentialsDialogReducer(open, { kind: "draft", name, dirty: true });
}

describe("credentials dialog dismissal guard", () => {
  it("closes when nothing is typed", () => {
    expect(credentialsDialogReducer(open, { kind: "requestClose" })).toEqual(
      credentialsDialogInitialState(false),
    );
  });

  it("refuses to close while a key sits unsubmitted", () => {
    const state = withDraft();
    expect(hasKeyDraft(state)).toBe(true);
    const refused = credentialsDialogReducer(state, { kind: "requestClose" });
    expect(refused.open).toBe(true);
    expect(refused.discardAsked).toBe(true);
  });

  it("asks once, not again, for the same draft", () => {
    const asked = credentialsDialogReducer(withDraft(), {
      kind: "requestClose",
    });
    expect(credentialsDialogReducer(asked, { kind: "requestClose" })).toBe(
      asked,
    );
  });

  it("stops asking when the field is emptied", () => {
    const asked = credentialsDialogReducer(withDraft(), {
      kind: "requestClose",
    });
    const cleared = credentialsDialogReducer(asked, {
      kind: "draft",
      name: "api_key",
      dirty: false,
    });
    expect(cleared.drafts.api_key).toBe(false);
    expect(cleared.discardAsked).toBe(false);
  });

  it("watches every key of a multi-key node", () => {
    let state = withDraft("label_studio_token");
    state = credentialsDialogReducer(state, {
      kind: "draft",
      name: "s3_secret_key",
      dirty: true,
    });
    state = credentialsDialogReducer(state, {
      kind: "draft",
      name: "label_studio_token",
      dirty: false,
    });
    expect(hasKeyDraft(state)).toBe(true);
    expect(state.discardAsked).toBe(false);
  });

  it("keeps the draft when the person says they were still typing", () => {
    const asked = credentialsDialogReducer(withDraft(), {
      kind: "requestClose",
    });
    const kept = credentialsDialogReducer(asked, { kind: "keepEditing" });
    expect(kept).toEqual({ ...asked, discardAsked: false });
    expect(hasKeyDraft(kept)).toBe(true);
  });

  it("closes and forgets the drafts on an explicit discard", () => {
    const asked = credentialsDialogReducer(withDraft(), {
      kind: "requestClose",
    });
    expect(credentialsDialogReducer(asked, { kind: "discard" })).toEqual(
      credentialsDialogInitialState(false),
    );
  });

  it("does nothing when a closed dialog is asked to close", () => {
    const closed = credentialsDialogInitialState(false);
    expect(credentialsDialogReducer(closed, { kind: "requestClose" })).toBe(
      closed,
    );
  });

  it("reports the same state for a draft flag it already holds", () => {
    const typed = withDraft();
    expect(
      credentialsDialogReducer(typed, {
        kind: "draft",
        name: "api_key",
        dirty: true,
      }),
    ).toBe(typed);
  });
});

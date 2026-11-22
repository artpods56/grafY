import { describe, expect, it } from "vitest";

import type { Credential } from "@/lib/api";
import { runEffectReducer } from "@/lib/state/effect-reducer";

import { credentialFormReducer } from "./credential-form-state";
import { credentialListReducer } from "./credential-list-state";

const personal = { scope: "personal" } as const;
const candidate = { provider_kind: "mistral", value: "k", config: {} };

describe("credentialFormReducer", () => {
  it("tests a key, keeps the result across a rename, and drops it on a new key", () => {
    const testing = runEffectReducer(
      credentialFormReducer,
      { kind: "editing" },
      { kind: "test", location: personal, candidate },
    );
    expect(testing.state).toEqual({ kind: "testing" });
    expect(testing.effects).toEqual([
      { kind: "test", location: personal, candidate },
    ]);
    const verification = {
      status: "unreachable" as const,
      message: "No answer.",
      account_hint: null,
    };
    const tested = runEffectReducer(credentialFormReducer, testing.state, {
      kind: "tested",
      verification,
    }).state;
    expect(tested).toEqual({
      kind: "editing",
      check: { kind: "verified", verification },
    });
    const renamed = runEffectReducer(credentialFormReducer, tested, {
      kind: "edit",
      field: "label",
    }).state;
    expect(renamed).toBe(tested);
    expect(
      runEffectReducer(credentialFormReducer, tested, {
        kind: "edit",
        field: "value",
      }).state,
    ).toEqual({ kind: "editing" });
  });

  it("ignores a second request while one is in flight", () => {
    const saving = { kind: "saving" } as const;
    const next = runEffectReducer(credentialFormReducer, saving, {
      kind: "test",
      location: personal,
      candidate,
    });
    expect(next.state).toBe(saving);
    expect(next.effects).toEqual([]);
    expect(
      runEffectReducer(credentialFormReducer, saving, { kind: "close" }).state,
    ).toBe(saving);
  });

  it("holds the saved credential once the save resolves", () => {
    const saved = { id: "c", label: "Key" } as Credential;
    expect(
      runEffectReducer(
        credentialFormReducer,
        { kind: "saving" },
        { kind: "resolve", saved },
      ).state,
    ).toEqual({ kind: "saved", saved });
  });
});

describe("credentialListReducer", () => {
  it("deletes only after a confirm for the same row", () => {
    const asked = runEffectReducer(
      credentialListReducer,
      { kind: "idle" },
      { kind: "ask-delete", id: "a" },
    );
    expect(asked.effects).toEqual([]);
    expect(
      runEffectReducer(credentialListReducer, asked.state, {
        kind: "confirm-delete",
        id: "b",
      }).effects,
    ).toEqual([]);
    const confirmed = runEffectReducer(credentialListReducer, asked.state, {
      kind: "confirm-delete",
      id: "a",
    });
    expect(confirmed.effects).toEqual([{ kind: "delete", id: "a" }]);
    expect(confirmed.state).toEqual({
      kind: "busy",
      id: "a",
      operation: "delete",
    });
  });

  it("reopens a rejected edit with its failure", () => {
    const body = {
      label: null,
      value: "k",
      verify: true,
      save_if_unverified: false,
    };
    const busy = runEffectReducer(
      credentialListReducer,
      { kind: "editing", id: "a" },
      { kind: "submit-edit", id: "a", body },
    );
    expect(busy.effects).toEqual([{ kind: "update", id: "a", body }]);
    expect(
      runEffectReducer(credentialListReducer, busy.state, {
        kind: "failed",
        id: "a",
        message: "Unreachable.",
        canSave: true,
      }).state,
    ).toEqual({
      kind: "editing",
      id: "a",
      failure: { message: "Unreachable.", canSave: true },
    });
  });

  it("says a re-verify's outcome under its row", () => {
    const busy = runEffectReducer(
      credentialListReducer,
      { kind: "idle" },
      { kind: "verify", id: "a" },
    ).state;
    expect(
      runEffectReducer(credentialListReducer, busy, {
        kind: "edit",
        id: "b",
      }).state,
    ).toBe(busy);
    expect(
      runEffectReducer(credentialListReducer, busy, {
        kind: "done",
        id: "a",
        tone: "success",
        message: "Verified.",
      }).state,
    ).toEqual({
      kind: "idle",
      notice: { id: "a", tone: "success", message: "Verified." },
    });
  });
});

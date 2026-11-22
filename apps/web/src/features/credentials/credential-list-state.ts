import type { UpdateCredential } from "@/lib/api";

import type { CredentialTone } from "./credential-display";

/**
 * One saved-credential list: at most one row is being confirmed, edited or
 * waited on at a time, and the last outcome is said under the row it was for.
 */

export interface CredentialRowNotice {
  id: string;
  tone: CredentialTone;
  message: string;
}

export type CredentialRowOperation = "verify" | "delete" | "update";

export type CredentialListState =
  | { kind: "idle"; notice?: CredentialRowNotice }
  | { kind: "confirming-delete"; id: string }
  | {
      kind: "editing";
      id: string;
      failure?: { message: string; canSave: boolean };
    }
  | { kind: "busy"; id: string; operation: CredentialRowOperation };

export type CredentialListAction =
  | { kind: "verify"; id: string }
  | { kind: "ask-delete"; id: string }
  | { kind: "confirm-delete"; id: string }
  | { kind: "edit"; id: string }
  | { kind: "submit-edit"; id: string; body: UpdateCredential }
  | { kind: "cancel" }
  | { kind: "done"; id: string; tone: CredentialTone; message?: string }
  | { kind: "failed"; id: string; message: string; canSave: boolean };

export type CredentialListEffect =
  | { kind: "verify"; id: string }
  | { kind: "delete"; id: string }
  | { kind: "update"; id: string; body: UpdateCredential };

export function credentialListReducer(
  state: CredentialListState,
  action: CredentialListAction,
  exec: (effect: CredentialListEffect) => void,
): CredentialListState {
  if (action.kind === "done" || action.kind === "failed") {
    if (state.kind !== "busy" || state.id !== action.id) return state;
    if (action.kind === "done") {
      return action.message
        ? {
            kind: "idle",
            notice: {
              id: action.id,
              tone: action.tone,
              message: action.message,
            },
          }
        : { kind: "idle" };
    }
    // A rejected edit keeps the form open with what went wrong, so the
    // person can fix it or save the key anyway.
    if (state.operation === "update") {
      return {
        kind: "editing",
        id: action.id,
        failure: { message: action.message, canSave: action.canSave },
      };
    }
    return {
      kind: "idle",
      notice: { id: action.id, tone: "danger", message: action.message },
    };
  }
  if (state.kind === "busy") return state;
  switch (action.kind) {
    case "verify":
      exec({ kind: "verify", id: action.id });
      return { kind: "busy", id: action.id, operation: "verify" };
    case "ask-delete":
      return { kind: "confirming-delete", id: action.id };
    case "confirm-delete":
      if (state.kind !== "confirming-delete" || state.id !== action.id) {
        return state;
      }
      exec({ kind: "delete", id: action.id });
      return { kind: "busy", id: action.id, operation: "delete" };
    case "edit":
      return { kind: "editing", id: action.id };
    case "submit-edit":
      if (state.kind !== "editing" || state.id !== action.id) return state;
      exec({ kind: "update", id: action.id, body: action.body });
      return { kind: "busy", id: action.id, operation: "update" };
    case "cancel":
      return { kind: "idle" };
  }
}

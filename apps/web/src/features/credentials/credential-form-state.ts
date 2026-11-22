import type {
  CreateCredential,
  Credential,
  CredentialLocation,
  CredentialVerification,
} from "@/lib/api";

/** What a "Test key" press found, shown until the form is edited again. */
export type CredentialCheck =
  | { kind: "verified"; verification: CredentialVerification }
  | { kind: "error"; message: string };

export type CredentialFormState =
  | { kind: "closed" }
  | { kind: "editing"; check?: CredentialCheck }
  | { kind: "testing" }
  | { kind: "saving" }
  | { kind: "failed"; message: string; canSave: boolean }
  | { kind: "saved"; saved: Credential };

export interface CredentialCandidate {
  provider_kind: string;
  value: string;
  config: CreateCredential["verify_config"];
}

export type CredentialFormAction =
  | { kind: "open" }
  | { kind: "close" }
  /** A field changed; a key check is stale unless only the label did. */
  | { kind: "edit"; field: string }
  | {
      kind: "test";
      location: CredentialLocation;
      candidate: CredentialCandidate;
    }
  | { kind: "tested"; verification: CredentialVerification }
  | { kind: "test-failed"; message: string }
  | { kind: "submit"; location: CredentialLocation; body: CreateCredential }
  | { kind: "reject"; message: string; canSave: boolean }
  | { kind: "resolve"; saved: Credential };

export type CredentialFormEffect =
  | { kind: "save"; location: CredentialLocation; body: CreateCredential }
  | {
      kind: "test";
      location: CredentialLocation;
      candidate: CredentialCandidate;
    };

/** A request is in flight: nothing but its answer moves the form. */
function busy(state: CredentialFormState): boolean {
  return state.kind === "saving" || state.kind === "testing";
}

/** A check that could not prove the key may still be saved on purpose. */
export function checkAllowsSaveAnyway(check: CredentialCheck | undefined) {
  if (check?.kind !== "verified") return false;
  const status = check.verification.status;
  return status === "unreachable" || status === "unsupported";
}

export function credentialFormReducer(
  state: CredentialFormState,
  action: CredentialFormAction,
  exec: (effect: CredentialFormEffect) => void,
): CredentialFormState {
  switch (action.kind) {
    case "open":
      return busy(state) ? state : { kind: "editing" };
    case "edit":
      if (state.kind === "failed") return { kind: "editing" };
      if (state.kind === "editing" && state.check && action.field !== "label") {
        return { kind: "editing" };
      }
      return state;
    case "close":
      return busy(state) ? state : { kind: "closed" };
    case "test":
      if (state.kind !== "editing" && state.kind !== "failed") return state;
      exec({
        kind: "test",
        location: action.location,
        candidate: action.candidate,
      });
      return { kind: "testing" };
    case "tested":
      return state.kind === "testing"
        ? {
            kind: "editing",
            check: { kind: "verified", verification: action.verification },
          }
        : state;
    case "test-failed":
      return state.kind === "testing"
        ? { kind: "editing", check: { kind: "error", message: action.message } }
        : state;
    case "submit":
      if (state.kind !== "editing" && state.kind !== "failed") return state;
      exec({ kind: "save", location: action.location, body: action.body });
      return { kind: "saving" };
    case "reject":
      return state.kind === "saving"
        ? { kind: "failed", message: action.message, canSave: action.canSave }
        : state;
    case "resolve":
      return state.kind === "saving"
        ? { kind: "saved", saved: action.saved }
        : state;
  }
}

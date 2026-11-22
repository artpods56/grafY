import type { CreateCredential, CredentialLocation } from "@/lib/api";

export type CredentialFormState =
  | { kind: "closed" }
  | { kind: "editing" }
  | { kind: "saving" }
  | { kind: "failed"; message: string; canSave: boolean }
  | { kind: "saved"; message: string };

export type CredentialFormAction =
  | { kind: "open" }
  | { kind: "close" }
  | { kind: "edit" }
  | { kind: "submit"; location: CredentialLocation; body: CreateCredential }
  | { kind: "reject"; message: string; canSave: boolean }
  | { kind: "resolve"; message: string };

export type CredentialFormEffect = {
  kind: "save";
  location: CredentialLocation;
  body: CreateCredential;
};

export function credentialFormReducer(
  state: CredentialFormState,
  action: CredentialFormAction,
  exec: (effect: CredentialFormEffect) => void,
): CredentialFormState {
  switch (action.kind) {
    case "open":
    case "edit":
      return state.kind === "saving" ? state : { kind: "editing" };
    case "close":
      return state.kind === "saving" ? state : { kind: "closed" };
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
        ? { kind: "saved", message: action.message }
        : state;
  }
}

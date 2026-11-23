/**
 * The credentials dialog's dismissal guard.
 *
 * A pasted key cannot be read back, so closing the dialog while one sits
 * unsubmitted in a field has to be a decision the person made — not something
 * an Escape tap or a stray backdrop click did on their behalf. The dialog owns
 * this state; the component only translates clicks into actions.
 */

export interface CredentialsDialogState {
  open: boolean;
  /** Secret inputs holding typed text the server has never seen. */
  readonly drafts: Readonly<Record<string, boolean>>;
  /** A close was refused: ask what to do with the key on screen. */
  readonly discardAsked: boolean;
}

export type CredentialsDialogAction =
  | { kind: "open" }
  | { kind: "requestClose" }
  | { kind: "draft"; name: string; dirty: boolean }
  | { kind: "discard" }
  | { kind: "keepEditing" };

export function credentialsDialogInitialState(
  open = false,
): CredentialsDialogState {
  return { open, drafts: {}, discardAsked: false };
}

export function hasKeyDraft(state: CredentialsDialogState): boolean {
  return Object.values(state.drafts).some((dirty) => dirty);
}

export function credentialsDialogReducer(
  state: CredentialsDialogState,
  action: CredentialsDialogAction,
): CredentialsDialogState {
  switch (action.kind) {
    case "open":
      if (state.open && !state.discardAsked) return state;
      return { ...state, open: true, discardAsked: false };
    case "requestClose":
      if (!state.open) return state;
      if (hasKeyDraft(state)) {
        return state.discardAsked ? state : { ...state, discardAsked: true };
      }
      return { open: false, drafts: state.drafts, discardAsked: false };
    case "draft": {
      const dirty = state.drafts[action.name] === true;
      if (dirty === action.dirty) return state;
      const drafts = { ...state.drafts, [action.name]: action.dirty };
      if (!action.dirty && !hasKeyDraft({ ...state, drafts })) {
        return { ...state, drafts, discardAsked: false };
      }
      return { ...state, drafts };
    }
    case "discard":
      return { open: false, drafts: {}, discardAsked: false };
    case "keepEditing":
      return state.discardAsked ? { ...state, discardAsked: false } : state;
  }
}

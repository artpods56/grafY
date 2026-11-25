/**
 * The shared dismiss-guard lifecycle of a `WorkbenchModal`.
 *
 * A modal that hosts an editor (a long prompt, a fullscreen TIFF, a future
 * artifact editor) cannot close silently while it holds unsaved edits: an
 * Escape tap or a stray backdrop click must not throw the work away. The
 * component owns this state; it only translates UI events into actions, so
 * the whole lifecycle is unit-testable without a renderer.
 *
 * The phases are mutually exclusive on purpose: "is the confirm banner up"
 * is a phase, not a boolean flag that can disagree with "is the modal open".
 */

export type WorkbenchModalState =
  | { readonly phase: "closed" }
  | { readonly phase: "open" }
  | { readonly phase: "confirming_discard" };

export type WorkbenchModalAction =
  | { readonly type: "sync_open"; readonly open: boolean }
  | { readonly type: "request_close"; readonly dirty: boolean }
  | { readonly type: "keep_editing" }
  | { readonly type: "confirm_discard" };

export function workbenchModalInitialState(open: boolean): WorkbenchModalState {
  return { phase: open ? "open" : "closed" };
}

export function workbenchModalReducer(
  state: WorkbenchModalState,
  action: WorkbenchModalAction,
): WorkbenchModalState {
  switch (action.type) {
    case "sync_open":
      // The controlled `open` prop wins from the outside, even over a
      // pending discard question.
      if (action.open && state.phase === "open") return state;
      if (!action.open && state.phase === "closed") return state;
      return { phase: action.open ? "open" : "closed" };
    case "request_close":
      if (state.phase !== "open") return state;
      return action.dirty
        ? { phase: "confirming_discard" }
        : { phase: "closed" };
    case "keep_editing":
      if (state.phase !== "confirming_discard") return state;
      return { phase: "open" };
    case "confirm_discard":
      if (state.phase === "closed") return state;
      return { phase: "closed" };
  }
}

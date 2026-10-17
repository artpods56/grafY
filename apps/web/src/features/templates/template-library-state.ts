/**
 * Decisions for the Templates library screen: which result is on screen, what the
 * "Use template" form holds, and whether a create or archive request is in flight.
 *
 * The form fields, the dialog visibility, and the busy/error flags could disagree
 * with each other and with the template the preview shows, because nothing owned
 * the relationship between them. Every rule for moving between those shapes lives
 * here as a pure function; requests stay in the component.
 */

/** `${locationId}:${templateId}` — see `templateKey` in `TemplateLibrary.tsx`. */
export type TemplateIdentityKey = string;

/**
 * One opened copy form. It names the template it was opened for so the create
 * request can never be addressed from a different template than the one the
 * person typed the name next to.
 */
export interface UseTemplateForm {
  templateKey: TemplateIdentityKey;
  /** Location that owns the template. The copy request is addressed here. */
  sourceLocationId: string;
  templateId: string;
  graphName: string;
  destinationId: string;
  folderId: string;
}

export type UseTemplateDialog =
  | { phase: "closed" }
  | { phase: "editing"; form: UseTemplateForm }
  /** A copy request started from this form is in flight. Fields stay editable. */
  | { phase: "creating"; form: UseTemplateForm }
  | { phase: "failed"; form: UseTemplateForm; error: string };

export type ArchiveTemplateState =
  | { phase: "idle" }
  | { phase: "archiving"; templateKey: TemplateIdentityKey }
  | { phase: "failed"; templateKey: TemplateIdentityKey; error: string };

export interface TemplateLibraryState {
  query: string;
  /** Result the person chose. `null` lets the first match stand in. */
  selectedKey: string | null;
  use: UseTemplateDialog;
  /**
   * Templates with a copy request that has not answered, listed in the order the
   * requests started. A request outlives the form it started in — the person can
   * go and come back while it runs — so "is this template busy?" is answered here
   * rather than by the dialog's phase. Otherwise a reopened form reads as idle and
   * offers a copy that cannot start.
   */
  pendingCopy: readonly TemplateIdentityKey[];
  archive: ArchiveTemplateState;
}

export type TemplateLibraryEvent =
  /** The result set changed, so an open form no longer describes what is on screen. */
  | { type: "queryChanged"; query: string }
  /** Arrow-key inspection. A form survives only if it belongs to the new result. */
  | { type: "selectionMoved"; templateKey: TemplateIdentityKey }
  /** A result row was clicked, which drops any open form. */
  | { type: "resultChosen"; templateKey: TemplateIdentityKey }
  | { type: "useOpened"; form: UseTemplateForm }
  | { type: "useDismissed" }
  | { type: "graphNameChanged"; value: string }
  | { type: "destinationChanged"; destinationId: string }
  | { type: "folderChanged"; folderId: string }
  | { type: "createRequested"; templateKey: TemplateIdentityKey }
  | { type: "createSucceeded"; templateKey: TemplateIdentityKey }
  | { type: "createFailed"; templateKey: TemplateIdentityKey; error: string }
  | { type: "archiveRequested"; templateKey: TemplateIdentityKey }
  | { type: "archiveSucceeded"; templateKey: TemplateIdentityKey }
  | { type: "archiveFailed"; templateKey: TemplateIdentityKey; error: string };

export const initialTemplateLibraryState: TemplateLibraryState = {
  query: "",
  selectedKey: null,
  use: { phase: "closed" },
  pendingCopy: [],
  archive: { phase: "idle" },
};

/** The form an open dialog holds, or `null` when nothing is being copied. */
export function openUseForm(use: UseTemplateDialog): UseTemplateForm | null {
  return use.phase === "closed" ? null : use.form;
}

/**
 * The form a copy request may start from, or `null` when none may.
 *
 * Returning the form keeps the request addressed by the same value this decision
 * approved, instead of letting the caller read a field off a dialog it only
 * checked as a whole.
 */
export function canRequestCopy(
  state: TemplateLibraryState,
): UseTemplateForm | null {
  const use = state.use;
  if (use.phase !== "editing" && use.phase !== "failed") return null;
  // One request per template: the template may be waiting on a request started
  // from a form the person already left.
  if (state.pendingCopy.includes(use.form.templateKey)) return null;
  if (use.form.destinationId === "" || use.form.graphName.trim() === "") {
    return null;
  }
  return use.form;
}

/** Drop a settled template from the busy list. Settling twice changes nothing. */
function settleCopy(
  state: TemplateLibraryState,
  key: TemplateIdentityKey,
): TemplateLibraryState {
  return state.pendingCopy.includes(key)
    ? { ...state, pendingCopy: state.pendingCopy.filter((p) => p !== key) }
    : state;
}

function withOpenForm(
  state: TemplateLibraryState,
  update: (form: UseTemplateForm) => UseTemplateForm,
): TemplateLibraryState {
  const use = state.use;
  if (use.phase === "closed") return state;
  return { ...state, use: { ...use, form: update(use.form) } };
}

export function templateLibraryReducer(
  state: TemplateLibraryState,
  event: TemplateLibraryEvent,
): TemplateLibraryState {
  switch (event.type) {
    case "queryChanged": {
      if (state.query === event.query) return state;
      return { ...state, query: event.query, use: { phase: "closed" } };
    }

    case "selectionMoved": {
      const held = openUseForm(state.use);
      const keepsForm = held !== null && held.templateKey === event.templateKey;
      return {
        ...state,
        selectedKey: event.templateKey,
        use: keepsForm ? state.use : { phase: "closed" },
      };
    }

    case "resultChosen":
      return {
        ...state,
        selectedKey: event.templateKey,
        use: { phase: "closed" },
      };

    // The form that started a request keeps it until it answers, so it is not
    // replaced. A form for another template opens beside the running copy.
    case "useOpened": {
      const held = openUseForm(state.use);
      return held !== null && state.pendingCopy.includes(held.templateKey)
        ? state
        : { ...state, use: { phase: "editing", form: event.form } };
    }

    case "useDismissed":
      return state.use.phase === "closed"
        ? state
        : { ...state, use: { phase: "closed" } };

    case "graphNameChanged":
      return withOpenForm(state, (form) => ({
        ...form,
        graphName: event.value,
      }));

    // A copy in a new folder of the previous save location would be a silent
    // move, so the folder choice belongs to the location it was picked under.
    case "destinationChanged":
      return withOpenForm(state, (form) => ({
        ...form,
        destinationId: event.destinationId,
        folderId: "",
      }));

    case "folderChanged":
      return withOpenForm(state, (form) => ({
        ...form,
        folderId: event.folderId,
      }));

    // Only a form waiting for its first or next attempt can start a copy, and
    // only for the template it belongs to.
    case "createRequested": {
      const form = canRequestCopy(state);
      if (form === null || form.templateKey !== event.templateKey) return state;
      return {
        ...state,
        pendingCopy: [...state.pendingCopy, event.templateKey],
        use: { phase: "creating", form },
      };
    }

    // A completion answers the request that started it, so it lands only on the
    // dialog still holding that template's form. A copy the person already left,
    // or a late answer for another template, cannot rewrite what is on screen.
    case "createSucceeded": {
      const settled = settleCopy(state, event.templateKey);
      const use = state.use;
      return use.phase === "creating" &&
        use.form.templateKey === event.templateKey
        ? { ...settled, use: { phase: "editing", form: use.form } }
        : settled;
    }

    case "createFailed": {
      const settled = settleCopy(state, event.templateKey);
      const use = state.use;
      return use.phase === "creating" &&
        use.form.templateKey === event.templateKey
        ? {
            ...settled,
            use: { phase: "failed", form: use.form, error: event.error },
          }
        : settled;
    }

    // One archive runs at a time. The slot names the template its outcome belongs
    // to, so an answer cannot be shown against another preview.
    case "archiveRequested": {
      if (state.archive.phase === "archiving") return state;
      return {
        ...state,
        archive: { phase: "archiving", templateKey: event.templateKey },
      };
    }

    // Archiving closes the copy form of that same template and nothing else.
    case "archiveSucceeded": {
      const archive = state.archive;
      if (
        archive.phase !== "archiving" ||
        archive.templateKey !== event.templateKey
      ) {
        return state;
      }
      const held = openUseForm(state.use);
      return {
        ...state,
        archive: { phase: "idle" },
        use:
          held !== null && held.templateKey === event.templateKey
            ? { phase: "closed" }
            : state.use,
      };
    }

    case "archiveFailed": {
      const archive = state.archive;
      if (
        archive.phase !== "archiving" ||
        archive.templateKey !== event.templateKey
      ) {
        return state;
      }
      return {
        ...state,
        archive: {
          phase: "failed",
          templateKey: event.templateKey,
          error: event.error,
        },
      };
    }

    default: {
      const unhandled: never = event;
      throw new Error(
        `Unhandled templates event: ${JSON.stringify(unhandled)}`,
      );
    }
  }
}

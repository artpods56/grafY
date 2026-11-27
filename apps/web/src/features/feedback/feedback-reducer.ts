import type {
  FeedbackClient,
  FeedbackElement,
  FeedbackKind,
  FeedbackReportSubmission,
} from "@/lib/api/contract";

/** What a person picked on screen, described by the adapter. */
export interface PickedTarget {
  readonly element: FeedbackElement;
  /** A short name a person reads, such as `Button “Run”`. */
  readonly name: string;
}

export type ScreenshotState =
  | { readonly status: "none" }
  | {
      readonly status: "ready";
      readonly blob: Blob;
      /** An object URL for the preview; released when the report is done with it. */
      readonly url: string;
      /** A canvas overlaps the shot, and WebGL canvases come out blank. */
      readonly mayMissCanvas: boolean;
    }
  | { readonly status: "failed" };

export interface FeedbackDraft {
  readonly kind: FeedbackKind;
  readonly message: string;
  readonly includeScreenshot: boolean;
}

/** Where the report was started: fixed when the picker opens. */
export interface FeedbackContext {
  readonly workspaceId: string | null;
  readonly pagePath: string;
}

export type FeedbackState =
  | { readonly phase: "idle" }
  | {
      readonly phase: "picking";
      readonly context: FeedbackContext;
      readonly draft: FeedbackDraft;
    }
  | {
      readonly phase: "capturing";
      readonly context: FeedbackContext;
      readonly draft: FeedbackDraft;
      readonly target: PickedTarget;
    }
  | {
      readonly phase: "composing";
      readonly context: FeedbackContext;
      readonly draft: FeedbackDraft;
      readonly target: PickedTarget | null;
      readonly screenshot: ScreenshotState;
      readonly error: string | null;
    }
  | {
      readonly phase: "sending";
      readonly context: FeedbackContext;
      readonly draft: FeedbackDraft;
      readonly target: PickedTarget | null;
      readonly screenshot: ScreenshotState;
    }
  | { readonly phase: "sent" };

export type FeedbackAction =
  | { readonly type: "start"; readonly context: FeedbackContext }
  | { readonly type: "pick"; readonly target: PickedTarget }
  | { readonly type: "skipPick" }
  | {
      readonly type: "captured";
      readonly blob: Blob;
      readonly url: string;
      readonly mayMissCanvas: boolean;
    }
  | { readonly type: "captureFailed" }
  | { readonly type: "repick" }
  | { readonly type: "editDraft"; readonly draft: Partial<FeedbackDraft> }
  | { readonly type: "submit"; readonly client: FeedbackClient }
  | { readonly type: "sent" }
  | { readonly type: "sendFailed"; readonly message: string }
  | { readonly type: "cancel" }
  | { readonly type: "dismiss" };

export type FeedbackEffect =
  | { readonly type: "capture"; readonly target: PickedTarget }
  | {
      readonly type: "send";
      readonly submission: FeedbackReportSubmission;
      readonly screenshot: Blob | null;
    }
  | { readonly type: "releaseScreenshot"; readonly url: string }
  | { readonly type: "scheduleDismiss" };

export const IDLE_FEEDBACK: FeedbackState = { phase: "idle" };

const EMPTY_DRAFT: FeedbackDraft = {
  kind: "bug",
  message: "",
  includeScreenshot: true,
};

function release(
  screenshot: ScreenshotState,
  exec: (effect: FeedbackEffect) => void,
): void {
  if (screenshot.status === "ready") {
    exec({ type: "releaseScreenshot", url: screenshot.url });
  }
}

function composing(
  context: FeedbackContext,
  draft: FeedbackDraft,
  target: PickedTarget | null,
  screenshot: ScreenshotState,
  error: string | null = null,
): FeedbackState {
  return { phase: "composing", context, draft, target, screenshot, error };
}

/**
 * Pick an element, photograph it, write the report, send it. The picker and the
 * dialog never show at once, so a screenshot never contains the dialog.
 */
export function feedbackReducer(
  state: FeedbackState,
  action: FeedbackAction,
  exec: (effect: FeedbackEffect) => void,
): FeedbackState {
  switch (action.type) {
    case "start":
      if (state.phase !== "idle" && state.phase !== "sent") return state;
      return { phase: "picking", context: action.context, draft: EMPTY_DRAFT };
    case "pick":
      if (state.phase !== "picking") return state;
      exec({ type: "capture", target: action.target });
      return {
        phase: "capturing",
        context: state.context,
        draft: state.draft,
        target: action.target,
      };
    case "skipPick":
      if (state.phase !== "picking") return state;
      return composing(state.context, state.draft, null, { status: "none" });
    case "captured":
      if (state.phase !== "capturing") {
        // A shot that lands after a cancel belongs to nobody.
        exec({ type: "releaseScreenshot", url: action.url });
        return state;
      }
      return composing(state.context, state.draft, state.target, {
        status: "ready",
        blob: action.blob,
        url: action.url,
        mayMissCanvas: action.mayMissCanvas,
      });
    case "captureFailed":
      if (state.phase !== "capturing") return state;
      return composing(state.context, state.draft, state.target, {
        status: "failed",
      });
    case "repick":
      if (state.phase !== "composing") return state;
      release(state.screenshot, exec);
      return { phase: "picking", context: state.context, draft: state.draft };
    case "editDraft":
      if (state.phase !== "composing") return state;
      return {
        ...state,
        draft: { ...state.draft, ...action.draft },
        error: null,
      };
    case "submit": {
      if (state.phase !== "composing") return state;
      const message = state.draft.message.trim();
      if (message === "") return state;
      const screenshot =
        state.screenshot.status === "ready" && state.draft.includeScreenshot
          ? state.screenshot.blob
          : null;
      exec({
        type: "send",
        submission: {
          kind: state.draft.kind,
          message,
          page_path: state.context.pagePath,
          workspace_id: state.context.workspaceId,
          element: state.target?.element ?? null,
          client: action.client,
        },
        screenshot,
      });
      return {
        phase: "sending",
        context: state.context,
        draft: state.draft,
        target: state.target,
        screenshot: state.screenshot,
      };
    }
    case "sent":
      if (state.phase !== "sending") return state;
      release(state.screenshot, exec);
      exec({ type: "scheduleDismiss" });
      return { phase: "sent" };
    case "sendFailed":
      if (state.phase !== "sending") return state;
      return composing(
        state.context,
        state.draft,
        state.target,
        state.screenshot,
        action.message,
      );
    case "cancel":
      if (
        state.phase === "idle" ||
        state.phase === "sending" ||
        state.phase === "sent"
      ) {
        return state;
      }
      if (state.phase === "composing") release(state.screenshot, exec);
      return IDLE_FEEDBACK;
    case "dismiss":
      if (state.phase !== "sent") return state;
      return IDLE_FEEDBACK;
  }
}

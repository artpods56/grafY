"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { usePathname } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import type { FeedbackClient } from "@/lib/api/contract";
import { submitFeedback } from "@/lib/api/feedback";
import { useEffectReducer } from "@/lib/state/use-effect-reducer";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { captureElementScreenshot } from "./capture-screenshot";
import { FEEDBACK_UI_ATTRIBUTE } from "./element-description";
import {
  feedbackReducer,
  IDLE_FEEDBACK,
  type FeedbackAction,
  type FeedbackEffect,
} from "./feedback-reducer";
import { FeedbackDialog } from "./FeedbackDialog";
import { FeedbackPicker } from "./FeedbackPicker";

export interface FeedbackController {
  /** Open the picker. `workspaceId` names the Workspace the page belongs to, if any. */
  start: (options: { workspaceId: string | null }) => void;
}

const FeedbackControllerContext =
  React.createContext<FeedbackController | null>(null);

/** Null outside the provider, so a surface without it just hides its entry point. */
export function useFeedback(): FeedbackController | null {
  return React.useContext(FeedbackControllerContext);
}

const SENT_NOTICE_MS = 4000;

const s = stylex.create({
  sent: {
    position: "fixed",
    left: "50%",
    bottom: "max(16px, env(safe-area-inset-bottom))",
    transform: "translateX(-50%)",
    zIndex: 2147483000,
    paddingBlock: tokens.space2,
    paddingInline: tokens.space3,
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorAccent,
    color: tokens.colorOnAccent,
    boxShadow: tokens.shadowNodeRaised,
    fontSize: tokens.fontSizeSm,
  },
});

function sendFailureMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 429) {
    return "You have sent a lot of feedback in the last hour. Try again later.";
  }
  if (error instanceof ApiError && error.status === 413) {
    return "The screenshot is too large. Untick “Include screenshot” and send again.";
  }
  return "Your feedback could not be sent. Check your connection and try again.";
}

function currentClient(): FeedbackClient {
  const applied = document.documentElement.style.colorScheme;
  const dark =
    applied === "dark" ||
    (applied !== "light" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  return {
    viewport_width: Math.max(1, Math.round(window.innerWidth)),
    viewport_height: Math.max(1, Math.round(window.innerHeight)),
    device_pixel_ratio: Math.min(16, window.devicePixelRatio || 1),
    user_agent: navigator.userAgent.slice(0, 512),
    color_scheme: dark ? "dark" : "light",
  };
}

function runFeedbackEffect(
  effect: FeedbackEffect,
  dispatch: React.Dispatch<FeedbackAction>,
): void {
  switch (effect.type) {
    case "capture":
      void captureElementScreenshot(effect.target.element).then(
        ({ blob, mayMissCanvas }) =>
          dispatch({
            type: "captured",
            blob,
            url: URL.createObjectURL(blob),
            mayMissCanvas,
          }),
        (error: unknown) => {
          console.warn("Feedback screenshot failed.", error);
          dispatch({ type: "captureFailed" });
        },
      );
      return;
    case "send":
      void submitFeedback(effect.submission, effect.screenshot).then(
        () => dispatch({ type: "sent" }),
        (error: unknown) =>
          dispatch({ type: "sendFailed", message: sendFailureMessage(error) }),
      );
      return;
    case "releaseScreenshot":
      URL.revokeObjectURL(effect.url);
      return;
    case "scheduleDismiss":
      window.setTimeout(() => dispatch({ type: "dismiss" }), SENT_NOTICE_MS);
      return;
  }
}

/** Mounted once for the whole app; any surface opens the picker through `useFeedback`. */
export function FeedbackProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const [state, dispatch] = useEffectReducer(
    feedbackReducer,
    IDLE_FEEDBACK,
    runFeedbackEffect,
  );
  const controller = React.useMemo<FeedbackController>(
    () => ({
      start: ({ workspaceId }) =>
        dispatch({
          type: "start",
          context: { workspaceId, pagePath: pathname },
        }),
    }),
    [dispatch, pathname],
  );
  const cancel = React.useCallback(
    () => dispatch({ type: "cancel" }),
    [dispatch],
  );

  return (
    <FeedbackControllerContext.Provider value={controller}>
      {children}
      {state.phase === "picking" || state.phase === "capturing" ? (
        <FeedbackPicker
          capturing={state.phase === "capturing" ? state.target : null}
          onPick={(target) => dispatch({ type: "pick", target })}
          onSkip={() => dispatch({ type: "skipPick" })}
          onCancel={cancel}
        />
      ) : null}
      <FeedbackDialog
        state={
          state.phase === "composing" || state.phase === "sending"
            ? state
            : null
        }
        onEdit={(draft) => dispatch({ type: "editDraft", draft })}
        onRepick={() => dispatch({ type: "repick" })}
        onSubmit={() => dispatch({ type: "submit", client: currentClient() })}
        onCancel={cancel}
      />
      {state.phase === "sent" ? (
        <div
          {...{ [FEEDBACK_UI_ATTRIBUTE]: "" }}
          role="status"
          {...stylex.props(s.sent)}
        >
          Thanks — your feedback was sent.
        </div>
      ) : null}
    </FeedbackControllerContext.Provider>
  );
}

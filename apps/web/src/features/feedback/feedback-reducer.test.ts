import { describe, expect, it } from "vitest";

import { runEffectSequence } from "@/lib/state/effect-reducer";

import {
  feedbackReducer,
  IDLE_FEEDBACK,
  type FeedbackAction,
  type PickedTarget,
} from "./feedback-reducer";

const context = {
  workspaceId: "ws-1",
  pagePath: "/workspaces/lab/projects/p1",
};
const target: PickedTarget = {
  name: "Button “Run”",
  element: {
    tag: "button",
    selector: "main > button",
    label: "Run",
    role: "button",
    test_id: null,
    canvas_item_id: "card-1",
    text: "Run",
    rect: { x: 10, y: 20, width: 80, height: 32 },
  },
};
const client = {
  viewport_width: 1280,
  viewport_height: 800,
  device_pixel_ratio: 2,
  user_agent: "vitest",
  color_scheme: "dark" as const,
};
const blob = new Blob(["png"], { type: "image/png" });

function run(actions: readonly FeedbackAction[]) {
  return runEffectSequence(feedbackReducer, IDLE_FEEDBACK, actions);
}

describe("feedbackReducer", () => {
  it("photographs the picked element before the dialog opens", () => {
    const { state, effects } = run([
      { type: "start", context },
      { type: "pick", target },
    ]);
    expect(state.phase).toBe("capturing");
    expect(effects).toEqual([{ type: "capture", target }]);

    const ready = run([
      { type: "start", context },
      { type: "pick", target },
      { type: "captured", blob, url: "blob:1", mayMissCanvas: false },
    ]).state;
    expect(ready).toMatchObject({
      phase: "composing",
      target,
      screenshot: { status: "ready", url: "blob:1" },
    });
  });

  it("sends the trimmed message with the screenshot only when it is included", () => {
    const base: FeedbackAction[] = [
      { type: "start", context },
      { type: "pick", target },
      { type: "captured", blob, url: "blob:1", mayMissCanvas: false },
      { type: "editDraft", draft: { message: "  It froze  " } },
    ];
    const withShot = run([...base, { type: "submit", client }]);
    expect(withShot.state.phase).toBe("sending");
    expect(withShot.effects.at(-1)).toEqual({
      type: "send",
      submission: {
        kind: "bug",
        message: "It froze",
        page_path: context.pagePath,
        workspace_id: "ws-1",
        element: target.element,
        client,
      },
      screenshot: blob,
    });

    const withoutShot = run([
      ...base,
      { type: "editDraft", draft: { includeScreenshot: false } },
      { type: "submit", client },
    ]);
    expect(withoutShot.effects.at(-1)).toMatchObject({ screenshot: null });
  });

  it("refuses an empty message", () => {
    const { state, effects } = run([
      { type: "start", context },
      { type: "skipPick" },
      { type: "editDraft", draft: { message: "   " } },
      { type: "submit", client },
    ]);
    expect(state.phase).toBe("composing");
    expect(effects).toEqual([]);
  });

  it("keeps the draft and shows the error when sending fails", () => {
    const { state } = run([
      { type: "start", context },
      { type: "skipPick" },
      { type: "editDraft", draft: { message: "Idea", kind: "idea" } },
      { type: "submit", client },
      { type: "sendFailed", message: "Offline" },
    ]);
    expect(state).toMatchObject({
      phase: "composing",
      error: "Offline",
      draft: { message: "Idea", kind: "idea" },
    });
  });

  it("releases the preview and schedules the thank-you when sent", () => {
    const { state, effects } = run([
      { type: "start", context },
      { type: "pick", target },
      { type: "captured", blob, url: "blob:1", mayMissCanvas: true },
      { type: "editDraft", draft: { message: "x" } },
      { type: "submit", client },
      { type: "sent" },
    ]);
    expect(state.phase).toBe("sent");
    expect(effects.slice(-2)).toEqual([
      { type: "releaseScreenshot", url: "blob:1" },
      { type: "scheduleDismiss" },
    ]);
    expect(
      run([{ type: "start", context }, { type: "dismiss" }]).state.phase,
    ).toBe("picking");
  });

  it("releases a screenshot that lands after a cancel", () => {
    const { state, effects } = run([
      { type: "start", context },
      { type: "pick", target },
      { type: "cancel" },
      { type: "captured", blob, url: "blob:late", mayMissCanvas: false },
    ]);
    expect(state).toBe(IDLE_FEEDBACK);
    expect(effects.at(-1)).toEqual({
      type: "releaseScreenshot",
      url: "blob:late",
    });
  });

  it("picks again without losing what was written", () => {
    const { state, effects } = run([
      { type: "start", context },
      { type: "pick", target },
      { type: "captured", blob, url: "blob:1", mayMissCanvas: false },
      { type: "editDraft", draft: { message: "Half written" } },
      { type: "repick" },
    ]);
    expect(state).toMatchObject({
      phase: "picking",
      draft: { message: "Half written" },
    });
    expect(effects.at(-1)).toEqual({
      type: "releaseScreenshot",
      url: "blob:1",
    });
  });

  it("ignores cancel while sending", () => {
    const sending = run([
      { type: "start", context },
      { type: "skipPick" },
      { type: "editDraft", draft: { message: "x" } },
      { type: "submit", client },
      { type: "cancel" },
    ]);
    expect(sending.state.phase).toBe("sending");
  });
});

// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

import {
  WorkbenchActivityBar,
  type WorkbenchActivity,
} from "./WorkbenchActivityBar";

async function renderActivity(activity: WorkbenchActivity) {
  const container = document.createElement("div");
  const root = createRoot(container);
  await act(async () => {
    root.render(<WorkbenchActivityBar activity={activity} />);
  });
  return { container, root };
}

describe("WorkbenchActivityBar", () => {
  it("renders a global viewer result without an execution action", async () => {
    const { container, root } = await renderActivity({
      eyebrow: "Linked view",
      title: "Linked feature located",
      message: "Located 1 matching map feature.",
      tone: "success",
    });

    expect(container.querySelector("aside")?.getAttribute("aria-label")).toBe(
      "Linked view: Linked feature located",
    );
    expect(container.textContent).toContain("Located 1 matching map feature.");
    expect(container.querySelector("button")).toBeNull();
    await act(async () => root.unmount());
  });

  it("invokes the action supplied by the active operation", async () => {
    const onRetry = vi.fn();
    const { container, root } = await renderActivity({
      eyebrow: "Linked view",
      title: "Linked selection lookup failed",
      message: "The map query timed out.",
      tone: "error",
      action: {
        kind: "retry",
        label: "Retry",
        ariaLabel: "Retry linked selection lookup",
        onInvoke: onRetry,
      },
    });
    const button = container.querySelector("button");

    expect(button?.getAttribute("aria-label")).toBe(
      "Retry linked selection lookup",
    );
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onRetry).toHaveBeenCalledOnce();
    await act(async () => root.unmount());
  });
});

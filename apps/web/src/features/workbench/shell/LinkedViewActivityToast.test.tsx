// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

import { LinkedViewActivityToast } from "./LinkedViewActivityToast";
import type { ArtifactViewerActivity } from "../artifacts/artifact-interactions";

async function renderToast(
  activity: ArtifactViewerActivity | null,
  actions: { onRetry?: () => void; onDismiss?: () => void } = {},
) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <LinkedViewActivityToast
        activity={activity}
        onRetry={actions.onRetry}
        onDismiss={actions.onDismiss}
      />,
    );
  });
  return { container, root };
}

describe("LinkedViewActivityToast", () => {
  it("renders a linked view result without an action", async () => {
    const { container, root } = await renderToast({
      state: "success",
      title: "Linked feature located",
      message: "Located 1 matching map feature.",
    });

    expect(document.body.textContent).toContain(
      "Located 1 matching map feature.",
    );
    expect(document.body.textContent).toContain("Linked feature located");
    expect(
      document
        .querySelector("[data-linked-view-toast]")
        ?.getAttribute("aria-label"),
    ).toBe("Linked view");
    expect(container.querySelector("button")).toBeNull();
    await act(async () => root.unmount());
    container.remove();
  });

  it("retries and dismisses from the toast", async () => {
    const onRetry = vi.fn();
    const onDismiss = vi.fn();
    const { root } = await renderToast(
      {
        state: "error",
        title: "Linked selection lookup failed",
        message: "The map query timed out.",
      },
      { onRetry, onDismiss },
    );

    const retry = document.querySelector(
      '[aria-label="Retry Linked selection lookup failed"]',
    );
    const dismiss = document.querySelector(
      '[aria-label="Dismiss Linked selection lookup failed"]',
    );
    expect(retry).toBeInstanceOf(HTMLButtonElement);
    expect(dismiss).toBeInstanceOf(HTMLButtonElement);
    await act(async () => {
      retry?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      dismiss?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onRetry).toHaveBeenCalledOnce();
    expect(onDismiss).toHaveBeenCalledOnce();
    await act(async () => root.unmount());
  });
});

// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import * as stylex from "@stylexjs/stylex";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Notice } from "./notice";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mountedRoots = new Set<ReturnType<typeof createRoot>>();

afterEach(async () => {
  await act(async () => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.clear();
  document.body.replaceChildren();
});

async function mount(element: React.ReactElement) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.add(root);

  await act(async () => root.render(element));
  return container;
}

describe("Notice", () => {
  it("is a neutral inline status by default", async () => {
    const container = await mount(<Notice>Saved</Notice>);

    const root = container.firstElementChild;
    const text = root?.firstElementChild;

    expect(root?.getAttribute("role")).toBe("status");
    expect(root?.className).toBe("base inline neutral");
    expect(text?.tagName).toBe("DIV");
    expect(text?.className).toBe("text");
    expect(text?.textContent).toBe("Saved");
    expect(container.querySelector("button")).toBeNull();
  });

  it.each([["danger"], ["warning"]] as const)(
    "announces %s as an alert",
    async (tone) => {
      const container = await mount(<Notice tone={tone}>Problem</Notice>);

      const root = container.firstElementChild;

      expect(root?.getAttribute("role")).toBe("alert");
      expect(root?.className).toBe(`base inline ${tone}`);
    },
  );

  it("takes an id so another control can be described by it", async () => {
    const container = await mount(
      <>
        <input aria-describedby="token-name-error" />
        <Notice id="token-name-error" tone="danger">
          A name is required
        </Notice>
      </>,
    );

    const notice = container.querySelector<HTMLElement>("#token-name-error");

    expect(notice?.getAttribute("role")).toBe("alert");
    expect(notice?.textContent).toBe("A name is required");
  });

  it("draws a banner", async () => {
    const container = await mount(
      <Notice variant="banner" tone="danger">
        x
      </Notice>,
    );

    expect(container.firstElementChild?.className).toBe("base banner danger");
  });

  it("shows a trailing action", async () => {
    const container = await mount(
      <Notice action={<button type="button">Retry</button>}>Failed</Notice>,
    );

    const action = container.querySelector(".action");
    const button = action?.querySelector("button");

    expect(action?.className).toBe("action");
    expect(button?.textContent).toBe("Retry");
  });

  it("dismisses", async () => {
    const spy = vi.fn();
    const container = await mount(<Notice onDismiss={spy}>Gone soon</Notice>);

    const buttons = container.querySelectorAll("button");
    const button = buttons[0] as HTMLButtonElement | undefined;

    expect(buttons).toHaveLength(1);
    expect(button?.getAttribute("aria-label")).toBe("Dismiss");
    expect(button?.getAttribute("title")).toBe("Dismiss");

    await act(async () => button?.click());

    expect(spy).toHaveBeenCalledTimes(1);

    const relabelled = await mount(
      <Notice onDismiss={spy} dismissLabel="Close notice">
        Gone soon
      </Notice>,
    );

    expect(relabelled.querySelector("button")?.getAttribute("aria-label")).toBe(
      "Close notice",
    );
  });

  it("takes overrides", async () => {
    const withClass = await mount(<Notice className="extra">Saved</Notice>);
    expect(withClass.firstElementChild?.className).toBe(
      "base inline neutral extra",
    );

    const withXstyle = await mount(
      <Notice
        xstyle={{ __styleName: "override" } as unknown as stylex.StyleXStyles}
      >
        Saved
      </Notice>,
    );
    expect(withXstyle.firstElementChild?.className).toBe(
      "base inline neutral override",
    );
  });
});

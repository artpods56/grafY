// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles extends Record<string, object>>(styles: Styles) =>
    Object.fromEntries(
      Object.entries(styles).map(([name, style]) => [
        name,
        { ...style, __styleName: name },
      ]),
    ) as Styles,
  defineVars: <Variables,>(variables: Variables) => variables,
  props: (
    ...styles: Array<{ __styleName?: string } | null | false | undefined>
  ) => ({
    className: styles
      .flatMap((style) =>
        style && style.__styleName ? [style.__styleName] : [],
      )
      .join(" "),
  }),
}));

import {
  Dialog,
  DialogContent,
  type DialogContentSize,
  DialogTitle,
} from "./dialog";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mountedRoots = new Set<ReturnType<typeof createRoot>>();

afterEach(async () => {
  await act(async () => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.clear();
  document.body.replaceChildren();
});

describe("DialogContent", () => {
  it.each<[DialogContentSize, string]>([
    ["compact", "sizeCompact"],
    ["default", "sizeDefault"],
    ["form", "sizeForm"],
    ["wide", "sizeWide"],
    ["catalog", "sizeCatalog"],
    ["viewport", "sizeViewport"],
  ])("composes the shared frame with the %s size", async (size, sizeStyle) => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    mountedRoots.add(root);

    await act(async () => {
      root.render(
        <Dialog open>
          <DialogContent size={size}>
            <DialogTitle>Dialog title</DialogTitle>
          </DialogContent>
        </Dialog>,
      );
    });

    const popup = document.querySelector<HTMLElement>('[role="dialog"]');
    expect(popup?.classList.contains("content")).toBe(true);
    expect(popup?.classList.contains(sizeStyle)).toBe(true);
  });
});

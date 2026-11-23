// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  Dialog,
  DialogContent,
  type DialogContentSize,
  DialogTitle,
} from "./dialog";

/**
 * The shared mock in `vitest.setup.ts` reads one `__styleName` per `props`
 * argument, so an array `xstyle` — how `DialogContent` hands `IconButton` its
 * `[close, phoneTouch.square]` pair — would vanish from the class names. This
 * file's copy mirrors the shared mock but flattens arrays, the way the
 * compiled `stylex.props` treats them.
 */
vi.mock("@stylexjs/stylex", () => {
  const names = (style: unknown): string[] => {
    if (Array.isArray(style)) return style.flatMap(names);
    return style && (style as { __styleName?: string }).__styleName
      ? [(style as { __styleName: string }).__styleName]
      : [];
  };
  return {
    create: (styles: Record<string, object>) =>
      Object.fromEntries(
        Object.entries(styles).map(([name, style]) => [
          name,
          { ...style, __styleName: name },
        ]),
      ),
    defineVars: (variables: unknown) => variables,
    keyframes: () => "keyframes",
    defaultMarker: () => ({}),
    when: { ancestor: (selector: string) => selector },
    props: (...styles: unknown[]) => ({
      className: styles.flatMap(names).join(" "),
    }),
  };
});

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

  it("closes through a kit IconButton that keeps its phone target", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    mountedRoots.add(root);

    function Stateful() {
      const [open, setOpen] = React.useState(true);
      return (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent size="compact">
            <DialogTitle>Dialog title</DialogTitle>
          </DialogContent>
        </Dialog>
      );
    }
    await act(async () => root.render(<Stateful />));

    const close = document.querySelector<HTMLElement>(
      'button[aria-label="Close"]',
    );
    if (!close) throw new Error("expected the Close button");
    const classes = close.className.split(" ");
    // The kit's `IconButton` drew the button, so it carries the kit rules …
    expect(classes).toContain("ghost");
    expect(classes).toContain("md");
    // … and both overrides: the dialog's own anchor, and `square`, the name
    // `phoneTouch.square` shares with the IconButton's square shape.
    expect(classes).toContain("close");
    expect(classes).toContain("square");

    await act(async () => close.click());
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });
});

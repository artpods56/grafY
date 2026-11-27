"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Crosshair, LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { tokens } from "@/lib/stylex/tokens.stylex";

import {
  describeTarget,
  elementAtPoint,
  FEEDBACK_UI_ATTRIBUTE,
  meaningfulTarget,
} from "./element-description";
import type { PickedTarget } from "./feedback-reducer";

const spin = stylex.keyframes({ to: { transform: "rotate(360deg)" } });

const s = stylex.create({
  layer: {
    position: "fixed",
    inset: 0,
    zIndex: 2147483000,
    cursor: "crosshair",
    touchAction: "none",
  },
  layerBusy: { cursor: "progress" },
  highlight: {
    position: "fixed",
    pointerEvents: "none",
    boxSizing: "border-box",
    borderWidth: "2px",
    borderStyle: "solid",
    borderColor: tokens.colorInfo,
    borderRadius: tokens.radiusSm,
    backgroundColor:
      "light-dark(rgba(74, 143, 212, 0.12), rgba(96, 165, 250, 0.14))",
    transitionProperty: {
      default: "top, left, width, height",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    transitionDuration: "70ms",
    transitionTimingFunction: "ease-out",
  },
  chip: {
    position: "fixed",
    pointerEvents: "none",
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    maxWidth: "min(360px, calc(100vw - 16px))",
    paddingBlock: "3px",
    paddingInline: "8px",
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorAccent,
    color: tokens.colorOnAccent,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    lineHeight: "16px",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  bar: {
    position: "fixed",
    top: "max(12px, env(safe-area-inset-top))",
    left: "50%",
    transform: "translateX(-50%)",
    display: "flex",
    alignItems: "center",
    gap: tokens.space2,
    maxWidth: "calc(100vw - 32px)",
    paddingBlock: "6px",
    paddingInlineStart: tokens.space3,
    paddingInlineEnd: "6px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorSurfaceElevated,
    boxShadow: tokens.shadowNodeRaised,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    cursor: "default",
  },
  barText: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    minWidth: 0,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  barHint: {
    color: tokens.colorMuted,
    display: { default: "inline", "@media (max-width: 620px)": "none" },
  },
  spinner: {
    animationName: {
      default: spin,
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    animationDuration: "800ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
});

interface Highlight {
  readonly element: Element | null;
  readonly rect: { x: number; y: number; width: number; height: number };
  readonly name: string;
}

const CHIP_HEIGHT = 24;

/**
 * A transparent layer over the whole app. Moving the pointer outlines what a click
 * would pick; a click picks it. Its own chrome carries `data-feedback-ui`, so it
 * looks through itself and stays out of the screenshot.
 */
export function FeedbackPicker({
  capturing,
  onPick,
  onSkip,
  onCancel,
}: {
  /** The target being photographed; the layer stops picking meanwhile. */
  capturing: PickedTarget | null;
  onPick: (target: PickedTarget) => void;
  onSkip: () => void;
  onCancel: () => void;
}) {
  const [hover, setHover] = React.useState<Highlight | null>(null);
  const busy = capturing !== null;

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      onCancel();
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [onCancel]);

  const targetAt = (event: React.PointerEvent | React.MouseEvent) => {
    if ((event.target as Element).closest("[data-feedback-bar]")) return null;
    const hit = elementAtPoint(event.clientX, event.clientY);
    return hit ? meaningfulTarget(hit) : null;
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (busy) return;
    const target = targetAt(event);
    if (!target) {
      setHover(null);
      return;
    }
    if (hover?.element === target) return;
    const picked = describeTarget(target);
    setHover({ element: target, rect: picked.element.rect, name: picked.name });
  };

  const onClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (busy) return;
    const target = targetAt(event);
    if (!target) return;
    event.preventDefault();
    onPick(describeTarget(target));
  };

  const shown: Highlight | null = capturing
    ? { element: null, rect: capturing.element.rect, name: capturing.name }
    : hover;
  const chipTop = shown
    ? shown.rect.y > CHIP_HEIGHT + 4
      ? shown.rect.y - CHIP_HEIGHT - 4
      : shown.rect.y + shown.rect.height + 4
    : 0;

  return (
    <div
      {...{ [FEEDBACK_UI_ATTRIBUTE]: "" }}
      {...stylex.props(s.layer, busy && s.layerBusy)}
      onPointerMove={onPointerMove}
      onPointerLeave={() => setHover(null)}
      onClick={onClick}
    >
      {shown ? (
        <>
          <div
            {...stylex.props(s.highlight)}
            style={{
              top: shown.rect.y,
              left: shown.rect.x,
              width: shown.rect.width,
              height: shown.rect.height,
            }}
            aria-hidden="true"
          />
          <div
            {...stylex.props(s.chip)}
            style={{ top: chipTop, left: Math.max(8, shown.rect.x) }}
            aria-hidden="true"
          >
            {shown.name}
          </div>
        </>
      ) : null}
      <div
        data-feedback-bar=""
        role="toolbar"
        aria-label="Pick what your feedback is about"
        {...stylex.props(s.bar)}
      >
        <span {...stylex.props(s.barText)} role="status">
          {busy ? (
            <>
              <LoaderCircle
                size={14}
                aria-hidden="true"
                {...stylex.props(s.spinner)}
              />
              Taking a screenshot…
            </>
          ) : (
            <>
              <Crosshair size={14} aria-hidden="true" />
              Click what your feedback is about
              <span {...stylex.props(s.barHint)}>· Esc to cancel</span>
            </>
          )}
        </span>
        {busy ? null : (
          <Button type="button" variant="ghost" size="sm" onClick={onSkip}>
            Whole page
          </Button>
        )}
        <Button type="button" variant="secondary" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

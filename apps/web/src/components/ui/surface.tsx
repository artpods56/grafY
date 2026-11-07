"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { tokens } from "@/lib/stylex/tokens.stylex";

function joinClassNames(...names: Array<string | undefined>) {
  return names.filter(Boolean).join(" ") || undefined;
}

/**
 * `floating` is the one the kit could not draw before: a strip of controls that
 * sits on top of a map or a canvas, where the content behind still matters, so
 * the surface is translucent and lifted rather than flat.
 */
export type SurfaceTone = "raised" | "floating" | "sunken";
export type SurfacePadding = "none" | "xs" | "sm" | "md";
export type SurfaceShape = "sm" | "md" | "lg" | "pill";

export type SurfaceProps = Omit<
  React.ComponentPropsWithoutRef<"div">,
  "className" | "style"
> & {
  tone?: SurfaceTone;
  padding?: SurfacePadding;
  shape?: SurfaceShape;
  /** Plain class names added after the StyleX ones, e.g. React Flow's "nodrag nopan". */
  className?: string;
  /** Caller overrides made with stylex.create, applied last so they win. */
  xstyle?: stylex.StyleXStyles;
};

const surface = stylex.create({
  base: {
    boxSizing: "border-box",
    minWidth: 0,
    borderWidth: 1,
    borderStyle: "solid",
  },
  raised: {
    backgroundColor: tokens.colorSurface,
    borderColor: tokens.colorBorder,
  },
  floating: {
    // The token is already the translucent pair the canvas controls use; the
    // blur is what makes text under the strip unreadable rather than busy.
    backgroundColor: tokens.colorFlowControls,
    borderColor: tokens.colorBorder,
    boxShadow: tokens.shadowNodeRaised,
    backdropFilter: "blur(6px)",
    WebkitBackdropFilter: "blur(6px)",
  },
  sunken: {
    backgroundColor: tokens.colorSurfaceSunken,
    borderColor: tokens.colorDivider,
  },
  none: {
    padding: 0,
  },
  xs: {
    padding: "3px",
  },
  sm: {
    padding: "5px",
  },
  md: {
    padding: "10px",
  },
  smShape: {
    borderRadius: tokens.radiusSm,
  },
  mdShape: {
    borderRadius: tokens.radiusMd,
  },
  lgShape: {
    borderRadius: tokens.radiusLg,
  },
  pillShape: {
    borderRadius: "9999px",
  },
});

const TONE = {
  raised: surface.raised,
  floating: surface.floating,
  sunken: surface.sunken,
} as const;

const PADDING = {
  none: surface.none,
  xs: surface.xs,
  sm: surface.sm,
  md: surface.md,
} as const;

const SHAPE = {
  sm: surface.smShape,
  md: surface.mdShape,
  lg: surface.lgShape,
  pill: surface.pillShape,
} as const;

/**
 * The chrome a control row wears, without a call site inventing a background.
 *
 * `tone="floating"`, `shape="pill"` is the map utility strip: a translucent,
 * lifted row of buttons over live map tiles. Nothing here owns layout — position
 * the surface with the caller's own grid or absolute rule, and put the controls
 * in the kit's own parts.
 */
export const Surface = React.forwardRef<HTMLDivElement, SurfaceProps>(
  function Surface(
    {
      tone = "raised",
      padding = "xs",
      shape = "md",
      className,
      xstyle,
      children,
      ...props
    },
    ref,
  ) {
    const styled = stylex.props(
      surface.base,
      TONE[tone],
      PADDING[padding],
      SHAPE[shape],
      xstyle,
    );
    return (
      <div
        ref={ref}
        {...props}
        className={joinClassNames(styled.className, className)}
        style={styled.style}
      >
        {children}
      </div>
    );
  },
);

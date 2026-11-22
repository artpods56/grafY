"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";

/** How far the fade at a clipped edge of a card's text reaches. */
const TEXT_FADE = "32px";

const s = stylex.create({
  // Readable content shows itself instead of a file tile.
  textBody: {
    flexDirection: "column",
    alignItems: "stretch",
    gap: "6px",
    overflow: "hidden",
  },
  textContent: {
    minWidth: 0,
    margin: 0,
    // Pretty-printed JSON can run to hundreds of lines. The card keeps a
    // bounded height; the rest is reached by selecting the card and scrolling.
    overflow: "hidden",
    color: tokens.colorText,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
    lineHeight: 1.5,
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
  },
  // Rendered words take the page's type; the raw view keeps the monospace above.
  textRendered: {
    fontFamily: "inherit",
    fontSize: tokens.fontSizeXs,
    whiteSpace: "normal",
  },
  textScrollable: { overflow: "auto" },
});

const NO_TEXT_EDGES = { above: false, below: false, wide: false };

/** Clipped text fades out at each edge that has more beyond it. */
function textFadeMask({ above, below }: typeof NO_TEXT_EDGES) {
  if (!above && !below) return undefined;
  const top = above ? `transparent, black ${TEXT_FADE}` : "black";
  const bottom = below
    ? `black calc(100% - ${TEXT_FADE}), transparent`
    : "black";
  return `linear-gradient(to bottom, ${top}, ${bottom})`;
}

/**
 * The words an artifact card prints: its own text, or rendered markdown or HTML,
 * inside a body of the height the card decided on.
 *
 * Overflow is measured, not counted: a long line wraps, so the number of newlines
 * says little about how tall the text renders. Only a body that does overflow
 * takes the wheel away from the canvas, and only while the card is selected.
 */
export function CardTextBody({
  height,
  rendered = false,
  interactive = false,
  children,
}: {
  /** The tallest the text may draw before it is reached by scrolling. */
  height: number;
  /** Rendered words (markdown, HTML) take the page's type instead of monospace. */
  rendered?: boolean;
  /** The card is selected, so its own scrolling beats the canvas's. */
  interactive?: boolean;
  children: React.ReactNode;
}) {
  const ref = React.useRef<HTMLElement>(null);
  const [edges, setEdges] = React.useState(NO_TEXT_EDGES);
  const measure = React.useCallback(() => {
    const element = ref.current;
    const next = element
      ? {
          above: element.scrollTop > 1,
          below:
            element.scrollTop + element.clientHeight < element.scrollHeight - 1,
          wide: element.scrollWidth > element.clientWidth + 1,
        }
      : NO_TEXT_EDGES;
    setEdges((current) =>
      current.above === next.above &&
      current.below === next.below &&
      current.wide === next.wide
        ? current
        : next,
    );
  }, []);
  React.useLayoutEffect(() => {
    const element = ref.current;
    measure();
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [measure, children, height, rendered]);
  const overflows = edges.above || edges.below || edges.wide;
  const props = stylex.props(
    s.textContent,
    rendered ? s.textRendered : null,
    overflows && interactive ? s.textScrollable : null,
  );

  return React.createElement(
    rendered ? "div" : "pre",
    {
      ...props,
      ref,
      onScroll: measure,
      style: {
        ...props.style,
        maxHeight: height,
        maskImage: textFadeMask(edges),
      },
      className:
        overflows && interactive
          ? `nodrag nowheel ${props.className ?? ""}`
          : props.className,
    },
    children,
  );
}

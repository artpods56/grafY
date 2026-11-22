"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { disarmFrameHtml } from "../frame-html";
import { CellHtmlTable } from "./cell-html-table";
import { htmlFrameDocument, isWholeHtmlTable } from "./cell-views";

const s = stylex.create({
  frame: {
    display: "block",
    width: "100%",
    borderWidth: 0,
    backgroundColor: "transparent",
  },
  // Until it is meant to be used, the frame must not take the card's drags and the
  // canvas's zoom for itself: an event inside a frame never reaches this page.
  resting: { pointerEvents: "none" },
});

/** The page's text colour and scheme where the frame sits, which it cannot inherit. */
function themeAt(element: HTMLElement) {
  const style = getComputedStyle(element);
  return { color: style.color, colorScheme: style.colorScheme };
}

/**
 * HTML someone wrote. A bare table is drawn as this page's own elements. Anything else
 * goes in an empty sandbox with no network: no scripts, no navigation, no forms, an
 * origin of its own, and nothing fetched, so it can only be looked at. Remote links
 * are removed first. The sandbox does not stop the frame from navigating itself.
 */
export function HtmlView({
  html,
  height,
  interactive = true,
}: {
  html: string;
  /** The frame cannot be measured from out here, so its height is given. */
  height: number | string;
  /** Whether a pointer may reach it: scrolling it, selecting its text. */
  interactive?: boolean;
}): React.ReactElement {
  const [theme, setTheme] = React.useState<ReturnType<typeof themeAt> | null>(
    null,
  );
  const measure = React.useCallback((element: HTMLElement | null) => {
    if (element) setTheme(themeAt(element));
  }, []);
  // The press that selects a card is also the start of dragging it, and a frame that
  // woke up under that press would take the drag. It waits for the press to end.
  const [pressed, setPressed] = React.useState(false);
  React.useEffect(() => {
    const press = () => setPressed(true);
    const release = () => setPressed(false);
    window.addEventListener("pointerdown", press, true);
    window.addEventListener("pointerup", release, true);
    window.addEventListener("pointercancel", release, true);
    return () => {
      window.removeEventListener("pointerdown", press, true);
      window.removeEventListener("pointerup", release, true);
      window.removeEventListener("pointercancel", release, true);
    };
  }, []);
  const awake = interactive && !pressed;
  const safeHtml = React.useMemo(() => disarmFrameHtml(html), [html]);
  if (isWholeHtmlTable(safeHtml)) return <CellHtmlTable html={safeHtml} />;
  return (
    <div ref={measure} style={{ height }}>
      {theme ? (
        <iframe
          title="Rendered HTML"
          sandbox=""
          srcDoc={htmlFrameDocument(safeHtml, theme)}
          className={awake ? "nodrag nowheel" : undefined}
          {...stylex.props(s.frame, awake ? null : s.resting)}
          style={{ height: "100%" }}
        />
      ) : null}
    </div>
  );
}

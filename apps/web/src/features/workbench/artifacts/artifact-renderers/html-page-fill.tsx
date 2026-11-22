"use client";

import { LoaderCircle } from "lucide-react";
import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { Button } from "@/components/ui/button";
import { tokens } from "@/lib/stylex/tokens.stylex";

import type { HtmlPageLoad } from "./html-page";
import { HtmlView } from "./table/html-view";

const s = stylex.create({
  fill: {
    minWidth: 0,
  },
  scroll: { overflow: "auto" },
  template: {
    margin: 0,
    overflow: "hidden",
    color: tokens.colorText,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
    lineHeight: 1.5,
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
  },
  status: {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    justifyContent: "flex-start",
    gap: "6px",
    boxSizing: "border-box",
    margin: 0,
    overflow: "hidden",
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  reading: {
    flexDirection: "row",
    alignItems: "center",
  },
  line: { margin: 0 },
  spinner: {
    flexShrink: 0,
    color: tokens.colorInfo,
    animationName: "grafy-spin",
    animationDuration: "900ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
});

function withWheel(props: { className?: string }, selected: boolean) {
  return selected ? `nodrag nowheel ${props.className ?? ""}` : props.className;
}

/** The inside of an html.page card: the filled page, its template, or why not. */
export function HtmlPageFill({
  load,
  height,
  selected,
  view,
  onRetry,
}: {
  load: HtmlPageLoad | undefined;
  height: number;
  selected: boolean;
  view: "html" | "text";
  onRetry: () => void;
}): React.ReactElement {
  if (load && view === "text" && load.status !== "unreadable") {
    const props = stylex.props(s.fill, s.template, selected ? s.scroll : null);
    return (
      <pre
        {...props}
        className={withWheel(props, selected)}
        style={{ height, maxHeight: height }}
      >
        {load.template}
      </pre>
    );
  }
  if (!load) {
    return (
      <div
        role="status"
        {...stylex.props(s.fill, s.status, s.reading)}
        style={{ height }}
      >
        <LoaderCircle
          size={13}
          aria-hidden="true"
          {...stylex.props(s.spinner)}
        />
        <span>Reading this page</span>
      </div>
    );
  }
  if (load.status === "ready") {
    return (
      <HtmlView html={load.rendered} height={height} interactive={selected} />
    );
  }
  const messages =
    load.status === "sources"
      ? load.failures.map((failure) => failure.message)
      : [load.message];
  const props = stylex.props(s.fill, s.status, selected ? s.scroll : null);
  return (
    <div
      role="status"
      {...props}
      className={withWheel(props, selected)}
      style={{ height }}
    >
      {messages.map((message) => (
        <p key={message} {...stylex.props(s.line)}>
          {message}
        </p>
      ))}
      {load.status === "template" ? null : (
        <Button
          variant="soft"
          size="sm"
          className="nodrag nopan"
          onClick={onRetry}
        >
          Try again
        </Button>
      )}
    </div>
  );
}

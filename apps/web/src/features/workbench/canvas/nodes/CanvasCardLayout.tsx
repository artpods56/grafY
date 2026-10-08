"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

/**
 * Shared card chrome for artifact cards and operator nodes: name above the
 * plate, rails hung outside the body, no layout reserved for the marks.
 * Option B keeps port names off the plate — balls carry them on hover.
 */

export const canvasCard = stylex.create({
  // The frame is exactly the card: head over body. The rails hang off the
  // body's sides, so picking the card up never changes its geometry.
  frame: {
    display: "grid",
    gridTemplateRows: "auto minmax(0, 1fr)",
    position: "relative",
  },
  head: { gridRow: 1, minWidth: 0 },
  body: { gridRow: 2, minWidth: 0, position: "relative" },
});

export const canvasCardRail = stylex.create({
  // A rail is one port slot (30px) wide, a small gap (8px) away from the body.
  // Every mark centres on it, so the two rails mirror each other and the
  // action cannot drift off the port centreline. Rails sit outside the body
  // and take no layout space, so revealing them moves nothing but the marks.
  // They come before the media in the DOM, so the card paints over whatever
  // part of a mark is still tucked under it.
  rail: {
    position: "absolute",
    top: 0,
    bottom: 0,
    width: "30px",
    display: "flex",
    pointerEvents: "none",
  },
  left: {
    right: "calc(100% + 8px)",
    flexDirection: "column",
    justifyContent: "flex-start",
    alignItems: "center",
  },
  right: {
    left: "calc(100% + 8px)",
    flexDirection: "column",
    justifyContent: "flex-start",
    alignItems: "center",
  },
  // Stack of port slots; each slot is lattice-tall so ball centres stay on
  // the same mid-cell lines the old in-plate rail used.
  stack: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    width: "100%",
  },
  // Outputs pin to the body's bottom edge, like an artifact's single out.
  output: {
    marginTop: "auto",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    width: "100%",
  },
  slot: {
    display: "grid",
    placeItems: "center",
    width: "100%",
    flexShrink: 0,
  },
  // Out of the rail's flow. The rail is as wide as a port, so centring here
  // puts the button on the port line; the 4px top pad (half of 30 − 22) sets
  // it level with the first input port.
  actions: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    paddingTop: "4px",
  },
});

export function CanvasCardFrame({
  children,
  ...rest
}: React.ComponentProps<"div">) {
  return (
    <div
      data-artifact-frame="true"
      {...stylex.props(canvasCard.frame)}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CanvasCardHead({
  children,
  ...rest
}: React.ComponentProps<"div">) {
  return (
    <div data-artifact-head="true" {...stylex.props(canvasCard.head)} {...rest}>
      {children}
    </div>
  );
}

export function CanvasCardBody({
  children,
  ...rest
}: React.ComponentProps<"div">) {
  return (
    <div data-artifact-body="true" {...stylex.props(canvasCard.body)} {...rest}>
      {children}
    </div>
  );
}

export function CanvasCardLeftRail({
  children,
  testId,
}: {
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <div
      data-artifact-rail="left"
      data-testid={testId}
      {...stylex.props(canvasCardRail.rail, canvasCardRail.left)}
    >
      <div {...stylex.props(canvasCardRail.stack)}>{children}</div>
    </div>
  );
}

export function CanvasCardRightRail({
  children,
  actions,
  testId,
}: {
  children: React.ReactNode;
  actions?: React.ReactNode;
  testId?: string;
}) {
  return (
    <div
      data-artifact-rail="right"
      data-testid={testId}
      {...stylex.props(canvasCardRail.rail, canvasCardRail.right)}
    >
      {actions}
      <div {...stylex.props(canvasCardRail.output)}>{children}</div>
    </div>
  );
}

export function CanvasCardRailSlot({
  height,
  children,
  ...rest
}: {
  height: number;
  children: React.ReactNode;
} & React.ComponentProps<"div">) {
  return (
    <div
      data-testid="port-rail-row"
      {...stylex.props(canvasCardRail.slot)}
      style={{ height }}
      {...rest}
    >
      {children}
    </div>
  );
}

"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

/**
 * Shared card chrome for artifact cards and operator nodes: name above the
 * body. An artifact card hangs its ports on rails outside the body; a node
 * labels its ports on rows inside its plate.
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
    justifyContent: "center",
    alignItems: "flex-start",
  },
  right: {
    left: "calc(100% + 8px)",
    flexDirection: "column",
    justifyContent: "flex-start",
    alignItems: "center",
  },
  // Only the output port sets the rail height, so a short file card still pins
  // that port to the body's bottom edge.
  output: { marginTop: "auto" },
  // Out of the rail's flow. The rail is as wide as a port, so centring here
  // puts the button on the port line; the 4px top pad (half of 30 − 22) sets
  // it level with the input port.
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

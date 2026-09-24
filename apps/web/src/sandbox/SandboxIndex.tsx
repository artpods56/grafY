"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import Link from "next/link";

import { tokens } from "@/lib/stylex/tokens.stylex";
import { SPIKES } from "./catalog";

const s = stylex.create({
  page: {
    minHeight: "100svh",
    padding: "28px 32px 48px",
    backgroundColor: tokens.colorBg,
    color: tokens.colorText,
  },
  kicker: {
    marginBottom: "6px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  title: {
    marginBottom: "8px",
    fontSize: tokens.fontSizeLg,
    fontWeight: 600,
    letterSpacing: "-0.02em",
  },
  lead: {
    maxWidth: "42rem",
    marginBottom: "24px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
  },
  list: {
    display: "grid",
    gap: "8px",
    maxWidth: "36rem",
  },
  row: {
    display: "grid",
    gap: "4px",
    padding: "12px 14px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    backgroundColor: {
      default: tokens.colorChrome,
      ":hover": tokens.colorHover,
    },
  },
  rowTitle: {
    fontSize: tokens.fontSizeMd,
    fontWeight: 600,
  },
  rowSummary: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.45,
  },
});

export function SandboxIndex() {
  return (
    <div {...stylex.props(s.page)}>
      <div {...stylex.props(s.kicker)}>Development only</div>
      <h1 {...stylex.props(s.title)}>Sandbox</h1>
      <p {...stylex.props(s.lead)}>
        Spikes against real Grafy chrome. Nothing here is a product surface. Add
        a folder under <code>src/sandbox/spikes</code> and register it in the
        catalog.
      </p>
      <div {...stylex.props(s.list)}>
        {SPIKES.map((spike) => (
          <Link
            key={spike.id}
            href={`/sandbox/${spike.id}`}
            {...stylex.props(s.row)}
          >
            <span {...stylex.props(s.rowTitle)}>{spike.title}</span>
            <span {...stylex.props(s.rowSummary)}>{spike.summary}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

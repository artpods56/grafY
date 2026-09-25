"use client";

import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";

import { record } from "./payload";
import { MONO } from "./styles";

const s = stylex.create({
  prettyGrid: { display: "grid", gap: "6px" },
  prettyRow: {
    display: "grid",
    gridTemplateColumns: "94px minmax(0, 1fr)",
    alignItems: "baseline",
    gap: "8px",
  },
  prettyKey: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "10px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  prettyText: {
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.5,
    wordBreak: "break-word",
  },
  prettyNumber: {
    color: tokens.colorAccent,
    fontFamily: MONO,
    fontSize: tokens.fontSizeXs,
  },
  chips: { display: "flex", flexWrap: "wrap", gap: "4px" },
  valueChip: {
    padding: "1px 7px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurface,
    fontSize: "10px",
    fontWeight: 600,
  },
  nestedGroup: {
    display: "grid",
    gap: "5px",
    marginTop: "2px",
    paddingLeft: "9px",
    borderLeftWidth: 2,
    borderLeftStyle: "solid",
    borderLeftColor: tokens.colorDivider,
  },
});

export function PrettyValue({ value }: { value: unknown }) {
  if (typeof value === "string") {
    return <span {...stylex.props(s.prettyText)}>{value}</span>;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return <span {...stylex.props(s.prettyNumber)}>{String(value)}</span>;
  }
  if (Array.isArray(value)) {
    if (value.every((item) => record(item) === null)) {
      return (
        <span {...stylex.props(s.chips)}>
          {value.map((item, index) => (
            <span key={index} {...stylex.props(s.valueChip)}>
              {typeof item === "string" ? item : JSON.stringify(item)}
            </span>
          ))}
        </span>
      );
    }
    return (
      <span {...stylex.props(s.nestedGroup)}>
        {value.map((item, index) => (
          <PrettyValue key={index} value={item} />
        ))}
      </span>
    );
  }
  const object = record(value);
  if (object) {
    return (
      <span {...stylex.props(s.prettyGrid)}>
        {Object.entries(object).map(([key, entry]) => (
          <span key={key} {...stylex.props(s.prettyRow)}>
            <span {...stylex.props(s.prettyKey)} title={key}>
              {key}
            </span>
            <PrettyValue value={entry} />
          </span>
        ))}
      </span>
    );
  }
  return <span {...stylex.props(s.prettyText)}>—</span>;
}

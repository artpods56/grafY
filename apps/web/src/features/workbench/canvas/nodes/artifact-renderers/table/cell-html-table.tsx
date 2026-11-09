"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";

const s = stylex.create({
  // As wide as its words: a narrow card scrolls the table rather than breaking them.
  table: {
    width: "max-content",
    overflowWrap: "normal",
    borderCollapse: "collapse",
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
  },
  cell: {
    padding: "3px 6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    textAlign: "left",
    verticalAlign: "top",
  },
  header: {
    color: tokens.colorTextEmphasis,
    fontWeight: 600,
  },
});

const KEPT = new Set([
  "table",
  "caption",
  "thead",
  "tbody",
  "tfoot",
  "tr",
  "th",
  "td",
  "br",
  "b",
  "strong",
  "i",
  "em",
  "sub",
  "sup",
]);

/** A span a provider wrote, when it is a span and not something else. */
function span(element: Element, name: string): number | undefined {
  const value = element.getAttribute(name);
  return value && /^[1-9]\d{0,3}$/.test(value) ? Number(value) : undefined;
}

function rendered(node: Node, key: number): React.ReactNode {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent;
  if (node.nodeType !== Node.ELEMENT_NODE) return null;
  const element = node as Element;
  const name = element.tagName.toLowerCase();
  const children = Array.from(element.childNodes, rendered);
  // An element off the list loses itself and keeps its words.
  if (!KEPT.has(name))
    return <React.Fragment key={key}>{children}</React.Fragment>;
  if (name === "br") return <br key={key} />;
  if (name === "table") {
    return (
      <table key={key} {...stylex.props(s.table)}>
        {children}
      </table>
    );
  }
  if (name === "th" || name === "td") {
    const Cell = name;
    return (
      <Cell
        key={key}
        rowSpan={span(element, "rowspan")}
        colSpan={span(element, "colspan")}
        {...stylex.props(s.cell, name === "th" ? s.header : null)}
      >
        {children}
      </Cell>
    );
  }
  return React.createElement(name, { key }, children);
}

/**
 * An HTML table a provider wrote, drawn as this page's own elements. Parsing makes an
 * inert document, and only table structure and its two span attributes are carried
 * over, so nothing the provider wrote can run or load, and the table takes the theme.
 */
export function CellHtmlTable({ html }: { html: string }): React.ReactElement {
  const body = new DOMParser().parseFromString(html, "text/html").body;
  return <>{Array.from(body.childNodes, rendered)}</>;
}

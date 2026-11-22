"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import Markdown, {
  type MarkdownToJSX,
  sanitizer as sanitizeMarkdownUrl,
} from "markdown-to-jsx";

import { tokens } from "@/lib/stylex/tokens.stylex";

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

const s = stylex.create({
  root: {
    color: "inherit",
    fontSize: "14px",
    lineHeight: 1.45,
    overflowWrap: "anywhere",
  },
  heading1: {
    marginTop: 0,
    marginBottom: "0.4em",
    fontSize: "1.35em",
    fontWeight: 700,
    lineHeight: 1.25,
  },
  heading2: {
    marginTop: "0.75em",
    marginBottom: "0.35em",
    fontSize: "1.15em",
    fontWeight: 700,
    lineHeight: 1.3,
  },
  heading3: {
    marginTop: "0.65em",
    marginBottom: "0.3em",
    fontSize: "1em",
    fontWeight: 700,
    lineHeight: 1.35,
  },
  paragraph: {
    marginTop: 0,
    marginBottom: "0.55em",
  },
  list: {
    marginTop: 0,
    marginBottom: "0.55em",
    paddingLeft: "1.25em",
  },
  listItem: {
    marginBottom: "0.2em",
  },
  blockquote: {
    marginTop: "0.55em",
    marginRight: 0,
    marginBottom: "0.55em",
    marginLeft: 0,
    paddingLeft: "0.7em",
    borderLeftWidth: 2,
    borderLeftStyle: "solid",
    borderLeftColor: "currentColor",
    opacity: 0.85,
  },
  code: {
    fontFamily: MONO,
    fontSize: "0.85em",
  },
  inlineCode: {
    paddingTop: "1px",
    paddingRight: "4px",
    paddingBottom: "1px",
    paddingLeft: "4px",
    borderRadius: "4px",
    backgroundColor: tokens.colorSurfaceSunken,
  },
  pre: {
    marginTop: "0.55em",
    marginBottom: "0.55em",
    padding: "0.55em 0.65em",
    overflowX: "auto",
    borderRadius: "6px",
    backgroundColor: tokens.colorSurfaceSunken,
    lineHeight: 1.45,
    whiteSpace: "pre",
  },
  link: {
    color: tokens.colorAccent,
    textDecorationLine: "underline",
    textUnderlineOffset: "2px",
  },
  rule: {
    height: 1,
    marginTop: "0.75em",
    marginBottom: "0.75em",
    borderWidth: 0,
    backgroundColor: "currentColor",
    opacity: 0.35,
  },
  table: {
    display: "block",
    width: "100%",
    marginTop: "0.55em",
    marginBottom: "0.55em",
    overflowX: "auto",
    borderCollapse: "collapse",
    fontSize: "0.92em",
  },
  tableCell: {
    padding: "4px 8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    textAlign: "left",
  },
  tableHeader: {
    fontWeight: 700,
  },
});

function safeMarkdownUrl(value: string | undefined): string | null {
  if (!value) return null;
  const sanitized = sanitizeMarkdownUrl(value);
  if (!sanitized) return null;
  const scheme = /^([a-z][a-z\d+.-]*):/i.exec(sanitized.trim())?.[1];
  if (!scheme) return sanitized;
  return ["http", "https", "mailto"].includes(scheme.toLowerCase())
    ? sanitized
    : null;
}

function MarkdownCode({
  className,
  children,
  ...props
}: React.ComponentPropsWithoutRef<"code">) {
  const block = typeof className === "string" && className.includes("lang-");
  return (
    <code
      className={className}
      {...props}
      {...stylex.props(s.code, block ? null : s.inlineCode)}
    >
      {children}
    </code>
  );
}

function MarkdownLink({
  href,
  children,
  ...props
}: React.ComponentPropsWithoutRef<"a">) {
  const safeHref = safeMarkdownUrl(href);
  if (!safeHref) {
    return <span {...props}>{children}</span>;
  }
  return (
    <a
      {...props}
      href={safeHref}
      target="_blank"
      rel="noreferrer noopener"
      {...stylex.props(s.link)}
    >
      {children}
    </a>
  );
}

const markdownOptions: MarkdownToJSX.Options = {
  disableParsingRawHTML: true,
  enforceAtxHeadings: true,
  sanitizer: (value) => safeMarkdownUrl(value),
  wrapper: React.Fragment,
  overrides: {
    h1: { component: "h1", props: stylex.props(s.heading1) },
    h2: { component: "h2", props: stylex.props(s.heading2) },
    h3: { component: "h3", props: stylex.props(s.heading3) },
    h4: { component: "h4", props: stylex.props(s.heading3) },
    h5: { component: "h5", props: stylex.props(s.heading3) },
    h6: { component: "h6", props: stylex.props(s.heading3) },
    p: { component: "p", props: stylex.props(s.paragraph) },
    ul: { component: "ul", props: stylex.props(s.list) },
    ol: { component: "ol", props: stylex.props(s.list) },
    li: { component: "li", props: stylex.props(s.listItem) },
    blockquote: {
      component: "blockquote",
      props: stylex.props(s.blockquote),
    },
    code: MarkdownCode,
    pre: { component: "pre", props: stylex.props(s.pre) },
    a: MarkdownLink,
    hr: { component: "hr", props: stylex.props(s.rule) },
    table: { component: "table", props: stylex.props(s.table) },
    th: {
      component: "th",
      props: stylex.props(s.tableCell, s.tableHeader),
    },
    td: { component: "td", props: stylex.props(s.tableCell) },
    img: {
      component: ({ alt }: { alt?: string }) => (
        <span>{alt ? `[image: ${alt}]` : "[image]"}</span>
      ),
    },
  },
};

/** Secure markdown renderer for canvas/documentation surfaces. */
export function SafeMarkdown({
  children,
  className,
  style,
}: {
  children: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div {...stylex.props(s.root)} className={className} style={style}>
      <Markdown options={markdownOptions}>{children}</Markdown>
    </div>
  );
}

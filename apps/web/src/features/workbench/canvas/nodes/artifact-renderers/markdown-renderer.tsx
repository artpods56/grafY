"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import Markdown, {
  type MarkdownToJSX,
  sanitizer as sanitizeMarkdownUrl,
} from "markdown-to-jsx";

import { tokens } from "@/lib/stylex/tokens.stylex";

import { artifactMeta } from "./artifact-meta";
import { markdownPayload } from "./payload";
import { PrettyValue } from "./pretty-value";
import type { ArtifactRendererSpec } from "./registry";
import { MONO, sharedStyles } from "./styles";

const s = stylex.create({
  markdown: {
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.65,
    overflowWrap: "anywhere",
  },
  markdownHeading1: {
    marginTop: "2px",
    marginBottom: "9px",
    color: tokens.colorTextEmphasis,
    fontSize: "15px",
    fontWeight: 700,
    lineHeight: 1.3,
  },
  markdownHeading2: {
    marginTop: "14px",
    marginBottom: "7px",
    color: tokens.colorTextEmphasis,
    fontSize: "13px",
    fontWeight: 700,
    lineHeight: 1.35,
  },
  markdownHeading3: {
    marginTop: "12px",
    marginBottom: "6px",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 700,
    lineHeight: 1.4,
  },
  markdownParagraph: {
    marginTop: 0,
    marginBottom: "9px",
  },
  markdownList: {
    marginTop: 0,
    marginBottom: "9px",
    paddingLeft: "18px",
  },
  markdownListItem: { marginBottom: "3px" },
  markdownBlockquote: {
    marginTop: "9px",
    marginRight: 0,
    marginBottom: "9px",
    marginLeft: 0,
    paddingLeft: "10px",
    borderLeftWidth: 2,
    borderLeftStyle: "solid",
    borderLeftColor: tokens.colorAccentBorder,
    color: tokens.colorMuted,
  },
  markdownCode: {
    fontFamily: MONO,
    fontSize: "10px",
  },
  markdownInlineCode: {
    paddingTop: "1px",
    paddingRight: "4px",
    paddingBottom: "1px",
    paddingLeft: "4px",
    borderRadius: "4px",
    backgroundColor: tokens.colorSurfaceSunken,
  },
  markdownPre: {
    marginTop: "9px",
    marginBottom: "9px",
    padding: "9px 10px",
    overflowX: "auto",
    borderRadius: "6px",
    backgroundColor: tokens.colorSurfaceSunken,
    lineHeight: 1.55,
    whiteSpace: "pre",
  },
  markdownLink: {
    color: tokens.colorAccent,
    textDecorationLine: "underline",
    textUnderlineOffset: "2px",
  },
  markdownRule: {
    height: 1,
    marginTop: "12px",
    marginBottom: "12px",
    borderWidth: 0,
    backgroundColor: tokens.colorDivider,
  },
  markdownTable: {
    display: "block",
    width: "100%",
    marginTop: "9px",
    marginBottom: "9px",
    overflowX: "auto",
    borderCollapse: "collapse",
    fontSize: tokens.fontSizeXs,
  },
  markdownTableCell: {
    padding: "5px 7px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    textAlign: "left",
    verticalAlign: "top",
  },
  markdownTableHeader: {
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorTextEmphasis,
    fontWeight: 700,
  },
  markdownImageReference: {
    display: "flex",
    alignItems: "baseline",
    flexWrap: "wrap",
    gap: "6px",
    marginTop: "9px",
    marginBottom: "9px",
    padding: "6px 8px",
    borderRadius: "6px",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
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
  children,
  className,
  ...props
}: React.ComponentPropsWithoutRef<"code">) {
  const block = Boolean(className) || String(children).includes("\n");
  return (
    <code
      {...props}
      className={className}
      {...stylex.props(s.markdownCode, block ? null : s.markdownInlineCode)}
    >
      {children}
    </code>
  );
}

function MarkdownLink({
  children,
  href,
  ...props
}: React.ComponentPropsWithoutRef<"a">) {
  const safeHref = safeMarkdownUrl(href);
  return (
    <a
      {...props}
      href={safeHref ?? undefined}
      target="_blank"
      rel="noreferrer noopener"
      {...stylex.props(s.markdownLink)}
    >
      {children}
    </a>
  );
}

function MarkdownImageReference({
  alt,
  src,
  title,
}: React.ComponentPropsWithoutRef<"img">) {
  const safeSource = safeMarkdownUrl(typeof src === "string" ? src : undefined);
  return (
    <span {...stylex.props(s.markdownImageReference)}>
      <span>Image: {alt || "untitled"}</span>
      {safeSource ? (
        <a
          href={safeSource}
          title={title}
          target="_blank"
          rel="noreferrer noopener"
          {...stylex.props(s.markdownLink)}
        >
          open source
        </a>
      ) : null}
    </span>
  );
}

const markdownOptions: MarkdownToJSX.Options = {
  disableParsingRawHTML: true,
  enforceAtxHeadings: true,
  sanitizer: (value) => safeMarkdownUrl(value),
  wrapper: React.Fragment,
  overrides: {
    h1: { component: "h1", props: stylex.props(s.markdownHeading1) },
    h2: { component: "h2", props: stylex.props(s.markdownHeading2) },
    h3: { component: "h3", props: stylex.props(s.markdownHeading3) },
    h4: { component: "h4", props: stylex.props(s.markdownHeading3) },
    h5: { component: "h5", props: stylex.props(s.markdownHeading3) },
    h6: { component: "h6", props: stylex.props(s.markdownHeading3) },
    p: { component: "p", props: stylex.props(s.markdownParagraph) },
    ul: { component: "ul", props: stylex.props(s.markdownList) },
    ol: { component: "ol", props: stylex.props(s.markdownList) },
    li: { component: "li", props: stylex.props(s.markdownListItem) },
    blockquote: {
      component: "blockquote",
      props: stylex.props(s.markdownBlockquote),
    },
    code: MarkdownCode,
    pre: { component: "pre", props: stylex.props(s.markdownPre) },
    a: MarkdownLink,
    hr: { component: "hr", props: stylex.props(s.markdownRule) },
    table: { component: "table", props: stylex.props(s.markdownTable) },
    th: {
      component: "th",
      props: stylex.props(s.markdownTableCell, s.markdownTableHeader),
    },
    td: { component: "td", props: stylex.props(s.markdownTableCell) },
    img: MarkdownImageReference,
  },
};

export const markdownRenderer: ArtifactRendererSpec = {
  id: "markdown",
  modes: ["preview", "raw"],
  matches: (artifact) =>
    artifact.artifact_type === "text.markdown" && artifact.schema_version === 1,
  Component: ({ artifact, payload, mode }) => {
    const markdown = markdownPayload(payload)?.markdown ?? artifact.text;
    if (markdown === undefined || markdown === null) {
      return <PrettyValue value={payload ?? artifactMeta(artifact)} />;
    }
    if (mode === "raw") {
      return <pre {...stylex.props(sharedStyles.jsonCode)}>{markdown}</pre>;
    }
    return (
      <div {...stylex.props(s.markdown)}>
        <Markdown options={markdownOptions}>{markdown}</Markdown>
      </div>
    );
  },
};

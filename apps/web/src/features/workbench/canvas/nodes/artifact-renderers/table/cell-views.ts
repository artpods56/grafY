/**
 * The ways one table cell's full value can be read. A cell is stored as plain
 * text whatever it holds, so which readings make sense is decided from the value.
 */
export type CellView = "text" | "markdown" | "json" | "html";

const HTML_TABLE = /<table[\s>][\s\S]*<\/table\s*>/i;
const WHOLE_HTML_TABLE = /^\s*<table[\s>][\s\S]*<\/table\s*>\s*$/i;
/** Opens on a tag and closes on one: a document, not prose that mentions a tag. */
const HTML_DOCUMENT =
  /^\s*<(?:!doctype\s|!--|[a-z][a-z0-9-]*[\s/>])[\s\S]*>\s*$/i;

/** A table and nothing else, which can be drawn without a frame. */
export function isWholeHtmlTable(value: string): boolean {
  return (
    WHOLE_HTML_TABLE.test(value) &&
    value.search(/<\/table\s*>/i) === value.lastIndexOf("</table") &&
    (value.match(/<table[\s>]/gi) ?? []).length === 1
  );
}

/**
 * A whole document for a sandboxed frame. The frame runs no scripts, and the policy
 * comes first so nothing written after it can load anything from the network, which
 * would otherwise tell a third party who opened this and when. The sandbox does not
 * stop the frame from navigating itself, so remote links and base elements are
 * removed before this HTML is placed here. The rest only lets the words sit on the
 * card in the page's colours, until the HTML says otherwise.
 */
export function htmlFrameDocument(
  html: string,
  theme: { color: string; colorScheme: string },
): string {
  return `<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:"><style>
:root { color-scheme: ${theme.colorScheme}; }
body { margin: 8px; background: transparent; color: ${theme.color}; font: 12px/1.45 system-ui, sans-serif; }
</style>${html}`;
}

function parsedJson(value: string): object | null {
  const start = value.trimStart()[0];
  if (start !== "{" && start !== "[") return null;
  try {
    return JSON.parse(value) as object;
  } catch {
    return null;
  }
}

/** The views `value` offers, the plain text always first. */
export function cellViews(value: unknown): readonly CellView[] {
  if (typeof value !== "string") {
    return typeof value === "object" && value !== null
      ? ["text", "json"]
      : ["text"];
  }
  return [
    "text",
    "markdown",
    ...(parsedJson(value) ? (["json"] as const) : []),
    ...(HTML_TABLE.test(value) || HTML_DOCUMENT.test(value)
      ? (["html"] as const)
      : []),
  ];
}

/** The value indented for reading, or null when it is not a JSON object or array. */
export function prettyCellJson(value: unknown): string | null {
  const parsed = typeof value === "string" ? parsedJson(value) : value;
  return typeof parsed === "object" && parsed !== null
    ? JSON.stringify(parsed, null, 2)
    : null;
}

/** What a person calls each view. */
export const CELL_VIEW_LABEL: Record<CellView, string> = {
  text: "Text",
  markdown: "Markdown",
  json: "JSON",
  html: "HTML",
};

/**
 * The views a text artifact's card offers. JSON is already indented as text, so it
 * has nothing to switch to; everything else may be read as Markdown or a table.
 */
export function textCardViews(text: string): readonly CellView[] {
  const views = cellViews(text);
  return views.includes("json") ? [] : views;
}

/** What a card opens on: HTML it plainly holds, or what the artifact says it is. */
export function defaultTextCardView(
  views: readonly CellView[],
  artifactType: string | undefined,
): CellView {
  if (views.includes("html")) return "html";
  if (artifactType === "text.markdown" && views.includes("markdown"))
    return "markdown";
  return "text";
}

/**
 * The ways one table cell's full value can be read. A cell is stored as plain
 * text whatever it holds, so which readings make sense is decided from the value.
 */
export type CellView = "text" | "markdown" | "json" | "html";

const HTML_TABLE = /<table[\s>][\s\S]*<\/table\s*>/i;

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
    ...(HTML_TABLE.test(value) ? (["html"] as const) : []),
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
  html: "Table",
};

/**
 * The views a text artifact's card offers. JSON is already indented as text, so it
 * has nothing to switch to; everything else may be read as Markdown or a table.
 */
export function textCardViews(text: string): readonly CellView[] {
  const views = cellViews(text);
  return views.includes("json") ? [] : views;
}

/** What a card opens on: what the artifact says it is, or a table it plainly holds. */
export function defaultTextCardView(
  views: readonly CellView[],
  artifactType: string | undefined,
): CellView {
  if (views.includes("html")) return "html";
  if (artifactType === "text.markdown" && views.includes("markdown"))
    return "markdown";
  return "text";
}

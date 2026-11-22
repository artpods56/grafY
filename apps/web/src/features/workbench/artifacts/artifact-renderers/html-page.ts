import Mustache from "mustache";
import useSWR from "swr";

import {
  artifactInlineContentUrl,
  getArtifactTablePage,
  getArtifactTableSchema,
  type TablePage,
} from "@/lib/api";

import { readTextHead } from "./text-head";

/**
 * A page and each source are read whole. Past this the card says the artifact
 * could not be read, rather than filling the template with a cut-off value.
 */
export const HTML_PAGE_BYTE_LIMIT = 2 * 1024 * 1024;

/**
 * `GET .../table/page` rejects a `limit` above 100 (OpenAPI maximum). The
 * first page is as large as that route allows.
 */
export const HTML_PAGE_TABLE_ROW_LIMIT = 100;

/** `column_ids` and `column_limit` both stop at 100. */
const TABLE_COLUMN_LIMIT = 100;
/** The route rejects a preview over this many characters. */
const TABLE_PREVIEW_CHARACTER_BUDGET = 2_000_000;
const TABLE_CELL_CHARACTERS_MAX = 2000;
const TABLE_CELL_CHARACTERS_MIN = 32;
/** With no column ids the route falls back to its default column window. */
const TABLE_DEFAULT_COLUMN_WINDOW = 25;

const HTML_PAGE_SWR = {
  revalidateIfStale: false,
  revalidateOnFocus: false,
  revalidateOnReconnect: false,
} as const;

export interface HtmlPageSourceRef {
  readonly artifact_id: string;
  readonly artifact_type: string;
  readonly schema_version: number;
}

export interface NamedSource {
  readonly name: string;
  readonly ref: HtmlPageSourceRef;
}

export interface HtmlPageDocument {
  readonly html: string;
  readonly sources: readonly NamedSource[];
}

export type WholeText =
  | { readonly kind: "text"; readonly text: string }
  | { readonly kind: "truncated" }
  | { readonly kind: "unreadable" };

export type SourceFetch =
  | { readonly kind: "text"; readonly text: WholeText }
  | { readonly kind: "table"; readonly page: TablePage }
  | { readonly kind: "failed" };

export interface SourceFailure {
  readonly name: string;
  readonly message: string;
}

export type HtmlPageLoad =
  | {
      readonly status: "ready";
      readonly template: string;
      readonly rendered: string;
      readonly sourceNames: readonly string[];
      readonly shortfalls: readonly string[];
    }
  | {
      readonly status: "sources";
      readonly template: string;
      readonly sourceNames: readonly string[];
      readonly failures: readonly SourceFailure[];
    }
  | {
      readonly status: "template";
      readonly template: string;
      readonly sourceNames: readonly string[];
      readonly message: string;
      readonly shortfalls: readonly string[];
    }
  | { readonly status: "unreadable"; readonly message: string };

const PAGE_UNREADABLE = "This page could not be read";

export function isHtmlPageArtifact(
  ref: { artifact_type: string; schema_version: number } | null,
): boolean {
  return (
    ref !== null &&
    ref.artifact_type === "html.page" &&
    ref.schema_version === 1
  );
}

export function sourceFailure(name: string): SourceFailure {
  return { name, message: `${name} could not be read` };
}

/** `total` rows exist and this page is only the first slice the route will give. */
export function tableShortfall(
  name: string,
  shown: number,
  total: number,
): string | null {
  if (total <= shown) return null;
  return `showing ${shown.toLocaleString("en-US")} of ${total.toLocaleString("en-US")} rows of ${name}`;
}

export function rowsFromTablePage(
  page: TablePage,
): Record<string, string | number | boolean | null>[] {
  return page.rows.map((row) =>
    Object.fromEntries(
      Object.entries(row).map(([columnId, cell]) => [columnId, cell.display]),
    ),
  );
}

/**
 * Mustache's own escaping stays on, and there are no partials: a page can
 * only print the values it was handed.
 */
export function renderHtmlPage(
  html: string,
  view: Record<string, unknown>,
): { ok: true; html: string } | { ok: false; message: string } {
  try {
    return { ok: true, html: Mustache.render(html, view) };
  } catch (error) {
    return {
      ok: false,
      message:
        error instanceof Error
          ? error.message
          : "This template could not be rendered",
    };
  }
}

export function parseHtmlPage(text: string): HtmlPageDocument {
  const value: unknown = JSON.parse(text);
  if (!isRecord(value) || typeof value.html !== "string") {
    throw new Error(PAGE_UNREADABLE);
  }
  if (!isRecord(value.sources)) throw new Error(PAGE_UNREADABLE);
  const sources = Object.entries(value.sources).map(([name, ref]) => {
    if (!isSourceRef(ref)) throw new Error(PAGE_UNREADABLE);
    return { name, ref };
  });
  return { html: value.html, sources };
}

/**
 * One page from bytes already in hand. `read` is how each source arrives, so
 * a test can hand back a truncation or a table page without the network.
 * Sources are asked for together. One failure does not drop the rest.
 */
export async function assembleHtmlPage(
  pageText: WholeText,
  read: (source: NamedSource) => Promise<SourceFetch>,
): Promise<HtmlPageLoad> {
  if (pageText.kind !== "text") {
    return { status: "unreadable", message: PAGE_UNREADABLE };
  }
  let document: HtmlPageDocument;
  try {
    document = parseHtmlPage(pageText.text);
  } catch {
    return { status: "unreadable", message: PAGE_UNREADABLE };
  }
  const sourceNames = document.sources.map((source) => source.name);
  const fetched = await Promise.all(
    document.sources.map((source) =>
      read(source).then(
        (result) => ({ source, result }),
        () => ({ source, result: { kind: "failed" } as const }),
      ),
    ),
  );
  const failures: SourceFailure[] = [];
  const view: Record<string, unknown> = {};
  const shortfalls: string[] = [];
  for (const { source, result } of fetched) {
    const interpreted = interpretSource(source, result);
    if (!interpreted.ok) {
      failures.push(interpreted.failure);
      continue;
    }
    view[source.name] = interpreted.value;
    if (interpreted.shortfall) shortfalls.push(interpreted.shortfall);
  }
  if (failures.length > 0) {
    return {
      status: "sources",
      template: document.html,
      sourceNames,
      failures,
    };
  }
  const rendered = renderHtmlPage(document.html, view);
  if (!rendered.ok) {
    return {
      status: "template",
      template: document.html,
      sourceNames,
      message: rendered.message,
      shortfalls,
    };
  }
  return {
    status: "ready",
    template: document.html,
    rendered: rendered.html,
    sourceNames,
    shortfalls,
  };
}

export async function readWholeText(url: string): Promise<WholeText> {
  try {
    const head = await readTextHead(url, HTML_PAGE_BYTE_LIMIT);
    if (!head) return { kind: "unreadable" };
    if (head.truncated) return { kind: "truncated" };
    return { kind: "text", text: head.text };
  } catch {
    return { kind: "unreadable" };
  }
}

export async function loadHtmlPage(
  workspaceId: string,
  artifactId: string,
): Promise<HtmlPageLoad> {
  const pageText = await readWholeText(
    artifactInlineContentUrl(workspaceId, artifactId),
  );
  return assembleHtmlPage(pageText, (source) =>
    fetchSource(workspaceId, source.ref),
  );
}

/**
 * The page and its sources are immutable, so a second card must not ask again. What
 * could not be read may read next time, so that outcome can be asked for again.
 */
export function useHtmlPage(workspaceId: string, artifactId: string | null) {
  return useSWR(
    artifactId === null
      ? null
      : (["html-page", workspaceId, artifactId] as const),
    ([, workspace, id]) => loadHtmlPage(workspace, id),
    HTML_PAGE_SWR,
  );
}

function interpretSource(
  source: NamedSource,
  result: SourceFetch,
):
  | { ok: true; value: unknown; shortfall: string | null }
  | { ok: false; failure: SourceFailure } {
  try {
    if (source.ref.artifact_type.startsWith("table.")) {
      if (result.kind !== "table") {
        return { ok: false, failure: sourceFailure(source.name) };
      }
      const rows = rowsFromTablePage(result.page);
      return {
        ok: true,
        value: rows,
        shortfall: [
          tableShortfall(source.name, rows.length, result.page.total_rows),
          result.page.rows.some((row) =>
            Object.values(row).some((cell) => cell.truncated),
          )
            ? `some cells of ${source.name} are cut short`
            : null,
        ]
          .filter((line) => line !== null)
          .join("; "),
      };
    }
    if (result.kind !== "text" || result.text.kind !== "text") {
      return { ok: false, failure: sourceFailure(source.name) };
    }
    const text = result.text.text;
    if (source.ref.artifact_type === "scalar.text") {
      return { ok: true, value: scalarField(text, "value"), shortfall: null };
    }
    if (source.ref.artifact_type === "text.markdown") {
      return {
        ok: true,
        value: scalarField(text, "markdown"),
        shortfall: null,
      };
    }
    return { ok: true, value: parsedJson(text), shortfall: null };
  } catch {
    return { ok: false, failure: sourceFailure(source.name) };
  }
}

function scalarField(text: string, field: "value" | "markdown"): string {
  const value = parsedJson(text);
  if (!isRecord(value) || typeof value[field] !== "string") {
    throw new Error("not text");
  }
  return value[field];
}

function parsedJson(text: string): unknown {
  const value: unknown = JSON.parse(text);
  return value;
}

async function fetchSource(
  workspaceId: string,
  ref: HtmlPageSourceRef,
): Promise<SourceFetch> {
  try {
    if (ref.artifact_type.startsWith("table.")) {
      return {
        kind: "table",
        page: await fetchTablePage(workspaceId, ref.artifact_id),
      };
    }
    return {
      kind: "text",
      text: await readWholeText(
        artifactInlineContentUrl(workspaceId, ref.artifact_id),
      ),
    };
  } catch {
    return { kind: "failed" };
  }
}

async function fetchTablePage(
  workspaceId: string,
  artifactId: string,
): Promise<TablePage> {
  const schema = await getArtifactTableSchema(workspaceId, artifactId);
  const columnIds = schema.columns
    .slice(0, TABLE_COLUMN_LIMIT)
    .map((column) => column.id);
  return getArtifactTablePage(
    workspaceId,
    artifactId,
    0,
    HTML_PAGE_TABLE_ROW_LIMIT,
    columnIds,
    cellCharacterLimit(columnIds.length),
  );
}

function cellCharacterLimit(columnCount: number): number {
  const columns = columnCount > 0 ? columnCount : TABLE_DEFAULT_COLUMN_WINDOW;
  const budget = Math.floor(
    TABLE_PREVIEW_CHARACTER_BUDGET / (HTML_PAGE_TABLE_ROW_LIMIT * columns),
  );
  return Math.min(
    TABLE_CELL_CHARACTERS_MAX,
    Math.max(TABLE_CELL_CHARACTERS_MIN, budget),
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSourceRef(value: unknown): value is HtmlPageSourceRef {
  if (!isRecord(value)) return false;
  return (
    typeof value.artifact_id === "string" &&
    value.artifact_id.length > 0 &&
    typeof value.artifact_type === "string" &&
    value.artifact_type.length > 0 &&
    typeof value.schema_version === "number" &&
    Number.isInteger(value.schema_version)
  );
}

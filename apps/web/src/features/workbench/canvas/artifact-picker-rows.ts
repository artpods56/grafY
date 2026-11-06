import type { TableSchema } from "@/lib/api";

/** The most nested rows one list offers. */
export const PICKER_ROW_LIMIT = 100;

type Column = TableSchema["columns"][number];

/**
 * Which columns a table's rows are picked by: the one a dragged row carries, and a
 * shorter one that tells rows apart. A column named `text` is the row's text by
 * convention (an OCR block's, say); otherwise it is the first text column.
 */
export function pickerColumns(
  columns: readonly Column[],
): { content: Column; label: Column | null } | null {
  const texts = columns.filter((column) => column.value_type === "text");
  const content = texts.find((column) => column.id === "text") ?? texts[0];
  if (!content) return null;
  return {
    content,
    label: texts.find((column) => column !== content) ?? null,
  };
}

/** One line of a cell for a list: without markup, without runs of space. */
export function pickerPreview(value: unknown): string {
  if (typeof value !== "string") return "";
  return value
    .replace(/<[^>]*>?/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

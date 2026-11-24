import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  schemaFields,
  type ConfigValidationIssue,
  type SchemaField,
} from "../../config-ui/config-schema";
import { countConfigShelfCells } from "../cell-card-geometry";
import {
  ADVANCED_SECTION_KEY,
  ADVANCED_TOGGLE_ID,
  advancedGroupIndices,
  buildSchemaConfigEntries,
} from "../cell-config-plan";
import type { CellConfigFieldSpec } from "../cell-contracts";
import { CellConfigBand } from "./CellConfigFields";

/**
 * The `Advanced` disclosure of a config band: where its row sits, what it
 * heads, and how the fields it discloses line up. The shape is the one the
 * OCR nodes draw — two labelled selects with a checkbox beside each, so a
 * boolean is always the short half of a shelf.
 */

const ocrFields: SchemaField[] = schemaFields({
  type: "object",
  properties: {
    document: { type: "string", title: "Document" },
    prompt: { type: "string", title: "Prompt" },
    table_format: {
      type: "string",
      title: "Table format",
      enum: ["markdown", "html"],
      "x-grafy-advanced": true,
    },
    extract_header: {
      type: "boolean",
      title: "Separate headers",
      default: false,
      "x-grafy-advanced": true,
    },
    extract_footer: {
      type: "boolean",
      title: "Separate footers",
      default: false,
      "x-grafy-advanced": true,
    },
    confidence: {
      type: "string",
      title: "Confidence detail",
      enum: ["page", "block"],
      "x-grafy-advanced": true,
    },
  },
});

/** The same node with one advanced field carried by a named group. */
const groupedFields: SchemaField[] = schemaFields({
  type: "object",
  properties: {
    document: { type: "string", title: "Document" },
    language: {
      type: "string",
      title: "Language",
      default: "ru",
      "x-grafy-advanced": true,
      "x-grafy-group": "Recognition",
    },
    dictionary: {
      type: "string",
      title: "Dictionary",
      "x-grafy-group": "Recognition",
    },
    confidence: {
      type: "string",
      title: "Confidence detail",
      enum: ["page", "block"],
      "x-grafy-advanced": true,
    },
  },
});

function entries(
  config: Record<string, unknown>,
  options: { open?: boolean; issues?: readonly ConfigValidationIssue[] } = {},
): CellConfigFieldSpec[] {
  return buildSchemaConfigEntries({
    fields: ocrFields,
    config,
    issues: options.issues ?? [],
    sections: options.open ? { [ADVANCED_SECTION_KEY]: true } : undefined,
  });
}

function ids(list: readonly CellConfigFieldSpec[]): string[] {
  return list.map((entry) => entry.id);
}

function draw(fields: readonly CellConfigFieldSpec[]): string {
  return renderToStaticMarkup(
    <CellConfigBand
      fields={fields}
      style={{}}
      onChange={() => {}}
      onToggleSection={() => {}}
    />,
  );
}

/** One cell of a drawn band: its opening tag, with the placement styles. */
function cell(html: string, id: string): string {
  const start = html.indexOf(`data-config-field="${id}"`);
  expect(start, `no cell for ${id}`).toBeGreaterThan(-1);
  return html.slice(start, html.indexOf(">", start));
}

function rowSpan(style: string): [number, number] {
  const match = /grid-row:(\d+) \/ span (\d+)/.exec(style);
  expect(match, "no grid-row").not.toBeNull();
  return [Number(match?.[1]), Number(match?.[2])];
}

describe("the config band's advanced disclosure", () => {
  it("heads its fields in both states", () => {
    const closed = entries({});
    const open = entries({}, { open: true });

    // Closed, only the untouched fields fold away; the row that heads them
    // stays where it was, so nothing jumps when the section opens.
    expect(ids(closed)).toEqual(["document", "prompt", ":advanced"]);
    expect(ids(open)).toEqual([
      "document",
      "prompt",
      ":advanced",
      "table_format",
      "extract_header",
      "extract_footer",
      "confidence",
    ]);
    for (const list of [closed, open]) {
      expect(list[2]).toMatchObject({
        id: ":advanced",
        kind: "advanced",
        span: 2,
        denseRows: 1,
        section: { key: ADVANCED_SECTION_KEY, count: 4 },
      });
    }
    expect(closed[2]?.section?.open).toBe(false);
    expect(open[2]?.section?.open).toBe(true);
    // Every entry after the row, and none before it, is the section's.
    expect(advancedGroupIndices(closed)).toEqual([]);
    expect(advancedGroupIndices(open)).toEqual([3, 4, 5, 6]);
  });

  it("titles the row after the section and lets `aria-expanded` say the state", () => {
    const closed = draw(entries({}));
    const open = draw(entries({}, { open: true }));

    for (const html of [closed, open]) {
      expect(html).toContain(`data-config-section="${ADVANCED_SECTION_KEY}"`);
      expect(html).toContain(">Advanced<");
      expect(html).not.toContain(">Hide advanced<");
    }
    expect(closed).toContain('aria-expanded="false"');
    expect(open).toContain('aria-expanded="true"');
  });

  it("shows an advanced field the person changed under the closed row", () => {
    const customized = entries({ extract_header: true });
    expect(ids(customized)).toContain("extract_header");
    expect(ids(customized)).not.toContain("extract_footer");
    expect(customized[2]?.section).toMatchObject({ open: false, count: 3 });
    expect(advancedGroupIndices(customized)).toEqual([3]);

    const html = draw(customized);
    const band = html.slice(html.indexOf("data-config-band"));
    expect(band.indexOf('data-config-field="extract_header"')).toBeGreaterThan(
      band.indexOf(`data-config-field="${ADVANCED_TOGGLE_ID}"`),
    );
  });

  it("keeps an advanced field validation rejects in view", () => {
    const rejected = entries(
      { table_format: "pdf" },
      {
        issues: [
          { fieldName: "table_format", message: "Choose a table format" },
        ],
      },
    );
    expect(ids(rejected)).toContain("table_format");
    expect(rejected[2]?.section).toMatchObject({ open: false, count: 3 });
    // Its issue is drawn by the field itself, not repeated by the row.
    expect(rejected[2]?.section?.issueCount).toBe(0);
    expect(rejected.find(({ id }) => id === "table_format")?.issue).toBe(
      "Choose a table format",
    );
  });

  it("draws the tray of disclosed fields under its row and nothing else", () => {
    const open = entries({}, { open: true });
    const html = draw(open);

    const toggle = html.indexOf(`data-config-field="${ADVANCED_TOGGLE_ID}"`);
    const tray = html.indexOf(
      `data-config-advanced-group="${ADVANCED_SECTION_KEY}"`,
    );
    expect(toggle).toBeGreaterThan(-1);
    expect(tray).toBeGreaterThan(toggle);
    expect(html.indexOf('data-config-field="document"')).toBeLessThan(toggle);

    // The tray holds the rows counted for the fold, no more and no less, so
    // the plate the card was sized for is exactly full.
    const rows = countConfigShelfCells(open);
    const [first, span] = rowSpan(html.slice(tray, html.indexOf(">", tray)));
    const [toggleRow] = rowSpan(cell(html, ADVANCED_TOGGLE_ID));
    expect(first).toBe(toggleRow + 1);
    expect(first + span - 1).toBe(rows);

    // Closed, the row is the band's last thing: no frame, no stray divider.
    const closed = draw(entries({}));
    expect(closed).not.toContain("data-config-advanced-group");
    expect(closed.slice(closed.lastIndexOf('data-config-field="'))).toContain(
      `data-config-field="${ADVANCED_TOGGLE_ID}"`,
    );
  });

  it("stands a checkbox on the row its shelf-mate's control sits on", () => {
    const html = draw(entries({}, { open: true }));
    const checkbox = cell(html, "extract_header");
    const select = cell(html, "table_format");

    // Both take the whole 2-row shelf; only the short one is brought down to
    // the control line, by the 5px a centred labelled block keeps under it.
    expect(rowSpan(select)).toEqual([1, 2]);
    expect(rowSpan(checkbox)).toEqual([1, 2]);
    expect(select).not.toContain("cellOnShelfBottom");
    expect(checkbox).toContain("cellOnShelfBottom");
    expect(checkbox).toContain("padding-bottom:5px");
  });

  it("leaves a named group's own advanced fields to that group", () => {
    const closed = buildSchemaConfigEntries({
      fields: groupedFields,
      config: {},
    });

    // The row counts the fields its fold can hold, so a quiet field a group
    // carries stays inside the group rather than being counted and hidden.
    expect(ids(closed)).toEqual([
      "document",
      "group:Recognition",
      "language",
      "dictionary",
      ":advanced",
    ]);
    expect(closed[1]?.section).toMatchObject({ count: 2 });
    expect(closed[4]?.section).toMatchObject({
      key: ADVANCED_SECTION_KEY,
      count: 1,
    });
    // Closed, the row discloses nothing: the group already shows its own field.
    expect(advancedGroupIndices(closed)).toEqual([]);
  });

  it("pairs two changed checkboxes on one shelf of their own", () => {
    const customized = entries({ extract_header: true, extract_footer: true });
    expect(ids(customized)).toEqual([
      "document",
      "prompt",
      ":advanced",
      "extract_header",
      "extract_footer",
    ]);
    expect(customized[2]?.section).toMatchObject({ open: false, count: 2 });

    const html = draw(customized);
    // Equal partners fill their shelf evenly: neither is pulled off centre.
    // Both are counted on the tray's own lattice, from its first row.
    expect(rowSpan(cell(html, "extract_header"))).toEqual([1, 1]);
    expect(cell(html, "extract_header")).not.toContain("cellOnShelfBottom");
    expect(cell(html, "extract_footer")).not.toContain("cellOnShelfBottom");

    // The tray holds exactly the row they fill, which is the row the card was
    // sized for: no clipped bottom row, no dead space under the last control.
    const tray = html.indexOf(
      `data-config-advanced-group="${ADVANCED_SECTION_KEY}"`,
    );
    expect(rowSpan(html.slice(tray, html.indexOf(">", tray)))).toEqual([4, 1]);
    expect(countConfigShelfCells(customized)).toBe(4);
  });
});

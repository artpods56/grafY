"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Popover } from "@base-ui/react/popover";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Columns3,
} from "lucide-react";
import Markdown, {
  type MarkdownToJSX,
  sanitizer as sanitizeMarkdownUrl,
} from "markdown-to-jsx";
import useSWR from "swr";

import {
  artifactContentUrl,
  getArtifactTableCell,
  getArtifactTablePage,
  getArtifactTableSchema,
  queryArtifactTablePage,
  type ArtifactSummary,
  type TablePage,
  type TableQueryInput,
  type TableSchema,
} from "@/lib/api";
import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { overlay } from "@/lib/stylex/overlay.stylex";
import {
  interactionScalarFromIntegerEncoding,
  interactionScalarFromTableCell,
  type ArtifactViewerEffect,
  type ArtifactViewerInteractionContext,
} from "../artifact-interactions";
import { GeoMapArtifactRenderer } from "./geo-map-artifact-renderer";

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

const s = stylex.create({
  jsonCode: {
    margin: 0,
    fontFamily: MONO,
    fontSize: "10px",
    lineHeight: 1.55,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  },
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
  image: {
    display: "block",
    width: "100%",
    borderRadius: "8px",
    backgroundColor: tokens.colorSurface,
  },
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
  tablePreview: {
    display: "grid",
    gap: "6px",
    minWidth: 0,
  },
  tableSummary: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "10px",
    color: tokens.colorMuted,
    fontSize: "10px",
  },
  tableSummaryMeta: {
    display: "inline-flex",
    alignItems: "center",
    gap: "5px",
    whiteSpace: "nowrap",
  },
  tableSummaryStrong: {
    color: tokens.colorTextEmphasis,
    fontWeight: 700,
  },
  tableSummaryDivider: {
    color: tokens.colorDivider,
  },
  tableToolbarActions: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },
  tableViewport: {
    width: "100%",
    maxHeight: "420px",
    overflow: "auto",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  dataTable: {
    width: "max-content",
    minWidth: "100%",
    borderCollapse: "separate",
    borderSpacing: 0,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
  },
  tableIndexHeader: {
    position: "sticky",
    top: 0,
    left: 0,
    zIndex: 3,
    width: "42px",
    minWidth: "42px",
    padding: "7px 9px",
    borderRightWidth: 1,
    borderRightStyle: "solid",
    borderRightColor: tokens.colorDivider,
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "9px",
    fontWeight: 600,
    textAlign: "right",
  },
  tableHeader: {
    position: "sticky",
    top: 0,
    zIndex: 2,
    minWidth: "132px",
    maxWidth: "300px",
    padding: "7px 10px",
    borderRightWidth: 1,
    borderRightStyle: "solid",
    borderRightColor: tokens.colorDivider,
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    backgroundColor: tokens.colorSurfaceSunken,
    textAlign: "left",
    verticalAlign: "bottom",
  },
  tableHeaderTitle: {
    display: "block",
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontWeight: 700,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  tableHeaderType: {
    display: "block",
    marginTop: "2px",
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "9px",
    fontWeight: 500,
  },
  tableIndexCell: {
    position: "sticky",
    left: 0,
    zIndex: 1,
    width: "42px",
    minWidth: "42px",
    padding: "6px 9px",
    borderRightWidth: 1,
    borderRightStyle: "solid",
    borderRightColor: tokens.colorDivider,
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "9px",
    textAlign: "right",
  },
  tableCell: {
    minWidth: "132px",
    maxWidth: "300px",
    padding: "6px 10px",
    overflow: "hidden",
    borderRightWidth: 1,
    borderRightStyle: "solid",
    borderRightColor: tokens.colorDivider,
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    color: tokens.colorText,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    verticalAlign: "top",
  },
  tableCellSelected: {
    backgroundColor: tokens.colorAccentSoft,
  },
  tableCellHighlighted: {
    backgroundColor: tokens.colorHoverStrong,
  },
  tableRowInteractive: {
    cursor: "pointer",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    outlineStyle: "solid",
    outlineColor: tokens.colorAccent,
    outlineOffset: "-2px",
  },
  tableCellCode: { fontFamily: MONO, fontSize: "10px" },
  tableCellNull: { color: tokens.colorSubtle, fontStyle: "italic" },
  tableEmpty: {
    padding: "28px 14px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    textAlign: "center",
  },
  tableLimit: {
    color: tokens.colorSubtle,
    fontSize: "10px",
  },
  tablePager: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "10px",
    minWidth: 0,
  },
  tablePagerMeta: {
    display: "flex",
    alignItems: "center",
    gap: "9px",
    minWidth: 0,
  },
  tablePagerActions: {
    display: "flex",
    alignItems: "center",
    gap: "3px",
  },
  tablePagerButton: {
    minHeight: "26px",
    paddingInline: "9px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    borderRadius: "6px",
    backgroundColor: tokens.colorSurface,
    color: {
      default: tokens.colorText,
      ":disabled": tokens.colorTextDisabled,
    },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
    fontSize: "10px",
  },
  tablePagerIconButton: {
    width: "26px",
    paddingInline: 0,
    display: "grid",
    placeItems: "center",
  },
  tablePageIndicator: {
    minWidth: "74px",
    color: tokens.colorMuted,
    fontSize: "10px",
    textAlign: "center",
    whiteSpace: "nowrap",
  },
  tablePageSize: {
    height: "26px",
    paddingInline: "6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    borderRadius: "6px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    outlineStyle: "solid",
    outlineColor: tokens.colorAccent,
    outlineOffset: "1px",
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    fontSize: "10px",
  },
  columnPickerTrigger: {
    height: "26px",
    display: "inline-flex",
    alignItems: "center",
    gap: "5px",
    paddingInline: "8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    borderRadius: "6px",
    backgroundColor: {
      default: tokens.colorSurface,
      ":hover": tokens.colorSurfaceMuted,
    },
    color: tokens.colorText,
    cursor: "pointer",
    fontSize: "10px",
  },
  columnPickerCount: {
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "9px",
  },
  columnPickerPositioner: {
    zIndex: 30,
  },
  columnPickerPopup: {
    width: "248px",
    padding: "9px",
    outline: "none",
  },
  columnPickerHeader: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: "8px",
    paddingInline: "3px",
    paddingBottom: "7px",
  },
  columnPickerTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: "10px",
    fontWeight: 750,
  },
  columnPickerHint: {
    color: tokens.colorSubtle,
    fontSize: "9px",
  },
  columnPickerList: {
    maxHeight: "236px",
    display: "grid",
    gap: "2px",
    overflowY: "auto",
    paddingBlock: "2px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  columnPickerOption: {
    display: "grid",
    gridTemplateColumns: "15px minmax(0, 1fr) auto",
    alignItems: "center",
    gap: "7px",
    padding: "6px 4px",
    borderRadius: "5px",
    cursor: "pointer",
    fontSize: "10px",
  },
  columnPickerOptionTitle: {
    overflow: "hidden",
    color: tokens.colorText,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  columnPickerOptionType: {
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "9px",
  },
  columnPickerFooter: {
    display: "flex",
    justifyContent: "space-between",
    gap: "6px",
    paddingTop: "7px",
  },
  columnPickerTextButton: {
    padding: "3px",
    borderWidth: 0,
    backgroundColor: "transparent",
    color: tokens.colorAccent,
    cursor: "pointer",
    fontSize: "9px",
  },
  tableTruncatedCellButton: {
    width: "100%",
    padding: 0,
    overflow: "hidden",
    borderWidth: 0,
    backgroundColor: "transparent",
    color: tokens.colorAccent,
    cursor: "pointer",
    fontFamily: "inherit",
    fontSize: "inherit",
    textAlign: "left",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  tableCellDetail: {
    display: "grid",
    gap: "6px",
    padding: "8px",
    borderRadius: "7px",
    backgroundColor: tokens.colorSurfaceSunken,
  },
  tableCellDetailHeader: {
    display: "flex",
    justifyContent: "space-between",
    gap: "8px",
    color: tokens.colorMuted,
    fontSize: "10px",
  },
  tableCellDetailValue: {
    width: "100%",
    minHeight: "100px",
    resize: "vertical",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    borderRadius: "6px",
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    fontFamily: MONO,
    fontSize: "10px",
  },
  tableDownload: {
    color: tokens.colorAccent,
    fontSize: "10px",
    textDecorationLine: "none",
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

export interface ArtifactRenderProps {
  artifact: ArtifactSummary;
  payload?: unknown;
  mode: string;
  availableHeight?: number;
  interaction?: ArtifactViewerInteractionContext;
}

export interface ArtifactRendererInteractionCapabilities {
  emits: readonly "key-selection"[];
  accepts: readonly ArtifactViewerEffect[];
}

export interface ArtifactRendererSpec {
  id: string;
  modes: readonly string[];
  interaction?: ArtifactRendererInteractionCapabilities;
  matches(artifact: ArtifactSummary, payload?: unknown): boolean;
  Component: React.ComponentType<ArtifactRenderProps>;
}

function record(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

export function formatJsonSchemaPayload(payload: unknown): string | null {
  const schemaText = record(payload)?.value;
  if (typeof schemaText !== "string") return null;

  try {
    const schema: unknown = JSON.parse(schemaText);
    if (record(schema) === null) return null;
    return JSON.stringify(schema, null, 2);
  } catch {
    return null;
  }
}

export interface MarkdownArtifactPayload {
  markdown: string;
}

export function markdownPayload(
  payload: unknown,
): MarkdownArtifactPayload | null {
  const markdown = record(payload)?.markdown;
  return typeof markdown === "string" ? { markdown } : null;
}

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

function artifactMeta(artifact: ArtifactSummary): Record<string, unknown> {
  return {
    type: `${artifact.artifact_type}@${artifact.schema_version}`,
    content_type: artifact.content_type,
    ...(artifact.byte_size != null ? { byte_size: artifact.byte_size } : {}),
    ...(artifact.text ? { text: artifact.text } : {}),
    artifact_id: artifact.artifact_id,
  };
}

const imageRenderer: ArtifactRendererSpec = {
  id: "image",
  modes: ["preview", "meta"],
  matches: (artifact) =>
    artifact.content_type.startsWith("image/") && Boolean(artifact.content_url),
  Component: ({ artifact, mode }) => {
    const { workspace } = useWorkspaceContext();
    if (mode === "meta") {
      return <PrettyValue value={artifactMeta(artifact)} />;
    }
    const url =
      artifactContentUrl(workspace.id, artifact.content_url) ??
      artifact.content_url ??
      "";
    return (
      /* eslint-disable-next-line @next/next/no-img-element -- artifact URLs are dynamic */
      <img
        src={url}
        alt={artifact.text ?? artifact.artifact_type}
        {...stylex.props(s.image)}
      />
    );
  },
};

const geoMapRenderer: ArtifactRendererSpec = {
  id: "geo-map",
  modes: ["map", "raw"],
  interaction: {
    emits: ["key-selection"],
    accepts: ["filter", "highlight", "focus"],
  },
  matches: (artifact) =>
    [
      "geo.feature_collection",
      "geo.raster_scan",
      "geo.map_layer",
      "geo.map_document",
    ].includes(artifact.artifact_type) && artifact.schema_version === 1,
  Component: GeoMapArtifactRenderer,
};

const DEFAULT_TABLE_PAGE_SIZE = 50;
const DEFAULT_VISIBLE_COLUMN_COUNT = 6;
const MAX_VISIBLE_COLUMN_COUNT = 100;
const TABLE_CELL_PREVIEW_CHARACTERS = 256;
const TABLE_SELECTION_ACTIVITY_DELAY_MS = 200;

function tableCellText(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return "[unavailable value]";
  }
}

interface TableCellSelection {
  rowIndex: number;
  columnId: string;
  columnTitle: string;
}

function TableColumnPicker({
  columns,
  visibleColumnIds,
  onVisibleColumnIdsChange,
}: {
  columns: TableSchema["columns"];
  visibleColumnIds: readonly string[];
  onVisibleColumnIdsChange: (columnIds: readonly string[]) => void;
}) {
  const visibleColumnIdSet = new Set(visibleColumnIds);
  return (
    <Popover.Root>
      <Popover.Trigger
        type="button"
        aria-label="Choose visible table columns"
        title="Choose visible columns"
        {...stylex.props(s.columnPickerTrigger)}
      >
        <Columns3 size={12} aria-hidden="true" />
        Columns
        <span {...stylex.props(s.columnPickerCount)}>
          {visibleColumnIds.length}/{columns.length}
        </span>
        <ChevronDown size={11} aria-hidden="true" />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner
          side="bottom"
          align="end"
          sideOffset={6}
          {...stylex.props(s.columnPickerPositioner)}
        >
          <Popover.Popup
            className="nodrag nopan nowheel"
            {...stylex.props(overlay.popup, s.columnPickerPopup)}
          >
            <div {...stylex.props(s.columnPickerHeader)}>
              <span {...stylex.props(s.columnPickerTitle)}>
                Visible columns
              </span>
              <span {...stylex.props(s.columnPickerHint)}>
                Choose up to {MAX_VISIBLE_COLUMN_COUNT}
              </span>
            </div>
            <div {...stylex.props(s.columnPickerList)}>
              {columns.map((column) => {
                const checked = visibleColumnIdSet.has(column.id);
                const disabled =
                  (checked && visibleColumnIds.length === 1) ||
                  (!checked &&
                    visibleColumnIds.length >= MAX_VISIBLE_COLUMN_COUNT);
                return (
                  <label
                    key={column.id}
                    title={column.title || column.id}
                    {...stylex.props(overlay.item, s.columnPickerOption)}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={disabled}
                      onChange={(event) => {
                        if (event.currentTarget.checked) {
                          onVisibleColumnIdsChange([
                            ...visibleColumnIds,
                            column.id,
                          ]);
                          return;
                        }
                        onVisibleColumnIdsChange(
                          visibleColumnIds.filter(
                            (columnId) => columnId !== column.id,
                          ),
                        );
                      }}
                    />
                    <span {...stylex.props(s.columnPickerOptionTitle)}>
                      {column.title || column.id}
                    </span>
                    <span {...stylex.props(s.columnPickerOptionType)}>
                      {column.value_type}
                    </span>
                  </label>
                );
              })}
            </div>
            <div {...stylex.props(s.columnPickerFooter)}>
              <button
                type="button"
                {...stylex.props(s.columnPickerTextButton)}
                onClick={() =>
                  onVisibleColumnIdsChange(
                    columns
                      .slice(0, MAX_VISIBLE_COLUMN_COUNT)
                      .map((column) => column.id),
                  )
                }
              >
                Show all
              </button>
              <button
                type="button"
                {...stylex.props(s.columnPickerTextButton)}
                onClick={() =>
                  onVisibleColumnIdsChange(
                    columns
                      .slice(0, DEFAULT_VISIBLE_COLUMN_COUNT)
                      .map((column) => column.id),
                  )
                }
              >
                Reset
              </button>
            </div>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}

function TablePageNavigation({
  page,
  requestedOffset,
  pageSize,
  onOffsetChange,
  onPageSizeChange,
}: {
  page: TablePage;
  requestedOffset: number;
  pageSize: number;
  onOffsetChange: (offset: number) => void;
  onPageSizeChange: (pageSize: number) => void;
}) {
  const pageEnd = page.offset + page.rows.length;
  const waitingForRows = requestedOffset !== page.offset;
  const totalPages = Math.max(1, Math.ceil(page.total_rows / pageSize));
  const currentPage =
    page.total_rows === 0 ? 1 : Math.floor(page.offset / pageSize) + 1;
  const lastPageOffset =
    page.total_rows === 0
      ? 0
      : Math.floor((page.total_rows - 1) / pageSize) * pageSize;
  return (
    <div
      role="group"
      aria-label="Table row pages"
      {...stylex.props(s.tablePager)}
    >
      <span {...stylex.props(s.tablePagerMeta)}>
        <span aria-live="polite" {...stylex.props(s.tableLimit)}>
          {page.total_rows === 0
            ? "No rows"
            : `${page.offset + 1}–${pageEnd} of ${page.total_rows}`}
        </span>
        <select
          aria-label="Rows per page"
          value={pageSize}
          {...stylex.props(s.tablePageSize)}
          onChange={(event) =>
            onPageSizeChange(Number(event.currentTarget.value))
          }
        >
          <option value={25}>25 / page</option>
          <option value={50}>50 / page</option>
          <option value={100}>100 / page</option>
        </select>
      </span>
      <span {...stylex.props(s.tablePagerActions)}>
        <button
          type="button"
          aria-label="First page"
          title="First page"
          disabled={requestedOffset === 0}
          {...stylex.props(s.tablePagerButton, s.tablePagerIconButton)}
          onClick={() => onOffsetChange(0)}
        >
          <ChevronsLeft size={13} aria-hidden="true" />
        </button>
        <button
          type="button"
          aria-label="Previous page"
          title="Previous page"
          disabled={requestedOffset === 0}
          {...stylex.props(s.tablePagerButton, s.tablePagerIconButton)}
          onClick={() =>
            onOffsetChange(Math.max(0, requestedOffset - pageSize))
          }
        >
          <ChevronLeft size={13} aria-hidden="true" />
        </button>
        <span aria-live="polite" {...stylex.props(s.tablePageIndicator)}>
          Page {currentPage} of {totalPages}
        </span>
        <button
          type="button"
          aria-label="Next page"
          title="Next page"
          disabled={waitingForRows || pageEnd >= page.total_rows}
          {...stylex.props(s.tablePagerButton, s.tablePagerIconButton)}
          onClick={() => onOffsetChange(pageEnd)}
        >
          <ChevronRight size={13} aria-hidden="true" />
        </button>
        <button
          type="button"
          aria-label="Last page"
          title="Last page"
          disabled={waitingForRows || pageEnd >= page.total_rows}
          {...stylex.props(s.tablePagerButton, s.tablePagerIconButton)}
          onClick={() => onOffsetChange(lastPageOffset)}
        >
          <ChevronsRight size={13} aria-hidden="true" />
        </button>
      </span>
    </div>
  );
}

function TableArtifactRendererState({
  artifact,
  mode,
  availableHeight,
  interaction,
}: {
  artifact: ArtifactSummary;
  mode: string;
  availableHeight?: number;
  interaction?: ArtifactViewerInteractionContext;
}) {
  const { workspace } = useWorkspaceContext();
  const [requestedPage, setRequestedPage] = React.useState({
    filterSignature: "",
    offset: 0,
  });
  const [pageSize, setPageSize] = React.useState(DEFAULT_TABLE_PAGE_SIZE);
  const [visibleColumnIds, setVisibleColumnIds] = React.useState<
    readonly string[] | null
  >(null);
  const [selectedCell, setSelectedCell] =
    React.useState<TableCellSelection | null>(null);
  const [selectingRowIndex, setSelectingRowIndex] = React.useState<
    number | null
  >(null);
  const selectionRequestRef = React.useRef<AbortController | null>(null);
  const selectionActivityTimerRef = React.useRef<number | null>(null);
  const activityChangeRef = React.useRef(interaction?.onActivityChange);
  const cellDetailId = React.useId();
  const cellTriggerRef = React.useRef<HTMLButtonElement | null>(null);
  const {
    data: tableSchema,
    error: tableSchemaError,
    mutate: retryTableSchema,
  } = useSWR(
    ["table-artifact-schema", workspace.id, artifact.artifact_id] as const,
    ([, workspaceId, artifactId]) =>
      getArtifactTableSchema(workspaceId, artifactId),
  );
  const selectedColumnIds = React.useMemo(() => {
    if (!tableSchema) return [];
    const availableColumnIds = new Set(
      tableSchema.columns.map((column) => column.id),
    );
    const retainedColumnIds = visibleColumnIds?.filter((columnId) =>
      availableColumnIds.has(columnId),
    );
    if (retainedColumnIds?.length) return retainedColumnIds;
    return tableSchema.columns
      .slice(0, DEFAULT_VISIBLE_COLUMN_COUNT)
      .map((column) => column.id);
  }, [tableSchema, visibleColumnIds]);
  const selectedColumnSignature = selectedColumnIds.join("\u0000");
  const filterGroups =
    interaction?.incoming.flatMap((binding) =>
      binding.effects.includes("filter") && binding.rows.length
        ? [{ rows: binding.rows.map((values) => ({ values })) }]
        : [],
    ) ?? [];
  const highlightGroups =
    interaction?.incoming.flatMap((binding) =>
      binding.effects.includes("highlight") && binding.rows.length
        ? [{ rows: binding.rows.map((values) => ({ values })) }]
        : [],
    ) ?? [];
  const filterSignature = JSON.stringify(filterGroups);
  const offset =
    requestedPage.filterSignature === filterSignature
      ? requestedPage.offset
      : 0;
  const interactionQuery: TableQueryInput | null =
    filterGroups.length || highlightGroups.length
      ? {
          filter_groups: filterGroups,
          highlight_groups: highlightGroups,
          offset,
          limit: pageSize,
          ...(selectedColumnIds.length
            ? { column_ids: [...selectedColumnIds] }
            : {}),
          max_cell_characters: TABLE_CELL_PREVIEW_CHARACTERS,
        }
      : null;
  const interactionQuerySignature = JSON.stringify({
    filter_groups: filterGroups,
    highlight_groups: highlightGroups,
  });
  const pageKey = [
    interactionQuery ? "table-artifact-query" : "table-artifact-page",
    workspace.id,
    artifact.artifact_id,
    offset,
    pageSize,
    selectedColumnSignature,
    interactionQuerySignature,
  ] as const;
  const {
    data: page,
    error: pageError,
    isValidating: pageLoading,
    mutate: retryPage,
  } = useSWR(
    tableSchema ? pageKey : null,
    ([, workspaceId, artifactId, pageOffset]) =>
      interactionQuery
        ? queryArtifactTablePage(workspaceId, artifactId, interactionQuery)
        : getArtifactTablePage(
            workspaceId,
            artifactId,
            pageOffset,
            pageSize,
            selectedColumnIds,
            TABLE_CELL_PREVIEW_CHARACTERS,
          ),
    { keepPreviousData: true },
  );
  const cellKey = selectedCell
    ? ([
        "table-artifact-cell",
        workspace.id,
        artifact.artifact_id,
        selectedCell.rowIndex,
        selectedCell.columnId,
      ] as const)
    : null;
  const {
    data: fullCell,
    error: fullCellError,
    isLoading: fullCellLoading,
  } = useSWR(cellKey, ([, workspaceId, artifactId, rowIndex, columnId]) =>
    getArtifactTableCell(workspaceId, artifactId, rowIndex, columnId),
  );

  React.useEffect(() => {
    if (!interaction || !tableSchema) return;
    interaction.onFieldsChange(
      tableSchema.columns.map((column) => ({
        id: column.id,
        title: column.title || column.id,
        valueType: column.value_type,
      })),
    );
  }, [interaction, tableSchema]);

  React.useEffect(() => {
    activityChangeRef.current = interaction?.onActivityChange;
  }, [interaction?.onActivityChange]);

  React.useEffect(
    () => () => {
      const request = selectionRequestRef.current;
      selectionRequestRef.current = null;
      request?.abort();
      if (selectionActivityTimerRef.current !== null) {
        window.clearTimeout(selectionActivityTimerRef.current);
        selectionActivityTimerRef.current = null;
      }
      activityChangeRef.current?.(null);
    },
    [],
  );

  if (!page) {
    return (
      <div {...stylex.props(s.tablePreview)}>
        <span
          role={tableSchemaError || pageError ? "alert" : "status"}
          aria-live={tableSchemaError || pageError ? undefined : "polite"}
          {...stylex.props(s.tableLimit)}
        >
          {tableSchemaError
            ? "Could not load the table columns."
            : pageError
              ? "Could not load this table page."
              : "Loading table page…"}
        </span>
        {tableSchemaError || pageError ? (
          <button
            type="button"
            {...stylex.props(s.tablePagerButton)}
            onClick={() =>
              void (tableSchemaError ? retryTableSchema() : retryPage())
            }
          >
            Retry
          </button>
        ) : null}
      </div>
    );
  }

  const viewportHeight = availableHeight
    ? Math.max(120, availableHeight - 92)
    : undefined;
  const contentUrl = artifactContentUrl(workspace.id, artifact.content_url);
  const fullCellText = fullCell ? tableCellText(fullCell.value) : "";
  const selectedSourceIndices = new Set(
    interaction?.selection.items.flatMap((item) =>
      item.sourceIndex === undefined ? [] : [item.sourceIndex],
    ) ?? [],
  );
  const highlightedSourceIndices = new Set(page.highlighted_row_indices);
  const selectRow = async (
    rowIndex: number,
    visibleRow: TablePage["rows"][number],
  ) => {
    if (!interaction) return;
    if (selectedSourceIndices.has(rowIndex)) {
      const previousRequest = selectionRequestRef.current;
      selectionRequestRef.current = null;
      previousRequest?.abort();
      if (selectionActivityTimerRef.current !== null) {
        window.clearTimeout(selectionActivityTimerRef.current);
        selectionActivityTimerRef.current = null;
      }
      setSelectingRowIndex(null);
      interaction.onActivityChange(null);
      interaction.onSelectionChange({
        kind: "key-selection",
        items: [],
      });
      return;
    }
    const requestedFields = interaction.outgoingFields.length
      ? interaction.outgoingFields
      : page.columns.map((column) => column.id);
    if (!requestedFields.length) {
      interaction.onActivityChange({
        state: "warning",
        title: "Row cannot be linked",
        message: "This table has no fields available for selection.",
      });
      return;
    }
    selectionRequestRef.current?.abort();
    if (selectionActivityTimerRef.current !== null) {
      window.clearTimeout(selectionActivityTimerRef.current);
      selectionActivityTimerRef.current = null;
    }
    interaction.onActivityChange(null);
    const request = new AbortController();
    selectionRequestRef.current = request;
    setSelectingRowIndex(rowIndex);
    selectionActivityTimerRef.current = window.setTimeout(() => {
      if (selectionRequestRef.current !== request) return;
      selectionActivityTimerRef.current = null;
      interaction.onActivityChange({
        state: "working",
        title: "Reading selected row",
        message: `Loading mapped values from row ${rowIndex + 1}.`,
      });
    }, TABLE_SELECTION_ACTIVITY_DELAY_MS);
    let selectionFailed = false;
    try {
      const cells = await Promise.all(
        requestedFields.map((fieldName) =>
          getArtifactTableCell(
            workspace.id,
            artifact.artifact_id,
            rowIndex,
            fieldName,
            request.signal,
          ),
        ),
      );
      if (selectionRequestRef.current !== request) return;
      const values = Object.fromEntries(
        cells.flatMap((cell) => {
          const value = interactionScalarFromTableCell(cell);
          return value === undefined ? [] : [[cell.column_id, value]];
        }),
      );
      for (const column of page.columns) {
        const cell = visibleRow[column.id];
        if (
          !(column.id in values) &&
          cell &&
          !cell.truncated &&
          (cell.display === null ||
            typeof cell.display === "string" ||
            typeof cell.display === "number" ||
            typeof cell.display === "boolean")
        ) {
          values[column.id] =
            column.value_type === "integer"
              ? interactionScalarFromIntegerEncoding(cell.display)
              : cell.display;
        }
      }
      interaction.onSelectionChange({
        kind: "key-selection",
        items: [{ values, sourceIndex: rowIndex }],
      });
    } catch (error) {
      if (request.signal.aborted || selectionRequestRef.current !== request) {
        return;
      }
      selectionFailed = true;
      const message =
        error instanceof Error
          ? error.message
          : "Could not read the selected row.";
      interaction.onActivityChange({
        state: "error",
        title: "Could not read selected row",
        message,
        retry: () => void selectRow(rowIndex, visibleRow),
      });
    } finally {
      if (selectionRequestRef.current === request) {
        if (selectionActivityTimerRef.current !== null) {
          window.clearTimeout(selectionActivityTimerRef.current);
          selectionActivityTimerRef.current = null;
        }
        selectionRequestRef.current = null;
        setSelectingRowIndex(null);
        if (!selectionFailed) interaction.onActivityChange(null);
      }
    }
  };
  return (
    <div
      aria-busy={pageLoading || selectingRowIndex !== null}
      {...stylex.props(s.tablePreview)}
    >
      {pageError ? (
        <span role="alert" {...stylex.props(s.tableLimit)}>
          Could not load the requested table page. The previous page is still
          available.{" "}
          <button type="button" onClick={() => void retryPage()}>
            Retry
          </button>
        </span>
      ) : null}
      <div {...stylex.props(s.tableSummary)}>
        <span {...stylex.props(s.tableSummaryMeta)}>
          <span {...stylex.props(s.tableSummaryStrong)}>{page.total_rows}</span>
          <span>{page.total_rows === 1 ? "row" : "rows"}</span>
          <span aria-hidden="true" {...stylex.props(s.tableSummaryDivider)}>
            ·
          </span>
          <span>
            {page.total_columns}{" "}
            {page.total_columns === 1 ? "column" : "columns"}
          </span>
        </span>
        <span {...stylex.props(s.tableToolbarActions)}>
          {contentUrl ? (
            <a
              href={contentUrl}
              download
              title="Download the complete table as JSON"
              {...stylex.props(s.tableDownload)}
            >
              Download JSON
            </a>
          ) : null}
          {tableSchema?.columns.length ? (
            <TableColumnPicker
              columns={tableSchema.columns}
              visibleColumnIds={selectedColumnIds}
              onVisibleColumnIdsChange={(columnIds) => {
                setSelectedCell(null);
                setVisibleColumnIds(columnIds);
              }}
            />
          ) : null}
        </span>
      </div>
      {mode === "raw" ? (
        <pre {...stylex.props(s.jsonCode)}>{JSON.stringify(page, null, 2)}</pre>
      ) : (
        <div
          role="region"
          aria-label="Table preview"
          tabIndex={0}
          className="nodrag nowheel"
          {...stylex.props(s.tableViewport)}
          style={{ maxHeight: viewportHeight }}
        >
          <table {...stylex.props(s.dataTable)}>
            <thead>
              <tr>
                <th scope="col" {...stylex.props(s.tableIndexHeader)}>
                  #
                </th>
                {page.columns.map((column) => (
                  <th
                    key={column.id}
                    scope="col"
                    title={`${column.title || column.id} · ${column.value_type}`}
                    {...stylex.props(s.tableHeader)}
                  >
                    <span {...stylex.props(s.tableHeaderTitle)}>
                      {column.title || column.id}
                    </span>
                    <span {...stylex.props(s.tableHeaderType)}>
                      {column.value_type}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {page.rows.map((row, pageRowIndex) => {
                const rowIndex =
                  page.row_indices?.[pageRowIndex] ??
                  page.offset + pageRowIndex;
                const selected = selectedSourceIndices.has(rowIndex);
                const highlighted = highlightedSourceIndices.has(rowIndex);
                return (
                  <tr
                    key={rowIndex}
                    tabIndex={interaction ? 0 : undefined}
                    aria-selected={interaction ? selected : undefined}
                    {...stylex.props(
                      interaction ? s.tableRowInteractive : null,
                    )}
                    onClick={() => void selectRow(rowIndex, row)}
                    onKeyDown={(event) => {
                      if (
                        interaction &&
                        (event.key === "Enter" || event.key === " ")
                      ) {
                        event.preventDefault();
                        void selectRow(rowIndex, row);
                      }
                    }}
                  >
                    <th
                      scope="row"
                      {...stylex.props(
                        s.tableIndexCell,
                        selected ? s.tableCellSelected : null,
                        !selected && highlighted
                          ? s.tableCellHighlighted
                          : null,
                      )}
                    >
                      {rowIndex + 1}
                    </th>
                    {page.columns.map((column) => {
                      const cell = row[column.id];
                      const text = tableCellText(cell.display);
                      const code =
                        column.value_type !== "text" &&
                        column.value_type !== "boolean";
                      return (
                        <td
                          key={column.id}
                          title={
                            cell.truncated
                              ? "Preview truncated; click to inspect"
                              : undefined
                          }
                          {...stylex.props(
                            s.tableCell,
                            code ? s.tableCellCode : null,
                            cell.display === null ? s.tableCellNull : null,
                            selected ? s.tableCellSelected : null,
                            !selected && highlighted
                              ? s.tableCellHighlighted
                              : null,
                          )}
                        >
                          {cell.truncated ? (
                            <button
                              type="button"
                              aria-expanded={
                                selectedCell?.rowIndex === rowIndex &&
                                selectedCell.columnId === column.id
                              }
                              aria-controls={cellDetailId}
                              {...stylex.props(s.tableTruncatedCellButton)}
                              onClick={(event) => {
                                event.stopPropagation();
                                cellTriggerRef.current = event.currentTarget;
                                setSelectedCell({
                                  rowIndex,
                                  columnId: column.id,
                                  columnTitle: column.title || column.id,
                                });
                              }}
                            >
                              {text}
                            </button>
                          ) : (
                            text
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
              {!page.rows.length ? (
                <tr>
                  <td
                    colSpan={Math.max(1, page.columns.length + 1)}
                    {...stylex.props(s.tableEmpty)}
                  >
                    {page.columns.length
                      ? "This table has no rows"
                      : "This table has no columns or rows"}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}
      <TablePageNavigation
        page={page}
        requestedOffset={offset}
        pageSize={pageSize}
        onOffsetChange={(nextOffset) => {
          setSelectedCell(null);
          setRequestedPage({ filterSignature, offset: nextOffset });
        }}
        onPageSizeChange={(nextPageSize) => {
          setSelectedCell(null);
          setRequestedPage({ filterSignature, offset: 0 });
          setPageSize(nextPageSize);
        }}
      />
      {mode !== "raw" && selectedCell ? (
        <div
          id={cellDetailId}
          role="region"
          aria-label="Full table cell value"
          {...stylex.props(s.tableCellDetail)}
        >
          <div {...stylex.props(s.tableCellDetailHeader)}>
            <span>
              Row {selectedCell.rowIndex + 1} · {selectedCell.columnTitle}
            </span>
            <button
              type="button"
              aria-label="Close full cell value"
              {...stylex.props(s.tablePagerButton)}
              onClick={() => {
                const trigger = cellTriggerRef.current;
                setSelectedCell(null);
                window.requestAnimationFrame(() => trigger?.focus());
              }}
            >
              Close
            </button>
          </div>
          {fullCellLoading ? (
            <span
              role="status"
              aria-live="polite"
              {...stylex.props(s.tableLimit)}
            >
              Loading full cell…
            </span>
          ) : fullCellError ? (
            <span role="alert" {...stylex.props(s.tableLimit)}>
              Could not load the full cell value.
            </span>
          ) : fullCell ? (
            <textarea
              autoFocus
              readOnly
              aria-label="Full cell value"
              value={fullCellText}
              {...stylex.props(s.tableCellDetailValue)}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function TableArtifactRenderer(props: {
  artifact: ArtifactSummary;
  mode: string;
  availableHeight?: number;
  interaction?: ArtifactViewerInteractionContext;
}) {
  return (
    <TableArtifactRendererState key={props.artifact.artifact_id} {...props} />
  );
}

const tableRenderer: ArtifactRendererSpec = {
  id: "table",
  modes: ["table", "raw"],
  interaction: {
    emits: ["key-selection"],
    accepts: ["filter", "highlight"],
  },
  matches: (artifact) =>
    artifact.artifact_type === "table.data" && artifact.schema_version === 1,
  Component: ({ artifact, mode, availableHeight, interaction }) => (
    <TableArtifactRenderer
      artifact={artifact}
      mode={mode}
      availableHeight={availableHeight}
      interaction={interaction}
    />
  ),
};

const jsonSchemaRenderer: ArtifactRendererSpec = {
  id: "json-schema",
  modes: ["pretty", "raw"],
  matches: (artifact) =>
    artifact.artifact_type === "json.schema" && artifact.schema_version === 1,
  Component: ({ artifact, payload, mode }) => {
    const value = payload === undefined ? artifactMeta(artifact) : payload;
    if (mode === "pretty") {
      const formattedSchema = formatJsonSchemaPayload(value);
      if (formattedSchema !== null) {
        return <pre {...stylex.props(s.jsonCode)}>{formattedSchema}</pre>;
      }
      return <PrettyValue value={value} />;
    }
    return (
      <pre {...stylex.props(s.jsonCode)}>{JSON.stringify(value, null, 2)}</pre>
    );
  },
};

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

const markdownRenderer: ArtifactRendererSpec = {
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
      return <pre {...stylex.props(s.jsonCode)}>{markdown}</pre>;
    }
    return (
      <div {...stylex.props(s.markdown)}>
        <Markdown options={markdownOptions}>{markdown}</Markdown>
      </div>
    );
  },
};

const jsonRenderer: ArtifactRendererSpec = {
  id: "json",
  modes: ["pretty", "raw"],
  matches: (artifact, payload) =>
    payload !== undefined || artifact.content_type === "application/json",
  Component: ({ artifact, payload, mode }) => {
    const value = payload === undefined ? artifactMeta(artifact) : payload;
    if (mode === "raw") {
      return (
        <pre {...stylex.props(s.jsonCode)}>
          {JSON.stringify(value, null, 2)}
        </pre>
      );
    }
    return <PrettyValue value={value} />;
  },
};

export const META_ARTIFACT_RENDERER: ArtifactRendererSpec = {
  id: "meta",
  modes: ["meta"],
  matches: () => true,
  Component: ({ artifact }) => <PrettyValue value={artifactMeta(artifact)} />,
};

export const ARTIFACT_RENDERERS: readonly ArtifactRendererSpec[] = [
  imageRenderer,
  geoMapRenderer,
  tableRenderer,
  jsonSchemaRenderer,
  markdownRenderer,
  jsonRenderer,
  META_ARTIFACT_RENDERER,
];

export function rendererFor(
  artifact: ArtifactSummary,
  payload?: unknown,
): ArtifactRendererSpec {
  return (
    ARTIFACT_RENDERERS.find((renderer) =>
      renderer.matches(artifact, payload),
    ) ?? META_ARTIFACT_RENDERER
  );
}

/** Table and map opt in; markdown, image, JSON, and empty previews do not. */
export function rendererCanBrush(
  artifact: ArtifactSummary | undefined,
): boolean {
  if (!artifact) return false;
  const interaction = rendererFor(artifact).interaction;
  return Boolean(
    interaction &&
    (interaction.emits.length > 0 || interaction.accepts.length > 0),
  );
}

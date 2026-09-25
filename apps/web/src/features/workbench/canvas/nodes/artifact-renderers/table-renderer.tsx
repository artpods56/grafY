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
  type ArtifactViewerInteractionContext,
} from "../../artifact-interactions";

import type { ArtifactRendererSpec } from "./spec";
import { sharedStyles } from "./styles";

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

const s = stylex.create({
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
});

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
        <pre {...stylex.props(sharedStyles.jsonCode)}>
          {JSON.stringify(page, null, 2)}
        </pre>
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

export const tableRenderer: ArtifactRendererSpec = {
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

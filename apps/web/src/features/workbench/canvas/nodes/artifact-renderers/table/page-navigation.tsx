"use client";

import * as stylex from "@stylexjs/stylex";
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react";

import type { TablePage } from "@/lib/api";
import { IconButton } from "@/components/ui/button";
import { Select } from "@/components/ui/select";

import { s } from "./styles";

export function TablePageNavigation({
  page,
  requestedOffset,
  pageSize,
  onOffsetChange,
  onPageSizeChange,
  canvas = false,
}: {
  page: TablePage;
  requestedOffset: number;
  pageSize: number;
  onOffsetChange: (offset: number) => void;
  onPageSizeChange: (pageSize: number) => void;
  canvas?: boolean;
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
      {...stylex.props(s.tablePager, canvas ? s.tableCanvasPager : null)}
    >
      <span {...stylex.props(s.tablePagerMeta)}>
        <span aria-live="polite" {...stylex.props(s.tableLimit)}>
          {page.total_rows === 0
            ? "No rows"
            : `${page.offset + 1}–${pageEnd} of ${page.total_rows}`}
        </span>
        <Select
          aria-label="Rows per page"
          size="dense"
          block={false}
          value={pageSize}
          onChange={(event) =>
            onPageSizeChange(Number(event.currentTarget.value))
          }
        >
          <option value={25}>25 / page</option>
          <option value={50}>50 / page</option>
          <option value={100}>100 / page</option>
        </Select>
      </span>
      <span
        {...stylex.props(
          s.tablePagerActions,
          canvas ? s.tableCanvasPagerActions : null,
        )}
      >
        <IconButton
          label="First page"
          title="First page"
          variant="soft"
          className="nodrag"
          disabled={requestedOffset === 0}
          onClick={() => onOffsetChange(0)}
        >
          <ChevronsLeft size={13} />
        </IconButton>
        <IconButton
          label="Previous page"
          title="Previous page"
          variant="soft"
          className="nodrag"
          disabled={requestedOffset === 0}
          onClick={() =>
            onOffsetChange(Math.max(0, requestedOffset - pageSize))
          }
        >
          <ChevronLeft size={13} />
        </IconButton>
        <span aria-live="polite" {...stylex.props(s.tablePageIndicator)}>
          Page {currentPage} of {totalPages}
        </span>
        <IconButton
          label="Next page"
          title="Next page"
          variant="soft"
          className="nodrag"
          disabled={waitingForRows || pageEnd >= page.total_rows}
          onClick={() => onOffsetChange(pageEnd)}
        >
          <ChevronRight size={13} />
        </IconButton>
        <IconButton
          label="Last page"
          title="Last page"
          variant="soft"
          className="nodrag"
          disabled={waitingForRows || pageEnd >= page.total_rows}
          onClick={() => onOffsetChange(lastPageOffset)}
        >
          <ChevronsRight size={13} />
        </IconButton>
      </span>
    </div>
  );
}

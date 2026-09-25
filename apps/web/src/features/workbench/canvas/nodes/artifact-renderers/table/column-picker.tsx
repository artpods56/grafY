"use client";

import * as stylex from "@stylexjs/stylex";
import { Popover } from "@base-ui/react/popover";
import { ChevronDown, Columns3 } from "lucide-react";

import type { TableSchema } from "@/lib/api";
import { overlay } from "@/lib/stylex/overlay.stylex";

import {
  DEFAULT_VISIBLE_COLUMN_COUNT,
  MAX_VISIBLE_COLUMN_COUNT,
} from "./constants";
import { s } from "./styles";

export function TableColumnPicker({
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

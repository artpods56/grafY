"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Plus, Trash2 } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import { TextInput } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { Select } from "@/components/ui/select";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { ArtifactEditorActions } from "./editor-actions";
import {
  formatCellInput,
  parseCellInput,
  reduceTableEditor,
  tableEditorPayload,
  TABLE_VALUE_TYPES,
  createTableEditorState,
  isValueType,
} from "./table-editor-reducer";
import type { ArtifactEditorProps } from "./types";

const s = stylex.create({
  root: {
    display: "grid",
    gap: tokens.space3,
    minHeight: 0,
  },
  toolbar: {
    display: "flex",
    flexWrap: "wrap",
    gap: tokens.space2,
  },
  scroller: {
    overflow: "auto",
    maxHeight: "24rem",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
  },
  table: {
    borderCollapse: "collapse",
    width: "100%",
    minWidth: "100%",
    fontSize: tokens.fontSizeXs,
  },
  th: {
    position: "sticky",
    top: 0,
    zIndex: 1,
    backgroundColor: tokens.colorSurfaceRaised,
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
    padding: tokens.space2,
    textAlign: "left",
    verticalAlign: "top",
  },
  td: {
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    padding: tokens.space1,
    verticalAlign: "middle",
  },
  heading: {
    display: "grid",
    gap: tokens.space1,
    minWidth: "8rem",
  },
  headingRow: {
    display: "flex",
    alignItems: "center",
    gap: tokens.space1,
  },
  cellInput: {
    minWidth: "7rem",
  },
  rowIndex: {
    color: tokens.colorSubtle,
    fontVariantNumeric: "tabular-nums",
    paddingInline: tokens.space2,
    whiteSpace: "nowrap",
  },
});

export function TableArtifactEditor({
  initialPayload,
  saving = false,
  error = null,
  onSave,
  onCancel,
  onDraftChange,
}: ArtifactEditorProps) {
  const [state, setState] = React.useState(() =>
    createTableEditorState(initialPayload),
  );

  const dispatch: typeof setState = (update) => {
    setState((current) => {
      const next = typeof update === "function" ? update(current) : update;
      onDraftChange?.(tableEditorPayload(next));
      return next;
    });
  };

  const reduce = (action: Parameters<typeof reduceTableEditor>[1]) => {
    dispatch((current) => reduceTableEditor(current, action));
  };

  return (
    <div {...stylex.props(s.root)}>
      <div {...stylex.props(s.toolbar)}>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={saving}
          onClick={() => reduce({ type: "add-row" })}
        >
          <Plus size={13} />
          Add row
        </Button>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={saving}
          onClick={() => reduce({ type: "add-column" })}
        >
          <Plus size={13} />
          Add column
        </Button>
      </div>
      <div {...stylex.props(s.scroller)}>
        <table {...stylex.props(s.table)}>
          <thead>
            <tr>
              <th {...stylex.props(s.th)} />
              {state.columns.map((column) => (
                <th key={column.id} {...stylex.props(s.th)}>
                  <div {...stylex.props(s.heading)}>
                    <div {...stylex.props(s.headingRow)}>
                      <TextInput
                        size="dense"
                        aria-label={`Title for ${column.id}`}
                        value={column.title}
                        disabled={saving}
                        onChange={(event) =>
                          reduce({
                            type: "rename-column",
                            columnId: column.id,
                            title: event.target.value,
                          })
                        }
                      />
                      <IconButton
                        label={`Delete column ${column.title || column.id}`}
                        size="2xs"
                        variant="ghost"
                        disabled={saving || state.columns.length <= 1}
                        onClick={() =>
                          reduce({
                            type: "delete-column",
                            columnId: column.id,
                          })
                        }
                      >
                        <Trash2 size={12} />
                      </IconButton>
                    </div>
                    <Select
                      size="dense"
                      aria-label={`Type for ${column.title || column.id}`}
                      value={column.value_type}
                      disabled={saving}
                      onChange={(event) =>
                        reduce({
                          type: "set-column-type",
                          columnId: column.id,
                          value_type: isValueType(event.target.value)
                            ? event.target.value
                            : "text",
                        })
                      }
                    >
                      {TABLE_VALUE_TYPES.map((valueType) => (
                        <option key={valueType} value={valueType}>
                          {valueType}
                        </option>
                      ))}
                    </Select>
                  </div>
                </th>
              ))}
              <th {...stylex.props(s.th)} />
            </tr>
          </thead>
          <tbody>
            {state.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                <td {...stylex.props(s.td, s.rowIndex)}>{rowIndex + 1}</td>
                {state.columns.map((column) => (
                  <td key={column.id} {...stylex.props(s.td)}>
                    <TextInput
                      size="dense"
                      xstyle={s.cellInput}
                      aria-label={`${column.title || column.id}, row ${rowIndex + 1}`}
                      value={formatCellInput(row[column.id] ?? null)}
                      disabled={saving}
                      onChange={(event) =>
                        reduce({
                          type: "set-cell",
                          row: rowIndex,
                          columnId: column.id,
                          value: parseCellInput(
                            event.target.value,
                            column.value_type,
                          ),
                        })
                      }
                    />
                  </td>
                ))}
                <td {...stylex.props(s.td)}>
                  <IconButton
                    label={`Delete row ${rowIndex + 1}`}
                    size="2xs"
                    variant="ghost"
                    disabled={saving}
                    onClick={() =>
                      reduce({ type: "delete-row", row: rowIndex })
                    }
                  >
                    <Trash2 size={12} />
                  </IconButton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {state.rows.length === 0 ? (
        <Notice tone="neutral">No rows yet. Add a row to start editing.</Notice>
      ) : null}
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <ArtifactEditorActions
        saving={saving}
        extra={
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={saving || state.past.length === 0}
            onClick={() => reduce({ type: "undo" })}
          >
            Undo
          </Button>
        }
        onReset={() => reduce({ type: "reset" })}
        onCancel={onCancel}
        onSave={() => void onSave(tableEditorPayload(state))}
      />
    </div>
  );
}

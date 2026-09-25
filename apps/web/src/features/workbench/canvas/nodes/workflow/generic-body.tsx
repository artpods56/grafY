"use client";

import * as stylex from "@stylexjs/stylex";
import { RotateCcw } from "lucide-react";

import { artifactTypeVariableOptions } from "@/features/workbench/model/claimed-formats";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { artifactTypeColor } from "../../nodes.css";
import { nodeSecretDependencyRevision } from "../../node-secrets";
import { resolvedNodeWidth, type WorkflowNodeLayout } from "../../node-layout";
import {
  declaredArtifactTypeVariables,
  type WorkflowNodeData,
} from "../../types";
import { useOptionalCanvasGridSettings } from "../../canvas-grid-settings";
import { GRID_CELL_SIZE_DEFAULT, spanFromLength } from "../../grid-layout";
import { configBoardColumns, packFieldFootprints } from "../field-footprints";

import {
  ConfigField,
  SecretInputField,
  configBricks,
  configFieldLabelIsRedundant,
} from "./config-fields";
import { nodeInteractionProps } from "./ports";

const s = stylex.create({
  genericTypes: {
    display: "grid",
    gap: "5px",
    padding: "0 10px 8px",
  },
  genericTypeRow: {
    minHeight: "30px",
    display: "flex",
    alignItems: "center",
    gap: "7px",
    padding: "5px 7px",
    borderRadius: "7px",
    backgroundColor: tokens.colorSurfaceMuted,
  },
  genericTypeDot: {
    width: "6px",
    height: "6px",
    flexShrink: 0,
    borderRadius: "9999px",
    backgroundColor: tokens.colorAccent,
  },
  genericTypeCopy: {
    minWidth: 0,
    flex: 1,
    overflow: "hidden",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  genericTypeBound: {
    color: tokens.colorTextEmphasis,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontWeight: 500,
  },
  bindType: {
    minWidth: 0,
    flex: 1,
    paddingInline: "4px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "5px",
    backgroundColor: tokens.colorSurface,
    color: tokens.colorTextEmphasis,
    cursor: "pointer",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
  },
  resetType: {
    minHeight: "22px",
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    paddingInline: "6px",
    borderWidth: 0,
    borderRadius: "5px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: { default: tokens.colorMuted, ":hover": tokens.colorText },
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 500,
  },
  resetTypeDisabled: {
    color: tokens.colorSubtle,
    cursor: "not-allowed",
    opacity: 0.55,
  },
  body: {
    display: "grid",
    gap: "9px",
    padding: "0 16px 6px",
    minHeight: 0,
  },
  /**
   * Config bricks sit on the lattice: columns come from the node width, rows
   * are whole cells that may stretch when a brick's content outgrows them.
   * Row gap stays 0 so the packed cell count still predicts the body height;
   * the slack inside each brick is the visual gutter.
   */
  configBoard: {
    display: "grid",
    columnGap: "10px",
    rowGap: 0,
    minWidth: 0,
    alignItems: "stretch",
  },
  /** The reserved gutter below every brick is what separates adjacent shelves. */
  configBrick: {
    minWidth: 0,
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
    paddingBottom: "8px",
  },
});

export function GenericArtifactTypeState({
  id,
  data,
  resettable,
}: {
  id: string;
  data: WorkflowNodeData;
  resettable: boolean;
}) {
  const variables = declaredArtifactTypeVariables(data.spec);
  if (!variables.length) return null;
  const bindableArtifactTypes = data.bindableArtifactTypes ?? [];

  return (
    <div {...stylex.props(s.genericTypes)} aria-label="Generic artifact types">
      {variables.map((variable) => {
        const artifactType = data.artifactTypeBindings[variable];
        const options = artifactTypeVariableOptions(
          data.spec.operator_id,
          variable,
          bindableArtifactTypes,
        );
        const picksType =
          data.onBindArtifactTypeBinding !== undefined && options.length > 0;
        const label = artifactType
          ? `${artifactType.id}@${artifactType.schema_version}`
          : "Any artifact · binds on connect";
        return (
          <div key={variable} {...stylex.props(s.genericTypeRow)}>
            <span
              aria-hidden="true"
              {...stylex.props(s.genericTypeDot)}
              style={
                artifactType
                  ? {
                      backgroundColor: artifactTypeColor(
                        artifactType.id,
                        tokens.colorAccent,
                      ),
                    }
                  : undefined
              }
            />
            {picksType ? (
              <select
                disabled={!resettable}
                aria-label={`Bind artifact type ${variable}`}
                title={
                  resettable
                    ? `Bind ${variable} to an artifact type`
                    : "Disconnect this node before changing its type"
                }
                {...nodeInteractionProps(stylex.props(s.bindType))}
                value={
                  artifactType
                    ? `${artifactType.id}@${artifactType.schema_version}`
                    : ""
                }
                onChange={(event) => {
                  const choice = event.currentTarget.value;
                  if (!choice) return;
                  const separator = choice.lastIndexOf("@");
                  data.onBindArtifactTypeBinding?.(id, variable, {
                    id: choice.slice(0, separator),
                    schema_version: Number(choice.slice(separator + 1)),
                  });
                }}
              >
                <option value="">Any artifact · binds on connect</option>
                {options.map((type) => (
                  <option
                    key={`${type.id}@${type.schema_version}`}
                    value={`${type.id}@${type.schema_version}`}
                  >
                    {`${type.id}@${type.schema_version}`}
                  </option>
                ))}
              </select>
            ) : (
              <span
                title={`${variable}: ${label}`}
                {...stylex.props(
                  s.genericTypeCopy,
                  artifactType ? s.genericTypeBound : null,
                )}
              >
                {label}
              </span>
            )}
            {artifactType ? (
              <button
                type="button"
                disabled={!resettable || !data.onResetArtifactTypeBinding}
                aria-label={`Reset artifact type ${variable}`}
                title={
                  resettable
                    ? "Reset type"
                    : "Disconnect this node before resetting its type"
                }
                {...nodeInteractionProps(
                  stylex.props(
                    s.resetType,
                    resettable ? null : s.resetTypeDisabled,
                  ),
                )}
                onClick={() => data.onResetArtifactTypeBinding?.(id, variable)}
              >
                <RotateCcw size={10} />
                Reset type
              </button>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Config inputs are packed onto the body lattice in schema order. Widening the
 * node stretches the existing bricks first (more room for labels/descriptions);
 * packing only adds columns once another half-brick can stay comfortably wide.
 * A saved body height is only a request — the board grows whenever the ordered
 * bricks need more rows.
 */
export function GenericBody({
  id,
  data,
  bodyHeight,
  layout,
  onLayoutDraft,
  onLayoutCommit,
}: {
  id: string;
  data: WorkflowNodeData;
  bodyHeight: number | null;
  layout: WorkflowNodeLayout | null;
  onLayoutDraft: (layout: WorkflowNodeLayout | null) => void;
  onLayoutCommit: (layout: WorkflowNodeLayout | null) => void;
}) {
  const grid = useOptionalCanvasGridSettings();
  const bricks = configBricks(data);
  if (!bricks.length) return null;

  const cellSize = grid?.settings.cellSize ?? GRID_CELL_SIZE_DEFAULT;
  const labelHidden = configFieldLabelIsRedundant(data.spec.title, bricks);
  const board = packFieldFootprints(
    bricks.map((brick) => brick.footprint),
    {
      columns: configBoardColumns(resolvedNodeWidth(layout), cellSize),
      minRows: bodyHeight === null ? 0 : spanFromLength(bodyHeight, cellSize),
    },
  );

  return (
    <div {...stylex.props(s.body)}>
      <div
        data-testid="config-board"
        {...stylex.props(s.configBoard)}
        style={{
          gridTemplateColumns: `repeat(${board.columns}, minmax(0, 1fr))`,
          gridTemplateRows: `repeat(${board.rows}, minmax(${cellSize}px, auto))`,
        }}
      >
        {board.placements.map((placement) => {
          const brick = bricks[placement.index];
          if (!brick) return null;
          const fillsCell = brick.footprint.growY === true;
          return (
            <div
              key={
                brick.kind === "field"
                  ? `field:${brick.field.name}`
                  : `secret:${brick.input.name}`
              }
              data-testid="config-brick"
              {...stylex.props(s.configBrick)}
              style={{
                gridColumn: `${placement.col + 1} / span ${placement.w}`,
                gridRow: `${placement.row + 1} / span ${placement.h}`,
              }}
            >
              {brick.kind === "field" ? (
                <ConfigField
                  field={brick.field}
                  value={data.config[brick.field.name]}
                  fillHeight={fillsCell}
                  labelHidden={labelHidden}
                  layout={layout}
                  onLayoutDraft={onLayoutDraft}
                  onLayoutCommit={onLayoutCommit}
                  onChange={(value) =>
                    data.onConfigChange?.(id, brick.field.name, value)
                  }
                />
              ) : (
                <SecretInputField
                  key={`${data.secretInputScope}:${brick.input.name}:${nodeSecretDependencyRevision(brick.input, data.config)}`}
                  id={id}
                  data={data}
                  input={brick.input}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

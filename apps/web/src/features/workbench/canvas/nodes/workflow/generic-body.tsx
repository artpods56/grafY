"use client";

import * as stylex from "@stylexjs/stylex";
import { RotateCcw } from "lucide-react";

import { artifactTypeVariableOptions } from "@/features/workbench/model/claimed-formats";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { nodeSecretDependencyRevision } from "../../node-secrets";
import { resolvedNodeWidth, type WorkflowNodeLayout } from "../../node-layout";
import {
  declaredArtifactTypeVariables,
  type WorkflowNodeData,
} from "../../types";
import { useOptionalCanvasGridSettings } from "../../canvas-grid-settings";
import { GRID_CELL_SIZE_DEFAULT, spanFromLength } from "../../grid-layout";
import { validateConfig } from "../../config-schema";
import { configBoardColumns, packFieldFootprints } from "../field-footprints";

import {
  ConfigField,
  SecretInputField,
  configBricks,
  configFieldLabelIsRedundant,
} from "./config-fields";
import { ANY_TYPE_LABEL, nodeInteractionProps } from "./ports";

const s = stylex.create({
  configValidationError: {
    margin: 0,
    color: tokens.colorDanger,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
  },
  configValidationSummary: {
    margin: "0 12px 8px",
    color: tokens.colorDanger,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
  },
  // The type a generic node works with, as one quiet line at the top of the
  // plate: a label, the choice, and a reset. Its colour is on the balls. Only
  // for a type no visible port carries.
  genericTypes: {
    display: "grid",
    minWidth: 0,
    paddingBlock: "4px 2px",
  },
  genericTypeRow: {
    minWidth: 0,
    height: "24px",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    paddingInline: "10px 6px",
  },
  genericTypeLabel: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
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
    color: tokens.colorText,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10.5px",
  },
  bindType: {
    minWidth: 0,
    flex: 1,
    height: "22px",
    paddingInline: "4px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: { default: "transparent", ":hover": tokens.colorBorder },
    borderRadius: tokens.radiusSm,
    backgroundColor: { default: "transparent", ":hover": tokens.colorSurface },
    color: tokens.colorText,
    cursor: { default: "pointer", ":disabled": "default" },
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10.5px",
    textOverflow: "ellipsis",
  },
  resetType: {
    width: "22px",
    height: "22px",
    flexShrink: 0,
    display: "grid",
    placeItems: "center",
    padding: 0,
    borderWidth: 0,
    borderRadius: "9999px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorText },
    cursor: "pointer",
  },
  resetTypeDisabled: {
    cursor: "not-allowed",
    opacity: 0.45,
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
  skip,
}: {
  id: string;
  data: WorkflowNodeData;
  resettable: boolean;
  /** Variables already chosen on a visible port. */
  skip: ReadonlySet<string>;
}) {
  const variables = declaredArtifactTypeVariables(data.spec).filter(
    (variable) => !skip.has(variable),
  );
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
          : ANY_TYPE_LABEL;
        return (
          <div key={variable} {...stylex.props(s.genericTypeRow)}>
            <span {...stylex.props(s.genericTypeLabel)}>
              {variables.length > 1 ? `Type ${variable}` : "Type"}
            </span>
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
                <option value="">{ANY_TYPE_LABEL}</option>
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
                <RotateCcw size={11} />
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
  const issues = validateConfig(data.spec.config_schema, data.config);
  if (!bricks.length && !issues.length) return null;
  const displayedFields = new Set(
    bricks.flatMap((brick) =>
      brick.kind === "field" ? [brick.field.name] : [],
    ),
  );
  const summaryIssues = issues.filter(
    (issue) =>
      issue.fieldName === null || !displayedFields.has(issue.fieldName),
  );

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
      {bricks.length ? (
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
                  <>
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
                    {issues
                      .filter((issue) => issue.fieldName === brick.field.name)
                      .map((issue, index) => (
                        <p
                          key={`${brick.field.name}-config-issue-${index}`}
                          role="alert"
                          {...stylex.props(s.configValidationError)}
                        >
                          {issue.message}
                        </p>
                      ))}
                  </>
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
      ) : null}
      {summaryIssues.length ? (
        <p role="alert" {...stylex.props(s.configValidationSummary)}>
          This node has configuration errors in fields that cannot be edited
          here.
        </p>
      ) : null}
    </div>
  );
}

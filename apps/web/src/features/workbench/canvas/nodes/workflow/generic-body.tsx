"use client";

import * as React from "react";
import { useUpdateNodeInternals } from "@xyflow/react";
import * as stylex from "@stylexjs/stylex";
import { ChevronRight, RotateCcw } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";
import { Button, IconButton } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Notice } from "@/components/ui/notice";

import { resolvedNodeWidth, type WorkflowNodeLayout } from "../../node-layout";
import {
  declaredArtifactTypeVariables,
  type WorkflowNodeData,
} from "../../types";
import { useOptionalCanvasGridSettings } from "../../canvas-grid-settings";
import { artifactTypeKey } from "../../artifact-type-key";
import {
  formatArtifactTypeLabel,
  formatArtifactTypeTooltip,
} from "../../artifact-type-label";
import { useArtifactTypeCatalog } from "../../use-artifact-type-catalog";
import { GRID_CELL_SIZE_DEFAULT, spanFromLength } from "../../grid-layout";
import {
  schemaFields,
  validateConfig,
  visibleSchemaFields,
  type ConfigValidationIssue,
  type ConnectedInputPortMap,
  type SchemaField,
} from "../../config-schema";
import { configBoardColumns, packFieldFootprints } from "../field-footprints";

import {
  ConfigField,
  configBricks,
  configFieldLabelIsRedundant,
  type ConfigBrick,
} from "./config-fields";
import { ANY_TYPE_LABEL } from "./ports";

const s = stylex.create({
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
    minHeight: "24px",
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
  /** A named group: one quiet header row, its bricks on the same lattice. */
  group: {
    minWidth: 0,
    display: "grid",
    gap: "4px",
  },
  groupToggle: {
    width: "100%",
    minWidth: 0,
    justifyContent: "flex-start",
    gap: "5px",
    paddingBlock: "3px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
    borderRadius: 0,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    textAlign: "left",
    textDecoration: {
      default: "none",
      ":hover:not(:disabled)": "none",
      ":focus-visible": "none",
    },
  },
  groupTitle: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  groupCount: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 400,
  },
  groupIssues: {
    flexShrink: 0,
    marginLeft: "auto",
    color: tokens.colorDanger,
    fontSize: "10px",
    fontWeight: 500,
  },
  chevron: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    transitionDuration: "120ms",
    transitionProperty: "transform",
  },
  chevronOpen: { transform: "rotate(90deg)" },
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
  const artifactTypes = useArtifactTypeCatalog();
  const variables = declaredArtifactTypeVariables(data.spec).filter(
    (variable) => !skip.has(variable),
  );
  if (!variables.length) return null;
  const bindableArtifactTypes = data.bindableArtifactTypes ?? [];

  return (
    <div {...stylex.props(s.genericTypes)} aria-label="Generic artifact types">
      {variables.map((variable) => {
        const artifactType = data.artifactTypeBindings[variable];
        const picksType =
          data.onBindArtifactTypeBinding !== undefined &&
          bindableArtifactTypes.length > 0;
        const label = artifactType
          ? formatArtifactTypeLabel(artifactType, artifactTypes)
          : ANY_TYPE_LABEL;
        return (
          <div key={variable} {...stylex.props(s.genericTypeRow)}>
            <span {...stylex.props(s.genericTypeLabel)}>
              {variables.length > 1 ? `Type ${variable}` : "Type"}
            </span>
            {picksType ? (
              <Select
                size="dense"
                mono
                disabled={!resettable}
                aria-label={`Bind artifact type ${variable}`}
                title={
                  resettable
                    ? `Bind ${variable} to an artifact type`
                    : "Disconnect this node before changing its type"
                }
                className="nodrag nowheel"
                value={artifactType ? artifactTypeKey(artifactType) : ""}
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
                {bindableArtifactTypes.map((type) => (
                  <option
                    key={artifactTypeKey(type)}
                    value={artifactTypeKey(type)}
                    title={formatArtifactTypeTooltip(type)}
                  >
                    {formatArtifactTypeLabel(type, artifactTypes)}
                  </option>
                ))}
              </Select>
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
              <IconButton
                label={`Reset artifact type ${variable}`}
                title={
                  resettable
                    ? "Reset type"
                    : "Disconnect this node before resetting its type"
                }
                size="xs"
                shape="round"
                className="nodrag nowheel"
                disabled={!resettable || !data.onResetArtifactTypeBinding}
                onClick={() => data.onResetArtifactTypeBinding?.(id, variable)}
              >
                <RotateCcw size={11} />
              </IconButton>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

type ConfigSegment =
  | { kind: "board"; key: string; fields: SchemaField[] }
  | { kind: "group"; key: string; name: string; fields: SchemaField[] };

/**
 * Ungrouped fields stay in schema order on the lattice; a named group gathers
 * its fields where its first one stands, so the order a schema reads in is
 * the order the card reads in.
 */
function configSegments(fields: readonly SchemaField[]): ConfigSegment[] {
  const segments: ConfigSegment[] = [];
  const groups = new Map<string, SchemaField[]>();
  for (const field of fields) {
    if (field.group) {
      const members = groups.get(field.group);
      if (members) {
        members.push(field);
      } else {
        const created = [field];
        groups.set(field.group, created);
        segments.push({
          kind: "group",
          key: `group:${field.group}`,
          name: field.group,
          fields: created,
        });
      }
      continue;
    }
    const last = segments.at(-1);
    if (last?.kind === "board") {
      last.fields.push(field);
    } else {
      segments.push({
        kind: "board",
        key: `board:${field.name}`,
        fields: [field],
      });
    }
  }
  return segments;
}

/** An advanced field folds away only while it still holds its default. */
function isQuietAdvanced(
  field: SchemaField,
  value: unknown,
  invalidFields: ReadonlySet<string | null>,
): boolean {
  if (!field.advanced || invalidFields.has(field.name)) return false;
  return (
    value === undefined ||
    JSON.stringify(value) === JSON.stringify(field.defaultValue)
  );
}

/** A group opens by default when it holds something to fix or to set. */
function groupStartsOpen(
  fields: readonly SchemaField[],
  invalidFields: ReadonlySet<string | null>,
): boolean {
  return fields.some(
    (field) => invalidFields.has(field.name) || !field.advanced,
  );
}

function ConfigBoard({
  id,
  data,
  bricks,
  issues,
  columns,
  cellSize,
  minRows,
  labelHidden,
  layout,
  onLayoutDraft,
  onLayoutCommit,
  connectedPorts,
  onStructureChange,
}: {
  id: string;
  data: WorkflowNodeData;
  bricks: readonly ConfigBrick[];
  issues: readonly ConfigValidationIssue[];
  columns: number;
  cellSize: number;
  minRows: number;
  labelHidden: boolean;
  layout: WorkflowNodeLayout | null;
  onLayoutDraft: (layout: WorkflowNodeLayout | null) => void;
  onLayoutCommit: (layout: WorkflowNodeLayout | null) => void;
  connectedPorts?: ConnectedInputPortMap;
  onStructureChange: () => void;
}) {
  const board = packFieldFootprints(
    bricks.map((brick) => brick.footprint),
    { columns, minRows },
  );
  return (
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
        const { field } = brick;
        return (
          <div
            key={`field:${field.name}`}
            data-testid="config-brick"
            data-config-field={field.name}
            {...stylex.props(s.configBrick)}
            style={{
              gridColumn: `${placement.col + 1} / span ${placement.w}`,
              gridRow: `${placement.row + 1} / span ${placement.h}`,
            }}
          >
            <ConfigField
              field={field}
              value={data.config[field.name]}
              fillHeight={brick.footprint.growY === true}
              labelHidden={labelHidden}
              layout={layout}
              onLayoutDraft={onLayoutDraft}
              onLayoutCommit={onLayoutCommit}
              connectedPorts={connectedPorts}
              onStructureChange={onStructureChange}
              onChange={(value) => data.onConfigChange?.(id, field.name, value)}
            />
            {issues
              .filter((issue) => issue.fieldName === field.name)
              .map((issue, index) => (
                <Notice
                  key={`${field.name}-config-issue-${index}`}
                  tone="danger"
                >
                  {issue.message}
                </Notice>
              ))}
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
 *
 * Which fields show is a function of the config and the wires: a field hidden
 * by its `visibleWhen` keeps its saved value untouched, so turning the
 * condition back on brings back exactly what was there.
 */
export function GenericBody({
  id,
  data,
  bodyHeight,
  layout,
  onLayoutDraft,
  onLayoutCommit,
  connectedPorts,
}: {
  id: string;
  data: WorkflowNodeData;
  bodyHeight: number | null;
  layout: WorkflowNodeLayout | null;
  onLayoutDraft: (layout: WorkflowNodeLayout | null) => void;
  onLayoutCommit: (layout: WorkflowNodeLayout | null) => void;
  connectedPorts?: ConnectedInputPortMap;
}) {
  const grid = useOptionalCanvasGridSettings();
  const [optionsOpen, setOptionsOpen] = React.useState(false);
  const [groupOpen, setGroupOpen] = React.useState<
    Readonly<Record<string, boolean>>
  >({});
  // Composite fields fold and unfold on their own; each fold is a new height.
  const [structureRevision, bumpStructure] = React.useReducer(
    (revision: number) => revision + 1,
    0,
  );
  const updateNodeInternals = useUpdateNodeInternals();
  const allFields = schemaFields(data.spec.config_schema);
  const issues = validateConfig(data.spec.config_schema, data.config);
  const visibleFields = visibleSchemaFields(
    allFields,
    { config: data.config, connectedPorts },
    issues,
  );
  const invalidFields = new Set(issues.map((issue) => issue.fieldName));
  const hiddenAdvanced = visibleFields.filter((field) =>
    isQuietAdvanced(field, data.config[field.name], invalidFields),
  );
  const shownFields = optionsOpen
    ? visibleFields
    : visibleFields.filter((field) => !hiddenAdvanced.includes(field));
  const segments = configSegments(shownFields);
  const isGroupOpen = (segment: ConfigSegment) =>
    segment.kind === "board" ||
    (groupOpen[segment.name] ?? groupStartsOpen(segment.fields, invalidFields));
  const layoutSignature = [
    shownFields.map((field) => field.name).join("|"),
    segments
      .filter((segment) => segment.kind === "group" && isGroupOpen(segment))
      .map((segment) => segment.key)
      .join("|"),
    optionsOpen,
    structureRevision,
  ].join("#");

  React.useLayoutEffect(() => {
    updateNodeInternals(id);
  }, [id, layoutSignature, updateNodeInternals]);

  if (!allFields.length && !issues.length) return null;
  const displayedFields = new Set(shownFields.map((field) => field.name));
  const summaryIssues = issues.filter(
    (issue) =>
      issue.fieldName === null || !displayedFields.has(issue.fieldName),
  );

  const cellSize = grid?.settings.cellSize ?? GRID_CELL_SIZE_DEFAULT;
  const columns = configBoardColumns(resolvedNodeWidth(layout), cellSize);
  const onlyBoard = segments.length === 1 && segments[0]?.kind === "board";
  // A saved body height belongs to the one board a plain node has.
  const minRows =
    bodyHeight === null || !onlyBoard
      ? 0
      : spanFromLength(bodyHeight, cellSize);
  const labelHidden =
    onlyBoard &&
    configFieldLabelIsRedundant(data.spec.title, configBricks(shownFields));
  const boardProps = {
    id,
    data,
    issues,
    columns,
    cellSize,
    labelHidden,
    layout,
    onLayoutDraft,
    onLayoutCommit,
    connectedPorts,
    onStructureChange: bumpStructure,
  };

  return (
    <div {...stylex.props(s.body)}>
      {segments.map((segment) => {
        const bricks = configBricks(segment.fields);
        if (segment.kind === "board") {
          return (
            <ConfigBoard
              key={segment.key}
              bricks={bricks}
              minRows={minRows}
              {...boardProps}
            />
          );
        }
        const open = isGroupOpen(segment);
        const groupIssues = issues.filter((issue) =>
          segment.fields.some((field) => field.name === issue.fieldName),
        ).length;
        return (
          <section
            key={segment.key}
            aria-label={segment.name}
            data-config-group={segment.name}
            {...stylex.props(s.group)}
          >
            <Button
              variant="plain"
              size="text"
              aria-expanded={open}
              className="nodrag nopan nowheel"
              xstyle={s.groupToggle}
              onClick={() =>
                setGroupOpen((current) => ({
                  ...current,
                  [segment.name]: !open,
                }))
              }
            >
              <ChevronRight
                size={12}
                aria-hidden="true"
                {...stylex.props(s.chevron, open ? s.chevronOpen : null)}
              />
              <span {...stylex.props(s.groupTitle)}>{segment.name}</span>
              <span {...stylex.props(s.groupCount)}>
                {segment.fields.length}
              </span>
              {groupIssues ? (
                <span {...stylex.props(s.groupIssues)}>
                  {groupIssues === 1 ? "1 issue" : `${groupIssues} issues`}
                </span>
              ) : null}
            </Button>
            {open ? (
              <ConfigBoard bricks={bricks} minRows={0} {...boardProps} />
            ) : null}
          </section>
        );
      })}
      {hiddenAdvanced.length || optionsOpen ? (
        <Button
          size="xs"
          variant="ghost"
          className="nodrag nopan nowheel"
          onClick={() => setOptionsOpen((open) => !open)}
          aria-expanded={optionsOpen}
        >
          {optionsOpen ? "Hide options" : `Options (${hiddenAdvanced.length})`}
        </Button>
      ) : null}
      {summaryIssues.length ? (
        <Notice tone="danger">
          This node has configuration errors in fields that cannot be edited
          here.
        </Notice>
      ) : null}
    </div>
  );
}

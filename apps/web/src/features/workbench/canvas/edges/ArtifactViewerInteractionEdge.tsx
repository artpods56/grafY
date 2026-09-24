"use client";

import * as stylex from "@stylexjs/stylex";
import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  useReactFlow,
  type EdgeProps,
} from "@xyflow/react";
import { Plus, Trash2 } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";
import type {
  ArtifactViewerInteractionEdge,
  CanvasEdge,
  CanvasNode,
} from "../artifact-viewer";
import type {
  ArtifactInteractionField,
  ArtifactViewerEffect,
} from "../artifact-interactions";
import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import { GRID_CELL_SIZE_DEFAULT } from "../grid-layout";
import { dockedBridgeLayout } from "./docked-connection";
import { EdgeSelectorBlock } from "./EdgeSelectorBlock";
import { applyHandleFanOffset } from "./edge-path";
import { useEdgeIsDocked } from "./useDockedConnection";
import { useEdgeFanOffsets } from "./useEdgeFanOffsets";

const s = stylex.create({
  heading: {
    color: tokens.colorTextEmphasis,
    fontSize: "10px",
    fontWeight: 750,
  },
  popup: {
    display: "grid",
    gap: "10px",
    padding: "11px",
  },
  mapping: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) 16px minmax(0, 1fr) 28px",
    alignItems: "center",
    gap: "7px",
  },
  select: {
    minWidth: 0,
    width: "100%",
    height: "30px",
    paddingInline: "7px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "6px",
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
  },
  arrow: {
    color: tokens.colorSubtle,
    textAlign: "center",
  },
  iconButton: {
    width: "24px",
    height: "24px",
    display: "grid",
    placeItems: "center",
    padding: 0,
    borderWidth: 0,
    borderRadius: "6px",
    backgroundColor: {
      default: tokens.colorSurfaceMuted,
      ":hover": tokens.colorHover,
    },
    color: tokens.colorMuted,
    cursor: "pointer",
  },
  footer: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
  },
  effects: {
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    gap: "7px",
  },
  effect: {
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    color: tokens.colorMuted,
    fontSize: "9px",
    fontWeight: 650,
  },
});

const EFFECTS: readonly ArtifactViewerEffect[] = [
  "filter",
  "highlight",
  "focus",
];

function interactionChipLabel(
  effects: readonly ArtifactViewerEffect[],
): string {
  return effects.length ? `follow · ${effects.join(" + ")}` : "follow";
}

function fieldOptionLabel(field: ArtifactInteractionField): string {
  return `${field.title} · ${field.valueType}`;
}

function FieldSelect({
  ariaLabel,
  value,
  fields,
  onChange,
}: {
  ariaLabel: string;
  value: string;
  fields: readonly ArtifactInteractionField[];
  onChange: (value: string) => void;
}) {
  const known = fields.some((field) => field.id === value);
  const empty = fields.length === 0;
  return (
    <select
      aria-label={ariaLabel}
      title={value || ariaLabel}
      value={value}
      disabled={empty && !value}
      {...stylex.props(s.select)}
      onChange={(event) => onChange(event.currentTarget.value)}
    >
      <option value="">{empty ? "No fields yet" : "Choose field"}</option>
      {!known && value ? <option value={value}>{value}</option> : null}
      {fields.map((field) => (
        <option key={field.id} value={field.id}>
          {fieldOptionLabel(field)}
        </option>
      ))}
    </select>
  );
}

export default function ArtifactViewerInteractionEdgeControl({
  id,
  data,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  style,
  selected,
}: EdgeProps<ArtifactViewerInteractionEdge>) {
  const { deleteElements } = useReactFlow<CanvasNode, CanvasEdge>();
  const docked = useEdgeIsDocked(id);
  const cellSize =
    useOptionalCanvasGridSettings()?.settings.cellSize ??
    GRID_CELL_SIZE_DEFAULT;
  const fan = useEdgeFanOffsets(id, sourcePosition, targetPosition);
  const source = applyHandleFanOffset(
    { x: sourceX, y: sourceY },
    sourcePosition,
    fan.source,
  );
  const target = applyHandleFanOffset(
    { x: targetX, y: targetY },
    targetPosition,
    fan.target,
  );
  const [path, labelX, labelY] = getBezierPath({
    sourceX: source.x,
    sourceY: source.y,
    sourcePosition,
    targetX: target.x,
    targetY: target.y,
    targetPosition,
  });
  const binding = data?.binding;
  if (!binding) {
    return (
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        interactionWidth={24}
        style={style}
      />
    );
  }
  const sourceFields = data?.sourceFields ?? [];
  const targetFields = data?.targetFields ?? [];
  const label = interactionChipLabel(binding.effects);
  const bridge = docked ? dockedBridgeLayout(source, target, cellSize) : null;

  const updateBinding = (
    update: Partial<Pick<typeof binding, "mappings" | "effects">>,
  ) => {
    data?.onBindingChange?.(binding.id, { ...binding, ...update });
  };

  return (
    <>
      <BaseEdge
        id={id}
        path={
          docked ? `M${source.x},${source.y} L${target.x},${target.y}` : path
        }
        markerEnd={docked ? undefined : markerEnd}
        interactionWidth={24}
        style={{
          ...style,
          opacity: docked ? 0 : selected ? 0.95 : 0.72,
          strokeWidth: selected ? 2.5 : (style?.strokeWidth ?? 2),
        }}
      />
      <EdgeLabelRenderer>
        <EdgeSelectorBlock
          anchor={bridge?.anchor ?? { x: labelX, y: labelY }}
          selected={selected}
          label={label}
          docked={docked}
          width={bridge?.width}
          height={bridge?.height}
          bendAriaLabel={`Bend viewer follow ${label}`}
          bendHandlers={{}}
          editAriaLabel="Configure viewer interaction"
          editTitle="Configure field mapping and effects"
          removeAriaLabel="Remove viewer interaction"
          onRemove={() => {
            void deleteElements({ edges: [{ id }] });
          }}
        >
          <div {...stylex.props(s.popup)}>
            <span {...stylex.props(s.heading)}>Field mapping</span>
            {binding.mappings.map((mapping, index) => (
              <div key={index} {...stylex.props(s.mapping)}>
                <FieldSelect
                  ariaLabel={`Source field ${index + 1}`}
                  value={mapping.sourceField}
                  fields={sourceFields}
                  onChange={(sourceField) => {
                    const mappings = binding.mappings.map(
                      (candidate, candidateIndex) =>
                        candidateIndex === index
                          ? { ...candidate, sourceField }
                          : candidate,
                    );
                    updateBinding({ mappings });
                  }}
                />
                <span aria-hidden="true" {...stylex.props(s.arrow)}>
                  →
                </span>
                <FieldSelect
                  ariaLabel={`Target field ${index + 1}`}
                  value={mapping.targetField}
                  fields={targetFields}
                  onChange={(targetField) => {
                    const mappings = binding.mappings.map(
                      (candidate, candidateIndex) =>
                        candidateIndex === index
                          ? { ...candidate, targetField }
                          : candidate,
                    );
                    updateBinding({ mappings });
                  }}
                />
                <button
                  type="button"
                  aria-label={`Remove field mapping ${index + 1}`}
                  title="Remove mapping"
                  disabled={binding.mappings.length === 1}
                  {...stylex.props(s.iconButton)}
                  onClick={() =>
                    updateBinding({
                      mappings: binding.mappings.filter(
                        (_, candidateIndex) => candidateIndex !== index,
                      ),
                    })
                  }
                >
                  <Trash2 size={11} aria-hidden="true" />
                </button>
              </div>
            ))}
            <div {...stylex.props(s.footer)}>
              <span {...stylex.props(s.effects)}>
                {EFFECTS.map((effect) => (
                  <label key={effect} {...stylex.props(s.effect)}>
                    <input
                      type="checkbox"
                      checked={binding.effects.includes(effect)}
                      onChange={(event) => {
                        const effects = event.currentTarget.checked
                          ? [...binding.effects, effect]
                          : binding.effects.filter(
                              (candidate) => candidate !== effect,
                            );
                        if (effects.length) updateBinding({ effects });
                      }}
                    />
                    {effect}
                  </label>
                ))}
              </span>
              <button
                type="button"
                aria-label="Add field mapping"
                title="Add mapping"
                disabled={binding.mappings.length >= 8}
                {...stylex.props(s.iconButton)}
                onClick={() =>
                  updateBinding({
                    mappings: [
                      ...binding.mappings,
                      { sourceField: "", targetField: "" },
                    ],
                  })
                }
              >
                <Plus size={12} aria-hidden="true" />
              </button>
            </div>
          </div>
        </EdgeSelectorBlock>
      </EdgeLabelRenderer>
    </>
  );
}

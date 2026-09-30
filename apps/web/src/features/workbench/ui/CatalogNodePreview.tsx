"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type { SchemaField } from "../canvas/config-schema";
import { PORT_RING_REACH, portMarkStyle } from "../canvas/handle-style";
import { artifactTypeColor } from "../canvas/nodes.css";
import { portArtifactType, portHasInstancePlugs } from "../canvas/types";

export function portKey(port: Port): string {
  return `${port.direction}:${port.name}`;
}

export function artifactTitleFor(registry: NodeRegistry, port: Port): string {
  const artifactType = portArtifactType(port);
  if (!artifactType) return "Any artifact";
  return (
    registry.artifact_types.find(
      (artifact) =>
        artifact.key.id === artifactType.id &&
        artifact.key.schema_version === artifactType.schema_version,
    )?.title ?? artifactType.id
  );
}

export function fieldTypeLabel(field: SchemaField): string {
  if (field.enumValues?.length) return "choice";
  if (field.format === "textarea") return "multiline text";
  if (field.type === "number-tuple") {
    return `${field.items.length}-number tuple`;
  }
  if (field.type === "string-list") return "text list";
  return field.type;
}

/**
 * The preview is a node as it sits on the canvas, picked up: its name above
 * the plate, port names inside the plate's edges, and each port's ring out on
 * a stem (see `PortBall`).
 */
const s = stylex.create({
  previewNode: {
    position: "relative",
    display: "grid",
    width: "300px",
    flexShrink: 0,
    overflow: "visible",
    color: tokens.colorText,
  },
  previewHeader: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    height: "24px",
    paddingInline: "2px",
  },
  previewTitle: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
    letterSpacing: "-0.01em",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  previewPlate: {
    position: "relative",
    overflow: "visible",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNodeActive,
  },
  previewRail: {
    display: "grid",
    paddingBlock: "2px",
  },
  previewRailRow: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
    alignItems: "stretch",
    height: "36px",
  },
  previewPortSlot: {
    position: "relative",
    minWidth: 0,
    display: "flex",
    alignItems: "center",
  },
  previewPortSlotOut: {
    justifyContent: "flex-end",
  },
  previewTab: {
    display: "flex",
    alignItems: "center",
    gap: "4px",
    maxWidth: "calc(100% - 8px)",
    height: "22px",
    paddingInline: "10px 8px",
    borderWidth: 0,
    borderRadius: tokens.radiusSm,
    backgroundColor: "transparent",
    color: tokens.colorMuted,
    fontFamily: "inherit",
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
  },
  previewTabButton: {
    cursor: "pointer",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: { default: tokens.colorMuted, ":hover": tokens.colorText },
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
  },
  previewTabSelected: {
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorText,
  },
  previewTabIn: {},
  previewTabOut: {
    flexDirection: "row-reverse",
    paddingInline: "8px 10px",
  },
  previewTabLabel: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  previewTabShape: {
    flexShrink: 0,
    color: tokens.colorSubtle,
  },
  // The row sits inside the plate's 1px border: the ring's centre is 23px
  // outside the plate, its stem runs back to the plate's edge.
  previewStem: {
    position: "absolute",
    top: "50%",
    width: "23px",
    height: "1px",
    marginTop: "-0.5px",
    opacity: 0.5,
    pointerEvents: "none",
  },
  previewStemIn: { left: "-24px" },
  previewStemOut: { right: "-24px" },
  previewHandle: {
    position: "absolute",
    top: "50%",
    width: "10px",
    height: "10px",
    marginTop: "-5px",
    boxSizing: "border-box",
    borderWidth: 2,
    borderStyle: "solid",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurface,
    pointerEvents: "none",
  },
  previewHandleIn: {
    left: "-29px",
  },
  previewHandleOut: {
    right: "-29px",
  },
  previewEmptyPort: {
    paddingInline: "12px",
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 700,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  previewBody: {
    display: "grid",
    gap: "6px",
    padding: "6px 14px 14px",
  },
  previewField: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: "10px",
    minHeight: "22px",
    padding: "5px 8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "5px",
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
  previewFieldMeta: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "9px",
  },
  previewBodyEmpty: {
    minHeight: "18px",
  },
});

export const CATALOG_PREVIEW_WIDTH = 300;
/** The name row above the plate, then the plate's border and rail padding. */
const PREVIEW_HEADER_HEIGHT = 24 + 1;
const PREVIEW_RAIL_PADDING = 2;
const PREVIEW_ROW_HEIGHT = 36;

export function catalogPreviewInputHandleOffset(
  spec: NodeSpec,
  portName: string | undefined,
): { x: number; y: number } {
  const index = Math.max(
    0,
    spec.inputs.findIndex((port) => port.name === portName),
  );
  // A connection meets the ring's outer edge, a ring's reach off the plate.
  return {
    x: -PORT_RING_REACH,
    y:
      PREVIEW_HEADER_HEIGHT +
      PREVIEW_RAIL_PADDING +
      index * PREVIEW_ROW_HEIGHT +
      PREVIEW_ROW_HEIGHT / 2,
  };
}

export function catalogPreviewOutputHandleOffset(
  spec: NodeSpec,
  portName: string | undefined,
): { x: number; y: number } {
  const index = Math.max(
    0,
    spec.outputs.findIndex((port) => port.name === portName),
  );
  return {
    x: CATALOG_PREVIEW_WIDTH + PORT_RING_REACH,
    y:
      PREVIEW_HEADER_HEIGHT +
      PREVIEW_RAIL_PADDING +
      index * PREVIEW_ROW_HEIGHT +
      PREVIEW_ROW_HEIGHT / 2,
  };
}

interface CatalogNodePreviewProps {
  spec: NodeSpec;
  registry: NodeRegistry;
  fields: readonly SchemaField[];
  selectedPortKey?: string | null;
  onSelectPort?: (port: Port) => void;
}

function PreviewPort({
  port,
  direction,
  registry,
  emptyLabel,
  selected,
  onSelect,
}: {
  port: Port | undefined;
  direction: "input" | "output";
  registry: NodeRegistry;
  emptyLabel: string | null;
  selected: boolean;
  onSelect?: (port: Port) => void;
}) {
  const output = direction === "output";
  if (!port) {
    return (
      <div
        {...stylex.props(
          s.previewPortSlot,
          output ? s.previewPortSlotOut : null,
        )}
      >
        {emptyLabel ? (
          <span {...stylex.props(s.previewEmptyPort)}>{emptyLabel}</span>
        ) : null}
      </div>
    );
  }

  const artifactType = portArtifactType(port);
  const color = artifactType
    ? artifactTypeColor(artifactType.id, tokens.colorAccent)
    : tokens.colorAccent;
  const multiple = port.shape === "many" || portHasInstancePlugs(port);
  const title = `${artifactTitleFor(registry, port)} · ${multiple ? "sequence" : "single value"}`;
  const tab = (
    <>
      <span {...stylex.props(s.previewTabLabel)}>
        {port.title ?? port.name}
      </span>
      {port.direction === "input" && port.required ? (
        <span {...stylex.props(s.previewTabShape)}>*</span>
      ) : null}
      {port.shape === "many" ? (
        <span {...stylex.props(s.previewTabShape)}>· many</span>
      ) : null}
    </>
  );

  return (
    <div
      title={title}
      {...stylex.props(s.previewPortSlot, output ? s.previewPortSlotOut : null)}
    >
      {onSelect ? (
        <button
          type="button"
          aria-pressed={selected}
          aria-label={`Show nodes that work with ${port.title ?? port.name}`}
          {...stylex.props(
            s.previewTab,
            output ? s.previewTabOut : s.previewTabIn,
            s.previewTabButton,
            selected ? s.previewTabSelected : null,
          )}
          onClick={() => onSelect(port)}
        >
          {tab}
        </button>
      ) : (
        <span
          {...stylex.props(
            s.previewTab,
            output ? s.previewTabOut : s.previewTabIn,
            selected ? s.previewTabSelected : null,
          )}
        >
          {tab}
        </span>
      )}
      <span
        aria-hidden="true"
        {...stylex.props(
          s.previewStem,
          output ? s.previewStemOut : s.previewStemIn,
        )}
        style={{ backgroundColor: color }}
      />
      <span
        aria-hidden="true"
        {...stylex.props(
          s.previewHandle,
          output ? s.previewHandleOut : s.previewHandleIn,
        )}
        style={portMarkStyle(color, multiple)}
      />
    </div>
  );
}

export function CatalogNodePreview({
  spec,
  registry,
  fields,
  selectedPortKey,
  onSelectPort,
}: CatalogNodePreviewProps) {
  const visibleFields = fields.slice(0, 4);
  const rowCount = Math.max(spec.inputs.length, spec.outputs.length, 1);
  const inputCountLabel = `${spec.inputs.length} ${spec.inputs.length === 1 ? "input" : "inputs"}`;
  const outputCountLabel = `${spec.outputs.length} ${spec.outputs.length === 1 ? "output" : "outputs"}`;

  return (
    <article
      aria-label={`${spec.title}: ${inputCountLabel}, ${outputCountLabel}`}
      {...stylex.props(s.previewNode)}
    >
      <header {...stylex.props(s.previewHeader)}>
        <span {...stylex.props(s.previewTitle)}>{spec.title}</span>
      </header>
      <div {...stylex.props(s.previewPlate)}>
        <div {...stylex.props(s.previewRail)}>
          {Array.from({ length: rowCount }, (_, index) => (
            <div
              key={`preview-rail-${index}`}
              {...stylex.props(s.previewRailRow)}
            >
              <PreviewPort
                port={spec.inputs[index]}
                direction="input"
                registry={registry}
                selected={Boolean(
                  spec.inputs[index] &&
                  selectedPortKey === portKey(spec.inputs[index]!),
                )}
                onSelect={onSelectPort}
                emptyLabel={
                  index === 0 && spec.inputs.length === 0 ? "Start" : null
                }
              />
              <PreviewPort
                port={spec.outputs[index]}
                direction="output"
                registry={registry}
                selected={Boolean(
                  spec.outputs[index] &&
                  selectedPortKey === portKey(spec.outputs[index]!),
                )}
                onSelect={onSelectPort}
                emptyLabel={
                  index === 0 && spec.outputs.length === 0 ? "End" : null
                }
              />
            </div>
          ))}
        </div>
        {visibleFields.length ? (
          <div {...stylex.props(s.previewBody)}>
            {visibleFields.map((field) => (
              <div key={field.name} {...stylex.props(s.previewField)}>
                <span>{field.title}</span>
                <span {...stylex.props(s.previewFieldMeta)}>
                  {fieldTypeLabel(field)}
                </span>
              </div>
            ))}
            {fields.length > visibleFields.length ? (
              <div {...stylex.props(s.previewField)}>
                <span>+{fields.length - visibleFields.length} more</span>
              </div>
            ) : null}
          </div>
        ) : (
          <div {...stylex.props(s.previewBodyEmpty)} />
        )}
      </div>
    </article>
  );
}

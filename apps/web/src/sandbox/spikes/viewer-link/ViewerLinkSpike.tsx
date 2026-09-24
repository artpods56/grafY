"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Popover } from "@base-ui/react/popover";
import {
  CircleHelp,
  Copy,
  Link2,
  MoreHorizontal,
  Trash2,
  X,
} from "lucide-react";

import { overlay } from "@/lib/stylex/overlay.stylex";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { portMarkStyle } from "@/features/workbench/canvas/handle-style";
import { artifactTypeColor } from "@/features/workbench/canvas/nodes.css";
import {
  canvasNodeInteractionProps,
  nodeChrome,
} from "@/features/workbench/canvas/nodes/CanvasNodeChrome";
import {
  CatalogNodePreview,
  portKey,
} from "@/features/workbench/ui/CatalogNodePreview";
import { workbenchStyles } from "@/features/workbench/ui/Workbench.styles";
import { SandboxShell } from "../../SandboxShell";
import {
  MAP_DOCUMENT_SPEC,
  MAP_PORT,
  NOTES_PORT,
  PARCELS_REGISTRY,
  PARCEL_ROWS,
  QUERY_PARCELS_FIELDS,
  QUERY_PARCELS_SPEC,
  ROWS_PORT,
  SURVEY_NOTES_SPEC,
} from "../../fixtures/parcels";

type ApproachId = "drag" | "menu" | "rail" | "send";
type SceneId = "pair" | "markdown";
type Phase = "idle" | "carrying" | "menu" | "aim" | "mapping" | "live";
type ViewerKind = "table" | "map" | "markdown";

const APPROACHES: { id: ApproachId; label: string; note: string }[] = [
  {
    id: "drag",
    label: "Drag a row",
    note: "Drag a table row onto the map. The record is the handle — not a port.",
  },
  {
    id: "menu",
    label: "Link views in ⋯",
    note: "Select the table, open ⋯, choose Link views…, then click the map.",
  },
  {
    id: "rail",
    label: "Selection toolbar",
    note: "Select both viewers. Link views appears on the same toolbar as Run.",
  },
  {
    id: "send",
    label: "Send to…",
    note: "Click a row. Send to… lists other viewers that can follow this selection.",
  },
];

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";
const TABLE_COLOR = artifactTypeColor("table.data", tokens.colorAccent);
const MAP_COLOR = artifactTypeColor("geo.map_document", tokens.colorAccent);
const MARKDOWN_COLOR = artifactTypeColor("text.markdown", tokens.colorAccent);

const s = stylex.create({
  controls: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    flexWrap: "wrap",
    marginBottom: "20px",
  },
  sceneButton: {
    height: "28px",
    paddingInline: "10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
    },
    color: tokens.colorText,
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
  },
  sceneButtonActive: {
    backgroundColor: tokens.colorAccentSoft,
  },
  board: {
    display: "flex",
    alignItems: "flex-start",
    gap: "28px",
  },
  column: {
    display: "grid",
    gap: "16px",
    justifyItems: "start",
  },
  pair: {
    position: "relative",
    display: "flex",
    alignItems: "flex-start",
    gap: "28px",
  },
  card: {
    position: "relative",
    width: "300px",
    flexShrink: 0,
    overflow: "visible",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNodeRaised,
    color: tokens.colorText,
  },
  cardTarget: {
    outlineWidth: 1,
    outlineStyle: "dashed",
    outlineColor: tokens.colorBorderStrong,
    outlineOffset: "6px",
  },
  rail: {
    display: "grid",
    paddingBlock: "2px",
  },
  railRow: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
    alignItems: "stretch",
    height: "36px",
  },
  portSlot: {
    position: "relative",
    minWidth: 0,
    display: "flex",
    alignItems: "center",
  },
  tab: {
    display: "flex",
    alignItems: "center",
    height: "24px",
    maxWidth: "calc(100% - 10px)",
    paddingInline: "14px 12px",
    borderWidth: 0,
    borderRadius: "0 9999px 9999px 0",
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
  },
  handle: {
    position: "absolute",
    top: "50%",
    left: "-5px",
    width: "10px",
    height: "10px",
    boxSizing: "border-box",
    transform: "translateY(-50%)",
    borderWidth: 2,
    borderStyle: "solid",
    borderRadius: "99px",
    backgroundColor: tokens.colorSurface,
    pointerEvents: "none",
  },
  viewport: {
    minHeight: 0,
    overflow: "hidden",
    padding: "0 12px 10px",
  },
  follow: {
    height: "18px",
    paddingInline: "7px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: "9px",
    fontWeight: 700,
    whiteSpace: "nowrap",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: tokens.fontSizeXs,
  },
  tableHead: {
    backgroundColor: tokens.colorSurfaceSunken,
  },
  tableHeadCell: {
    minWidth: "52px",
    padding: "7px 8px",
    borderRightWidth: 1,
    borderRightStyle: "solid",
    borderRightColor: tokens.colorDivider,
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    textAlign: "left",
    verticalAlign: "bottom",
  },
  tableHeadTitle: {
    display: "block",
    color: tokens.colorTextEmphasis,
    fontWeight: 700,
  },
  tableHeadType: {
    display: "block",
    marginTop: "2px",
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "9px",
    fontWeight: 500,
  },
  tableIndex: {
    width: "28px",
    minWidth: "28px",
    padding: "6px 6px",
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
    padding: "6px 8px",
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
  },
  tableRow: {
    cursor: "pointer",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
    },
  },
  tableRowSelected: {
    backgroundColor: tokens.colorAccentSoft,
  },
  tableRowCarrying: {
    outlineWidth: 1,
    outlineStyle: "dashed",
    outlineColor: tokens.colorBorderStrong,
    outlineOffset: "-1px",
  },
  markdown: {
    padding: "4px 2px 8px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
  },
  markdownTitle: {
    marginBottom: "6px",
    color: tokens.colorTextEmphasis,
    fontWeight: 600,
  },
  gutter: {
    position: "relative",
    width: "220px",
    flexShrink: 0,
    alignSelf: "stretch",
    display: "grid",
    placeItems: "center",
  },
  chip: {
    minHeight: "24px",
    display: "inline-flex",
    alignItems: "stretch",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "8px",
    backgroundColor: tokens.colorSurfaceRaised,
    boxShadow: tokens.shadowNode,
    color: tokens.colorMuted,
    overflow: "hidden",
  },
  chipButton: {
    minHeight: "24px",
    display: "inline-flex",
    alignItems: "center",
    gap: "5px",
    paddingInline: "8px",
    borderWidth: 0,
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
    },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: "9px",
    fontWeight: 700,
    whiteSpace: "nowrap",
  },
  chipRemove: {
    width: "24px",
    borderWidth: 0,
    borderLeftWidth: 1,
    borderLeftStyle: "solid",
    borderLeftColor: tokens.colorBorder,
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorDangerHover,
    },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorDanger },
    cursor: "pointer",
  },
  mapping: {
    width: "280px",
    display: "grid",
    gap: "10px",
    padding: "11px",
  },
  mappingTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: "10px",
    fontWeight: 750,
  },
  mappingRow: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) 16px minmax(0, 1fr)",
    alignItems: "center",
    gap: "7px",
  },
  mappingInput: {
    minWidth: 0,
    height: "30px",
    paddingInline: "9px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "6px",
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    fontFamily: MONO,
    fontSize: "10px",
  },
  mappingArrow: {
    color: tokens.colorSubtle,
    textAlign: "center",
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
  mappingActions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: "8px",
  },
  ghostButton: {
    height: "28px",
    paddingInline: "9px",
    borderWidth: 0,
    borderRadius: "5px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
    },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
  },
  primaryButton: {
    height: "28px",
    paddingInline: "9px",
    borderWidth: 0,
    borderRadius: "5px",
    backgroundColor: {
      default: tokens.colorAccent,
      ":hover": tokens.colorAccentHover,
    },
    color: tokens.colorOnAccent,
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
    fontWeight: 700,
  },
  hint: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
    textAlign: "center",
  },
  sendMenu: {
    position: "absolute",
    zIndex: 4,
    top: "118px",
    left: "40px",
    minWidth: "168px",
    padding: "4px",
  },
});

function ArtifactPort({ color, label }: { color: string; label: string }) {
  return (
    <div {...stylex.props(s.railRow)}>
      <div {...stylex.props(s.portSlot)}>
        <span {...stylex.props(s.tab)}>{label}</span>
        <span
          aria-hidden="true"
          {...stylex.props(s.handle)}
          style={portMarkStyle(color)}
        />
      </div>
      <div />
    </div>
  );
}

function ViewerHeader({
  selected,
  following,
  showLinkAction,
  onFollow,
  onLinkViews,
}: {
  selected: boolean;
  following: boolean;
  showLinkAction: boolean;
  onFollow?: () => void;
  onLinkViews?: () => void;
}) {
  return (
    <header {...stylex.props(nodeChrome.header)}>
      <span {...stylex.props(nodeChrome.title)}>Artifact Viewer</span>
      {following && onFollow ? (
        <button type="button" {...stylex.props(s.follow)} onClick={onFollow}>
          Following · id
        </button>
      ) : null}
      {selected ? (
        <>
          <Popover.Root>
            <Popover.Trigger
              type="button"
              aria-label="About Artifact Viewer"
              {...canvasNodeInteractionProps(
                stylex.props(nodeChrome.headerButton),
              )}
            >
              <CircleHelp size={13} />
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Positioner side="top" align="start" sideOffset={7}>
                <Popover.Popup
                  {...canvasNodeInteractionProps(
                    stylex.props(overlay.popup, nodeChrome.helpPopup),
                  )}
                >
                  <span {...stylex.props(nodeChrome.helpTitle)}>
                    Artifact Viewer
                  </span>
                  <span {...stylex.props(nodeChrome.helpDescription)}>
                    Presentation-only preview. Connect an output and the
                    renderer follows that artifact type.
                  </span>
                </Popover.Popup>
              </Popover.Positioner>
            </Popover.Portal>
          </Popover.Root>
          <Popover.Root>
            <Popover.Trigger
              type="button"
              aria-label="Actions for Artifact Viewer"
              {...canvasNodeInteractionProps(
                stylex.props(nodeChrome.headerButton),
              )}
            >
              <MoreHorizontal size={13} />
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Positioner side="bottom" align="end" sideOffset={6}>
                <Popover.Popup
                  {...canvasNodeInteractionProps(
                    stylex.props(overlay.popup, nodeChrome.nodeMenu),
                  )}
                >
                  {showLinkAction && onLinkViews ? (
                    <button
                      type="button"
                      {...stylex.props(overlay.item, nodeChrome.nodeMenuItem)}
                      onClick={onLinkViews}
                    >
                      <Link2 size={13} />
                      Link views…
                    </button>
                  ) : null}
                  <button
                    type="button"
                    {...stylex.props(
                      overlay.item,
                      nodeChrome.nodeMenuItem,
                      nodeChrome.nodeMenuItemDanger,
                    )}
                  >
                    <Trash2 size={13} />
                    Delete node
                  </button>
                </Popover.Popup>
              </Popover.Positioner>
            </Popover.Portal>
          </Popover.Root>
        </>
      ) : null}
    </header>
  );
}

function TablePreview({
  selectedRow,
  carrying,
  draggable,
  onRow,
  onDragStart,
  onDragEnd,
}: {
  selectedRow: number;
  carrying: boolean;
  draggable: boolean;
  onRow: (index: number) => void;
  onDragStart?: (index: number) => void;
  onDragEnd?: () => void;
}) {
  return (
    <table {...stylex.props(s.table)}>
      <thead {...stylex.props(s.tableHead)}>
        <tr>
          <th {...stylex.props(s.tableIndex)} />
          {["id", "block", "facing", "use"].map((name) => (
            <th key={name} {...stylex.props(s.tableHeadCell)}>
              <span {...stylex.props(s.tableHeadTitle)}>{name}</span>
              <span {...stylex.props(s.tableHeadType)}>text</span>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {PARCEL_ROWS.map((row, index) => (
          <tr
            key={row.id}
            draggable={draggable}
            onClick={() => onRow(index)}
            onDragStart={(event) => {
              event.dataTransfer.setData("text/plain", row.id);
              event.dataTransfer.effectAllowed = "copy";
              onDragStart?.(index);
            }}
            onDragEnd={onDragEnd}
            {...stylex.props(
              s.tableRow,
              selectedRow === index ? s.tableRowSelected : null,
              carrying && selectedRow === index ? s.tableRowCarrying : null,
            )}
          >
            <td {...stylex.props(s.tableIndex)}>{index + 1}</td>
            <td {...stylex.props(s.tableCell)}>{row.id}</td>
            <td {...stylex.props(s.tableCell)}>{row.block}</td>
            <td {...stylex.props(s.tableCell)}>{row.facing}</td>
            <td {...stylex.props(s.tableCell)}>{row.use}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function MapPreview({
  selectedRow,
  live,
}: {
  selectedRow: number;
  live: boolean;
}) {
  const parcels = [
    { id: "12", x: 16, y: 14, w: 68, h: 46 },
    { id: "14", x: 92, y: 26, w: 82, h: 56 },
    { id: "18", x: 24, y: 70, w: 114, h: 34 },
    { id: "21", x: 186, y: 12, w: 70, h: 90 },
  ];
  return (
    <svg viewBox="0 0 276 136" width="100%" height="136">
      <rect
        width="276"
        height="136"
        fill="var(--grafy-map-land, transparent)"
      />
      <path
        d="M0 68 H276"
        stroke="currentColor"
        strokeWidth="5"
        opacity="0.22"
      />
      <path
        d="M148 0 V136"
        stroke="currentColor"
        strokeWidth="4"
        opacity="0.22"
      />
      {parcels.map((parcel, index) => {
        const active = live && selectedRow === index;
        return (
          <g key={parcel.id}>
            <rect
              x={parcel.x}
              y={parcel.y}
              width={parcel.w}
              height={parcel.h}
              rx="2"
              fill={active ? "currentColor" : "transparent"}
              fillOpacity={active ? 0.14 : 0}
              stroke="currentColor"
              strokeOpacity={active ? 0.85 : 0.35}
            />
            <text
              x={parcel.x + 8}
              y={parcel.y + 16}
              fill="currentColor"
              fontSize="10"
              fontWeight="700"
              opacity={active ? 1 : 0.65}
            >
              {parcel.id}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function MappingSheet({
  onDone,
  onCancel,
}: {
  onDone: () => void;
  onCancel: () => void;
}) {
  return (
    <div {...stylex.props(overlay.popup, s.mapping)}>
      <div {...stylex.props(s.mappingTitle)}>Field mapping</div>
      <div {...stylex.props(s.mappingRow)}>
        <input
          readOnly
          value="id"
          aria-label="Source field"
          {...stylex.props(s.mappingInput)}
        />
        <span {...stylex.props(s.mappingArrow)}>→</span>
        <input
          readOnly
          value="id"
          aria-label="Target field"
          {...stylex.props(s.mappingInput)}
        />
      </div>
      <div {...stylex.props(s.effects)}>
        <label {...stylex.props(s.effect)}>
          <input type="checkbox" disabled />
          filter
        </label>
        <label {...stylex.props(s.effect)}>
          <input type="checkbox" defaultChecked readOnly />
          highlight
        </label>
        <label {...stylex.props(s.effect)}>
          <input type="checkbox" defaultChecked readOnly />
          focus
        </label>
      </div>
      <div {...stylex.props(s.mappingActions)}>
        <button
          type="button"
          {...stylex.props(s.ghostButton)}
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          type="button"
          {...stylex.props(s.primaryButton)}
          onClick={onDone}
        >
          Link
        </button>
      </div>
    </div>
  );
}

function MappingChip({
  onOpen,
  onUnlink,
}: {
  onOpen: () => void;
  onUnlink: () => void;
}) {
  return (
    <div {...stylex.props(s.chip)}>
      <button type="button" {...stylex.props(s.chipButton)} onClick={onOpen}>
        <Link2 size={10} aria-hidden="true" />
        highlight + focus
      </button>
      <button
        type="button"
        aria-label="Remove viewer interaction"
        {...stylex.props(s.chipRemove)}
        onClick={onUnlink}
      >
        <X size={11} />
      </button>
    </div>
  );
}

function ViewerCard({
  kind,
  selected,
  dropTarget,
  following,
  selectedRow,
  carrying,
  live,
  showLinkAction,
  draggableRows,
  onSelect,
  onFollow,
  onLinkViews,
  onRow,
  onDragStart,
  onDragEnd,
  onDrop,
}: {
  kind: ViewerKind;
  selected: boolean;
  dropTarget: boolean;
  following: boolean;
  selectedRow: number;
  carrying: boolean;
  live: boolean;
  showLinkAction: boolean;
  draggableRows: boolean;
  onSelect: () => void;
  onFollow?: () => void;
  onLinkViews?: () => void;
  onRow?: (index: number) => void;
  onDragStart?: (index: number) => void;
  onDragEnd?: () => void;
  onDrop?: () => void;
}) {
  const color =
    kind === "table"
      ? TABLE_COLOR
      : kind === "map"
        ? MAP_COLOR
        : MARKDOWN_COLOR;
  return (
    <article
      aria-label="Artifact viewer"
      onClick={onSelect}
      onDragOver={
        dropTarget
          ? (event) => {
              event.preventDefault();
            }
          : undefined
      }
      onDrop={
        onDrop
          ? (event) => {
              event.preventDefault();
              onDrop();
            }
          : undefined
      }
      {...stylex.props(s.card, dropTarget ? s.cardTarget : null)}
    >
      <ViewerHeader
        selected={selected}
        following={following}
        showLinkAction={showLinkAction}
        onFollow={onFollow}
        onLinkViews={onLinkViews}
      />
      <div {...stylex.props(s.rail)}>
        <ArtifactPort color={color} label="Artifact" />
      </div>
      <div {...stylex.props(s.viewport)}>
        {kind === "table" ? (
          <TablePreview
            selectedRow={selectedRow}
            carrying={carrying}
            draggable={draggableRows}
            onRow={onRow ?? (() => undefined)}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
          />
        ) : kind === "map" ? (
          <MapPreview selectedRow={selectedRow} live={live} />
        ) : (
          <div {...stylex.props(s.markdown)}>
            <div {...stylex.props(s.markdownTitle)}>Survey notes</div>
            Parcel 12 sits on the north lot. Access from the east road.
          </div>
        )}
      </div>
    </article>
  );
}

function stepNote(approach: ApproachId, scene: SceneId, phase: Phase): string {
  const base = APPROACHES.find((item) => item.id === approach)?.note ?? "";
  if (scene === "markdown") {
    return "Markdown cannot emit a key-selection. No Link views, no Send to…, no row to drag.";
  }
  if (phase === "carrying") return "Drop the row on the map.";
  if (phase === "aim") {
    return approach === "rail"
      ? "Both selected. Press Link views on the toolbar."
      : "Click the map.";
  }
  if (phase === "mapping") return "Confirm which fields match, then Link.";
  if (phase === "live") {
    return "Click another row. The matching parcel lights up. The chip is the link — not a port.";
  }
  return base;
}

export function ViewerLinkSpike() {
  const [approach, setApproach] = React.useState<ApproachId>("drag");
  const [scene, setScene] = React.useState<SceneId>("pair");
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [selected, setSelected] = React.useState<"left" | "map" | "both">(
    "left",
  );
  const [selectedRow, setSelectedRow] = React.useState(0);
  const [sendOpen, setSendOpen] = React.useState(false);
  const dropped = React.useRef(false);
  const pair = scene === "pair";
  const leftKind: ViewerKind = pair ? "table" : "markdown";
  const live = phase === "live";
  const mapping = phase === "mapping";
  const carrying = approach === "drag" && phase === "carrying";
  const aiming = phase === "aim";
  const bothSelected = approach === "rail" && (selected === "both" || aiming);

  const reset = React.useCallback(() => {
    setPhase("idle");
    setSelected("left");
    setSendOpen(false);
  }, []);

  const pickApproach = (id: ApproachId) => {
    setApproach(id);
    reset();
  };

  const finishDrop = () => {
    if (!pair) return;
    if (phase === "carrying" || phase === "aim") {
      dropped.current = true;
      setPhase("mapping");
    }
  };

  return (
    <SandboxShell
      title="Link viewers"
      note={stepNote(approach, scene, phase)}
      variants={APPROACHES}
      activeVariant={approach}
      onVariant={(id) => pickApproach(id as ApproachId)}
    >
      <div {...stylex.props(s.controls)}>
        <button
          type="button"
          {...stylex.props(
            s.sceneButton,
            scene === "pair" ? s.sceneButtonActive : null,
          )}
          onClick={() => {
            setScene("pair");
            reset();
          }}
        >
          Table → map
        </button>
        <button
          type="button"
          {...stylex.props(
            s.sceneButton,
            scene === "markdown" ? s.sceneButtonActive : null,
          )}
          onClick={() => {
            setScene("markdown");
            reset();
          }}
        >
          Markdown → map
        </button>
      </div>

      <div {...stylex.props(s.board, s.pair)}>
        <div {...stylex.props(s.column)}>
          <CatalogNodePreview
            spec={pair ? QUERY_PARCELS_SPEC : SURVEY_NOTES_SPEC}
            registry={PARCELS_REGISTRY}
            fields={pair ? QUERY_PARCELS_FIELDS : []}
            selectedPortKey={portKey(pair ? ROWS_PORT : NOTES_PORT)}
          />
          <div style={{ position: "relative" }}>
            <ViewerCard
              kind={leftKind}
              selected={selected === "left" || bothSelected}
              dropTarget={false}
              following={false}
              selectedRow={selectedRow}
              carrying={carrying}
              live={live}
              showLinkAction={approach === "menu" && leftKind === "table"}
              draggableRows={approach === "drag" && pair}
              onSelect={() => {
                if (approach === "rail" && selected === "map") {
                  setSelected("both");
                  setPhase("aim");
                  return;
                }
                setSelected("left");
                setSendOpen(false);
              }}
              onLinkViews={
                pair
                  ? () => {
                      setPhase("aim");
                      setSelected("left");
                    }
                  : undefined
              }
              onRow={
                leftKind === "table"
                  ? (index) => {
                      setSelectedRow(index);
                      setSelected("left");
                      if (approach === "send" && pair && !live) {
                        setSendOpen(true);
                      }
                    }
                  : undefined
              }
              onDragStart={
                approach === "drag" && pair
                  ? (index) => {
                      dropped.current = false;
                      setSelectedRow(index);
                      setPhase("carrying");
                    }
                  : undefined
              }
              onDragEnd={
                approach === "drag"
                  ? () => {
                      if (!dropped.current) setPhase("idle");
                    }
                  : undefined
              }
            />
            {sendOpen && approach === "send" && pair && !live ? (
              <div {...stylex.props(overlay.popup, s.sendMenu)}>
                <button
                  type="button"
                  {...stylex.props(overlay.item, nodeChrome.nodeMenuItem)}
                  onClick={() => {
                    setSendOpen(false);
                    setPhase("mapping");
                  }}
                >
                  Send to Map document
                </button>
              </div>
            ) : null}
          </div>
        </div>

        <div {...stylex.props(s.gutter)}>
          {mapping ? (
            <MappingSheet onDone={() => setPhase("live")} onCancel={reset} />
          ) : live ? (
            <MappingChip onOpen={() => setPhase("mapping")} onUnlink={reset} />
          ) : approach === "rail" && bothSelected ? (
            <div {...stylex.props(workbenchStyles.selectionToolbar)}>
              <span {...stylex.props(workbenchStyles.selectionLabel)}>
                2 selected
              </span>
              <span {...stylex.props(workbenchStyles.selectionDivider)} />
              <button
                type="button"
                disabled={!pair}
                {...stylex.props(
                  workbenchStyles.toolButton,
                  workbenchStyles.primaryButton,
                )}
                onClick={() => {
                  if (pair) setPhase("mapping");
                }}
              >
                <Link2 size={13} />
                Link views
              </button>
              <button
                type="button"
                {...stylex.props(workbenchStyles.toolButton)}
              >
                <Copy size={13} />
                Duplicate
              </button>
            </div>
          ) : carrying || aiming ? (
            <span {...stylex.props(s.hint)}>
              {carrying ? "Drop on the map" : "Click the map"}
            </span>
          ) : null}
        </div>

        <div {...stylex.props(s.column)}>
          <CatalogNodePreview
            spec={MAP_DOCUMENT_SPEC}
            registry={PARCELS_REGISTRY}
            fields={[]}
            selectedPortKey={portKey(MAP_PORT)}
          />
          <ViewerCard
            kind="map"
            selected={selected === "map" || bothSelected}
            dropTarget={(carrying || aiming) && pair}
            following={live}
            selectedRow={selectedRow}
            carrying={false}
            live={live}
            showLinkAction={false}
            draggableRows={false}
            onSelect={() => {
              if (approach === "rail" && selected === "left") {
                setSelected("both");
                setPhase("aim");
                return;
              }
              if ((carrying || aiming) && pair) {
                finishDrop();
                return;
              }
              setSelected("map");
            }}
            onFollow={() => setPhase("mapping")}
            onDrop={pair ? finishDrop : undefined}
          />
        </div>
      </div>
    </SandboxShell>
  );
}

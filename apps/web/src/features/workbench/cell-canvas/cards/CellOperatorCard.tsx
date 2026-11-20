"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ChevronDown, ChevronUp, Play, Plus, X } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import { Field, TextArea, TextInput } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { artifactTypeColor } from "@/features/workbench/canvas/nodes.css";
import { tokens } from "@/lib/stylex/tokens.stylex";

import {
  CellResizeGrip,
  useCellCardState,
  useCellInteractionStore,
} from "../CellCanvasContext";
import { computeOperatorCardLayout } from "../cell-card-geometry";
import type {
  CellConfigFieldSpec,
  CellResizeEdge,
  OperatorCardSurfaceData,
} from "../cell-contracts";
import {
  cellCornerRadius,
  type CellCorners,
  type CellGlassMaterial,
} from "../cell-glass-stage";
import {
  CARD_HEADER_HEIGHT,
  CARD_PLATE_BOTTOM_INSET,
  CARD_PLATE_INSET_X,
  CARD_PLATE_TOP,
  CELL_SIZE,
  type CellCardKind,
  type CellCardModel,
  type CellPort,
  type WorldPoint,
} from "../cell-model";
import { ConnectorFitting } from "../pipe-visuals";

/**
 * The operator card, and the card shell every real card on the cell canvas is
 * built from.
 *
 * The shell is `CellCard`'s anatomy: the outer box covers the card's cells
 * exactly, row 0 holds the floating title (0..24) over the plate's top strip
 * (26..50), and each port's stem and open ring sit on `(rowOffset + 0.5) *
 * CELL_SIZE`, where the router and the glass stage put its well. A card's body
 * places its rows from the same lattice, so nothing in it is measured and no
 * content can push a port off its row.
 */

export type CellResizeHandler = (
  cardId: string,
  edge: CellResizeEdge,
  event: React.PointerEvent<HTMLDivElement>,
) => void;

/** The props every real card takes, whatever it shows. */
export interface CellCardBaseProps {
  card: CellCardModel;
  /** Applied only to the dragged or settling card; undefined at rest. */
  visualOffset?: WorldPoint;
  material?: CellGlassMaterial;
  corners?: CellCorners;
  /** Overrides the interaction store, for a card rendered on its own. */
  selected?: boolean;
  dragging?: boolean;
  hovered?: boolean;
  /** Port ids on this card that have a pipe; the glass stage draws their well. */
  connectedPortIds?: ReadonlySet<string>;
  /** `${cardId}:${portId}` of the port a connection drag is over. */
  activePortKey?: string | null;
  onCardPointerDown?: (
    cardId: string,
    event: React.PointerEvent<HTMLDivElement>,
  ) => void;
  onPortPointerDown?: (
    cardId: string,
    port: CellPort,
    event: React.PointerEvent<HTMLButtonElement>,
  ) => void;
  onResizeStart?: CellResizeHandler;
  onResizeMove?: CellResizeHandler;
  onResizeEnd?: CellResizeHandler;
}

export interface CellCardState {
  selected: boolean;
  dragging: boolean;
  hovered: boolean;
}

/** The plate's own border, inside its border box. */
const PLATE_BORDER = 1;
/** The hit target around a port's ring. */
const PORT_HIT_SIZE = 30;
/** The open ring's drawing box, in flow units. */
const RING_BOX = 20;
/** Outer radius of the glass stage's recessed well: a stem stops at it. */
const WELL_OUTER_RADIUS = 14;
/** The Opus ring's outer radius: an open port's stem stops at it. */
const RING_OUTER_RADIUS = 5;

const MONO_FONT =
  "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace";

// StyleX evaluates these at build time, so they are plain strings, not calls.
const REST_SHADOW =
  "0 1px 2px light-dark(color-mix(in srgb, black 10%, transparent), color-mix(in srgb, black 45%, transparent)), 0 8px 20px -6px light-dark(color-mix(in srgb, black 18%, transparent), color-mix(in srgb, black 55%, transparent)), 0 22px 44px -14px light-dark(color-mix(in srgb, black 16%, transparent), color-mix(in srgb, black 50%, transparent))";
const LIFTED_SHADOW =
  "0 2px 4px light-dark(color-mix(in srgb, black 12%, transparent), color-mix(in srgb, black 50%, transparent)), 0 16px 32px -8px light-dark(color-mix(in srgb, black 24%, transparent), color-mix(in srgb, black 62%, transparent)), 0 36px 64px -18px light-dark(color-mix(in srgb, black 22%, transparent), color-mix(in srgb, black 58%, transparent))";
const SELECTION_RING = `0 0 0 1px ${tokens.colorAccent}`;
const LIQUID_SPECULAR =
  "inset 0 1px 0 light-dark(color-mix(in srgb, white 95%, transparent), color-mix(in srgb, white 24%, transparent)), inset 0 -1px 0 color-mix(in srgb, white 10%, transparent)";
const LIQUID_BORDER =
  "light-dark(color-mix(in srgb, white 85%, transparent), color-mix(in srgb, white 14%, transparent))";

const NO_CONNECTED_PORTS: ReadonlySet<string> = new Set();

const s = stylex.create({
  root: {
    position: "absolute",
    top: 0,
    left: 0,
    boxSizing: "border-box",
    color: tokens.colorText,
    willChange: "transform",
  },
  header: {
    boxSizing: "border-box",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    userSelect: "none",
    touchAction: "none",
  },
  title: {
    flexGrow: 1,
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    fontSize: "12px",
    fontWeight: 500,
    opacity: 0.65,
  },
  titleActive: { opacity: 1 },
  plate: {
    position: "relative",
    boxSizing: "border-box",
    overflow: "hidden",
    borderWidth: `${PLATE_BORDER}px`,
    borderStyle: "solid",
    touchAction: "none",
    userSelect: "none",
  },
  plateFrost: {
    backgroundColor: tokens.colorChrome,
    borderColor: tokens.colorBorder,
  },
  plateLiquid: {
    backgroundColor: `color-mix(in srgb, ${tokens.colorSurface} 58%, transparent)`,
    borderColor: LIQUID_BORDER,
  },
  plateActiveBorder: { borderColor: tokens.colorBorderStrong },
  frostRest: { boxShadow: REST_SHADOW },
  frostSelected: { boxShadow: `${SELECTION_RING}, ${REST_SHADOW}` },
  frostDragging: { boxShadow: LIFTED_SHADOW },
  liquidRest: { boxShadow: `${LIQUID_SPECULAR}, ${REST_SHADOW}` },
  liquidSelected: {
    boxShadow: `${SELECTION_RING}, ${LIQUID_SPECULAR}, ${REST_SHADOW}`,
  },
  liquidDragging: { boxShadow: `${LIQUID_SPECULAR}, ${LIFTED_SHADOW}` },
  strip: {
    boxSizing: "border-box",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    paddingInline: "10px",
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    color: tokens.colorSubtle,
    fontFamily: MONO_FONT,
    fontSize: "10px",
    overflow: "hidden",
    whiteSpace: "nowrap",
  },
  stem: {
    position: "absolute",
    height: "1px",
    opacity: 0.45,
    pointerEvents: "none",
  },
  port: {
    position: "absolute",
    boxSizing: "border-box",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    width: `${PORT_HIT_SIZE}px`,
    height: `${PORT_HIT_SIZE}px`,
    padding: 0,
    borderWidth: 0,
    borderRadius: "9999px",
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)":
        "color-mix(in srgb, var(--cell-port) 22%, transparent)",
    },
    cursor: "crosshair",
    touchAction: "none",
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorAccent}`,
    },
  },
  portHot: {
    backgroundColor: {
      default: "color-mix(in srgb, var(--cell-port) 30%, transparent)",
      ":hover:not(:disabled)":
        "color-mix(in srgb, var(--cell-port) 30%, transparent)",
    },
  },
  ring: {
    display: "block",
    flexShrink: 0,
    overflow: "visible",
    pointerEvents: "none",
  },

  // Shared small marks, used by every card's header, strip and rows.
  ellipsis: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  grow: { flexGrow: 1, flexBasis: 0 },
  chip: {
    flexShrink: 0,
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    height: "16px",
    paddingInline: "6px",
    borderRadius: "9999px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
    fontSize: "9px",
    fontWeight: 500,
    whiteSpace: "nowrap",
  },
  dot: {
    flexShrink: 0,
    width: "6px",
    height: "6px",
    borderRadius: "9999px",
  },
  dotIdle: { backgroundColor: tokens.colorSubtle },
  dotDone: { backgroundColor: tokens.colorSuccess },
  dotWorking: { backgroundColor: tokens.colorInfo },
  dotError: { backgroundColor: tokens.colorDanger },
  status: {
    flexShrink: 0,
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    whiteSpace: "nowrap",
  },

  // Operator body.
  band: {
    position: "absolute",
    left: 0,
    right: 0,
    boxSizing: "border-box",
  },
  portRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    paddingInline: "10px",
    pointerEvents: "none",
  },
  portLabel: {
    flexBasis: 0,
    flexGrow: 1,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
  portLabelOutput: { textAlign: "right" },
  portMeta: { color: tokens.colorSubtle },
  plugRow: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    paddingInline: "10px 6px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
  indexBadge: {
    flexShrink: 0,
    minWidth: "22px",
    height: "16px",
    paddingInline: "4px",
    boxSizing: "border-box",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorSubtle,
    fontFamily: MONO_FONT,
    fontSize: "9px",
  },
  addRow: {
    display: "flex",
    alignItems: "center",
    paddingInline: "10px",
  },
  configGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    // One dense row is 25px and two make a cell, as the band's height counts.
    gridAutoRows: "25px",
    rowGap: 0,
    columnGap: "8px",
    alignItems: "center",
    paddingInline: "10px",
    overflow: "hidden",
  },
  configCell: { minWidth: 0, minHeight: 0 },
  // A single-line field keeps its label beside the control so it fits one dense row.
  inlineField: {
    gridTemplateColumns: "minmax(0, 2fr) minmax(0, 3fr)",
    alignItems: "center",
    columnGap: "6px",
  },
  appendix: {
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    backgroundColor: tokens.colorSurfaceSunken,
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  appendixHeader: {
    flexShrink: 0,
    boxSizing: "border-box",
    height: "24px",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    paddingInline: "10px 4px",
    fontSize: "10px",
    fontWeight: 600,
    color: tokens.colorMuted,
  },
  appendixSummary: {
    flexShrink: 0,
    paddingInline: "10px",
    paddingBottom: "4px",
    color: tokens.colorSubtle,
    fontSize: "10px",
  },
  appendixSummaryInline: {
    fontWeight: 400,
    color: tokens.colorSubtle,
  },
  appendixPreview: {
    flexGrow: 1,
    minHeight: 0,
    overflowY: "auto",
    margin: 0,
    paddingInline: "10px",
    paddingBottom: "6px",
    color: tokens.colorMuted,
    fontFamily: MONO_FONT,
    fontSize: "9.5px",
    lineHeight: 1.5,
    listStyle: "none",
  },
});

const PLATE_SHADOWS = {
  frost: {
    rest: s.frostRest,
    selected: s.frostSelected,
    dragging: s.frostDragging,
  },
  liquid: {
    rest: s.liquidRest,
    selected: s.liquidSelected,
    dragging: s.liquidDragging,
  },
} as const;

/** Shared marks for the other card files' headers, strips and rows. */
export const cellCardMarks = {
  ellipsis: s.ellipsis,
  grow: s.grow,
  chip: s.chip,
  dot: s.dot,
  status: s.status,
  indexBadge: s.indexBadge,
  band: s.band,
};

/** StyleX classes plus per-card geometry, which changes with every card. */
export function styled(
  inline: React.CSSProperties,
  ...styles: stylex.StyleXStyles[]
): { className?: string; style: React.CSSProperties } {
  const props = stylex.props(...styles);
  return { className: props.className, style: { ...props.style, ...inline } };
}

/**
 * Top of cell row `rowOffset`, in the plate's content box: rows inside the
 * plate are placed from its padding edge, below the plate's top and border.
 */
export function plateRowTop(rowOffset: number): number {
  return rowOffset * CELL_SIZE - (CARD_PLATE_TOP + PLATE_BORDER);
}

/** The plate's content height, inside both borders. */
export function plateContentHeight(card: CellCardModel): number {
  return (
    card.heightCells * CELL_SIZE -
    CARD_PLATE_TOP -
    CARD_PLATE_BOTTOM_INSET -
    PLATE_BORDER * 2
  );
}

/** Keeps a band inside the plate when the card is shorter than its bands. */
export function clippedBandHeight(
  card: CellCardModel,
  top: number,
  height: number,
): number {
  return Math.max(0, Math.min(height, plateContentHeight(card) - top));
}

/** A pointer press on a control stays on the control, never starting a card drag. */
export function stopCardDrag(event: React.PointerEvent): void {
  event.stopPropagation();
}

/** The store's state for this card, under any state the caller pins. */
export function useResolvedCardState(
  cardId: string,
  overrides: { selected?: boolean; dragging?: boolean; hovered?: boolean },
): CellCardState {
  const stored = useCellCardState(cardId);
  return {
    selected: overrides.selected ?? stored.selected,
    dragging: overrides.dragging ?? stored.dragging,
    hovered: overrides.hovered ?? stored.hovered,
  };
}

export function statusDotStyle(
  status: "idle" | "done" | "working" | "error" | undefined,
): stylex.StyleXStyles {
  switch (status) {
    case "done":
      return s.dotDone;
    case "working":
      return s.dotWorking;
    case "error":
      return s.dotError;
    default:
      return s.dotIdle;
  }
}

export interface CellCardShellProps extends CellCardBaseProps {
  kind: CellCardKind;
  state: CellCardState;
  /** Defaults to `card.ports`; the operator adds its instance plugs. */
  ports?: readonly CellPort[];
  /** Marks after the title in the floating header. */
  headerExtra?: React.ReactNode;
  /** The plate's 23px top strip, ending on row 0's lower edge. */
  strip?: React.ReactNode;
  resizable: boolean;
  /** Floats over the card, e.g. a `CellCardToolbar`. */
  toolbar?: React.ReactNode;
  /** Inline plate paint, e.g. an annotation's tint. */
  plateStyle?: React.CSSProperties;
  /** Extra `data-*` attributes on the outer box. */
  rootData?: Record<`data-${string}`, string>;
  children?: React.ReactNode;
}

/** The outer box, header, plate, ports and resize grip of a real card. */
export function CellCardShell({
  card,
  kind,
  state,
  ports = card.ports,
  visualOffset,
  material = "frost",
  corners = "rounded",
  connectedPortIds = NO_CONNECTED_PORTS,
  activePortKey,
  onCardPointerDown,
  onPortPointerDown,
  onResizeStart,
  onResizeMove,
  onResizeEnd,
  headerExtra,
  strip,
  resizable,
  toolbar,
  plateStyle,
  rootData,
  children,
}: CellCardShellProps) {
  const store = useCellInteractionStore();
  const { selected, dragging, hovered } = state;
  const width = card.widthCells * CELL_SIZE;
  const height = card.heightCells * CELL_SIZE;
  const x = card.col * CELL_SIZE + (visualOffset?.x ?? 0);
  const y = card.row * CELL_SIZE + (visualOffset?.y ?? 0);
  const active = selected || dragging;
  const shadowState = dragging ? "dragging" : selected ? "selected" : "rest";
  const handleCardPointerDown = (event: React.PointerEvent<HTMLDivElement>) =>
    onCardPointerDown?.(card.id, event);

  return (
    <div
      data-cell-card="true"
      data-card-id={card.id}
      data-card-kind={kind}
      data-material={material}
      data-selected={selected ? "true" : "false"}
      data-dragging={dragging ? "true" : "false"}
      {...rootData}
      onPointerEnter={() => store?.setHoveredCard(card.id)}
      onPointerLeave={() => store?.setHoveredCard(null)}
      {...styled(
        {
          width,
          height,
          transform: `translate3d(${x}px, ${y}px, 0)`,
          zIndex: dragging ? 20 : selected ? 10 : 1,
        },
        s.root,
      )}
    >
      <div
        data-card-header="true"
        onPointerDown={handleCardPointerDown}
        {...styled(
          {
            height: CARD_HEADER_HEIGHT,
            marginBottom: CARD_PLATE_TOP - CARD_HEADER_HEIGHT,
            paddingInline: CARD_PLATE_INSET_X,
            cursor: dragging ? "grabbing" : "grab",
          },
          s.header,
        )}
      >
        <span {...stylex.props(s.title, active && s.titleActive)}>
          {card.title}
        </span>
        {headerExtra}
      </div>
      <article
        onPointerDown={handleCardPointerDown}
        {...styled(
          {
            height: height - CARD_PLATE_TOP - CARD_PLATE_BOTTOM_INSET,
            marginInline: CARD_PLATE_INSET_X,
            borderRadius: cellCornerRadius(corners),
            cursor: dragging ? "grabbing" : "grab",
            ...plateStyle,
          },
          s.plate,
          material === "liquid" ? s.plateLiquid : s.plateFrost,
          active && s.plateActiveBorder,
          PLATE_SHADOWS[material][shadowState],
        )}
      >
        {strip != null ? (
          <div
            data-card-strip="true"
            {...styled(
              // Plate border + this strip end exactly on row 0's lower edge.
              { height: CARD_HEADER_HEIGHT - PLATE_BORDER },
              s.strip,
            )}
          >
            {strip}
          </div>
        ) : null}
        {children}
      </article>
      {ports.map((port) => (
        <CellCardPort
          key={port.id}
          card={card}
          port={port}
          width={width}
          connected={connectedPortIds.has(port.id)}
          hot={activePortKey === `${card.id}:${port.id}`}
          onPortPointerDown={onPortPointerDown}
        />
      ))}
      {toolbar}
      {resizable ? (
        <CellResizeGrip
          cardId={card.id}
          edge="se"
          visible={selected || hovered}
          onResizeStart={onResizeStart}
          onResizeMove={onResizeMove}
          onResizeEnd={onResizeEnd}
        />
      ) : null}
    </div>
  );
}

/**
 * A port's stem and hit target. A connected port's ring and well are the glass
 * stage's; an open port draws its own Opus ring.
 */
function CellCardPort({
  card,
  port,
  width,
  connected,
  hot,
  onPortPointerDown,
}: {
  card: CellCardModel;
  port: CellPort;
  width: number;
  connected: boolean;
  hot: boolean;
  onPortPointerDown: CellCardBaseProps["onPortPointerDown"];
}) {
  const centre = {
    x: port.direction === "input" ? -CELL_SIZE / 2 : width + CELL_SIZE / 2,
    y: (port.rowOffset + 0.5) * CELL_SIZE,
  };
  const portColor = artifactTypeColor(port.artifactTypeId, tokens.colorMuted);
  const sequence = port.shape === "many";
  // The stem runs from the plate's outer edge to the well's or ring's rim.
  const stemLength =
    CELL_SIZE / 2 +
    CARD_PLATE_INSET_X -
    (connected ? WELL_OUTER_RADIUS : RING_OUTER_RADIUS);
  const stemLeft =
    port.direction === "input"
      ? CARD_PLATE_INSET_X - stemLength
      : width - CARD_PLATE_INSET_X;
  return (
    <>
      <span
        aria-hidden="true"
        data-port-stem={port.id}
        {...styled(
          {
            left: stemLeft,
            top: centre.y - 0.5,
            width: stemLength,
            backgroundColor: portColor,
          },
          s.stem,
        )}
      />
      <button
        type="button"
        data-port-id={port.id}
        data-port-direction={port.direction}
        data-port-connected={connected ? "true" : "false"}
        data-port-card-id={card.id}
        data-port-hot={hot ? "true" : "false"}
        aria-label={`${card.title} ${port.direction} ${port.name} (${sequence ? "list" : "single"} ${port.artifactTypeId})`}
        onPointerDown={(event) => {
          event.stopPropagation();
          onPortPointerDown?.(card.id, port, event);
        }}
        {...styled(
          {
            left: centre.x - PORT_HIT_SIZE / 2,
            top: centre.y - PORT_HIT_SIZE / 2,
            "--cell-port": portColor,
          } as React.CSSProperties,
          s.port,
          hot && s.portHot,
        )}
      >
        {connected ? null : (
          <svg
            aria-hidden="true"
            data-port-ring={sequence ? "list" : "single"}
            width={RING_BOX}
            height={RING_BOX}
            viewBox={`${-RING_BOX / 2} ${-RING_BOX / 2} ${RING_BOX} ${RING_BOX}`}
            {...stylex.props(s.ring)}
          >
            <ConnectorFitting
              centre={{ x: 0, y: 0 }}
              color={portColor}
              sequence={sequence}
              design="opus"
            />
          </svg>
        )}
      </button>
    </>
  );
}

// --- Operator card ---------------------------------------------------------

export interface CellOperatorCardProps extends CellCardBaseProps {
  surface: OperatorCardSurfaceData;
  onRun?: (cardId: string) => void;
  onAddPlug?: (cardId: string, portName: string) => void;
  onRemovePlug?: (cardId: string, portName: string, plugId: string) => void;
  onConfigChange?: (
    cardId: string,
    fieldId: string,
    value: string | number | boolean,
  ) => void;
  onToggleAppendix?: (cardId: string) => void;
}

const STATUS_TEXT = {
  idle: undefined,
  done: "Done",
  working: "Working",
  error: "Error",
} as const;

function portLabel(port: CellPort): React.ReactNode {
  return (
    <>
      {port.name}
      {port.required ? <span {...stylex.props(s.portMeta)}> *</span> : null}
      {port.shape === "many" ? (
        <span {...stylex.props(s.portMeta)}> · list</span>
      ) : null}
    </>
  );
}

function CellOperatorCardImpl(props: CellOperatorCardProps) {
  const {
    card,
    surface,
    connectedPortIds = NO_CONNECTED_PORTS,
    onRun,
    onAddPlug,
    onRemovePlug,
    onConfigChange,
    onToggleAppendix,
  } = props;
  const state = useResolvedCardState(card.id, props);
  const layout = computeOperatorCardLayout(card, surface);
  const groups = surface.instancePlugGroups ?? [];
  const configFields = surface.configFields ?? [];
  const appendix = surface.appendix ?? null;

  // Every instance plug is an input port on its own row: one the model already
  // lists keeps its entry, and a plug it does not list gets one here.
  const ports: CellPort[] = [...card.ports];
  const listedPortIds = new Set(card.ports.map((port) => port.id));
  const plugIds = new Set<string>();
  const connected = new Set(connectedPortIds);
  for (const group of groups) {
    group.plugs.forEach((plug, index) => {
      plugIds.add(plug.plugId);
      if (plug.connected) connected.add(plug.plugId);
      if (listedPortIds.has(plug.plugId)) return;
      ports.push({
        id: plug.plugId,
        name: plug.label,
        direction: "input",
        rowOffset: group.startRowOffset + index,
        artifactTypeId: group.artifactTypeId,
        shape: group.shape,
      });
    });
  }

  // The plug rows label their own ports; the rest pair up by row.
  const plugPortNames = groups.map((group) => group.portName);
  const portRows = new Map<number, { input?: CellPort; output?: CellPort }>();
  for (const port of card.ports) {
    if (plugIds.has(port.id)) continue;
    const isPlug = plugPortNames.some(
      (name) => port.name === name || port.id.startsWith(`${name}:`),
    );
    if (isPlug) continue;
    const row = portRows.get(port.rowOffset) ?? {};
    row[port.direction] = port;
    portRows.set(port.rowOffset, row);
  }

  const statusText = surface.statusLabel ?? STATUS_TEXT[card.status ?? "idle"];
  const headerExtra = (
    <>
      {statusText ? (
        <span
          data-card-status={card.status ?? "idle"}
          {...stylex.props(s.status)}
        >
          <span
            aria-hidden="true"
            {...stylex.props(s.dot, statusDotStyle(card.status))}
          />
          {statusText}
        </span>
      ) : null}
      {onRun ? (
        <IconButton
          size="2xs"
          variant="ghost"
          label={`Run ${card.title}`}
          disabled={surface.runDisabled}
          onPointerDown={stopCardDrag}
          onClick={() => onRun(card.id)}
        >
          <Play size={11} />
        </IconButton>
      ) : null}
    </>
  );

  const bandStyle = (startRow: number, heightCells: number) => {
    const top = plateRowTop(startRow);
    return {
      top,
      height: clippedBandHeight(card, top, heightCells * CELL_SIZE),
    };
  };

  return (
    <CellCardShell
      {...props}
      kind="operator"
      state={state}
      ports={ports}
      connectedPortIds={connected}
      headerExtra={headerExtra}
      strip={<span {...stylex.props(s.ellipsis)}>{card.subtitle}</span>}
      resizable={card.resizable === true}
    >
      {[...portRows].map(([rowOffset, { input, output }]) => (
        <div
          key={`port-row:${rowOffset}`}
          data-port-row={rowOffset}
          {...styled(
            { top: plateRowTop(rowOffset), height: CELL_SIZE },
            s.band,
            s.portRow,
          )}
        >
          <span {...stylex.props(s.portLabel, s.ellipsis)}>
            {input ? portLabel(input) : null}
          </span>
          <span {...stylex.props(s.portLabel, s.ellipsis, s.portLabelOutput)}>
            {output ? portLabel(output) : null}
          </span>
        </div>
      ))}

      {groups.map((group) => (
        <React.Fragment key={`plugs:${group.portName}`}>
          {group.plugs.map((plug, index) => (
            <div
              key={plug.plugId}
              data-instance-plug-row={plug.plugId}
              data-plug-port={group.portName}
              {...styled(
                {
                  top: plateRowTop(group.startRowOffset + index),
                  height: CELL_SIZE,
                },
                s.band,
                s.plugRow,
              )}
            >
              <span title={group.title} {...stylex.props(s.indexBadge)}>
                #{index + 1}
              </span>
              <span {...stylex.props(s.ellipsis, s.grow)}>{plug.label}</span>
              {plug.connectionMeta ? (
                <span {...stylex.props(s.chip)}>{plug.connectionMeta}</span>
              ) : null}
              {onRemovePlug ? (
                <IconButton
                  size="2xs"
                  variant="ghost"
                  label={`Remove ${plug.label}`}
                  onPointerDown={stopCardDrag}
                  onClick={() =>
                    onRemovePlug(card.id, group.portName, plug.plugId)
                  }
                >
                  <X size={11} />
                </IconButton>
              ) : null}
            </div>
          ))}
          {group.canAdd ? (
            <div
              data-instance-plug-add={group.portName}
              {...styled(
                {
                  top: plateRowTop(group.startRowOffset + group.plugs.length),
                  height: CELL_SIZE,
                },
                s.band,
                s.addRow,
              )}
            >
              <Button
                size="xs"
                variant="dashed"
                onPointerDown={stopCardDrag}
                onClick={() => onAddPlug?.(card.id, group.portName)}
              >
                <Plus size={12} />
                Add {group.title}
              </Button>
            </div>
          ) : null}
        </React.Fragment>
      ))}

      {layout.configBand && configFields.length > 0 ? (
        <div
          data-config-band="true"
          onPointerDown={stopCardDrag}
          {...styled(
            bandStyle(
              layout.configBand.startRow,
              layout.configBand.heightCells,
            ),
            s.band,
            s.configGrid,
          )}
        >
          {configFields.map((field) => (
            <div
              key={field.id}
              data-config-field={field.id}
              {...styled(
                {
                  gridColumn: field.span === 1 ? "span 1" : "1 / -1",
                  gridRow: `span ${fieldDenseRows(field)}`,
                },
                s.configCell,
              )}
            >
              <ConfigFieldControl
                field={field}
                onChange={(value) => onConfigChange?.(card.id, field.id, value)}
              />
            </div>
          ))}
        </div>
      ) : null}

      {layout.appendixBand && appendix ? (
        <section
          data-appendix-band={appendix.collapsed ? "collapsed" : "expanded"}
          {...styled(
            bandStyle(
              layout.appendixBand.startRow,
              layout.appendixBand.heightCells,
            ),
            s.band,
            s.appendix,
          )}
        >
          <div {...stylex.props(s.appendixHeader)}>
            <span {...stylex.props(s.ellipsis)}>{appendix.title}</span>
            <span {...stylex.props(s.chip)}>{appendix.kindBadge}</span>
            {appendix.itemCount != null ? (
              <span {...stylex.props(s.chip)}>{appendix.itemCount}</span>
            ) : null}
            {appendix.collapsed ? (
              <span
                data-appendix-summary="true"
                {...stylex.props(s.ellipsis, s.grow, s.appendixSummaryInline)}
              >
                {appendix.summaryText}
              </span>
            ) : (
              <span {...stylex.props(s.grow)} />
            )}
            <IconButton
              size="2xs"
              variant="ghost"
              label={
                appendix.collapsed ? "Expand appendix" : "Collapse appendix"
              }
              onPointerDown={stopCardDrag}
              onClick={() => onToggleAppendix?.(card.id)}
            >
              {appendix.collapsed ? (
                <ChevronDown size={11} />
              ) : (
                <ChevronUp size={11} />
              )}
            </IconButton>
          </div>
          {appendix.collapsed ? null : (
            <>
              <div
                data-appendix-summary="true"
                {...stylex.props(s.appendixSummary, s.ellipsis)}
              >
                {appendix.summaryText}
              </div>
              {appendix.previewLines?.length ? (
                <ul
                  data-appendix-preview="true"
                  onPointerDown={stopCardDrag}
                  {...stylex.props(s.appendixPreview)}
                >
                  {appendix.previewLines.map((line, index) => (
                    <li key={index} {...stylex.props(s.ellipsis)}>
                      {line}
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          )}
        </section>
      ) : null}
    </CellCardShell>
  );
}

/** Dense rows a field takes on the shelf grid, as `countConfigShelfCells` counts them. */
function fieldDenseRows(field: CellConfigFieldSpec): number {
  return Math.max(1, field.denseRows ?? (field.kind === "multiline" ? 3 : 1));
}

function ConfigFieldControl({
  field,
  onChange,
}: {
  field: CellConfigFieldSpec;
  onChange: (value: string | number | boolean) => void;
}) {
  const text = String(field.value ?? "");
  switch (field.kind) {
    case "toggle":
      return (
        <Switch
          size="dense"
          checked={Boolean(field.value)}
          label={field.label}
          onCheckedChange={onChange}
        />
      );
    case "multiline":
      return (
        <Field size="dense" label={field.label}>
          <TextArea
            size="dense"
            rows={2}
            value={text}
            placeholder={field.placeholder}
            onChange={(event) => onChange(event.target.value)}
          />
        </Field>
      );
    case "select":
      return (
        <Field size="dense" label={field.label} xstyle={s.inlineField}>
          <Select
            size="dense"
            value={text}
            onChange={(event) => onChange(event.target.value)}
          >
            {(field.options ?? []).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </Field>
      );
    case "number":
      return (
        <Field size="dense" label={field.label} xstyle={s.inlineField}>
          <TextInput
            size="dense"
            type="number"
            mono
            value={text}
            placeholder={field.placeholder}
            onChange={(event) => onChange(Number(event.target.value))}
          />
        </Field>
      );
    case "text":
      return (
        <Field size="dense" label={field.label} xstyle={s.inlineField}>
          <TextInput
            size="dense"
            value={text}
            placeholder={field.placeholder}
            onChange={(event) => onChange(event.target.value)}
          />
        </Field>
      );
  }
}

export const CellOperatorCard = React.memo(CellOperatorCardImpl);

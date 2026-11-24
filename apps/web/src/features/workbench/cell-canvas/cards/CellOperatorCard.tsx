"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  ChevronDown,
  ChevronUp,
  MoreHorizontal,
  Play,
  Plus,
  Trash2,
  X,
} from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import {
  Menu,
  MenuContent,
  MenuGroup,
  MenuGroupLabel,
  MenuItem,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/menu";
import { artifactTypeColor } from "@/features/workbench/config-ui/nodes.css";
import { tokens } from "@/lib/stylex/tokens.stylex";

import {
  CellResizeGrip,
  useCellCardState,
  useCellInteractionStore,
} from "../CellCanvasContext";
import {
  computeOperatorCardLayout,
  plugRowOffset,
} from "../cell-card-geometry";
import type {
  CellResizeEdge,
  OperatorCardSurfaceData,
  ServicePortPrompt,
} from "../cell-contracts";
import {
  cardPlateFill,
  cellCornerRadius,
  type CellCorners,
  type CellGlassMaterial,
  type CellWellStyle,
} from "../cell-glass-stage";
import {
  CARD_HEADER_HEIGHT,
  CARD_PLATE_BOTTOM_INSET,
  CARD_PLATE_INSET_X,
  CARD_HEADER_TOP,
  CARD_PLATE_TOP,
  CELL_SIZE,
  punchedPortCardCentre,
  type CellCardKind,
  type CellCardModel,
  type CellPort,
  type WorldPoint,
  cellPortKey,
  isPortActive,
  isPortConnected,
} from "../cell-model";
import { ConnectorFitting, type PipeFamily } from "../pipe-visuals";
import {
  PUNCH_OUTER_RADIUS,
  PUNCHED_LABEL_INSET,
  PunchedPortSocket,
} from "../punched-port";

import { CellConfigBand } from "./CellConfigFields";
import { CellCredentialsDialog } from "./CellCredentialsDialog";

/**
 * The operator card, and the card shell every real card on the cell canvas is
 * built from.
 *
 * The shell is `CellCard`'s anatomy: the outer box covers the card's cells
 * exactly, the floating title (12..36) sits over the plate, which begins at
 * 38 on every card kind; an artifact, collection, agent or note opens its
 * plate with a 23px strip, an operator goes straight to its first port row —
 * and each port's stem and open ring sit on `(rowOffset + 0.5) *
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
  /**
   * `punched` puts each port in a hole through the plate and moves the labels
   * in past it; the other styles keep the port in the gutter cell.
   */
  well?: CellWellStyle;
  /** The pipe family a punched port's stub is drawn in. */
  pipe?: PipeFamily;
  /** How solid the plate is, 0.2 to 1; undefined keeps it solid. */
  cardFill?: number;
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
  /** Adds "Remove" to the card's "⋯" menu. */
  onRemove?: (cardId: string) => void;
}

/** One action in a card's "⋯" menu, after what the card is. */
export interface CellCardMenuItem {
  id: string;
  label: string;
  icon?: React.ReactNode;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
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
const WELL_OUTER_RADIUS = 11;
/** The Opus ring's outer radius: an open port's stem stops at it. */
const RING_OUTER_RADIUS = 5;

const MONO_FONT =
  "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace";

// StyleX evaluates these at build time, so they are plain strings, not calls.
const REST_SHADOW =
  "0 1px 2px light-dark(color-mix(in srgb, black 10%, transparent), color-mix(in srgb, black 45%, transparent)), 0 8px 20px -6px light-dark(color-mix(in srgb, black 18%, transparent), color-mix(in srgb, black 55%, transparent)), 0 22px 44px -14px light-dark(color-mix(in srgb, black 16%, transparent), color-mix(in srgb, black 50%, transparent))";
const LIQUID_SPECULAR =
  "inset 0 1px 0 light-dark(color-mix(in srgb, white 95%, transparent), color-mix(in srgb, white 24%, transparent)), inset 0 -1px 0 color-mix(in srgb, white 10%, transparent)";
const SELECTION_HALO = `0 0 0 3px color-mix(in srgb, ${tokens.colorAccent} 8%, transparent)`;
const LIQUID_BORDER =
  "light-dark(color-mix(in srgb, white 85%, transparent), color-mix(in srgb, white 14%, transparent))";

const NO_CONNECTED_PORTS: ReadonlySet<string> = new Set();
const NO_MENU_ITEMS: readonly CellCardMenuItem[] = [];

const s = stylex.create({
  root: {
    position: "absolute",
    top: 0,
    left: 0,
    boxSizing: "border-box",
    color: tokens.colorText,
    pointerEvents: "none",
    willChange: "transform",
  },
  header: {
    boxSizing: "border-box",
    display: "flex",
    alignItems: "center",
    gap: "4px",
    pointerEvents: "auto",
    userSelect: "none",
    touchAction: "none",
  },
  // The name is a tab that hugs its text. At rest it is bare and recedes;
  // selected, it fills with ink. Its padding is the same in both states, so
  // the name never shifts. The plate answers it with a very light accent edge
  // and a soft gutter (`plateActive`, `*ShadowActive`).
  title: {
    flexShrink: 1,
    minWidth: 0,
    marginRight: "auto",
    boxSizing: "border-box",
    height: "20px",
    paddingInline: "10px",
    borderRadius: tokens.radiusMd,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    color: tokens.colorText,
    fontSize: "12px",
    fontWeight: 500,
    lineHeight: "20px",
    opacity: 0.65,
    transitionProperty: "background-color, color, opacity",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
  },
  // An artifact's title names its type and is short: it keeps its whole
  // width, and the file name beside it gives way instead.
  titleFixed: {
    flexShrink: 0,
    maxWidth: "100%",
  },
  titleSelected: {
    opacity: 1,
    backgroundColor: tokens.colorAccent,
    color: tokens.colorChrome,
  },
  // At rest only the title floats above the plate. Selected and at rest, or
  // while the "⋯" menu is open, the header's actions (run, status, sizes,
  // counts, then the "⋯") fade in together beside the title.
  headerActions: {
    flexShrink: 0,
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    animationName: "grafy-node-detail-in",
    animationDuration: {
      default: "160ms",
      "@media (prefers-reduced-motion: reduce)": "0s",
    },
    animationTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
    animationFillMode: "both",
  },
  menuSlot: {
    flexShrink: 0,
    width: "20px",
    height: "20px",
    display: "inline-grid",
    placeItems: "center",
  },
  menuReveal: {
    display: "inline-grid",
    placeItems: "center",
  },
  menuTriggerOpen: {
    color: tokens.colorText,
    backgroundColor: tokens.colorHover,
  },
  menuInfo: {
    display: "grid",
    gap: "2px",
    padding: "6px 8px 8px",
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
    color: tokens.colorMuted,
    overflowWrap: "anywhere",
  },
  menuInfoTitle: {
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 560,
  },
  plate: {
    position: "relative",
    boxSizing: "border-box",
    overflow: "hidden",
    borderWidth: `${PLATE_BORDER}px`,
    borderStyle: "solid",
    pointerEvents: "auto",
    touchAction: "none",
    userSelect: "none",
  },
  plateFrost: {
    backgroundColor: tokens.colorChrome,
    borderColor: tokens.colorBorder,
  },
  // Cards are solid: a pipe under one is hidden, never seen through it.
  plateLiquid: {
    backgroundColor: tokens.colorSurface,
    borderColor: LIQUID_BORDER,
  },
  // Selected or held, the plate takes a very light accent edge and a soft 3px
  // gutter that answers the ink-filled title tab. A held card keeps its
  // resting shadow: the drop ghost shows the move.
  plateActive: {
    borderColor: `color-mix(in srgb, ${tokens.colorAccent} 20%, transparent)`,
  },
  frostShadow: { boxShadow: REST_SHADOW },
  liquidShadow: { boxShadow: `${LIQUID_SPECULAR}, ${REST_SHADOW}` },
  frostShadowActive: { boxShadow: `${SELECTION_HALO}, ${REST_SHADOW}` },
  liquidShadowActive: {
    boxShadow: `${LIQUID_SPECULAR}, ${SELECTION_HALO}, ${REST_SHADOW}`,
  },
  // An artifact's plate under punched wells: the fill and the preview sit on
  // this layer, which the shell cuts the holes out of, so the canvas shows
  // through them. The plate itself keeps its border and its drop shadow.
  plateInterior: {
    position: "absolute",
    inset: 0,
    borderRadius: "inherit",
    overflow: "hidden",
  },
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
    pointerEvents: "auto",
    touchAction: "none",
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorAccent}`,
    },
  },
  // A punched port answers the pointer with its ring, not a tinted disc.
  portPunched: {
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": "transparent",
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
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
    alignItems: "center",
    columnGap: "8px",
    pointerEvents: "none",
  },
  portSlot: { minWidth: 0, display: "flex" },
  portSlotInput: {
    alignItems: "center",
    gap: "4px",
  },
  portSlotInputDrop: { pointerEvents: "auto" },
  portSlotOutput: { justifyContent: "flex-end" },
  // A port's name sits in a tab flush with the plate's edge, square on the
  // side its stem leaves from, so tab, stem and ring read as one line. With
  // punched wells there is no stem: the tab is a pill beside the hole.
  portTab: {
    boxSizing: "border-box",
    minWidth: 0,
    maxWidth: "100%",
    height: "22px",
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    paddingInline: "10px 8px",
    borderRadius: "0 4px 4px 0",
    backgroundColor: tokens.colorHover,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
    whiteSpace: "nowrap",
  },
  portTabOutput: {
    paddingInline: "8px 10px",
    borderRadius: "4px 0 0 4px",
  },
  portTabPunched: {
    height: "18px",
    paddingInline: "7px",
    borderRadius: "9999px",
  },
  portName: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  portTabMuted: {
    color: tokens.colorSubtle,
    backgroundColor: tokens.colorSurfaceSunken,
  },
  portCaption: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    color: tokens.colorSubtle,
    fontWeight: 400,
  },
  pickEngine: {
    maxWidth: "100%",
    minWidth: 0,
    flexShrink: 1,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    pointerEvents: "auto",
  },
  emptyEngine: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    pointerEvents: "auto",
    textDecoration: {
      default: "none",
      ":hover:not(:disabled)": "underline",
    },
  },
  portMeta: { flexShrink: 0, color: tokens.colorSubtle, fontWeight: 400 },
  plugRow: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    paddingRight: "6px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
  plugIndex: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontFamily: MONO_FONT,
    fontSize: "9.5px",
    fontWeight: 400,
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

/** Shared marks for the other card files' headers, strips and rows. */
export const cellCardMarks = {
  ellipsis: s.ellipsis,
  grow: s.grow,
  chip: s.chip,
  dot: s.dot,
  status: s.status,
  indexBadge: s.indexBadge,
  band: s.band,
  // A sequence's spread draws real card plates and headers from these.
  header: s.header,
  title: s.title,
  titleFixed: s.titleFixed,
  titleSelected: s.titleSelected,
  headerActions: s.headerActions,
  menuSlot: s.menuSlot,
  menuReveal: s.menuReveal,
  plate: s.plate,
  plateFrost: s.plateFrost,
  plateLiquid: s.plateLiquid,
  plateActive: s.plateActive,
  frostShadow: s.frostShadow,
  liquidShadow: s.liquidShadow,
  frostShadowActive: s.frostShadowActive,
  liquidShadowActive: s.liquidShadowActive,
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
  /** Marks after the title in the floating header, shown while selected. */
  headerExtra?: React.ReactNode;
  /** Quiet facts after the title in the floating header, always shown. */
  headerMeta?: React.ReactNode;
  /** Painted under the plate inside the card box, e.g. a sequence's card backs. */
  behindPlate?: React.ReactNode;
  /** The plate's 23px top strip, under the plate's top edge. */
  strip?: React.ReactNode;
  resizable: boolean;
  /** Floats over the card, e.g. a `CellCardToolbar`. */
  toolbar?: React.ReactNode;
  /** Actions in the "⋯" menu, before "Remove". */
  menuItems?: readonly CellCardMenuItem[];
  /** The menu's line under the card's name; defaults to its subtitle. */
  menuDetail?: React.ReactNode;
  /** Inline plate paint, e.g. an annotation's tint. */
  plateStyle?: React.CSSProperties;
  /** Plate styles applied after the shell's own, e.g. a lift's transition. */
  plateXstyle?: stylex.StyleXStyles;
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
  well = "recessed",
  pipe = "glass",
  cardFill,
  connectedPortIds = NO_CONNECTED_PORTS,
  activePortKey,
  onCardPointerDown,
  onPortPointerDown,
  onResizeStart,
  onResizeMove,
  onResizeEnd,
  onRemove,
  headerExtra,
  headerMeta,
  behindPlate,
  strip,
  resizable,
  toolbar,
  menuItems = NO_MENU_ITEMS,
  menuDetail = card.subtitle,
  plateStyle,
  plateXstyle,
  rootData,
  children,
}: CellCardShellProps) {
  const store = useCellInteractionStore();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const { selected, dragging } = state;
  const width = card.widthCells * CELL_SIZE;
  const height = card.heightCells * CELL_SIZE;
  const x = card.col * CELL_SIZE + (visualOffset?.x ?? 0);
  const y = card.row * CELL_SIZE + (visualOffset?.y ?? 0);
  const active = selected || dragging;
  // Over an artifact's preview a punched port is a real hole through the card.
  const seeThrough = well === "punched" && kind === "artifact";
  const plateFill = cardPlateFill(material, cardFill);
  const showHeaderActions = (selected && !dragging) || menuOpen;
  const items: CellCardMenuItem[] = [...menuItems];
  if (onRemove) {
    items.push({
      id: "remove",
      label: "Remove",
      icon: <Trash2 size={13} />,
      danger: true,
      onSelect: () => onRemove(card.id),
    });
  }
  const handleCardPointerDown = (event: React.PointerEvent<HTMLDivElement>) =>
    onCardPointerDown?.(card.id, event);

  return (
    <div
      data-cell-card="true"
      data-card-id={card.id}
      data-card-kind={kind}
      data-material={material}
      data-well={well}
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
            marginTop: CARD_HEADER_TOP,
            height: CARD_HEADER_HEIGHT,
            marginBottom: CARD_PLATE_TOP - CARD_HEADER_TOP - CARD_HEADER_HEIGHT,
            paddingInline: CARD_PLATE_INSET_X,
            cursor: dragging ? "grabbing" : "grab",
          },
          s.header,
        )}
      >
        <span
          data-card-title={active ? "selected" : "rest"}
          title={card.title}
          {...stylex.props(
            s.title,
            kind === "artifact" && s.titleFixed,
            active && s.titleSelected,
          )}
        >
          {card.title}
        </span>
        {headerMeta}
        {showHeaderActions ? (
          <span
            data-card-header-actions="true"
            {...stylex.props(s.headerActions)}
          >
            {headerExtra}
            <span data-card-menu-slot="true" {...stylex.props(s.menuSlot)}>
              <span
                data-card-menu="true"
                onPointerDown={stopCardDrag}
                {...stylex.props(s.menuReveal)}
              >
                <CellCardMenu
                  title={card.title}
                  detail={menuDetail}
                  items={items}
                  open={menuOpen}
                  onOpenChange={setMenuOpen}
                />
              </span>
            </span>
          </span>
        ) : null}
      </div>
      {behindPlate}
      <article
        onPointerDown={handleCardPointerDown}
        {...styled(
          {
            height: height - CARD_PLATE_TOP - CARD_PLATE_BOTTOM_INSET,
            marginInline: CARD_PLATE_INSET_X,
            borderRadius: cellCornerRadius(corners),
            cursor: dragging ? "grabbing" : "grab",
            backgroundColor: seeThrough ? "transparent" : plateFill,
            ...plateStyle,
          },
          s.plate,
          material === "liquid" ? s.plateLiquid : s.plateFrost,
          active && s.plateActive,
          material === "liquid"
            ? active
              ? s.liquidShadowActive
              : s.liquidShadow
            : active
              ? s.frostShadowActive
              : s.frostShadow,
          plateXstyle,
        )}
      >
        {strip != null ? (
          <div
            data-card-strip="true"
            {...styled(
              // Plate border + this strip end at 62, where row 2's port centre
              // sits half a cell lower.
              { height: CARD_HEADER_HEIGHT - PLATE_BORDER },
              s.strip,
            )}
          >
            {strip}
          </div>
        ) : null}
        {seeThrough ? (
          <div
            data-plate-interior="punched"
            {...styled(
              {
                backgroundColor: plateFill,
                ...punchedHoleMask(card, ports, {
                  x: CARD_PLATE_INSET_X + PLATE_BORDER,
                  y: CARD_PLATE_TOP + PLATE_BORDER,
                }),
              },
              s.plateInterior,
            )}
          >
            {children}
          </div>
        ) : (
          children
        )}
      </article>
      {ports.map((port) => (
        <CellCardPort
          key={cellPortKey(port.direction, port.id)}
          card={card}
          port={port}
          width={width}
          connected={isPortConnected(connectedPortIds, port)}
          hot={isPortActive(activePortKey, card.id, port)}
          punched={well === "punched"}
          open={seeThrough}
          material={material}
          pipe={pipe}
          onPortPointerDown={onPortPointerDown}
        />
      ))}
      {toolbar}
      {resizable ? (
        <CellResizeGrip
          cardId={card.id}
          edge="se"
          visible={selected && !dragging}
          onResizeStart={onResizeStart}
          onResizeMove={onResizeMove}
          onResizeEnd={onResizeEnd}
        />
      ) : null}
    </div>
  );
}

/**
 * A mask that cuts each punched port's hole out of a layer whose top-left
 * corner sits at `origin` in the card's box: one clear disc the well's lip
 * wide per port, intersected, everything else kept.
 */
export function punchedHoleMask(
  card: Pick<CellCardModel, "widthCells" | "heightCells">,
  ports: readonly Pick<CellPort, "id" | "direction" | "rowOffset">[],
  origin: { x: number; y: number },
  /**
   * Maps a hole's centre in the card's box to the layer's own box, for a
   * layer drawn under a transform; its `scale` widens the disc to match.
   */
  place?: {
    centre: (centre: { x: number; y: number }) => { x: number; y: number };
    scale: number;
  },
): React.CSSProperties {
  if (ports.length === 0) return {};
  const scale = place?.scale ?? 1;
  const layers = ports.map((port) => {
    const cardCentre = punchedPortCardCentre(card, port);
    const centre = place ? place.centre(cardCentre) : cardCentre;
    return `radial-gradient(circle at ${centre.x - origin.x}px ${centre.y - origin.y}px, transparent ${(PUNCH_OUTER_RADIUS - 0.25) / scale}px, black ${(PUNCH_OUTER_RADIUS + 0.25) / scale}px)`;
  });
  const image = layers.join(", ");
  return {
    maskImage: image,
    WebkitMaskImage: image,
    maskComposite: "intersect",
    WebkitMaskComposite: "source-in",
  };
}

/**
 * The card's one "⋯": what the card is, then what can be done with it, the
 * way the workbench node's menu reads.
 */
export function CellCardMenu({
  title,
  detail,
  items,
  open,
  onOpenChange,
}: {
  title: string;
  detail?: React.ReactNode;
  items: readonly CellCardMenuItem[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Menu open={open} onOpenChange={onOpenChange}>
      <MenuTrigger
        render={
          <IconButton
            label={`Actions for ${title}`}
            size="2xs"
            variant="ghost"
            xstyle={open ? s.menuTriggerOpen : null}
          />
        }
      >
        <MoreHorizontal size={13} />
      </MenuTrigger>
      <MenuContent side="bottom" align="end" sideOffset={6}>
        <MenuGroup>
          <MenuGroupLabel xstyle={s.menuInfo}>
            <span {...stylex.props(s.menuInfoTitle)}>{title}</span>
            {detail ? <span>{detail}</span> : null}
          </MenuGroupLabel>
          {items.length ? <MenuSeparator /> : null}
          {items.map((item) => (
            <MenuItem
              key={item.id}
              icon={item.icon}
              danger={item.danger}
              disabled={item.disabled}
              onClick={item.onSelect}
            >
              {item.label}
            </MenuItem>
          ))}
        </MenuGroup>
      </MenuContent>
    </Menu>
  );
}

/**
 * A port's stem and hit target. A connected port's ring and well are the glass
 * stage's; an open port draws its own Opus ring. A punched port has no stem:
 * it sits in a hole through the plate, which this draws whether a pipe runs
 * into it or not.
 */
function CellCardPort({
  card,
  port,
  width,
  connected,
  hot,
  punched,
  open,
  material,
  pipe,
  onPortPointerDown,
}: {
  card: CellCardModel;
  port: CellPort;
  width: number;
  connected: boolean;
  hot: boolean;
  punched: boolean;
  open: boolean;
  material: CellGlassMaterial;
  pipe: PipeFamily;
  onPortPointerDown: CellCardBaseProps["onPortPointerDown"];
}) {
  const [hovered, setHovered] = React.useState(false);
  const input = port.direction === "input";
  const centre = punched
    ? punchedPortCardCentre(card, port)
    : {
        x: input ? -CELL_SIZE / 2 : width + CELL_SIZE / 2,
        y: (port.rowOffset + 0.5) * CELL_SIZE,
      };
  const isService = port.kind === "service";
  const portColor = port.mutedCaption
    ? tokens.colorSubtle
    : isService
      ? tokens.colorAccent
      : artifactTypeColor(port.artifactTypeId, tokens.colorMuted);
  const sequence = port.shape === "many";
  const plugSplitIndex =
    port.direction === "input" ? port.id.indexOf("::") : -1;
  const dropInputAttrs =
    port.direction === "input" && !isService
      ? plugSplitIndex >= 0
        ? {
            "data-input-node-id": card.id,
            "data-input-plug-port": port.id.slice(0, plugSplitIndex),
            "data-input-plug-id": port.id.slice(plugSplitIndex + 2),
          }
        : {
            "data-input-node-id": card.id,
            "data-input-port-name": port.id,
          }
      : undefined;
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
      {punched ? null : (
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
      )}
      <button
        type="button"
        data-port-id={port.id}
        data-port-direction={port.direction}
        data-port-well={punched ? "punched" : undefined}
        data-port-kind={port.kind ?? "artifact"}
        data-port-muted={port.mutedCaption ? "true" : undefined}
        title={port.mutedCaption}
        data-port-connected={connected ? "true" : "false"}
        data-port-card-id={card.id}
        data-port-hot={hot ? "true" : "false"}
        {...dropInputAttrs}
        aria-label={`${card.title} ${port.direction} ${port.name} (${
          isService
            ? `service ${port.serviceContractLabel ?? port.artifactTypeId}`
            : `${sequence ? "list" : "single"} ${port.artifactTypeId}`
        })`}
        onPointerDown={(event) => {
          event.stopPropagation();
          onPortPointerDown?.(card.id, port, event);
        }}
        onPointerEnter={punched ? () => setHovered(true) : undefined}
        onPointerLeave={punched ? () => setHovered(false) : undefined}
        {...styled(
          {
            left: centre.x - PORT_HIT_SIZE / 2,
            top: centre.y - PORT_HIT_SIZE / 2,
            "--cell-port": portColor,
          } as React.CSSProperties,
          s.port,
          punched ? s.portPunched : hot && s.portHot,
        )}
      >
        {punched ? (
          <PunchedPortSocket
            side={input ? "left" : "right"}
            color={portColor}
            sequence={sequence}
            connected={connected}
            hot={hot}
            hovered={hovered}
            open={open}
            material={material}
            pipe={pipe}
          />
        ) : connected ? null : (
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
  /** A field's new value: a primitive, or a whole object or list. */
  onConfigChange?: (cardId: string, fieldId: string, value: unknown) => void;
  /** Opens or closes a config section: a group, the advanced fold, an object. */
  onToggleConfigSection?: (
    cardId: string,
    sectionKey: string,
    open: boolean,
  ) => void;
  onApplySecret?: (
    cardId: string,
    name: string,
    value: string,
  ) => Promise<boolean>;
  onRemoveSecret?: (cardId: string, name: string) => Promise<boolean>;
  onToggleAppendix?: (cardId: string) => void;
  /** Opens the engine picker for an empty required service input. */
  onPickServiceEngine?: (cardId: string, portName: string) => void;
}

const STATUS_TEXT = {
  idle: undefined,
  done: "Done",
  working: "Working",
  error: "Error",
} as const;

function CellPortTab({ port, punched }: { port: CellPort; punched: boolean }) {
  const output = port.direction === "output";
  const isService = port.kind === "service";
  const muted = Boolean(port.mutedCaption);
  return (
    <span
      data-port-tab={port.id}
      data-port-kind={port.kind ?? "artifact"}
      data-port-muted={muted ? "true" : undefined}
      title={
        port.mutedCaption
          ? port.mutedCaption
          : isService
            ? port.serviceContractLabel
            : punched
              ? port.name
              : undefined
      }
      {...stylex.props(
        s.portTab,
        output && s.portTabOutput,
        punched && s.portTabPunched,
        muted && s.portTabMuted,
      )}
    >
      <span {...stylex.props(s.portName)}>{port.name}</span>
      {port.mutedCaption ? (
        <span
          data-port-caption={port.mutedCaption}
          {...stylex.props(s.portCaption)}
        >
          {port.mutedCaption}
        </span>
      ) : null}
      {!output && port.required ? (
        <span {...stylex.props(s.portMeta)}>*</span>
      ) : null}
      {isService ? (
        <span {...stylex.props(s.portMeta)}>· service</span>
      ) : port.shape === "many" ? (
        <span {...stylex.props(s.portMeta)}>· list</span>
      ) : null}
    </span>
  );
}

function ServicePortAffordance({
  cardId,
  port,
  connected,
  prompt,
  onPick,
}: {
  cardId: string;
  port: CellPort;
  connected: boolean;
  prompt: ServicePortPrompt | undefined;
  onPick?: (cardId: string, portName: string) => void;
}) {
  if (!prompt || connected || port.direction !== "input") return null;
  if (prompt.mode === "empty") {
    if (prompt.settingsHref) {
      return (
        <a
          href={prompt.settingsHref}
          data-service-port-empty={port.id}
          title={prompt.title}
          onPointerDown={stopCardDrag}
          {...stylex.props(s.emptyEngine)}
        >
          {prompt.label}
        </a>
      );
    }
    return (
      <span
        data-service-port-empty={port.id}
        title={prompt.title}
        onPointerDown={stopCardDrag}
        {...stylex.props(s.emptyEngine)}
      >
        {prompt.label}
      </span>
    );
  }
  if (!onPick) return null;
  return (
    <Button
      size="xs"
      variant="dashed"
      data-pick-engine={port.id}
      title={prompt.label}
      xstyle={s.pickEngine}
      onPointerDown={stopCardDrag}
      onClick={() => onPick(cardId, port.id)}
    >
      {prompt.label}
    </Button>
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
    onToggleConfigSection,
    onApplySecret,
    onRemoveSecret,
    onToggleAppendix,
    onPickServiceEngine,
  } = props;
  const state = useResolvedCardState(card.id, props);
  const punched = props.well === "punched";
  // Punched, every row's content starts past the hole in the plate.
  const punchedInset = punched ? PUNCHED_LABEL_INSET : undefined;
  const layout = computeOperatorCardLayout(card, surface);
  const groups = surface.instancePlugGroups ?? [];
  const configFields = surface.configFields ?? [];
  const secretInputs = surface.secretInputs ?? [];
  const appendix = surface.appendix ?? null;

  // Every instance plug is an input port on its own row: one the model already
  // lists keeps its entry, and a plug it does not list gets one here.
  const ports: CellPort[] = [...card.ports];
  const listedPortIds = new Set(card.ports.map((port) => port.id));
  const plugIds = new Set<string>();
  const connected = new Set(connectedPortIds);
  for (const group of groups) {
    group.plugs.forEach((plug, index) => {
      const compositeId = `${group.portName}::${plug.plugId}`;
      plugIds.add(plug.plugId);
      plugIds.add(compositeId);
      if (plug.connected) {
        connected.add(cellPortKey("input", plug.plugId));
        connected.add(cellPortKey("input", compositeId));
      }
      if (listedPortIds.has(plug.plugId) || listedPortIds.has(compositeId)) {
        return;
      }
      ports.push({
        id: plug.plugId,
        name: plug.label,
        direction: "input",
        rowOffset: plugRowOffset(group, index),
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
  const statusAriaWord =
    card.status === "done"
      ? "done"
      : card.status === "working"
        ? "working"
        : card.status === "error"
          ? "failed"
          : (statusText ?? "").toLowerCase();
  // Always shown, not only while selected: a card that still needs a key
  // says so at rest.
  const headerMeta =
    secretInputs.length > 0 ? (
      <span data-card-credentials="true" onPointerDown={stopCardDrag}>
        <CellCredentialsDialog
          cardId={card.id}
          cardTitle={card.title}
          inputs={secretInputs}
          onApply={
            onApplySecret
              ? (name, value) => onApplySecret(card.id, name, value)
              : undefined
          }
          onRemove={
            onRemoveSecret ? (name) => onRemoveSecret(card.id, name) : undefined
          }
        />
      </span>
    ) : null;
  const headerExtra = (
    <>
      {statusText ? (
        <span
          role="status"
          aria-label={`${card.title} ${statusAriaWord}`}
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
      headerMeta={headerMeta}
      resizable={card.resizable === true}
    >
      {[...portRows].map(([rowOffset, { input, output }]) => (
        <div
          key={`port-row:${rowOffset}`}
          data-port-row={rowOffset}
          {...styled(
            {
              top: plateRowTop(rowOffset),
              height: CELL_SIZE,
              paddingInline: punchedInset,
            },
            s.band,
            s.portRow,
          )}
        >
          <span
            data-input-node-id={
              input && input.kind !== "service" ? card.id : undefined
            }
            data-input-port-name={
              input && input.kind !== "service" ? input.id : undefined
            }
            {...stylex.props(
              s.portSlot,
              s.portSlotInput,
              input && input.kind !== "service" && s.portSlotInputDrop,
            )}
          >
            {input ? <CellPortTab port={input} punched={punched} /> : null}
            {input ? (
              <ServicePortAffordance
                cardId={card.id}
                port={input}
                connected={isPortConnected(connected, input)}
                prompt={surface.servicePortPrompts?.[input.id]}
                onPick={onPickServiceEngine}
              />
            ) : null}
          </span>
          <span {...stylex.props(s.portSlot, s.portSlotOutput)}>
            {output ? <CellPortTab port={output} punched={punched} /> : null}
          </span>
        </div>
      ))}

      {groups.map((group) => (
        <React.Fragment key={`plugs:${group.portName}`}>
          {group.plugs.map((plug, index) => {
            const rawPlugId = plug.plugId.startsWith(`${group.portName}::`)
              ? plug.plugId.slice(group.portName.length + 2)
              : plug.plugId;
            return (
              <div
                key={plug.plugId}
                data-instance-plug-row={plug.plugId}
                data-plug-port={group.portName}
                data-input-node-id={card.id}
                data-input-plug-port={group.portName}
                data-input-plug-id={rawPlugId}
                {...styled(
                  {
                    top: plateRowTop(plugRowOffset(group, index)),
                    height: CELL_SIZE,
                    paddingLeft: punchedInset,
                  },
                  s.band,
                  s.plugRow,
                )}
              >
                <span
                  title={group.title}
                  {...stylex.props(s.portTab, punched && s.portTabPunched)}
                >
                  <span {...stylex.props(s.plugIndex)}>#{index + 1}</span>
                  <span {...stylex.props(s.portName)}>{plug.label}</span>
                </span>
                <span {...stylex.props(s.grow)} />
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
            );
          })}
          {group.canAdd ? (
            <div
              data-instance-plug-add={group.portName}
              {...styled(
                {
                  top: plateRowTop(plugRowOffset(group, group.plugs.length)),
                  height: CELL_SIZE,
                  paddingLeft: punchedInset,
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
        <CellConfigBand
          fields={configFields}
          sections={surface.configSections}
          connectedPorts={surface.connectedInputPorts}
          style={bandStyle(
            layout.configBand.startRow,
            layout.configBand.heightCells,
          )}
          className={stylex.props(s.band).className}
          onPointerDown={stopCardDrag}
          onChange={
            onConfigChange
              ? (fieldId, value) => onConfigChange(card.id, fieldId, value)
              : undefined
          }
          onToggleSection={
            onToggleConfigSection
              ? (key, open) => onToggleConfigSection(card.id, key, open)
              : undefined
          }
        />
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

export const CellOperatorCard = React.memo(CellOperatorCardImpl);

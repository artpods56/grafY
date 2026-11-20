"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { X } from "lucide-react";

import { IconButton } from "@/components/ui/button";
import { Surface } from "@/components/ui/surface";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { useCellPipeState } from "./CellCanvasContext";
import type {
  CellDockedJoin,
  CellMarqueeRect,
  CellPipeAttachment,
  CellRemotePeerState,
} from "./cell-contracts";
import {
  CARD_PLATE_INSET_X,
  CELL_SIZE,
  STANDARD_CARD_WIDTH_CELLS,
  type CellCardModel,
} from "./cell-model";

/**
 * What the glass stage draws over the glass, in world units: the bridges of
 * docked pipes, the pipe selector pills, the marquee and other people's
 * cursors and drags. Render them inside a `CellViewportLayer`; each places
 * itself by world coordinates and takes the pointer only where it is drawn.
 */

/** The hit target around a docked seam. */
const JOIN_HIT_SIZE = 30;
/** Half the gap between two parallel strands of a list bridge. */
const SEQUENCE_STRAND_OFFSET = 2.65;
/** How far a bridge reaches past each plate edge, onto the card it joins. */
const BRIDGE_OVERHANG = 2;

const DEFAULT_PILL_WIDTH_CELLS = 6;
const DEFAULT_PILL_HEIGHT_CELLS = 1;
const DEFAULT_CARD_HEIGHT_CELLS = 6;

const NO_PIPE_IDS: ReadonlySet<string> = new Set();

const s = stylex.create({
  // A zero-size plane at the world origin; each overlay is placed inside it.
  plane: {
    position: "absolute",
    top: 0,
    left: 0,
    width: 0,
    height: 0,
    overflow: "visible",
    pointerEvents: "none",
  },

  join: {
    position: "absolute",
    boxSizing: "border-box",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 0,
    margin: 0,
    borderWidth: 0,
    borderRadius: "9999px",
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)":
        "color-mix(in srgb, var(--cell-join) 16%, transparent)",
    },
    cursor: "pointer",
    pointerEvents: "auto",
    touchAction: "none",
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorAccentBorder}`,
    },
  },
  joinArt: {
    display: "block",
    overflow: "visible",
    pointerEvents: "none",
  },
  joinDisabled: { opacity: 0.55 },

  pillBox: {
    position: "absolute",
    boxSizing: "border-box",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    pointerEvents: "auto",
    touchAction: "none",
    cursor: "pointer",
    userSelect: "none",
  },
  capsule: {
    boxSizing: "border-box",
    height: "24px",
    maxWidth: "100%",
    display: "flex",
    alignItems: "center",
    gap: "5px",
    paddingInlineStart: "8px",
    paddingInlineEnd: "3px",
    backgroundColor: tokens.colorChrome,
    borderColor: {
      default: tokens.colorBorder,
      ":hover:not(:disabled)": tokens.colorBorderStrong,
    },
    boxShadow: tokens.shadowNode,
    color: tokens.colorText,
    fontSize: "10px",
    whiteSpace: "nowrap",
    transitionProperty: "border-color",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
  },
  capsuleActive: {
    borderColor: {
      default: tokens.colorAccent,
      ":hover:not(:disabled)": tokens.colorAccent,
    },
  },
  capsuleDisabled: { color: tokens.colorSubtle },
  capsuleNoActions: { paddingInlineEnd: "8px" },
  colorDot: {
    flexShrink: 0,
    width: "7px",
    height: "7px",
    borderRadius: "9999px",
  },
  pillLabel: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    fontWeight: 500,
  },
  conversion: {
    flexShrink: 0,
    height: "14px",
    display: "inline-flex",
    alignItems: "center",
    paddingInline: "5px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
    fontSize: "9px",
  },
  actions: {
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
  },

  marquee: {
    position: "absolute",
    boxSizing: "border-box",
    backgroundColor: tokens.colorAccentSoft,
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorAccent,
    pointerEvents: "none",
  },

  ghost: {
    position: "absolute",
    boxSizing: "border-box",
    borderWidth: "1.5px",
    borderStyle: "dashed",
    borderRadius: "12px",
    pointerEvents: "none",
  },
  cursor: {
    position: "absolute",
    top: 0,
    left: 0,
    display: "grid",
    justifyItems: "start",
    gap: "2px",
    pointerEvents: "none",
    willChange: "transform",
  },
  pointer: {
    display: "block",
    width: "16px",
    height: "19px",
    overflow: "visible",
  },
  peerName: {
    maxWidth: "120px",
    marginTop: "-3px",
    marginLeft: "10px",
    paddingBlock: "1px",
    paddingInline: "5px",
    borderRadius: tokens.radiusSm,
    color: "white",
    fontSize: "10px",
    fontWeight: 600,
    lineHeight: 1.3,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
});

/** StyleX classes plus per-overlay world geometry. */
function placed(
  inline: React.CSSProperties,
  ...styles: stylex.StyleXStyles[]
): { className?: string; style: React.CSSProperties } {
  const props = stylex.props(...styles);
  return { className: props.className, style: { ...props.style, ...inline } };
}

// --- Docked bridges --------------------------------------------------------

export interface CellDockedBridgeLayerProps {
  joins: readonly CellDockedJoin[];
  selectedPipeIds?: ReadonlySet<string>;
  hoveredPipeId?: string | null;
  onJoinHover?: (pipeId: string | null) => void;
  onJoinSelect?: (
    pipeId: string,
    event: React.MouseEvent<HTMLButtonElement>,
  ) => void;
}

/**
 * The pipes of cards that sit edge to edge. Their ports face each other
 * across the 8px seam between the two plates, so the pipe is a short bridge
 * over the seam rather than a route through the gutter.
 */
export function CellDockedBridgeLayer({
  joins,
  selectedPipeIds = NO_PIPE_IDS,
  hoveredPipeId = null,
  onJoinHover,
  onJoinSelect,
}: CellDockedBridgeLayerProps) {
  if (joins.length === 0) return null;
  return (
    <div data-cell-docked-bridges="true" {...stylex.props(s.plane)}>
      {joins.map((join) => (
        <DockedBridge
          key={join.pipeId}
          join={join}
          selected={selectedPipeIds.has(join.pipeId)}
          hovered={hoveredPipeId === join.pipeId}
          onJoinHover={onJoinHover}
          onJoinSelect={onJoinSelect}
        />
      ))}
    </div>
  );
}

function DockedBridge({
  join,
  selected,
  hovered,
  onJoinHover,
  onJoinSelect,
}: {
  join: CellDockedJoin;
  selected: boolean;
  hovered: boolean;
  onJoinHover: CellDockedBridgeLayerProps["onJoinHover"];
  onJoinSelect: CellDockedBridgeLayerProps["onJoinSelect"];
}) {
  const pipeState = useCellPipeState(join.pipeId);
  const isSelected = selected || pipeState.selected;
  const active = isSelected || hovered || pipeState.hovered;
  const half = JOIN_HIT_SIZE / 2;
  const reach = CARD_PLATE_INSET_X + BRIDGE_OVERHANG;
  const strandYs = join.sequence
    ? [-SEQUENCE_STRAND_OFFSET, SEQUENCE_STRAND_OFFSET]
    : [0];
  const label = join.projectionLabel ?? join.conversionLabel ?? null;
  return (
    <button
      type="button"
      data-docked-join={join.pipeId}
      data-docked-sequence={join.sequence ? "true" : "false"}
      data-docked-enabled={join.enabled ? "true" : "false"}
      data-docked-active={active ? "true" : "false"}
      aria-pressed={isSelected}
      aria-label={`Docked pipe ${join.sourcePortId} to ${join.targetPortId}${label ? ` (${label})` : ""}`}
      onPointerEnter={() => onJoinHover?.(join.pipeId)}
      onPointerLeave={() => onJoinHover?.(null)}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => onJoinSelect?.(join.pipeId, event)}
      {...placed(
        {
          left: join.seamPoint.x - half,
          top: join.seamPoint.y - half,
          width: JOIN_HIT_SIZE,
          height: JOIN_HIT_SIZE,
          "--cell-join": join.color,
        } as React.CSSProperties,
        s.join,
      )}
    >
      <svg
        aria-hidden="true"
        width={JOIN_HIT_SIZE}
        height={JOIN_HIT_SIZE}
        viewBox={`${-half} ${-half} ${JOIN_HIT_SIZE} ${JOIN_HIT_SIZE}`}
        {...stylex.props(s.joinArt, !join.enabled && s.joinDisabled)}
      >
        <g
          data-docked-strands={strandYs.length}
          fill="none"
          strokeLinecap="round"
          strokeWidth={join.sequence ? 2.1 : 3}
          strokeDasharray={join.enabled ? undefined : "2.5 2"}
          style={{ stroke: join.color }}
        >
          {strandYs.map((y) => (
            <line key={y} x1={-reach} y1={y} x2={reach} y2={y} />
          ))}
        </g>
        {active ? (
          // The coupler: a collar over the seam, the pipe's colour on chrome.
          <rect
            data-docked-coupler="true"
            x={-2.5}
            y={join.sequence ? -6.5 : -5.5}
            width={5}
            height={join.sequence ? 13 : 11}
            rx={2}
            strokeWidth={isSelected ? 1.6 : 1.2}
            style={{ fill: tokens.colorChrome, stroke: join.color }}
          />
        ) : null}
      </svg>
    </button>
  );
}

// --- Pipe selector pill ----------------------------------------------------

export interface CellEdgeSelectorPillProps {
  attachment: CellPipeAttachment;
  selected?: boolean;
  hovered?: boolean;
  onHover?: (pipeId: string | null) => void;
  onSelect?: (pipeId: string, event?: React.MouseEvent<HTMLElement>) => void;
  onRemove?: (pipeId: string) => void;
  /** More actions after the label, e.g. a menu trigger. */
  children?: React.ReactNode;
}

/**
 * A pipe's label above the glass: a 24px capsule in the middle of a whole-cell
 * grab box (3 × 1 cells unless the attachment says otherwise), centred on the
 * pipe segment it names. Hovering or selecting it lights the pipe under it.
 */
export function CellEdgeSelectorPill({
  attachment,
  selected,
  hovered,
  onHover,
  onSelect,
  onRemove,
  children,
}: CellEdgeSelectorPillProps) {
  const pipeState = useCellPipeState(attachment.pipeId);
  const isSelected = selected ?? pipeState.selected;
  const isHovered = hovered ?? pipeState.hovered;
  const width = (attachment.widthCells || DEFAULT_PILL_WIDTH_CELLS) * CELL_SIZE;
  const height =
    (attachment.heightCells || DEFAULT_PILL_HEIGHT_CELLS) * CELL_SIZE;
  const hasActions = children != null || onRemove != null;

  return (
    <div
      data-edge-pill={attachment.pipeId}
      data-edge-selector-pill={attachment.pipeId}
      data-edge-selector-orientation={attachment.segmentOrientation}
      data-edge-selector-docked={attachment.isDocked ? "true" : "false"}
      data-selected={isSelected ? "true" : "false"}
      data-hovered={isHovered ? "true" : "false"}
      onPointerEnter={() => onHover?.(attachment.pipeId)}
      onPointerLeave={() => onHover?.(null)}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => onSelect?.(attachment.pipeId, event)}
      {...placed(
        {
          left: attachment.anchor.x - width / 2,
          top: attachment.anchor.y - height / 2,
          width,
          height,
        },
        s.pillBox,
      )}
    >
      <Surface
        tone="raised"
        padding="none"
        shape="pill"
        xstyle={[
          s.capsule,
          (isSelected || isHovered) && s.capsuleActive,
          !attachment.enabled && s.capsuleDisabled,
          !hasActions && s.capsuleNoActions,
        ]}
      >
        <span
          aria-hidden="true"
          data-edge-selector-color="true"
          {...placed({ backgroundColor: attachment.color }, s.colorDot)}
        />
        <span
          data-edge-selector-label="true"
          title={attachment.label}
          {...stylex.props(s.pillLabel)}
        >
          {attachment.label}
        </span>
        {attachment.conversionLabel ? (
          <span
            data-edge-selector-conversion="true"
            {...stylex.props(s.conversion)}
          >
            {attachment.conversionLabel}
          </span>
        ) : null}
        {hasActions ? (
          <span {...stylex.props(s.actions)}>
            {children}
            {onRemove ? (
              <IconButton
                size="2xs"
                variant="ghost"
                shape="round"
                label={`Remove ${attachment.label}`}
                onPointerDown={(event) => event.stopPropagation()}
                onClick={(event) => {
                  event.stopPropagation();
                  onRemove(attachment.pipeId);
                }}
              >
                <X size={11} />
              </IconButton>
            ) : null}
          </span>
        ) : null}
      </Surface>
    </div>
  );
}

// --- Marquee ---------------------------------------------------------------

/** The rubber-band selection box, from wherever the drag started. */
export function CellMarqueeOverlay({
  marquee,
}: {
  marquee: CellMarqueeRect | null;
}) {
  if (marquee === null) return null;
  const left = Math.min(marquee.start.x, marquee.current.x);
  const top = Math.min(marquee.start.y, marquee.current.y);
  const width = Math.abs(marquee.current.x - marquee.start.x);
  const height = Math.abs(marquee.current.y - marquee.start.y);
  return (
    <div
      aria-hidden="true"
      data-cell-marquee="true"
      {...placed({ left, top, width, height }, s.marquee)}
    />
  );
}

// --- Remote presence -------------------------------------------------------

/**
 * Other people on the canvas: a dashed frame where each card they drag will
 * land, and their pointer with their name.
 */
export function CellRemotePresenceLayer({
  peers,
  cards,
}: {
  peers: readonly CellRemotePeerState[];
  cards?: readonly CellCardModel[];
}) {
  const cardById = React.useMemo(
    () => new Map((cards ?? []).map((card) => [card.id, card])),
    [cards],
  );
  if (peers.length === 0) return null;
  return (
    <div
      aria-hidden="true"
      data-cell-remote-presence="true"
      {...stylex.props(s.plane)}
    >
      {peers.map((peer) => (
        <React.Fragment key={peer.sessionId ?? peer.actorId}>
          {Object.entries(peer.draggingCards).map(([cardId, cell]) => {
            const card = cardById.get(cardId);
            const widthCells = card?.widthCells ?? STANDARD_CARD_WIDTH_CELLS;
            const heightCells = card?.heightCells ?? DEFAULT_CARD_HEIGHT_CELLS;
            return (
              <div
                key={cardId}
                data-remote-drag-ghost={`${peer.actorId}:${cardId}`}
                {...placed(
                  {
                    left: cell.col * CELL_SIZE,
                    top: cell.row * CELL_SIZE,
                    width: widthCells * CELL_SIZE,
                    height: heightCells * CELL_SIZE,
                    borderColor: peer.color,
                    backgroundColor: `color-mix(in srgb, ${peer.color} 10%, transparent)`,
                  },
                  s.ghost,
                )}
              />
            );
          })}
          {peer.cursor !== null ? (
            <div
              data-remote-peer-cursor={peer.actorId}
              data-remote-peer-activity={peer.activity ?? "idle"}
              {...placed(
                {
                  transform: `translate3d(${peer.cursor.x}px, ${peer.cursor.y}px, 0)`,
                },
                s.cursor,
              )}
            >
              <svg viewBox="0 0 24 24" {...stylex.props(s.pointer)}>
                {/* The tip is the hotspot, at (0, 0). */}
                <path
                  d="M0.6 0.6v17.4l4.9-4.7 3.5 8.1 2.9-1.3-3.6-7.9H18z"
                  strokeWidth={1.4}
                  strokeLinejoin="round"
                  paintOrder="stroke fill"
                  style={{ fill: peer.color, stroke: tokens.colorChrome }}
                />
              </svg>
              <span
                data-remote-peer-name="true"
                {...placed({ backgroundColor: peer.color }, s.peerName)}
              >
                {peer.displayName}
              </span>
            </div>
          ) : null}
        </React.Fragment>
      ))}
    </div>
  );
}

"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { artifactTypeColor } from "@/features/workbench/canvas/nodes.css";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { ConnectorFitting } from "./pipe-visuals";
import type { CellGlassMaterial } from "./cell-glass-stage";
import {
  CARD_HEADER_HEIGHT,
  CARD_HEADER_TOP,
  CARD_PLATE_BOTTOM_INSET,
  CARD_PLATE_INSET_X,
  CARD_PLATE_TOP,
  CELL_SIZE,
  type CellCardModel,
  type CellPort,
  type WorldPoint,
} from "./cell-model";

/**
 * One card on the cell canvas, drawn without React Flow.
 *
 * The card's outer box covers its cells exactly. Rows 0 and 1 hold the floating
 * title (0..24) and the plate's subtitle strip (26..50), so a status or a long
 * subtitle never moves a port row. Every port row below is pinned to
 * `(rowOffset + 0.5) * CELL_SIZE`, the centre the router and the glass stage
 * use for the port's well.
 *
 * A connected port's ring and well are drawn by the glass stage under the
 * card; the card draws only the open ring of an unconnected port, with the same
 * Opus fitting, so the two read as one mark.
 */

export interface CellCardProps {
  card: CellCardModel;
  /** Applied only to the dragged/settling card; undefined when resting. */
  visualOffset?: WorldPoint;
  material: CellGlassMaterial;
  selected: boolean;
  dragging: boolean;
  /** Port ids on this card that currently have a pipe (glass stage draws their well + connector fitting). */
  connectedPortIds: ReadonlySet<string>;
  /** `${cardId}:${portId}` when a port is actively hovered/targeted during connection wiring. */
  activePortKey?: string | null;
  onCardPointerDown: (
    cardId: string,
    event: React.PointerEvent<HTMLDivElement>,
  ) => void;
  onPortPointerDown: (
    cardId: string,
    port: CellPort,
    event: React.PointerEvent<HTMLButtonElement>,
  ) => void;
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
/** Cards stand on the glass: a contact shadow, then a soft one cast below. */
const REST_SHADOW =
  "0 1px 2px light-dark(color-mix(in srgb, black 10%, transparent), color-mix(in srgb, black 45%, transparent)), 0 8px 20px -6px light-dark(color-mix(in srgb, black 18%, transparent), color-mix(in srgb, black 55%, transparent)), 0 22px 44px -14px light-dark(color-mix(in srgb, black 16%, transparent), color-mix(in srgb, black 50%, transparent))";
/** Liquid glass cards: a bright top edge and a faint bottom one. */
const LIQUID_SPECULAR =
  "inset 0 1px 0 light-dark(color-mix(in srgb, white 95%, transparent), color-mix(in srgb, white 24%, transparent)), inset 0 -1px 0 color-mix(in srgb, white 10%, transparent)";
const SELECTION_HALO = `0 0 0 3px color-mix(in srgb, ${tokens.colorAccent} 8%, transparent)`;
const LIQUID_BORDER =
  "light-dark(color-mix(in srgb, white 85%, transparent), color-mix(in srgb, white 14%, transparent))";

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
    gap: "8px",
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
  status: {
    flexShrink: 0,
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    whiteSpace: "nowrap",
  },
  statusDot: {
    width: "6px",
    height: "6px",
    borderRadius: "9999px",
  },
  statusDone: { backgroundColor: tokens.colorSuccess },
  statusWorking: { backgroundColor: tokens.colorInfo },
  plate: {
    position: "relative",
    boxSizing: "border-box",
    overflow: "visible",
    borderWidth: `${PLATE_BORDER}px`,
    borderStyle: "solid",
    borderRadius: tokens.radiusMd,
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
  subtitle: {
    boxSizing: "border-box",
    paddingInline: "10px",
    display: "flex",
    alignItems: "center",
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    color: tokens.colorSubtle,
    fontFamily: MONO_FONT,
    fontSize: "10px",
    overflow: "hidden",
    whiteSpace: "nowrap",
  },
  subtitleText: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  portRow: {
    position: "absolute",
    left: 0,
    right: 0,
    boxSizing: "border-box",
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
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
  portLabelOutput: { textAlign: "right" },
  portMeta: { color: tokens.colorSubtle },
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
});

/** StyleX classes plus per-card geometry, which changes with every card. */
function styled(
  inline: React.CSSProperties,
  ...styles: stylex.StyleXStyles[]
): { className?: string; style: React.CSSProperties } {
  const props = stylex.props(...styles);
  return { className: props.className, style: { ...props.style, ...inline } };
}

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

/** Port centre relative to the card's outer origin. */
function portCentre(card: CellCardModel, port: CellPort): WorldPoint {
  const width = card.widthCells * CELL_SIZE;
  return {
    x: port.direction === "input" ? -CELL_SIZE / 2 : width + CELL_SIZE / 2,
    y: (port.rowOffset + 0.5) * CELL_SIZE,
  };
}

function CellCardImpl({
  card,
  visualOffset,
  material,
  selected,
  dragging,
  connectedPortIds,
  activePortKey,
  onCardPointerDown,
  onPortPointerDown,
}: CellCardProps) {
  const width = card.widthCells * CELL_SIZE;
  const height = card.heightCells * CELL_SIZE;
  const x = card.col * CELL_SIZE + (visualOffset?.x ?? 0);
  const y = card.row * CELL_SIZE + (visualOffset?.y ?? 0);
  const active = selected || dragging;
  const plateHeight = height - CARD_PLATE_TOP - CARD_PLATE_BOTTOM_INSET;
  // Rows inside the plate are placed from its padding box, below the border.
  const plateContentTop = CARD_PLATE_TOP + PLATE_BORDER;

  const rows = new Map<number, { input?: CellPort; output?: CellPort }>();
  for (const port of card.ports) {
    const row = rows.get(port.rowOffset) ?? {};
    row[port.direction] = port;
    rows.set(port.rowOffset, row);
  }

  const handleCardPointerDown = (event: React.PointerEvent<HTMLDivElement>) =>
    onCardPointerDown(card.id, event);

  return (
    <div
      data-cell-card="true"
      data-card-id={card.id}
      data-material={material}
      data-dragging={dragging ? "true" : "false"}
      data-selected={selected ? "true" : "false"}
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
        <span {...stylex.props(s.title, active && s.titleActive)}>
          {card.title}
        </span>
        {card.status === "done" || card.status === "working" ? (
          <span data-card-status={card.status} {...stylex.props(s.status)}>
            <span
              aria-hidden="true"
              {...stylex.props(
                s.statusDot,
                card.status === "done" ? s.statusDone : s.statusWorking,
              )}
            />
            {card.status === "done" ? "Done" : "Working"}
          </span>
        ) : null}
      </div>
      <article
        onPointerDown={handleCardPointerDown}
        {...styled(
          {
            height: plateHeight,
            marginInline: CARD_PLATE_INSET_X,
            cursor: dragging ? "grabbing" : "grab",
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
        )}
      >
        <div
          {...styled(
            // Plate border + this strip end at 62, above the first port row.
            { height: CARD_HEADER_HEIGHT - PLATE_BORDER },
            s.subtitle,
          )}
        >
          <span {...stylex.props(s.subtitleText)}>{card.subtitle}</span>
        </div>
        {[...rows].map(([rowOffset, { input, output }]) => (
          <div
            key={rowOffset}
            data-port-row={rowOffset}
            {...styled(
              {
                top: rowOffset * CELL_SIZE - plateContentTop,
                height: CELL_SIZE,
              },
              s.portRow,
            )}
          >
            <span {...stylex.props(s.portLabel)}>
              {input ? portLabel(input) : null}
            </span>
            <span {...stylex.props(s.portLabel, s.portLabelOutput)}>
              {output ? portLabel(output) : null}
            </span>
          </div>
        ))}
      </article>
      {card.ports.map((port) => {
        const centre = portCentre(card, port);
        const connected = connectedPortIds.has(port.id);
        const hot = activePortKey === `${card.id}:${port.id}`;
        const portColor = artifactTypeColor(
          port.artifactTypeId,
          tokens.colorMuted,
        );
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
          <React.Fragment key={port.id}>
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
                onPortPointerDown(card.id, port, event);
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
          </React.Fragment>
        );
      })}
    </div>
  );
}

export const CellCard = React.memo(CellCardImpl);

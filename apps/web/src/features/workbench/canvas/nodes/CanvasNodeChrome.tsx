"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Trash2 } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";
import { useHandleIsDocked } from "../edges/useDockedConnection";
import {
  GRID_CELL_SIZE_DEFAULT,
  PORT_RAIL_ROW_HEIGHT_CELLS,
  lengthFromSpan,
} from "../grid-layout";
import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import { NodeMenu, type NodeMenuItem } from "./NodeMenu";
import { PortBall } from "./PortBall";

/** Height of the name row that sits above a node's plate. */
export const NODE_HEADER_HEIGHT = 24;

/**
 * Shared chrome for operator nodes and Artifact Viewers, on the artifact
 * card's layout: the name sits above the plate, port labels sit inside it at
 * its edges, and each label's ball sits just outside, on a stem back to the
 * plate.
 */
export const nodeChrome = stylex.create({
  header: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "6px",
    height: "24px",
    paddingInline: "2px 0",
    userSelect: "none",
  },
  title: {
    minWidth: 0,
    flex: 1,
    overflow: "hidden",
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
    letterSpacing: "-0.01em",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    transitionProperty: "opacity",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
  },
  // At rest the name recedes, like an artifact's label; picked up it reads in
  // full.
  titleQuiet: { opacity: 0.6 },
  headerButton: {
    width: "22px",
    height: "22px",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    borderWidth: 0,
    borderRadius: "9999px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
    },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorText },
    cursor: "pointer",
  },
  // The "⋯" exists only while the node is picked up (or its menu is open),
  // and rises in (keyframes in globals.css).
  menuSlot: {
    display: "grid",
    flexShrink: 0,
    animationName: "grafy-node-detail-in",
    animationDuration: {
      default: "160ms",
      "@media (prefers-reduced-motion: reduce)": "0s",
    },
    animationTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
    animationFillMode: "both",
  },
  portRail: {
    display: "grid",
  },
  portRailRow: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
    alignItems: "stretch",
    boxSizing: "border-box",
  },
  portRailSlot: {
    position: "relative",
    minWidth: 0,
    display: "flex",
    alignItems: "center",
  },
  portRailSlotOut: {
    justifyContent: "flex-end",
  },
  tabRow: {
    position: "relative",
    display: "flex",
    width: "100%",
    height: "100%",
    minHeight: "28px",
    alignItems: "center",
  },
  tabRowOut: { justifyContent: "flex-end" },
  // A port's name, quiet and flush with the plate's edge; its ball carries the
  // type colour outside.
  tab: {
    display: "flex",
    alignItems: "center",
    gap: "4px",
    maxWidth: "calc(100% - 8px)",
    height: "22px",
    paddingInline: "10px 8px",
    borderWidth: 0,
    borderRadius: tokens.radiusSm,
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
    },
    color: { default: tokens.colorMuted, ":hover": tokens.colorText },
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
  },
  tabLabel: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  tabShape: { flexShrink: 0, color: tokens.colorSubtle },
  tabIn: {},
  tabOut: {
    flexDirection: "row-reverse",
    paddingInline: "8px 10px",
  },
  tabDocked: {
    visibility: "hidden",
    pointerEvents: "none",
  },
  tabInactive: { opacity: 0.55 },
  // Where a row's ball hangs: centred on the row, outside the plate. The row
  // sits flush with the plate's inside edge, so the 30px slot starts the 1px
  // border and the 8px gap further out; a row set in from the plate says how
  // far through `--port-inset`.
  ballAnchor: {
    position: "absolute",
    top: "50%",
    marginTop: "-15px",
    zIndex: 1,
  },
  ballAnchorIn: { left: "calc(-39px - var(--port-inset, 0px))" },
  ballAnchorOut: { right: "calc(-39px - var(--port-inset, 0px))" },
});

export function canvasNodeInteractionProps(
  props: ReturnType<typeof stylex.props>,
) {
  return {
    ...props,
    className: `nodrag nowheel${props.className ? ` ${props.className}` : ""}`,
  };
}

export type CanvasNodeOverflowItem = NodeMenuItem;

/**
 * The name row above a node's plate: the name, its status, and one "⋯" that
 * opens on what the node is and then what can be done with it.
 */
export function CanvasNodeHeader({
  title,
  selected,
  status,
  aboutTitle,
  aboutDescription,
  aboutFooter,
  overflowItems,
  onRemove,
  removeLabel = "Delete node",
  onMenuOpenChange,
  children,
}: {
  title: string;
  selected: boolean;
  status?: React.ReactNode;
  aboutTitle: string;
  aboutDescription: React.ReactNode;
  aboutFooter?: React.ReactNode;
  overflowItems?: readonly CanvasNodeOverflowItem[];
  onRemove?: () => void;
  removeLabel?: string;
  onMenuOpenChange?: (open: boolean) => void;
  children?: React.ReactNode;
}) {
  const [menuOpen, setMenuOpen] = React.useState(false);
  const items: NodeMenuItem[] = [
    ...(overflowItems ?? []),
    ...(onRemove
      ? [
          {
            id: "remove",
            label: removeLabel,
            icon: <Trash2 size={13} />,
            danger: true,
            onClick: onRemove,
          },
        ]
      : []),
  ];
  const showMenu = selected || menuOpen;
  return (
    <header data-node-header="true" {...stylex.props(nodeChrome.header)}>
      <span
        {...stylex.props(
          nodeChrome.title,
          selected ? null : nodeChrome.titleQuiet,
        )}
        title={title}
      >
        {title}
      </span>
      {status}
      {children}
      {showMenu ? (
        <span
          {...canvasNodeInteractionProps(stylex.props(nodeChrome.menuSlot))}
        >
          <NodeMenu
            label={`Actions for ${title}`}
            info={{
              title: aboutTitle,
              lines: [aboutDescription],
              footer: aboutFooter,
            }}
            items={items}
            align="end"
            onOpenChange={(open) => {
              setMenuOpen(open);
              onMenuOpenChange?.(open);
            }}
          />
        </span>
      ) : null}
    </header>
  );
}

export function CanvasPortRail({
  rows,
}: {
  rows: readonly { input?: React.ReactNode; output?: React.ReactNode }[];
}) {
  const grid = useOptionalCanvasGridSettings();
  const cellSize = grid?.settings.cellSize ?? GRID_CELL_SIZE_DEFAULT;
  const rowHeight = lengthFromSpan(PORT_RAIL_ROW_HEIGHT_CELLS, cellSize);
  if (!rows.length) return null;

  return (
    <div data-testid="port-rail" {...stylex.props(nodeChrome.portRail)}>
      {rows.map((row, index) => (
        <div
          key={index}
          data-testid="port-rail-row"
          style={{ height: rowHeight }}
          {...stylex.props(nodeChrome.portRailRow)}
        >
          <div {...stylex.props(nodeChrome.portRailSlot)}>{row.input}</div>
          <div
            {...stylex.props(
              nodeChrome.portRailSlot,
              nodeChrome.portRailSlotOut,
            )}
          >
            {row.output}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * A port's ball, hung outside the plate level with its row. `centerY` pins the
 * ball's centre that far down a tall row instead of at its middle.
 */
export function CanvasPortBall({
  centerY,
  ...props
}: React.ComponentProps<typeof PortBall> & { centerY?: number }) {
  return (
    <span
      {...stylex.props(
        nodeChrome.ballAnchor,
        props.side === "input"
          ? nodeChrome.ballAnchorIn
          : nodeChrome.ballAnchorOut,
      )}
      style={
        centerY === undefined ? undefined : { top: centerY - 15, marginTop: 0 }
      }
    >
      <PortBall {...props} />
    </span>
  );
}

export function CanvasPortTab({
  nodeId,
  label,
  hint,
  direction,
  handleId,
  color,
  isConnectable,
  ariaLabel,
  title,
  multiple = false,
  inactive = false,
}: {
  nodeId: string;
  label: string;
  hint?: string;
  direction: "input" | "output";
  handleId: string;
  color: string;
  isConnectable?: boolean;
  ariaLabel: string;
  title?: string;
  /** Sequence (or plug collection) shape: the mark draws a second ring. */
  multiple?: boolean;
  /** Nothing to pass yet: the label and mark read as inert. */
  inactive?: boolean;
}) {
  const input = direction === "input";
  const docked = useHandleIsDocked(nodeId, handleId);
  return (
    <div
      data-docked-port={docked ? "true" : undefined}
      {...stylex.props(nodeChrome.tabRow, input ? null : nodeChrome.tabRowOut)}
    >
      <div
        {...stylex.props(
          nodeChrome.tab,
          input ? nodeChrome.tabIn : nodeChrome.tabOut,
          docked ? nodeChrome.tabDocked : null,
          inactive ? nodeChrome.tabInactive : null,
        )}
        title={title}
      >
        <span {...stylex.props(nodeChrome.tabLabel)}>{label}</span>
        {hint ? (
          <span {...stylex.props(nodeChrome.tabShape)}>{hint}</span>
        ) : null}
      </div>
      <CanvasPortBall
        nodeId={nodeId}
        handleId={handleId}
        side={direction}
        color={color}
        sequence={multiple}
        isConnectable={isConnectable !== false}
        idle={inactive}
        docked={docked}
        ariaLabel={ariaLabel}
        title={title}
      />
    </div>
  );
}

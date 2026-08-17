"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Popover } from "@base-ui/react/popover";
import { Handle, Position } from "@xyflow/react";
import { CircleHelp, MoreHorizontal, Trash2 } from "lucide-react";

import { overlay } from "@/lib/stylex/overlay.stylex";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { useHandleIsDocked } from "../edges/useDockedConnection";
import { dockedHandleStyle, handleStyle } from "../handle-style";
import {
  GRID_CELL_SIZE_DEFAULT,
  PORT_RAIL_ROW_HEIGHT_CELLS,
  lengthFromSpan,
} from "../grid-layout";
import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";

/**
 * Shared card chrome for operator nodes and Artifact Viewers: one lattice cell
 * of header, paired port rails, and selection-gated about/overflow actions.
 */
export const nodeChrome = stylex.create({
  header: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "4px",
    minHeight: "34px",
    padding: "5px 10px 3px 12px",
  },
  title: {
    minWidth: 0,
    flex: 1,
    overflow: "hidden",
    marginLeft: "4px",
    color: tokens.colorText,
    fontSize: tokens.fontSizeMd,
    fontWeight: 500,
    letterSpacing: "-0.01em",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  headerButton: {
    width: "22px",
    height: "22px",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    borderWidth: 0,
    borderRadius: "9999px",
    backgroundColor: {
      default: tokens.colorSurface,
      ":hover": tokens.colorHover,
    },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorText },
    cursor: "pointer",
  },
  nodeMenu: {
    minWidth: "150px",
    display: "grid",
    padding: "4px",
    zIndex: 50,
  },
  nodeMenuItem: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "6px 8px",
    borderRadius: tokens.radiusSm,
    color: tokens.colorText,
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
    textAlign: "left",
  },
  nodeMenuItemDanger: {
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorDangerHover,
    },
    color: { default: tokens.colorDanger, ":hover": tokens.colorDanger },
  },
  helpPopup: {
    width: "280px",
    display: "grid",
    gap: "6px",
    padding: "11px 13px",
    zIndex: 50,
  },
  helpTitle: { fontSize: tokens.fontSizeSm, fontWeight: 600 },
  helpDescription: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.5,
  },
  helpFooter: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    paddingTop: "6px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  portRail: {
    display: "grid",
    paddingBlock: "2px",
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
    cursor: "crosshair",
  },
  tabRowOut: { justifyContent: "flex-end" },
  tab: {
    display: "flex",
    alignItems: "center",
    gap: "4px",
    maxWidth: "calc(100% - 12px)",
    height: "24px",
    paddingInline: "14px 12px",
    borderWidth: 0,
    backgroundColor: {
      default: tokens.colorSurfaceMuted,
      ":hover": tokens.colorHoverStrong,
    },
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
  },
  tabLabel: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  tabShape: { flexShrink: 0 },
  tabIn: { borderRadius: "0 9999px 9999px 0" },
  tabOut: {
    flexDirection: "row-reverse",
    paddingInline: "12px 14px",
    borderRadius: "9999px 0 0 9999px",
  },
  tabDocked: {
    visibility: "hidden",
    pointerEvents: "none",
  },
});

export function canvasNodeInteractionProps(
  props: ReturnType<typeof stylex.props>,
) {
  return {
    ...props,
    className: `nodrag nowheel${props.className ? ` ${props.className}` : ""}`,
  };
}

export interface CanvasNodeOverflowItem {
  id: string;
  label: string;
  icon?: React.ReactNode;
  disabled?: boolean;
  danger?: boolean;
  onClick?: () => void;
}

export function CanvasNodeHeader({
  title,
  selected,
  status,
  aboutLabel,
  aboutTitle,
  aboutDescription,
  aboutFooter,
  overflowItems,
  onRemove,
  children,
}: {
  title: string;
  selected: boolean;
  status?: React.ReactNode;
  aboutLabel: string;
  aboutTitle: string;
  aboutDescription: React.ReactNode;
  aboutFooter?: React.ReactNode;
  overflowItems?: readonly CanvasNodeOverflowItem[];
  onRemove?: () => void;
  children?: React.ReactNode;
}) {
  return (
    <header {...stylex.props(nodeChrome.header)}>
      <span {...stylex.props(nodeChrome.title)} title={title}>
        {title}
      </span>
      {status}
      {children}
      {selected ? (
        <>
          <Popover.Root>
            <Popover.Trigger
              type="button"
              aria-label={aboutLabel}
              title={aboutLabel}
              {...canvasNodeInteractionProps(stylex.props(nodeChrome.headerButton))}
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
                  <span {...stylex.props(nodeChrome.helpTitle)}>{aboutTitle}</span>
                  <span {...stylex.props(nodeChrome.helpDescription)}>
                    {aboutDescription}
                  </span>
                  {aboutFooter ? (
                    <span {...stylex.props(nodeChrome.helpFooter)}>
                      {aboutFooter}
                    </span>
                  ) : null}
                </Popover.Popup>
              </Popover.Positioner>
            </Popover.Portal>
          </Popover.Root>
          {overflowItems?.length || onRemove ? (
            <Popover.Root>
              <Popover.Trigger
                type="button"
                aria-label={`Actions for ${title}`}
                title={`Actions for ${title}`}
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
                    {overflowItems?.length
                      ? overflowItems.map((item) => (
                          <button
                            key={item.id}
                            type="button"
                            disabled={item.disabled}
                            {...stylex.props(
                              overlay.item,
                              nodeChrome.nodeMenuItem,
                              item.danger
                                ? nodeChrome.nodeMenuItemDanger
                                : null,
                            )}
                            onClick={item.onClick}
                          >
                            {item.icon}
                            {item.label}
                          </button>
                        ))
                      : null}
                    {onRemove ? (
                      <button
                        type="button"
                        {...stylex.props(
                          overlay.item,
                          nodeChrome.nodeMenuItem,
                          nodeChrome.nodeMenuItemDanger,
                        )}
                        onClick={onRemove}
                      >
                        <Trash2 size={13} />
                        Delete node
                      </button>
                    ) : null}
                  </Popover.Popup>
                </Popover.Positioner>
              </Popover.Portal>
            </Popover.Root>
          ) : null}
        </>
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
          <div {...stylex.props(nodeChrome.portRailSlot, nodeChrome.portRailSlotOut)}>
            {row.output}
          </div>
        </div>
      ))}
    </div>
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
        )}
        title={title}
      >
        <span {...stylex.props(nodeChrome.tabLabel)}>{label}</span>
        {hint ? (
          <span {...stylex.props(nodeChrome.tabShape)}>{hint}</span>
        ) : null}
      </div>
      <Handle
        id={handleId}
        type={input ? "target" : "source"}
        position={input ? Position.Left : Position.Right}
        isConnectable={isConnectable}
        aria-hidden={docked}
        aria-label={ariaLabel}
        title={title}
        style={
          docked ? dockedHandleStyle("50%") : handleStyle("50%", color)
        }
      />
    </div>
  );
}

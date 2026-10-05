"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Menu } from "@base-ui/react/menu";
import { MoreHorizontal } from "lucide-react";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { overlay } from "@/lib/stylex/overlay.stylex";
import {
  useRegisterNodeMenu,
  type NodeMenuInfo,
  type NodeMenuItem,
} from "./node-menu-registry";

export type { NodeMenuInfo, NodeMenuItem };

const s = stylex.create({
  // Quiet until asked: subtle ink at rest, full ink and a wash on hover or
  // while its menu is open.
  trigger: {
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    width: "22px",
    height: "22px",
    padding: 0,
    borderWidth: 0,
    borderRadius: "9999px",
    color: { default: tokens.colorSubtle, ":hover": tokens.colorText },
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    cursor: "pointer",
    transitionProperty: "color, background-color",
    transitionDuration: "120ms",
    ":focus-visible": { outline: `2px solid ${tokens.colorAccent}` },
  },
  triggerOpen: {
    color: tokens.colorText,
    backgroundColor: tokens.colorHover,
  },
  popup: {
    display: "grid",
    gap: "1px",
    minWidth: "200px",
    maxWidth: "min(300px, calc(100vw - 24px))",
    padding: "4px",
    zIndex: 60,
  },
  // What the thing is, heading the menu: name, then the facts about it.
  info: {
    display: "grid",
    gap: "2px",
    padding: "6px 8px 8px",
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
    color: tokens.colorMuted,
    overflowWrap: "anywhere",
  },
  infoTitle: {
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 560,
  },
  infoMono: {
    marginTop: "2px",
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
    userSelect: "text",
  },
  infoFooter: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    marginTop: "4px",
  },
  separator: {
    height: "1px",
    margin: "3px 4px",
    backgroundColor: tokens.colorDivider,
  },
  item: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "6px 8px",
    borderRadius: tokens.radiusSm,
    color: { default: tokens.colorText, ":disabled": tokens.colorTextDisabled },
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
    textAlign: "left",
  },
  itemDanger: {
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorDangerHover,
    },
    color: {
      default: tokens.colorDanger,
      ":disabled": tokens.colorTextDisabled,
    },
  },
});

/**
 * The one "⋯" a canvas card carries: a menu that opens on what the thing is,
 * then what can be done with it. Info and actions share it, so a card never
 * shows a second button that could be mistaken for a port.
 */
export function NodeMenu({
  label,
  title = "Info and actions",
  info,
  items,
  onOpenChange,
  align = "start",
}: {
  /** Accessible name of the trigger. */
  label: string;
  title?: string;
  info: NodeMenuInfo;
  items: readonly NodeMenuItem[];
  onOpenChange?: (open: boolean) => void;
  align?: "start" | "end";
}) {
  const [open, setOpen] = React.useState(false);
  const popup = stylex.props(overlay.popup, s.popup);
  // The canvas right-click menu opens on the same facts and actions.
  useRegisterNodeMenu(info, items);
  return (
    <Menu.Root
      onOpenChange={(next) => {
        setOpen(next);
        onOpenChange?.(next);
      }}
    >
      <Menu.Trigger
        {...stylex.props(s.trigger, open ? s.triggerOpen : null)}
        aria-label={label}
        title={title}
      >
        <MoreHorizontal size={14} />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner side="bottom" align={align} sideOffset={6}>
          <Menu.Popup
            {...popup}
            className={`nodrag nopan nowheel ${popup.className ?? ""}`}
          >
            <Menu.Group>
              <Menu.GroupLabel {...stylex.props(s.info)}>
                <span {...stylex.props(s.infoTitle)}>{info.title}</span>
                {(info.lines ?? []).map((line, index) => (
                  <span key={index}>{line}</span>
                ))}
                {info.mono ? (
                  <span {...stylex.props(s.infoMono)}>{info.mono}</span>
                ) : null}
                {info.footer ? (
                  <span {...stylex.props(s.infoFooter)}>{info.footer}</span>
                ) : null}
              </Menu.GroupLabel>
              {items.length ? (
                <Menu.Separator {...stylex.props(s.separator)} />
              ) : null}
              {items.map((item) => (
                <Menu.Item
                  key={item.id}
                  disabled={item.disabled}
                  onClick={item.onClick}
                  {...stylex.props(
                    overlay.item,
                    s.item,
                    item.danger ? s.itemDanger : null,
                  )}
                >
                  {item.icon}
                  {item.label}
                </Menu.Item>
              ))}
            </Menu.Group>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

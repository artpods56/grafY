"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { MoreHorizontal } from "lucide-react";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { IconButton } from "@/components/ui/button";
import {
  Menu,
  MenuContent,
  MenuGroup,
  MenuGroupLabel,
  MenuItem,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/menu";
import {
  useRegisterNodeMenu,
  type NodeMenuInfo,
  type NodeMenuItem,
} from "./node-menu-registry";

export type { NodeMenuInfo, NodeMenuItem };

const s = stylex.create({
  triggerOpen: {
    color: tokens.colorText,
    backgroundColor: tokens.colorHover,
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
  // The canvas right-click menu opens on the same facts and actions.
  useRegisterNodeMenu(info, items);
  return (
    <Menu
      onOpenChange={(next) => {
        setOpen(next);
        onOpenChange?.(next);
      }}
    >
      <MenuTrigger
        render={
          <IconButton
            label={label}
            title={title}
            size="xs"
            shape="round"
            xstyle={open ? s.triggerOpen : null}
          />
        }
      >
        <MoreHorizontal size={14} />
      </MenuTrigger>
      <MenuContent side="bottom" align={align} sideOffset={6}>
        <MenuGroup>
          <MenuGroupLabel xstyle={s.info}>
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
          </MenuGroupLabel>
          {items.length ? <MenuSeparator /> : null}
          {items.map((item) => (
            <MenuItem
              key={item.id}
              disabled={item.disabled}
              onClick={item.onClick}
              danger={item.danger}
              icon={item.icon}
            >
              {item.label}
            </MenuItem>
          ))}
        </MenuGroup>
      </MenuContent>
    </Menu>
  );
}

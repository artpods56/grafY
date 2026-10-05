"use client";

import * as stylex from "@stylexjs/stylex";
import { Menu } from "@base-ui/react/menu";
import { type LucideIcon } from "lucide-react";

import { panelStyles as s } from "../panel-styles";

export function MenuItem({
  icon: Icon,
  label,
  disabled,
  onSelect,
}: {
  icon: LucideIcon;
  label: string;
  disabled?: boolean;
  onSelect: () => void;
}) {
  return (
    <Menu.Item
      disabled={disabled}
      onClick={onSelect}
      {...stylex.props(s.menuItem)}
    >
      <Icon size={12} aria-hidden="true" />
      {label}
    </Menu.Item>
  );
}

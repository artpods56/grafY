"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Menu as BaseMenu } from "@base-ui/react/menu";
import { Check, ChevronRight } from "lucide-react";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { overlay } from "@/lib/stylex/overlay.stylex";

function joinClassNames(...names: Array<string | undefined>) {
  return names.filter(Boolean).join(" ") || undefined;
}

/** The menu's state; wraps a MenuTrigger and a MenuContent. */
export const Menu = BaseMenu.Root;
export const MenuTrigger = BaseMenu.Trigger;
export const MenuGroup = BaseMenu.Group;
export const MenuRadioGroup = BaseMenu.RadioGroup;
export const MenuSubmenu = BaseMenu.SubmenuRoot;

type PositionerProps = React.ComponentPropsWithoutRef<
  typeof BaseMenu.Positioner
>;

export type MenuContentProps = Omit<
  React.ComponentPropsWithoutRef<typeof BaseMenu.Popup>,
  "className" | "style"
> & {
  /** Side of the anchor the popup sits on. */
  side?: PositionerProps["side"];
  /** How the popup aligns to the anchor along its edge. */
  align?: PositionerProps["align"];
  /** Gap between the anchor and the popup in pixels. */
  sideOffset?: number;
  /** Shift along the anchor's edge in pixels. */
  alignOffset?: number;
  /** Places the popup at an element or a point instead of the trigger. */
  anchor?: PositionerProps["anchor"];
  /** Keep this many pixels of clearance from the viewport edges. */
  collisionPadding?: number;
  /** Plain class names added after the StyleX ones, e.g. React Flow's "nodrag nopan". */
  className?: string;
  /** Caller overrides made with stylex.create, applied last so they win. */
  xstyle?: stylex.StyleXStyles;
  /** Overrides for the positioner, applied last. A menu inside a dialog uses this to sit above it. */
  positionerXstyle?: stylex.StyleXStyles;
};

/** The floating menu: portal, positioner and popup, in the app's overlay chrome. */
export function MenuContent({
  side = "bottom",
  align = "start",
  sideOffset = 6,
  alignOffset = 0,
  anchor,
  collisionPadding = 8,
  className,
  xstyle,
  positionerXstyle,
  children,
  ...props
}: MenuContentProps) {
  const styled = stylex.props(overlay.popup, menu.panel, xstyle);
  return (
    <BaseMenu.Portal>
      <BaseMenu.Positioner
        side={side}
        align={align}
        sideOffset={sideOffset}
        alignOffset={alignOffset}
        anchor={anchor}
        collisionPadding={collisionPadding}
        {...stylex.props(menu.positioner, positionerXstyle)}
      >
        <BaseMenu.Popup
          {...props}
          // A menu over the canvas must not start a drag, a pan or a zoom.
          className={joinClassNames(
            "nodrag nopan nowheel",
            styled.className,
            className,
          )}
          style={styled.style}
        >
          {children}
        </BaseMenu.Popup>
      </BaseMenu.Positioner>
    </BaseMenu.Portal>
  );
}

export type MenuItemProps = Omit<
  React.ComponentPropsWithoutRef<typeof BaseMenu.Item>,
  "className" | "style"
> & {
  /** A leading icon, e.g. <Settings2 size={13} />. */
  icon?: React.ReactNode;
  /** Trailing quiet text, e.g. a shortcut or a count. */
  hint?: React.ReactNode;
  /** A destructive action: red text and a red wash when highlighted. */
  danger?: boolean;
  /** The current choice, e.g. the open conversation: a filled row. */
  active?: boolean;
  className?: string;
  xstyle?: stylex.StyleXStyles;
};

/** One action in a menu, with optional icon and trailing hint. */
export const MenuItem = React.forwardRef<HTMLElement, MenuItemProps>(
  function MenuItem(
    {
      icon,
      hint,
      danger = false,
      active = false,
      className,
      xstyle,
      children,
      ...props
    },
    ref,
  ) {
    const styled = stylex.props(
      menu.item,
      danger ? menu.danger : null,
      active ? menu.active : null,
      xstyle,
    );
    return (
      <BaseMenu.Item
        ref={ref}
        {...props}
        className={joinClassNames(styled.className, className)}
        style={styled.style}
      >
        {icon != null ? (
          <span aria-hidden="true" {...stylex.props(menu.icon)}>
            {icon}
          </span>
        ) : null}
        <span {...stylex.props(menu.label)}>{children}</span>
        {hint != null ? <span {...stylex.props(menu.hint)}>{hint}</span> : null}
      </BaseMenu.Item>
    );
  },
);

export type MenuCheckboxItemProps = Omit<
  React.ComponentPropsWithoutRef<typeof BaseMenu.CheckboxItem>,
  "className" | "style"
> & {
  className?: string;
  xstyle?: stylex.StyleXStyles;
};

/** A menu row that toggles, with a check while on. */
export const MenuCheckboxItem = React.forwardRef<
  HTMLElement,
  MenuCheckboxItemProps
>(function MenuCheckboxItem({ className, xstyle, children, ...props }, ref) {
  const styled = stylex.props(menu.item, xstyle);
  return (
    <BaseMenu.CheckboxItem
      ref={ref}
      {...props}
      className={joinClassNames(styled.className, className)}
      style={styled.style}
    >
      <span aria-hidden="true" {...stylex.props(menu.icon)}>
        <BaseMenu.CheckboxItemIndicator>
          <Check size={13} />
        </BaseMenu.CheckboxItemIndicator>
      </span>
      <span {...stylex.props(menu.label)}>{children}</span>
    </BaseMenu.CheckboxItem>
  );
});

export type MenuRadioItemProps = Omit<
  React.ComponentPropsWithoutRef<typeof BaseMenu.RadioItem>,
  "className" | "style"
> & {
  /** A second, quiet line under the label, e.g. when the conversation was updated. */
  detail?: React.ReactNode;
  className?: string;
  xstyle?: stylex.StyleXStyles;
};

/** One choice in a MenuRadioGroup, with a check on the chosen one. */
export const MenuRadioItem = React.forwardRef<HTMLElement, MenuRadioItemProps>(
  function MenuRadioItem(
    { detail, className, xstyle, children, ...props },
    ref,
  ) {
    const styled = stylex.props(menu.item, xstyle);
    return (
      <BaseMenu.RadioItem
        ref={ref}
        {...props}
        className={joinClassNames(styled.className, className)}
        style={styled.style}
      >
        <span aria-hidden="true" {...stylex.props(menu.icon)}>
          <BaseMenu.RadioItemIndicator>
            <Check size={13} />
          </BaseMenu.RadioItemIndicator>
        </span>
        {detail != null ? (
          <span {...stylex.props(menu.label, menu.stack)}>
            <span {...stylex.props(menu.line)}>{children}</span>
            <span {...stylex.props(menu.detail)}>{detail}</span>
          </span>
        ) : (
          <span {...stylex.props(menu.label)}>{children}</span>
        )}
      </BaseMenu.RadioItem>
    );
  },
);

export type MenuSubmenuTriggerProps = Omit<
  React.ComponentPropsWithoutRef<typeof BaseMenu.SubmenuTrigger>,
  "className" | "style"
> & {
  /** A leading icon, e.g. <Plus size={13} />. */
  icon?: React.ReactNode;
  className?: string;
  xstyle?: stylex.StyleXStyles;
};

/** The row that opens a nested menu, with a chevron at its end. */
export const MenuSubmenuTrigger = React.forwardRef<
  HTMLElement,
  MenuSubmenuTriggerProps
>(function MenuSubmenuTrigger(
  { icon, className, xstyle, children, ...props },
  ref,
) {
  const styled = stylex.props(menu.item, xstyle);
  return (
    <BaseMenu.SubmenuTrigger
      ref={ref}
      {...props}
      className={joinClassNames(styled.className, className)}
      style={styled.style}
    >
      {icon != null ? (
        <span aria-hidden="true" {...stylex.props(menu.icon)}>
          {icon}
        </span>
      ) : null}
      <span {...stylex.props(menu.label)}>{children}</span>
      <ChevronRight
        size={13}
        aria-hidden="true"
        {...stylex.props(menu.chevron)}
      />
    </BaseMenu.SubmenuTrigger>
  );
});

/** A hairline between groups of rows. */
export function MenuSeparator() {
  return <BaseMenu.Separator {...stylex.props(menu.separator)} />;
}

type MenuGroupLabelProps = {
  children: React.ReactNode;
  className?: string;
  /** Caller overrides made with stylex.create, applied last. */
  xstyle?: stylex.StyleXStyles;
};

/** The accessible label of a MenuGroup. Unstyled, so a menu can head itself with its own facts. */
export function MenuGroupLabel({
  children,
  className,
  xstyle,
}: MenuGroupLabelProps) {
  const styled = stylex.props(xstyle);
  return (
    <BaseMenu.GroupLabel
      className={joinClassNames(styled.className, className)}
      style={styled.style}
    >
      {children}
    </BaseMenu.GroupLabel>
  );
}

/** A small uppercase heading for a MenuGroup. */
export function MenuLabel({ children }: { children: React.ReactNode }) {
  return <MenuGroupLabel xstyle={menu.groupLabel}>{children}</MenuGroupLabel>;
}

const menu = stylex.create({
  /** The app's popup layer, above the canvas and its floating chrome. */
  positioner: {
    zIndex: 80,
    outline: "none",
  },
  panel: {
    display: "grid",
    gap: "1px",
    minWidth: "200px",
    maxWidth: "min(300px, calc(100vw - 16px))",
    maxHeight: "min(420px, var(--available-height))",
    overflowY: "auto",
    padding: "4px",
    outline: "none",
    transformOrigin: "var(--transform-origin)",
    transitionProperty: "opacity, transform",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
    opacity: {
      default: 1,
      ":is([data-starting-style], [data-ending-style])": 0,
    },
    transform: {
      default: "none",
      ":is([data-starting-style], [data-ending-style])": "scale(0.97)",
    },
  },
  item: {
    minHeight: { default: "28px", "@media (pointer: coarse)": "40px" },
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "0 8px",
    borderRadius: tokens.radiusSm,
    color: {
      default: tokens.colorText,
      ":is([data-disabled])": tokens.colorTextDisabled,
    },
    cursor: { default: "default", ":is([data-disabled])": "not-allowed" },
    fontSize: tokens.fontSizeSm,
    outline: "none",
    userSelect: "none",
    backgroundColor: {
      default: "transparent",
      ":is([data-highlighted])": tokens.colorHover,
      ":is([data-popup-open])": tokens.colorHover,
    },
  },
  danger: {
    color: {
      default: tokens.colorDanger,
      ":is([data-disabled])": tokens.colorTextDisabled,
    },
    backgroundColor: {
      default: "transparent",
      ":is([data-highlighted])": tokens.colorDangerHover,
    },
  },
  active: {
    backgroundColor: {
      default: tokens.colorAccentSoft,
      ":is([data-highlighted])": tokens.colorAccentSoft,
    },
  },
  icon: {
    width: "14px",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    color: "inherit",
    opacity: 0.8,
  },
  label: {
    minWidth: 0,
    flex: 1,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  /** A label with a second line. The single-line ellipsis stays on each line. */
  stack: {
    display: "grid",
    gap: "1px",
    whiteSpace: "normal",
    textOverflow: "clip",
  },
  line: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  detail: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: "10px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  hint: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  chevron: {
    flexShrink: 0,
    color: tokens.colorSubtle,
  },
  separator: {
    height: "1px",
    margin: "4px 2px",
    backgroundColor: tokens.colorDivider,
  },
  groupLabel: {
    padding: "5px 8px 4px",
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 700,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
});

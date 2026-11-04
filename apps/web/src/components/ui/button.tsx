"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Button as BaseButton } from "@base-ui/react/button";
import Link from "next/link";
import { tokens } from "@/lib/stylex/tokens.stylex";

export type ButtonVariant =
  "primary" | "secondary" | "soft" | "ghost" | "danger" | "plain" | "dashed";
export type ButtonSize = "xs" | "sm" | "md" | "lg" | "text";
export type IconButtonVariant = "ghost" | "soft" | "primary" | "danger";
export type IconButtonSize = "xs" | "sm" | "md" | "lg";

type SharedProps = Omit<
  React.ComponentPropsWithoutRef<typeof BaseButton>,
  "className" | "style"
> & {
  /** Plain class names added after the StyleX ones, e.g. React Flow's "nodrag nopan". */
  className?: string;
  /** Caller overrides made with stylex.create, applied last so they win. */
  xstyle?: stylex.StyleXStyles;
};

export type ButtonProps = SharedProps & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** When given, the button is a toggle: sets `aria-pressed` and the pressed look. */
  pressed?: boolean;
  /**
   * A colour chip before the label: an annotation's colour, a layer's fill.
   * No kit part took a per-option colour, so a swatch picker had to paint its
   * own chip inside the label.
   */
  swatch?: string;
};

export type IconButtonProps = Omit<SharedProps, "children" | "aria-label"> & {
  /** Required: becomes aria-label, and the title unless `title` is given. */
  label: string;
  /**
   * The icon, e.g. <Settings2 size={14} />. Optional only so an IconButton can
   * be the `render` target of a Base UI trigger, which passes its own children in.
   */
  children?: React.ReactNode;
  variant?: IconButtonVariant;
  size?: IconButtonSize;
  shape?: "square" | "round";
  /** When given, the button is a toggle: sets aria-pressed and the pressed look. */
  pressed?: boolean;
};

const button = stylex.create({
  base: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "6px",
    flexShrink: 0,
    boxSizing: "border-box",
    margin: 0,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: "transparent",
    borderRadius: tokens.radiusMd,
    fontFamily: "inherit",
    fontWeight: 500,
    lineHeight: 1,
    whiteSpace: "nowrap",
    textDecoration: "none",
    userSelect: "none",
    cursor: {
      default: "pointer",
      ":disabled": "default",
    },
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorAccentBorder}`,
    },
    outlineOffset: "1px",
    transitionProperty: "background-color, border-color, color",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
  },
  xs: {
    height: "22px",
    paddingInline: "8px",
    fontSize: tokens.fontSizeXs,
    borderRadius: tokens.radiusSm,
  },
  sm: {
    height: "28px",
    paddingInline: "10px",
    fontSize: tokens.fontSizeSm,
  },
  md: {
    height: "32px",
    paddingInline: "12px",
    fontSize: tokens.fontSizeSm,
  },
  lg: {
    height: { default: "36px", "@media (max-width: 620px)": "44px" },
    paddingInline: "14px",
    fontSize: tokens.fontSizeMd,
  },
  /**
   * For a control inside something that already has a text baseline: a table
   * cell, a list row. Its box comes from the surrounding type, so a row of these
   * does not change the height of the line it sits on.
   */
  text: {
    height: "auto",
    paddingInline: "3px",
    paddingBlock: "1px",
    fontSize: "inherit",
    borderRadius: tokens.radiusSm,
  },
  primary: {
    backgroundColor: {
      default: tokens.colorAccent,
      ":hover:not(:disabled)": tokens.colorAccentHover,
      ":disabled": tokens.colorAccentDisabled,
    },
    color: tokens.colorOnAccent,
    fontWeight: 600,
  },
  secondary: {
    backgroundColor: {
      default: tokens.colorChrome,
      ":hover:not(:disabled)": tokens.colorSurfaceRaised,
    },
    borderColor: {
      default: tokens.colorBorder,
      ":hover:not(:disabled)": tokens.colorBorderStrong,
    },
    color: {
      default: tokens.colorText,
      ":disabled": tokens.colorTextDisabled,
    },
  },
  soft: {
    backgroundColor: {
      default: tokens.colorSurfaceRaised,
      ":hover:not(:disabled)": tokens.colorHoverStrong,
    },
    color: {
      default: tokens.colorText,
      ":disabled": tokens.colorTextDisabled,
    },
  },
  ghost: {
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorHover,
    },
    color: {
      default: tokens.colorText,
      ":disabled": tokens.colorTextDisabled,
    },
  },
  danger: {
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorDangerHover,
    },
    color: {
      default: tokens.colorDanger,
      ":disabled": tokens.colorTextDisabled,
    },
  },
  /**
   * A word that acts, on the line it describes: a truncated table cell, a row's
   * "Show more". It borrows the surrounding type and only says it is clickable
   * when the pointer is on it or a key has focus.
   */
  plain: {
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorHover,
    },
    borderColor: "transparent",
    color: {
      default: tokens.colorText,
      ":disabled": tokens.colorTextDisabled,
    },
    textDecoration: {
      default: "none",
      ":hover:not(:disabled)": "underline",
      ":focus-visible": "underline",
    },
    fontWeight: "inherit",
  },
  /**
   * The affordance for appending a thing to a list: dashed because it holds
   * nothing yet, quiet because the row it adds is the point.
   */
  dashed: {
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorHover,
    },
    borderStyle: "dashed",
    borderColor: {
      default: tokens.colorBorder,
      ":hover:not(:disabled)": tokens.colorBorderStrong,
      ":disabled": tokens.colorDivider,
    },
    color: {
      default: tokens.colorSubtle,
      ":hover:not(:disabled)": tokens.colorText,
      ":disabled": tokens.colorTextDisabled,
    },
    fontWeight: 500,
  },
  /**
   * A toggle's own state, so a text button does not have to write `aria-pressed`
   * and invent a colour for it. Applied over the variant, under `xstyle`.
   */
  pressed: {
    backgroundColor: {
      default: tokens.colorHover,
      ":hover:not(:disabled)": tokens.colorHoverStrong,
    },
    color: tokens.colorText,
  },
  swatch: {
    display: "block",
    width: "8px",
    height: "8px",
    flexShrink: 0,
    borderRadius: "2px",
    // A colour the person picked can be anything, so it keeps a hairline to stay
    // visible against a surface of the same colour.
    boxShadow: `inset 0 0 0 1px ${tokens.colorBorder}`,
  },
});

const icon = stylex.create({
  base: {
    display: "inline-grid",
    placeItems: "center",
    flexShrink: 0,
    boxSizing: "border-box",
    margin: 0,
    padding: 0,
    borderWidth: 0,
    cursor: {
      default: "pointer",
      ":disabled": "default",
    },
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorAccentBorder}`,
    },
    outlineOffset: "1px",
    transitionProperty: "background-color, color",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
  },
  xs: {
    width: "22px",
    height: "22px",
  },
  sm: {
    width: "26px",
    height: "26px",
  },
  md: {
    width: "28px",
    height: "28px",
  },
  lg: {
    width: "32px",
    height: "32px",
  },
  square: {
    borderRadius: tokens.radiusMd,
  },
  round: {
    borderRadius: "9999px",
  },
  ghost: {
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorHover,
    },
    color: {
      default: tokens.colorSubtle,
      ":hover:not(:disabled)": tokens.colorText,
      ":disabled": tokens.colorTextDisabled,
    },
  },
  soft: {
    backgroundColor: {
      default: tokens.colorSurfaceRaised,
      ":hover:not(:disabled)": tokens.colorHoverStrong,
    },
    color: {
      default: tokens.colorText,
      ":disabled": tokens.colorTextDisabled,
    },
  },
  primary: {
    backgroundColor: {
      default: tokens.colorAccent,
      ":hover:not(:disabled)": tokens.colorAccentHover,
      ":disabled": tokens.colorAccentDisabled,
    },
    color: tokens.colorOnAccent,
  },
  danger: {
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorDangerHover,
    },
    color: {
      default: tokens.colorSubtle,
      ":hover:not(:disabled)": tokens.colorDanger,
      ":disabled": tokens.colorTextDisabled,
    },
  },
  pressed: {
    backgroundColor: {
      default: tokens.colorHover,
      ":hover:not(:disabled)": tokens.colorHoverStrong,
    },
    color: tokens.colorText,
  },
});

function joinClassNames(...names: Array<string | undefined>) {
  return names.filter(Boolean).join(" ") || undefined;
}

/** Text button for toolbars, dialogs, and forms, in seven variants and five sizes. */
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      variant = "secondary",
      size = "md",
      pressed,
      swatch,
      className,
      xstyle,
      children,
      ...props
    },
    ref,
  ) {
    const styled = stylex.props(
      button.base,
      button[variant],
      button[size],
      pressed ? button.pressed : null,
      xstyle,
    );
    return (
      <BaseButton
        ref={ref}
        {...props}
        aria-pressed={pressed}
        className={joinClassNames(styled.className, className)}
        style={styled.style}
      >
        {swatch != null ? (
          <span
            aria-hidden="true"
            {...stylex.props(button.swatch)}
            style={{ backgroundColor: swatch }}
          />
        ) : null}
        {children}
      </BaseButton>
    );
  },
);

export type ButtonLinkProps = Omit<
  React.ComponentPropsWithoutRef<typeof Link>,
  "className" | "style"
> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Plain class names added after the StyleX ones. */
  className?: string;
  /** Caller overrides made with stylex.create, applied last. */
  xstyle?: stylex.StyleXStyles;
};

/** A link drawn as a Button: navigation that reads as an action, and stays a link for assistive tech. */
export const ButtonLink = React.forwardRef<HTMLAnchorElement, ButtonLinkProps>(
  function ButtonLink(
    { variant = "secondary", size = "md", className, xstyle, ...props },
    ref,
  ) {
    const styled = stylex.props(
      button.base,
      button[variant],
      button[size],
      xstyle,
    );
    return (
      <Link
        ref={ref}
        {...props}
        className={joinClassNames(styled.className, className)}
        style={styled.style}
      />
    );
  },
);

/** Icon-only button, square or round, that labels itself through `label` and can act as a toggle. */
export const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(
  function IconButton(
    {
      label,
      title,
      variant = "ghost",
      size = "sm",
      shape = "square",
      pressed,
      className,
      xstyle,
      children,
      ...props
    },
    ref,
  ) {
    const styled = stylex.props(
      icon.base,
      icon[variant],
      icon[size],
      icon[shape],
      pressed ? icon.pressed : null,
      xstyle,
    );
    return (
      <BaseButton
        ref={ref}
        {...props}
        aria-label={label}
        title={title ?? label}
        aria-pressed={pressed}
        className={joinClassNames(styled.className, className)}
        style={styled.style}
      >
        {children}
      </BaseButton>
    );
  },
);

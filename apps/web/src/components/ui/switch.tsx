"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Switch as BaseSwitch } from "@base-ui/react/switch";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { phoneTouch } from "./touch-target";

function joinClassNames(...names: Array<string | undefined>) {
  return names.filter(Boolean).join(" ") || undefined;
}

/**
 * `dense` is the canvas-card step. A layer inspector holds its controls in a 25px
 * row with a 9px label, and the desktop steps put fewer controls per screenful
 * inside the card's own scroll area.
 */
export type SwitchSize = "dense" | "sm" | "md";

export type SwitchProps = {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  /**
   * The visible name, set after the track. Clicking it toggles the switch, so a
   * row that is only "label + switch" needs no other markup.
   */
  label?: React.ReactNode;
  disabled?: boolean;
  size?: SwitchSize;
  /** Identifies the control when a form submits it. */
  name?: string;
  /** Names the control when `label` is an icon or lives elsewhere. */
  "aria-label"?: string;
  /**
   * A native tooltip, for the case where the row's own text is truncated and the
   * tooltip is what expands it.
   */
  title?: string;
  /**
   * Pointer intent on the control itself — on a canvas, this is where a call site
   * stops the event so the card does not start dragging.
   */
  onClick?: React.MouseEventHandler<HTMLElement>;
  /**
   * For a switch in a page rather than a canvas card: on the shell's phone
   * breakpoint the row grows to 44px and the track to the pill a thumb aims at.
   * Say it here instead of copying the media query, and never on a control inside
   * a card, which keeps its pixel size at every viewport.
   */
  phoneTouch?: boolean;
  /**
   * Plain class names added after the StyleX ones. On a canvas card this is how
   * the row keeps React Flow's `nodrag nopan`: React Flow walks up from the
   * event target, so the root carries them.
   */
  className?: string;
  /** Caller overrides made with stylex.create, applied last so they win. */
  xstyle?: stylex.StyleXStyles;
};

const toggle = stylex.create({
  root: {
    display: "inline-flex",
    alignItems: "center",
    gap: "7px",
    minWidth: 0,
    margin: 0,
    cursor: "pointer",
    color: tokens.colorText,
    userSelect: "none",
  },
  /** The canvas rows that take the dense control are 9px type. */
  dense: {
    gap: "5px",
    fontSize: "9px",
    lineHeight: 1.3,
  },
  sm: {
    gap: "6px",
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.35,
  },
  md: {
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.4,
  },
  disabled: {
    cursor: "not-allowed",
    color: tokens.colorTextDisabled,
  },
  label: {
    minWidth: 0,
    overflowWrap: "anywhere",
  },
  track: {
    position: "relative",
    flexShrink: 0,
    boxSizing: "border-box",
    borderWidth: 1,
    borderStyle: "solid",
    borderRadius: "9999px",
    transitionProperty: "background-color, border-color",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
  },
  denseTrack: {
    width: "22px",
    height: "13px",
  },
  smTrack: {
    width: "26px",
    height: "15px",
  },
  mdTrack: {
    width: "31px",
    height: "18px",
  },
  off: {
    backgroundColor: tokens.colorSurfaceSunken,
    borderColor: tokens.colorBorder,
  },
  on: {
    backgroundColor: tokens.colorAccent,
    borderColor: tokens.colorAccent,
  },
  trackDisabled: {
    backgroundColor: tokens.colorSurfaceMuted,
    borderColor: tokens.colorDivider,
  },
  thumb: {
    position: "absolute",
    top: "50%",
    insetInlineStart: "2px",
    display: "block",
    boxSizing: "border-box",
    borderRadius: "9999px",
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNode,
    transitionProperty: "transform",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
  },
  denseThumb: {
    width: "9px",
    height: "9px",
    marginTop: "-4.5px",
  },
  smThumb: {
    width: "11px",
    height: "11px",
    marginTop: "-5.5px",
  },
  mdThumb: {
    width: "14px",
    height: "14px",
    marginTop: "-7px",
  },
  thumbDisabled: {
    backgroundColor: tokens.colorTextDisabled,
    boxShadow: "none",
  },
  /**
   * The phone step, shared by every desktop size: the track becomes the 44x26 pill
   * a thumb aims at and the thumb the 20px mark inside it. They set `min` sizes, so
   * they compose with the desktop `width` / `height` rather than replacing them —
   * see the one-property rule in `touch-target.ts`.
   */
  phoneTrack: {
    minWidth: { default: "unset", "@media (max-width: 620px)": "44px" },
    minHeight: { default: "unset", "@media (max-width: 620px)": "26px" },
  },
  phoneThumb: {
    minWidth: { default: "unset", "@media (max-width: 620px)": "20px" },
    minHeight: { default: "unset", "@media (max-width: 620px)": "20px" },
  },
  phoneShift: {
    transform: {
      default: "translateX(0px)",
      "@media (max-width: 620px)": "translateX(18px)",
    },
  },
  // Each step needs its own travel: track width - thumb width - 2 * inset.
  denseShift: {
    transform: "translateX(8px)",
  },
  smShift: {
    transform: "translateX(10px)",
  },
  mdShift: {
    transform: "translateX(13px)",
  },
});

const TRACK_BY_SIZE = {
  dense: toggle.denseTrack,
  sm: toggle.smTrack,
  md: toggle.mdTrack,
} as const;

const THUMB_BY_SIZE = {
  dense: toggle.denseThumb,
  sm: toggle.smThumb,
  md: toggle.mdThumb,
} as const;

const SHIFT_BY_SIZE = {
  dense: toggle.denseShift,
  sm: toggle.smShift,
  md: toggle.mdShift,
} as const;

/**
 * An on/off control with `role="switch"`, for a setting that takes effect the
 * moment it is flipped. Something inside a form that is applied on submit is a
 * `Checkbox`; one of several mutually exclusive modes is a `SegmentedControl`.
 *
 * The label belongs to the control because every reported call site — the grid
 * lab's toggle, a workflow port's "required" — had one, and the `<label>` wrapper
 * is what makes the text clickable.
 */
export function Switch({
  checked,
  onCheckedChange,
  label,
  disabled = false,
  size = "md",
  name,
  phoneTouch: phone = false,
  title,
  onClick,
  className,
  xstyle,
  ...props
}: SwitchProps) {
  // A `role="switch"` is not a labelable element, so the `<label>` around this
  // control hands its text to the hidden input and not to the switch. Pointing
  // `aria-labelledby` at the label is what makes
  // `getByRole("switch", { name: "Show grid lines" })` find the switch, and not
  // nothing at all.
  const id = React.useId();
  const labelId = label == null ? undefined : id;
  const on = checked && !disabled;
  const root = stylex.props(
    toggle.root,
    toggle[size],
    phone ? phoneTouch.on : null,
    disabled ? toggle.disabled : null,
    xstyle,
  );
  const track = stylex.props(
    toggle.track,
    TRACK_BY_SIZE[size],
    phone ? toggle.phoneTrack : null,
    disabled ? toggle.trackDisabled : checked ? toggle.on : toggle.off,
  );
  const thumb = stylex.props(
    toggle.thumb,
    THUMB_BY_SIZE[size],
    phone ? toggle.phoneThumb : null,
    on ? SHIFT_BY_SIZE[size] : null,
    on && phone ? toggle.phoneShift : null,
    disabled ? toggle.thumbDisabled : null,
  );

  return (
    <label
      className={joinClassNames(root.className, className)}
      style={root.style}
    >
      <BaseSwitch.Root
        title={title}
        onClick={onClick}
        checked={checked}
        // Base UI hands the change details as a second argument; the kit's own
        // contract is the value alone, so a call site cannot lean on them.
        onCheckedChange={(next) => onCheckedChange(next)}
        disabled={disabled}
        name={name}
        aria-label={props["aria-label"]}
        aria-labelledby={labelId}
        className={track.className}
        style={track.style}
      >
        <BaseSwitch.Thumb className={thumb.className} style={thumb.style} />
      </BaseSwitch.Root>
      {label != null ? (
        <span {...stylex.props(toggle.label)} id={labelId}>
          {label}
        </span>
      ) : null}
    </label>
  );
}

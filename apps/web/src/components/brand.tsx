import * as stylex from "@stylexjs/stylex";
import type { CSSProperties } from "react";

export const BRAND_NAME_DISPLAY = "grafY";
export const BRAND_LOGO_SRC = "/assets/grafy_logo.png";
export const BRAND_ICON_SRC = "/assets/grafy_icon.png";
/** Intrinsic pixel size of grafy_icon.png */
export const BRAND_ICON_INTRINSIC = { width: 231, height: 284 } as const;

/**
 * The brand mark's own box. The ink stays a black asset and `--grafy-brand-filter`
 * inverts it for a dark document; those `:root` / `prefers-color-scheme` rules stay
 * in `globals.css` because a component cannot declare a variable it only reads.
 */
const styles = stylex.create({
  mark: {
    display: "block",
    objectFit: "contain",
    filter: "var(--grafy-brand-filter)",
  },
  loader: {
    display: "inline-grid",
    placeItems: "center",
    width: "var(--grafy-brand-loader-size, 48px)",
    height: "var(--grafy-brand-loader-size, 48px)",
    flexShrink: 0,
  },
  loaderMark: {
    display: "block",
    objectFit: "fill",
    transformOrigin:
      "var(--grafy-brand-loader-hub-x, 49.8%) var(--grafy-brand-loader-hub-y, 50.7%)",
    filter: "var(--grafy-brand-filter)",
    // Longhands, not the `animation` shorthand: this StyleX version drops the
    // shorthand without a warning, and the flip is the whole point of the mark.
    animationName: {
      default: "grafy-brand-loader-flip",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    animationDuration: "1.7s",
    animationIterationCount: "infinite",
    willChange: "transform",
    userSelect: "none",
    WebkitUserDrag: "none",
  },
});

function joinClassNames(...names: Array<string | undefined>) {
  return names.filter(Boolean).join(" ");
}

type BrandMarkProps = {
  size?: number;
  className?: string;
  alt?: string;
};

export function BrandIcon({
  size = 28,
  className,
  alt = BRAND_NAME_DISPLAY,
}: BrandMarkProps) {
  const styled = stylex.props(styles.mark);
  return (
    // eslint-disable-next-line @next/next/no-img-element -- static brand asset in public/
    <img
      src={BRAND_ICON_SRC}
      width={size}
      height={size}
      alt={alt}
      className={joinClassNames(styled.className, className)}
      draggable={false}
    />
  );
}

export function BrandWordmark({
  height = 22,
  className,
  alt = BRAND_NAME_DISPLAY,
}: {
  height?: number;
  className?: string;
  alt?: string;
}) {
  const width = Math.round(height * (1157 / 392));
  const styled = stylex.props(styles.mark);
  return (
    // eslint-disable-next-line @next/next/no-img-element -- static brand asset in public/
    <img
      src={BRAND_LOGO_SRC}
      width={width}
      height={height}
      alt={alt}
      className={joinClassNames(styled.className, className)}
      draggable={false}
    />
  );
}

/**
 * Hub / junction node in grafy_icon.png, measured from ink geometry.
 * Rotation pivots here so a 180° flip reads as the graph reorienting in place.
 */
export const BRAND_ICON_HUB_ORIGIN = {
  x: "49.8%",
  y: "50.7%",
} as const;

type BrandLoaderProps = {
  /** Outer square footprint in CSS pixels. */
  size?: number;
  className?: string;
  label?: string;
  /** When true, omit status semantics (parent already announces). */
  decorative?: boolean;
};

export function BrandLoader({
  size = 48,
  className,
  label = "Loading",
  decorative = false,
}: BrandLoaderProps) {
  // Leave room for the mid-rotation sweep around the hub (~0.59 of icon height).
  const markHeight = Math.round(size * 0.82);
  const markWidth = Math.round(
    markHeight * (BRAND_ICON_INTRINSIC.width / BRAND_ICON_INTRINSIC.height),
  );
  const styled = stylex.props(styles.loader);
  // Per-instance geometry stays inline; `styles.loader` reads each one with the
  // fallback the retired global rule used to carry.
  const customProperties = {
    "--grafy-brand-loader-size": `${size}px`,
    "--grafy-brand-loader-hub-x": BRAND_ICON_HUB_ORIGIN.x,
    "--grafy-brand-loader-hub-y": BRAND_ICON_HUB_ORIGIN.y,
  } as CSSProperties;

  return (
    <span
      className={joinClassNames(styled.className, className)}
      style={{ ...styled.style, ...customProperties }}
      role={decorative ? undefined : "status"}
      aria-live={decorative ? undefined : "polite"}
      aria-label={decorative ? undefined : label}
      aria-hidden={decorative ? true : undefined}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset in public/ */}
      <img
        src={BRAND_ICON_SRC}
        width={markWidth}
        height={markHeight}
        alt=""
        aria-hidden="true"
        {...stylex.props(styles.loaderMark)}
        draggable={false}
      />
    </span>
  );
}

import type { CSSProperties } from "react";

export const BRAND_NAME = "grafy";
export const BRAND_NAME_DISPLAY = "grafY";
export const BRAND_LOGO_SRC = "/assets/grafy_logo.png";
export const BRAND_ICON_SRC = "/assets/grafy_icon.png";
/** Intrinsic pixel size of grafy_icon.png */
export const BRAND_ICON_INTRINSIC = { width: 231, height: 284 } as const;

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
  return (
    // eslint-disable-next-line @next/next/no-img-element -- static brand asset in public/
    <img
      src={BRAND_ICON_SRC}
      width={size}
      height={size}
      alt={alt}
      className={
        className ? `grafy-brand-icon ${className}` : "grafy-brand-icon"
      }
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
  return (
    // eslint-disable-next-line @next/next/no-img-element -- static brand asset in public/
    <img
      src={BRAND_LOGO_SRC}
      width={width}
      height={height}
      alt={alt}
      className={
        className ? `grafy-brand-wordmark ${className}` : "grafy-brand-wordmark"
      }
      draggable={false}
    />
  );
}

export function BrandLockup({
  iconSize = 28,
  wordmarkHeight = 20,
  className,
}: {
  iconSize?: number;
  wordmarkHeight?: number;
  className?: string;
}) {
  return (
    <span
      className={
        className ? `grafy-brand-lockup ${className}` : "grafy-brand-lockup"
      }
    >
      <BrandIcon size={iconSize} alt="" />
      <BrandWordmark height={wordmarkHeight} />
    </span>
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
  const style = {
    "--grafy-brand-loader-size": `${size}px`,
    "--grafy-brand-loader-hub-x": BRAND_ICON_HUB_ORIGIN.x,
    "--grafy-brand-loader-hub-y": BRAND_ICON_HUB_ORIGIN.y,
  } as CSSProperties;

  return (
    <span
      className={
        className ? `grafy-brand-loader ${className}` : "grafy-brand-loader"
      }
      style={style}
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
        className="grafy-brand-loader__mark"
        draggable={false}
      />
    </span>
  );
}

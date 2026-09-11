import { tokens } from "@/lib/stylex/tokens.stylex";

type CSSProperties = Record<string, string | number>;

/** The mark a handle draws: a disc, or a square when the input is pinned. */
export type PortMarkShape = "circle" | "square";

function markRadius(shape: PortMarkShape): string {
  return shape === "square" ? "2px" : "9999px";
}

/**
 * Catalog preview and canvas handles share this mark: a hollow 10px disc with
 * a 2px typed border. Sequence ports add a second concentric ring.
 */
export function portMarkStyle(color: string, multiple = false): CSSProperties {
  return multiple
    ? {
        borderColor: color,
        boxShadow: `0 0 0 2px ${tokens.colorSurface}, 0 0 0 3.5px ${color}`,
      }
    : { borderColor: color };
}

/**
 * React Flow hit target (30px) with the catalog port mark drawn in the center.
 * `multiple` is sequence shape (or an instance-plug collection), not variadic.
 */
export function handleStyle(
  top: number | string,
  color: string,
  multiple = false,
  shape: PortMarkShape = "circle",
): CSSProperties {
  const surface = tokens.colorSurface;
  return {
    top: typeof top === "number" ? `${top}px` : top,
    width: "30px",
    height: "30px",
    borderRadius: markRadius(shape),
    background: multiple
      ? `radial-gradient(circle, ${surface} 0 3px, ${color} 3px 5px, ${surface} 5px 7px, ${color} 7px 8.5px, transparent 9px)`
      : `radial-gradient(circle, ${surface} 0 3px, ${color} 3px 5px, transparent 5.5px)`,
    border: "none",
    boxShadow: "none",
    cursor: "crosshair",
    touchAction: "none",
  };
}

/** Keep the RF hit-target size so internals stay measured while the mark is hidden. */
export function dockedHandleStyle(top: number | string): CSSProperties {
  return {
    top: typeof top === "number" ? `${top}px` : top,
    width: "30px",
    height: "30px",
    opacity: 0,
    pointerEvents: "none",
    border: "none",
    background: "transparent",
    boxShadow: "none",
  };
}

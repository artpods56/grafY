import { tokens } from "@/lib/stylex/tokens.stylex";

type CSSProperties = Record<string, string | number>;

/**
 * Port geometry for canvas cards, from the card's outer edge: an 8px gap, then
 * a 30px slot whose centre (23px out) carries the 10px ring. The React Flow
 * handle is exactly the ring and React Flow anchors an edge on the handle's
 * outer side, so an edge starts {@link PORT_RING_REACH} px from the card.
 */
export const PORT_SLOT = 30;
export const PORT_GAP = 8;
/** From the card's outer edge to the ring's centre. */
export const PORT_CENTER_REACH = PORT_GAP + PORT_SLOT / 2;
/** From the card's outer edge to the ring's outer edge, where an edge starts. */
export const PORT_RING_REACH = PORT_CENTER_REACH + 5;

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

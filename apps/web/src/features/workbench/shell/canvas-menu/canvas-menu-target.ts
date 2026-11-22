/**
 * What a right-click on the canvas landed on. The canvas menu opens on the
 * thing under the pointer: a node, the multi-selection's frame, an edge, or
 * the empty pane.
 */
export type CanvasMenuTarget =
  | { kind: "pane" }
  | { kind: "node"; nodeId: string }
  | { kind: "selection" }
  | { kind: "edge"; edgeId: string };

export interface CanvasMenuRequest {
  /** Viewport coordinates the menu opens at. */
  point: { x: number; y: number };
  target: CanvasMenuTarget;
  /** Where focus goes when the menu closes: where it was before it opened. */
  returnFocus?: HTMLElement | null;
}

/**
 * Places where the browser's own menu is the useful one: text a person can
 * copy, paste or spell-check. The canvas menu never covers those.
 */
const NATIVE_MENU_SELECTOR =
  'input, textarea, select, [contenteditable=""], [contenteditable="true"]';

export function wantsNativeMenu(element: Element): boolean {
  return element.closest(NATIVE_MENU_SELECTOR) !== null;
}

/** The canvas thing under `element`, or null for chrome that sits on the canvas. */
export function canvasMenuTarget(element: Element): CanvasMenuTarget | null {
  if (!element.closest('[data-cell-canvas="true"]')) return null;
  if (element.closest('[data-cell-canvas-chrome="true"]')) return null;
  const card = element.closest<HTMLElement>('[data-cell-card="true"]');
  if (card) {
    const nodeId = card.getAttribute("data-card-id");
    return nodeId ? { kind: "node", nodeId } : null;
  }
  const pill = element.closest<HTMLElement>("[data-edge-selector-pill]");
  if (pill) {
    const edgeId = pill.getAttribute("data-edge-selector-pill");
    return edgeId ? { kind: "edge", edgeId } : null;
  }
  const join = element.closest<HTMLElement>("[data-docked-join]");
  if (join) {
    const edgeId = join.getAttribute("data-docked-join");
    return edgeId ? { kind: "edge", edgeId } : null;
  }
  const pipeHit = element.closest<HTMLElement>("[data-pipe-hit]");
  if (pipeHit) {
    const edgeId = pipeHit.getAttribute("data-pipe-hit");
    return edgeId ? { kind: "edge", edgeId } : null;
  }
  return { kind: "pane" };
}

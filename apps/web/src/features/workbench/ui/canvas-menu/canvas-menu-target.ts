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
  if (!element.closest(".react-flow")) return null;
  const node = element.closest<HTMLElement>(".react-flow__node");
  if (node) {
    const nodeId = node.getAttribute("data-id");
    return nodeId ? { kind: "node", nodeId } : null;
  }
  if (element.closest(".react-flow__nodesselection-rect")) {
    return { kind: "selection" };
  }
  const edge = element.closest(".react-flow__edge");
  if (edge) {
    const edgeId = edge.getAttribute("data-id");
    return edgeId ? { kind: "edge", edgeId } : null;
  }
  // Edge label chips and panels float over the pane but are not the pane.
  if (element.closest(".react-flow__edgelabel-renderer, .react-flow__panel")) {
    return null;
  }
  return element.closest(".react-flow__pane") ? { kind: "pane" } : null;
}

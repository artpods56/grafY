import type { CellGlassLook } from "@/features/workbench/cell-canvas/cell-glass-stage";
import type { CellRoutingOptions } from "@/features/workbench/cell-canvas/cell-model";

function rect({ x, y, width, height }: DOMRectReadOnly) {
  return { x, y, width, height };
}

export function inspectCards(root: HTMLElement) {
  return Array.from(
    root.querySelectorAll<HTMLElement>("[data-cell-card][data-card-id]"),
    (card) => ({
      id: card.dataset.cardId,
      rect: rect(card.getBoundingClientRect()),
      ports: Array.from(
        card.querySelectorAll<HTMLElement>(
          "[data-port-id][data-port-direction]",
        ),
        (port) => {
          const box = port.getBoundingClientRect();
          return {
            id: port.dataset.portId,
            direction: port.dataset.portDirection,
            centre: {
              x: box.left + box.width / 2,
              y: box.top + box.height / 2,
            },
            rect: rect(box),
          };
        },
      ),
      tabs: Array.from(
        card.querySelectorAll<HTMLElement>("[data-port-tab]"),
        (tab) => ({
          id: tab.dataset.portTab,
          row: tab.closest<HTMLElement>("[data-port-row]")?.dataset.portRow,
          rect: rect(tab.getBoundingClientRect()),
        }),
      ),
    }),
  );
}

declare global {
  interface Window {
    __grafy?: {
      look: CellGlassLook;
      routing: CellRoutingOptions;
      cards: ReturnType<typeof inspectCards>;
    };
  }
}

import type { Port } from "@/lib/api";

import { portHasInstancePlugs, type WorkflowNodeData } from "../canvas/types";
import type { ArtifactDropTarget } from "../model/artifact-drop";

/** The input row under a drawer drag, including a row hidden under the overlay. */
export function artifactDropRowAt(
  clientX: number,
  clientY: number,
): HTMLElement | null {
  for (const element of document.elementsFromPoint(clientX, clientY)) {
    if (!(element instanceof Element)) continue;
    if (element.closest("[data-base-ui-portal]")) continue;
    const row = element.closest<HTMLElement>("[data-input-node-id]");
    if (row) return row;
  }
  return null;
}

/** Whether a drawer drag is over the canvas itself, rather than a panel. */
export function canvasAtPoint(clientX: number, clientY: number): boolean {
  for (const element of document.elementsFromPoint(clientX, clientY)) {
    if (!(element instanceof Element)) continue;
    if (element.closest("[data-base-ui-portal]")) continue;
    if (element.closest(".react-flow")) return true;
  }
  return false;
}

/** A drop only fits a row the node actually publishes for that input slot. */
export function artifactDropTargetFitsNode(
  target: ArtifactDropTarget,
  data: WorkflowNodeData,
  port: Port,
): boolean {
  if (!portHasInstancePlugs(port)) return target.plugId === null;
  if (!target.plugId) return false;
  return data.inputPlugs.some(
    (plug) => plug.id === target.plugId && plug.portName === port.name,
  );
}

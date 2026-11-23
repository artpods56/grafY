/**
 * Where an upload or a sample was started.
 *
 * `/projects/new` is an unsaved draft and has no graph id. A saved Project is
 * the project id together with the open graph: Workbench stays mounted across
 * Project switches, and two Projects can both call their graph "main".
 */
export type CanvasPlacementTarget =
  | { readonly kind: "draft"; readonly sessionId: string }
  | {
      readonly kind: "saved";
      readonly projectId: string;
      readonly graphId: string;
    };

export function canvasPlacementTarget(input: {
  projectId: string | null;
  graphId: string | null;
  draftSessionId: string;
}): CanvasPlacementTarget | null {
  if (input.projectId === null) {
    return { kind: "draft", sessionId: input.draftSessionId };
  }
  if (input.graphId === null) return null;
  return {
    kind: "saved",
    projectId: input.projectId,
    graphId: input.graphId,
  };
}

/** Returning to `/projects/new` from a saved Project starts a new draft. */
export function advanceDraftSession(
  previousProjectId: string | null,
  projectId: string | null,
  session: number,
): number {
  if (projectId === null && previousProjectId !== null) return session + 1;
  return session;
}

/** Place only while authoring is on and the canvas is still the one that started the request. */
export function mayPlaceOnInitiatingCanvas(input: {
  authoringEnabled: boolean;
  active: CanvasPlacementTarget | null;
  initiating: CanvasPlacementTarget | null;
}): boolean {
  if (
    !input.authoringEnabled ||
    input.active === null ||
    input.initiating === null
  ) {
    return false;
  }
  return sameCanvasTarget(input.active, input.initiating);
}

function sameCanvasTarget(
  active: CanvasPlacementTarget,
  initiating: CanvasPlacementTarget,
): boolean {
  if (initiating.kind === "draft") {
    return active.kind === "draft" && active.sessionId === initiating.sessionId;
  }
  return (
    active.kind === "saved" &&
    active.projectId === initiating.projectId &&
    active.graphId === initiating.graphId
  );
}

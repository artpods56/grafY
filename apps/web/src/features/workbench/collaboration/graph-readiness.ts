import type { GraphRoomStatus } from "./protocol";

export type GraphReadinessState = "current" | "stale" | "unavailable";

export interface GraphReadiness {
  readonly state: GraphReadinessState;
  readonly trusted: boolean;
}

/** One trust policy for every action that consumes the displayed saved graph. */
export function graphReadiness(
  status: GraphRoomStatus,
  hasConfirmedHead: boolean,
): GraphReadiness {
  if (status === "ready" && hasConfirmedHead) {
    return { state: "current", trusted: true };
  }
  if (hasConfirmedHead) {
    return { state: "stale", trusted: false };
  }
  return { state: "unavailable", trusted: false };
}

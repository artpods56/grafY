import type { PresenceParticipant } from "./protocol";

const ACTOR_COLOR: Record<string, string> = {
  indigo: "#4f46e5",
  emerald: "#059669",
  amber: "#d97706",
  rose: "#e11d48",
  sky: "#0284c7",
  violet: "#7c3aed",
  teal: "#0d9488",
  orange: "#ea580c",
};

export function actorColor(color: string): string {
  return ACTOR_COLOR[color] ?? ACTOR_COLOR.indigo ?? "#4f46e5";
}

export function remoteSelectedNodeIds(
  participants: readonly PresenceParticipant[],
  localSessionId: string | null,
): ReadonlySet<string> {
  const ids = new Set<string>();
  for (const participant of participants) {
    if (participant.project_room_session_id === localSessionId) continue;
    for (const nodeId of participant.selected_node_ids) {
      ids.add(nodeId);
    }
  }
  return ids;
}

/** First remote collaborator color for a node, if any. */
export function remoteSelectionColor(
  participants: readonly PresenceParticipant[],
  localSessionId: string | null,
  nodeId: string,
): string | null {
  for (const participant of participants) {
    if (participant.project_room_session_id === localSessionId) continue;
    if (participant.selected_node_ids.includes(nodeId)) {
      return actorColor(participant.actor.color);
    }
  }
  return null;
}

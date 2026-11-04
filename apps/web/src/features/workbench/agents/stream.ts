export type AgentDelta = {
  graph_id: string;
  agent_id: string;
  conversation_id: string;
  turn_id: string;
  message_id: string;
  offset: number;
  text: string;
};
export type PartialReply = {
  turnId: string;
  messageId: string;
  text: string;
  gap: boolean;
};
export function appendDelta(
  current: PartialReply | null,
  delta: AgentDelta,
): PartialReply {
  const base = current ?? {
    turnId: delta.turn_id,
    messageId: delta.message_id,
    text: "",
    gap: false,
  };
  if (
    base.turnId !== delta.turn_id ||
    base.messageId !== delta.message_id ||
    base.gap
  )
    return { ...base, gap: true };
  const length = Array.from(base.text).length;
  if (delta.offset < length) return base;
  if (delta.offset !== length) return { ...base, gap: true };
  return { ...base, text: base.text + delta.text };
}
export function parseDelta(raw: unknown): AgentDelta | null {
  if (
    !raw ||
    typeof raw !== "object" ||
    !("type" in raw) ||
    raw.type !== "agent.delta"
  )
    return null;
  if (
    !("graph_id" in raw) ||
    typeof raw.graph_id !== "string" ||
    !("agent_id" in raw) ||
    typeof raw.agent_id !== "string" ||
    !("conversation_id" in raw) ||
    typeof raw.conversation_id !== "string" ||
    !("turn_id" in raw) ||
    typeof raw.turn_id !== "string" ||
    !("message_id" in raw) ||
    typeof raw.message_id !== "string" ||
    !("offset" in raw) ||
    typeof raw.offset !== "number" ||
    !Number.isInteger(raw.offset) ||
    raw.offset < 0 ||
    !("text" in raw) ||
    typeof raw.text !== "string"
  )
    return null;
  return {
    graph_id: raw.graph_id,
    agent_id: raw.agent_id,
    conversation_id: raw.conversation_id,
    turn_id: raw.turn_id,
    message_id: raw.message_id,
    offset: raw.offset,
    text: raw.text,
  };
}
type Notice = { workspaceId: string; projectId: string; raw: unknown };
const listeners = new Set<(notice: Notice) => void>();
export function publishAgentRoom(notice: Notice) {
  for (const listener of listeners) listener(notice);
}
export function subscribeAgentRoom(listener: (notice: Notice) => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export type AgentNotice = {
  graphId: string;
  agentId: string;
  conversationId: string;
};
/** Lifecycle frames invalidate the HTTP snapshot; their payload never becomes history. */
export function parseAgentNotice(raw: unknown): AgentNotice | null {
  if (!raw || typeof raw !== "object" || !("type" in raw)) return null;
  if (
    raw.type !== "agent.turn.started" &&
    raw.type !== "agent.turn.finished" &&
    raw.type !== "agent.event.appended"
  )
    return null;
  const target =
    raw.type === "agent.turn.started" && "turn" in raw ? raw.turn : raw;
  if (
    !target ||
    typeof target !== "object" ||
    !("graph_id" in target) ||
    typeof target.graph_id !== "string" ||
    !("agent_id" in target) ||
    typeof target.agent_id !== "string"
  )
    return null;
  const entry =
    raw.type === "agent.event.appended" && "event" in raw ? raw.event : target;
  if (
    !entry ||
    typeof entry !== "object" ||
    !("conversation_id" in entry) ||
    typeof entry.conversation_id !== "string" ||
    !("turn_id" in entry) ||
    typeof entry.turn_id !== "string"
  )
    return null;
  if (
    raw.type === "agent.event.appended" &&
    (!("sequence" in entry) ||
      typeof entry.sequence !== "number" ||
      !Number.isInteger(entry.sequence) ||
      entry.sequence < 1)
  )
    return null;
  return {
    graphId: target.graph_id,
    agentId: target.agent_id,
    conversationId: entry.conversation_id,
  };
}

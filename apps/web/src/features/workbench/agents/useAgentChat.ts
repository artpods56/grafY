import * as React from "react";
import { agentApi, type AgentScope, type AgentEvent } from "@/lib/api/agents";
import type { components } from "@/lib/api/generated/grafy";
import { createUuid } from "../model/uuid";
import {
  appendDelta,
  parseDelta,
  parseAgentNotice,
  subscribeAgentRoom,
  type PartialReply,
} from "./stream";
type S = components["schemas"];
export function useAgentChat(scope: AgentScope) {
  const api = React.useMemo(
    () =>
      agentApi({
        workspaceId: scope.workspaceId,
        projectId: scope.projectId,
        graphId: scope.graphId,
        agentId: scope.agentId,
      }),
    [scope.workspaceId, scope.projectId, scope.graphId, scope.agentId],
  );
  const [conversations, setConversations] = React.useState<
    readonly S["AgentConversationResponse"][]
  >([]);
  const [conversationId, setConversationId] = React.useState("");
  const [events, setEvents] = React.useState<readonly AgentEvent[]>([]);
  const [partial, setPartial] = React.useState<PartialReply | null>(null);
  const partialRef = React.useRef(partial);
  partialRef.current = partial;
  const [active, setActive] = React.useState<
    S["ActiveAgentTurnResponse"] | null
  >(null);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const sending = React.useRef(false);
  const retry = React.useRef<S["SendAgentTurnRequest"] | null>(null);
  const generation = React.useRef(0);
  const fail = (reason: unknown) =>
    setError(
      reason instanceof Error ? reason.message : "Unable to load conversation.",
    );
  React.useEffect(() => {
    let alive = true;
    void api
      .list()
      .then((result) => {
        if (alive) {
          setConversations(result.conversations);
          setLoading(result.conversations.length > 0);
          setConversationId(result.conversations[0]?.id ?? "");
        }
      })
      .catch((reason) => {
        if (alive) {
          setLoading(false);
          fail(reason);
        }
      });
    return () => {
      alive = false;
    };
  }, [api]);
  const sync = React.useCallback(async () => {
    if (!conversationId) return;
    const version = ++generation.current;
    let after = 0;
    const history: AgentEvent[] = [];
    for (;;) {
      const page = await api.events(conversationId, after);
      history.push(...page.events);
      if (
        page.next_sequence >= page.last_sequence ||
        page.next_sequence <= after
      )
        break;
      after = page.next_sequence;
    }
    const snapshot = await api.active(conversationId);
    if (version !== generation.current) return;
    setEvents(history);
    setActive(snapshot);
    const final =
      snapshot &&
      history.some(
        (event) =>
          event.turn_id === snapshot.turn.id &&
          event.payload.kind === "assistant_message",
      );
    let next =
      snapshot && snapshot.message_id && !final
        ? {
            turnId: snapshot.turn.id,
            messageId: snapshot.message_id,
            text: snapshot.partial_text,
            gap: false,
          }
        : null;
    const provisional = partialRef.current;
    if (
      next &&
      provisional &&
      !provisional.gap &&
      provisional.turnId === next.turnId &&
      provisional.messageId === next.messageId &&
      provisional.text.startsWith(next.text)
    )
      next = provisional;
    partialRef.current = next;
    setPartial(next);
  }, [api, conversationId]);
  React.useEffect(() => {
    const lifecycle = generation;
    void sync()
      .then(() => setLoading(false))
      .catch((reason) => {
        setLoading(false);
        fail(reason);
      });
    return () => {
      lifecycle.current++;
    };
  }, [sync]);
  React.useEffect(
    () =>
      subscribeAgentRoom((notice) => {
        if (
          notice.workspaceId !== scope.workspaceId ||
          notice.projectId !== scope.projectId
        )
          return;
        const raw = notice.raw;
        if (!raw || typeof raw !== "object" || !("type" in raw)) return;
        if (raw.type === "room.ready") {
          void sync().catch(fail);
          return;
        }
        const delta = parseDelta(raw);
        if (delta) {
          if (
            delta.graph_id !== scope.graphId ||
            delta.agent_id !== scope.agentId ||
            delta.conversation_id !== conversationId
          )
            return;
          if (
            events.some(
              (event) =>
                event.turn_id === delta.turn_id &&
                event.payload.kind === "assistant_message",
            )
          )
            return;
          const next = appendDelta(partialRef.current, delta);
          partialRef.current = next;
          setPartial(next);
          if (next.gap) void sync().catch(fail);
          return;
        }
        const target = parseAgentNotice(raw);
        if (
          target?.graphId === scope.graphId &&
          target.agentId === scope.agentId &&
          target.conversationId === conversationId
        )
          void sync().catch(fail);
      }),
    [
      scope.workspaceId,
      scope.projectId,
      scope.graphId,
      scope.agentId,
      conversationId,
      sync,
      events,
    ],
  );
  async function action(task: () => Promise<void>) {
    setError("");
    setBusy(true);
    try {
      await task();
      return true;
    } catch (reason) {
      fail(reason);
      return false;
    } finally {
      setBusy(false);
    }
  }
  function select(id: string) {
    generation.current++;
    setLoading(!!id);
    setEvents([]);
    setPartial(null);
    partialRef.current = null;
    setActive(null);
    retry.current = null;
    setConversationId(id);
  }
  return {
    conversations,
    conversationId,
    events,
    partial,
    active,
    error,
    busy,
    loading,
    retryText: retry.current?.text,
    select,
    create: () =>
      action(async () => {
        const item = await api.create();
        setConversations((items) => [...items, item]);
        select(item.id);
      }),
    fork: (sequence: number) =>
      action(async () => {
        const item = await api.fork(conversationId, sequence);
        setConversations((items) => [...items, item]);
        select(item.id);
      }),
    send: (text: string) =>
      action(async () => {
        if (sending.current || active || loading || !text.trim()) return;
        sending.current = true;
        try {
          const body = retry.current ?? { client_turn_id: createUuid(), text };
          retry.current = body;
          await api.send(conversationId, body);
          await sync();
          retry.current = null;
        } finally {
          sending.current = false;
        }
      }),
    stop: () =>
      action(async () => {
        if (active) {
          await api.cancel(conversationId, active.turn.id);
          await sync();
        }
      }),
  };
}

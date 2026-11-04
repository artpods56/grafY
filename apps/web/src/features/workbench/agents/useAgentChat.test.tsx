// @vitest-environment jsdom
import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { useAgentChat } from "./useAgentChat";
import { publishAgentRoom } from "./stream";
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const scope = { workspaceId: "w", projectId: "p", graphId: "g", agentId: "a" };
it("retries one turn identity, stops, and replaces provisional text with durable history", async () => {
  let history: unknown[] = [];
  let running = false;
  let failSend = true;
  const ids: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      let data: unknown;
      if (url.endsWith("/conversations"))
        data = { conversations: [{ id: "c", title: "Chat" }] };
      else if (url.includes("/events?"))
        data = {
          events: history,
          last_sequence: history.length,
          next_sequence: history.length,
        };
      else if (url.endsWith("/active-turn"))
        data = running
          ? {
              turn: { id: "t", status: "running" },
              message_id: "m",
              partial_text: "😀",
              partial_offset: 1,
            }
          : null;
      else if (url.endsWith("/turns")) {
        const body = JSON.parse(String(init.body));
        ids.push(body.client_turn_id);
        if (failSend) {
          failSend = false;
          throw new Error("Disconnected");
        }
        running = true;
        data = { id: "t" };
      } else if (url.endsWith("/cancel")) {
        running = false;
        history = [
          {
            sequence: 1,
            turn_id: "t",
            payload: { kind: "assistant_message", text: "Final answer" },
          },
        ];
        data = { id: "t" };
      }
      return new Response(JSON.stringify(data), { status: 200 });
    }),
  );
  let chat: ReturnType<typeof useAgentChat> | undefined;
  function Harness() {
    chat = useAgentChat(scope);
    return null;
  }
  const host = document.createElement("div");
  const root = createRoot(host);
  await act(async () => {
    root.render(<Harness />);
  });
  if (!chat) throw new Error("Hook did not mount");
  await act(async () => {
    await chat?.send("Hello");
  });
  expect(chat.error).toBe("Disconnected");
  await act(async () => {
    await chat?.send("Hello");
  });
  expect(ids).toHaveLength(2);
  expect(ids[0]).toBe(ids[1]);
  expect(chat.partial?.text).toBe("😀");
  await act(async () => {
    publishAgentRoom({
      workspaceId: "w",
      projectId: "p",
      raw: {
        type: "agent.delta",
        graph_id: "g",
        agent_id: "a",
        conversation_id: "c",
        turn_id: "t",
        message_id: "m",
        offset: 1,
        text: " hello",
      },
    });
  });
  expect(chat.partial?.text).toBe("😀 hello");
  await act(async () => {
    publishAgentRoom({
      workspaceId: "w",
      projectId: "p",
      raw: {
        type: "agent.delta",
        graph_id: "other",
        agent_id: "a",
        conversation_id: "c",
        turn_id: "t",
        message_id: "m",
        offset: 7,
        text: "wrong",
      },
    });
  });
  expect(chat.partial?.text).toBe("😀 hello");
  await act(async () => {
    publishAgentRoom({
      workspaceId: "w",
      projectId: "p",
      raw: {
        type: "agent.delta",
        graph_id: "g",
        agent_id: "a",
        conversation_id: "c",
        turn_id: "t",
        message_id: "m",
        offset: 99,
        text: "gap",
      },
    });
  });
  expect(chat.partial?.text).toBe("😀");

  await act(async () => {
    await chat?.stop();
  });
  expect(chat.partial).toBeNull();
  expect(chat.active).toBeNull();
  expect(chat.events).toEqual(history);
  await act(async () => {
    publishAgentRoom({
      workspaceId: "w",
      projectId: "p",
      raw: { type: "room.ready" },
    });
  });
  expect(chat.events).toHaveLength(1);
  await act(async () => {
    publishAgentRoom({
      workspaceId: "w",
      projectId: "p",
      raw: {
        type: "agent.delta",
        graph_id: "g",
        agent_id: "a",
        conversation_id: "c",
        turn_id: "t",
        message_id: "m",
        offset: 0,
        text: "late",
      },
    });
  });
  expect(chat.partial).toBeNull();

  await act(async () => root.unmount());
  vi.unstubAllGlobals();
});

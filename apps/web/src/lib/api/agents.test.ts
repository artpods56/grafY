import { expect, it, vi } from "vitest";
import { agentApi } from "./agents";
it("scopes all conversation requests and clears a write-only key", async () => {
  const fetch = vi.fn(
    async (_url: string, _init: RequestInit) =>
      new Response("{}", { status: 200 }),
  );
  vi.stubGlobal("fetch", fetch);
  const api = agentApi({
    workspaceId: "w",
    projectId: "p",
    graphId: "g",
    agentId: "a",
  });
  await api.key("secret");
  await api.clearKey();
  await api.send("c", { client_turn_id: "stable", text: "Hi" });
  await api.cancel("c", "t");
  await api.fork("c", 2);
  expect(fetch.mock.calls.map((call) => call[0])).toEqual([
    "/api/v1/workspaces/w/projects/p/graphs/g/agents/a/key",
    "/api/v1/workspaces/w/projects/p/graphs/g/agents/a/key",
    "/api/v1/workspaces/w/projects/p/graphs/g/agents/a/conversations/c/turns",
    "/api/v1/workspaces/w/projects/p/graphs/g/agents/a/conversations/c/cancel",
    "/api/v1/workspaces/w/projects/p/graphs/g/agents/a/conversations/c/fork",
  ]);
  vi.unstubAllGlobals();
});

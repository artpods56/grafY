import { request } from "./client";
import type { components } from "./generated/grafy";
type S = components["schemas"];
export type AgentEvent = S["AgentConversationEventResponse"];
export type AgentScope = {
  workspaceId: string;
  projectId: string;
  graphId: string;
  agentId: string;
};
export function agentApi(scope: AgentScope) {
  const root = `/v1/workspaces/${encodeURIComponent(scope.workspaceId)}/projects/${encodeURIComponent(scope.projectId)}/graphs/${encodeURIComponent(scope.graphId)}/agents/${encodeURIComponent(scope.agentId)}`;
  const conversation = (id: string) =>
    `${root}/conversations/${encodeURIComponent(id)}`;
  return {
    list: () =>
      request<S["AgentConversationListResponse"]>(
        "GET",
        `${root}/conversations`,
      ),
    create: () =>
      request<S["AgentConversationResponse"]>("POST", `${root}/conversations`, {
        body: {
          title: "New conversation",
        } satisfies S["StartAgentConversationRequest"],
      }),
    events: (id: string, after: number) =>
      request<S["AgentConversationEventListResponse"]>(
        "GET",
        `${conversation(id)}/events?after_sequence=${after}`,
      ),
    active: (id: string) =>
      request<S["ActiveAgentTurnResponse"] | null>(
        "GET",
        `${conversation(id)}/active-turn`,
      ),
    send: (id: string, body: S["SendAgentTurnRequest"]) =>
      request<S["AgentTurnResponse"]>("POST", `${conversation(id)}/turns`, {
        body,
      }),
    cancel: (id: string, turnId: string) =>
      request<S["AgentTurnResponse"]>("POST", `${conversation(id)}/cancel`, {
        body: { turn_id: turnId } satisfies S["CancelAgentTurnRequest"],
      }),
    fork: (id: string, sequence: number) =>
      request<S["AgentConversationResponse"]>(
        "POST",
        `${conversation(id)}/fork`,
        {
          body: {
            at_sequence: sequence,
          } satisfies S["ForkAgentConversationRequest"],
        },
      ),
    model: () => request<S["AgentModelResponse"]>("GET", `${root}/model`),
    key: (key: string) =>
      request<S["AgentKeyResponse"]>("PUT", `${root}/key`, {
        body: { value: key } satisfies S["SetAgentKeyRequest"],
      }),
    clearKey: () => request<void>("DELETE", `${root}/key`),
  };
}

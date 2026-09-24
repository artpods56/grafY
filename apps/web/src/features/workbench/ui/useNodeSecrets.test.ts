// @vitest-environment jsdom

import * as React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AppliedNodeSecret,
  GraphNodeSecrets,
  NodeSpec,
  SavedGraphNode,
} from "@/lib/api";
import { WORKFLOW_NODE_TYPE, createWorkflowNodeData } from "../canvas/types";
import type { WorkflowNode } from "../model/execution-plan";
import { deferred } from "./test/deferred";
import { renderHook } from "./test/renderHook";
import { useNodeSecrets, type NodeSecretGraph } from "./useNodeSecrets";

const api = vi.hoisted(() => ({
  getGraphNodeSecrets: vi.fn<typeof import("@/lib/api").getGraphNodeSecrets>(),
  applyNodeSecret: vi.fn<typeof import("@/lib/api").applyNodeSecret>(),
  removeNodeSecret: vi.fn<typeof import("@/lib/api").removeNodeSecret>(),
}));

vi.mock("@/lib/api", () => api);

const nodeId = "llm-1";
const secretName = "api_key";
const savedBaseUrl = "https://api.openai.com/v1";

function secretNodeSpec(): NodeSpec {
  return {
    operator_id: "llm.openai.completion",
    operator_version: 1,
    plugin_slug: "external.llm",
    origin: "builtin",
    title: "OpenAI-compatible completion",
    description: "Completes a prompt through an OpenAI-compatible API.",
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [],
    secret_inputs: [
      {
        name: secretName,
        title: "API key",
        description: "OpenAI-compatible bearer credential.",
        config_dependencies: ["base_url"],
      },
    ],
  };
}

function workflowNode(baseUrl = savedBaseUrl, id = nodeId): WorkflowNode {
  return {
    id,
    type: WORKFLOW_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: {
      ...createWorkflowNodeData(secretNodeSpec()),
      config: { base_url: baseUrl },
    },
  };
}

function savedNode(baseUrl = savedBaseUrl, id = nodeId): SavedGraphNode {
  return {
    id,
    kind: "builtin",
    operator_id: "llm.openai.completion",
    operator_version: 1,
    position: { x: 0, y: 0 },
    config: { base_url: baseUrl },
    input_plugs: [],
    artifact_type_bindings: [],
  };
}

function graph(
  id: string,
  revision: number,
  baseUrl = savedBaseUrl,
  nodes: readonly SavedGraphNode[] = [savedNode(baseUrl)],
): NodeSecretGraph {
  return { id, revision, nodes };
}

function graphSecrets(
  activeGraph: NodeSecretGraph,
  configured: boolean,
): GraphNodeSecrets {
  return {
    graph_id: activeGraph.id,
    graph_revision: activeGraph.revision,
    secrets: [{ node_id: nodeId, name: secretName, configured }],
  };
}

beforeEach(() => {
  api.getGraphNodeSecrets.mockReset();
  api.applyNodeSecret.mockReset();
  api.removeNodeSecret.mockReset();
});

describe("useNodeSecrets", () => {
  it("keeps an unsupported node's secrets dormant and absent from client status", async () => {
    const node = workflowNode();
    node.data.compatibility = {
      status: "unsupported",
      issues: ["The operator is unavailable."],
      inputs: [],
      outputs: [],
      persistedNode: savedNode(),
    };
    const activeGraph = graph("00000000-0000-4000-8000-000000000001", 1);
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets("workspace-1", nodes),
      { nodes: [node] },
    );

    let refreshed = false;
    await React.act(async () => {
      refreshed = await hook.result.current.refreshNodeSecretStatuses(
        activeGraph,
        [node],
      );
    });

    expect(refreshed).toBe(true);
    expect(api.getGraphNodeSecrets).not.toHaveBeenCalled();
    expect(hook.result.current.nodeSecretStatuses).toEqual({});
  });

  it("keeps the newest refresh when an older graph request finishes last", async () => {
    const node = workflowNode();
    const olderGraph = graph("00000000-0000-4000-8000-000000000001", 1);
    const newerGraph = graph("00000000-0000-4000-8000-000000000002", 3);
    const olderResponse = deferred<GraphNodeSecrets>();
    const newerResponse = deferred<GraphNodeSecrets>();
    api.getGraphNodeSecrets
      .mockReturnValueOnce(olderResponse.promise)
      .mockReturnValueOnce(newerResponse.promise);
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets("workspace-1", nodes),
      { nodes: [node] },
    );

    let olderRefresh!: Promise<boolean>;
    await React.act(() => {
      olderRefresh = hook.result.current.refreshNodeSecretStatuses(olderGraph, [
        node,
      ]);
    });
    let newerRefresh!: Promise<boolean>;
    await React.act(() => {
      newerRefresh = hook.result.current.refreshNodeSecretStatuses(newerGraph, [
        node,
      ]);
    });

    let newerRefreshed = false;
    await React.act(async () => {
      newerResponse.resolve(graphSecrets(newerGraph, true));
      newerRefreshed = await newerRefresh;
    });
    expect(newerRefreshed).toBe(true);
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: { [secretName]: { state: "configured" } },
    });

    let olderRefreshed = true;
    await React.act(async () => {
      olderResponse.resolve(graphSecrets(olderGraph, false));
      olderRefreshed = await olderRefresh;
    });
    expect(olderRefreshed).toBe(false);
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: { [secretName]: { state: "configured" } },
    });
  });

  it("does not restore statuses after the active graph is cleared", async () => {
    const node = workflowNode();
    const activeGraph = graph("00000000-0000-4000-8000-000000000003", 2);
    const response = deferred<GraphNodeSecrets>();
    api.getGraphNodeSecrets.mockReturnValue(response.promise);
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets("workspace-1", nodes),
      { nodes: [node] },
    );

    let refresh!: Promise<boolean>;
    await React.act(() => {
      refresh = hook.result.current.refreshNodeSecretStatuses(activeGraph, [
        node,
      ]);
    });
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: { [secretName]: { state: "loading" } },
    });

    await React.act(() => {
      hook.result.current.clearGraphSecretStatuses();
    });
    response.resolve(graphSecrets(activeGraph, true));

    await expect(refresh).resolves.toBe(false);
    expect(hook.result.current.nodeSecretStatuses).toEqual({});
  });

  it("does not repopulate a forgotten node when a refresh finishes", async () => {
    const node = workflowNode();
    const activeGraph = graph("00000000-0000-4000-8000-000000000006", 5);
    const response = deferred<GraphNodeSecrets>();
    api.getGraphNodeSecrets.mockReturnValue(response.promise);
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets("workspace-1", nodes),
      { nodes: [node] },
    );

    let refresh!: Promise<boolean>;
    await React.act(() => {
      refresh = hook.result.current.refreshNodeSecretStatuses(activeGraph, [
        node,
      ]);
    });
    await React.act(() => {
      hook.result.current.forgetNodeSecretStatuses(nodeId);
    });

    await React.act(async () => {
      response.resolve(graphSecrets(activeGraph, true));
      await expect(refresh).resolves.toBe(true);
    });
    expect(hook.result.current.nodeSecretStatuses).toEqual({});
  });

  it("refreshes unrelated nodes while preserving a concurrent secret write", async () => {
    const otherNodeId = "llm-2";
    const firstNode = workflowNode();
    const otherNode = workflowNode(savedBaseUrl, otherNodeId);
    const activeGraph = graph(
      "00000000-0000-4000-8000-000000000007",
      6,
      savedBaseUrl,
      [savedNode(), savedNode(savedBaseUrl, otherNodeId)],
    );
    const refreshResponse = deferred<GraphNodeSecrets>();
    const applyResponse = deferred<AppliedNodeSecret>();
    api.getGraphNodeSecrets
      .mockResolvedValueOnce({
        graph_id: activeGraph.id,
        graph_revision: activeGraph.revision,
        secrets: [
          { node_id: nodeId, name: secretName, configured: false },
          { node_id: otherNodeId, name: secretName, configured: false },
        ],
      })
      .mockReturnValueOnce(refreshResponse.promise);
    api.applyNodeSecret.mockReturnValue(applyResponse.promise);
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets("workspace-1", nodes),
      { nodes: [firstNode, otherNode] },
    );

    await React.act(async () => {
      await hook.result.current.refreshNodeSecretStatuses(activeGraph, [
        firstNode,
        otherNode,
      ]);
    });
    let applying!: Promise<boolean>;
    await React.act(() => {
      applying = hook.result.current.applyConfiguredNodeSecret(
        nodeId,
        secretName,
        "sk-concurrent-write",
      );
    });
    let refresh!: Promise<boolean>;
    await React.act(() => {
      refresh = hook.result.current.refreshNodeSecretStatuses(activeGraph, [
        firstNode,
        otherNode,
      ]);
    });
    expect(
      hook.result.current.nodeSecretStatuses[nodeId]?.[secretName]?.state,
    ).toBe("applying");
    expect(
      hook.result.current.nodeSecretStatuses[otherNodeId]?.[secretName]?.state,
    ).toBe("loading");

    await React.act(async () => {
      applyResponse.resolve({
        node_id: nodeId,
        name: secretName,
        configured: true,
      });
      await applying;
    });
    expect(
      hook.result.current.nodeSecretStatuses[nodeId]?.[secretName]?.state,
    ).toBe("configured");
    expect(
      hook.result.current.nodeSecretStatuses[otherNodeId]?.[secretName]?.state,
    ).toBe("loading");

    let refreshed = false;
    await React.act(async () => {
      refreshResponse.resolve({
        graph_id: activeGraph.id,
        graph_revision: activeGraph.revision,
        secrets: [
          { node_id: nodeId, name: secretName, configured: false },
          { node_id: otherNodeId, name: secretName, configured: true },
        ],
      });
      refreshed = await refresh;
    });
    expect(refreshed).toBe(true);
    expect(
      hook.result.current.nodeSecretStatuses[nodeId]?.[secretName]?.state,
    ).toBe("configured");
    expect(
      hook.result.current.nodeSecretStatuses[otherNodeId]?.[secretName]?.state,
    ).toBe("configured");
  });

  it("sends the exact write-only value and stores only lifecycle metadata", async () => {
    const node = workflowNode();
    const activeGraph = graph("00000000-0000-4000-8000-000000000004", 7);
    api.getGraphNodeSecrets.mockResolvedValue(graphSecrets(activeGraph, false));
    const applyResponse = deferred<AppliedNodeSecret>();
    api.applyNodeSecret.mockReturnValue(applyResponse.promise);
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets("workspace-1", nodes),
      { nodes: [node] },
    );
    await React.act(async () => {
      await hook.result.current.refreshNodeSecretStatuses(activeGraph, [node]);
    });

    const plaintext = "sk-test-plaintext-value";
    let applying!: Promise<boolean>;
    await React.act(() => {
      applying = hook.result.current.applyConfiguredNodeSecret(
        nodeId,
        secretName,
        plaintext,
      );
    });

    expect(api.applyNodeSecret).toHaveBeenCalledWith(
      "workspace-1",
      activeGraph.id,
      nodeId,
      secretName,
      { value: plaintext, expected_graph_revision: activeGraph.revision },
    );
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: { [secretName]: { state: "applying" } },
    });
    expect(
      JSON.stringify(hook.result.current.nodeSecretStatuses),
    ).not.toContain(plaintext);

    let applied = false;
    await React.act(async () => {
      applyResponse.resolve({
        node_id: nodeId,
        name: secretName,
        configured: true,
      });
      applied = await applying;
    });
    expect(applied).toBe(true);
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: { [secretName]: { state: "configured" } },
    });
    expect(
      JSON.stringify(hook.result.current.nodeSecretStatuses),
    ).not.toContain(plaintext);
  });

  it("fails closed when a secret dependency no longer matches the saved node", async () => {
    const node = workflowNode("https://openrouter.ai/api/v1");
    const activeGraph = graph("00000000-0000-4000-8000-000000000005", 4);
    api.getGraphNodeSecrets.mockResolvedValue(graphSecrets(activeGraph, true));
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets("workspace-1", nodes),
      { nodes: [node] },
    );
    await React.act(async () => {
      await hook.result.current.refreshNodeSecretStatuses(activeGraph, [node]);
    });

    await expect(
      hook.result.current.applyConfiguredNodeSecret(
        nodeId,
        secretName,
        "must-not-be-sent",
      ),
    ).resolves.toBe(false);

    expect(api.applyNodeSecret).not.toHaveBeenCalled();
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: { [secretName]: { state: "configured" } },
    });
  });
});

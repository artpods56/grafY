// @vitest-environment jsdom

import * as React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AppliedNodeSecret,
  NodeSpec,
  ProjectNodeSecrets,
  SavedGraphNode,
} from "@/lib/api";
import { WORKFLOW_NODE_TYPE, createWorkflowNodeData } from "../canvas/types";
import type { WorkflowNode } from "../model/execution-plan";
import { deferred } from "./test/deferred";
import { renderHook } from "./test/renderHook";
import { useNodeSecrets, type NodeSecretGraph } from "./useNodeSecrets";

const api = vi.hoisted(() => ({
  getProjectNodeSecrets:
    vi.fn<typeof import("@/lib/api").getProjectNodeSecrets>(),
  applyNodeSecret: vi.fn<typeof import("@/lib/api").applyNodeSecret>(),
  removeNodeSecret: vi.fn<typeof import("@/lib/api").removeNodeSecret>(),
}));

vi.mock("@/lib/api", () => api);

const workspaceId = "workspace-1";
/** A Project is addressed by a Project id — never by a Graph id. */
const projectId = "00000000-0000-4000-8000-000000000001";
const otherProjectId = "00000000-0000-4000-8000-000000000008";
/** The Graph inside that Project the node lives in. */
const graphId = "main";
const otherGraphId = "analysis";
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
  projectId: string,
  graphId: string,
  revision: number,
  baseUrl = savedBaseUrl,
  nodes: readonly SavedGraphNode[] = [savedNode(baseUrl)],
): NodeSecretGraph {
  return { id: projectId, graphId, revision, nodes };
}

function projectSecrets(
  activeGraph: NodeSecretGraph,
  configured: boolean,
  headSequence = activeGraph.revision,
): ProjectNodeSecrets {
  return {
    project_id: activeGraph.id,
    graph_id: activeGraph.graphId,
    head_sequence: headSequence,
    unresolved_nodes: [],
    secrets: [{ node_id: nodeId, name: secretName, configured }],
  };
}

/**
 * What the API answers when `expected_head_sequence` names a head that is gone:
 * an ApiError carrying 409 and nothing else. A secret write raises no other
 * status for the head, so a test that means "the head moved" says it this way.
 */
function headMoved(): Error {
  return Object.assign(
    new Error("API error 409: collaboration head conflict"),
    {
      name: "ApiError",
      status: 409,
      detail: "collaboration head conflict",
    },
  );
}

function applied(configured = true): AppliedNodeSecret {
  return { node_id: nodeId, name: secretName, configured };
}

beforeEach(() => {
  api.getProjectNodeSecrets.mockReset();
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
    const activeGraph = graph(projectId, graphId, 1);
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
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
    expect(api.getProjectNodeSecrets).not.toHaveBeenCalled();
    expect(hook.result.current.nodeSecretStatuses).toEqual({});
  });

  it("asks for the Project and the Graph as two distinct things", async () => {
    const node = workflowNode();
    const activeGraph = graph(projectId, graphId, 2);
    api.getProjectNodeSecrets.mockResolvedValue(
      projectSecrets(activeGraph, false),
    );
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
      { nodes: [node] },
    );

    await React.act(async () => {
      await expect(
        hook.result.current.refreshNodeSecretStatuses(activeGraph, [node]),
      ).resolves.toBe(true);
    });

    expect(api.getProjectNodeSecrets).toHaveBeenCalledWith(
      workspaceId,
      projectId,
      graphId,
      undefined,
    );
  });

  it("keeps the newest refresh when an older graph request finishes last", async () => {
    const node = workflowNode();
    // Both Graphs live in one Project: the Project id alone cannot tell them
    // apart, so the Graph is what makes an older response stale.
    const olderGraph = graph(projectId, otherGraphId, 1);
    const newerGraph = graph(projectId, graphId, 3);
    const olderResponse = deferred<ProjectNodeSecrets>();
    const newerResponse = deferred<ProjectNodeSecrets>();
    api.getProjectNodeSecrets
      .mockReturnValueOnce(olderResponse.promise)
      .mockReturnValueOnce(newerResponse.promise);
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
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
      newerResponse.resolve(projectSecrets(newerGraph, true));
      newerRefreshed = await newerRefresh;
    });
    expect(newerRefreshed).toBe(true);
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: { [secretName]: { state: "configured" } },
    });

    let olderRefreshed = true;
    await React.act(async () => {
      olderResponse.resolve(projectSecrets(olderGraph, false));
      olderRefreshed = await olderRefresh;
    });
    expect(olderRefreshed).toBe(false);
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: { [secretName]: { state: "configured" } },
    });
  });

  it("does not apply a listing that names a different Graph than it was asked for", async () => {
    const node = workflowNode();
    const activeGraph = graph(projectId, graphId, 4);
    api.getProjectNodeSecrets.mockResolvedValue(
      projectSecrets(graph(projectId, otherGraphId, 4), true),
    );
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
      { nodes: [node] },
    );

    await React.act(async () => {
      await expect(
        hook.result.current.refreshNodeSecretStatuses(activeGraph, [node]),
      ).resolves.toBe(false);
    });

    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: {
        [secretName]: {
          state: "error",
          message: "Secret status could not be loaded.",
        },
      },
    });
  });

  it("does not apply a listing that names a different Project than it was asked for", async () => {
    const node = workflowNode();
    const activeGraph = graph(projectId, graphId, 4);
    api.getProjectNodeSecrets.mockResolvedValue(
      projectSecrets(graph(otherProjectId, graphId, 4), true),
    );
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
      { nodes: [node] },
    );

    await React.act(async () => {
      await expect(
        hook.result.current.refreshNodeSecretStatuses(activeGraph, [node]),
      ).resolves.toBe(false);
    });

    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: {
        [secretName]: {
          state: "error",
          message: "Secret status could not be loaded.",
        },
      },
    });
  });

  it("does not restore statuses after the active graph is cleared", async () => {
    const node = workflowNode();
    const activeGraph = graph(projectId, graphId, 2);
    const response = deferred<ProjectNodeSecrets>();
    api.getProjectNodeSecrets.mockReturnValue(response.promise);
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
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
    response.resolve(projectSecrets(activeGraph, true));

    await expect(refresh).resolves.toBe(false);
    expect(hook.result.current.nodeSecretStatuses).toEqual({});
  });

  it("does not repopulate a forgotten node when a refresh finishes", async () => {
    const node = workflowNode();
    const activeGraph = graph(projectId, graphId, 5);
    const response = deferred<ProjectNodeSecrets>();
    api.getProjectNodeSecrets.mockReturnValue(response.promise);
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
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
      response.resolve(projectSecrets(activeGraph, true));
      await expect(refresh).resolves.toBe(true);
    });
    expect(hook.result.current.nodeSecretStatuses).toEqual({});
  });

  it("refreshes unrelated nodes while preserving a concurrent secret write", async () => {
    const otherNodeId = "llm-2";
    const firstNode = workflowNode();
    const otherNode = workflowNode(savedBaseUrl, otherNodeId);
    const activeGraph = graph(projectId, graphId, 6, savedBaseUrl, [
      savedNode(),
      savedNode(savedBaseUrl, otherNodeId),
    ]);
    const refreshResponse = deferred<ProjectNodeSecrets>();
    const applyResponse = deferred<AppliedNodeSecret>();
    api.getProjectNodeSecrets
      .mockResolvedValueOnce({
        project_id: activeGraph.id,
        graph_id: activeGraph.graphId,
        head_sequence: activeGraph.revision,
        unresolved_nodes: [],
        secrets: [
          { node_id: nodeId, name: secretName, configured: false },
          { node_id: otherNodeId, name: secretName, configured: false },
        ],
      })
      .mockReturnValueOnce(refreshResponse.promise);
    api.applyNodeSecret.mockReturnValue(applyResponse.promise);
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
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
        project_id: activeGraph.id,
        graph_id: activeGraph.graphId,
        head_sequence: activeGraph.revision,
        unresolved_nodes: [],
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
    const activeGraph = graph(projectId, graphId, 7);
    api.getProjectNodeSecrets.mockResolvedValue(
      projectSecrets(activeGraph, false),
    );
    const applyResponse = deferred<AppliedNodeSecret>();
    api.applyNodeSecret.mockReturnValue(applyResponse.promise);
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
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
      workspaceId,
      activeGraph.id,
      activeGraph.graphId,
      nodeId,
      secretName,
      { value: plaintext, expected_head_sequence: activeGraph.revision },
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
    const activeGraph = graph(projectId, graphId, 4);
    api.getProjectNodeSecrets.mockResolvedValue(
      projectSecrets(activeGraph, true),
    );
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
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

  it("removes a secret at the head the listing was read at", async () => {
    const node = workflowNode();
    // The canvas was opened at head 6; the Project head has moved to 9 since.
    // The listing says so, and a write has to name 9 to land at all.
    const activeGraph = graph(projectId, graphId, 6);
    api.getProjectNodeSecrets.mockResolvedValue(
      projectSecrets(activeGraph, true, 9),
    );
    const removal = deferred<undefined>();
    api.removeNodeSecret.mockReturnValue(removal.promise);
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
      { nodes: [node] },
    );
    await React.act(async () => {
      await hook.result.current.refreshNodeSecretStatuses(activeGraph, [node]);
    });

    let removing!: Promise<boolean>;
    await React.act(() => {
      removing = hook.result.current.removeConfiguredNodeSecret(
        nodeId,
        secretName,
      );
    });

    expect(api.removeNodeSecret).toHaveBeenCalledWith(
      workspaceId,
      activeGraph.id,
      activeGraph.graphId,
      nodeId,
      secretName,
      9,
    );
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: { [secretName]: { state: "removing" } },
    });

    await React.act(async () => {
      removal.resolve(undefined);
      await expect(removing).resolves.toBe(true);
    });
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: { [secretName]: { state: "unconfigured" } },
    });
  });

  it("applies a secret whose head moved between the listing and the write", async () => {
    const node = workflowNode();
    // The canvas was opened at head 4. One accepted batch — this tab dragging a
    // node, a peer editing the same Project — moves the head to 7 without a
    // checkpoint, so the listing this token came from is the only thing that is
    // stale, and the write has to be re-addressed at 7 rather than refused.
    const activeGraph = graph(projectId, graphId, 4);
    api.getProjectNodeSecrets
      .mockResolvedValueOnce(projectSecrets(activeGraph, false))
      .mockResolvedValueOnce(projectSecrets(activeGraph, false, 7));
    api.applyNodeSecret
      .mockRejectedValueOnce(headMoved())
      .mockResolvedValueOnce(applied());
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
      { nodes: [node] },
    );
    await React.act(async () => {
      await hook.result.current.refreshNodeSecretStatuses(activeGraph, [node]);
    });

    let appliedResult = false;
    await React.act(async () => {
      appliedResult = await hook.result.current.applyConfiguredNodeSecret(
        nodeId,
        secretName,
        "sk-after-a-drag",
      );
    });

    expect(appliedResult).toBe(true);
    expect(api.applyNodeSecret).toHaveBeenNthCalledWith(
      1,
      workspaceId,
      activeGraph.id,
      activeGraph.graphId,
      nodeId,
      secretName,
      { value: "sk-after-a-drag", expected_head_sequence: 4 },
    );
    expect(api.applyNodeSecret).toHaveBeenNthCalledWith(
      2,
      workspaceId,
      activeGraph.id,
      activeGraph.graphId,
      nodeId,
      secretName,
      { value: "sk-after-a-drag", expected_head_sequence: 7 },
    );
    // The retry's token came from a listing the server answered at 7 — the only
    // source this hook will take a head from.
    expect(api.getProjectNodeSecrets).toHaveBeenCalledTimes(2);
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: { [secretName]: { state: "configured" } },
    });
  });

  it("removes a secret whose head moved between the listing and the write", async () => {
    const node = workflowNode();
    const activeGraph = graph(projectId, graphId, 6);
    api.getProjectNodeSecrets
      .mockResolvedValueOnce(projectSecrets(activeGraph, true, 9))
      .mockResolvedValueOnce(projectSecrets(activeGraph, true, 10));
    api.removeNodeSecret
      .mockRejectedValueOnce(headMoved())
      .mockResolvedValueOnce(undefined);
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
      { nodes: [node] },
    );
    await React.act(async () => {
      await hook.result.current.refreshNodeSecretStatuses(activeGraph, [node]);
    });

    let removed = false;
    await React.act(async () => {
      removed = await hook.result.current.removeConfiguredNodeSecret(
        nodeId,
        secretName,
      );
    });

    expect(removed).toBe(true);
    expect(api.removeNodeSecret).toHaveBeenNthCalledWith(
      1,
      workspaceId,
      activeGraph.id,
      activeGraph.graphId,
      nodeId,
      secretName,
      9,
    );
    expect(api.removeNodeSecret).toHaveBeenNthCalledWith(
      2,
      workspaceId,
      activeGraph.id,
      activeGraph.graphId,
      nodeId,
      secretName,
      10,
    );
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: { [secretName]: { state: "unconfigured" } },
    });
  });

  it("re-reads the listing for no other failure than a head conflict", async () => {
    const node = workflowNode();
    const activeGraph = graph(projectId, graphId, 4);
    api.getProjectNodeSecrets.mockResolvedValue(
      projectSecrets(activeGraph, false),
    );
    // 503 is the encryption key refusing to load. Retrying it at a fresh head
    // would send a value the server may already have stored.
    api.applyNodeSecret.mockRejectedValue(
      Object.assign(new Error("API error 503: node secret store unavailable"), {
        name: "ApiError",
        status: 503,
      }),
    );
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
      { nodes: [node] },
    );
    await React.act(async () => {
      await hook.result.current.refreshNodeSecretStatuses(activeGraph, [node]);
    });

    let appliedResult = true;
    await React.act(async () => {
      appliedResult = await hook.result.current.applyConfiguredNodeSecret(
        nodeId,
        secretName,
        "sk-once-only",
      );
    });

    expect(appliedResult).toBe(false);
    expect(api.applyNodeSecret).toHaveBeenCalledTimes(1);
    expect(api.getProjectNodeSecrets).toHaveBeenCalledTimes(1);
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: {
        [secretName]: {
          state: "error",
          message: "The secret could not be applied.",
        },
      },
    });
  });

  it("keeps the head a conflict revealed so the next write lands", async () => {
    const node = workflowNode();
    // The head moved to 4 and moved again before the retry could land, so this
    // attempt is reported rather than chased. What it must not do is stay stuck:
    // the listing read during recovery is the next write's token.
    const activeGraph = graph(projectId, graphId, 3);
    api.getProjectNodeSecrets
      .mockResolvedValueOnce(projectSecrets(activeGraph, false))
      .mockResolvedValueOnce(projectSecrets(activeGraph, false, 4));
    api.applyNodeSecret
      .mockRejectedValueOnce(headMoved())
      .mockRejectedValueOnce(headMoved())
      .mockResolvedValueOnce(applied());
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
      { nodes: [node] },
    );
    await React.act(async () => {
      await hook.result.current.refreshNodeSecretStatuses(activeGraph, [node]);
    });

    let firstAttempt = true;
    await React.act(async () => {
      firstAttempt = await hook.result.current.applyConfiguredNodeSecret(
        nodeId,
        secretName,
        "sk-conflicted",
      );
    });
    expect(firstAttempt).toBe(false);
    expect(api.applyNodeSecret).toHaveBeenNthCalledWith(
      2,
      workspaceId,
      activeGraph.id,
      activeGraph.graphId,
      nodeId,
      secretName,
      { value: "sk-conflicted", expected_head_sequence: 4 },
    );
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: {
        [secretName]: {
          state: "error",
          message: "The secret could not be applied.",
        },
      },
    });

    // Pressing Apply again must not need another listing: the token it holds
    // already names head 4, which is what the server answered last.
    let secondAttempt = false;
    await React.act(async () => {
      secondAttempt = await hook.result.current.applyConfiguredNodeSecret(
        nodeId,
        secretName,
        "sk-conflicted",
      );
    });
    expect(secondAttempt).toBe(true);
    expect(api.applyNodeSecret).toHaveBeenNthCalledWith(
      3,
      workspaceId,
      activeGraph.id,
      activeGraph.graphId,
      nodeId,
      secretName,
      { value: "sk-conflicted", expected_head_sequence: 4 },
    );
    expect(api.getProjectNodeSecrets).toHaveBeenCalledTimes(2);
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: { [secretName]: { state: "configured" } },
    });
  });

  it("writes no secret when no listing has told it the head to guard", async () => {
    const node = workflowNode();
    const activeGraph = graph(projectId, graphId, 3);
    api.getProjectNodeSecrets.mockRejectedValue(new Error("offline"));
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
      { nodes: [node] },
    );
    await React.act(async () => {
      await expect(
        hook.result.current.refreshNodeSecretStatuses(activeGraph, [node]),
      ).resolves.toBe(false);
    });
    expect(hook.result.current.nodeSecretStatuses).toEqual({
      [nodeId]: {
        [secretName]: {
          state: "error",
          message: "Secret status could not be loaded.",
        },
      },
    });

    // A Project head starts at 0 and the API accepts 0, so a write with no
    // listing behind it would overwrite the live document rather than fail.
    await expect(
      hook.result.current.applyConfiguredNodeSecret(nodeId, secretName, "sk-x"),
    ).resolves.toBe(false);
    await expect(
      hook.result.current.removeConfiguredNodeSecret(nodeId, secretName),
    ).resolves.toBe(false);

    expect(api.applyNodeSecret).not.toHaveBeenCalled();
    expect(api.removeNodeSecret).not.toHaveBeenCalled();
  });

  it("does not carry one Graph's head into another Graph of the same Project", async () => {
    const node = workflowNode();
    const openedGraph = graph(projectId, graphId, 5);
    const switchingGraph = graph(projectId, otherGraphId, 5);
    const switchResponse = deferred<ProjectNodeSecrets>();
    api.getProjectNodeSecrets
      .mockResolvedValueOnce(projectSecrets(openedGraph, true))
      .mockReturnValueOnce(switchResponse.promise);
    const hook = await renderHook(
      ({ nodes }: { nodes: readonly WorkflowNode[] }) =>
        useNodeSecrets(workspaceId, nodes),
      { nodes: [node] },
    );
    await React.act(async () => {
      await hook.result.current.refreshNodeSecretStatuses(openedGraph, [node]);
    });
    await React.act(() => {
      void hook.result.current.refreshNodeSecretStatuses(switchingGraph, [
        node,
      ]);
    });

    await expect(
      hook.result.current.removeConfiguredNodeSecret(nodeId, secretName),
    ).resolves.toBe(false);

    expect(api.removeNodeSecret).not.toHaveBeenCalled();
    switchResponse.resolve(projectSecrets(switchingGraph, false));
  });
});

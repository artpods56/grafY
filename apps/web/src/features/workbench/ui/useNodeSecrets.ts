"use client";

import * as React from "react";

import {
  applyNodeSecret,
  getGraphNodeSecrets,
  removeNodeSecret,
  type NodeSecretStatus,
  type SavedGraphNode,
} from "@/lib/api";
import {
  nodeSecretBindingReady,
  nodeSecretInputs,
  reconciledNodeSecretStatuses,
  type WorkflowNodeSecretStatus,
  type WorkflowNodeSecretStatuses,
} from "../canvas/node-secrets";
import { workflowNodeIsSupported } from "../canvas/types";
import type { WorkflowNode } from "../model/execution-plan";

export interface NodeSecretGraph {
  id: string;
  revision: number;
  nodes: readonly SavedGraphNode[];
}

export type NodeSecretStatusesByNode = Readonly<
  Record<string, WorkflowNodeSecretStatuses>
>;

export interface UseNodeSecretsResult {
  nodeSecretStatuses: NodeSecretStatusesByNode;
  refreshNodeSecretStatuses: (
    graph: NodeSecretGraph,
    graphNodes: readonly WorkflowNode[],
    signal?: AbortSignal,
  ) => Promise<boolean>;
  applyConfiguredNodeSecret: (
    nodeId: string,
    name: string,
    value: string,
  ) => Promise<boolean>;
  removeConfiguredNodeSecret: (
    nodeId: string,
    name: string,
  ) => Promise<boolean>;
  clearGraphSecretStatuses: () => void;
  forgetNodeSecretStatuses: (nodeId: string) => void;
}

function graphNodeSecretStatuses(
  nodes: readonly WorkflowNode[],
  remote: readonly NodeSecretStatus[],
): NodeSecretStatusesByNode {
  return Object.fromEntries(
    nodes
      .filter(
        (node) =>
          workflowNodeIsSupported(node.data) &&
          nodeSecretInputs(node.data.spec).length > 0,
      )
      .map((node) => [
        node.id,
        reconciledNodeSecretStatuses(node.data.spec, node.id, remote),
      ]),
  );
}

function nodeSecretStatusesWithState(
  nodes: readonly WorkflowNode[],
  state: WorkflowNodeSecretStatus["state"],
  message?: string,
): NodeSecretStatusesByNode {
  return Object.fromEntries(
    nodes
      .filter(
        (node) =>
          workflowNodeIsSupported(node.data) &&
          nodeSecretInputs(node.data.spec).length > 0,
      )
      .map((node) => [
        node.id,
        Object.fromEntries(
          nodeSecretInputs(node.data.spec).map((input) => [
            input.name,
            { state, message } satisfies WorkflowNodeSecretStatus,
          ]),
        ),
      ]),
  );
}

type NodeSecretWriteVersions = Map<string, Map<string, number>>;

function nodeSecretWriteVersion(
  versions: ReadonlyMap<string, ReadonlyMap<string, number>>,
  nodeId: string,
  name: string,
): number {
  return versions.get(nodeId)?.get(name) ?? 0;
}

function advanceNodeSecretWriteVersion(
  versions: NodeSecretWriteVersions,
  nodeId: string,
  name: string,
): number {
  let nodeVersions = versions.get(nodeId);
  if (!nodeVersions) {
    nodeVersions = new Map();
    versions.set(nodeId, nodeVersions);
  }
  const nextVersion = (nodeVersions.get(name) ?? 0) + 1;
  nodeVersions.set(name, nextVersion);
  return nextVersion;
}

function snapshotNodeSecretWriteVersions(
  versions: NodeSecretWriteVersions,
): NodeSecretWriteVersions {
  return new Map(
    [...versions].map(([nodeId, nodeVersions]) => [
      nodeId,
      new Map(nodeVersions),
    ]),
  );
}

function invalidateNodeSecretWrites(
  versions: NodeSecretWriteVersions,
  nodeId?: string,
): void {
  for (const [versionNodeId, nodeVersions] of versions) {
    if (nodeId !== undefined && versionNodeId !== nodeId) continue;
    for (const [name, version] of nodeVersions) {
      nodeVersions.set(name, version + 1);
    }
  }
}

function mergeRefreshStatuses(
  next: NodeSecretStatusesByNode,
  current: NodeSecretStatusesByNode,
  preserveExistingWrites: boolean,
  refreshWriteVersions: ReadonlyMap<string, ReadonlyMap<string, number>>,
  currentWriteVersions: ReadonlyMap<string, ReadonlyMap<string, number>>,
): NodeSecretStatusesByNode {
  return Object.fromEntries(
    Object.entries(next).map(([nodeId, nextNodeStatuses]) => [
      nodeId,
      Object.fromEntries(
        Object.entries(nextNodeStatuses).map(([name, nextStatus]) => {
          const currentStatus = current[nodeId]?.[name];
          const writeChanged =
            nodeSecretWriteVersion(currentWriteVersions, nodeId, name) !==
            nodeSecretWriteVersion(refreshWriteVersions, nodeId, name);
          const writeInProgress =
            preserveExistingWrites &&
            (currentStatus?.state === "applying" ||
              currentStatus?.state === "removing");
          return [
            name,
            currentStatus && (writeChanged || writeInProgress)
              ? currentStatus
              : nextStatus,
          ];
        }),
      ),
    ]),
  );
}

/** Keeps secret values write-only: only status metadata enters React state. */
export function useNodeSecrets(
  workspaceId: string,
  nodes: readonly WorkflowNode[],
): UseNodeSecretsResult {
  const [nodeSecretStatuses, setNodeSecretStatuses] =
    React.useState<NodeSecretStatusesByNode>({});
  const activeGraphRef = React.useRef<NodeSecretGraph | null>(null);
  const refreshGenerationRef = React.useRef(0);
  const writeVersionsRef = React.useRef<NodeSecretWriteVersions>(new Map());
  const nodesByIdRef = React.useRef<ReadonlyMap<string, WorkflowNode>>(
    new Map(nodes.map((node) => [node.id, node])),
  );

  React.useEffect(() => {
    nodesByIdRef.current = new Map(nodes.map((node) => [node.id, node]));
  }, [nodes]);

  const refreshNodeSecretStatuses = React.useCallback(
    async (
      graph: NodeSecretGraph,
      graphNodes: readonly WorkflowNode[],
      signal?: AbortSignal,
    ): Promise<boolean> => {
      const refreshGeneration = refreshGenerationRef.current + 1;
      refreshGenerationRef.current = refreshGeneration;
      const previousGraph = activeGraphRef.current;
      const continuesActiveGraph =
        previousGraph?.id === graph.id &&
        previousGraph.revision === graph.revision;
      if (!continuesActiveGraph) {
        invalidateNodeSecretWrites(writeVersionsRef.current);
      }
      activeGraphRef.current = graph;
      nodesByIdRef.current = new Map(graphNodes.map((node) => [node.id, node]));
      const refreshWriteVersions = snapshotNodeSecretWriteVersions(
        writeVersionsRef.current,
      );

      if (
        !graphNodes.some(
          (node) =>
            workflowNodeIsSupported(node.data) &&
            nodeSecretInputs(node.data.spec).length > 0,
        )
      ) {
        setNodeSecretStatuses({});
        return true;
      }

      const loadingStatuses = nodeSecretStatusesWithState(
        graphNodes,
        "loading",
      );
      setNodeSecretStatuses((current) =>
        mergeRefreshStatuses(
          loadingStatuses,
          current,
          continuesActiveGraph,
          refreshWriteVersions,
          writeVersionsRef.current,
        ),
      );
      try {
        const response = await getGraphNodeSecrets(
          workspaceId,
          graph.id,
          signal,
        );
        if (
          refreshGenerationRef.current !== refreshGeneration ||
          activeGraphRef.current?.id !== graph.id ||
          activeGraphRef.current.revision !== graph.revision
        ) {
          return false;
        }
        if (
          response.graph_id !== graph.id ||
          response.graph_revision !== graph.revision
        ) {
          throw new Error("Node secret status revision mismatch");
        }
        const refreshedStatuses = graphNodeSecretStatuses(
          [...nodesByIdRef.current.values()],
          response.secrets,
        );
        setNodeSecretStatuses((current) =>
          mergeRefreshStatuses(
            refreshedStatuses,
            current,
            continuesActiveGraph,
            refreshWriteVersions,
            writeVersionsRef.current,
          ),
        );
        return true;
      } catch {
        if (
          signal?.aborted ||
          refreshGenerationRef.current !== refreshGeneration ||
          activeGraphRef.current?.id !== graph.id ||
          activeGraphRef.current.revision !== graph.revision
        ) {
          return false;
        }
        const errorStatuses = nodeSecretStatusesWithState(
          [...nodesByIdRef.current.values()],
          "error",
          "Secret status could not be loaded.",
        );
        setNodeSecretStatuses((current) =>
          mergeRefreshStatuses(
            errorStatuses,
            current,
            continuesActiveGraph,
            refreshWriteVersions,
            writeVersionsRef.current,
          ),
        );
        return false;
      }
    },
    [workspaceId],
  );

  const applyConfiguredNodeSecret = React.useCallback(
    async (nodeId: string, name: string, value: string): Promise<boolean> => {
      const graph = activeGraphRef.current;
      if (!graph) return false;
      const node = nodesByIdRef.current.get(nodeId);
      const input =
        node && workflowNodeIsSupported(node.data)
          ? nodeSecretInputs(node.data.spec).find(
              (candidate) => candidate.name === name,
            )
          : undefined;
      const savedNode = graph.nodes.find(
        (candidate) => candidate.id === nodeId,
      );
      if (
        !node ||
        !input ||
        !nodeSecretBindingReady(
          input,
          {
            id: node.id,
            operator_id: node.data.spec.operator_id,
            operator_version: node.data.spec.operator_version,
            config: node.data.config,
          },
          savedNode,
        )
      ) {
        return false;
      }

      const writeVersion = advanceNodeSecretWriteVersion(
        writeVersionsRef.current,
        nodeId,
        name,
      );
      setNodeSecretStatuses((current) => ({
        ...current,
        [nodeId]: {
          ...(current[nodeId] ?? {}),
          [name]: { state: "applying" },
        },
      }));
      try {
        const response = await applyNodeSecret(
          workspaceId,
          graph.id,
          nodeId,
          name,
          {
            value,
            expected_graph_revision: graph.revision,
          },
        );
        if (
          response.node_id !== nodeId ||
          response.name !== name ||
          response.configured !== true
        ) {
          throw new Error("Node secret response mismatch");
        }
        if (
          activeGraphRef.current?.id !== graph.id ||
          activeGraphRef.current.revision !== graph.revision ||
          nodeSecretWriteVersion(writeVersionsRef.current, nodeId, name) !==
            writeVersion
        ) {
          return true;
        }
        advanceNodeSecretWriteVersion(writeVersionsRef.current, nodeId, name);
        setNodeSecretStatuses((current) => ({
          ...current,
          [nodeId]: {
            ...(current[nodeId] ?? {}),
            [name]: { state: "configured" },
          },
        }));
        return true;
      } catch {
        if (
          activeGraphRef.current?.id === graph.id &&
          activeGraphRef.current.revision === graph.revision &&
          nodeSecretWriteVersion(writeVersionsRef.current, nodeId, name) ===
            writeVersion
        ) {
          advanceNodeSecretWriteVersion(writeVersionsRef.current, nodeId, name);
          setNodeSecretStatuses((current) => ({
            ...current,
            [nodeId]: {
              ...(current[nodeId] ?? {}),
              [name]: {
                state: "error",
                message: "The secret could not be applied.",
              },
            },
          }));
        }
        return false;
      }
    },
    [workspaceId],
  );

  const removeConfiguredNodeSecret = React.useCallback(
    async (nodeId: string, name: string): Promise<boolean> => {
      const graph = activeGraphRef.current;
      if (!graph) return false;
      const node = nodesByIdRef.current.get(nodeId);
      const input =
        node && workflowNodeIsSupported(node.data)
          ? nodeSecretInputs(node.data.spec).find(
              (candidate) => candidate.name === name,
            )
          : undefined;
      const savedNode = graph.nodes.find(
        (candidate) => candidate.id === nodeId,
      );
      if (
        !node ||
        !input ||
        !nodeSecretBindingReady(
          input,
          {
            id: node.id,
            operator_id: node.data.spec.operator_id,
            operator_version: node.data.spec.operator_version,
            config: node.data.config,
          },
          savedNode,
        )
      ) {
        return false;
      }

      const writeVersion = advanceNodeSecretWriteVersion(
        writeVersionsRef.current,
        nodeId,
        name,
      );
      setNodeSecretStatuses((current) => ({
        ...current,
        [nodeId]: {
          ...(current[nodeId] ?? {}),
          [name]: { state: "removing" },
        },
      }));
      try {
        await removeNodeSecret(
          workspaceId,
          graph.id,
          nodeId,
          name,
          graph.revision,
        );
        if (
          activeGraphRef.current?.id !== graph.id ||
          activeGraphRef.current.revision !== graph.revision ||
          nodeSecretWriteVersion(writeVersionsRef.current, nodeId, name) !==
            writeVersion
        ) {
          return true;
        }
        advanceNodeSecretWriteVersion(writeVersionsRef.current, nodeId, name);
        setNodeSecretStatuses((current) => ({
          ...current,
          [nodeId]: {
            ...(current[nodeId] ?? {}),
            [name]: { state: "unconfigured" },
          },
        }));
        return true;
      } catch {
        if (
          activeGraphRef.current?.id === graph.id &&
          activeGraphRef.current.revision === graph.revision &&
          nodeSecretWriteVersion(writeVersionsRef.current, nodeId, name) ===
            writeVersion
        ) {
          advanceNodeSecretWriteVersion(writeVersionsRef.current, nodeId, name);
          setNodeSecretStatuses((current) => ({
            ...current,
            [nodeId]: {
              ...(current[nodeId] ?? {}),
              [name]: {
                state: "error",
                message: "The stored secret could not be removed.",
              },
            },
          }));
        }
        return false;
      }
    },
    [workspaceId],
  );

  const clearGraphSecretStatuses = React.useCallback(() => {
    refreshGenerationRef.current += 1;
    invalidateNodeSecretWrites(writeVersionsRef.current);
    activeGraphRef.current = null;
    setNodeSecretStatuses({});
  }, []);

  const forgetNodeSecretStatuses = React.useCallback((nodeId: string) => {
    invalidateNodeSecretWrites(writeVersionsRef.current, nodeId);
    const remainingNodes = new Map(nodesByIdRef.current);
    remainingNodes.delete(nodeId);
    nodesByIdRef.current = remainingNodes;
    setNodeSecretStatuses((current) =>
      Object.fromEntries(
        Object.entries(current).filter(([id]) => id !== nodeId),
      ),
    );
  }, []);

  return {
    nodeSecretStatuses,
    refreshNodeSecretStatuses,
    applyConfiguredNodeSecret,
    removeConfiguredNodeSecret,
    clearGraphSecretStatuses,
    forgetNodeSecretStatuses,
  };
}

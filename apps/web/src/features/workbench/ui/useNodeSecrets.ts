"use client";

import * as React from "react";

import {
  applyNodeSecret,
  getProjectNodeSecrets,
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

/**
 * The secrets of one Graph, addressed the way the API addresses them: the Project
 * whose head holds the Graph document, and the Graph inside that Project whose
 * nodes declare the secrets. A Node Execution Secret is written into the
 * Project's document, so a write is guarded by the Project head's
 * collaboration_sequence — and a Project id is never a Graph id.
 */
export interface NodeSecretGraph {
  /** The Project that holds the Graph. Not a Graph id. */
  id: string;
  /** The Graph inside that Project, named separately. */
  graphId: string;
  /** The Project head's collaboration_sequence this Graph was read at. */
  revision: number;
  nodes: readonly SavedGraphNode[];
}

export type NodeSecretStatusesByNode = Readonly<
  Record<string, WorkflowNodeSecretStatuses>
>;

/**
 * The head a secret write was read against. Only a listing can establish one:
 * the Project head's first sequence is 0 and the API accepts 0 as a real
 * expectation, so no number may be invented for a write that never read.
 */
interface NodeSecretHead {
  readonly projectId: string;
  readonly graphId: string;
  readonly sequence: number;
}

/** A write that passed every guard, with the identity and version it claims. */
interface SecretWriteTarget {
  readonly graph: NodeSecretGraph;
  readonly headSequence: number;
  readonly writeVersion: number;
}

function sameNodeSecretGraph(
  graph: NodeSecretGraph,
  active: NodeSecretGraph | null,
): boolean {
  return (
    active !== null &&
    graph.id === active.id &&
    graph.graphId === active.graphId &&
    graph.revision === active.revision
  );
}

function guardedHeadSequence(
  head: NodeSecretHead | null,
  graph: NodeSecretGraph,
): number | null {
  if (head === null) return null;
  if (head.projectId !== graph.id || head.graphId !== graph.graphId) {
    return null;
  }
  return head.sequence;
}

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
  const headRef = React.useRef<NodeSecretHead | null>(null);
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
      // A Graph switch inside the same Project keeps the Project id, so identity
      // has to read all three: Project, Graph, and the head it was opened at.
      const continuesActiveGraph = sameNodeSecretGraph(graph, previousGraph);
      if (!continuesActiveGraph) {
        invalidateNodeSecretWrites(writeVersionsRef.current);
        headRef.current = null;
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
        const response = await getProjectNodeSecrets(
          workspaceId,
          graph.id,
          graph.graphId,
          signal,
        );
        if (
          refreshGenerationRef.current !== refreshGeneration ||
          !sameNodeSecretGraph(graph, activeGraphRef.current)
        ) {
          return false;
        }
        if (
          response.project_id !== graph.id ||
          response.graph_id !== graph.graphId
        ) {
          throw new Error("Node secret status identity mismatch");
        }
        // The listing names the head it was read at. That is the sequence a later
        // write must claim: newer than whatever the caller opened the Graph at,
        // and the only number here that came from the server.
        headRef.current = {
          projectId: graph.id,
          graphId: graph.graphId,
          sequence: response.head_sequence,
        };
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
          !sameNodeSecretGraph(graph, activeGraphRef.current)
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

  /**
   * What a secret write should claim: the active Graph, the head its listing was
   * read at, and a fresh write version. Null when there is nothing to write
   * against — no active Graph, no head this client ever read (a write that
   * cannot name one would overwrite a newer document, and the API would believe
   * any number it was handed), or a node whose secret binding no longer holds.
   */
  const prepareSecretWrite = React.useCallback(
    (nodeId: string, name: string): SecretWriteTarget | null => {
      const graph = activeGraphRef.current;
      if (!graph) return null;
      const headSequence = guardedHeadSequence(headRef.current, graph);
      if (headSequence === null) return null;
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
        return null;
      }
      return {
        graph,
        headSequence,
        writeVersion: advanceNodeSecretWriteVersion(
          writeVersionsRef.current,
          nodeId,
          name,
        ),
      };
    },
    [],
  );

  const applyConfiguredNodeSecret = React.useCallback(
    async (nodeId: string, name: string, value: string): Promise<boolean> => {
      const target = prepareSecretWrite(nodeId, name);
      if (!target) return false;
      const { graph, headSequence, writeVersion } = target;
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
          graph.graphId,
          nodeId,
          name,
          {
            value,
            expected_head_sequence: headSequence,
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
          !sameNodeSecretGraph(graph, activeGraphRef.current) ||
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
          sameNodeSecretGraph(graph, activeGraphRef.current) &&
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
    [prepareSecretWrite, workspaceId],
  );

  const removeConfiguredNodeSecret = React.useCallback(
    async (nodeId: string, name: string): Promise<boolean> => {
      const target = prepareSecretWrite(nodeId, name);
      if (!target) return false;
      const { graph, headSequence, writeVersion } = target;
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
          graph.graphId,
          nodeId,
          name,
          headSequence,
        );
        if (
          !sameNodeSecretGraph(graph, activeGraphRef.current) ||
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
          sameNodeSecretGraph(graph, activeGraphRef.current) &&
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
    [prepareSecretWrite, workspaceId],
  );

  const clearGraphSecretStatuses = React.useCallback(() => {
    refreshGenerationRef.current += 1;
    invalidateNodeSecretWrites(writeVersionsRef.current);
    headRef.current = null;
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

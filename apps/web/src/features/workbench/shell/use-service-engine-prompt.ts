"use client";

import * as React from "react";

import type { Credential, NodeRegistry, NodeSpec } from "@/lib/api";
import { useEffectReducer } from "@/lib/state/use-effect-reducer";
import { createUuid } from "@/features/workbench/authoring/uuid";

import type {
  AuthoredGraphOrigin,
  GraphCommand,
} from "../authoring/graph-document";
import { catalogNodeSpecs } from "../authoring/node-catalog";
import type { NodeCredentialController } from "../authoring/node-secrets";
import type { WorkflowNodeSecretStatuses } from "../authoring/node-secrets";
import {
  boundWorkspaceKeyNotice,
  partitionPendingBindings,
  settleBindingFailure,
  workspaceKeyBindFailedNotice,
  type QueuedSharedBinding,
} from "../authoring/pending-shared-binding";
import {
  initialServiceEnginePromptState,
  serviceEnginePromptReducer,
  type ServiceEngineConsumer,
  type ServiceEnginePromptEffect,
  type ServiceEngineWorld,
} from "../authoring/service-engine-prompt";
import {
  portMetaForPort,
  type WorkflowEdge,
  type WorkflowNode,
} from "../authoring/types";
import type { ContextualDiscoverySession } from "../cell-canvas/ContextualNodeDiscovery";
import type { CellCanvasViewportHandle } from "../cell-canvas/CellCanvas";
import type { ContextualRouteChoice } from "../authoring/node-catalog";

export interface EngineConnectNoticeState {
  readonly lead: string;
  readonly undoNodeId: string;
  readonly consumerNodeId: string;
}

export interface LocalEnginePlacement {
  readonly id: string;
  readonly position: { readonly x: number; readonly y: number };
  readonly spec: NodeSpec;
  readonly satisfiedInputs: readonly string[];
}

function draftIds() {
  return { nodeId: `node-${createUuid()}`, edgeId: `edge-${createUuid()}` };
}

function satisfiedInputNames(
  nodeId: string,
  edges: readonly WorkflowEdge[],
  origins: readonly AuthoredGraphOrigin[],
): string[] {
  const names = new Set<string>();
  for (const edge of edges) {
    if (edge.data?.enabled === false || edge.target !== nodeId) continue;
    names.add(edge.targetPort);
  }
  for (const origin of origins) {
    if (origin.to_node === nodeId) names.add(origin.to_port);
  }
  return [...names];
}

function deploymentDefaults(
  nodes: readonly WorkflowNode[],
  statuses: Readonly<Record<string, WorkflowNodeSecretStatuses>>,
): ServiceEngineWorld["vault"]["deploymentDefaults"] {
  const defaults: { operatorId: string; secretName: string }[] = [];
  for (const node of nodes) {
    const nodeStatuses = statuses[node.id];
    if (!nodeStatuses) continue;
    for (const [secretName, status] of Object.entries(nodeStatuses)) {
      if (!status.remote?.deployment_default_available) continue;
      defaults.push({
        operatorId: node.data.spec.operator_id,
        secretName,
      });
    }
  }
  return defaults;
}

function fallbackAnchor(): { x: number; y: number } {
  if (typeof window === "undefined") return { x: 0, y: 0 };
  return { x: window.innerWidth / 2, y: 120 };
}

/**
 * React host for the engine prompt. The reducer decides; this applies the
 * authoring batch, the shared-key write, and the selection hand-off.
 */
export function useServiceEnginePrompt({
  graphId,
  canEdit,
  running,
  nodes,
  savedNodes,
  edges,
  origins,
  registry,
  credentials,
  nodeSecretStatuses,
  canEditProject,
  applyAuthoringCommands,
  selectNode,
  selectCredential,
  openDiscovery,
  closeDiscovery,
  viewportHandle,
  onRejected,
  clearError,
}: {
  graphId: string | null;
  canEdit: boolean;
  running: boolean;
  nodes: readonly WorkflowNode[];
  /** Nodes on the saved head. Null until this graph has a checkpoint. */
  savedNodes: readonly { readonly id: string }[] | null;
  edges: readonly WorkflowEdge[];
  origins: readonly AuthoredGraphOrigin[];
  registry: NodeRegistry | null | undefined;
  credentials: readonly Credential[];
  nodeSecretStatuses: Readonly<Record<string, WorkflowNodeSecretStatuses>>;
  canEditProject: boolean;
  applyAuthoringCommands: (commands: readonly GraphCommand[]) => void;
  selectNode: (nodeId: string) => void;
  selectCredential: NodeCredentialController["selectCredential"];
  openDiscovery: (session: ContextualDiscoverySession) => void;
  closeDiscovery: () => void;
  viewportHandle: CellCanvasViewportHandle | null;
  onRejected: (message: string) => void;
  clearError: () => void;
}) {
  const nodesRef = React.useRef(nodes);
  const edgesRef = React.useRef(edges);
  const originsRef = React.useRef(origins);
  const viewportRef = React.useRef(viewportHandle);
  const applyRef = React.useRef(applyAuthoringCommands);
  const selectNodeRef = React.useRef(selectNode);
  const selectCredentialRef = React.useRef(selectCredential);
  const openDiscoveryRef = React.useRef(openDiscovery);
  const closeDiscoveryRef = React.useRef(closeDiscovery);
  const onRejectedRef = React.useRef(onRejected);
  const clearErrorRef = React.useRef(clearError);
  const [notice, setNotice] = React.useState<EngineConnectNoticeState | null>(
    null,
  );
  const noticeRef = React.useRef(notice);
  const graphIdRef = React.useRef(graphId);
  const pendingRef = React.useRef<QueuedSharedBinding[]>([]);
  const writingKeysRef = React.useRef<Set<string>>(new Set());
  const bindingGenerationRef = React.useRef(0);
  const graphSeenRef = React.useRef(graphId);
  const expectedLabelsRef = React.useRef<Map<string, readonly string[]>>(
    new Map(),
  );
  const completedCountRef = React.useRef<Map<string, number>>(new Map());
  const failedNodeIdsRef = React.useRef<Set<string>>(new Set());
  const [noticeGraphId, setNoticeGraphId] = React.useState(graphId);
  if (noticeGraphId !== graphId) {
    setNoticeGraphId(graphId);
    setNotice(null);
  }

  const runEffect = React.useCallback(
    (
      effect: ServiceEnginePromptEffect,
      dispatch: React.Dispatch<
        Parameters<typeof serviceEnginePromptReducer>[1]
      >,
    ) => {
      switch (effect.type) {
        case "close_prompt":
          closeDiscoveryRef.current();
          return;
        case "open_prompt": {
          const node = nodesRef.current.find(
            (candidate) => candidate.id === effect.consumerNodeId,
          );
          const port = node?.data.spec.inputs.find(
            (candidate) => candidate.name === effect.servicePortName,
          );
          if (!port || port.direction !== "input" || port.kind !== "service") {
            dispatch({ type: "prompt_closed" });
            return;
          }
          let meta;
          try {
            meta = portMetaForPort(port);
          } catch {
            dispatch({ type: "prompt_closed" });
            return;
          }
          const screen = viewportRef.current?.worldToScreen(
            effect.flowPosition,
          );
          openDiscoveryRef.current({
            graphId: effect.graphId,
            sourceNodeId: effect.consumerNodeId,
            sourceEndpoint: {
              kind: "port",
              portName: effect.servicePortName,
              direction: "input",
              meta,
            },
            sourcePortTitle: effect.portTitle,
            direction: "upstream",
            clientAnchor: screen ?? fallbackAnchor(),
            flowPosition: effect.flowPosition,
            candidates: effect.candidates,
            trigger: "port_prompt",
            engineRows: effect.rows,
          });
          return;
        }
        case "connect_provider": {
          const edge = effect.commands.find(
            (command) => command.kind === "add_edge",
          );
          if (
            edge?.kind === "add_edge" &&
            edgesRef.current.some(
              (existing) =>
                existing.data?.enabled !== false &&
                existing.target === edge.edge.to_node &&
                existing.targetPort === edge.edge.to_port,
            )
          ) {
            onRejectedRef.current(
              "This input is already connected or no longer accepts this connection.",
            );
            return;
          }
          applyRef.current(effect.commands);
          selectNodeRef.current(effect.selectNodeId);
          clearErrorRef.current();
          setNotice({
            lead: effect.toast,
            undoNodeId: effect.undoNodeId,
            consumerNodeId: effect.consumerNodeId,
          });
          if (effect.bindings.length > 0) {
            expectedLabelsRef.current.set(
              effect.undoNodeId,
              effect.bindings.map((binding) => binding.label),
            );
            completedCountRef.current.set(effect.undoNodeId, 0);
            failedNodeIdsRef.current.delete(effect.undoNodeId);
            const queued: QueuedSharedBinding[] = effect.bindings.map(
              (binding) => ({
                nodeId: effect.undoNodeId,
                secretName: binding.secretName,
                credentialId: binding.credentialId,
                providerTitle: effect.providerTitle,
                credentialLabel: binding.label,
                graphId: effect.graphId,
                saveAttempts: 0,
              }),
            );
            pendingRef.current = [
              ...pendingRef.current.filter(
                (item) => item.nodeId !== effect.undoNodeId,
              ),
              ...queued,
            ];
          }
          return;
        }
        default: {
          const exhaustive: never = effect;
          return exhaustive;
        }
      }
    },
    [],
  );

  const [state, dispatch] = useEffectReducer(
    serviceEnginePromptReducer,
    initialServiceEnginePromptState,
    runEffect,
    { flush: "sync" },
  );

  React.useLayoutEffect(() => {
    nodesRef.current = nodes;
    edgesRef.current = edges;
    originsRef.current = origins;
    viewportRef.current = viewportHandle;
    applyRef.current = applyAuthoringCommands;
    selectNodeRef.current = selectNode;
    selectCredentialRef.current = selectCredential;
    openDiscoveryRef.current = openDiscovery;
    closeDiscoveryRef.current = closeDiscovery;
    onRejectedRef.current = onRejected;
    clearErrorRef.current = clearError;
    noticeRef.current = notice;
    graphIdRef.current = graphId;
  });

  const bindingStillCurrent = React.useCallback(
    (binding: QueuedSharedBinding, generation: number) =>
      bindingGenerationRef.current === generation &&
      graphIdRef.current === binding.graphId &&
      !failedNodeIdsRef.current.has(binding.nodeId),
    [],
  );

  const nodeBindingBusy = React.useCallback((nodeId: string) => {
    if (pendingRef.current.some((item) => item.nodeId === nodeId)) return true;
    const prefix = `${nodeId}\0`;
    for (const key of writingKeysRef.current) {
      if (key.startsWith(prefix)) return true;
    }
    return false;
  }, []);

  const startWrite = React.useCallback(
    (binding: QueuedSharedBinding) => {
      const key = `${binding.nodeId}\0${binding.secretName}`;
      if (writingKeysRef.current.has(key)) return;
      writingKeysRef.current.add(key);
      const generation = bindingGenerationRef.current;
      void selectCredentialRef
        .current(binding.nodeId, binding.secretName, {
          scope: "shared",
          binding: {
            mode: "credential",
            credential_id: binding.credentialId,
          },
        })
        .then(
          () => {
            writingKeysRef.current.delete(key);
            if (!bindingStillCurrent(binding, generation)) return;
            const labels = expectedLabelsRef.current.get(binding.nodeId);
            if (!labels) return;
            const completed =
              (completedCountRef.current.get(binding.nodeId) ?? 0) + 1;
            completedCountRef.current.set(binding.nodeId, completed);
            if (
              nodeBindingBusy(binding.nodeId) ||
              completed !== labels.length
            ) {
              return;
            }
            const lead = boundWorkspaceKeyNotice(binding.providerTitle, labels);
            setNotice((current) => {
              if (!current || current.undoNodeId !== binding.nodeId) {
                return current;
              }
              return { ...current, lead };
            });
          },
          (error: unknown) => {
            writingKeysRef.current.delete(key);
            if (
              bindingGenerationRef.current !== generation ||
              graphIdRef.current !== binding.graphId
            ) {
              return;
            }
            const settled = settleBindingFailure(error, binding.saveAttempts);
            if (settled.type === "retry") {
              if (failedNodeIdsRef.current.has(binding.nodeId)) return;
              pendingRef.current = [
                ...pendingRef.current,
                { ...binding, saveAttempts: settled.saveAttempts },
              ];
              return;
            }
            failedNodeIdsRef.current.add(binding.nodeId);
            pendingRef.current = pendingRef.current.filter(
              (item) => item.nodeId !== binding.nodeId,
            );
            onRejectedRef.current(settled.message);
            const lead = workspaceKeyBindFailedNotice(
              binding.providerTitle,
              settled.message,
            );
            setNotice((current) => {
              if (!current || current.undoNodeId !== binding.nodeId) {
                return current;
              }
              return { ...current, lead };
            });
          },
        );
    },
    [bindingStillCurrent, nodeBindingBusy],
  );

  React.useEffect(() => {
    if (graphSeenRef.current !== graphId) {
      graphSeenRef.current = graphId;
      bindingGenerationRef.current += 1;
      pendingRef.current = [];
      expectedLabelsRef.current.clear();
      completedCountRef.current.clear();
      failedNodeIdsRef.current.clear();
    }
    // The secret listing is read so this effect retries a save-first
    // rejection once the head sequence arrives. The partition itself only
    // cares that the provider id is on the saved head.
    void nodeSecretStatuses;
    const partitioned = partitionPendingBindings({
      pending: pendingRef.current,
      graphId,
      canvasNodeIds: new Set(nodes.map((node) => node.id)),
      savedNodeIds: new Set((savedNodes ?? []).map((node) => node.id)),
    });
    pendingRef.current = [...partitioned.waiting];
    for (const binding of partitioned.ready) startWrite(binding);
  }, [graphId, nodes, nodeSecretStatuses, savedNodes, startWrite]);

  const world = React.useMemo<ServiceEngineWorld | null>(() => {
    if (!registry) return null;
    return {
      registry,
      catalogNodes: catalogNodeSpecs(registry),
      vault: {
        canEditProject,
        credentials: credentials.map((credential) => ({
          id: credential.id,
          label: credential.label,
          providerKind: credential.provider_kind,
          scope: credential.scope,
        })),
        deploymentDefaults: deploymentDefaults(nodes, nodeSecretStatuses),
      },
    };
  }, [canEditProject, credentials, nodeSecretStatuses, nodes, registry]);

  React.useLayoutEffect(() => {
    dispatch({
      type: "gates",
      graphId: graphId ?? "",
      canEdit,
      running,
    });
  }, [canEdit, dispatch, graphId, running]);

  React.useLayoutEffect(() => {
    if (state.phase !== "awaiting_placement") return;
    if ((graphId ?? "") !== state.graphId || !canEdit || running) return;
    const node = nodes.find(
      (candidate) => candidate.id === state.consumerNodeId,
    );
    dispatch({
      type: "placement_committed",
      graphId: graphId ?? "",
      canEdit,
      running,
      consumer: node
        ? {
            id: node.id,
            position: node.position,
            spec: node.data.spec,
            satisfiedInputs: satisfiedInputNames(node.id, edges, origins),
          }
        : null,
      world,
      draftIds: draftIds(),
    });
  }, [
    canEdit,
    dispatch,
    edges,
    graphId,
    nodes,
    origins,
    running,
    state,
    world,
  ]);

  const noteLocalPlacement = React.useCallback(
    (placement: LocalEnginePlacement) => {
      if (!graphId) return;
      dispatch({
        type: "local_placement",
        origin: "node_selector",
        graphId,
        canEdit,
        running,
        consumer: {
          id: placement.id,
          position: placement.position,
          spec: placement.spec,
          satisfiedInputs: placement.satisfiedInputs,
        },
      });
    },
    [canEdit, dispatch, graphId, running],
  );

  const noteContinuedNode = React.useCallback(
    (placement: LocalEnginePlacement) => {
      if (!graphId) return;
      dispatch({
        type: "local_placement",
        origin: "continue_from_port",
        graphId,
        canEdit,
        running,
        consumer: {
          id: placement.id,
          position: placement.position,
          spec: placement.spec,
          satisfiedInputs: placement.satisfiedInputs,
        },
      });
    },
    [canEdit, dispatch, graphId, running],
  );

  const pickEngine = React.useCallback(
    (nodeId: string, portName: string) => {
      if (!graphId) return;
      const node = nodesRef.current.find(
        (candidate) => candidate.id === nodeId,
      );
      if (!node) return;
      const consumer: ServiceEngineConsumer = {
        id: node.id,
        position: node.position,
        spec: node.data.spec,
        satisfiedInputs: satisfiedInputNames(
          node.id,
          edgesRef.current,
          originsRef.current,
        ),
      };
      dispatch({
        type: "pick_engine",
        graphId,
        canEdit,
        running,
        consumer,
        portName,
        world,
        draftIds: draftIds(),
        openPicker: true,
      });
    },
    [canEdit, dispatch, graphId, running, world],
  );

  const chooseProvider = React.useCallback(
    (spec: NodeSpec, choice: ContextualRouteChoice) => {
      if (!graphId || !world) return;
      dispatch({
        type: "provider_chosen",
        graphId,
        canEdit,
        running,
        spec,
        choice,
        world,
        draftIds: draftIds(),
      });
    },
    [canEdit, dispatch, graphId, running, world],
  );

  const closePrompt = React.useCallback(() => {
    dispatch({ type: "prompt_closed" });
  }, [dispatch]);

  const dismissNotice = React.useCallback(() => {
    setNotice(null);
  }, []);

  const undoNotice = React.useCallback(() => {
    const current = noticeRef.current;
    if (!current) return;
    // The provider was a second batch. Removing it drops its edge and leaves
    // the consumer the person just placed.
    applyRef.current([
      { kind: "remove_nodes", node_ids: [current.undoNodeId] },
    ]);
    selectNodeRef.current(current.consumerNodeId);
    pendingRef.current = pendingRef.current.filter(
      (item) => item.nodeId !== current.undoNodeId,
    );
    bindingGenerationRef.current += 1;
    expectedLabelsRef.current.delete(current.undoNodeId);
    completedCountRef.current.delete(current.undoNodeId);
    failedNodeIdsRef.current.delete(current.undoNodeId);
    setNotice(null);
  }, []);

  return {
    notice,
    dismissNotice,
    undoNotice,
    noteLocalPlacement,
    noteContinuedNode,
    pickEngine,
    chooseProvider,
    closePrompt,
  };
}

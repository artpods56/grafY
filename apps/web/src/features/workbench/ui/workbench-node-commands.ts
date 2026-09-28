import * as React from "react";

import type { ArtifactTypeKey } from "@/lib/api";

import type { ArtifactViewerCanvasState } from "../canvas/artifact-viewer";
import { withoutViewerEdgesFrom } from "../canvas/artifact-viewer-edits";
import { appendInputPlug } from "../canvas/input-plugs";
import type { ArtifactQueryRelation } from "../canvas/query-artifact-tables";
import type { SchemaBuilderField } from "../canvas/schema-builder";
import type { WorkflowNodeConfig, WorkflowInputPlug } from "../canvas/types";
import type { GraphCommand } from "../model/graph-document";
import type { PendingConnectionRoute } from "./ConnectionRouteDialog";

/** The part of a canvas node these gestures touch: its plugs and its configuration. */
type NodeSubject = {
  readonly id: string;
  readonly data: {
    readonly config: WorkflowNodeConfig;
    readonly inputPlugs: readonly WorkflowInputPlug[];
  };
};

/** The part of a canvas edge these gestures touch: which node it joins. */
type EdgeSubject = { readonly source: string; readonly target: string };

export type NodeCommandDeps = {
  nodes: readonly NodeSubject[];
  edges: readonly EdgeSubject[];
  applyAuthoringCommands: (commands: readonly GraphCommand[]) => void;
  commitArtifactViewers: (
    updater: (current: ArtifactViewerCanvasState) => ArtifactViewerCanvasState,
  ) => void;
  forgetNodeSecretStatuses: (nodeId: string) => void;
  setPendingConnectionRoute: React.Dispatch<
    React.SetStateAction<PendingConnectionRoute | null>
  >;
  setRunError: React.Dispatch<React.SetStateAction<string | null>>;
};

/**
 * Card and node gestures that rewrite one workflow node: delete it, add or reorder an
 * input plug, rewrite a schema builder or artifact-query configuration, or rebind an
 * artifact type.
 *
 * Each one ends in the same place, an authoring command, and each one clears the pending
 * connection route and the visible run error afterwards, because the thing the user was
 * connecting to has just changed.
 */
export function useNodeCommands(deps: NodeCommandDeps) {
  const {
    applyAuthoringCommands,
    commitArtifactViewers,
    edges,
    forgetNodeSecretStatuses,
    nodes,
    setPendingConnectionRoute,
    setRunError,
  } = deps;

  const hasIncidentEdges = React.useCallback(
    (nodeId: string) =>
      edges.some((edge) => edge.source === nodeId || edge.target === nodeId),
    [edges],
  );

  const updateConfigurationAndInputPlugs = React.useCallback(
    (
      nodeId: string,
      inputPlugs: readonly WorkflowInputPlug[],
      configuration: (config: WorkflowNodeConfig) => WorkflowNodeConfig,
    ) => {
      const node = nodes.find((candidate) => candidate.id === nodeId);
      if (!node) return;
      applyAuthoringCommands([
        {
          kind: "update_node_configuration_and_input_plugs",
          node_id: nodeId,
          config: configuration(node.data.config),
          input_plugs: inputPlugs.map((plug) => ({
            id: plug.id,
            port: plug.portName,
          })),
        },
      ]);
      setPendingConnectionRoute(null);
      setRunError(null);
    },
    [applyAuthoringCommands, nodes, setPendingConnectionRoute, setRunError],
  );

  const removeNode = React.useCallback(
    (nodeId: string) => {
      applyAuthoringCommands([{ kind: "remove_nodes", node_ids: [nodeId] }]);
      commitArtifactViewers((current) =>
        withoutViewerEdgesFrom(current, nodeId),
      );
      forgetNodeSecretStatuses(nodeId);
      setPendingConnectionRoute(null);
      setRunError(null);
    },
    [
      applyAuthoringCommands,
      commitArtifactViewers,
      forgetNodeSecretStatuses,
      setPendingConnectionRoute,
      setRunError,
    ],
  );

  const addNodeInputPlug = React.useCallback(
    (nodeId: string, portName: string) => {
      const node = nodes.find((candidate) => candidate.id === nodeId);
      if (!node) return;
      const inputPlugs = appendInputPlug(node.data.inputPlugs, portName);
      const plug = inputPlugs[inputPlugs.length - 1];
      if (!plug) return;
      applyAuthoringCommands([
        {
          kind: "add_input_plug",
          node_id: nodeId,
          plug: { id: plug.id, port: plug.portName },
        },
      ]);
    },
    [applyAuthoringCommands, nodes],
  );

  const removeNodeInputPlug = React.useCallback(
    (nodeId: string, plugId: string) => {
      applyAuthoringCommands([
        {
          kind: "remove_input_plug",
          node_id: nodeId,
          plug_id: plugId,
        },
      ]);
      setPendingConnectionRoute(null);
      setRunError(null);
    },
    [applyAuthoringCommands, setPendingConnectionRoute, setRunError],
  );

  const reorderNodeInputPlug = React.useCallback(
    (nodeId: string, portName: string, plugId: string, toIndex: number) => {
      applyAuthoringCommands([
        {
          kind: "reorder_input_plug",
          node_id: nodeId,
          port: portName,
          plug_id: plugId,
          to_index: toIndex,
        },
      ]);
    },
    [applyAuthoringCommands],
  );

  const updateSchemaBuilderFields = React.useCallback(
    (
      nodeId: string,
      fields: readonly SchemaBuilderField[],
      inputPlugs: readonly WorkflowInputPlug[],
    ) => {
      updateConfigurationAndInputPlugs(nodeId, inputPlugs, (config) => ({
        ...config,
        fields,
      }));
    },
    [updateConfigurationAndInputPlugs],
  );

  const updateArtifactQueryRelations = React.useCallback(
    (
      nodeId: string,
      relations: readonly ArtifactQueryRelation[],
      inputPlugs: readonly WorkflowInputPlug[],
    ) => {
      updateConfigurationAndInputPlugs(nodeId, inputPlugs, (config) => ({
        ...config,
        relations,
      }));
    },
    [updateConfigurationAndInputPlugs],
  );

  const resetNodeArtifactTypeBinding = React.useCallback(
    (nodeId: string, variable: string) => {
      if (hasIncidentEdges(nodeId)) return;

      applyAuthoringCommands([
        {
          kind: "reset_artifact_type_binding",
          node_id: nodeId,
          variable,
        },
      ]);
      setPendingConnectionRoute(null);
      setRunError(null);
    },
    [
      applyAuthoringCommands,
      hasIncidentEdges,
      setPendingConnectionRoute,
      setRunError,
    ],
  );

  const bindNodeArtifactTypeBinding = React.useCallback(
    (nodeId: string, variable: string, artifactType: ArtifactTypeKey) => {
      if (hasIncidentEdges(nodeId)) return;

      applyAuthoringCommands([
        {
          kind: "bind_artifact_type",
          node_id: nodeId,
          variable,
          artifact_type: artifactType,
        },
      ]);
      setPendingConnectionRoute(null);
      setRunError(null);
    },
    [
      applyAuthoringCommands,
      hasIncidentEdges,
      setPendingConnectionRoute,
      setRunError,
    ],
  );

  return {
    addNodeInputPlug,
    bindNodeArtifactTypeBinding,
    removeNode,
    removeNodeInputPlug,
    reorderNodeInputPlug,
    resetNodeArtifactTypeBinding,
    updateArtifactQueryRelations,
    updateSchemaBuilderFields,
  };
}

"use client";

import * as React from "react";

import { uploadFile } from "@/lib/api";
import type { ImageUploadItem } from "@/lib/api";
import type { NodeExecution, WorkflowEdge } from "../canvas/types";
import { nodeAndDescendantIds } from "../model/graph-authoring";
import type { GraphCommand } from "../model/graph-document";
import type { WorkflowNode } from "../model/execution-plan";
import type { AuthoringCommandOptions } from "./authoring-command-guard";

interface UseNodeFileUploadsOptions {
  workspaceId: string;
  nodes: readonly WorkflowNode[];
  edges: readonly WorkflowEdge[];
  setNodes: React.Dispatch<React.SetStateAction<WorkflowNode[]>>;
  setRunError: (message: string | null) => void;
  applyAuthoringCommands: (
    commands: readonly GraphCommand[],
    options?: AuthoringCommandOptions,
  ) => void;
}

export interface UseNodeFileUploadsResult {
  /** True while any node is uploading a file; this pauses local authoring. */
  uploading: boolean;
  handleImagesSelected: (nodeId: string, files: File[]) => Promise<void>;
}

/**
 * Owns the lifecycle of file uploads attached to a node: marks the node and
 * its descendants busy while the request is in flight, then settles the node
 * to a non-busy state on success or failure. The upload is what pauses local
 * authoring, so its own completion is committed with the upload-completion
 * exemption instead of being rejected by that pause.
 */
export function useNodeFileUploads({
  workspaceId,
  nodes,
  edges,
  setNodes,
  setRunError,
  applyAuthoringCommands,
}: UseNodeFileUploadsOptions): UseNodeFileUploadsResult {
  const uploading = nodes.some(
    (node) => node.data.execution.status === "uploading",
  );

  const settleNodeExecution = React.useCallback(
    (nodeId: string, execution: NodeExecution) => {
      setNodes((current) =>
        current.map((node) =>
          node.id === nodeId
            ? { ...node, data: { ...node.data, execution } }
            : node,
        ),
      );
    },
    [setNodes],
  );

  const handleImagesSelected = React.useCallback(
    async (nodeId: string, files: File[]) => {
      const invalidatedNodeIds = nodeAndDescendantIds(nodeId, edges);
      setNodes((current) =>
        current.map((node) => {
          if (!invalidatedNodeIds.has(node.id)) return node;
          return {
            ...node,
            data: {
              ...node.data,
              run: null,
              progress: null,
              execution:
                node.id === nodeId
                  ? { status: "uploading" }
                  : { status: "idle" },
            },
          };
        }),
      );
      setRunError(null);
      try {
        const responses = await Promise.all(
          files.map((file) => uploadFile(workspaceId, file)),
        );
        // The upload response also carries ingest metadata (the resolved
        // artifact type and any blob notice). The node config keeps only the
        // staged-upload fields its operator declares, which are validated with
        // extra="forbid".
        const uploads: ImageUploadItem[] = responses.map(
          ({ upload_key, filename, byte_size }) => ({
            upload_key,
            filename,
            byte_size,
          }),
        );
        // The in-flight upload is what pauses local authoring; its own
        // completion is exempt from that pause so the result commits and the
        // node settles instead of locking the graph.
        applyAuthoringCommands(
          [
            {
              kind: "update_node_configuration",
              node_id: nodeId,
              field: "uploads",
              value: uploads,
            },
          ],
          { isUploadCompletion: true },
        );
        settleNodeExecution(nodeId, { status: "idle" });
      } catch (uploadError) {
        const cause =
          uploadError instanceof Error
            ? uploadError.message
            : "the request could not be completed";
        settleNodeExecution(nodeId, { status: "failed", error: cause });
        setRunError(`File upload failed: ${cause}`);
      }
    },
    [
      applyAuthoringCommands,
      edges,
      settleNodeExecution,
      setNodes,
      setRunError,
      workspaceId,
    ],
  );

  return { uploading, handleImagesSelected };
}

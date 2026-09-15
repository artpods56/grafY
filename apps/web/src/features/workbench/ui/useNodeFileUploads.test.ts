// @vitest-environment jsdom

import * as React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeSpec, UploadResponse } from "@/lib/api";
import {
  GEOJSON_UPLOAD_OPERATOR_ID,
  WORKFLOW_NODE_TYPE,
  createWorkflowNodeData,
  type WorkflowEdge,
} from "../canvas/types";
import type { GraphCommand } from "../model/graph-document";
import type { WorkflowNode } from "../model/execution-plan";
import type { AuthoringCommandOptions } from "./authoring-command-guard";
import { deferred } from "./test/deferred";
import { renderHook } from "./test/renderHook";
import { useNodeFileUploads } from "./useNodeFileUploads";

const uploadFileMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ uploadFile: uploadFileMock }));

const NO_EDGES: readonly WorkflowEdge[] = [];

function nodeSpec(): NodeSpec {
  return {
    operator_id: GEOJSON_UPLOAD_OPERATOR_ID,
    operator_version: 1,
    plugin_slug: "gis",
    origin: "builtin",
    title: "Import GeoJSON",
    description: "Import a GeoJSON FeatureCollection",
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [],
  };
}

function workflowNode(id = "node-1"): WorkflowNode {
  return {
    id,
    type: WORKFLOW_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: createWorkflowNodeData(nodeSpec()),
  };
}

function geoJsonFile(): File {
  return new File(['{"type": "FeatureCollection", "features": []}'], "layer.geojson", {
    type: "application/geo+json",
  });
}

function uploadResponse(): UploadResponse {
  return {
    byte_size: 48,
    filename: "layer.geojson",
    upload_key: "uploads/layer.geojson",
    artifact_type: "file.geojson@1",
    notice: null,
  };
}

interface HarnessProps {
  initialNodes: readonly WorkflowNode[];
  applyAuthoringCommands: (
    commands: readonly GraphCommand[],
    options?: AuthoringCommandOptions,
  ) => void;
}

/**
 * Hosts the upload hook against real node/run-error state so the test can
 * observe the node settle out of the busy "uploading" state.
 */
function useHarness({ initialNodes, applyAuthoringCommands }: HarnessProps) {
  const [nodes, setNodes] = React.useState<WorkflowNode[]>([...initialNodes]);
  const [runError, setRunError] = React.useState<string | null>(null);
  const { uploading, handleImagesSelected } = useNodeFileUploads({
    workspaceId: "workspace-1",
    nodes,
    edges: NO_EDGES,
    setNodes,
    setRunError,
    applyAuthoringCommands,
  });
  return { nodes, runError, uploading, handleImagesSelected };
}

type HarnessValue = ReturnType<typeof useHarness>;

/**
 * Returns a callable that starts an upload on the first node. The caller runs
 * it inside `React.act`; the returned promise settles when the upload flow
 * finishes. `React.act` must stay in the test body because nesting it inside
 * another async function prevents it from flushing in this environment.
 */
function startUploadOn(
  hook: { result: { current: HarnessValue } },
  files: readonly File[] = [geoJsonFile()],
): () => Promise<void> {
  return () => hook.result.current.handleImagesSelected("node-1", [...files]);
}

describe("useNodeFileUploads", () => {
  beforeEach(() => {
    uploadFileMock.mockReset();
  });

  it("commits the upload result and unlocks authoring after a successful upload", async () => {
    const applyAuthoringCommands = vi.fn();
    const upload = uploadResponse();
    const uploadDeferred = deferred<UploadResponse>();
    uploadFileMock.mockReturnValue(uploadDeferred.promise);

    const hook = await renderHook(useHarness, {
      initialNodes: [workflowNode()],
      applyAuthoringCommands,
    });

    expect(hook.result.current.uploading).toBe(false);
    expect(hook.result.current.nodes[0].data.execution.status).toBe("idle");

    const begin = startUploadOn(hook);
    let handlePromise!: Promise<void>;
    await React.act(async () => {
      handlePromise = begin();
    });
    expect(hook.result.current.uploading).toBe(true);
    expect(hook.result.current.nodes[0].data.execution.status).toBe("uploading");
    expect(applyAuthoringCommands).not.toHaveBeenCalled();

    await React.act(async () => {
      uploadDeferred.resolve(upload);
      await handlePromise;
    });

    expect(applyAuthoringCommands).toHaveBeenCalledWith(
      [
        {
          kind: "update_node_configuration",
          node_id: "node-1",
          field: "uploads",
          // Ingest metadata stays out of the node config, which the upload
          // operator validates with extra="forbid".
          value: [
            {
              byte_size: 48,
              filename: "layer.geojson",
              upload_key: "uploads/layer.geojson",
            },
          ],
        },
      ],
      { isUploadCompletion: true },
    );
    expect(hook.result.current.nodes[0].data.execution.status).toBe("idle");
    expect(hook.result.current.uploading).toBe(false);
    expect(hook.result.current.runError).toBeNull();
  });

  it("settles the node and reports the cause when the upload fails", async () => {
    const applyAuthoringCommands = vi.fn();
    const uploadDeferred = deferred<UploadResponse>();
    uploadFileMock.mockReturnValue(uploadDeferred.promise);

    const hook = await renderHook(useHarness, {
      initialNodes: [workflowNode()],
      applyAuthoringCommands,
    });

    const begin = startUploadOn(hook);
    let handlePromise!: Promise<void>;
    await React.act(async () => {
      handlePromise = begin();
    });
    expect(hook.result.current.uploading).toBe(true);

    await React.act(async () => {
      uploadDeferred.reject(new Error("413 Request Entity Too Large"));
      await handlePromise;
    });

    expect(applyAuthoringCommands).not.toHaveBeenCalled();
    expect(hook.result.current.nodes[0].data.execution.status).toBe("failed");
    expect(hook.result.current.nodes[0].data.execution.error).toBe(
      "413 Request Entity Too Large",
    );
    expect(hook.result.current.uploading).toBe(false);
    expect(hook.result.current.runError).toBe(
      "File upload failed: 413 Request Entity Too Large",
    );
  });

  it("leaves no busy state when the upload request is aborted", async () => {
    const applyAuthoringCommands = vi.fn();
    const uploadDeferred = deferred<UploadResponse>();
    uploadFileMock.mockReturnValue(uploadDeferred.promise);

    const hook = await renderHook(useHarness, {
      initialNodes: [workflowNode()],
      applyAuthoringCommands,
    });

    const begin = startUploadOn(hook);
    let handlePromise!: Promise<void>;
    await React.act(async () => {
      handlePromise = begin();
    });

    await React.act(async () => {
      uploadDeferred.reject(
        Object.assign(new Error("The operation was aborted."), {
          name: "AbortError",
        }),
      );
      await handlePromise;
    });

    expect(applyAuthoringCommands).not.toHaveBeenCalled();
    expect(hook.result.current.uploading).toBe(false);
    expect(hook.result.current.nodes[0].data.execution.status).toBe("failed");
    expect(hook.result.current.runError).toBe(
      "File upload failed: The operation was aborted.",
    );
  });

  it("pauses authoring only for the duration of the in-flight upload", async () => {
    const applyAuthoringCommands = vi.fn();
    const uploadDeferred = deferred<UploadResponse>();
    uploadFileMock.mockReturnValue(uploadDeferred.promise);

    const hook = await renderHook(useHarness, {
      initialNodes: [workflowNode()],
      applyAuthoringCommands,
    });

    const begin = startUploadOn(hook);
    let handlePromise!: Promise<void>;
    await React.act(async () => {
      handlePromise = begin();
    });
    expect(hook.result.current.uploading).toBe(true);

    await React.act(async () => {
      uploadDeferred.resolve(uploadResponse());
      await handlePromise;
    });

    expect(hook.result.current.uploading).toBe(false);
    expect(hook.result.current.nodes[0].data.execution.status).toBe("idle");
  });
});
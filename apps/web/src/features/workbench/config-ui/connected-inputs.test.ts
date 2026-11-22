import { describe, expect, it } from "vitest";

import type {
  ArtifactConversionSpec,
  ArtifactRef,
  ArtifactRefSequence,
  ArtifactTypeSpec,
  SavedGraphOrigin,
} from "@/lib/api";

import { artifactPortFixture, nodeSpecFixture } from "../test-fixtures";
import {
  ARTIFACT_ORIGIN_EDGE_TYPE,
  type ArtifactOriginEdge,
} from "../artifacts/artifact-origin-edge";
import {
  ARTIFACT_VIEWER_NODE_TYPE,
  type ArtifactViewerNode,
  type CanvasWorkflowNode,
} from "../artifacts/artifact-viewer";
import {
  connectedInputPortsForDocumentNode,
  connectedInputPortsForNode,
} from "./connected-inputs";
import { encodeHandleId } from "../authoring/handles";
import {
  createWorkflowNodeData,
  portMetaForPort,
  WORKFLOW_EDGE_TYPE,
  WORKFLOW_NODE_TYPE,
  type WorkflowEdge,
  type WorkflowEdgeData,
} from "../authoring/types";

const text = { id: "scalar.text", schema_version: 2 };
const document = { id: "document.json", schema_version: 1 };
const vector = { id: "geo.vector", schema_version: 3 };
const input = artifactPortFixture({
  name: "input",
  direction: "input",
  artifact_type: vector,
});
const other = artifactPortFixture({ name: "other", direction: "input" });
const output = artifactPortFixture({
  name: "output",
  direction: "output",
  artifact_type: null,
  artifact_type_variable: "T",
});
const spec = nodeSpecFixture({
  operator_id: "test.target",
  inputs: [input, other],
});
const sourceSpec = nodeSpecFixture({
  operator_id: "test.source",
  outputs: [output],
});
const source: CanvasWorkflowNode = {
  id: "source",
  type: WORKFLOW_NODE_TYPE,
  position: { x: 0, y: 0 },
  data: {
    ...createWorkflowNodeData(sourceSpec),
    artifactTypeBindings: { T: document },
  },
};
const options = { nodeId: "target", spec, nodes: [source] };

function workflowEdge(overrides: Partial<WorkflowEdgeData> = {}): WorkflowEdge {
  return {
    id: "edge",
    type: WORKFLOW_EDGE_TYPE,
    source: source.id,
    // Keep the handle generic to exercise the current source binding.
    sourceHandle: encodeHandleId(portMetaForPort(output)),
    target: "target",
    targetHandle: encodeHandleId(portMetaForPort(input, "one", "plug-1")),
    data: { enabled: true, collectionMode: "direct", ...overrides },
  };
}

const conversions: readonly ArtifactConversionSpec[] = [
  {
    key: { id: "document-to-text", version: 1 },
    source_artifact_type: document,
    target_artifact_type: text,
    title: "Document to text",
  },
  {
    key: { id: "text-to-vector", version: 2 },
    source_artifact_type: text,
    target_artifact_type: vector,
    title: "Text to vector",
  },
];

const artifactTypes: readonly ArtifactTypeSpec[] = [
  {
    key: document,
    title: "JSON document",
    preview_kind: "text",
    bundle: { format: "inline-json", version: 1 },
    payload_schema: {},
    field_projections: [
      { path: ["content", "text"], title: "Text", target_artifact_type: text },
    ],
  },
];

const ref: ArtifactRef = {
  artifact_id: "ref-one",
  artifact_type: text.id,
  schema_version: text.schema_version,
};
const sequence: ArtifactRefSequence = {
  artifact_type: ref.artifact_type,
  index_key: "order_index",
  schema_version: ref.schema_version,
  ordered: true,
  item_refs: [ref, { ...ref, artifact_id: "ref-two" }],
};

function savedOrigin(value: SavedGraphOrigin["value"]): SavedGraphOrigin {
  return {
    id: "origin",
    to_node: "target",
    to_port: "input",
    collection_mode: "direct",
    conversion_path: [],
    value,
  };
}

describe("connectedInputPortsForNode", () => {
  it("ignores disabled and unrelated edges and resolves the enabled source port binding", () => {
    const disabled = workflowEdge({ enabled: false });
    expect(
      connectedInputPortsForNode({
        ...options,
        edges: [disabled, { ...workflowEdge(), target: "another-node" }],
      }),
    ).toEqual({
      input: { connected: false, artifactTypeKey: null },
      other: { connected: false, artifactTypeKey: null },
    });
    expect(
      connectedInputPortsForNode({ ...options, edges: [workflowEdge()] }),
    ).toEqual({
      input: { connected: true, artifactTypeKey: "document.json@1" },
      other: { connected: false, artifactTypeKey: null },
    });
  });

  it("uses the concrete source handle when the source node is unavailable", () => {
    const edge = {
      ...workflowEdge(),
      sourceHandle: encodeHandleId(
        portMetaForPort(output, "one", undefined, { T: text }),
      ),
    };
    expect(
      connectedInputPortsForNode({ ...options, nodes: [], edges: [edge] })
        .input,
    ).toEqual({ connected: true, artifactTypeKey: "scalar.text@2" });
    expect(
      connectedInputPortsForNode({
        ...options,
        nodes: [],
        edges: [workflowEdge()],
      }).input,
    ).toEqual({ connected: true, artifactTypeKey: null });
  });

  it("uses a projection's target type when the artifact catalog is available", () => {
    const edges = [workflowEdge({ projection: { path: ["content", "text"] } })];
    expect(
      connectedInputPortsForNode({ ...options, edges, artifactTypes }).input,
    ).toEqual({ connected: true, artifactTypeKey: "scalar.text@2" });
    expect(connectedInputPortsForNode({ ...options, edges }).input).toEqual({
      connected: true,
      artifactTypeKey: "document.json@1",
    });
  });

  it("uses the final conversion's versioned target type", () => {
    const edges = [
      workflowEdge({ conversionPath: conversions.map(({ key }) => key) }),
    ];
    expect(
      connectedInputPortsForNode({ ...options, edges, conversions }).input,
    ).toEqual({ connected: true, artifactTypeKey: "geo.vector@3" });
  });

  it.each([ref, sequence])("resolves a saved origin with value %j", (value) => {
    expect(
      connectedInputPortsForNode({
        ...options,
        edges: [],
        origins: [
          savedOrigin(value),
          { ...savedOrigin(value), to_node: "elsewhere", to_port: "other" },
        ],
      }),
    ).toEqual({
      input: { connected: true, artifactTypeKey: "scalar.text@2" },
      other: { connected: false, artifactTypeKey: null },
    });
  });

  it("uses conversion targets for saved origins and keeps workflow edges on other ports", () => {
    expect(
      connectedInputPortsForNode({
        ...options,
        edges: [
          {
            ...workflowEdge(),
            targetHandle: encodeHandleId(portMetaForPort(other)),
          },
        ],
        origins: [
          {
            ...savedOrigin(sequence),
            conversion_path: [{ id: "text-to-vector", version: 2 }],
          },
        ],
        conversions,
      }),
    ).toEqual({
      input: { connected: true, artifactTypeKey: "geo.vector@3" },
      other: { connected: true, artifactTypeKey: "document.json@1" },
    });
  });

  it("reads an origin edge's source card when saved origins are omitted", () => {
    const card: ArtifactViewerNode = {
      id: "card",
      type: ARTIFACT_VIEWER_NODE_TYPE,
      position: { x: 0, y: 0 },
      data: { layout: null, mode: null, artifactRef: sequence },
    };
    const edge: ArtifactOriginEdge = {
      id: "drawn-origin",
      type: ARTIFACT_ORIGIN_EDGE_TYPE,
      source: card.id,
      target: "target",
      targetHandle: encodeHandleId(portMetaForPort(input)),
      data: { originId: "origin" },
    };
    const cardOptions = { ...options, edges: [edge], nodes: [card] };
    expect(connectedInputPortsForNode(cardOptions).input).toEqual({
      connected: true,
      artifactTypeKey: "scalar.text@2",
    });
    expect(
      connectedInputPortsForNode({ ...cardOptions, origins: [] }).input,
    ).toEqual({ connected: false, artifactTypeKey: null });
  });
});

describe("connectedInputPortsForDocumentNode", () => {
  const sources = new Map([
    [
      "source",
      {
        node: {
          artifact_type_bindings: [{ variable: "T", artifact_type: document }],
        },
        spec: sourceSpec,
      },
    ],
  ]);
  const documentEdge = {
    id: "edge",
    from_node: "source",
    from_port: "output",
    to_node: "target",
    to_port: "input",
    to_plug: "plug-1",
    collection_mode: "direct" as const,
    conversion_path: [],
    enabled: true,
  };
  const base = {
    nodeId: "target",
    spec,
    origins: [],
    sources,
    conversions,
    artifactTypes,
  };

  it("types an edge by its source's bound port, projection, or conversion", () => {
    expect(
      connectedInputPortsForDocumentNode({ ...base, edges: [documentEdge] }),
    ).toEqual({
      input: { connected: true, artifactTypeKey: "document.json@1" },
      other: { connected: false, artifactTypeKey: null },
    });
    expect(
      connectedInputPortsForDocumentNode({
        ...base,
        edges: [{ ...documentEdge, projection: { path: ["content", "text"] } }],
      }).input,
    ).toEqual({ connected: true, artifactTypeKey: "scalar.text@2" });
    expect(
      connectedInputPortsForDocumentNode({
        ...base,
        edges: [
          {
            ...documentEdge,
            conversion_path: [
              { id: "document-to-text", version: 1 },
              { id: "text-to-vector", version: 2 },
            ],
          },
        ],
      }).input,
    ).toEqual({ connected: true, artifactTypeKey: "geo.vector@3" });
  });

  it("ignores disabled edges and reads origins by their value", () => {
    expect(
      connectedInputPortsForDocumentNode({
        ...base,
        edges: [{ ...documentEdge, enabled: false }],
      }).input,
    ).toEqual({ connected: false, artifactTypeKey: null });
    expect(
      connectedInputPortsForDocumentNode({
        ...base,
        edges: [],
        origins: [savedOrigin(ref)],
      }).input,
    ).toEqual({ connected: true, artifactTypeKey: "scalar.text@2" });
  });
});

import { describe, expect, it } from "vitest";

import type {
  ArtifactConversionSpec,
  ArtifactRef,
  ArtifactTypeSpec,
  SavedGraphOrigin,
} from "@/lib/api";

import { artifactPortFixture, nodeSpecFixture } from "../test-fixtures";

import { connectedInputPortsForDocumentNode } from "./connected-inputs";

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

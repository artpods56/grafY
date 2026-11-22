import { describe, expect, it } from "vitest";

import type { NodeRegistry } from "@/lib/api";

import {
  artifactPortFixture,
  nodeSpecFixture,
  servicePortFixture,
} from "../test-fixtures";
import type { AuthoredGraphDocument } from "./graph-document";
import {
  effectiveOutputPortShape,
  resolveGraphSemantics,
} from "./graph-semantics";

function registryWith(nodes: NodeRegistry["nodes"]): NodeRegistry {
  return {
    nodes,
    artifact_types: [
      {
        key: { id: "image.jpeg", schema_version: 1 },
        title: "JPEG image",
        preview_kind: "image",
        bundle: { format: "binary-file", version: 1 },
        field_projections: [],
        payload_schema: {},
      },
      {
        key: { id: "document.regions", schema_version: 1 },
        title: "Regions",
        preview_kind: "file",
        bundle: { format: "inline-json", version: 1 },
        field_projections: [],
        payload_schema: {},
      },
      {
        key: { id: "scalar.text", schema_version: 1 },
        title: "Text",
        preview_kind: "text",
        bundle: { format: "inline-json", version: 1 },
        field_projections: [],
        payload_schema: {},
      },
    ],
    artifact_conversions: [],
    plugins: [],
  };
}

function emptyDocument(
  overrides: Partial<
    Pick<AuthoredGraphDocument, "nodes" | "edges" | "origins">
  > = {},
): Pick<AuthoredGraphDocument, "nodes" | "edges" | "origins"> {
  return {
    nodes: [],
    edges: [],
    origins: [],
    ...overrides,
  };
}

describe("resolveGraphSemantics", () => {
  it("resolves exact specs with shape_field overrides and falls back to operator_id for displaySpec", () => {
    const dynamicInputSpec = nodeSpecFixture({
      operator_id: "graph.input",
      operator_version: 1,
      config_schema: {
        type: "object",
        properties: { shape: { type: "string", default: "one" } },
      },
      outputs: [
        artifactPortFixture({
          name: "value",
          direction: "output",
          shape: "one",
          shape_field: "shape",
        }),
      ],
    });
    const registry = registryWith([dynamicInputSpec]);

    const semantics = resolveGraphSemantics(
      emptyDocument({
        nodes: [
          {
            id: "exact",
            kind: "builtin",
            operator_id: "graph.input",
            operator_version: 1,
            config: { shape: "many" },
            input_plugs: [],
            artifact_type_bindings: [],
            position: { x: 0, y: 0 },
          },
          {
            id: "stale-version",
            kind: "builtin",
            operator_id: "graph.input",
            operator_version: 9,
            config: { shape: "many" },
            input_plugs: [],
            artifact_type_bindings: [],
            position: { x: 200, y: 0 },
          },
        ],
      }),
      registry,
    );

    const exact = semantics.nodes.get("exact");
    expect(exact?.compatibility.status).toBe("supported");
    expect(exact?.spec?.outputs[0]?.shape).toBe("many");
    expect(exact?.effectiveOutputShapes.get("value")).toBe("many");

    const stale = semantics.nodes.get("stale-version");
    expect(stale?.compatibility.status).toBe("unsupported");
    expect(stale?.spec).toBeNull();
    expect(stale?.displaySpec?.outputs[0]?.shape).toBe("many");
  });

  it("cascades map repairs from a sequence origin through downstream operators and widens output shapes", () => {
    const readSpec = nodeSpecFixture({
      operator_id: "ocr.read",
      inputs: [
        artifactPortFixture({
          name: "scan",
          direction: "input",
          artifact_type: { id: "image.jpeg", schema_version: 1 },
        }),
      ],
      outputs: [
        artifactPortFixture({
          name: "regions",
          direction: "output",
          artifact_type: { id: "document.regions", schema_version: 1 },
        }),
        servicePortFixture({
          name: "reader_service",
          direction: "output",
          service_contracts: [{ id: "ocr.reader", version: 1 }],
        }),
      ],
    });
    const drawSpec = nodeSpecFixture({
      operator_id: "image.draw_boxes",
      inputs: [
        artifactPortFixture({
          name: "image",
          direction: "input",
          artifact_type: { id: "image.jpeg", schema_version: 1 },
        }),
        artifactPortFixture({
          name: "boxes",
          direction: "input",
          artifact_type: { id: "document.regions", schema_version: 1 },
        }),
      ],
      outputs: [
        artifactPortFixture({
          name: "image",
          direction: "output",
          artifact_type: { id: "image.jpeg", schema_version: 1 },
        }),
      ],
    });
    const registry = registryWith([readSpec, drawSpec]);

    const semantics = resolveGraphSemantics(
      emptyDocument({
        nodes: [
          {
            id: "read",
            kind: "builtin",
            operator_id: "ocr.read",
            operator_version: 1,
            config: {},
            input_plugs: [],
            artifact_type_bindings: [],
            position: { x: 0, y: 0 },
          },
          {
            id: "draw",
            kind: "builtin",
            operator_id: "image.draw_boxes",
            operator_version: 1,
            config: {},
            input_plugs: [],
            artifact_type_bindings: [],
            position: { x: 300, y: 0 },
          },
        ],
        origins: [
          {
            id: "origin-1",
            to_node: "read",
            to_port: "scan",
            to_plug: null,
            collection_mode: "direct",
            conversion_path: [],
            value: {
              artifact_type: "image.jpeg",
              schema_version: 1,
              index_key: "index",
              ordered: true,
              item_refs: [
                {
                  artifact_id: "a1",
                  artifact_type: "image.jpeg",
                  schema_version: 1,
                },
                {
                  artifact_id: "a2",
                  artifact_type: "image.jpeg",
                  schema_version: 1,
                },
              ],
            },
          },
        ],
        edges: [
          {
            id: "edge-1",
            from_node: "read",
            from_port: "regions",
            to_node: "draw",
            to_port: "boxes",
            to_plug: null,
            enabled: true,
            collection_mode: "direct",
            conversion_path: [],
          },
        ],
      }),
      registry,
    );

    expect(semantics.originModeRepairs.get("origin-1")).toBe("map");
    expect(semantics.edgeModeRepairs.get("edge-1")).toBe("map");
    expect(semantics.origins.get("origin-1")?.collectionMode).toBe("map");
    expect(semantics.origins.get("origin-1")?.allowedCollectionModes).toEqual([
      "map",
    ]);
    expect(semantics.edges.get("edge-1")?.collectionMode).toBe("map");
    expect(semantics.edges.get("edge-1")?.allowedCollectionModes).toEqual([
      "map",
    ]);

    const readNode = semantics.nodes.get("read");
    expect(readNode?.runsPerItem).toBe(true);
    expect(readNode?.mappedInputPorts).toEqual(["scan"]);
    expect(readNode?.effectiveOutputShapes.get("regions")).toBe("many");
    expect(readNode?.effectiveOutputShapes.get("reader_service")).toBe("one");
    expect(
      effectiveOutputPortShape(semantics, "read", readSpec.outputs[0]!),
    ).toBe("many");
    expect(
      effectiveOutputPortShape(semantics, "read", readSpec.outputs[1]!),
    ).toBe("one");

    const drawNode = semantics.nodes.get("draw");
    expect(drawNode?.runsPerItem).toBe(true);
    expect(drawNode?.mappedInputPorts).toEqual(["boxes"]);
    expect(drawNode?.effectiveOutputShapes.get("image")).toBe("many");
  });

  it("separates active runsPerItem from disabled map drivers used during authoring", () => {
    const sourceSpec = nodeSpecFixture({
      operator_id: "source",
      outputs: [
        artifactPortFixture({
          name: "items",
          direction: "output",
          shape: "many",
        }),
      ],
    });
    const stepSpec = nodeSpecFixture({
      operator_id: "step",
      inputs: [
        artifactPortFixture({ name: "item", direction: "input", shape: "one" }),
      ],
      outputs: [
        artifactPortFixture({ name: "out", direction: "output", shape: "one" }),
      ],
    });
    const registry = registryWith([sourceSpec, stepSpec]);

    const semantics = resolveGraphSemantics(
      emptyDocument({
        nodes: [
          {
            id: "source",
            kind: "builtin",
            operator_id: "source",
            operator_version: 1,
            config: {},
            input_plugs: [],
            artifact_type_bindings: [],
            position: { x: 0, y: 0 },
          },
          {
            id: "step",
            kind: "builtin",
            operator_id: "step",
            operator_version: 1,
            config: {},
            input_plugs: [],
            artifact_type_bindings: [],
            position: { x: 200, y: 0 },
          },
        ],
        edges: [
          {
            id: "disabled-map",
            from_node: "source",
            from_port: "items",
            to_node: "step",
            to_port: "item",
            to_plug: null,
            enabled: false,
            collection_mode: "map",
            conversion_path: [],
          },
        ],
      }),
      registry,
    );

    const step = semantics.nodes.get("step");
    expect(step?.runsPerItem).toBe(false);
    expect(step?.mappedInputPorts).toEqual([]);
    expect(step?.effectiveOutputShapes.get("out")).toBe("one");
    expect(step?.outputsWidenedForAuthoring).toBe(true);
    expect(step?.allMappedInputPorts).toEqual(["item"]);
    expect(step?.authoringOutputShapes.get("out")).toBe("many");
    expect(semantics.mappedNodeIds.has("step")).toBe(false);
    expect(semantics.authoringMappedNodeIds.has("step")).toBe(true);
  });

  it("flags unsupported modules, stale call ports, bad plugs/bindings, and missing edge ports", () => {
    const calleeSpec = nodeSpecFixture({
      operator_id: "project.graph.child",
      inputs: [artifactPortFixture({ name: "input", direction: "input" })],
      outputs: [artifactPortFixture({ name: "output", direction: "output" })],
    });
    const opSpec = nodeSpecFixture({
      operator_id: "text.echo",
      inputs: [artifactPortFixture({ name: "text", direction: "input" })],
      outputs: [artifactPortFixture({ name: "text", direction: "output" })],
    });
    const registry = registryWith([calleeSpec, opSpec]);

    const semantics = resolveGraphSemantics(
      emptyDocument({
        nodes: [
          {
            id: "mod",
            kind: "module",
            operator_id: "text.echo",
            operator_version: 1,
            config: {},
            input_plugs: [],
            artifact_type_bindings: [],
            position: { x: 0, y: 0 },
          },
          {
            id: "stale-call",
            kind: "call",
            operator_id: "project.graph.child",
            operator_version: 1,
            config: {},
            input_plugs: [],
            artifact_type_bindings: [],
            position: { x: 100, y: 0 },
          },
          {
            id: "bad-plug",
            kind: "builtin",
            operator_id: "text.echo",
            operator_version: 1,
            config: {},
            input_plugs: [{ id: "p1", port: "text" }],
            artifact_type_bindings: [],
            position: { x: 200, y: 0 },
          },
          {
            id: "bad-binding",
            kind: "builtin",
            operator_id: "text.echo",
            operator_version: 1,
            config: {},
            input_plugs: [],
            artifact_type_bindings: [
              {
                variable: "T",
                artifact_type: { id: "scalar.text", schema_version: 1 },
              },
            ],
            position: { x: 300, y: 0 },
          },
          {
            id: "stale-edge-owner",
            kind: "builtin",
            operator_id: "text.echo",
            operator_version: 1,
            config: {},
            input_plugs: [],
            artifact_type_bindings: [],
            position: { x: 400, y: 0 },
          },
        ],
        edges: [
          {
            id: "call-edge",
            from_node: "stale-call",
            from_port: "removed_output",
            to_node: "stale-edge-owner",
            to_port: "removed_input",
            to_plug: null,
            enabled: true,
            collection_mode: "direct",
            conversion_path: [],
          },
        ],
      }),
      registry,
    );

    expect(semantics.nodes.get("mod")?.compatibility.status).toBe(
      "unsupported",
    );
    expect(semantics.nodes.get("stale-call")?.compatibility.status).toBe(
      "invalid",
    );
    expect(semantics.nodes.get("bad-plug")?.compatibility.status).toBe(
      "invalid",
    );
    expect(semantics.nodes.get("bad-binding")?.compatibility.status).toBe(
      "invalid",
    );
    expect(semantics.nodes.get("stale-edge-owner")?.compatibility.status).toBe(
      "invalid",
    );
  });
});

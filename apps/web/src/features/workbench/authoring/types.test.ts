import { describe, expect, it } from "vitest";

import type { NodeSpec } from "@/lib/api";
import { artifactPortFixture, nodeSpecFixture } from "../test-fixtures";
import {
  createWorkflowNodeData,
  portMetaForPort,
  serializeRunNode,
} from "./types";

const genericNodeSpec: NodeSpec = nodeSpecFixture({
  operator_id: "sequence.collect",
  title: "Collect",
  description: "Collect ordered artifacts.",
  inputs: [
    artifactPortFixture({
      name: "items",
      title: "Items",
      direction: "input",
      artifact_type: null,
      artifact_type_variable: "T",
      accepted_shapes: ["one", "many"],
      instance_plugs: true,
    }),
  ],
  outputs: [
    artifactPortFixture({
      name: "items",
      title: "Items",
      direction: "output",
      artifact_type: null,
      artifact_type_variable: "T",
      shape: "many",
    }),
  ],
});

describe("generic artifact type bindings", () => {
  it("resolves every port sharing T after the first binding", () => {
    const data = createWorkflowNodeData(genericNodeSpec);
    data.artifactTypeBindings = {
      T: { id: "scalar.text", schema_version: 1 },
    };

    const metas = [...data.spec.inputs, ...data.spec.outputs].map((port) =>
      portMetaForPort(port, port.shape, undefined, data.artifactTypeBindings),
    );

    expect(metas).toHaveLength(2);
    expect(metas).toEqual([
      {
        portName: "items",
        artifactTypeId: "scalar.text",
        schemaVersion: 1,
        shape: "one",
        direction: "input",
      },
      {
        portName: "items",
        artifactTypeId: "scalar.text",
        schemaVersion: 1,
        shape: "many",
        direction: "output",
      },
    ]);
  });

  it("preserves instance-plug identity when T binds to a raster image", () => {
    const input = genericNodeSpec.inputs[0]!;
    const plugId = "image-input-1";
    const genericMeta = portMetaForPort(input, input.shape, plugId);
    const data = createWorkflowNodeData(genericNodeSpec);
    data.artifactTypeBindings = {
      T: { id: "image.raster", schema_version: 1 },
    };
    const concreteMeta = portMetaForPort(
      input,
      input.shape,
      plugId,
      data.artifactTypeBindings,
    );

    expect(genericMeta).toEqual({
      portName: "items",
      artifactTypeVariable: "T",
      shape: "one",
      direction: "input",
      plugId,
    });
    expect(concreteMeta).toEqual({
      portName: "items",
      artifactTypeId: "image.raster",
      schemaVersion: 1,
      shape: "one",
      direction: "input",
      plugId,
    });
  });
});

describe("run node serialization", () => {
  it("sends ordinary config while omitting ephemeral progress state", () => {
    const data = createWorkflowNodeData(genericNodeSpec);
    data.config = {
      base_url: "https://api.openai.com/v1",
      model: "gpt-5-mini",
      bounds: [19.75, 49.97, 19.82, 50.03],
    };
    data.progress = {
      omittedCount: 0,
      entries: [
        {
          sequence: 1,
          message: "api_key=must-not-be-serialized",
          current: null,
          total: null,
          sourceNodePath: [],
          invocationIndex: null,
          invocationPath: [],
        },
      ],
    };

    const request = serializeRunNode("llm-node", data);

    expect(request.config).toEqual(data.config);
    expect(request).not.toHaveProperty("progress");
    expect(JSON.stringify(request)).not.toContain("api_key");
  });

  it("omits authoring input plugs that have no active execution edge", () => {
    const data = createWorkflowNodeData(genericNodeSpec);
    data.inputPlugs = [
      { id: "active", portName: "items" },
      { id: "disabled", portName: "items" },
    ];

    const request = serializeRunNode("collect-node", data, new Set(["active"]));

    expect(request.input_plugs).toEqual([{ id: "active", port: "items" }]);
    expect(data.inputPlugs).toHaveLength(2);
  });
});

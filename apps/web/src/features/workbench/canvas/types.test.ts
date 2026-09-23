import { describe, expect, it } from "vitest";

import type { NodeSpec } from "@/lib/api";
import { decodeHandleId, encodeHandleId } from "./handles";
import {
  bindArtifactTypeVariable,
  createWorkflowNodeData,
  portMetaForPort,
  resetArtifactTypeBinding,
  serializeRunNode,
} from "./types";

const genericNodeSpec: NodeSpec = {
  operator_id: "sequence.collect",
  operator_version: 1,
  plugin_slug: "test",
  origin: "builtin",
  title: "Collect",
  description: "Collect ordered artifacts.",
  catalog_visible: true,
  runnable: true,
  config_schema: {},
  input_schema: {},
  output_schema: {},
  inputs: [
    {
      name: "items",
      title: "Items",
      description: null,
      direction: "input",
      artifact_type: null,
      artifact_type_variable: "T",
      shape: "one",
      accepted_shapes: ["one", "many"],
      instance_plugs: true,
      variadic: false,
      required: true,
    },
  ],
  outputs: [
    {
      name: "items",
      title: "Items",
      description: null,
      direction: "output",
      artifact_type: null,
      artifact_type_variable: "T",
      shape: "many",
      accepted_shapes: ["many"],
      instance_plugs: false,
      variadic: false,
      required: true,
    },
  ],
};

const artifactQueryNodeSpec: NodeSpec = {
  operator_id: "sql.artifacts.query",
  operator_version: 1,
  plugin_slug: "external.sql",
  origin: "builtin",
  title: "Query artifact tables",
  description: "Runs read-only queries over table artifacts.",
  catalog_visible: true,
  runnable: true,
  config_schema: {
    type: "object",
    properties: { relations: { type: "array" } },
    required: ["relations"],
  },
  input_schema: {},
  output_schema: {},
  inputs: [
    {
      name: "statements",
      title: "Statements",
      description: null,
      direction: "input",
      artifact_type: { id: "sql.statement", schema_version: 1 },
      artifact_type_variable: null,
      shape: "one",
      accepted_shapes: ["one"],
      instance_plugs: true,
      variadic: true,
      required: true,
    },
    {
      name: "relations",
      title: "Relations",
      description: null,
      direction: "input",
      artifact_type: { id: "table.data", schema_version: 1 },
      artifact_type_variable: null,
      shape: "one",
      accepted_shapes: ["one"],
      instance_plugs: true,
      variadic: true,
      required: true,
    },
  ],
  outputs: [
    {
      name: "tables",
      title: "Tables",
      description: null,
      direction: "output",
      artifact_type: { id: "table.data", schema_version: 1 },
      artifact_type_variable: null,
      shape: "many",
      accepted_shapes: ["many"],
      instance_plugs: false,
      variadic: false,
      required: true,
    },
  ],
};

describe("artifact query initialization", () => {
  it("seeds one statement plug and one named relation with shared identity", () => {
    const data = createWorkflowNodeData(artifactQueryNodeSpec);
    const relationPlug = data.inputPlugs.find(
      (plug) => plug.portName === "relations",
    );

    expect(data.inputPlugs.map((plug) => plug.portName)).toEqual([
      "statements",
      "relations",
    ]);
    expect(data.config.relations).toEqual([
      { id: relationPlug?.id, alias: "relation_1" },
    ]);
  });
});

describe("scoped Plugin release pins", () => {
  it("pins a newly authored catalog node to its advertised immutable release", () => {
    const data = createWorkflowNodeData({
      ...genericNodeSpec,
      plugin_slug: "notes",
      origin: "plugin",
      plugin_revision: 4,
      plugin_release: { scope: "system", slug: "notes", revision: 4 },
    });

    expect(data.pluginReleasePin).toEqual({
      scope: "system",
      slug: "notes",
      revision: 4,
    });
    expect(serializeRunNode("notes-1", data).plugin_release).toEqual({
      scope: "system",
      slug: "notes",
      revision: 4,
    });
  });

  it("keeps host Plugin nodes unpinned", () => {
    expect(createWorkflowNodeData(genericNodeSpec).pluginReleasePin).toBeNull();
  });
});

describe("generic artifact type reset", () => {
  it("keeps an incident binding and clears a disconnected binding", () => {
    const data = createWorkflowNodeData(genericNodeSpec);
    data.artifactTypeBindings = {
      T: { id: "scalar.text", schema_version: 1 },
    };
    data.execution = { status: "failed", error: "stale" };
    data.progress = {
      omittedCount: 0,
      entries: [
        {
          sequence: 1,
          message: "stale",
          current: null,
          total: null,
          sourceNodePath: [],
          invocationIndex: null,
          invocationPath: [],
        },
      ],
    };

    expect(resetArtifactTypeBinding(data, "T", true)).toBe(data);

    const reset = resetArtifactTypeBinding(data, "T", false);
    expect(reset).not.toBe(data);
    expect(reset.artifactTypeBindings).toEqual({});
    expect(reset.execution).toEqual({ status: "idle" });
    expect(reset.progress).toBeNull();
  });

  it("resolves every port sharing T after the first binding", () => {
    const data = bindArtifactTypeVariable(
      createWorkflowNodeData(genericNodeSpec),
      "T",
      { id: "scalar.text", schema_version: 1 },
    );

    const handles = [...data.spec.inputs, ...data.spec.outputs].map((port) =>
      decodeHandleId(
        encodeHandleId(
          portMetaForPort(
            port,
            port.shape,
            undefined,
            data.artifactTypeBindings,
          ),
        ),
      ),
    );

    expect(handles).toHaveLength(2);
    expect(handles).toEqual([
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
    const genericHandle = decodeHandleId(
      encodeHandleId(portMetaForPort(input, input.shape, plugId)),
    );
    const data = bindArtifactTypeVariable(
      createWorkflowNodeData(genericNodeSpec),
      "T",
      { id: "image.raster", schema_version: 1 },
    );
    const concreteHandle = decodeHandleId(
      encodeHandleId(
        portMetaForPort(input, input.shape, plugId, data.artifactTypeBindings),
      ),
    );

    expect(genericHandle).toEqual({
      portName: "items",
      artifactTypeVariable: "T",
      shape: "one",
      direction: "input",
      plugId,
    });
    expect(concreteHandle).toEqual({
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
  it("sends ordinary config while omitting all write-only secret UI state", () => {
    const data = createWorkflowNodeData(genericNodeSpec);
    data.config = {
      base_url: "https://api.openai.com/v1",
      model: "gpt-5-mini",
      bounds: [19.75, 49.97, 19.82, 50.03],
    };
    data.secretStatuses = { api_key: { state: "configured" } };
    data.secretInputReadiness = { api_key: true };
    data.secretInputScope = "graph-1:2";
    data.onApplyNodeSecret = async () => true;
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
    expect(request).not.toHaveProperty("secretStatuses");
    expect(request).not.toHaveProperty("secretInputReadiness");
    expect(request).not.toHaveProperty("secretInputScope");
    expect(request).not.toHaveProperty("onApplyNodeSecret");
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

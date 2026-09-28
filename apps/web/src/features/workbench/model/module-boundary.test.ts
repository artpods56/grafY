import { describe, expect, it } from "vitest";

import type { NodeSpec, Port } from "@/lib/api";
import {
  WORKFLOW_NODE_TYPE,
  createWorkflowNodeData,
  type WorkflowEdge,
} from "../canvas/types";
import type { WorkflowNode } from "./execution-plan";
import { moduleBoundaries } from "./module-boundary";

function port(name: string, direction: Port["direction"]): Port {
  return {
    name,
    title: name,
    description: null,
    direction,
    artifact_type: { id: "text.value", schema_version: 1 },
    shape: "one",
    accepted_shapes: ["one"],
    instance_plugs: false,
    variadic: false,
    required: false,
  };
}

function nodeSpec(operatorId: string): NodeSpec {
  return {
    operator_id: operatorId,
    operator_version: 1,
    plugin_slug: "test",
    origin: "builtin",
    title: operatorId,
    description: operatorId,
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: [port("value", "input")],
    outputs: [port("value", "output")],
  };
}

function node(
  id: string,
  operatorId: string,
  options: {
    config?: Record<string, unknown>;
    artifactType?: { id: string; schema_version: number } | null;
  } = {},
): WorkflowNode {
  const data = createWorkflowNodeData(nodeSpec(operatorId), []);
  data.config = { ...data.config, ...options.config };
  data.artifactTypeBindings = options.artifactType
    ? { T: options.artifactType }
    : {};
  return {
    id,
    type: WORKFLOW_NODE_TYPE,
    position: { x: 0, y: 0 },
    selected: false,
    data,
  };
}

function edge(
  source: string,
  target: string,
  options: { enabled?: boolean } = {},
): WorkflowEdge {
  return {
    id: `${source}->${target}`,
    source,
    sourceHandle: null,
    target,
    targetHandle: null,
    data: {
      enabled: options.enabled ?? true,
      collectionMode: "direct",
      conversionPath: [],
    },
  };
}

describe("moduleBoundaries", () => {
  it("ignores every operator that is not a module boundary", () => {
    const summaries = moduleBoundaries(
      [node("step-1", "text.concat"), node("entry", "module.input")],
      [],
    );

    expect(summaries).toEqual([
      {
        id: "entry",
        direction: "input",
        portName: null,
        description: null,
        artifactType: null,
        connectionCount: 0,
      },
    ]);
  });

  it("reports the declared public name, description, and bound artifact type", () => {
    const summaries = moduleBoundaries(
      [
        node("exit", "module.output", {
          config: { public_name: "score", description: "Model score" },
          artifactType: { id: "integer.value", schema_version: 3 },
        }),
      ],
      [],
    );

    expect(summaries).toEqual([
      {
        id: "exit",
        direction: "output",
        portName: "score",
        description: "Model score",
        artifactType: "integer.value@3",
        connectionCount: 0,
      },
    ]);
  });

  it("counts only live connections on the boundary side", () => {
    const summaries = moduleBoundaries(
      [node("entry", "module.input"), node("exit", "module.output")],
      [
        edge("entry", "step-1"),
        edge("entry", "step-2", { enabled: false }),
        edge("step-1", "exit"),
        edge("entry", "exit"),
      ],
    );

    expect(
      summaries.map((summary) => `${summary.id}:${summary.connectionCount}`),
    ).toEqual(["entry:2", "exit:2"]);
  });
});

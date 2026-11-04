import { describe, expect, it } from "vitest";

import { encodeHandleId } from "../canvas/handles";
import {
  WORKFLOW_NODE_TYPE,
  createWorkflowNodeData,
  type WorkflowEdge,
  type WorkflowInputPlug,
  type WorkflowNodeData,
} from "../canvas/types";
import type { NodeSpec, Port, RunNodeResult } from "@/lib/api";
import {
  runTargetsFor,
  executionSubgraphFor,
  executionValidationIssue,
  missingRequiredInputsFor,
  selectedNodeAndAncestorIds,
  type WorkflowNode,
} from "./execution-plan";

interface PortOptions {
  required?: boolean;
  instancePlugs?: boolean;
  shape?: Port["shape"];
}

function port(
  name: string,
  direction: Port["direction"],
  options: PortOptions = {},
): Port {
  const shape = options.shape ?? "one";
  return {
    name,
    title: name,
    description: null,
    direction,
    artifact_type: { id: "test.artifact", schema_version: 1 },
    shape,
    accepted_shapes: [shape],
    instance_plugs: options.instancePlugs ?? false,
    variadic: false,
    required: options.required ?? true,
  };
}

function nodeSpec(
  operatorId: string,
  inputs: readonly Port[] = [],
  outputs: readonly Port[] = [port("result", "output")],
  title = operatorId,
): NodeSpec {
  return {
    operator_id: operatorId,
    operator_version: 1,
    plugin_slug: "test",
    origin: "builtin",
    title,
    description: title,
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs,
    outputs,
  };
}

function unsupportedCompatibility(
  nodeId: string,
  operatorId: string,
): Exclude<WorkflowNodeData["compatibility"], { status: "supported" }> {
  return {
    status: "unsupported",
    issues: [`Operator ${operatorId}@1 is unavailable.`],
    inputs: [],
    outputs: [{ portName: "result" }],
    persistedNode: {
      id: nodeId,
      kind: "builtin",
      operator_id: operatorId,
      operator_version: 1,
      config: {},
      position: { x: 0, y: 0 },
      input_plugs: [],
      artifact_type_bindings: [],
    },
  };
}

interface WorkflowNodeOptions {
  selected?: boolean;
  inputPlugs?: readonly WorkflowInputPlug[];
  run?: RunNodeResult | null;
  config?: Record<string, unknown>;
  compatibility?: WorkflowNodeData["compatibility"];
}

function workflowNode(
  id: string,
  spec: NodeSpec = nodeSpec(id),
  options: WorkflowNodeOptions = {},
): WorkflowNode {
  const inputPlugs = options.inputPlugs ?? [];
  const data = createWorkflowNodeData(
    spec,
    inputPlugs.map((plug) => ({ id: plug.id, port: plug.portName })),
  );
  data.run = options.run ?? null;
  data.config = options.config ?? data.config;
  data.compatibility = options.compatibility ?? data.compatibility;
  return {
    id,
    type: WORKFLOW_NODE_TYPE,
    position: { x: 0, y: 0 },
    selected: options.selected ?? false,
    data,
  };
}

interface WorkflowEdgeOptions {
  id?: string;
  sourcePort?: string;
  targetPort?: string;
  targetPlug?: string;
  enabled?: boolean;
  collectionMode?: "direct" | "map";
  sourceHandle?: string | null;
  targetHandle?: string | null;
  projection?: { path: readonly string[] };
  conversionPath?: readonly { id: string; version: number }[];
}

function outputHandle(portName: string): string {
  return encodeHandleId({
    portName,
    artifactTypeId: "test.artifact",
    schemaVersion: 1,
    shape: "one",
    direction: "output",
  });
}

function inputHandle(portName: string, plugId?: string): string {
  return encodeHandleId({
    portName,
    artifactTypeId: "test.artifact",
    schemaVersion: 1,
    shape: "one",
    direction: "input",
    ...(plugId ? { plugId } : {}),
  });
}

function workflowEdge(
  source: string,
  target: string,
  options: WorkflowEdgeOptions = {},
): WorkflowEdge {
  const sourcePort = options.sourcePort ?? "result";
  const targetPort = options.targetPort ?? "input";
  const sourceHandle =
    "sourceHandle" in options
      ? (options.sourceHandle ?? null)
      : outputHandle(sourcePort);
  const targetHandle =
    "targetHandle" in options
      ? (options.targetHandle ?? null)
      : inputHandle(targetPort, options.targetPlug);
  return {
    id: options.id ?? `${source}-${sourcePort}-${target}-${targetPort}`,
    source,
    sourceHandle,
    target,
    targetHandle,
    data: {
      enabled: options.enabled ?? true,
      collectionMode: options.collectionMode ?? "direct",
      conversionPath: options.conversionPath ?? [],
      ...(options.projection ? { projection: options.projection } : {}),
    },
  };
}

const artifactValue = {
  artifact_id: "00000000-0000-4000-8000-000000000001",
  artifact_type: "test.artifact",
  content_hash: null,
  schema_version: 1,
} as const;

function succeededRun(
  nodeId: string,
  outputPorts: readonly string[],
): RunNodeResult {
  return {
    node_id: nodeId,
    status: "succeeded",
    outputs: outputPorts.map((outputPort) => ({
      port: outputPort,
      kind: "single" as const,
      value: artifactValue,
      artifacts: [],
    })),
    error: null,
    result_fingerprint: `fp-${nodeId}`,
    created_at: "2026-07-20T08:00:00Z",
  };
}

describe("execution subgraphs", () => {
  it("runs every node with enabled edges only for the all scope", () => {
    const source = workflowNode("source");
    const target = workflowNode("target");
    const enabled = workflowEdge("source", "target", { id: "enabled" });
    const disabled = workflowEdge("source", "target", {
      id: "disabled",
      enabled: false,
    });

    const execution = executionSubgraphFor(
      "all",
      [source, target],
      [enabled, disabled],
    );

    expect([...execution.nodeIds]).toEqual(["source", "target"]);
    expect(execution.nodes.map((node) => node.id)).toEqual([
      "source",
      "target",
    ]);
    expect(execution.edges.map((edge) => edge.id)).toEqual(["enabled"]);
  });

  it("keeps active incoming edges but excludes outgoing edges for a selection", () => {
    const source = workflowNode("source");
    const target = workflowNode("target", nodeSpec("target"), {
      selected: true,
    });
    const downstream = workflowNode("downstream");
    const incoming = workflowEdge("source", "target", { id: "incoming" });
    const outgoing = workflowEdge("target", "downstream", { id: "outgoing" });
    const disabledIncoming = workflowEdge("source", "target", {
      id: "disabled-incoming",
      enabled: false,
    });

    const execution = executionSubgraphFor(
      "selected",
      [source, target, downstream],
      [incoming, outgoing, disabledIncoming],
    );

    expect([...execution.nodeIds]).toEqual(["target"]);
    expect(execution.nodes.map((node) => node.id)).toEqual(["target"]);
    expect(execution.edges.map((edge) => edge.id)).toEqual(["incoming"]);
  });

  it("walks enabled upstream dependencies without following outgoing branches", () => {
    const source = workflowNode("source");
    const middle = workflowNode("middle");
    const target = workflowNode("target", nodeSpec("target"), {
      selected: true,
    });
    const disabledSource = workflowNode("disabled-source");
    const downstream = workflowNode("downstream");
    const edges = [
      workflowEdge("source", "middle", { id: "source-middle" }),
      workflowEdge("middle", "target", { id: "middle-target" }),
      workflowEdge("disabled-source", "target", {
        id: "disabled-source-target",
        enabled: false,
      }),
      workflowEdge("target", "downstream", { id: "target-downstream" }),
      workflowEdge("unknown", "middle", { id: "unknown-middle" }),
    ];

    const execution = executionSubgraphFor(
      "selected-with-dependencies",
      [source, middle, target, disabledSource, downstream],
      edges,
    );

    expect([...execution.nodeIds]).toEqual(["target", "middle", "source"]);
    expect(execution.nodes.map((node) => node.id)).toEqual([
      "source",
      "middle",
      "target",
    ]);
    expect(execution.edges.map((edge) => edge.id)).toEqual([
      "source-middle",
      "middle-target",
    ]);
  });

  it("terminates ancestor traversal across cycles", () => {
    const first = workflowNode("first", nodeSpec("first"), {
      selected: true,
    });
    const second = workflowNode("second");

    expect([
      ...selectedNodeAndAncestorIds(
        [first, second],
        [workflowEdge("first", "second"), workflowEdge("second", "first")],
      ),
    ]).toEqual(["first", "second"]);
  });
});

describe("required execution inputs", () => {
  it("ignores optional ports and disabled connections", () => {
    const targetSpec = nodeSpec("target", [
      port("required", "input"),
      port("optional", "input", { required: false }),
    ]);
    const target = workflowNode("target", targetSpec);
    const disabled = workflowEdge("source", "target", {
      targetPort: "required",
      enabled: false,
    });

    expect(missingRequiredInputsFor([target], [disabled])).toEqual([
      {
        nodeId: "target",
        nodeTitle: "target",
        portName: "required",
      },
    ]);
    expect(
      missingRequiredInputsFor(
        [target],
        [workflowEdge("source", "target", { targetPort: "required" })],
      ),
    ).toEqual([]);
  });

  it("reports empty and individually disconnected required input plugs", () => {
    const collectSpec = nodeSpec("collect", [
      port("items", "input", { instancePlugs: true }),
    ]);
    const withoutPlugs = workflowNode("without-plugs", collectSpec);
    const withPlugs = workflowNode("with-plugs", collectSpec, {
      inputPlugs: [
        { id: "plug-one", portName: "items" },
        { id: "plug-two", portName: "items" },
      ],
    });
    const connectedSecondPlug = workflowEdge("source", "with-plugs", {
      targetPort: "items",
      targetPlug: "plug-two",
    });

    expect(missingRequiredInputsFor([withoutPlugs], [])).toEqual([
      {
        nodeId: "without-plugs",
        nodeTitle: "collect",
        portName: "items",
      },
    ]);
    expect(
      missingRequiredInputsFor([withPlugs], [connectedSecondPlug]),
    ).toEqual([
      {
        nodeId: "with-plugs",
        nodeTitle: "collect",
        portName: "items input 1",
      },
    ]);
  });
});

describe("execution validation", () => {
  it.each([
    ["all" as const, "Add at least one node before running the workflow."],
    [
      "selected" as const,
      "Select at least one node before running a selection.",
    ],
    [
      "selected-with-dependencies" as const,
      "Select at least one node before running a selection.",
    ],
  ])("reports the empty %s scope", (scope, message) => {
    expect(executionValidationIssue(scope, [], [])).toEqual({
      nodeId: null,
      message,
    });
  });

  it("blocks an unsupported node only when it belongs to the execution scope", () => {
    const unsupported = workflowNode("legacy", nodeSpec("legacy"), {
      compatibility: unsupportedCompatibility("legacy", "legacy"),
    });
    const healthy = workflowNode("healthy", nodeSpec("healthy"), {
      selected: true,
    });
    const selected = executionSubgraphFor(
      "selected",
      [unsupported, healthy],
      [],
    );
    const all = executionSubgraphFor("all", [unsupported, healthy], []);

    expect(
      executionValidationIssue("selected", selected.nodes, selected.edges),
    ).toBeNull();
    expect(executionValidationIssue("all", all.nodes, all.edges)).toEqual({
      nodeId: "legacy",
      message: "Cannot run legacy: Operator legacy@1 is unavailable.",
    });
  });

  it("blocks an unsupported upstream node when dependencies are requested", () => {
    const unsupported = workflowNode("legacy", nodeSpec("legacy"), {
      compatibility: unsupportedCompatibility("legacy", "legacy"),
    });
    const target = workflowNode("target", nodeSpec("target"), {
      selected: true,
    });
    const edge = workflowEdge("legacy", "target");
    const execution = executionSubgraphFor(
      "selected-with-dependencies",
      [unsupported, target],
      [edge],
    );

    expect(
      executionValidationIssue(
        "selected-with-dependencies",
        execution.nodes,
        execution.edges,
      ),
    ).toEqual({
      nodeId: "legacy",
      message: "Cannot run legacy: Operator legacy@1 is unavailable.",
    });
  });

  it("reports the first missing required input with its node context", () => {
    const target = workflowNode(
      "target",
      nodeSpec("target", [port("document", "input")], [], "Summarize"),
    );

    expect(executionValidationIssue("all", [target], [])).toEqual({
      nodeId: "target",
      message: "Summarize.document is required but unconnected in this run.",
    });
  });
});

describe("run targets", () => {
  it("names every node of the Graph when the whole Graph is run", () => {
    const source = workflowNode("source");
    const target = workflowNode("target", nodeSpec("target"));
    const execution = executionSubgraphFor(
      "all",
      [source, target],
      [workflowEdge("source", "target")],
    );

    expect(runTargetsFor(execution)).toEqual([
      { node_id: "source", call_path: [] },
      { node_id: "target", call_path: [] },
    ]);
  });

  it("names only the selection, and leaves its upstream to the stored results", () => {
    // The upstream is deliberately unselected and holds a stored result: a Run
    // reads that result by fingerprint, so the browser ships no values at all.
    const source = workflowNode("source", nodeSpec("source"), {
      run: succeededRun("source", ["result"]),
    });
    const target = workflowNode("target", nodeSpec("target"), {
      selected: true,
    });
    const execution = executionSubgraphFor(
      "selected",
      [source, target],
      [workflowEdge("source", "target")],
    );

    expect(runTargetsFor(execution)).toEqual([
      { node_id: "target", call_path: [] },
    ]);
  });

  it("names the selection and its ancestors when dependencies were asked for", () => {
    const source = workflowNode("source");
    const collect = workflowNode(
      "collect",
      nodeSpec("collect", [port("items", "input", { instancePlugs: true })]),
      {
        selected: true,
        inputPlugs: [{ id: "active-plug", portName: "items" }],
      },
    );
    const execution = executionSubgraphFor(
      "selected-with-dependencies",
      [source, collect],
      [
        workflowEdge("source", "collect", {
          targetPort: "items",
          targetPlug: "active-plug",
        }),
      ],
    );

    expect(
      runTargetsFor(execution).map((candidate) => candidate.node_id),
    ).toEqual(["source", "collect"]);
  });

  it("names an empty selection as an empty demand, which validation refuses first", () => {
    const source = workflowNode("source");
    const execution = executionSubgraphFor("selected", [source], []);

    expect(runTargetsFor(execution)).toEqual([]);
    expect(executionValidationIssue("selected", [], [], [])).toEqual({
      nodeId: null,
      message: "Select at least one node before running a selection.",
    });
  });
});

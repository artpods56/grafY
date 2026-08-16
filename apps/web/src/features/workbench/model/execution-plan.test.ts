import { describe, expect, it } from "vitest";

import { encodeHandleId } from "../canvas/handles";
import {
  WORKFLOW_NODE_TYPE,
  createWorkflowNodeData,
  type WorkflowEdge,
  type GeneratedNodeDraftSummary,
  type WorkflowInputPlug,
  type WorkflowNodeData,
} from "../canvas/types";
import type { NodeSpec, Port, RunNodeResult } from "@/lib/api";
import {
  executionRequestPlan,
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
    title,
    description: title,
    catalog_visible: true,
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
): Exclude<
  WorkflowNodeData["compatibility"],
  { status: "supported" }
> {
  return {
    status: "unsupported",
    issues: [`Operator ${operatorId}@1 is unavailable.`],
    inputs: [],
    outputs: [{ portName: "result" }],
    persistedNode: {
      id: nodeId,
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
  generation?: GeneratedNodeDraftSummary;
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
  data.generation = options.generation ?? null;
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
  const sourceHandle = "sourceHandle" in options
    ? options.sourceHandle ?? null
    : outputHandle(sourcePort);
  const targetHandle = "targetHandle" in options
    ? options.targetHandle ?? null
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

    expect(
      [...selectedNodeAndAncestorIds(
        [first, second],
        [
          workflowEdge("first", "second"),
          workflowEdge("second", "first"),
        ],
      )],
    ).toEqual(["first", "second"]);
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
    const all = executionSubgraphFor(
      "all",
      [unsupported, healthy],
      [],
    );

    expect(
      executionValidationIssue(
        "selected",
        selected.nodes,
        selected.edges,
      ),
    ).toBeNull();
    expect(
      executionValidationIssue("all", all.nodes, all.edges),
    ).toEqual({
      nodeId: "legacy",
      message:
        "Cannot run legacy: Operator legacy@1 is unavailable.",
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
      message:
        "Cannot run legacy: Operator legacy@1 is unavailable.",
    });
  });

  it("keeps a typed draft connectable but blocks execution until publication", () => {
    const draftSpec: NodeSpec = {
      ...nodeSpec("generated.node.1"),
      agent_authoring: {
        draft_node_id: "draft-1",
        status: "authoring",
        runnable: false,
        release_revision: null,
      },
    };
    const draft = workflowNode("generated", draftSpec, {
      generation: {
        draftId: "draft-1",
        runId: "run-1",
        buildId: "build-1",
        threadId: "thread-1",
        environmentId: "environment-1",
        state: "testing",
        error: null,
        capabilities: null,
        capabilityDigest: null,
        capabilityApprovalId: null,
        releaseRevision: null,
        targetOperatorVersion: 1,
        lastEventSequence: 0,
      },
    });

    expect(executionValidationIssue("all", [draft], [])).toEqual({
      nodeId: "generated",
      message:
        "Cannot run generated.node.1: publish the generated node first.",
    });

    draft.data.generation = { ...draft.data.generation!, state: "published" };
    draft.data.spec = {
      ...draft.data.spec,
      agent_authoring: {
        ...draft.data.spec.agent_authoring!,
        status: "published",
        runnable: true,
        release_revision: 1,
      },
    };
    expect(executionValidationIssue("all", [draft], [])).toBeNull();
  });

  it("reports an empty image upload before required-input failures", () => {
    const missingInput = workflowNode(
      "missing-input",
      nodeSpec("missing-input", [port("input", "input")]),
    );
    const upload = workflowNode(
      "upload",
      nodeSpec("image.upload", [], [port("images", "output")], "Images"),
      { config: { uploads: [] } },
    );

    expect(
      executionValidationIssue("all", [missingInput, upload], []),
    ).toEqual({
      nodeId: "upload",
      message: "Choose images for Images before running.",
    });
  });

  it.each([
    ["gis.geojson.upload", "GeoJSON", "Choose a GeoJSON file"],
    ["gis.geotiff.upload", "Historical scan", "Choose a GeoTIFF file"],
    ["table.file.import", "Source table", "Choose a CSV or XLSX file"],
  ])("reports an empty %s upload", (operatorId, title, expectedMessage) => {
    const upload = workflowNode(
      "upload",
      nodeSpec(operatorId, [], [port("result", "output")], title),
      { config: { uploads: [] } },
    );

    expect(executionValidationIssue("all", [upload], [])).toEqual({
      nodeId: "upload",
      message: `${expectedMessage} for ${title} before running.`,
    });
  });

  it("reports the first missing required input with its node context", () => {
    const target = workflowNode(
      "target",
      nodeSpec("target", [port("document", "input")], [], "Summarize"),
    );

    expect(executionValidationIssue("all", [target], [])).toEqual({
      nodeId: "target",
      message:
        "Summarize.document is required but unconnected in this run.",
    });
  });
});

describe("execution request planning", () => {
  it("pins each external source port once and derives edge and plug DTOs", () => {
    const source = workflowNode("source", nodeSpec("source"), {
      run: succeededRun("source", ["result"]),
    });
    const collectSpec = nodeSpec("collect", [
      port("items", "input", { required: false, instancePlugs: true }),
    ]);
    const collect = workflowNode("collect", collectSpec, {
      selected: true,
      inputPlugs: [
        { id: "active-plug", portName: "items" },
        { id: "inactive-plug", portName: "items" },
      ],
    });
    const target = workflowNode(
      "target",
      nodeSpec("target", [port("input", "input")]),
      { selected: true },
    );
    const collectEdge = workflowEdge("source", "collect", {
      id: "collect-edge",
      targetPort: "items",
      targetPlug: "active-plug",
      collectionMode: "map",
      projection: { path: ["content"] },
      conversionPath: [{ id: "extract-text", version: 2 }],
    });
    const duplicateSourceEdge = workflowEdge("source", "target", {
      id: "target-edge",
    });
    const execution = executionSubgraphFor(
      "selected",
      [source, collect, target],
      [collectEdge, duplicateSourceEdge],
    );

    const plan = executionRequestPlan(
      "selected",
      [source, collect, target],
      execution,
    );

    expect(plan.status).toBe("ready");
    if (plan.status !== "ready") return;
    expect(plan.request.scope).toBe("selected");
    expect(plan.request.pinned_outputs).toEqual([
      {
        from_node: "source",
        from_port: "result",
        value: artifactValue,
      },
    ]);
    expect(plan.request.nodes.map((node) => node.id)).toEqual([
      "collect",
      "target",
    ]);
    expect(plan.request.nodes[0]?.input_plugs).toEqual([
      { id: "active-plug", port: "items" },
    ]);
    expect(plan.request.edges).toEqual([
      {
        from_node: "source",
        from_port: "result",
        to_node: "collect",
        to_port: "items",
        to_plug: "active-plug",
        collection_mode: "map",
        projection: { path: ["content"] },
        conversion_path: [{ id: "extract-text", version: 2 }],
      },
      {
        from_node: "source",
        from_port: "result",
        to_node: "target",
        to_port: "input",
        to_plug: null,
        collection_mode: "direct",
        projection: null,
        conversion_path: [],
      },
    ]);
  });

  it("uses a materialized output from an unsupported node outside the selected scope", () => {
    const unsupported = workflowNode("legacy", nodeSpec("legacy"), {
      run: succeededRun("legacy", ["result"]),
      compatibility: unsupportedCompatibility("legacy", "legacy"),
    });
    const target = workflowNode(
      "target",
      nodeSpec("target", [port("input", "input")]),
      { selected: true },
    );
    const edge = workflowEdge("legacy", "target", {
      sourceHandle: "$compatibility::output::result::",
    });
    edge.data = {
      ...edge.data,
      enabled: true,
      collectionMode: "direct",
      sourcePortName: "result",
      targetPortName: "input",
      targetPlugId: null,
      compatibilityIssues: ["legacy: Operator legacy@1 is unavailable."],
    };
    const execution = executionSubgraphFor(
      "selected",
      [unsupported, target],
      [edge],
    );

    expect(
      executionValidationIssue(
        "selected",
        execution.nodes,
        execution.edges,
      ),
    ).toBeNull();
    const plan = executionRequestPlan(
      "selected",
      [unsupported, target],
      execution,
    );

    expect(plan.status).toBe("ready");
    if (plan.status !== "ready") return;
    expect(plan.request.pinned_outputs).toEqual([
      {
        from_node: "legacy",
        from_port: "result",
        value: artifactValue,
      },
    ]);
    expect(plan.request.nodes.map((node) => node.id)).toEqual(["target"]);
    expect(plan.request.edges).toEqual([
      {
        from_node: "legacy",
        from_port: "result",
        to_node: "target",
        to_port: "input",
        to_plug: null,
        collection_mode: "direct",
        projection: null,
        conversion_path: [],
      },
    ]);
  });

  it("reports every unique external source port without materialized output", () => {
    const source = workflowNode(
      "source",
      nodeSpec(
        "source",
        [],
        [port("first", "output"), port("second", "output")],
        "Source",
      ),
    );
    const target = workflowNode("target", nodeSpec("target"), {
      selected: true,
    });
    const edges = [
      workflowEdge("source", "target", {
        id: "first-edge",
        sourcePort: "first",
      }),
      workflowEdge("source", "target", {
        id: "duplicate-first-edge",
        sourcePort: "first",
      }),
      workflowEdge("source", "target", {
        id: "second-edge",
        sourcePort: "second",
      }),
    ];
    const execution = executionSubgraphFor(
      "selected",
      [source, target],
      edges,
    );

    expect(
      executionRequestPlan("selected", [source, target], execution),
    ).toEqual({
      status: "invalid",
      message:
        "Cannot run the selection because no accessible materialized output is available for Source.first, Source.second. Select the missing upstream nodes too, or choose “Run with dependencies”.",
    });
  });

  it("rejects a selected incoming edge without both encoded handles", () => {
    const source = workflowNode("source", nodeSpec("source"), {
      run: succeededRun("source", ["result"]),
    });
    const target = workflowNode("target", nodeSpec("target"), {
      selected: true,
    });
    const malformed = workflowEdge("source", "target", {
      id: "malformed-edge",
      sourceHandle: null,
    });
    const execution = executionSubgraphFor(
      "selected",
      [source, target],
      [malformed],
    );

    expect(
      executionRequestPlan("selected", [source, target], execution),
    ).toEqual({
      status: "invalid",
      message:
        "Cannot run the selection because edge malformed-edge does not identify both source and target ports.",
    });
  });

  it("omits pins and malformed edges while retaining target plug activity for all", () => {
    const source = workflowNode("source");
    const collect = workflowNode(
      "collect",
      nodeSpec("collect", [
        port("items", "input", { required: false, instancePlugs: true }),
      ]),
      { inputPlugs: [{ id: "plug", portName: "items" }] },
    );
    const malformed = workflowEdge("source", "collect", {
      sourceHandle: null,
      targetPort: "items",
      targetPlug: "plug",
    });
    const execution = executionSubgraphFor(
      "all",
      [source, collect],
      [malformed],
    );

    const plan = executionRequestPlan(
      "all",
      [source, collect],
      execution,
    );

    expect(plan.status).toBe("ready");
    if (plan.status !== "ready") return;
    expect(plan.request.scope).toBe("all");
    expect(plan.request).not.toHaveProperty("pinned_outputs");
    expect(plan.request.edges).toEqual([]);
    expect(plan.request.nodes[1]?.input_plugs).toEqual([
      { id: "plug", port: "items" },
    ]);
  });
});

import { describe, expect, it } from "vitest";

import type {
  ArtifactRef,
  NodeRegistry,
  NodeSpec,
  Port,
  RunNodeResult,
  SavedGraphOrigin,
} from "@/lib/api";
import { encodeHandleId } from "../canvas/handles";
import {
  WORKFLOW_NODE_TYPE,
  createWorkflowNodeData,
  portMetaForPort,
  type WorkflowEdge,
} from "../canvas/types";
import {
  COLLECTION_OPERATOR_ID,
  COLLECTION_PORT,
  collectCardsCommands,
  collectDisabledReason,
  collectionHoldsArtifacts,
  collectionMembers,
  collectionSparePlugId,
  collectionsWithoutSpare,
  ungroupCollectionDisabledReason,
  ungroupedCollectionCards,
  type CollectionSource,
} from "./collection";
import { missingRequiredInputsFor, type WorkflowNode } from "./execution-plan";
import { catalogNodeSpecs } from "./node-catalog";

const IMAGE = { id: "file.png", schema_version: 1 };

function ref(id: string, type = IMAGE): ArtifactRef {
  return { artifact_id: id, artifact_type: type.id, schema_version: 1 };
}

function spec(
  operator_id: string,
  inputs: Port[],
  outputs: Port[],
  title = operator_id,
): NodeSpec {
  return {
    operator_id,
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

const collectSpec = spec(
  COLLECTION_OPERATOR_ID,
  [
    {
      name: COLLECTION_PORT,
      title: "items",
      description: null,
      direction: "input",
      artifact_type: null,
      artifact_type_variable: "T",
      shape: "one",
      accepted_shapes: ["one", "many"],
      instance_plugs: true,
      variadic: true,
      required: true,
    },
  ],
  [
    {
      name: COLLECTION_PORT,
      title: "items",
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
  "Collect",
);

const resizeSpec = spec(
  "image.resize",
  [],
  [
    {
      name: "image",
      title: "Resized",
      description: null,
      direction: "output",
      artifact_type: IMAGE,
      shape: "one",
      accepted_shapes: ["one"],
      instance_plugs: false,
      variadic: false,
      required: true,
    },
  ],
  "Resize image",
);

function node(
  id: string,
  nodeSpec: NodeSpec,
  plugs: string[] = [],
  run: RunNodeResult | null = null,
): WorkflowNode {
  const data = createWorkflowNodeData(
    nodeSpec,
    plugs.map((plug) => ({ id: plug, port: COLLECTION_PORT })),
  );
  data.run = run;
  if (nodeSpec === collectSpec) data.artifactTypeBindings = { T: IMAGE };
  return {
    id,
    type: WORKFLOW_NODE_TYPE,
    position: { x: 0, y: 0 },
    data,
  };
}

function plugEdge(
  source: string,
  target: string,
  plugId: string,
): WorkflowEdge {
  const itemsPort = collectSpec.inputs[0];
  return {
    id: `${source}->${plugId}`,
    source,
    sourceHandle: encodeHandleId(portMetaForPort(resizeSpec.outputs[0])),
    target,
    targetHandle: encodeHandleId(
      portMetaForPort(itemsPort, itemsPort.shape, plugId, { T: IMAGE }),
    ),
    data: { enabled: true, collectionMode: "direct", conversionPath: [] },
  };
}

function origin(plugId: string, value: ArtifactRef): SavedGraphOrigin {
  return {
    id: `origin-${plugId}`,
    to_node: "collection",
    to_port: COLLECTION_PORT,
    to_plug: plugId,
    value,
    collection_mode: "direct",
    conversion_path: [],
  };
}

const succeeded = (value: ArtifactRef): RunNodeResult =>
  ({
    status: "succeeded",
    outputs: [{ port: "image", kind: "single", value, artifacts: [value] }],
  }) as unknown as RunNodeResult;

describe("collectionMembers", () => {
  it("resolves each plug to a Library value, an output, or the spare", () => {
    const collection = node("collection", collectSpec, ["a", "b", "c", "d"]);
    const producer = node("resize", resizeSpec, [], succeeded(ref("made")));
    const idle = node("resize-2", resizeSpec);
    const members = collectionMembers(
      collection,
      [collection, producer, idle],
      [
        plugEdge("resize", "collection", "b"),
        plugEdge("resize-2", "collection", "c"),
      ],
      [origin("a", ref("lib-1"))],
    );

    expect(members.map((member) => member.kind)).toEqual([
      "library",
      "output",
      "output",
      "empty",
    ]);
    expect(members[0]).toMatchObject({ refs: [ref("lib-1")] });
    expect(members[1]).toMatchObject({
      label: "Resize image → Resized",
      refs: [ref("made")],
    });
    // Not produced yet: the member is known, its artifacts are not.
    expect(members[2]).toMatchObject({ refs: null });
    expect(collectionSparePlugId(members)).toBe("d");
  });

  it("finds collections whose every plug is taken", () => {
    const full = node("collection", collectSpec, ["a"]);
    const roomy = node("other", collectSpec, ["x"]);
    expect(
      collectionsWithoutSpare([full, roomy], [], [origin("a", ref("lib-1"))]),
    ).toEqual(["collection"]);
  });
});

describe("collecting cards", () => {
  const library = (id: string, x: number, y: number): CollectionSource => ({
    kind: "library",
    cardId: `card-${id}`,
    position: { x, y },
    value: ref(id),
  });
  const output = (x: number, y: number): CollectionSource => ({
    kind: "output",
    cardId: "card-fed",
    position: { x, y },
    sourceNodeId: "resize",
    sourcePortName: "image",
  });

  it("gathers Library cards and a card on an output into one collection", () => {
    const producer = node("resize", resizeSpec);
    const plan = collectCardsCommands({
      sources: [
        output(400, 0),
        library("lib-2", 0, 200),
        library("lib-1", 0, 0),
      ],
      nodes: [producer],
      collectSpec,
      createNodeData: (nodeSpec, plugs) =>
        createWorkflowNodeData(nodeSpec, plugs),
    });
    if (!plan) throw new Error("expected a plan");

    const [addNode, ...rest] = plan.commands;
    if (addNode.kind !== "add_node") throw new Error("expected add_node");
    // Three members in reading order, plus the spare.
    expect(addNode.node.input_plugs).toHaveLength(4);
    expect(addNode.node.operator_id).toBe(COLLECTION_OPERATOR_ID);
    expect(addNode.node.artifact_type_bindings).toEqual([
      { variable: "T", artifact_type: IMAGE },
    ]);
    const plugs = addNode.node.input_plugs.map((plug) => plug.id);
    expect(rest.map((command) => command.kind)).toEqual([
      "add_origin",
      "add_edge",
      "add_origin",
    ]);
    const [first, wire, last] = rest;
    if (
      first.kind !== "add_origin" ||
      wire.kind !== "add_edge" ||
      last.kind !== "add_origin"
    ) {
      throw new Error("unexpected commands");
    }
    expect(first.origin).toMatchObject({
      to_plug: plugs[0],
      value: ref("lib-1"),
    });
    expect(wire.edge).toMatchObject({
      from_node: "resize",
      from_port: "image",
      to_node: plan.collectionId,
      to_plug: plugs[1],
    });
    expect(last.origin).toMatchObject({
      to_plug: plugs[2],
      value: ref("lib-2"),
    });
    expect([...plan.removedCardIds].sort()).toEqual(
      ["card-fed", "card-lib-1", "card-lib-2"].sort(),
    );
  });

  it("never repeats a member", () => {
    const producer = node("resize", resizeSpec);
    const plan = collectCardsCommands({
      sources: [
        library("lib-1", 0, 0),
        { ...library("lib-1", 300, 0), cardId: "card-lib-1-again" },
        output(0, 400),
        { ...output(300, 400), cardId: "card-fed-again" },
      ],
      nodes: [producer],
      collectSpec,
      createNodeData: (nodeSpec, plugs) =>
        createWorkflowNodeData(nodeSpec, plugs),
    });
    if (!plan) throw new Error("expected a plan");
    const [addNode, ...members] = plan.commands;
    if (addNode.kind !== "add_node") throw new Error("expected add_node");
    // One Library member, one output member, and the spare.
    expect(addNode.node.input_plugs).toHaveLength(3);
    expect(members.map((command) => command.kind)).toEqual([
      "add_origin",
      "add_edge",
    ]);
    // Every selected card is replaced, repeats included.
    expect(plan.removedCardIds).toHaveLength(4);
  });

  it("knows which artifacts a collection already holds", () => {
    const members = [
      {
        plugId: "a",
        kind: "library" as const,
        originId: "o",
        refs: [ref("x")],
      },
      { plugId: "b", kind: "empty" as const },
    ];
    expect(collectionHoldsArtifacts(members, [ref("x")])).toBe(true);
    expect(collectionHoldsArtifacts(members, [ref("x"), ref("y")])).toBe(false);
    expect(collectionHoldsArtifacts(members, [])).toBe(false);
  });

  it("refuses mixed types and a single card", () => {
    expect(collectDisabledReason([library("a", 0, 0)], [])).toMatch(
      /two or more/,
    );
    const table: CollectionSource = {
      kind: "library",
      cardId: "table",
      position: { x: 0, y: 0 },
      value: ref("t", { id: "table.data", schema_version: 1 }),
    };
    expect(collectDisabledReason([library("a", 0, 0), table], [])).toMatch(
      /one type/,
    );
  });
});

describe("ungrouping a collection", () => {
  it("turns members back into cards and skips the spare", () => {
    const cards = ungroupedCollectionCards(
      { x: 10, y: 20 },
      [
        { plugId: "a", kind: "library", originId: "o", refs: [ref("lib-1")] },
        {
          plugId: "b",
          kind: "output",
          edgeId: "e",
          sourceNodeId: "resize",
          sourcePortName: "image",
          label: "Resize image → Resized",
          refs: null,
        },
        { plugId: "c", kind: "empty" },
      ],
      250,
      190,
    );
    expect(cards).toEqual([
      { kind: "library", position: { x: 10, y: 20 }, value: ref("lib-1") },
      {
        kind: "output",
        position: { x: 10 + 250 + 64, y: 20 },
        sourceNodeId: "resize",
        sourcePortName: "image",
      },
    ]);
  });

  it("waits until nothing reads the collection's output", () => {
    const downstream: WorkflowEdge = {
      id: "out",
      source: "collection",
      target: "sink",
      sourceHandle: null,
      targetHandle: null,
    };
    expect(ungroupCollectionDisabledReason("collection", [downstream])).toMatch(
      /Disconnect/,
    );
    expect(ungroupCollectionDisabledReason("collection", [])).toBeNull();
  });
});

describe("collections elsewhere", () => {
  it("run with a spare plug once one member is in", () => {
    const collection = node("collection", collectSpec, ["a", "spare"]);
    expect(
      missingRequiredInputsFor([collection], [], [origin("a", ref("lib-1"))]),
    ).toEqual([]);
    expect(missingRequiredInputsFor([collection], [], [])).toHaveLength(1);
  });

  it("are not offered in the node catalog", () => {
    const registry = {
      nodes: [collectSpec, resizeSpec],
    } as unknown as NodeRegistry;
    expect(
      catalogNodeSpecs(registry, null).map(
        (candidate) => candidate.operator_id,
      ),
    ).toEqual(["image.resize"]);
  });
});

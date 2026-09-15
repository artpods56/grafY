// @vitest-environment jsdom

import { describe, expect, it } from "vitest";

import type { ArtifactConversionSpec, Port, SavedGraphOrigin } from "@/lib/api";
import { encodeHandleId } from "../canvas/handles";
import type { WorkflowEdge } from "../canvas/types";
import {
  ARTIFACT_DROP_DATA_TYPE,
  artifactDropCommands,
  artifactDropTargetFromRow,
  isArtifactDrop,
  readArtifactDrop,
  resolveArtifactDrop,
  writeArtifactDrop,
  type ArtifactDropGraphState,
  type ArtifactDropTarget,
} from "./artifact-drop";

type DropValue = SavedGraphOrigin["value"];
type ArtifactRef = Extract<DropValue, { artifact_id: string }>;
type ArtifactRefSequence = Extract<
  DropValue,
  { item_refs: readonly unknown[] }
>;

const TARGET: ArtifactDropTarget = {
  nodeId: "node-a",
  portName: "input",
  plugId: null,
};

function ref(id: string): ArtifactRef {
  return {
    artifact_id: `artifact-${id}`,
    artifact_type: id,
    schema_version: 1,
  };
}

/** One table artifact reference, distinguished by artifact id. */
function item(artifactId: string): ArtifactRef {
  return { artifact_id: artifactId, artifact_type: "table", schema_version: 1 };
}

function sequence(...artifactIds: string[]): ArtifactRefSequence {
  return {
    artifact_type: "table",
    schema_version: 1,
    item_refs: artifactIds.map((artifactId) => item(artifactId)),
    ordered: true,
    index_key: "order_index",
    sequence_id: "sequence-1",
  };
}

function port(overrides: Partial<Port> = {}): Port {
  return {
    name: "input",
    title: null,
    description: null,
    direction: "input",
    artifact_type: { id: "table", schema_version: 1 },
    artifact_type_variable: null,
    shape: "one",
    accepted_shapes: ["one"],
    also_accepts: [],
    instance_plugs: false,
    required: true,
    variadic: false,
    ...overrides,
  };
}

function conversion(
  id: string,
  source: string,
  target: string,
): ArtifactConversionSpec {
  return {
    key: { id, version: 1 },
    source_artifact_type: { id: source, schema_version: 1 },
    target_artifact_type: { id: target, schema_version: 1 },
    title: id,
  };
}

function origin(overrides: Partial<SavedGraphOrigin> = {}): SavedGraphOrigin {
  return {
    id: "origin-1",
    to_node: "node-a",
    to_port: "input",
    to_plug: null,
    value: ref("table"),
    conversion_path: [],
    ...overrides,
  };
}

function edge(overrides: Partial<WorkflowEdge> = {}): WorkflowEdge {
  return {
    id: "edge-1",
    source: "node-b",
    target: "node-a",
    sourceHandle: encodeHandleId({
      portName: "output",
      artifactTypeId: "table",
      schemaVersion: 1,
      shape: "one",
      direction: "output",
    }),
    targetHandle: encodeHandleId({
      portName: "input",
      artifactTypeId: "table",
      schemaVersion: 1,
      shape: "one",
      direction: "input",
    }),
    data: { enabled: true, collectionMode: "direct" },
    ...overrides,
  };
}

function state(
  overrides: Partial<ArtifactDropGraphState> = {},
): ArtifactDropGraphState {
  return {
    edges: [],
    origins: [],
    conversions: [],
    ...overrides,
  };
}

describe("artifact drop payload", () => {
  function dataTransferStub(): DataTransfer {
    const store = new Map<string, string>();
    return {
      types: [ARTIFACT_DROP_DATA_TYPE],
      effectAllowed: "none",
      dropEffect: "none",
      setData: (type: string, value: string) => {
        store.set(type, value);
      },
      getData: (type: string) => store.get(type) ?? "",
    } as unknown as DataTransfer;
  }

  it("round-trips a single artifact reference", () => {
    const dataTransfer = dataTransferStub();
    writeArtifactDrop(dataTransfer, ref("table"));

    expect(isArtifactDrop(dataTransfer)).toBe(true);
    expect(readArtifactDrop(dataTransfer)).toEqual({
      value: ref("table"),
      shape: "one",
    });
  });

  it("round-trips a sequence as the many shape", () => {
    const dataTransfer = dataTransferStub();
    writeArtifactDrop(dataTransfer, sequence("a", "b"));

    expect(readArtifactDrop(dataTransfer)).toEqual({
      value: sequence("a", "b"),
      shape: "many",
    });
  });

  it("ignores a drag that carries no Grafy artifact", () => {
    expect(readArtifactDrop(dataTransferStub())).toBeNull();
  });
});

describe("artifact drop target identity", () => {
  it("reads a plain input port row from its own element", () => {
    const row = document.createElement("div");
    row.dataset.inputNodeId = "node-a";
    row.dataset.inputPortName = "input";

    expect(artifactDropTargetFromRow(row)).toEqual({
      nodeId: "node-a",
      portName: "input",
      plugId: null,
    });
  });

  it("reads the plug a row currently publishes, not a stale handle", () => {
    const row = document.createElement("div");
    row.dataset.inputNodeId = "node-a";
    row.dataset.inputPlugId = "plug-2";
    row.dataset.inputPlugPort = "input";
    row.dataset.handleid = "input::table::1::one::input::plug-1";

    expect(artifactDropTargetFromRow(row)).toEqual({
      nodeId: "node-a",
      portName: "input",
      plugId: "plug-2",
    });
  });

  it("refuses a row that names no node", () => {
    const row = document.createElement("div");
    row.dataset.inputPortName = "input";

    expect(artifactDropTargetFromRow(row)).toBeNull();
  });
});

describe("artifact drop acceptance", () => {
  it("accepts an exact accepted type", () => {
    expect(
      resolveArtifactDrop(
        { value: ref("table"), shape: "one" },
        port(),
        {},
        [],
      ),
    ).toEqual({ conversionPath: [] });
  });

  it("accepts another type in the port's declared accepted set", () => {
    const target = port({
      also_accepts: [{ id: "csv", schema_version: 1 }],
    });

    expect(
      resolveArtifactDrop({ value: ref("csv"), shape: "one" }, target, {}, []),
    ).toEqual({ conversionPath: [] });
  });

  it("prefers the exact accepted type over a declared conversion", () => {
    const target = port({ also_accepts: [{ id: "csv", schema_version: 1 }] });

    expect(
      resolveArtifactDrop({ value: ref("table"), shape: "one" }, target, {}, [
        conversion("to-csv", "table", "csv"),
      ]),
    ).toEqual({ conversionPath: [] });
  });

  it("auto-selects one unique shortest declared conversion", () => {
    const conversions = [
      conversion("to-table", "csv", "table"),
      conversion("unrelated", "image", "table"),
    ];

    expect(
      resolveArtifactDrop(
        { value: ref("csv"), shape: "one" },
        port(),
        {},
        conversions,
      ),
    ).toEqual({ conversionPath: [{ id: "to-table", version: 1 }] });
  });

  it("refuses two equally short conversions instead of choosing one", () => {
    const conversions = [
      conversion("a", "csv", "table"),
      conversion("b", "csv", "table"),
    ];

    expect(
      resolveArtifactDrop(
        { value: ref("csv"), shape: "one" },
        port(),
        {},
        conversions,
      ),
    ).toBeNull();
  });

  it("refuses when only a projection could reach the port", () => {
    // A projection is a titled choice among several nested fields, and a drop
    // is a single gesture, so the resolver never sees projections at all.
    expect(
      resolveArtifactDrop(
        { value: ref("customer.record"), shape: "one" },
        port({ artifact_type: { id: "scalar.text", schema_version: 1 } }),
        {},
        [],
      ),
    ).toBeNull();
  });

  it("refuses a shape the port does not accept", () => {
    expect(
      resolveArtifactDrop(
        { value: sequence("a"), shape: "many" },
        port({ accepted_shapes: ["one"] }),
        {},
        [],
      ),
    ).toBeNull();
  });

  it("resolves a bound generic port from its artifact type binding", () => {
    const generic = port({
      artifact_type: null,
      artifact_type_variable: "Artifact::T",
    });

    expect(
      resolveArtifactDrop(
        { value: ref("table"), shape: "one" },
        generic,
        {
          "Artifact::T": { id: "table", schema_version: 1 },
        },
        [],
      ),
    ).toEqual({ conversionPath: [] });
  });
});

describe("artifact drop commands", () => {
  it("writes one origin through the collaboration vocabulary", () => {
    const commands = artifactDropCommands(
      { value: ref("table"), shape: "one" },
      TARGET,
      port(),
      {},
      state(),
    );

    expect(commands).toHaveLength(1);
    expect(commands?.[0]).toMatchObject({
      kind: "add_origin",
      origin: {
        to_node: "node-a",
        to_port: "input",
        to_plug: null,
        value: ref("table"),
        conversion_path: [],
      },
    });
  });

  it("records the selected conversion path on the origin", () => {
    const commands = artifactDropCommands(
      { value: ref("csv"), shape: "one" },
      TARGET,
      port(),
      {},
      state({ conversions: [conversion("to-table", "csv", "table")] }),
    );

    expect(commands?.[0]).toMatchObject({
      kind: "add_origin",
      origin: { conversion_path: [{ id: "to-table", version: 1 }] },
    });
  });

  it("removes an enabled edge on the same slot before placing the origin", () => {
    const commands = artifactDropCommands(
      { value: ref("table"), shape: "one" },
      TARGET,
      port(),
      {},
      state({ edges: [edge()] }),
    );

    expect(commands?.map((command) => command.kind)).toEqual([
      "remove_edges",
      "add_origin",
    ]);
    expect(commands?.[0]).toEqual({
      kind: "remove_edges",
      edge_ids: ["edge-1"],
    });
  });

  it("leaves a disabled edge beside the origin", () => {
    const commands = artifactDropCommands(
      { value: ref("table"), shape: "one" },
      TARGET,
      port(),
      {},
      state({
        edges: [edge({ data: { enabled: false, collectionMode: "direct" } })],
      }),
    );

    expect(commands?.map((command) => command.kind)).toEqual(["add_origin"]);
  });

  it("leaves an edge on another slot of the same node alone", () => {
    const commands = artifactDropCommands(
      { value: ref("table"), shape: "one" },
      TARGET,
      port(),
      {},
      state({
        edges: [
          edge({
            targetHandle: encodeHandleId({
              portName: "other",
              artifactTypeId: "table",
              schemaVersion: 1,
              shape: "one",
              direction: "input",
            }),
          }),
        ],
      }),
    );

    expect(commands?.map((command) => command.kind)).toEqual(["add_origin"]);
  });

  it("targets the plug row when the input takes instance plugs", () => {
    const target: ArtifactDropTarget = {
      nodeId: "node-a",
      portName: "items",
      plugId: "plug-2",
    };
    const commands = artifactDropCommands(
      { value: ref("table"), shape: "one" },
      target,
      port({
        name: "items",
        instance_plugs: true,
        shape: "many",
        accepted_shapes: ["one", "many"],
      }),
      {},
      state({
        edges: [
          edge({
            targetHandle: encodeHandleId({
              portName: "items",
              artifactTypeId: "table",
              schemaVersion: 1,
              shape: "many",
              direction: "input",
              plugId: "plug-2",
            }),
          }),
        ],
      }),
    );

    expect(commands?.map((command) => command.kind)).toEqual([
      "remove_edges",
      "add_origin",
    ]);
    expect(commands?.[1]).toMatchObject({
      kind: "add_origin",
      origin: { to_plug: "plug-2", to_port: "items" },
    });
  });

  it("replaces the origin already on the slot instead of adding a second", () => {
    const commands = artifactDropCommands(
      { value: ref("csv"), shape: "one" },
      TARGET,
      port({ also_accepts: [{ id: "csv", schema_version: 1 }] }),
      {},
      state({ origins: [origin()] }),
    );

    expect(commands).toEqual([
      {
        kind: "update_origin",
        origin_id: "origin-1",
        update: {
          value: ref("csv"),
          conversion_path: [],
        },
      },
    ]);
  });

  it("refuses a type the port does not accept without touching the graph", () => {
    const commands = artifactDropCommands(
      { value: ref("image"), shape: "one" },
      TARGET,
      port(),
      {},
      state({ edges: [edge()], origins: [origin()] }),
    );

    expect(commands).toBeNull();
  });

  it("refuses an ambiguous conversion without touching the graph", () => {
    const commands = artifactDropCommands(
      { value: ref("csv"), shape: "one" },
      TARGET,
      port(),
      {},
      state({
        edges: [edge()],
        origins: [origin()],
        conversions: [
          conversion("a", "csv", "table"),
          conversion("b", "csv", "table"),
        ],
      }),
    );

    expect(commands).toBeNull();
  });
});

describe("artifact drop collection on a many input", () => {
  const manyPort = port({
    shape: "many",
    accepted_shapes: ["one", "many"],
  });

  it("groups same-type drops into one ordered sequence", () => {
    const commands = artifactDropCommands(
      { value: item("artifact-second"), shape: "one" },
      TARGET,
      manyPort,
      {},
      state({ origins: [origin({ value: item("artifact-first") })] }),
    );

    const command = commands?.[0];
    expect(command?.kind).toBe("update_origin");
    if (command?.kind !== "update_origin") return;
    const value = command.update.value as ArtifactRefSequence;
    expect(value.item_refs.map((item) => item.artifact_id)).toEqual([
      "artifact-first",
      "artifact-second",
    ]);
    expect(value.artifact_type).toBe("table");
    expect(value.ordered).toBe(true);
    expect(value.index_key).toBe("order_index");
    expect(typeof value.sequence_id).toBe("string");
  });

  it("appends to the sequence already collected on the slot", () => {
    const commands = artifactDropCommands(
      { value: item("artifact-c"), shape: "one" },
      TARGET,
      manyPort,
      {},
      state({
        origins: [origin({ value: sequence("artifact-a", "artifact-b") })],
      }),
    );

    const command = commands?.[0];
    if (command?.kind !== "update_origin") throw new Error("expected update");
    const value = command.update.value as ArtifactRefSequence;
    expect(value.item_refs.map((item) => item.artifact_id)).toEqual([
      "artifact-a",
      "artifact-b",
      "artifact-c",
    ]);
    expect(value.sequence_id).toBe("sequence-1");
  });

  it("replaces across artifact types because one sequence holds one type", () => {
    const commands = artifactDropCommands(
      { value: ref("csv"), shape: "one" },
      TARGET,
      port({
        shape: "many",
        accepted_shapes: ["one", "many"],
        also_accepts: [{ id: "csv", schema_version: 1 }],
      }),
      {},
      state({ origins: [origin()] }),
    );

    const command = commands?.[0];
    if (command?.kind !== "update_origin") throw new Error("expected update");
    expect(command.update.value).toEqual(ref("csv"));
  });

  it("writes a dropped sequence as the collected value", () => {
    const commands = artifactDropCommands(
      { value: sequence("artifact-a", "artifact-b"), shape: "many" },
      TARGET,
      manyPort,
      {},
      state(),
    );

    expect(commands?.[0]).toMatchObject({
      kind: "add_origin",
      origin: { value: sequence("artifact-a", "artifact-b") },
    });
  });

  it("does not collect a converted drop into a mixed contract", () => {
    const commands = artifactDropCommands(
      { value: ref("csv"), shape: "one" },
      TARGET,
      port({ shape: "many", accepted_shapes: ["one", "many"] }),
      {},
      state({
        origins: [origin()],
        conversions: [conversion("to-table", "csv", "table")],
      }),
    );

    const command = commands?.[0];
    if (command?.kind !== "update_origin") throw new Error("expected update");
    expect(command.update.value).toEqual(ref("csv"));
    expect(command.update.conversion_path).toEqual([
      { id: "to-table", version: 1 },
    ]);
  });
});

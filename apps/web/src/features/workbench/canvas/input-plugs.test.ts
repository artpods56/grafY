import { afterEach, describe, expect, it, vi } from "vitest";

import type { NodeSpec, RunNodeResult } from "@/lib/api";
import {
  collectContributionLabel,
  createWorkflowInputPlug,
  initialInputPlugs,
  reconcileSchemaFieldInputPlugs,
  reorderInputPlug,
  type WorkflowInputPlug,
} from "./input-plugs";
import {
  createSchemaBuilderField,
  withSchemaFieldKind,
} from "./schema-builder";

describe("ordered input plugs", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("creates distinct plug IDs without the secure-context randomUUID API", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: crypto.getRandomValues.bind(crypto),
    });

    const first = createWorkflowInputPlug("items");
    const second = createWorkflowInputPlug("items");

    expect(first.portName).toBe("items");
    expect(first.id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    expect(second.id).not.toBe(first.id);
  });

  it("reorders one port by stable id without disturbing another port", () => {
    const plugs: WorkflowInputPlug[] = [
      { id: "a", portName: "items" },
      { id: "b", portName: "items" },
      { id: "note", portName: "note" },
      { id: "c", portName: "items" },
    ];

    const moved = reorderInputPlug(plugs, "items", "c", 0);
    expect(moved).toEqual([
      { id: "c", portName: "items" },
      { id: "a", portName: "items" },
      { id: "note", portName: "note" },
      { id: "b", portName: "items" },
    ]);
    expect(reorderInputPlug(moved, "items", "c", 1)).toEqual([
      { id: "a", portName: "items" },
      { id: "c", portName: "items" },
      { id: "note", portName: "note" },
      { id: "b", portName: "items" },
    ]);
    expect(plugs.map((plug) => plug.id)).toEqual(["a", "b", "note", "c"]);
  });

  it("does not manufacture an unowned plug for an optional instance port", () => {
    const optionalInstanceSpec: NodeSpec = {
      operator_id: "schema.builder",
      operator_version: 1,
      plugin_slug: "builtin.schema",
      origin: "builtin",
      title: "Schema Builder",
      description: "Build a JSON Schema.",
      catalog_visible: true,
      runnable: true,
      config_schema: {},
      input_schema: {},
      output_schema: {},
      inputs: [
        {
          name: "schemas",
          title: "Nested schemas",
          description: null,
          direction: "input",
          artifact_type: {
            id: "json.schema",
            schema_version: 1,
          },
          artifact_type_variable: null,
          shape: "many",
          accepted_shapes: ["one"],
          required: false,
          variadic: true,
          instance_plugs: true,
        },
      ],
      outputs: [],
    };

    expect(initialInputPlugs(optionalInstanceSpec)).toEqual([]);
    expect(
      initialInputPlugs({
        ...optionalInstanceSpec,
        inputs: [{ ...optionalInstanceSpec.inputs[0]!, required: true }],
      }),
    ).toEqual([{ id: expect.any(String), portName: "schemas" }]);
  });

  it("aligns nested-schema plugs to stable field ids and order", () => {
    const stringField = createSchemaBuilderField(0, "title");
    const objectField = withSchemaFieldKind(
      createSchemaBuilderField(1, "customer"),
      "schema",
    );
    const linesField = {
      ...withSchemaFieldKind(createSchemaBuilderField(2, "lines"), "sequence"),
      item_kind: "schema" as const,
    };
    const existing: WorkflowInputPlug[] = [
      { id: "other-a", portName: "other" },
      { id: "stale", portName: "schemas" },
      { id: "other-b", portName: "other" },
    ];

    expect(
      reconcileSchemaFieldInputPlugs(existing, [
        linesField,
        stringField,
        objectField,
      ]),
    ).toEqual([
      { id: "other-a", portName: "other" },
      { id: "lines", portName: "schemas" },
      { id: "customer", portName: "schemas" },
      { id: "other-b", portName: "other" },
    ]);
  });
});

describe("Collect contribution ranges", () => {
  it("formats one-based flattened output ranges from sequence metadata", () => {
    const run: RunNodeResult = {
      node_id: "collect",
      status: "succeeded",
      error: null,
      outputs: [
        {
          port: "items",
          kind: "sequence",
          artifacts: [],
          value: {
            artifact_type: "text",
            schema_version: 1,
            item_refs: [],
            ordered: true,
            index_key: "order_index",
            metadata: {
              collect_segments: [
                {
                  input_index: 0,
                  start_index: 0,
                  item_count: 1,
                  source_kind: "single",
                },
                {
                  input_index: 1,
                  start_index: 1,
                  item_count: 3,
                  source_kind: "sequence",
                },
                {
                  input_index: 2,
                  start_index: 4,
                  item_count: 0,
                  source_kind: "sequence",
                },
              ],
            },
          },
        },
      ],
    };

    expect(collectContributionLabel(run, 0)).toBe("output 1");
    expect(collectContributionLabel(run, 1)).toBe("output 2–4");
    expect(collectContributionLabel(run, 2)).toBe("output empty");
    expect(collectContributionLabel(run, 3)).toBeUndefined();
  });
});

import { describe, expect, it } from "vitest";

import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import { encodeHandleId } from "../canvas/handles";
import { portMetaForPort } from "../canvas/types";
import {
  artifactFilterId,
  buildCatalogFilters,
  catalogSearchRank,
  buildSourceFilters,
  catalogNodeKey,
  catalogNodePortSummary,
  catalogNodeSpecs,
  catalogNodesForFilter,
  downstreamCandidatesFromOutput,
  filterAndSearchCatalogNodes,
  INPUT_NODES_FILTER,
  sortCatalogNodes,
  sourceFilterId,
  upstreamCandidatesFromInput,
} from "./node-catalog";

const FIRST_GRAPH_ID = "00000000-0000-4000-8000-000000000001";

function port(
  name: string,
  direction: Port["direction"],
  options: Partial<Port> = {},
): Port {
  return {
    name,
    title: name,
    description: null,
    direction,
    artifact_type: { id: "scalar.text", schema_version: 1 },
    artifact_type_variable: null,
    shape: "one",
    accepted_shapes: ["one"],
    instance_plugs: false,
    variadic: false,
    required: true,
    ...options,
  };
}

function nodeSpec(
  operatorId: string,
  pluginSlug: string,
  operatorVersion = 1,
  catalogVisible = true,
  options: {
    title?: string;
    description?: string;
    inputs?: Port[];
    outputs?: Port[];
  } = {},
): NodeSpec {
  return {
    operator_id: operatorId,
    operator_version: operatorVersion,
    plugin_slug: pluginSlug,
    title: options.title ?? operatorId,
    description: options.description ?? operatorId,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: options.inputs ?? [],
    outputs: options.outputs ?? [],
    catalog_visible: catalogVisible,
    origin: "builtin",
    runnable: true,
  };
}

function registry(): NodeRegistry {
  return {
    plugins: [
      {
        slug: "builtin",
        title: "Built-in",
        origin: "builtin",
        entry_kind: "plugin",
      },
      {
        slug: "external",
        title: "External",
        origin: "builtin",
        entry_kind: "plugin",
      },
    ],
    artifact_types: [
      {
        key: { id: "scalar.text", schema_version: 1 },
        title: "Text",
        payload_schema: {},
        field_projections: [],
        bundle: { format: "inline-json", version: 1 },
      },
      {
        key: { id: "scalar.text", schema_version: 2 },
        title: "Text",
        payload_schema: {},
        field_projections: [],
        bundle: { format: "inline-json", version: 1 },
      },
      {
        key: { id: "table.data", schema_version: 1 },
        title: "Table",
        payload_schema: {},
        field_projections: [],
        bundle: { format: "table-bundle", version: 1 },
      },
    ],
    artifact_conversions: [],
    nodes: [
      nodeSpec("text.input", "builtin", 1, true, {
        title: "Enter text",
        outputs: [port("text", "output")],
      }),
      nodeSpec("text.transform", "builtin", 1, true, {
        title: "Transform text",
        inputs: [port("text", "input")],
        outputs: [port("text", "output")],
      }),
      nodeSpec("table.batch", "builtin", 1, true, {
        title: "Batch table",
        inputs: [
          port("rows", "input", {
            artifact_type: { id: "table.data", schema_version: 1 },
            shape: "many",
            accepted_shapes: ["many"],
          }),
        ],
        outputs: [
          port("rows", "output", {
            artifact_type: { id: "table.data", schema_version: 1 },
            shape: "many",
            accepted_shapes: ["many"],
          }),
        ],
      }),
      nodeSpec("generic.pass", "builtin", 1, true, {
        title: "Pass any",
        inputs: [
          port("value", "input", {
            artifact_type: null,
            artifact_type_variable: "T",
          }),
        ],
        outputs: [
          port("value", "output", {
            artifact_type: null,
            artifact_type_variable: "T",
          }),
        ],
      }),
      nodeSpec("ocr.external", "external", 1, true, {
        title: "OCR",
      }),
    ],
  };
}

describe("node catalog listings", () => {
  it("offers every visible operator, builtin and plugin alike", () => {
    const available = catalogNodeSpecs(registry());

    expect(
      available.map((spec) => [spec.operator_id, spec.operator_version]),
    ).toEqual([
      ["text.input", 1],
      ["text.transform", 1],
      ["table.batch", 1],
      ["generic.pass", 1],
      ["ocr.external", 1],
    ]);
  });

  it("keeps catalog_visible false operators out of the listing", () => {
    const catalog = registry();
    const hidden = nodeSpec("notes.draft", "builtin", 1, false);

    expect(
      catalogNodeSpecs({ ...catalog, nodes: [...catalog.nodes, hidden] }).map(
        (spec) => spec.operator_id,
      ),
    ).not.toContain("notes.draft");
  });

  it("lists the same nodes whichever graph is being edited", () => {
    // Only Modules were ever hidden from the catalog of their own graph, and
    // Modules are gone (ADR 0020), so the argument hides nothing.
    expect(catalogNodeSpecs(registry(), FIRST_GRAPH_ID)).toEqual(
      catalogNodeSpecs(registry(), null),
    );
  });
});

it("keys a deployed family by operator version without release selection", () => {
  expect(catalogNodeKey(nodeSpec("gis.raster.import", "external.gis"))).toBe(
    "gis.raster.import@1",
  );
});

describe("artifact catalog filters", () => {
  it("builds artifact filters with version labels only for duplicate titles", () => {
    const filters = buildCatalogFilters(registry());
    expect(filters.map((filter) => filter.title)).toEqual([
      "All nodes",
      "Table",
      "Text · v1",
      "Text · v2",
      "Single value",
      "Sequence",
      "Any artifact",
    ]);
  });

  it("matches exact artifact, shape, and any-artifact filters", () => {
    const nodes = catalogNodeSpecs(registry(), null);
    const filters = buildCatalogFilters(registry());
    const byId = Object.fromEntries(
      filters.map((filter) => [filter.id, filter]),
    );

    expect(
      catalogNodesForFilter(
        nodes,
        byId[artifactFilterId({ id: "scalar.text", schema_version: 1 })]!,
      ).map((spec) => spec.operator_id),
    ).toEqual(["text.input", "text.transform"]);

    expect(
      catalogNodesForFilter(nodes, byId.sequence!).map(
        (spec) => spec.operator_id,
      ),
    ).toEqual(["table.batch"]);

    expect(
      catalogNodesForFilter(nodes, byId["any-artifact"]!).map(
        (spec) => spec.operator_id,
      ),
    ).toEqual(["generic.pass"]);
  });

  it("sorts by title then operator identity and intersects search with filters", () => {
    const nodes = catalogNodeSpecs(registry(), null);
    const filter = buildCatalogFilters(registry()).find(
      (candidate) => candidate.id === "all",
    )!;

    expect(sortCatalogNodes(nodes).map((spec) => spec.title)).toEqual([
      "Batch table",
      "Enter text",
      "OCR",
      "Pass any",
      "Transform text",
    ]);

    expect(
      filterAndSearchCatalogNodes(nodes, [filter], "transform", registry()).map(
        (spec) => spec.operator_id,
      ),
    ).toEqual(["text.transform"]);
  });

  it("builds one source category per provider plugin that ships nodes", () => {
    const sources = buildSourceFilters(registry());

    expect(sources.map((filter) => [filter.id, filter.title])).toEqual([
      ["all", "All"],
      [sourceFilterId("builtin"), "Built-in"],
      [sourceFilterId("external"), "External"],
    ]);
  });

  it("matches source and input-node filters", () => {
    const nodes = catalogNodeSpecs(registry(), null);
    const sources = buildSourceFilters(registry());
    const byId = Object.fromEntries(
      sources.map((filter) => [filter.id, filter]),
    );

    expect(
      catalogNodesForFilter(nodes, byId[sourceFilterId("builtin")]!).map(
        (spec) => spec.operator_id,
      ),
    ).toEqual(["text.input", "text.transform", "table.batch", "generic.pass"]);

    // Nodes that take no inputs because they are inputs themselves.
    expect(
      catalogNodesForFilter(nodes, INPUT_NODES_FILTER).map(
        (spec) => spec.operator_id,
      ),
    ).toEqual(["text.input", "ocr.external"]);
  });

  it("intersects source, artifact, and input-node filters", () => {
    const nodes = catalogNodeSpecs(registry(), null);
    const sources = buildSourceFilters(registry());
    const builtin = sources.find((f) => f.id === sourceFilterId("builtin"))!;
    const textArtifact = buildCatalogFilters(registry()).find(
      (candidate) =>
        candidate.id ===
        artifactFilterId({ id: "scalar.text", schema_version: 1 }),
    )!;

    expect(
      filterAndSearchCatalogNodes(
        nodes,
        [builtin, textArtifact],
        "",
        registry(),
      ).map((spec) => spec.operator_id),
    ).toEqual(["text.input", "text.transform"]);

    expect(
      filterAndSearchCatalogNodes(
        nodes,
        [builtin, textArtifact, INPUT_NODES_FILTER],
        "",
        registry(),
      ).map((spec) => spec.operator_id),
    ).toEqual(["text.input"]);
  });

  it("summarizes ports with artifact titles", () => {
    const transform = catalogNodeSpecs(registry(), null).find(
      (spec) => spec.operator_id === "text.transform",
    )!;
    expect(catalogNodePortSummary(transform, registry())).toBe("Text → Text");
  });
});

describe("downstream candidates", () => {
  it("lists compatible nodes once and excludes optional instance-plug-only targets", () => {
    const source = port("text", "output");
    const sourceHandle = encodeHandleId(portMetaForPort(source));
    const nodes = [
      nodeSpec("text.transform", "builtin", 1, true, {
        title: "Transform text",
        inputs: [port("text", "input")],
        outputs: [port("text", "output")],
      }),
      nodeSpec("collect.optional", "builtin", 1, true, {
        title: "Optional collect",
        inputs: [
          port("items", "input", {
            instance_plugs: true,
            required: false,
          }),
        ],
        outputs: [port("text", "output")],
      }),
      nodeSpec("collect.required", "builtin", 1, true, {
        title: "Required collect",
        inputs: [
          port("items", "input", {
            instance_plugs: true,
            required: true,
          }),
        ],
        outputs: [port("text", "output")],
      }),
    ];

    const candidates = downstreamCandidatesFromOutput({
      sourcePort: source as Port & { readonly direction: "output" },
      sourceHandle,
      registry: { ...registry(), nodes },
      nodes,
    });

    expect(candidates.map((candidate) => candidate.spec.operator_id)).toEqual([
      "collect.required",
      "text.transform",
    ]);
    expect(candidates[0]?.choices).toHaveLength(1);
  });
});

describe("upstream candidates", () => {
  it("lists nodes whose outputs can feed the input", () => {
    const target = port("text", "input");
    const targetHandle = encodeHandleId(portMetaForPort(target));
    const nodes = [
      nodeSpec("text.transform", "builtin", 1, true, {
        title: "Transform text",
        inputs: [port("text", "input")],
        outputs: [port("text", "output")],
      }),
      nodeSpec("collect.optional", "builtin", 1, true, {
        title: "Optional collect",
        inputs: [
          port("items", "input", {
            instance_plugs: true,
            required: false,
          }),
        ],
        outputs: [port("text", "output")],
      }),
      nodeSpec("source.broken", "builtin", 1, true, {
        title: "Broken source",
        inputs: [],
        outputs: [
          port("rows", "output", {
            artifact_type: { id: "table.data", schema_version: 1 },
          }),
        ],
      }),
    ];

    const candidates = upstreamCandidatesFromInput({
      targetPort: target as Port & { readonly direction: "input" },
      targetHandle,
      registry: { ...registry(), nodes },
      nodes,
    });

    expect(candidates.map((candidate) => candidate.spec.operator_id)).toEqual([
      "collect.optional",
      "text.transform",
    ]);
    expect(candidates[0]?.choices[0]?.candidatePort.direction).toBe("output");
  });
});

describe("catalogSearchRank", () => {
  const titled = (title: string, description = "") =>
    nodeSpec(`op.${title}`, "builtin", 1, true, { title, description });

  it("puts nodes named for the query above nodes that mention it", () => {
    const ranks = [
      titled("Add integers"),
      titled("Integer sequence"),
      titled("Pad left", "adds padding"),
    ].map((spec) => [spec.title, catalogSearchRank(spec, "add")]);

    expect(ranks).toEqual([
      ["Add integers", 1],
      ["Integer sequence", 7],
      ["Pad left", 7],
    ]);
    expect(catalogSearchRank(titled("Add integers"), "add integers")).toBe(0);
    expect(catalogSearchRank(titled("Split text"), "text")).toBe(2);
    expect(catalogSearchRank(titled("Split text"), "text split")).toBe(4);
    expect(catalogSearchRank(titled("Split text"), "text join")).toBe(5);
  });

  it("finds a node by every word of the query, in any order", () => {
    const nodes = [titled("Split text"), titled("Join text")];
    expect(
      filterAndSearchCatalogNodes(nodes, [], "text split", {
        ...registry(),
        nodes,
      }).map((spec) => spec.title),
    ).toEqual(["Split text"]);
  });
});

it("keeps unlisted nodes out of the library and both discovery directions", () => {
  const catalog = registry();
  const input = { ...port("text", "input"), direction: "input" as const };
  const output = { ...port("text", "output"), direction: "output" as const };
  const hidden = [
    "notes.draft",
    "table.staging",
    "image.internal",
    "value.internal",
  ].map((id) =>
    nodeSpec(id, "builtin", 1, false, {
      inputs: [input],
      outputs: [output],
    }),
  );
  const visible = nodeSpec("text.visible", "builtin", 1, true, {
    inputs: [input],
    outputs: [output],
  });
  const nodes = [...hidden, visible];
  const listed = catalogNodeSpecs({ ...catalog, nodes }, null);
  expect(listed.map((node) => node.operator_id)).toEqual(["text.visible"]);
  const downstream = downstreamCandidatesFromOutput({
    sourcePort: output,
    sourceHandle: encodeHandleId(portMetaForPort(output)),
    registry: catalog,
    nodes,
  });
  const upstream = upstreamCandidatesFromInput({
    targetPort: input,
    targetHandle: encodeHandleId(portMetaForPort(input)),
    registry: catalog,
    nodes,
  });
  expect(downstream).toHaveLength(1);
  expect(upstream).toHaveLength(1);
});

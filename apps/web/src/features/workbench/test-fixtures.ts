import type { NodeSpec, Port, ServiceContractKey } from "@/lib/api";

type PortFixtureOptions<Direction extends Port["direction"]> = Omit<
  Partial<Port>,
  "name" | "direction" | "kind"
> & {
  name: string;
  direction: Direction;
};

function portDefaults({
  name,
  shape = "one",
}: Pick<Port, "name"> & Partial<Pick<Port, "shape">>) {
  return {
    title: name,
    description: null,
    shape,
    accepted_shapes: [shape],
    instance_plugs: false,
    variadic: false,
    required: true,
    artifact_type_variable: null,
  };
}

export function artifactPortFixture<Direction extends Port["direction"]>(
  options: Omit<
    PortFixtureOptions<Direction>,
    "service_contracts" | "features"
  >,
): Port & { direction: Direction; kind: "artifact" } {
  return {
    ...portDefaults(options),
    artifact_type: { id: "scalar.text", schema_version: 1 },
    ...options,
    kind: "artifact",
  };
}

export function servicePortFixture<Direction extends Port["direction"]>(
  options: Omit<
    PortFixtureOptions<Direction>,
    | "artifact_type"
    | "artifact_type_variable"
    | "also_accepts"
    | "service_contracts"
  > & {
    service_contracts: readonly [ServiceContractKey, ...ServiceContractKey[]];
  },
): Port & { direction: Direction; kind: "service" } {
  return {
    ...portDefaults(options),
    artifact_type: null,
    ...options,
    kind: "service",
  };
}

export function nodeSpecFixture(
  options: Pick<NodeSpec, "operator_id"> & Partial<NodeSpec>,
): NodeSpec {
  return {
    title: options.operator_id,
    description: "",
    operator_version: 1,
    plugin_slug: "test",
    origin: "builtin",
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [],
    runnable: true,
    catalog_visible: true,
    ...options,
  };
}

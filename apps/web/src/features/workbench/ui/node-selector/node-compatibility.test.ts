import { describe, expect, it } from "vitest";

import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";

import { compatibleNodesForPort } from "./node-compatibility";

function servicePort(
  name: string,
  direction: Port["direction"],
  contractId = "ocr.reader",
): Port {
  return {
    name,
    title: name,
    description: null,
    direction,
    kind: "service",
    service_contracts: [{ id: contractId, version: 1 }],
    artifact_type: null,
    artifact_type_variable: null,
    shape: "one",
    accepted_shapes: ["one"],
    instance_plugs: false,
    variadic: false,
    required: true,
  };
}

function node(
  operator_id: string,
  title: string,
  inputs: readonly Port[],
  outputs: readonly Port[],
): NodeSpec {
  return {
    operator_id,
    operator_version: 1,
    plugin_slug: "test",
    origin: "builtin",
    title,
    description: null,
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs,
    outputs,
  };
}

describe("compatibleNodesForPort service contracts", () => {
  it("lists providers that produce the OCR reader contract", () => {
    const ocr = node("ocr.read", "OCR", [servicePort("reader", "input")], []);
    const mistral = node(
      "mistral.ocr.provider",
      "Mistral OCR",
      [],
      [servicePort("reader", "output")],
    );
    const reducto = node(
      "reducto.ocr.provider",
      "Reducto",
      [],
      [servicePort("reader", "output")],
    );
    const other = node(
      "other.provider",
      "Other",
      [],
      [servicePort("reader", "output", "other.service")],
    );
    const registry: NodeRegistry = {
      nodes: [ocr, mistral, reducto, other],
      plugins: [],
      artifact_types: [],
      artifact_conversions: [],
      service_contracts: [
        { id: "ocr.reader", version: 1, title: "OCR service" },
      ],
    };

    const matches = compatibleNodesForPort(ocr, ocr.inputs[0]!, registry).map(
      (match) => match.spec.title,
    );

    expect(matches).toEqual(["Mistral OCR", "Reducto"]);
  });
});

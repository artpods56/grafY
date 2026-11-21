import { describe, expect, it } from "vitest";

import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import { nodeSpecFixture, servicePortFixture } from "../../test-fixtures";

import { compatibleNodesForPort } from "./node-compatibility";

function servicePort(
  name: string,
  direction: Port["direction"],
  contractId = "ocr.reader",
): Port {
  return servicePortFixture({
    name,
    title: name,
    direction,
    service_contracts: [{ id: contractId, version: 1 }],
  });
}

function node(
  operator_id: string,
  title: string,
  inputs: readonly Port[],
  outputs: readonly Port[],
): NodeSpec {
  return nodeSpecFixture({
    operator_id,
    title,
    inputs,
    outputs,
  });
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

import { describe, expect, it } from "vitest";

import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import { nodeSpecFixture, servicePortFixture } from "../../test-fixtures";

import { compatibleNodesForPort } from "./node-compatibility";

function servicePort(
  name: string,
  direction: Port["direction"],
  contractId = "ocr.document",
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
    const ocr = node(
      "ocr.read_document",
      "Document OCR",
      [servicePort("engine", "input")],
      [],
    );
    const mistral = node(
      "mistral.ocr.provider",
      "Mistral OCR",
      [],
      [servicePort("engine", "output")],
    );
    const reducto = node(
      "reducto.ocr.provider",
      "Reducto",
      [],
      [servicePort("engine", "output")],
    );
    const other = node(
      "other.provider",
      "Other",
      [],
      [servicePort("engine", "output", "other.service")],
    );
    const registry: NodeRegistry = {
      nodes: [ocr, mistral, reducto, other],
      plugins: [],
      artifact_types: [],
      artifact_conversions: [],
      service_contracts: [
        { id: "ocr.document", version: 1, title: "Document OCR" },
      ],
    };

    const matches = compatibleNodesForPort(ocr, ocr.inputs[0]!, registry).map(
      (match) => match.spec.title,
    );

    expect(matches).toEqual(["Mistral OCR", "Reducto"]);
  });
});

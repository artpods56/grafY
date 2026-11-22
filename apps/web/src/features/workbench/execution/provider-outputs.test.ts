import { describe, expect, it } from "vitest";

import type { NodeSpec, Port } from "@/lib/api";
import {
  artifactPortFixture,
  nodeSpecFixture,
  servicePortFixture,
} from "../test-fixtures";

import {
  connectedServiceProvider,
  notProducedInputReasons,
  unsupportedOutputForPort,
  unsupportedOutputLabel,
} from "./provider-outputs";
import { createWorkflowNodeData, type WorkflowEdge } from "../authoring/types";

function servicePort(
  name: string,
  direction: Port["direction"],
  features?: readonly string[],
): Port {
  return servicePortFixture({
    name,
    title: name,
    direction,
    service_contracts: [{ id: "ocr.reader", version: 1 }],
    features: features ? [...features] : undefined,
  });
}

function artifactPort(
  name: string,
  direction: Port["direction"],
  required: boolean,
  title?: string,
): Port {
  return artifactPortFixture({
    name,
    title: title ?? name,
    direction,
    required,
  });
}

function spec(
  id: string,
  title: string,
  inputs: readonly Port[],
  outputs: readonly Port[],
): NodeSpec {
  return nodeSpecFixture({
    operator_id: id,
    title,
    inputs,
    outputs,
  });
}

function edge(
  id: string,
  source: string,
  sourcePort: Port,
  target: string,
  targetPort: Port,
): WorkflowEdge {
  return {
    id,
    source,
    sourcePort: sourcePort.name,
    target,
    targetPort: targetPort.name,
    targetPlug: null,
    data: { enabled: true, collectionMode: "direct" },
  };
}

describe("provider-dependent outputs", () => {
  it("reads the connected provider title and features", () => {
    const providerOut = servicePort("reader", "output", ["blocks"]);
    const consumerIn = servicePort("reader", "input");
    const provider = {
      id: "provider",
      data: createWorkflowNodeData(
        spec("reducto.ocr.provider", "Reducto", [], [providerOut]),
      ),
    };
    const ocr = {
      id: "ocr",
      data: createWorkflowNodeData(
        spec(
          "ocr.read",
          "OCR",
          [consumerIn],
          [artifactPort("regions", "output", false, "Boxes on the page")],
        ),
      ),
    };

    expect(
      connectedServiceProvider(
        "ocr",
        [provider, ocr],
        [edge("e1", "provider", providerOut, "ocr", consumerIn)],
      ),
    ).toEqual({
      nodeId: "provider",
      title: "Reducto",
      features: ["blocks"],
    });
  });

  it("mutes an optional output absent from the provider features", () => {
    const provider = {
      nodeId: "provider",
      title: "Reducto",
      features: ["blocks"],
    };
    expect(
      unsupportedOutputForPort(
        artifactPort("regions", "output", false, "Boxes on the page"),
        provider,
      ),
    ).toEqual({
      portName: "regions",
      providerTitle: "Reducto",
    });
    expect(
      unsupportedOutputLabel({
        portName: "regions",
        providerTitle: "Reducto",
      }),
    ).toBe("Not produced by Reducto");
    expect(
      unsupportedOutputForPort(
        artifactPort("blocks", "output", false, "Text blocks"),
        provider,
      ),
    ).toBeNull();
    expect(
      unsupportedOutputForPort(
        artifactPort("markdown", "output", true, "Transcription"),
        provider,
      ),
    ).toBeNull();
    expect(
      unsupportedOutputForPort(artifactPort("regions", "output", false), null),
    ).toBeNull();
  });

  it("names the downstream input when a muted output is wired", () => {
    const providerOut = servicePort("reader", "output", ["blocks"]);
    const readerIn = servicePort("reader", "input");
    const regionsOut = artifactPort(
      "regions",
      "output",
      false,
      "Boxes on the page",
    );
    const boxesIn = artifactPort("regions", "input", true, "Boxes");
    const provider = {
      id: "provider",
      data: createWorkflowNodeData(
        spec("reducto.ocr.provider", "Reducto", [], [providerOut]),
      ),
    };
    const ocr = {
      id: "ocr",
      data: createWorkflowNodeData(
        spec("ocr.read", "OCR", [readerIn], [regionsOut]),
      ),
    };
    const draw = {
      id: "draw",
      data: createWorkflowNodeData(
        spec("test.draw_boxes", "Draw boxes", [boxesIn], []),
      ),
    };

    expect(
      notProducedInputReasons(
        "draw",
        [provider, ocr, draw],
        [
          edge("e1", "provider", providerOut, "ocr", readerIn),
          edge("e2", "ocr", regionsOut, "draw", boxesIn),
        ],
      ),
    ).toEqual([
      {
        portName: "regions",
        message: "Boxes are not produced by Reducto",
      },
    ]);
  });
});

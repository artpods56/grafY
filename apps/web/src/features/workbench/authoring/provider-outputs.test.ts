import { describe, expect, it } from "vitest";

import type { NodeSpec, Port } from "@/lib/api";
import {
  artifactPortFixture,
  nodeSpecFixture,
  servicePortFixture,
} from "../test-fixtures";

import {
  exclusiveInputLabel,
  exclusiveInputReason,
  gatedOutputForPort,
  gatedOutputLabel,
  notProducedInputReasons,
  unsupportedOutputForPort,
  unsupportedOutputLabel,
} from "./provider-outputs";
import { createWorkflowNodeData, type WorkflowEdge } from "./types";

const documentContract = { id: "ocr.document", version: 1 };

function servicePort(
  name: string,
  direction: Port["direction"],
  features?: readonly string[],
): Port {
  return servicePortFixture({
    name,
    title: name,
    direction,
    service_contracts: [documentContract],
    service_features: features
      ? [{ contract: documentContract, features }]
      : [],
  });
}

function artifactPort(
  name: string,
  direction: Port["direction"],
  required: boolean,
  title?: string,
  requires_service_feature: Port["requires_service_feature"] = null,
): Port {
  return artifactPortFixture({
    name,
    title: title ?? name,
    direction,
    required,
    requires_service_feature,
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
  it("checks the declared feature on the exact connected input and contract", () => {
    const decoyOut = servicePort("engine", "output", ["regions"]);
    const providerOut = servicePortFixture({
      name: "engine",
      direction: "output",
      service_contracts: [documentContract],
      service_features: [
        {
          contract: { ...documentContract, version: 2 },
          features: ["regions"],
        },
        { contract: documentContract, features: ["blocks"] },
      ],
    });
    const comparison = servicePort("comparison", "input");
    const engine = servicePort("engine", "input");
    const regions = artifactPort(
      "boxes",
      "output",
      false,
      "Boxes on the page",
      {
        input_port: "engine",
        feature: "regions",
      },
    );
    const blocks = artifactPort("rows", "output", false, "Text blocks", {
      input_port: "engine",
      feature: "blocks",
    });
    const unrelated = artifactPort("optional", "output", false);
    const decoy = {
      id: "decoy",
      data: createWorkflowNodeData(
        spec("test.full", "Full OCR", [], [decoyOut]),
      ),
    };
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
          "ocr.read_document",
          "Document OCR",
          [comparison, engine],
          [regions, blocks, unrelated],
        ),
      ),
    };
    const nodes = [decoy, provider, ocr];
    const comparisonEdge = edge("e1", decoy.id, decoyOut, ocr.id, comparison);
    const edges = [
      comparisonEdge,
      edge("e2", provider.id, providerOut, ocr.id, engine),
    ];

    const unsupported = unsupportedOutputForPort(regions, ocr, nodes, edges);
    expect(unsupported).toEqual({
      portName: "boxes",
      providerTitle: "Reducto",
    });
    if (!unsupported) throw new Error("Expected unsupported boxes");
    expect(unsupportedOutputLabel(unsupported)).toBe("Not produced by Reducto");
    expect(unsupportedOutputForPort(blocks, ocr, nodes, edges)).toBeNull();
    expect(unsupportedOutputForPort(unrelated, ocr, nodes, edges)).toBeNull();
    expect(
      unsupportedOutputForPort(regions, ocr, nodes, [comparisonEdge]),
    ).toBeNull();
  });

  it("names the downstream input when a muted output is wired", () => {
    const providerOut = servicePort("engine", "output", ["blocks"]);
    const engineIn = servicePort("engine", "input");
    const regionsOut = artifactPort(
      "regions",
      "output",
      false,
      "Boxes on the page",
      { input_port: "engine", feature: "regions" },
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
        spec("ocr.read_document", "Document OCR", [engineIn], [regionsOut]),
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
          edge("e1", "provider", providerOut, "ocr", engineIn),
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

  it("dims input-gated outputs and exclusive sibling inputs based on what is connected", () => {
    const textIn = artifactPortFixture({
      name: "text",
      title: "Text",
      direction: "input",
      required: false,
      exclusive_group: "source",
    });
    const recognizedIn = artifactPortFixture({
      name: "recognized",
      title: "Recognized text",
      direction: "input",
      required: false,
      exclusive_group: "source",
    });
    const textOut = artifactPortFixture({
      name: "text",
      title: "Latin text",
      direction: "output",
      required: false,
      requires_input: "text",
    });
    const recognizedOut = artifactPortFixture({
      name: "recognized",
      title: "Latin detections",
      direction: "output",
      required: false,
      requires_input: "recognized",
    });
    const upstreamOut = artifactPort("markdown", "output", true, "Markdown");
    const downstreamIn = artifactPort("labels", "input", true, "Labels");
    const upstream = {
      id: "up",
      data: createWorkflowNodeData(
        spec("test.up", "Source", [], [upstreamOut]),
      ),
    };
    const translit = {
      id: "translit",
      data: createWorkflowNodeData(
        spec(
          "text.transliterate_cyrillic",
          "Transliterate Cyrillic",
          [textIn, recognizedIn],
          [textOut, recognizedOut],
        ),
      ),
    };
    const downstream = {
      id: "down",
      data: createWorkflowNodeData(
        spec("test.down", "Consumer", [downstreamIn], []),
      ),
    };

    // Unconnected: both outputs gated, neither input blocked.
    expect(gatedOutputLabel(gatedOutputForPort(textOut, translit, [])!)).toBe(
      "Connect Text",
    );
    expect(
      gatedOutputLabel(gatedOutputForPort(recognizedOut, translit, [])!),
    ).toBe("Connect Recognized text");
    expect(exclusiveInputReason(textIn, translit, [])).toBeNull();
    expect(exclusiveInputReason(recognizedIn, translit, [])).toBeNull();

    // Connecting Text via an edge activates Latin text and dims Recognized text + Latin detections.
    const wiredEdges = [
      edge("e1", "up", upstreamOut, "translit", textIn),
      edge("e2", "translit", recognizedOut, "down", downstreamIn),
    ];
    expect(gatedOutputForPort(textOut, translit, wiredEdges)).toBeNull();
    expect(
      gatedOutputLabel(
        gatedOutputForPort(recognizedOut, translit, wiredEdges)!,
      ),
    ).toBe("Connect Recognized text");
    expect(exclusiveInputReason(textIn, translit, wiredEdges)).toBeNull();
    expect(
      exclusiveInputLabel(
        exclusiveInputReason(recognizedIn, translit, wiredEdges)!,
      ),
    ).toBe("Using Text");
    expect(
      notProducedInputReasons(
        "down",
        [upstream, translit, downstream],
        wiredEdges,
      ),
    ).toEqual([
      {
        portName: "labels",
        message:
          "Labels is not produced because Recognized text is not connected",
      },
    ]);

    // Connecting Recognized text via an origin activates Latin detections and dims Text.
    const origins = [{ to_node: "translit", to_port: "recognized" }];
    expect(gatedOutputForPort(recognizedOut, translit, [], origins)).toBeNull();
    expect(
      exclusiveInputLabel(exclusiveInputReason(textIn, translit, [], origins)!),
    ).toBe("Using Recognized text");
  });
});

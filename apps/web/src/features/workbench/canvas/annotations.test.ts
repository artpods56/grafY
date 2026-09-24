import { describe, expect, it } from "vitest";

import {
  ANNOTATION_NODE_TYPE,
  ANNOTATION_Z_INDEX,
  DEFAULT_ANNOTATION_COLOR,
  annotationsFromPresentation,
  createAnnotationNode,
  normalizeAnnotationColor,
  serializeAnnotations,
} from "./annotations";

describe("canvas annotations", () => {
  it("round-trips text and shape annotations", () => {
    const text = createAnnotationNode(
      "text",
      { x: 12, y: 34 },
      "annotation-text",
    );
    const rect = createAnnotationNode(
      "rectangle",
      { x: 50, y: 60 },
      "annotation-rect",
    );
    const serialized = serializeAnnotations([text, rect]);
    expect(serialized).toEqual([
      {
        id: "annotation-text",
        kind: "text",
        position: { x: 12, y: 34 },
        layout: { width: 240, height: 120 },
        text: "## Note\n\nDescribe this part of the graph.",
        color: DEFAULT_ANNOTATION_COLOR,
      },
      {
        id: "annotation-rect",
        kind: "rectangle",
        position: { x: 50, y: 60 },
        layout: { width: 160, height: 120 },
        text: "",
        color: DEFAULT_ANNOTATION_COLOR,
      },
    ]);

    const hydrated = annotationsFromPresentation({ annotations: serialized });
    expect(hydrated).toEqual([
      {
        id: "annotation-text",
        type: ANNOTATION_NODE_TYPE,
        position: { x: 12, y: 34 },
        zIndex: ANNOTATION_Z_INDEX,
        data: {
          kind: "text",
          layout: { width: 240, height: 120 },
          text: "## Note\n\nDescribe this part of the graph.",
          color: DEFAULT_ANNOTATION_COLOR,
        },
      },
      {
        id: "annotation-rect",
        type: ANNOTATION_NODE_TYPE,
        position: { x: 50, y: 60 },
        zIndex: ANNOTATION_Z_INDEX,
        data: {
          kind: "rectangle",
          layout: { width: 160, height: 120 },
          text: "",
          color: DEFAULT_ANNOTATION_COLOR,
        },
      },
    ]);
  });

  it("keeps selected annotations under default workflow node z-index", () => {
    // React Flow adds SELECTED_NODE_Z (1000) when elevateNodesOnSelect is on.
    expect(ANNOTATION_Z_INDEX + 1000).toBeLessThan(0);
  });

  it("normalizes legacy named colors and hex values", () => {
    expect(normalizeAnnotationColor("amber")).toBe("#b45309");
    expect(normalizeAnnotationColor("#AbCDeF")).toBe("#abcdef");
    expect(normalizeAnnotationColor("nope")).toBe(DEFAULT_ANNOTATION_COLOR);
  });
});

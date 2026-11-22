import { readFileSync } from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";

import { DEFAULT_ANNOTATION_LAYOUT } from "./annotations";
import {
  ARTIFACT_CARD_HEIGHT_MAX,
  ARTIFACT_CARD_HEIGHT_MIN,
  ARTIFACT_CARD_LAYOUT_BOUNDS,
  ARTIFACT_CARD_WIDTH_MAX,
  ARTIFACT_CARD_WIDTH_MIN,
  DEFAULT_ARTIFACT_CARD_WIDTH,
  DEFAULT_ARTIFACT_FILE_CARD_WIDTH,
  DEFAULT_ARTIFACT_MAP_BODY_HEIGHT,
  DEFAULT_ARTIFACT_MAP_CARD_WIDTH,
  DEFAULT_ARTIFACT_OUTPUT_CARD_WIDTH,
  DEFAULT_ARTIFACT_TABLE_BODY_HEIGHT,
  DEFAULT_ARTIFACT_TABLE_CARD_WIDTH,
} from "./artifact-card";
import {
  APPENDIX_HEIGHT_MIN,
  BODY_HEIGHT_MIN,
  DEFAULT_APPENDIX_HEIGHT,
  DEFAULT_BODY_HEIGHT,
  DEFAULT_NODE_WIDTH,
  LAYOUT_DIMENSION_MAX,
  NODE_WIDTH_MIN,
  clampNodeLayout,
} from "./node-layout";

interface SchemaProperty {
  type?: string;
  minimum?: number;
  maximum?: number;
  anyOf?: readonly SchemaProperty[];
}

interface OpenApiDocument {
  components: {
    schemas: Record<
      string,
      {
        properties?: Record<string, SchemaProperty>;
      }
    >;
  };
}

const OPENAPI_PATH = path.resolve(__dirname, "../../../../openapi/grafy.json");
const openapi = JSON.parse(
  readFileSync(OPENAPI_PATH, "utf8"),
) as OpenApiDocument;

function numericBounds(
  schemaName: string,
  propertyName: string,
): { minimum: number; maximum: number } {
  const prop =
    openapi.components.schemas[schemaName]?.properties?.[propertyName];
  if (!prop) {
    throw new Error(`Missing schema property ${schemaName}.${propertyName}`);
  }
  const branch =
    prop.anyOf?.find((candidate) => candidate.type === "number") ?? prop;
  if (
    typeof branch.minimum !== "number" ||
    typeof branch.maximum !== "number"
  ) {
    throw new Error(`Missing numeric bounds on ${schemaName}.${propertyName}`);
  }
  return { minimum: branch.minimum, maximum: branch.maximum };
}

function expectWithin(
  value: number,
  bounds: { minimum: number; maximum: number },
): void {
  expect(value).toBeGreaterThanOrEqual(bounds.minimum);
  expect(value).toBeLessThanOrEqual(bounds.maximum);
}

describe("frontend layout bounds match OpenAPI schema contracts", () => {
  it("keeps workflow node layout constants within GraphNodeLayout bounds", () => {
    const widthBounds = numericBounds("GraphNodeLayout", "width");
    const bodyHeightBounds = numericBounds("GraphNodeLayout", "body_height");
    const appendixHeightBounds = numericBounds(
      "GraphNodeLayout",
      "appendix_height",
    );

    expect(NODE_WIDTH_MIN).toBeGreaterThanOrEqual(widthBounds.minimum);
    expect(LAYOUT_DIMENSION_MAX).toBeLessThanOrEqual(widthBounds.maximum);
    expectWithin(DEFAULT_NODE_WIDTH, widthBounds);

    expect(BODY_HEIGHT_MIN).toBeGreaterThanOrEqual(bodyHeightBounds.minimum);
    expect(LAYOUT_DIMENSION_MAX).toBeLessThanOrEqual(bodyHeightBounds.maximum);
    expectWithin(DEFAULT_BODY_HEIGHT, bodyHeightBounds);

    expect(APPENDIX_HEIGHT_MIN).toBeGreaterThanOrEqual(
      appendixHeightBounds.minimum,
    );
    expect(LAYOUT_DIMENSION_MAX).toBeLessThanOrEqual(
      appendixHeightBounds.maximum,
    );
    expectWithin(DEFAULT_APPENDIX_HEIGHT, appendixHeightBounds);
  });

  it("keeps artifact card sizing constants within GraphPresentationViewerLayout bounds", () => {
    const widthBounds = numericBounds("GraphPresentationViewerLayout", "width");
    const bodyHeightBounds = numericBounds(
      "GraphPresentationViewerLayout",
      "body_height",
    );
    const appendixHeightBounds = numericBounds(
      "GraphPresentationViewerLayout",
      "appendix_height",
    );

    expect(ARTIFACT_CARD_WIDTH_MIN).toBeGreaterThanOrEqual(widthBounds.minimum);
    expect(ARTIFACT_CARD_WIDTH_MAX).toBeLessThanOrEqual(widthBounds.maximum);
    for (const defaultWidth of [
      DEFAULT_ARTIFACT_CARD_WIDTH,
      DEFAULT_ARTIFACT_FILE_CARD_WIDTH,
      DEFAULT_ARTIFACT_TABLE_CARD_WIDTH,
      DEFAULT_ARTIFACT_MAP_CARD_WIDTH,
      DEFAULT_ARTIFACT_OUTPUT_CARD_WIDTH,
    ]) {
      expectWithin(defaultWidth, widthBounds);
    }

    expect(ARTIFACT_CARD_HEIGHT_MIN).toBeGreaterThanOrEqual(
      bodyHeightBounds.minimum,
    );
    expect(ARTIFACT_CARD_HEIGHT_MAX).toBeLessThanOrEqual(
      bodyHeightBounds.maximum,
    );
    for (const defaultBodyHeight of [
      DEFAULT_ARTIFACT_TABLE_BODY_HEIGHT,
      DEFAULT_ARTIFACT_MAP_BODY_HEIGHT,
    ]) {
      expectWithin(defaultBodyHeight, bodyHeightBounds);
    }

    expect(APPENDIX_HEIGHT_MIN).toBeGreaterThanOrEqual(
      appendixHeightBounds.minimum,
    );
    expect(LAYOUT_DIMENSION_MAX).toBeLessThanOrEqual(
      appendixHeightBounds.maximum,
    );
  });

  it("keeps default annotation layouts within GraphAnnotationLayout bounds", () => {
    const widthBounds = numericBounds("GraphAnnotationLayout", "width");
    const heightBounds = numericBounds("GraphAnnotationLayout", "height");

    for (const kind of ["text", "rectangle", "ellipse"] as const) {
      expectWithin(DEFAULT_ANNOTATION_LAYOUT[kind].width, widthBounds);
      expectWithin(DEFAULT_ANNOTATION_LAYOUT[kind].height, heightBounds);
    }
  });

  it("keeps agent bounds aligned with GraphAgent schema limits", () => {
    const widthBounds = numericBounds("GraphAgent", "width");
    const heightBounds = numericBounds("GraphAgent", "height");

    expect(NODE_WIDTH_MIN).toBeGreaterThanOrEqual(widthBounds.minimum);
    expect(LAYOUT_DIMENSION_MAX).toBeLessThanOrEqual(widthBounds.maximum);
    expect(BODY_HEIGHT_MIN).toBeGreaterThanOrEqual(heightBounds.minimum);
    expect(LAYOUT_DIMENSION_MAX).toBeLessThanOrEqual(heightBounds.maximum);
  });

  it("clamps out-of-range dimensions strictly inside OpenAPI schema bounds", () => {
    const nodeWidthBounds = numericBounds("GraphNodeLayout", "width");
    const nodeBodyBounds = numericBounds("GraphNodeLayout", "body_height");
    const nodeAppendixBounds = numericBounds(
      "GraphNodeLayout",
      "appendix_height",
    );
    const cardWidthBounds = numericBounds(
      "GraphPresentationViewerLayout",
      "width",
    );
    const cardBodyBounds = numericBounds(
      "GraphPresentationViewerLayout",
      "body_height",
    );

    for (const extreme of [-500, 0, 10, 999_999]) {
      const clampedNode = clampNodeLayout({
        width: extreme,
        bodyHeight: extreme,
        appendixHeight: extreme,
      });
      expect(clampedNode).not.toBeNull();
      expectWithin(clampedNode!.width!, nodeWidthBounds);
      expectWithin(clampedNode!.bodyHeight!, nodeBodyBounds);
      expectWithin(clampedNode!.appendixHeight!, nodeAppendixBounds);

      const clampedCard = clampNodeLayout(
        {
          width: extreme,
          bodyHeight: extreme,
          appendixHeight: extreme,
        },
        ARTIFACT_CARD_LAYOUT_BOUNDS,
      );
      expect(clampedCard).not.toBeNull();
      expectWithin(clampedCard!.width!, cardWidthBounds);
      expectWithin(clampedCard!.bodyHeight!, cardBodyBounds);
      expectWithin(clampedCard!.appendixHeight!, nodeAppendixBounds);
    }
  });
});

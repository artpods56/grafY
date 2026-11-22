import { assert, describe, expect, it } from "vitest";

import type { SavedGraphNode } from "@/lib/api";

import {
  answerFormatEdge,
  askModelSpec,
  fixtureDocument,
  fixtureNode,
  richRegistry,
  schemaSourceSpec,
  vectorLayerSpec,
} from "./cell-config-fixtures.test-support";
import { countConfigShelfCells } from "./cell-card-geometry";
import type { OperatorCardSurfaceData } from "./cell-contracts";
import {
  buildOperatorCardsAndSurfaces,
  type CellNodeSecretState,
} from "./cell-operator-adapter";

function operator(
  document: Parameters<typeof buildOperatorCardsAndSurfaces>[0],
  id: string,
  options?: Parameters<typeof buildOperatorCardsAndSurfaces>[2],
) {
  const { cards, surfaces } = buildOperatorCardsAndSurfaces(
    document,
    richRegistry,
    options,
  );
  const surface = surfaces.get(id);
  const card = cards.find((candidate) => candidate.id === id);
  assert(surface?.kind === "operator" && card);
  return { surface, card };
}

function fieldIds(surface: OperatorCardSurfaceData): string[] {
  return (surface.configFields ?? []).map(({ id }) => id);
}

function rowsOf(surface: OperatorCardSurfaceData, id: string) {
  return surface.configFields?.find((field) => field.id === id)?.denseRows;
}

const ask = fixtureNode("ask", askModelSpec, {
  base_url: "https://api.example.test/v1",
});
const schema = fixtureNode("schema", schemaSourceSpec);

describe("operator config fields: visibleWhen", () => {
  it("hides `Schema Name` and `Strict` until `Answer format` is wired", () => {
    const unwired = operator(fixtureDocument([ask, schema]), "ask");
    const wired = operator(
      fixtureDocument([ask, schema], [answerFormatEdge()]),
      "ask",
    );

    expect(fieldIds(unwired.surface)).toEqual(["base_url", "model"]);
    expect(fieldIds(wired.surface)).toEqual([
      "base_url",
      "model",
      "schema_name",
      "strict",
    ]);
    // The two fields pair on one more 2-row shelf, so the card grows by it.
    expect(countConfigShelfCells(wired.surface.configFields ?? [])).toBe(4);
    expect(wired.card.heightCells - unwired.card.heightCells).toBe(2);
    expect(wired.surface.connectedInputPorts?.answer_format).toEqual({
      connected: true,
      artifactTypeKey: "json.schema@1",
    });
  });

  it("treats a disabled edge as no wire at all", () => {
    const { surface } = operator(
      fixtureDocument([ask, schema], [answerFormatEdge(false)]),
      "ask",
    );
    expect(fieldIds(surface)).not.toContain("schema_name");
    expect(surface.connectedInputPorts?.answer_format?.connected).toBe(false);
  });
});

describe("operator config fields: secrets", () => {
  it("moves secret inputs off the config band onto `secretInputs`", () => {
    const { surface } = operator(fixtureDocument([ask]), "ask");
    expect(fieldIds(surface)).not.toContain("api_key");
    expect(surface.configFields?.some((field) => field.id === "api_key")).toBe(
      false,
    );
    expect(surface.secretInputs).toEqual([
      expect.objectContaining({
        name: "api_key",
        title: "API key",
        state: "unknown",
        ready: false,
      }),
    ]);
  });

  it("reports a saved key as configured while its binding holds, stale once it changes", () => {
    const saved: SavedGraphNode = ask;
    const secrets: CellNodeSecretState = {
      statuses: { ask: { api_key: { state: "configured" } } },
      savedNodes: [saved],
      scope: "graph-1:epoch-1",
    };
    const held = operator(fixtureDocument([ask]), "ask", { secrets });
    expect(held.surface.secretInputs?.[0]).toMatchObject({
      state: "configured",
      ready: true,
    });

    // The key was saved for another base URL, so it cannot be trusted here.
    const moved = fixtureNode("ask", askModelSpec, {
      base_url: "https://other.example.test",
    });
    const changed = operator(fixtureDocument([moved]), "ask", { secrets });
    expect(changed.surface.secretInputs?.[0]).toMatchObject({
      state: "stale",
      ready: false,
    });
    // A new binding is a new revision, so a half-typed key starts over.
    expect(changed.surface.secretInputs?.[0]?.revision).not.toBe(
      held.surface.secretInputs?.[0]?.revision,
    );
  });

  it("gives an operator without secret inputs no `secretInputs`", () => {
    const layer = fixtureNode("layer", vectorLayerSpec, { title: "Roads" });
    const { surface } = operator(fixtureDocument([layer]), "layer");
    expect(surface.secretInputs).toBeUndefined();
  });
});

describe("operator config fields: rich schema metadata", () => {
  const layer = fixtureNode("layer", vectorLayerSpec, {
    title: "Roads",
    opacity: 0.4,
  });

  it("carries each field's full schema and stored value", () => {
    const { surface } = operator(fixtureDocument([layer]), "layer");
    const opacity = surface.configFields?.find(({ id }) => id === "opacity");
    expect(opacity).toMatchObject({
      label: "Opacity",
      kind: "number",
      value: 0.4,
      rawValue: 0.4,
      span: 1,
      denseRows: 2,
      schemaField: {
        type: "number",
        widget: "slider",
        minimum: 0,
        maximum: 1,
        defaultValue: 1,
      },
    });
    const blend = surface.configFields?.find(({ id }) => id === "blend");
    expect(blend).toMatchObject({
      span: 2,
      schemaField: {
        widget: "segmented",
        enumLabels: { normal: "Normal", multiply: "Multiply" },
      },
      options: [
        { value: "normal", label: "Normal" },
        { value: "multiply", label: "Multiply" },
      ],
    });
    const style = surface.configFields?.find(({ id }) => id === "style");
    expect(style?.schemaField).toMatchObject({
      type: "discriminated-union",
      discriminator: "kind",
      branches: [{ tag: "simple" }, { tag: "categorized_points" }],
    });
  });

  it("folds untouched advanced fields behind one `Advanced` row", () => {
    const folded = operator(fixtureDocument([layer]), "layer");
    expect(fieldIds(folded.surface)).toEqual([
      "title",
      "visible",
      "opacity",
      "blend",
      "style",
      ":advanced",
    ]);
    expect(folded.surface.configFields?.at(-1)).toMatchObject({
      kind: "advanced",
      label: "Advanced",
      denseRows: 1,
      section: { key: "advanced", open: false, count: 2 },
    });

    const opened = operator(fixtureDocument([layer]), "layer", {
      configSections: { layer: { advanced: true } },
    });
    expect(fieldIds(opened.surface)).toEqual([
      "title",
      "visible",
      "opacity",
      "blend",
      "min_zoom",
      "max_zoom",
      "style",
      ":advanced",
    ]);
    expect(opened.surface.configSections).toEqual({ advanced: true });
    // Min and max zoom pair on one more 2-row shelf.
    expect(opened.card.heightCells - folded.card.heightCells).toBe(2);
  });

  it("keeps an advanced field the person changed in view", () => {
    const zoomed = fixtureNode("layer", vectorLayerSpec, {
      title: "Roads",
      min_zoom: 6,
    });
    const { surface } = operator(fixtureDocument([zoomed]), "layer");
    expect(fieldIds(surface)).toContain("min_zoom");
    expect(fieldIds(surface)).not.toContain("max_zoom");
    expect(surface.configFields?.at(-1)?.section?.count).toBe(1);
  });

  it("names a field validation rejects", () => {
    const untitled = fixtureNode("layer", vectorLayerSpec, { title: "" });
    const { surface } = operator(fixtureDocument([untitled]), "layer");
    expect(
      surface.configFields?.find(({ id }) => id === "title")?.issue,
    ).toBeTruthy();
  });
});

describe("operator config fields: rows for composite fields", () => {
  it("grows the `Style` union with the branch it is on", () => {
    const simple = operator(
      fixtureDocument([fixtureNode("layer", vectorLayerSpec, { title: "A" })]),
      "layer",
    );
    // Header row, then Fill and Stroke width paired on one 2-row shelf.
    expect(rowsOf(simple.surface, "style")).toBe(3);

    const categorized = operator(
      fixtureDocument([
        fixtureNode("layer", vectorLayerSpec, {
          title: "A",
          style: {
            kind: "categorized_points",
            categories: [{ id: "c1", title: "Roads", color: "#ff0000" }],
          },
        }),
      ]),
      "layer",
    );
    // Header; the list's title row, one item (its title row, then Color),
    // and the "Add" row.
    expect(rowsOf(categorized.surface, "style")).toBe(1 + (1 + 3 + 1));
    expect(categorized.card.heightCells - simple.card.heightCells).toBe(3);
  });

  it("adds one item's rows for every item an object list holds", () => {
    const style = (count: number) => ({
      kind: "categorized_points",
      categories: Array.from({ length: count }, (_, index) => ({
        id: `c${index}`,
        title: `Category ${index}`,
        color: "#ff0000",
      })),
    });
    const rows = (count: number) =>
      rowsOf(
        operator(
          fixtureDocument([
            fixtureNode("layer", vectorLayerSpec, {
              title: "A",
              style: style(count),
            }),
          ]),
          "layer",
        ).surface,
        "style",
      );
    expect(rows(2)! - rows(1)!).toBe(3);
    expect(rows(3)! - rows(2)!).toBe(3);
  });

  it("never lets the config band push the ports above it", () => {
    const { card } = operator(
      fixtureDocument([
        fixtureNode("layer", vectorLayerSpec, {
          title: "A",
          style: {
            kind: "categorized_points",
            categories: [{ id: "c1", title: "Roads", color: "#ff0000" }],
          },
        }),
      ]),
      "layer",
    );
    expect(card.ports.map(({ id, rowOffset }) => [id, rowOffset])).toEqual([
      ["features", 2],
      ["layer", 2],
    ]);
  });
});

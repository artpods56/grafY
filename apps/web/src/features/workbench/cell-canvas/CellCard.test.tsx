import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CellCard, type CellCardProps } from "./CellCard";
import type { CellCardModel } from "./cell-model";

const IMPORT_CARD: CellCardModel = {
  id: "import",
  title: "Import",
  subtitle: "csv.read",
  status: "done",
  col: 2,
  row: 1,
  widthCells: 12,
  heightCells: 6,
  ports: [
    {
      id: "source",
      name: "source",
      direction: "input",
      rowOffset: 2,
      artifactTypeId: "file.csv",
      shape: "one",
      required: true,
    },
    {
      id: "rows",
      name: "rows",
      direction: "output",
      rowOffset: 2,
      artifactTypeId: "table.row",
      shape: "many",
    },
    {
      id: "schema",
      name: "schema",
      direction: "output",
      rowOffset: 4,
      artifactTypeId: "table.schema",
      shape: "one",
    },
  ],
};

const TALL_CARD: CellCardModel = {
  id: "join",
  title: "Join",
  subtitle: "table.join",
  col: 0,
  row: 0,
  widthCells: 12,
  heightCells: 8,
  ports: [
    {
      id: "left",
      name: "left",
      direction: "input",
      rowOffset: 2,
      artifactTypeId: "table.row",
      shape: "many",
    },
    {
      id: "right",
      name: "right",
      direction: "input",
      rowOffset: 4,
      artifactTypeId: "table.row",
      shape: "many",
    },
    {
      id: "joined",
      name: "joined",
      direction: "output",
      rowOffset: 6,
      artifactTypeId: "table.row",
      shape: "many",
    },
  ],
};

function render(overrides: Partial<CellCardProps> = {}): string {
  return renderToStaticMarkup(
    <CellCard
      card={IMPORT_CARD}
      material="frost"
      selected={false}
      dragging={false}
      connectedPortIds={new Set()}
      onCardPointerDown={() => {}}
      onPortPointerDown={() => {}}
      {...overrides}
    />,
  );
}

/** The opening tag of the port button with this id. */
function portTag(html: string, portId: string): string {
  const match = new RegExp(`<button[^>]*data-port-id="${portId}"[^>]*>`).exec(
    html,
  );
  expect(match, `port ${portId}`).not.toBeNull();
  return match![0];
}

/** The markup inside the port button with this id. */
function portInner(html: string, portId: string): string {
  const match = new RegExp(
    `<button[^>]*data-port-id="${portId}"[^>]*>(.*?)</button>`,
  ).exec(html);
  expect(match, `port ${portId}`).not.toBeNull();
  return match![1] ?? "";
}

describe("CellCard", () => {
  it("covers its cells exactly and sits on its grid origin", () => {
    const html = render();
    expect(html).toContain('data-cell-card="true"');
    expect(html).toContain('data-card-id="import"');
    expect(html).toContain('data-card-header="true"');
    expect(html).toContain("width:300px");
    expect(html).toContain("height:150px");
    expect(html).toContain("transform:translate3d(50px, 25px, 0)");
    // 150 - 26 (header + gap) - 4 (bottom inset)
    expect(html).toContain("height:120px");
    expect(html).toContain("Done");
  });

  it("adds a visual offset only to the moving card", () => {
    const html = render({ visualOffset: { x: 7, y: -3 }, dragging: true });
    expect(html).toContain("transform:translate3d(57px, 22px, 0)");
    expect(html).toContain('data-dragging="true"');
    expect(html).toContain("z-index:20");
  });

  it("pins every port of a taller card to its row centre", () => {
    const html = render({ card: TALL_CARD });
    expect(html).toContain("height:200px");
    for (const port of TALL_CARD.ports) {
      const centreY = (port.rowOffset + 0.5) * 25;
      const centreX = port.direction === "input" ? -12.5 : 312.5;
      const tag = portTag(html, port.id);
      expect(tag).toContain(`left:${centreX - 15}px`);
      expect(tag).toContain(`top:${centreY - 15}px`);
    }
    // Label rows start at the plate's padding box (26 + 1px border).
    expect(html).toMatch(/data-port-row="2"[^>]*top:23px/);
    expect(html).toMatch(/data-port-row="6"[^>]*top:123px/);
  });

  it("names each port and marks its direction and connection", () => {
    const html = render({ connectedPortIds: new Set(["rows"]) });
    const source = portTag(html, "source");
    expect(source).toContain(
      'aria-label="Import input source (single file.csv)"',
    );
    expect(source).toContain('data-port-direction="input"');
    expect(source).toContain('data-port-connected="false"');
    expect(source).toContain('data-port-card-id="import"');
    const rows = portTag(html, "rows");
    expect(rows).toContain('aria-label="Import output rows (list table.row)"');
    expect(rows).toContain('data-port-direction="output"');
    expect(rows).toContain('data-port-connected="true"');
  });

  it("draws a single or double open ring, and none over a connected well", () => {
    const html = render({ connectedPortIds: new Set(["rows"]) });
    const single = portInner(html, "source");
    expect(single).toContain('data-port-ring="single"');
    expect(single.match(/<circle/g)).toHaveLength(1);

    const open = render();
    const list = portInner(open, "rows");
    expect(list).toContain('data-port-ring="list"');
    expect(list.match(/<circle/g)).toHaveLength(2);

    expect(portInner(html, "rows")).toBe("");
  });

  it("stops a connected port's stem at the well rim", () => {
    const html = render({ connectedPortIds: new Set(["rows"]) });
    expect(html).toMatch(/data-port-stem="rows"[^>]*width:5\.5px/);
    expect(html).toMatch(/data-port-stem="source"[^>]*width:11\.5px/);
  });

  it("marks the targeted port hot", () => {
    const html = render({ activePortKey: "import:schema" });
    expect(portTag(html, "schema")).toContain('data-port-hot="true"');
    expect(portTag(html, "rows")).toContain('data-port-hot="false"');
  });

  it("draws frost and liquid plates without a backdrop filter", () => {
    const frost = render({ material: "frost" });
    const liquid = render({ material: "liquid", selected: true });
    const held = render({ material: "frost", dragging: true });
    expect(frost).toContain("plateFrost");
    expect(frost).toContain("frostShadow");
    expect(liquid).toContain("plateLiquid");
    // Selected or held, the plate takes a very light edge and a soft halo.
    expect(frost).not.toContain("plateActive");
    expect(liquid).toContain("plateActive");
    expect(liquid).toContain("liquidShadowActive");
    expect(liquid).toContain('data-selected="true"');
    // A held card keeps the same edge and halo: no lift.
    expect(held).toContain("plateActive");
    expect(held).toContain("frostShadowActive");
    expect(held).not.toMatch(/Dragging|Lifted/);
    for (const html of [frost, liquid]) {
      expect(html).not.toMatch(/backdrop/i);
    }
  });
});

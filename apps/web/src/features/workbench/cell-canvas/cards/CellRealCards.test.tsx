import { readFileSync } from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import type { ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CellViewportLayer } from "../CellCanvasContext";
import {
  CellDockedBridgeLayer,
  CellEdgeSelectorPill,
  CellMarqueeOverlay,
  CellRemotePresenceLayer,
} from "../CellGlassOverlays";
import { computeOperatorCardLayout } from "../cell-card-geometry";
import type {
  AgentCardSurfaceData,
  AnnotationCardSurfaceData,
  AnnotationColorToken,
  ArtifactCardSurfaceData,
  ArtifactPreviewKind,
  CellDockedJoin,
  CellPipeAttachment,
  CellRemotePeerState,
  CollectionCardSurfaceData,
  OperatorCardSurfaceData,
} from "../cell-contracts";
import {
  ARTIFACT_CARD_OUTPUT_PORT_ID,
  artifactCardOutputRow,
  type CellCardModel,
  type CellPort,
} from "../cell-model";
import {
  CellAgentCard,
  CellAnnotationCard,
} from "./CellAnnotationAndAgentCards";
import { CellArtifactCard, CellCollectionCard } from "./CellArtifactCard";
import { CellOperatorCard } from "./CellOperatorCard";
import { buildOperatorCardsAndSurfaces } from "../cell-operator-adapter";
import {
  askModelSpec,
  fixtureDocument,
  fixtureNode,
  richRegistry,
  vectorLayerSpec,
} from "../cell-config-fixtures.test-support";
import { CellCard } from "../CellCard";
import { PUNCHED_LABEL_INSET } from "../punched-port";

// --- Helpers ---------------------------------------------------------------

/** The opening tag of the first element carrying `attribute="value"`. */
function tagWith(html: string, attribute: string, value: string): string {
  const match = new RegExp(`<[a-z]+[^>]*${attribute}="${value}"[^>]*>`).exec(
    html,
  );
  expect(match, `${attribute}="${value}"`).not.toBeNull();
  return match![0];
}

function portTag(html: string, portId: string): string {
  return tagWith(html, "data-port-id", portId);
}

function stemTag(html: string, portId: string): string {
  return tagWith(html, "data-port-stem", portId);
}

/** Where a port's 30px hit target sits for its row and side, as `CellCard` places it. */
function expectPortPinned(html: string, port: CellPort, widthCells: number) {
  const centreX = port.direction === "input" ? -12.5 : widthCells * 25 + 12.5;
  const centreY = (port.rowOffset + 0.5) * 25;
  const tag = portTag(html, port.id);
  expect(tag).toContain(`left:${centreX - 15}px`);
  expect(tag).toContain(`top:${centreY - 15}px`);
}

function expectExactBox(html: string, widthCells: number, heightCells: number) {
  const root = tagWith(html, "data-cell-card", "true");
  expect(root).toContain(`width:${widthCells * 25}px`);
  expect(root).toContain(`height:${heightCells * 25}px`);
}

function count(html: string, pattern: RegExp): number {
  return html.match(new RegExp(pattern.source, "g"))?.length ?? 0;
}

// --- Operator card ---------------------------------------------------------

const OPERATOR_PORTS: readonly CellPort[] = [
  {
    id: "source",
    name: "source",
    direction: "input",
    rowOffset: 2,
    artifactTypeId: "table.row",
    shape: "many",
    required: true,
  },
  {
    id: "result",
    name: "result",
    direction: "output",
    rowOffset: 2,
    artifactTypeId: "table.row",
    shape: "many",
  },
  {
    id: "report",
    name: "report",
    direction: "output",
    rowOffset: 4,
    artifactTypeId: "text.markdown",
    shape: "one",
  },
  // A plug the model already lists; the second plug is synthesized by the card.
  {
    id: "images:0",
    name: "images",
    direction: "input",
    rowOffset: 4,
    artifactTypeId: "image.raster",
    shape: "one",
  },
];

const PLUGS: NonNullable<OperatorCardSurfaceData["instancePlugGroups"]> = [
  {
    portName: "images",
    title: "image",
    artifactTypeId: "image.raster",
    shape: "one",
    startRowOffset: 4,
    plugs: [
      {
        plugId: "images:0",
        label: "Cover",
        connected: true,
        connectionMeta: "png",
      },
      { plugId: "images:1", label: "Inset", connected: false },
    ],
    canAdd: true,
  },
];

const CONFIG_FIELDS: NonNullable<OperatorCardSurfaceData["configFields"]> = [
  {
    id: "prefix",
    label: "Prefix",
    kind: "text",
    value: "out_",
    span: 1,
  },
  { id: "limit", label: "Limit", kind: "number", value: 25, span: 1 },
  {
    id: "mode",
    label: "Mode",
    kind: "select",
    value: "inner",
    options: [
      { value: "inner", label: "Inner" },
      { value: "outer", label: "Outer" },
    ],
  },
  { id: "dedupe", label: "Dedupe", kind: "toggle", value: true },
  {
    id: "notes",
    label: "Notes",
    kind: "multiline",
    value: "keep it short",
  },
];

function operatorSurface(
  overrides: Partial<OperatorCardSurfaceData> = {},
): OperatorCardSurfaceData {
  return {
    kind: "operator",
    statusLabel: "Ready",
    configFields: CONFIG_FIELDS,
    instancePlugGroups: PLUGS,
    appendix: {
      title: "Last run",
      kindBadge: "table",
      heightCells: 6,
      collapsed: true,
      summaryText: "120 rows in 0.4s",
      previewLines: ["id,name", "1,alpha", "2,beta"],
      itemCount: 120,
    },
    ...overrides,
  };
}

function operatorCard(surface: OperatorCardSurfaceData): CellCardModel {
  const base: CellCardModel = {
    id: "merge",
    title: "Merge",
    subtitle: "table.merge",
    kind: "operator",
    status: "done",
    col: 6,
    row: 4,
    widthCells: 12,
    heightCells: 4,
    ports: OPERATOR_PORTS,
    resizable: true,
  };
  return {
    ...base,
    heightCells: computeOperatorCardLayout(base, surface).totalHeightCells,
  };
}

function renderOperator(
  surface: OperatorCardSurfaceData,
  extra: Partial<ComponentProps<typeof CellOperatorCard>> = {},
): { html: string; card: CellCardModel } {
  const card = operatorCard(surface);
  const html = renderToStaticMarkup(
    <CellOperatorCard
      card={card}
      surface={surface}
      selected={false}
      dragging={false}
      connectedPortIds={new Set(["result"])}
      onRun={() => {}}
      onAddPlug={() => {}}
      onRemovePlug={() => {}}
      onConfigChange={() => {}}
      onToggleAppendix={() => {}}
      {...extra}
    />,
  );
  return { html, card };
}

describe("CellOperatorCard", () => {
  it("lays out header, ports, plugs, config and appendix on whole cells", () => {
    const surface = operatorSurface();
    const layout = computeOperatorCardLayout(operatorCard(surface), surface);
    expect(layout.portBand).toEqual({ startRow: 2, heightCells: 3 });
    expect(layout.plugBand).toEqual({ startRow: 4, heightCells: 5 });
    // Prefix + Limit share a dense row; select, toggle 1 each; multiline 3.
    expect(layout.configBand).toEqual({ startRow: 10, heightCells: 6 });
    expect(layout.appendixBand).toEqual({ startRow: 16, heightCells: 2 });
    expect(layout.totalHeightCells).toBe(18);
  });

  it("renders the floating header with title, status and run action", () => {
    const { html, card } = renderOperator(operatorSurface(), {
      selected: true,
    });
    expectExactBox(html, 12, 18);
    expect(card.heightCells).toBe(18);
    expect(html).toContain('data-card-kind="operator"');
    const header = html.slice(
      html.indexOf('data-card-header="true"'),
      html.indexOf("<article"),
    );
    expect(header).toContain("Merge");
    expect(header).toContain('data-card-status="done"');
    expect(header).toContain("Ready");
    expect(header).toContain('aria-label="Run Merge"');
  });

  it("shows only the quiet title at rest, every header action once selected", () => {
    const header = (html: string) =>
      html.slice(
        html.indexOf('data-card-header="true"'),
        html.indexOf("<article"),
      );
    const rest = header(renderOperator(operatorSurface()).html);
    expect(rest).toContain("Merge");
    expect(rest).toContain('data-card-title="rest"');
    expect(rest).not.toContain("data-card-header-actions");
    expect(rest).not.toContain('aria-label="Run Merge"');
    expect(rest).not.toContain('data-card-status="done"');
    expect(rest).not.toContain('data-card-menu="true"');

    const selected = header(
      renderOperator(operatorSurface(), { selected: true }).html,
    );
    expect(selected).toContain('data-card-header-actions="true"');
    expect(selected).toContain('aria-label="Run Merge"');
    expect(selected).toContain('data-card-status="done"');
    expect(selected).toContain('data-card-menu="true"');

    const held = header(
      renderOperator(operatorSurface(), { selected: true, dragging: true })
        .html,
    );
    expect(held).toContain('data-card-title="selected"');
    expect(held).not.toContain("data-card-header-actions");
    expect(held).not.toContain('aria-label="Run Merge"');
    expect(held).not.toContain('data-card-menu="true"');
  });

  it("omits the run action without an onRun handler", () => {
    const { html } = renderOperator(operatorSurface(), {
      selected: true,
      onRun: undefined,
    });
    expect(html).not.toContain('aria-label="Run Merge"');
  });

  it("starts the plate at 26px with no strip, the title at the top of row 0", () => {
    const { html } = renderOperator(operatorSurface());
    expect(html).not.toContain("data-card-strip");
    expect(html).not.toContain("table.merge");
    // The 24px title sits at the top of row 0, 2px above the plate.
    expect(html).toMatch(
      /data-card-header="true"[^>]*margin-top:0;height:24px/,
    );
    // 18 cells: 450 - 26 (header + gap) - 4 (bottom inset).
    expect(html).toMatch(/<article[^>]*height:420px/);
  });

  it("frames a selected or held plate with a light edge and halo, no lift", () => {
    const rest = renderOperator(operatorSurface()).html;
    const selected = renderOperator(operatorSurface(), {
      selected: true,
    }).html;
    const dragging = renderOperator(operatorSurface(), {
      selected: true,
      dragging: true,
    }).html;
    const plateClass = (html: string) =>
      /<article[^>]*class="([^"]*)"/.exec(html)?.[1];
    expect(plateClass(rest)).toBe("plate plateFrost frostShadow");
    expect(plateClass(selected)).toBe(
      "plate plateFrost plateActive frostShadowActive",
    );
    // A held card keeps the same edge and halo: no deeper drag shadow.
    expect(plateClass(dragging)).toBe(plateClass(selected));
    expect(selected).toContain('data-card-title="selected"');
  });

  it("puts the ⋯ beside the run button in the floating header", () => {
    const { html } = renderOperator(operatorSurface(), { selected: true });
    const header = html.slice(
      html.indexOf('data-card-header="true"'),
      html.indexOf("<article"),
    );
    const run = header.indexOf('aria-label="Run Merge"');
    const menu = header.indexOf('data-card-menu="true"');
    expect(run).toBeGreaterThan(-1);
    expect(menu).toBeGreaterThan(run);
  });

  it("pairs regular ports by row and keeps plug ports out of them", () => {
    const { html } = renderOperator(operatorSurface());
    expect(html).toMatch(/data-port-row="2"[^>]*top:23px/);
    expect(html).toMatch(/data-port-row="4"[^>]*top:73px/);
    const row2 = html.slice(html.indexOf('data-port-row="2"'));
    expect(row2.slice(0, row2.indexOf("data-port-row=", 20))).toContain(
      "source",
    );
    expect(count(html, /data-port-row="/)).toBe(2);
  });

  it("renders instance plugs with a synthesized port for an unlisted plug", () => {
    const { html, card } = renderOperator(operatorSurface());
    expect(html).toMatch(/data-instance-plug-row="images:0"[^>]*top:73px/);
    expect(html).toMatch(/data-instance-plug-row="images:1"[^>]*top:123px/);
    expect(html).toContain("#1");
    expect(html).toContain("#2");
    expect(html).toContain("Cover");
    expect(html).toContain("Inset");
    expect(html).toContain('aria-label="Remove Inset"');
    expect(html).toMatch(/data-instance-plug-add="images"[^>]*top:173px/);
    expect(html).toContain("Add image");

    // The listed plug keeps its own port; the unlisted one gets a stem and button.
    expect(card.ports.some((port) => port.id === "images:1")).toBe(false);
    expect(portTag(html, "images:1")).toContain('data-port-card-id="merge"');
    expect(portTag(html, "images:1")).toContain('data-port-direction="input"');
    expectPortPinned(
      html,
      {
        id: "images:1",
        name: "Inset",
        direction: "input",
        rowOffset: 6,
        artifactTypeId: "image.raster",
        shape: "one",
      },
      12,
    );
    expect(stemTag(html, "images:1")).toContain("width:11.5px");
    // A plug the surface reports connected stops at the well rim.
    expect(portTag(html, "images:0")).toContain('data-port-connected="true"');
    expect(stemTag(html, "images:0")).toContain("width:5.5px");
  });

  it("renders every config field kind in the dense shelf band", () => {
    const { html } = renderOperator(operatorSurface());
    // Config band starts on row 10: 10 * 25 - 27; six cells tall.
    expect(html).toMatch(/data-config-band="true"[^>]*top:223px;height:150px/);
    for (const field of CONFIG_FIELDS) {
      expect(html).toContain(`data-config-field="${field.id}"`);
      expect(html).toContain(field.label);
    }
    // Each field is pinned to the shelf row and column its rows were counted
    // for: Prefix and Limit share shelf 1, Mode and Dedupe take a shelf each.
    expect(html).toMatch(
      /data-config-field="prefix"[^>]*grid-row:1 \/ span 1;grid-column:1 \/ span 1/,
    );
    expect(html).toMatch(
      /data-config-field="limit"[^>]*grid-row:1 \/ span 1;grid-column:2 \/ span 1/,
    );
    expect(html).toMatch(/data-config-field="mode"[^>]*grid-column:1 \/ -1/);
    expect(html).toMatch(/data-config-field="notes"[^>]*grid-row:4 \/ span 3/);
    expect(html).toContain('value="out_"');
    expect(html).toContain('type="number"');
    expect(html).toContain("<select");
    expect(html).toContain("<textarea");
    expect(html).toContain("keep it short");
    expect(html).toContain('role="switch"');
  });

  it("renders a collapsed appendix as two cells with an inline summary", () => {
    const { html } = renderOperator(operatorSurface());
    // The last band stops at the plate's content edge: 5px short of its cell
    // for the plate's bottom border and the card's 4px bottom inset.
    expect(html).toMatch(
      /data-appendix-band="collapsed"[^>]*top:373px;height:45px/,
    );
    expect(html).toContain("Last run");
    expect(html).toContain("120 rows in 0.4s");
    expect(html).toContain('aria-label="Expand appendix"');
    expect(html).not.toContain('data-appendix-preview="true"');
  });

  it("renders an expanded appendix over its own cell rows", () => {
    const surface = operatorSurface({
      appendix: { ...operatorSurface().appendix!, collapsed: false },
    });
    const { html } = renderOperator(surface);
    expectExactBox(html, 12, 22);
    expect(html).toMatch(
      /data-appendix-band="expanded"[^>]*top:373px;height:145px/,
    );
    expect(html).toContain('data-appendix-preview="true"');
    expect(html).toContain("2,beta");
    expect(html).toContain('aria-label="Collapse appendix"');
  });

  it("keeps every port pinned whatever config and appendix it shows", () => {
    const bare = renderOperator(
      operatorSurface({ configFields: [], appendix: null }),
    ).html;
    const collapsed = renderOperator(operatorSurface()).html;
    const expanded = renderOperator(
      operatorSurface({
        appendix: { ...operatorSurface().appendix!, collapsed: false },
      }),
    ).html;
    const portIds = [...OPERATOR_PORTS.map((port) => port.id), "images:1"];
    for (const id of portIds) {
      expect(portTag(collapsed, id)).toBe(portTag(bare, id));
      expect(portTag(expanded, id)).toBe(portTag(bare, id));
      expect(stemTag(collapsed, id)).toBe(stemTag(bare, id));
      expect(stemTag(expanded, id)).toBe(stemTag(bare, id));
    }
    for (const port of OPERATOR_PORTS) expectPortPinned(expanded, port, 12);
    expect(stemTag(expanded, "result")).toContain("width:5.5px");
    expect(stemTag(expanded, "source")).toContain("width:11.5px");
    expect(stemTag(expanded, "report")).toContain("width:11.5px");
  });

  it("shows a resize grip only when selected or hovered", () => {
    const rest = renderOperator(operatorSurface()).html;
    const selected = renderOperator(operatorSurface(), {
      selected: true,
    }).html;
    expect(rest).not.toContain("data-cell-resize-grip");
    expect(selected).toContain('data-cell-resize-grip="se"');
  });

  it("emits drop attrs on non-service inputs, status semantics, and avoids composite plug duplicates", () => {
    const servicePort: CellPort = {
      id: "service",
      name: "Service",
      direction: "input",
      rowOffset: 3,
      artifactTypeId: "llm.chat",
      shape: "one",
      kind: "service",
      serviceContractLabel: "Chat Model Service",
    };
    const compositeCard: CellCardModel = {
      id: "merge",
      title: "Merge",
      subtitle: "table.merge",
      kind: "operator",
      status: "done",
      col: 6,
      row: 4,
      widthCells: 12,
      heightCells: 14,
      ports: [
        OPERATOR_PORTS[0]!,
        servicePort,
        {
          id: "incoming::plug-a",
          name: "Plug 1",
          direction: "input",
          rowOffset: 5,
          artifactTypeId: "image.raster",
          shape: "one",
        },
      ],
    };
    const surface = operatorSurface({
      instancePlugGroups: [
        {
          portName: "incoming",
          title: "Incoming",
          artifactTypeId: "image.raster",
          shape: "one",
          startRowOffset: 5,
          plugs: [{ plugId: "plug-a", label: "Plug 1", connected: true }],
          canAdd: false,
        },
      ],
    });
    const html = renderToStaticMarkup(
      <CellOperatorCard
        card={compositeCard}
        surface={surface}
        selected
        dragging={false}
        onRun={() => {}}
      />,
    );

    const statusBadge = tagWith(html, "data-card-status", "done");
    expect(statusBadge).toContain('role="status"');
    expect(statusBadge).toContain('aria-label="Merge done"');

    const fixedDropPort = portTag(html, "source");
    expect(fixedDropPort).toContain('data-input-node-id="merge"');
    expect(fixedDropPort).toContain('data-input-port-name="source"');

    const svcPort = portTag(html, "service");
    expect(svcPort).toContain('data-port-kind="service"');
    expect(svcPort).not.toContain("data-input-node-id");
    expect(html).toContain("· service");

    expect(count(html, /data-port-id="incoming::plug-a"/)).toBe(1);
    expect(count(html, /data-port-id="plug-a"/)).toBe(0);
    const plugRow = tagWith(html, "data-instance-plug-row", "plug-a");
    expect(plugRow).toContain('data-input-node-id="merge"');
    expect(plugRow).toContain('data-input-plug-port="incoming"');
    expect(plugRow).toContain('data-input-plug-id="plug-a"');
  });
});

// --- Artifact and collection cards -----------------------------------------

const ARTIFACT_CARD: CellCardModel = {
  id: "photo",
  title: "Photo",
  subtitle: "image.raster",
  kind: "artifact",
  col: 0,
  row: 0,
  widthCells: 10,
  heightCells: 8,
  ports: [
    {
      id: "in",
      name: "in",
      direction: "input",
      rowOffset: 2,
      artifactTypeId: "image.raster",
      shape: "one",
    },
    {
      id: "out",
      name: "out",
      direction: "output",
      rowOffset: 4,
      artifactTypeId: "image.raster",
      shape: "one",
    },
  ],
};

const PREVIEWS: Record<ArtifactPreviewKind, ArtifactCardSurfaceData> = {
  image: {
    kind: "artifact",
    previewKind: "image",
    artifactTypeId: "image.raster",
    typeLabel: "Raster image",
    filename: "cover.png",
    dimensionsLabel: "640×480",
    imageUrl: "https://example.test/cover.png",
  },
  table: {
    kind: "artifact",
    previewKind: "table",
    artifactTypeId: "table.row",
    typeLabel: "Table",
    tableHeaders: ["id", "name"],
    tableRows: [
      ["1", "alpha"],
      ["2", "beta"],
    ],
  },
  markdown: {
    kind: "artifact",
    previewKind: "markdown",
    artifactTypeId: "text.markdown",
    typeLabel: "Markdown",
    previewText: "# Summary\n- first point\nplain line",
  },
  file: {
    kind: "artifact",
    previewKind: "file",
    artifactTypeId: "file.pdf",
    typeLabel: "PDF",
    filename: "report.pdf",
    byteSizeLabel: "1.2 MB",
  },
  map: {
    kind: "artifact",
    previewKind: "map",
    artifactTypeId: "gis.vector",
    typeLabel: "Vector layer",
    previewText: "Parcels",
    dimensionsLabel: "EPSG:4326",
  },
};

const PREVIEW_TEXT: Record<ArtifactPreviewKind, readonly string[]> = {
  image: ['src="https://example.test/cover.png"', 'alt="cover.png"'],
  table: ['scope="col"', "alpha", "beta"],
  markdown: ["Summary", "• first point", "plain line"],
  file: ["report.pdf", "PDF · 1.2 MB"],
  map: ["Parcels", "Vector layer", "EPSG:4326"],
};

function renderArtifact(
  surface: ArtifactCardSurfaceData,
  extra: Partial<ComponentProps<typeof CellArtifactCard>> = {},
): string {
  return renderToStaticMarkup(
    <CellArtifactCard
      card={ARTIFACT_CARD}
      surface={surface}
      selected={false}
      dragging={false}
      connectedPortIds={new Set(["out"])}
      {...extra}
    />,
  );
}

describe("CellArtifactCard", () => {
  for (const kind of Object.keys(PREVIEWS) as ArtifactPreviewKind[]) {
    it(`renders a ${kind} preview inside its exact cells`, () => {
      const html = renderArtifact(PREVIEWS[kind]);
      expectExactBox(html, 10, 8);
      expect(html).toContain('data-card-kind="artifact"');
      expect(html).toContain(`data-artifact-preview="${kind}"`);
      for (const text of PREVIEW_TEXT[kind]) expect(html).toContain(text);
      expect(html).not.toMatch(/canvasCardRail|card-rail|data-rail/i);
    });
  }

  it("keeps its ports on its own edges in the glass stage's wells", () => {
    const html = renderArtifact(PREVIEWS.image);
    for (const port of ARTIFACT_CARD.ports) {
      expectPortPinned(html, port, 10);
      expect(portTag(html, port.id)).toContain('data-port-card-id="photo"');
    }
    expect(stemTag(html, "in")).toContain("width:11.5px");
    expect(stemTag(html, "out")).toContain("width:5.5px");
  });

  it("has no inner strip and names its file in the floating header", () => {
    const html = renderArtifact(PREVIEWS.image);
    expect(html).not.toContain("data-card-strip");
    const header = /<div data-card-header="true"[\s\S]*?<\/div><article/.exec(
      html,
    )?.[0];
    expect(header).toContain(">Photo<");
    expect(header).toContain('<span data-card-meta="true" title="cover.png"');
    expect(header).toContain(">cover.png</span>");
    // No type dot: the title names the type, the filename names the file.
    expect(header).not.toMatch(/class="[^"]*dot/i);
    expect(header).not.toContain("640×480");
    expect(header).not.toContain("Raster image");
  });

  it("keeps the whole type title and ellipsizes a long file name beside it", () => {
    const filename = "887ACF23-B925-4963-9A2F-0C1D2E3F4A5B.jpeg";
    const html = renderArtifact({ ...PREVIEWS.image, filename });
    const header = /<div data-card-header="true"[\s\S]*?<\/div><article/.exec(
      html,
    )?.[0];
    // The title never shrinks: the file name takes what is left and gives way.
    expect(tagWith(header ?? "", "data-card-title", "rest")).toContain(
      'class="title titleFixed"',
    );
    expect(header).toContain(">Photo<");
    const meta = tagWith(header ?? "", "data-card-meta", "true");
    expect(meta).toContain('class="headerMeta"');
    expect(meta).toContain(`title="${filename}"`);
    expect(header).toContain(`<span class="ellipsis">${filename}</span>`);
    // An operator's long title still ellipsizes in a narrow card.
    const { html: operator } = renderOperator(operatorSurface());
    expect(tagWith(operator, "data-card-title", "rest")).toContain(
      'class="title"',
    );
  });

  it("falls back to its one measure, or leaves the header slot empty", () => {
    const { filename: _filename, ...unnamed } = PREVIEWS.image;
    const measured = renderArtifact(unnamed);
    expect(measured).toContain('<span data-card-meta="true" title="640×480"');
    const sized = renderArtifact({
      ...unnamed,
      dimensionsLabel: undefined,
      byteSizeLabel: "12 KB",
    });
    expect(sized).toContain('<span data-card-meta="true" title="12 KB"');
    const bare = renderArtifact({ ...unnamed, dimensionsLabel: undefined });
    expect(bare).not.toContain("data-card-meta");
  });

  it("paints a picture edge to edge over the checkerboard, framed by a hairline", () => {
    const html = renderArtifact(PREVIEWS.image);
    expect(html).toContain('data-artifact-preview="image"');
    expect(html).toContain('data-artifact-image-frame="true"');
    expect(html).not.toContain("data-artifact-stack-back");
    expect(html).not.toContain("data-artifact-stack-count");
  });

  it("keeps a TIFF on its placeholder icon", () => {
    const html = renderArtifact({
      ...PREVIEWS.image,
      artifactTypeId: "file.tiff",
      imageUrl: null,
    });
    expect(html).toContain('data-artifact-placeholder="image"');
    expect(html).not.toContain("<img");
    expect(html).not.toContain("data-artifact-image-frame");
  });

  it("fans a sequence's next items behind the plate with one count", () => {
    const html = renderArtifact({
      ...PREVIEWS.image,
      dimensionsLabel: "3 items",
      itemCount: 3,
      stackImageUrls: [
        "https://example.test/2.png",
        "https://example.test/3.png",
      ],
    });
    expect(html).toContain('data-artifact-stack-back="1"');
    expect(html).toContain('data-artifact-stack-back="2"');
    expect(html).toContain('src="https://example.test/2.png"');
    expect(html).toContain('src="https://example.test/3.png"');
    expect(html).toContain('data-artifact-stack-count="3"');
    // The count is said once in the header as bare text (no pill icon or
    // duplicate measure).
    expect(html.match(/>3 items</g)).toHaveLength(1);
    expect(html).not.toContain('data-artifact-stack-count="3"><svg');
    // The backs paint under the plate: before the <article> in the box.
    expect(html.indexOf("data-artifact-stack-back")).toBeLessThan(
      html.indexOf("<article"),
    );
  });

  it("makes a sequence's count in the header the button that lays it open", () => {
    const surface = { ...PREVIEWS.image, itemCount: 3, stackImageUrls: [] };
    const html = renderArtifact(surface, { onExpandSequence: () => {} });
    const count = tagWith(html, "data-artifact-stack-count", "3");
    expect(count.startsWith("<button")).toBe(true);
    expect(count).toContain('aria-label="Expand sequence (3 items)"');
    expect(count).toContain('aria-expanded="false"');
    expect(count).toContain('data-sequence-expanded="false"');
    expect(count).not.toContain("disabled");
    // In the header's right slot, in place of the file name, and nowhere on
    // the picture: the header comes before the plate.
    const header = html.slice(
      html.indexOf('data-card-header="true"'),
      html.indexOf("<article"),
    );
    expect(header).toContain('data-artifact-stack-count="3"');
    expect(header).toContain('data-card-meta="true"');
    expect(header).not.toContain(PREVIEWS.image.filename ?? "\u0000");
    const plate = html.slice(html.indexOf("<article"));
    expect(plate).not.toContain("data-artifact-stack-count");
    const open = renderArtifact(surface, {
      onExpandSequence: () => {},
      sequenceExpanded: true,
    });
    expect(tagWith(open, "data-artifact-stack-count", "3")).toContain(
      'aria-expanded="true"',
    );
    // Without the command it stays a quiet label.
    expect(
      tagWith(
        renderArtifact(surface),
        "data-artifact-stack-count",
        "3",
      ).startsWith("<span"),
    ).toBe(true);
  });

  it("disables the count of a stack boxed in too tightly to spread", () => {
    const surface = { ...PREVIEWS.image, itemCount: 3, stackImageUrls: [] };
    const count = tagWith(
      renderArtifact(surface, {
        onExpandSequence: () => {},
        canExpandSequence: false,
      }),
      "data-artifact-stack-count",
      "3",
    );
    expect(count).toContain('disabled=""');
    expect(count).toContain('title="Move card into open space to spread"');
  });

  it("keeps a single card's file name in the header", () => {
    const html = renderArtifact(PREVIEWS.image, { onExpandSequence: () => {} });
    expect(html).not.toContain("data-artifact-stack-count");
    expect(html).toContain(`title="${PREVIEWS.image.filename}"`);
  });

  it("draws one back for a two-item sequence", () => {
    const html = renderArtifact({
      ...PREVIEWS.image,
      itemCount: 2,
      stackImageUrls: ["https://example.test/2.png"],
    });
    expect(html).toContain('data-artifact-stack-back="1"');
    expect(html).not.toContain('data-artifact-stack-back="2"');
  });

  it("pins the fanned backs through the corner hole and turns them counter-clockwise", () => {
    const html = renderArtifact({
      ...PREVIEWS.image,
      itemCount: 3,
      stackImageUrls: [],
    });
    const first = tagWith(html, "data-artifact-stack-back", "1");
    const second = tagWith(html, "data-artifact-stack-back", "2");
    // Each back is the plate's own box (4px in, 26px down, 242×170)...
    for (const back of [first, second]) {
      expect(back).toContain("top:26px");
      expect(back).toContain("left:4px");
      expect(back).toContain("width:242px");
      expect(back).toContain("height:170px");
      // ...pivoting on the output hole at (250-22, 200-22) in card space.
      expect(back).toContain("transform-origin:224px 152px");
    }
    // A 242px plate keeps its far corners within 6px / 12px of the plate.
    expect(first).toContain("transform:rotate(-1.42deg)");
    expect(second).toContain("transform:rotate(-2.84deg)");
  });

  it("caps the fan's turn on a narrow card", () => {
    const html = renderArtifact(
      { ...PREVIEWS.image, itemCount: 3 },
      { card: { ...ARTIFACT_CARD, widthCells: 6 } },
    );
    expect(tagWith(html, "data-artifact-stack-back", "1")).toContain(
      "transform:rotate(-1.8deg)",
    );
    expect(tagWith(html, "data-artifact-stack-back", "2")).toContain(
      "transform:rotate(-3.6deg)",
    );
  });

  it("shows its ⋯ menu and grip only while selected and at rest", () => {
    const actions = { onInspect: () => {}, onRemove: () => {} };
    const hovered = renderArtifact(PREVIEWS.file, {
      ...actions,
      hovered: true,
    });
    expect(hovered).not.toContain('data-card-menu="true"');
    expect(hovered).not.toContain("data-card-header-actions");
    expect(hovered).not.toContain("data-cell-resize-grip");
    expect(hovered).toContain('data-card-title="rest"');

    const selected = renderArtifact(PREVIEWS.file, {
      ...actions,
      selected: true,
    });
    expect(selected).not.toContain("data-cell-card-toolbar");
    expect(selected).toContain('data-card-menu="true"');
    expect(selected).toContain('data-card-header-actions="true"');
    expect(selected).toContain('aria-label="Actions for Photo"');
    expect(selected).toContain('data-card-title="selected"');
    expect(selected).toContain('data-cell-resize-grip="se"');

    const dragging = renderArtifact(PREVIEWS.file, {
      ...actions,
      selected: true,
      dragging: true,
    });
    expect(dragging).not.toContain('data-card-menu="true"');
    expect(dragging).not.toContain("data-card-header-actions");
    expect(dragging).not.toContain("data-cell-resize-grip");
    expect(dragging).toContain('data-card-title="selected"');
  });
});

const COLLECTION_SURFACE: CollectionCardSurfaceData = {
  kind: "collection",
  artifactTypeId: "image.raster",
  typeLabel: "Raster image",
  members: [
    {
      id: "m1",
      label: "north.png",
      artifactTypeId: "image.raster",
      typeLabel: "Raster image",
      meta: "2 MB",
    },
    {
      id: "m2",
      label: "south.png",
      artifactTypeId: "image.raster",
      typeLabel: "Raster image",
    },
    {
      id: "m3",
      label: "east.png",
      artifactTypeId: "image.raster",
      typeLabel: "Raster image",
    },
  ],
  showSparePlug: true,
};

const COLLECTION_CARD: CellCardModel = {
  id: "shots",
  title: "Shots",
  subtitle: "collection",
  kind: "collection",
  col: 2,
  row: 2,
  widthCells: 10,
  heightCells: 10,
  ports: COLLECTION_SURFACE.members.map((member, index) => ({
    id: `member:${member.id}`,
    name: member.label,
    direction: "input" as const,
    rowOffset: 2 + index * 2,
    artifactTypeId: member.artifactTypeId,
    shape: "one" as const,
  })),
};

describe("CellCollectionCard", () => {
  it("puts each member on its own cell row beside its port, then a spare plug", () => {
    const html = renderToStaticMarkup(
      <CellCollectionCard
        card={COLLECTION_CARD}
        surface={COLLECTION_SURFACE}
        selected={false}
        dragging={false}
        onRemoveMember={() => {}}
      />,
    );
    expectExactBox(html, 10, 10);
    expect(html).toContain('data-card-kind="collection"');
    // The count is a header action: hidden at rest, shown once selected.
    expect(html).not.toContain('data-collection-count="3"');
    const selected = renderToStaticMarkup(
      <CellCollectionCard
        card={COLLECTION_CARD}
        surface={COLLECTION_SURFACE}
        selected
        dragging={false}
        onRemoveMember={() => {}}
      />,
    );
    expect(selected).toContain('data-collection-count="3"');
    expect(selected).toContain("3 items");
    COLLECTION_SURFACE.members.forEach((member, index) => {
      expect(html).toMatch(
        new RegExp(
          `data-collection-member="${member.id}"[^>]*top:${(2 + index * 2) * 25 - 27}px;height:50px`,
        ),
      );
      expect(html).toContain(member.label);
      expect(html).toContain(`aria-label="Remove ${member.label}"`);
    });
    for (const port of COLLECTION_CARD.ports) expectPortPinned(html, port, 10);
    expect(html).toMatch(
      /data-collection-spare-plug="true"[^>]*top:173px;height:50px/,
    );
    expect(html).toContain("Drop / wire item");
    expect(html).not.toMatch(/canvasCardRail|card-rail|data-rail/i);
  });

  it("leaves the spare plug out when the surface does not ask for it", () => {
    const html = renderToStaticMarkup(
      <CellCollectionCard
        card={COLLECTION_CARD}
        surface={{ ...COLLECTION_SURFACE, showSparePlug: false }}
      />,
    );
    expect(html).not.toContain("data-collection-spare-plug");
  });

  it("annotates member rows and spare plug rows with artifact drop target attributes", () => {
    const html = renderToStaticMarkup(
      <CellCollectionCard
        card={COLLECTION_CARD}
        surface={{ ...COLLECTION_SURFACE, sparePlugId: "spare-1" }}
      />,
    );
    const firstMember = tagWith(html, "data-collection-member", "m1");
    expect(firstMember).toContain('data-input-node-id="shots"');
    expect(firstMember).toContain('data-input-plug-port="items"');
    expect(firstMember).toContain('data-input-plug-id="m1"');

    const spareRow = tagWith(html, "data-collection-spare-plug", "true");
    expect(spareRow).toContain('data-input-node-id="shots"');
    expect(spareRow).toContain('data-input-plug-port="items"');
    expect(spareRow).toContain('data-input-plug-id="spare-1"');
  });
});

// --- Annotation and agent cards --------------------------------------------

const ANNOTATION_CARD: CellCardModel = {
  id: "zone",
  title: "Ingest zone",
  subtitle: "",
  kind: "annotation",
  col: 4,
  row: 6,
  widthCells: 16,
  heightCells: 12,
  ports: [],
};

const ANNOTATION_COLORS: readonly AnnotationColorToken[] = [
  "slate",
  "blue",
  "emerald",
  "amber",
  "violet",
  "rose",
];

function annotationSurface(
  variant: AnnotationCardSurfaceData["variant"],
  color: AnnotationColorToken,
): AnnotationCardSurfaceData {
  return {
    kind: "annotation",
    variant,
    color,
    bodyText: "Everything that reads raw files",
    layer: "under-cards",
  };
}

describe("CellAnnotationCard", () => {
  for (const color of ANNOTATION_COLORS) {
    it(`renders a ${color} frame for the under-cards layer`, () => {
      const html = renderToStaticMarkup(
        <CellViewportLayer
          layer="under-cards"
          viewport={{ x: 0, y: 0, zoom: 1 }}
        >
          <CellAnnotationCard
            card={ANNOTATION_CARD}
            surface={annotationSurface("frame", color)}
            selected={false}
            dragging={false}
          />
        </CellViewportLayer>,
      );
      expect(html).toContain('data-cell-viewport-layer="under-cards"');
      expect(html).toContain('data-annotation-variant="frame"');
      expect(html).toContain(`data-annotation-color="${color}"`);
      expect(html).toContain('data-annotation-label="true"');
      expect(html).toContain("Ingest zone");
      expect(html).toContain("Everything that reads raw files");
      expectExactBox(html, 16, 12);
      expect(html).toContain("transform:translate3d(100px, 150px, 0)");
      expect(html).toMatch(/background-color:light-dark\(color-mix/);
      // A frame has no plate and no header: it is tint on the glass.
      expect(html).not.toContain("<article");
      expect(html).not.toContain("data-card-header");
    });
  }

  it("outlines a selected frame and offers its resize grip", () => {
    const html = renderToStaticMarkup(
      <CellAnnotationCard
        card={ANNOTATION_CARD}
        surface={annotationSurface("frame", "blue")}
        selected
      />,
    );
    expect(html).toContain('data-selected="true"');
    expect(html).toContain("frameSelected");
    expect(html).toContain('data-cell-resize-grip="se"');
  });

  for (const color of ANNOTATION_COLORS) {
    it(`renders a ${color} note on the card plane`, () => {
      const html = renderToStaticMarkup(
        <CellAnnotationCard
          card={ANNOTATION_CARD}
          surface={annotationSurface("note", color)}
          selected={false}
        />,
      );
      expect(html).toContain('data-annotation-variant="note"');
      expect(html).toContain(`data-annotation-color="${color}"`);
      expect(html).toContain('data-annotation-body="true"');
      expect(html).toContain("<article");
      expectExactBox(html, 16, 12);
      expect(html).not.toContain("data-cell-card-toolbar");
    });
  }

  it("offers colour swatches on a selected note", () => {
    const html = renderToStaticMarkup(
      <CellAnnotationCard
        card={ANNOTATION_CARD}
        surface={annotationSurface("note", "amber")}
        selected
        onColorChange={() => {}}
      />,
    );
    expect(html).toContain('data-cell-card-toolbar="top"');
    for (const color of ANNOTATION_COLORS) {
      expect(html).toContain(`data-annotation-swatch="${color}"`);
    }
    expect(tagWith(html, "data-annotation-swatch", "amber")).toContain(
      'aria-pressed="true"',
    );
    expect(tagWith(html, "data-annotation-swatch", "rose")).not.toContain(
      'aria-pressed="true"',
    );
  });

  it("leaves swatches out of a selected note without onColorChange", () => {
    const html = renderToStaticMarkup(
      <CellAnnotationCard
        card={ANNOTATION_CARD}
        surface={annotationSurface("note", "amber")}
        selected
      />,
    );
    expect(html).not.toContain("data-annotation-swatch");
  });
});

const AGENT_CARD: CellCardModel = {
  id: "scout",
  title: "Scout",
  subtitle: "Research agent",
  kind: "agent",
  col: 8,
  row: 0,
  widthCells: 12,
  heightCells: 8,
  ports: [
    {
      id: "brief",
      name: "brief",
      direction: "input",
      rowOffset: 2,
      artifactTypeId: "text.plain",
      shape: "one",
    },
    {
      id: "findings",
      name: "findings",
      direction: "output",
      rowOffset: 2,
      artifactTypeId: "text.markdown",
      shape: "many",
    },
  ],
};

function agentSurface(
  agentStatus: AgentCardSurfaceData["agentStatus"],
): AgentCardSurfaceData {
  return {
    kind: "agent",
    modelLabel: "claude-opus-5-5",
    agentStatus,
    linkedToolCount: 3,
    recentToolRows: [
      {
        id: "t1",
        toolName: "web.search",
        status: "done",
        summary: "8 results",
      },
      {
        id: "t2",
        toolName: "table.read",
        status: "running",
        summary: "parcels.csv",
      },
    ],
    lastMessageSnippet: "Two sources disagree on the parcel count.",
  };
}

describe("CellAgentCard", () => {
  const STATUS_TEXT = {
    idle: "Idle",
    thinking: "Thinking",
    streaming: "Streaming",
    error: "Error",
  } as const;

  for (const status of Object.keys(STATUS_TEXT) as Array<
    keyof typeof STATUS_TEXT
  >) {
    it(`renders the ${status} agent inside its exact cells`, () => {
      const html = renderToStaticMarkup(
        <CellAgentCard
          card={AGENT_CARD}
          surface={agentSurface(status)}
          selected
          connectedPortIds={new Set(["brief"])}
        />,
      );
      const rest = renderToStaticMarkup(
        <CellAgentCard
          card={AGENT_CARD}
          surface={agentSurface(status)}
          selected={false}
          connectedPortIds={new Set(["brief"])}
        />,
      );
      // Model and status ride in the header: only while selected.
      expect(rest).not.toContain(`data-agent-status-indicator="${status}"`);
      expect(rest).not.toContain("data-card-header-actions");
      expectExactBox(html, 12, 8);
      expect(html).toContain('data-card-kind="agent"');
      expect(html).toContain(`data-agent-status="${status}"`);
      expect(html).toContain(`data-agent-status-indicator="${status}"`);
      expect(html).toContain(STATUS_TEXT[status]);
      expect(html).toContain("claude-opus-5-5");
      expect(html).toContain('data-agent-tool-count="true"');
      expect(html).toContain("3 tools");
      expect(html).toContain('data-agent-tool-row="t1"');
      expect(html).toContain('data-agent-tool-row="t2"');
      expect(html).toContain('data-tool-status="running"');
      expect(html).toContain("web.search");
      expect(html).toContain('data-agent-message-snippet="true"');
      expect(html).toContain("Two sources disagree");
      for (const port of AGENT_CARD.ports) expectPortPinned(html, port, 12);
      expect(stemTag(html, "brief")).toContain("width:5.5px");
      expect(stemTag(html, "findings")).toContain("width:11.5px");
    });
  }
});

// --- Glass overlays and viewport layers ------------------------------------

function dockedJoin(overrides: Partial<CellDockedJoin> = {}): CellDockedJoin {
  return {
    pipeId: "p1",
    sourceCardId: "a",
    sourcePortId: "out",
    targetCardId: "b",
    targetPortId: "in",
    seamCol: 6,
    row: 2,
    seamPoint: { x: 300, y: 125 },
    color: "var(--artifact-table)",
    sequence: false,
    enabled: true,
    ...overrides,
  };
}

describe("CellDockedBridgeLayer", () => {
  it("bridges a single seam with one strand inside a 30px hit target", () => {
    const html = renderToStaticMarkup(
      <CellDockedBridgeLayer joins={[dockedJoin()]} />,
    );
    const button = tagWith(html, "data-docked-join", "p1");
    expect(button).toContain('type="button"');
    expect(button).toContain('data-docked-sequence="false"');
    expect(button).toContain('data-docked-enabled="true"');
    expect(button).toContain("left:285px");
    expect(button).toContain("top:110px");
    expect(button).toContain("width:30px");
    expect(button).toContain("height:30px");
    expect(html).toContain('viewBox="-15 -15 30 30"');
    expect(html).toContain('data-docked-strands="1"');
    expect(html).toContain('stroke-width="3"');
    expect(count(html, /<line /)).toBe(1);
    expect(html).toContain('x1="-6" y1="0" x2="6" y2="0"');
    expect(html).not.toContain("stroke-dasharray");
    expect(html).not.toContain("data-docked-coupler");
  });

  it("bridges a list seam with two strands", () => {
    const html = renderToStaticMarkup(
      <CellDockedBridgeLayer
        joins={[dockedJoin({ pipeId: "p2", sequence: true })]}
      />,
    );
    expect(tagWith(html, "data-docked-join", "p2")).toContain(
      'data-docked-sequence="true"',
    );
    expect(html).toContain('data-docked-strands="2"');
    expect(html).toContain('stroke-width="2.1"');
    expect(count(html, /<line /)).toBe(2);
    expect(html).toContain('y1="-2.65"');
    expect(html).toContain('y1="2.65"');
  });

  it("dashes a disabled bridge and rings a selected or hovered one", () => {
    const html = renderToStaticMarkup(
      <CellDockedBridgeLayer
        joins={[
          dockedJoin({ pipeId: "off", enabled: false }),
          dockedJoin({ pipeId: "picked", seamPoint: { x: 300, y: 225 } }),
          dockedJoin({ pipeId: "over", seamPoint: { x: 300, y: 325 } }),
        ]}
        selectedPipeIds={new Set(["picked"])}
        hoveredPipeId="over"
      />,
    );
    expect(tagWith(html, "data-docked-join", "off")).toContain(
      'data-docked-enabled="false"',
    );
    expect(html).toContain('stroke-dasharray="2.5 2"');
    expect(html).toContain("joinDisabled");
    expect(tagWith(html, "data-docked-join", "picked")).toContain(
      'aria-pressed="true"',
    );
    expect(tagWith(html, "data-docked-join", "over")).toContain(
      'data-docked-active="true"',
    );
    expect(tagWith(html, "data-docked-join", "off")).toContain(
      'data-docked-active="false"',
    );
    expect(count(html, /data-docked-coupler="true"/)).toBe(2);
  });

  it("draws nothing for no joins", () => {
    expect(renderToStaticMarkup(<CellDockedBridgeLayer joins={[]} />)).toBe("");
  });
});

const ATTACHMENT: CellPipeAttachment = {
  pipeId: "p9",
  anchor: { x: 400, y: 175 },
  segmentOrientation: "horizontal",
  widthCells: 6,
  heightCells: 1,
  label: "rows",
  conversionLabel: "csv → table",
  color: "var(--artifact-table)",
  enabled: true,
  isDocked: false,
};

describe("CellEdgeSelectorPill", () => {
  it("centres a 6×1-cell grab box with the label, conversion chip and remove", () => {
    const html = renderToStaticMarkup(
      <CellEdgeSelectorPill
        attachment={ATTACHMENT}
        selected
        onRemove={() => {}}
      />,
    );
    const box = tagWith(html, "data-edge-selector-pill", "p9");
    expect(box).toContain('data-edge-selector-orientation="horizontal"');
    expect(box).toContain('data-selected="true"');
    expect(box).toContain("left:325px");
    expect(box).toContain("top:162.5px");
    expect(box).toContain("width:150px");
    expect(box).toContain("height:25px");
    expect(box).toContain('data-hovered="false"');
    expect(html).toMatch(
      /data-edge-selector-color="true"[^>]*background-color:var\(--artifact-table\)/,
    );
    expect(html).toMatch(/data-edge-selector-label="true"[^>]*>rows</);
    expect(html).toMatch(
      /data-edge-selector-conversion="true"[^>]*>csv → table</,
    );
    expect(html).toContain('aria-label="Remove rows"');
  });

  it("falls back to a 6×1 box and leaves out absent parts", () => {
    const html = renderToStaticMarkup(
      <CellEdgeSelectorPill
        attachment={{
          ...ATTACHMENT,
          widthCells: 0,
          heightCells: 0,
          conversionLabel: null,
          segmentOrientation: "vertical",
        }}
      />,
    );
    const box = tagWith(html, "data-edge-selector-pill", "p9");
    expect(box).toContain('data-selected="false"');
    expect(box).toContain('data-edge-selector-orientation="vertical"');
    expect(box).toContain("width:150px");
    expect(box).toContain("height:25px");
    expect(html).not.toContain("data-edge-selector-conversion");
    expect(html).not.toContain("Remove rows");
  });

  it("renders a caller's action in its children slot", () => {
    const html = renderToStaticMarkup(
      <CellEdgeSelectorPill attachment={ATTACHMENT}>
        <button type="button" data-test-menu="true">
          menu
        </button>
      </CellEdgeSelectorPill>,
    );
    expect(html).toContain('data-test-menu="true"');
  });

  it("omits the duplicate conversion chip when the pill label already names the conversion", () => {
    const html = renderToStaticMarkup(
      <CellEdgeSelectorPill
        attachment={{
          ...ATTACHMENT,
          label: "csv → table",
          conversionLabel: "csv → table",
        }}
      />,
    );
    expect(html).toContain("csv → table");
    expect(html).not.toContain("data-edge-selector-conversion");
  });
});

describe("CellMarqueeOverlay", () => {
  it("draws nothing without a marquee", () => {
    expect(renderToStaticMarkup(<CellMarqueeOverlay marquee={null} />)).toBe(
      "",
    );
  });

  it("normalizes a drag in any direction into one box", () => {
    const html = renderToStaticMarkup(
      <CellMarqueeOverlay
        marquee={{ start: { x: 320, y: 90 }, current: { x: 120, y: 240 } }}
      />,
    );
    const box = tagWith(html, "data-cell-marquee", "true");
    expect(box).toContain("left:120px");
    expect(box).toContain("top:90px");
    expect(box).toContain("width:200px");
    expect(box).toContain("height:150px");
    expect(box).toContain("marquee");
  });
});

const PEER: CellRemotePeerState = {
  actorId: "ada",
  displayName: "Ada",
  color: "var(--peer-ada)",
  cursor: { x: 410, y: 220 },
  activity: "moving_nodes",
  selectedCardIds: ["merge"],
  draggingCards: { merge: { col: 14, row: 8 }, ghost: { col: 2, row: 18 } },
};

describe("CellRemotePresenceLayer", () => {
  it("draws a peer's cursor and a ghost frame where each dragged card lands", () => {
    const html = renderToStaticMarkup(
      <CellRemotePresenceLayer
        peers={[PEER]}
        cards={[{ ...operatorCard(operatorSurface()), id: "merge" }]}
      />,
    );
    const known = tagWith(html, "data-remote-drag-ghost", "ada:merge");
    expect(known).toContain("transform:translate3d(346px, 196px, 0)");
    expect(known).toContain("width:308px");
    expect(known).toContain("height:458px");
    expect(known).toContain(
      "border-color:color-mix(in srgb, var(--peer-ada) 65%, transparent)",
    );
    expect(known).toContain(
      "background-color:color-mix(in srgb, var(--peer-ada) 6%, transparent)",
    );
    // A card the layer was not told about takes the standard 12 × 6 size.
    const unknown = tagWith(html, "data-remote-drag-ghost", "ada:ghost");
    expect(unknown).toContain("transform:translate3d(46px, 446px, 0)");
    expect(unknown).toContain("width:308px");
    expect(unknown).toContain("height:158px");

    const cursor = tagWith(html, "data-remote-peer-cursor", "ada");
    expect(cursor).toContain("transform:translate3d(410px, 220px, 0)");
    expect(cursor).toContain('data-remote-peer-activity="moving_nodes"');
    expect(html).toMatch(/data-remote-peer-name="true"[^>]*>Ada</);
  });

  it("leaves the cursor out for a peer with no pointer on the canvas", () => {
    const html = renderToStaticMarkup(
      <CellRemotePresenceLayer
        peers={[{ ...PEER, cursor: null, draggingCards: {} }]}
      />,
    );
    expect(html).not.toContain("data-remote-peer-cursor");
    expect(html).not.toContain("data-remote-drag-ghost");
  });
});

describe("CellViewportLayer", () => {
  // Vitest runs a StyleX stub that keeps rule names, not compiled CSS; the
  // `underCards` and `overCards` rules are z-index 3 and 6.
  it("places the under-cards plane between the frosted sheet and the cards", () => {
    const html = renderToStaticMarkup(
      <CellViewportLayer
        layer="under-cards"
        viewport={{ x: 40, y: -20, zoom: 1.5 }}
      />,
    );
    const layer = tagWith(html, "data-cell-viewport-layer", "under-cards");
    expect(layer).toContain("underCards");
    expect(layer).toContain("transform:translate3d(40px, -20px, 0) scale(1.5)");
  });

  it("places the over-cards plane above the cards and wiring", () => {
    const html = renderToStaticMarkup(
      <CellViewportLayer layer="over-cards">
        <CellMarqueeOverlay
          marquee={{ start: { x: 0, y: 0 }, current: { x: 10, y: 10 } }}
        />
      </CellViewportLayer>,
    );
    const layer = tagWith(html, "data-cell-viewport-layer", "over-cards");
    expect(layer).toContain("overCards");
    expect(layer).toContain("transform:translate3d(0px, 0px, 0) scale(1)");
    expect(html).toContain('data-cell-marquee="true"');
  });
});

// --- Punched wells ----------------------------------------------------------

/** Where a punched port's 30px hit target sits: 22px inside its card's edge. */
function expectPortPunched(html: string, port: CellPort, widthCells: number) {
  const centreX = port.direction === "input" ? 22 : widthCells * 25 - 22;
  const centreY = (port.rowOffset + 0.5) * 25;
  const tag = portTag(html, port.id);
  expect(tag).toContain('data-port-well="punched"');
  expect(tag).toContain(`left:${centreX - 15}px`);
  expect(tag).toContain(`top:${centreY - 15}px`);
}

/** The punched socket drawn inside a port's button. */
function socketOf(html: string, portId: string): string {
  const start = html.indexOf(`data-port-id="${portId}"`);
  expect(start, portId).toBeGreaterThanOrEqual(0);
  const end = html.indexOf("</button>", start);
  return html.slice(start, end);
}

describe("punched wells", () => {
  it("pins an artifact card's punched output 22px in from its right and bottom edges", () => {
    const card: CellCardModel = {
      ...ARTIFACT_CARD,
      ports: [
        ARTIFACT_CARD.ports[0]!,
        {
          id: ARTIFACT_CARD_OUTPUT_PORT_ID,
          name: "artifact",
          direction: "output",
          rowOffset: artifactCardOutputRow(ARTIFACT_CARD.heightCells),
          artifactTypeId: "image.raster",
          shape: "one",
        },
      ],
    };
    const punched = renderArtifact(PREVIEWS.image, { card, well: "punched" });
    const hole = portTag(punched, ARTIFACT_CARD_OUTPUT_PORT_ID);
    expect(hole).toContain('data-port-well="punched"');
    // (250 - 22, 200 - 22), less half the 30px hit target.
    expect(hole).toContain("left:213px");
    expect(hole).toContain("top:163px");
    // The input keeps its row midline.
    expectPortPunched(punched, card.ports[0]!, 10);
    // Recessed, the output stays on its row's gutter cell.
    const recessed = renderArtifact(PREVIEWS.image, { card });
    expectPortPinned(recessed, card.ports[1]!, 10);
  });

  it("drills every operator port through the plate, with no stem", () => {
    const { html } = renderOperator(operatorSurface(), { well: "punched" });
    expect(tagWith(html, "data-cell-card", "true")).toContain(
      'data-well="punched"',
    );
    for (const port of OPERATOR_PORTS) expectPortPunched(html, port, 12);
    expect(html).not.toContain("data-port-stem");
    // Synthesized plugs are punched too.
    expect(portTag(html, "images:1")).toContain('data-port-well="punched"');
  });

  it("runs a connected pipe into its hole and leaves an open hole empty", () => {
    const { html } = renderOperator(operatorSurface(), { well: "punched" });
    const connected = socketOf(html, "result");
    expect(connected).toContain('data-punched-socket="connected"');
    expect(connected).toContain('data-punched-floor="true"');
    expect(connected).toContain('data-cell-well-stub="list"');
    expect(connected).toContain('data-port-ring="list"');
    // The stage's own recessed well, bored through the plate.
    expect(connected).toContain('data-cell-well="punched"');
    expect(connected).toContain("well-wall-frost");
    // An output's stub runs out to the card's right edge.
    expect(connected).toMatch(/d="M0,0 L7\.8/);
    // ...clipped to the well's lip, so its end never shows on the plate.
    expect(connected).toMatch(
      /<clipPath id="(punch-[^"]+bore)"><circle r="11">/,
    );
    expect(connected).toMatch(
      /data-cell-well-stub="list" clip-path="url\(#punch-[^"]+bore\)"/,
    );
    const open = socketOf(html, "report");
    expect(open).toContain('data-punched-socket="open"');
    expect(open).toContain('data-punched-floor="true"');
    expect(open).not.toContain("data-cell-well-stub");
    expect(open).toContain('data-port-ring="single"');
    // The glow's layer is drawn unlit, so it fades in rather than mounts.
    expect(open).toContain('data-port-glow="off"');
  });

  it("previews the pipe in a hot open hole, running in from the card's left edge", () => {
    const { html } = renderOperator(operatorSurface(), {
      well: "punched",
      activePortKey: "merge:source",
      connectedPortIds: new Set(),
    });
    const hot = socketOf(html, "source");
    expect(hot).toContain('data-punched-socket="open"');
    expect(hot).toContain('data-cell-well-stub="list"');
    expect(hot).toMatch(/d="M0,0 L-7\.8/);
    expect(hot).toContain('opacity="0.6"');
    expect(hot).toContain('data-port-glow="on"');
    // No tinted disc behind the hole: the hole glows instead.
    expect(portTag(html, "source")).not.toMatch(/class="[^"]*portHot/);
  });

  it("moves port labels, plug rows and the add button in past the holes", () => {
    expect(PUNCHED_LABEL_INSET).toBe(34);
    const { html } = renderOperator(operatorSurface(), { well: "punched" });
    expect(tagWith(html, "data-port-row", "2")).toContain(
      "padding-inline:34px",
    );
    expect(tagWith(html, "data-instance-plug-row", "images:0")).toContain(
      "padding-left:34px",
    );
    expect(tagWith(html, "data-instance-plug-row", "images:1")).toContain(
      "padding-left:34px",
    );
    expect(tagWith(html, "data-instance-plug-add", "images")).toContain(
      "padding-left:34px",
    );
    // A long label truncates; its tab names it in full.
    expect(tagWith(html, "data-port-tab", "report")).toContain(
      'title="report"',
    );
  });

  it("draws a liquid card's punched well with the liquid glass paints", () => {
    const { html } = renderOperator(operatorSurface(), {
      well: "punched",
      material: "liquid",
    });
    const connected = socketOf(html, "result");
    expect(connected).toContain("well-wall-liquid");
    expect(connected).toContain("well-meniscus");
    expect(connected).toContain("well-specular");
    // Each socket's paints have ids of their own.
    const ids = [...html.matchAll(/id="(punch-[^"]+-well-edge)"/g)].map(
      (match) => match[1],
    );
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.length).toBeGreaterThan(1);
  });

  it("paints the plate at the look's card fill, or solid without one", () => {
    const liquid = renderOperator(operatorSurface(), {
      material: "liquid",
      cardFill: 0.4,
    }).html;
    expect(liquid).toMatch(
      /<article[^>]*background-color:color-mix\(in srgb, [^;]* 40%, transparent\)/,
    );
    const frost = renderOperator(operatorSurface(), { cardFill: 1 }).html;
    expect(frost).toMatch(/<article[^>]*100%, transparent\)/);
    const solid = renderOperator(operatorSurface()).html;
    expect(solid).not.toMatch(/<article[^>]*background-color/);
  });

  it("leaves the recessed card exactly as it was", () => {
    const { html } = renderOperator(operatorSurface());
    expect(tagWith(html, "data-cell-card", "true")).toContain(
      'data-well="recessed"',
    );
    for (const port of OPERATOR_PORTS) expectPortPinned(html, port, 12);
    expect(html).not.toContain("data-punched-socket");
    expect(html).not.toContain("data-port-well");
    expect(html).not.toContain("padding-inline:34px");
    expect(stemTag(html, "source")).toContain("width:11.5px");
  });

  it("cuts an artifact card's holes clean through its preview, with no collar", () => {
    const html = renderArtifact(PREVIEWS.image, { well: "punched" });
    for (const port of ARTIFACT_CARD.ports) expectPortPunched(html, port, 10);
    expect(html).not.toContain("data-port-stem");
    expect(html).not.toContain("data-punched-collar");
    for (const id of ["in", "out"]) {
      const socket = socketOf(html, id);
      expect(socket).toContain('data-punched-bore="through"');
      // No floor under the hole, only a thin open wall: the canvas shows.
      expect(socket).toContain('data-cell-well-wall="open"');
      expect(socket).not.toContain("data-cell-well-floor");
    }
    expect(socketOf(html, "out")).toContain('data-punched-socket="connected"');
    expect(socketOf(html, "in")).toContain('data-punched-socket="open"');

    // The plate keeps its border and shadow but paints no fill of its own...
    expect(/<article[^>]*>/.exec(html)?.[0]).toContain(
      "background-color:transparent",
    );
    // ...its fill and the preview sit on a layer the holes are cut out of, in
    // its own box: 5px (4 inset + 1 border) in, 27px (26 + 1) down.
    const interior = tagWith(html, "data-plate-interior", "punched");
    expect(interior).toContain(
      "mask-image:radial-gradient(circle at 17px 35.5px, transparent 10.75px, black 11.25px), radial-gradient(circle at 223px 85.5px, transparent 10.75px, black 11.25px)",
    );
    expect(interior).toContain("mask-composite:intersect");
    expect(html.indexOf("data-plate-interior")).toBeLessThan(
      html.indexOf('data-artifact-preview="image"'),
    );
  });

  it("cuts the corner hole through a punched sequence's backs at the pin", () => {
    const card: CellCardModel = {
      ...ARTIFACT_CARD,
      ports: [
        {
          id: ARTIFACT_CARD_OUTPUT_PORT_ID,
          name: "artifact",
          direction: "output",
          rowOffset: artifactCardOutputRow(ARTIFACT_CARD.heightCells),
          artifactTypeId: "image.raster",
          shape: "many",
        },
      ],
    };
    const surface = { ...PREVIEWS.image, itemCount: 3, stackImageUrls: [] };
    const html = renderArtifact(surface, { card, well: "punched" });
    // The hole is (228, 178) in the card, (224, 152) in a back's own box.
    expect(tagWith(html, "data-artifact-stack-back", "1")).toContain(
      "mask-image:radial-gradient(circle at 224px 152px, transparent 10.75px, black 11.25px)",
    );
    // In the gutter the backs are whole.
    expect(
      tagWith(
        renderArtifact(surface, { card }),
        "data-artifact-stack-back",
        "1",
      ),
    ).not.toContain("mask-image");
  });

  it("runs a collection's member and spare rows between the holes", () => {
    const html = renderToStaticMarkup(
      <CellCollectionCard
        card={COLLECTION_CARD}
        surface={COLLECTION_SURFACE}
        selected={false}
        dragging={false}
        well="punched"
        onRemoveMember={() => {}}
      />,
    );
    for (const port of COLLECTION_CARD.ports) expectPortPunched(html, port, 10);
    for (const member of COLLECTION_SURFACE.members) {
      expect(tagWith(html, "data-collection-member", member.id)).toContain(
        "padding-inline:34px",
      );
    }
    expect(tagWith(html, "data-collection-spare-plug", "true")).toContain(
      "padding-inline:34px",
    );
    // Only an artifact's preview is cut through; a collection's holes keep
    // their floor in the plate.
    expect(html).not.toContain("data-plate-interior");
    expect(html).toContain('data-punched-bore="floored"');
    expect(html).toContain('data-cell-well-floor="true"');
    expect(html).not.toContain('data-punched-bore="through"');
  });

  it("punches the demo card's ports and insets its labels", () => {
    const card = operatorCard(operatorSurface());
    const html = renderToStaticMarkup(
      <CellCard
        card={card}
        material="frost"
        well="punched"
        selected={false}
        dragging={false}
        connectedPortIds={new Set(["result"])}
        onCardPointerDown={() => {}}
        onPortPointerDown={() => {}}
      />,
    );
    for (const port of OPERATOR_PORTS) expectPortPunched(html, port, 12);
    expect(html).not.toContain("data-port-stem");
    expect(tagWith(html, "data-port-row", "2")).toContain(
      "padding-inline:34px",
    );
    expect(socketOf(html, "result")).toContain(
      'data-punched-socket="connected"',
    );
  });

  it("bridges a docked seam from one hole's mouth to the other's", () => {
    const html = renderToStaticMarkup(
      <CellDockedBridgeLayer joins={[dockedJoin()]} punched />,
    );
    expect(html).toContain('x1="-13" y1="0" x2="13" y2="0"');
    expect(tagWith(html, "data-docked-join", "p1")).toContain("width:30px");
  });
});

// --- Static source guardrails ----------------------------------------------

const CELL_CANVAS_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

const LANE_SOURCES = [
  "cell-card-geometry.ts",
  "CellCanvasContext.tsx",
  "cards/CellOperatorCard.tsx",
  "cards/CellArtifactCard.tsx",
  "cards/CellAnnotationAndAgentCards.tsx",
  "cards/CellArtifactSequenceSpread.tsx",
  "cell-artifact-stacking.ts",
  "CellGlassOverlays.tsx",
  "CellCard.tsx",
  "punched-port.tsx",
] as const;
const LANE_TESTS = [
  "cell-card-geometry.test.ts",
  "cards/CellRealCards.test.tsx",
  "cards/CellArtifactSequenceSpread.test.tsx",
  "cell-artifact-stacking.test.ts",
] as const;

// Built from parts so this file does not contain the strings it bans.
const XYFLOW_IMPORT = ["@xyflow", "react"].join("/");
const PHONE_TOUCH = ["phone", "Touch"].join("");

function readLaneFile(relative: string): string {
  return readFileSync(path.join(CELL_CANVAS_DIR, relative), "utf8");
}

describe("lane 2 source guardrails", () => {
  for (const file of [...LANE_SOURCES, ...LANE_TESTS]) {
    it(`${file} stays off React Flow, backdrop blur and phone targets`, () => {
      const source = readLaneFile(file);
      expect(source).not.toContain(XYFLOW_IMPORT);
      expect(source).not.toMatch(/backdrop-?filter/i);
      expect(source).not.toContain(PHONE_TOUCH);
      expect(source).not.toMatch(/["']:hover["']\s*:/);
      expect(source).not.toMatch(/from\s+["'][^"']*sandbox\//);
    });
  }

  for (const file of LANE_SOURCES) {
    it(`${file} paints with tokens, not raw hex colours`, () => {
      expect(readLaneFile(file)).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    });
  }
});

// --- Ports that share an id across directions -------------------------------

describe("an operator whose input and output are both named image", () => {
  const IMAGE_PORTS: readonly CellPort[] = [
    {
      id: "image",
      name: "image",
      direction: "input",
      rowOffset: 2,
      artifactTypeId: "image.raster",
      shape: "one",
    },
    {
      id: "image",
      name: "image",
      direction: "output",
      rowOffset: 2,
      artifactTypeId: "image.raster",
      shape: "one",
    },
  ];
  const surface = operatorSurface({
    instancePlugGroups: [],
    configFields: [],
    appendix: null,
  });
  const card = { ...operatorCard(surface), ports: IMAGE_PORTS };

  function render(extra: Partial<ComponentProps<typeof CellOperatorCard>>) {
    return renderToStaticMarkup(
      <CellOperatorCard
        card={card}
        surface={surface}
        selected={false}
        dragging={false}
        {...extra}
      />,
    );
  }
  const imagePort = (html: string, direction: "input" | "output") =>
    tagWith(html, "data-port-direction", direction);

  it("draws both ports, one on each side", () => {
    const html = render({});
    expect(count(html, /data-port-id="image"/)).toBe(2);
    expect(imagePort(html, "input")).toContain('data-port-id="image"');
    expect(imagePort(html, "output")).toContain('data-port-id="image"');
  });

  it("marks each side connected on its own", () => {
    const html = render({ connectedPortIds: new Set(["output:image"]) });
    expect(imagePort(html, "output")).toContain('data-port-connected="true"');
    expect(imagePort(html, "input")).toContain('data-port-connected="false"');
    // A bare id still reads as connected, for callers with one port per name.
    const bare = render({ connectedPortIds: new Set(["image"]) });
    expect(imagePort(bare, "input")).toContain('data-port-connected="true"');
  });

  it("lights only the side a connection drag is over", () => {
    const html = render({ activePortKey: "merge:input:image" });
    expect(imagePort(html, "input")).toContain('data-port-hot="true"');
    expect(imagePort(html, "output")).toContain('data-port-hot="false"');
  });

  it("keys the generic card's ports apart too", () => {
    const html = renderToStaticMarkup(
      <CellCard
        card={card}
        material="frost"
        selected={false}
        dragging={false}
        connectedPortIds={new Set(["input:image"])}
        activePortKey="merge:output:image"
        onCardPointerDown={() => {}}
        onPortPointerDown={() => {}}
      />,
    );
    expect(imagePort(html, "input")).toContain('data-port-connected="true"');
    expect(imagePort(html, "output")).toContain('data-port-connected="false"');
    expect(imagePort(html, "output")).toContain('data-port-hot="true"');
    expect(imagePort(html, "input")).toContain('data-port-hot="false"');
  });
});

// --- Stack style -----------------------------------------------------------

describe("CellArtifactCard stack style", () => {
  const stacked = { ...PREVIEWS.image, itemCount: 3, stackImageUrls: [] };

  it("fans by default and lays a deck straight when asked", () => {
    const fan = renderArtifact(stacked);
    expect(tagWith(fan, "data-cell-card", "true")).toContain(
      'data-stack-style="fan"',
    );
    expect(tagWith(fan, "data-artifact-stack-back", "1")).toContain(
      "transform:rotate(",
    );

    const deck = renderArtifact(stacked, { stackStyle: "deck" });
    const first = tagWith(deck, "data-artifact-stack-back", "1");
    const second = tagWith(deck, "data-artifact-stack-back", "2");
    expect(first).toContain("transform:translate3d(0px, 6px, 0) scale(0.96)");
    expect(second).toContain("transform:translate3d(0px, 12px, 0) scale(0.92)");
    for (const back of [first, second]) {
      expect(back).toContain("transform-origin:center bottom");
      expect(back).not.toContain("rotate(");
    }
  });

  it("cuts the corner hole through a deck's backs where the plate's hole lands", () => {
    const html = renderArtifact(stacked, {
      stackStyle: "deck",
      well: "punched",
    });
    const first = tagWith(html, "data-artifact-stack-back", "1");
    // Plate 242×170 at (4, 26); the hole at (228, 178) in the card box. The
    // back scales 0.96 about (125, 196) and drops 6: in its own box the hole
    // is at 125 + 103/0.96 - 4 and 196 + (178 - 6 - 196)/0.96 - 26.
    expect(first).toContain("mask-image:radial-gradient(circle at 228.29");
    expect(first).toContain("px 145px");
    expect(first).toContain("mask-composite:intersect");
  });

  it("does not swing in the backs a stack mounts with", () => {
    const html = renderArtifact(stacked);
    expect(tagWith(html, "data-artifact-stack-back", "1")).toContain(
      'data-stack-back-state="rest"',
    );
  });

  it("lifts its plate as a merge target and readies the dragged card to tuck", () => {
    const fanHover = renderArtifact(PREVIEWS.image, { mergeHover: true });
    expect(tagWith(fanHover, "data-cell-card", "true")).toContain(
      'data-merge-hover="true"',
    );
    expect(fanHover).toContain("transform:rotate(1.4deg) translateY(-2px)");
    const deckHover = renderArtifact(PREVIEWS.image, {
      mergeHover: true,
      stackStyle: "deck",
    });
    expect(deckHover).toContain("transform:translateY(-5px) scale(1.01)");
    const merging = renderArtifact(PREVIEWS.image, { merging: true });
    expect(merging).toContain("transform:rotate(-1.6deg) scale(0.95)");
    const deckMerging = renderArtifact(PREVIEWS.image, {
      merging: true,
      stackStyle: "deck",
    });
    expect(deckMerging).toContain("transform:scale(0.95)");
    // At rest the plate carries no transform.
    expect(renderArtifact(PREVIEWS.image)).not.toMatch(
      /<article[^>]*transform:/,
    );
  });
});

// --- Schema-driven config fields ---------------------------------------------

function renderRichOperator(
  config: Record<string, unknown>,
  options: Parameters<typeof buildOperatorCardsAndSurfaces>[2] = {},
  spec = vectorLayerSpec,
) {
  const id = "node";
  const { cards, surfaces } = buildOperatorCardsAndSurfaces(
    fixtureDocument([fixtureNode(id, spec, config)]),
    richRegistry,
    options,
  );
  const card = cards[0]!;
  const surface = surfaces.get(id);
  if (surface?.kind !== "operator") throw new Error("operator surface");
  const html = renderToStaticMarkup(
    <CellOperatorCard
      card={card}
      surface={surface}
      selected
      dragging={false}
      onConfigChange={() => {}}
      onToggleConfigSection={() => {}}
    />,
  );
  return { html, card, surface };
}

describe("CellOperatorCard schema config fields", () => {
  it("draws a slider with a tabular readout, a colour well with its hex, a segmented choice and a switch", () => {
    const { html } = renderRichOperator({ title: "Roads", opacity: 0.4 });
    // Opacity: the kit's range input and its printed value.
    expect(html).toMatch(/type="range"[^>]*value="0.4"/);
    expect(html).toContain(">0.40</output>");
    // Visible: a dense switch, named by its label.
    expect(html).toMatch(
      /role="switch"[^>]*aria-checked="true"[^>]*aria-labelledby/,
    );
    // Blend: segments with the schema's labels.
    expect(html).toContain('role="radiogroup" aria-label="Blend"');
    expect(html).toContain(">Multiply<");
    // Style › Fill: the swatch and the exact hex beside it.
    expect(html).toContain('type="color" aria-label="Fill"');
    expect(html).toMatch(/aria-label="Fill hex"[^>]*value="#3366ff"/);
  });

  it("draws the `Style` union with its branch picker and only the active branch's fields", () => {
    const simple = renderRichOperator({ title: "Roads" }).html;
    expect(simple).toContain(
      'data-config-union="style" data-config-branch="simple"',
    );
    expect(simple).toContain('aria-label="Style mode"');
    expect(simple).toContain('data-config-field="style.fill"');
    expect(simple).not.toContain('data-config-list="style.categories"');

    const categorized = renderRichOperator({
      title: "Roads",
      style: {
        kind: "categorized_points",
        categories: [{ id: "c1", title: "Roads", color: "#ff0000" }],
      },
    }).html;
    expect(categorized).toContain('data-config-branch="categorized_points"');
    expect(categorized).not.toContain('data-config-field="style.fill"');
    expect(categorized).toContain('data-config-list="style.categories"');
    expect(categorized).toContain('aria-label="Category 1 title"');
    expect(categorized).toContain(">Add category<");
    expect(categorized).toContain('aria-label="Remove category 1"');
  });

  it("places nested rows inside the rows the band was sized for", () => {
    const { html, surface } = renderRichOperator({ title: "Roads" });
    const style = surface.configFields?.find(({ id }) => id === "style");
    expect(style?.denseRows).toBe(3);
    // The union's frame is its header row plus a 2-row shelf of children.
    expect(html).toMatch(
      /data-config-field="style"[^>]*grid-row:[0-9]+ \/ span 3/,
    );
    expect(html).toMatch(
      /data-config-field="style.fill"[^>]*grid-row:1 \/ span 2;grid-column:1 \/ span 1/,
    );
    expect(html).toMatch(
      /data-config-field="style.stroke_width"[^>]*grid-row:1 \/ span 2;grid-column:2 \/ span 1/,
    );
    // Ten rows of band: nothing in it is clipped by the plate.
    expect(html).toMatch(/data-config-band="true"[^>]*height:250px/);
  });

  it("folds untouched advanced fields behind a toggle, and opens them in place", () => {
    const folded = renderRichOperator({ title: "Roads" });
    expect(folded.html).toMatch(
      /aria-expanded="false" data-config-section="advanced"[^>]*>[\s\S]*Advanced[\s\S]*2 hidden/,
    );
    expect(folded.html).not.toContain('data-config-field="min_zoom"');

    const opened = renderRichOperator(
      { title: "Roads" },
      { configSections: { node: { advanced: true } } },
    );
    expect(opened.html).toMatch(
      /aria-expanded="true" data-config-section="advanced"/,
    );
    expect(opened.html).toContain("Hide advanced");
    expect(opened.html).toContain('data-config-field="min_zoom"');
    expect(opened.html).toContain('data-config-field="max_zoom"');
    expect(opened.card.heightCells).toBe(folded.card.heightCells + 2);
  });

  it("puts the API key behind a header key button instead of in the band", () => {
    const { html } = renderRichOperator(
      { base_url: "https://api.example.test" },
      {},
      askModelSpec,
    );
    expect(html).toContain('data-card-credentials="true"');
    expect(html).toContain(
      'aria-label="Credentials for Ask a model: needs attention"',
    );
    expect(html).toContain('aria-haspopup="dialog"');
    expect(html).not.toContain('type="password"');
    expect(html).not.toContain('data-config-field="api_key"');
  });

  it("shows no key button on a card without secret inputs", () => {
    const { html } = renderRichOperator({ title: "Roads" });
    expect(html).not.toContain("data-card-credentials");
  });
});

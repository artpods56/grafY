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
import type { CellCardModel, CellPort } from "../cell-model";
import {
  CellAgentCard,
  CellAnnotationCard,
} from "./CellAnnotationAndAgentCards";
import { CellArtifactCard, CellCollectionCard } from "./CellArtifactCard";
import { CellOperatorCard } from "./CellOperatorCard";

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
    expect(html).toMatch(/data-config-field="prefix"[^>]*grid-column:span 1/);
    expect(html).toMatch(/data-config-field="mode"[^>]*grid-column:1 \/ -1/);
    expect(html).toMatch(/data-config-field="notes"[^>]*grid-row:span 3/);
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
      expect(html).toContain(PREVIEWS[kind].typeLabel);
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
    expect(known).toContain("left:350px");
    expect(known).toContain("top:200px");
    expect(known).toContain("width:300px");
    expect(known).toContain("height:450px");
    expect(known).toContain("border-color:var(--peer-ada)");
    expect(known).toContain(
      "background-color:color-mix(in srgb, var(--peer-ada) 10%, transparent)",
    );
    // A card the layer was not told about takes the standard 12 × 6 size.
    const unknown = tagWith(html, "data-remote-drag-ghost", "ada:ghost");
    expect(unknown).toContain("left:50px");
    expect(unknown).toContain("top:450px");
    expect(unknown).toContain("width:300px");
    expect(unknown).toContain("height:150px");

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
  "CellGlassOverlays.tsx",
] as const;
const LANE_TESTS = [
  "cell-card-geometry.test.ts",
  "cards/CellRealCards.test.tsx",
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

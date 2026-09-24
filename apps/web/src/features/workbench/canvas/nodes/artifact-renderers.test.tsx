// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const maplibreMock = vi.hoisted(() => {
  const instances: Array<Record<string, unknown>> = [];
  const addProtocol = vi.fn();

  class MapMock {
    options: Record<string, unknown>;
    addControl = vi.fn();
    canvas = document.createElement("canvas");
    canvasContainer = document.createElement("div");
    eventListeners: Record<
      string,
      Array<(event: Record<string, unknown>) => void>
    > = {};
    fitBounds = vi.fn();
    getCanvas = vi.fn(() => this.canvas);
    getCanvasContainer = vi.fn(() => this.canvasContainer);
    getLayer: ReturnType<typeof vi.fn>;
    getSource = vi.fn(() => ({}));
    isStyleLoaded = vi.fn(() => true);
    moveLayer = vi.fn();
    queryRenderedFeatures = vi.fn((): Array<Record<string, unknown>> => []);
    querySourceFeatures = vi.fn((): Array<Record<string, unknown>> => []);
    remove = vi.fn();
    resize = vi.fn();
    setLayerZoomRange = vi.fn();
    setLayoutProperty = vi.fn();
    setPaintProperty = vi.fn();
    setFilter = vi.fn();
    unproject = vi.fn(() => ({ lng: 19.93821, lat: 50.06143 }));

    constructor(options: Record<string, unknown>) {
      this.options = options;
      const style = options.style as { layers?: Array<{ id: string }> };
      const layerIds = new Set((style.layers ?? []).map((layer) => layer.id));
      this.getLayer = vi.fn((id: string) =>
        layerIds.has(id) ? { id } : undefined,
      );
      instances.push(this as unknown as Record<string, unknown>);
    }

    emit(event: string, payload: Record<string, unknown>) {
      for (const callback of this.eventListeners[event] ?? []) {
        callback(payload);
      }
    }

    on(event: string, callback: (event: Record<string, unknown>) => void) {
      this.eventListeners[event] ??= [];
      this.eventListeners[event].push(callback);
      if (event === "load") callback({});
      return this;
    }
  }

  return { addProtocol, instances, MapMock };
});

vi.mock("maplibre-gl", () => ({
  default: {
    addProtocol: maplibreMock.addProtocol,
    Map: maplibreMock.MapMock,
    NavigationControl: class NavigationControl {},
    workerUrl: "",
  },
}));

vi.mock("pmtiles", () => ({
  Protocol: class Protocol {
    tile = vi.fn();
  },
}));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("@/features/workspaces/WorkspaceLayout", () => ({
  useWorkspaceContext: () => ({
    workspace: {
      id: "workspace-1",
      slug: "team",
      name: "Local",
      kind: "personal",
      role: "owner",
      capabilities: [],
    },
    workspaces: [],
    refreshWorkspaces: async () => undefined,
  }),
}));

import type {
  ArtifactSummary,
  GeoRenderDescriptor,
  TablePage,
} from "@/lib/api";
import {
  formatJsonSchemaPayload,
  markdownPayload,
  rendererCanBrush,
  rendererFor,
} from "./artifact-renderers";
import type { ArtifactViewerInteractionContext } from "../artifact-interactions";

const JSON_SCHEMA_ARTIFACT: ArtifactSummary = {
  artifact_id: "schema-artifact",
  artifact_type: "json.schema",
  schema_version: 1,
  content_type: "application/json",
};

const MARKDOWN_ARTIFACT: ArtifactSummary = {
  artifact_id: "markdown-artifact",
  artifact_type: "text.markdown",
  schema_version: 1,
  content_type: "application/json",
};

const MAP_ARTIFACT: ArtifactSummary = {
  artifact_id: "map-artifact",
  artifact_type: "geo.map_document",
  schema_version: 1,
  content_type: "application/json",
  content_url: "./artifacts/map-artifact/content",
};

const GEO_RENDER_DESCRIPTOR: GeoRenderDescriptor = {
  artifact_id: "map-artifact",
  kind: "map_document",
  basemap: "openstreetmap",
  initial_bounds: [-12, 35, 22, 61],
  layers: [
    {
      id: "parcels",
      title: "Parcels",
      visible: true,
      opacity: 1,
      min_zoom: 2,
      max_zoom: 18,
      source: {
        kind: "vector",
        artifact_id: "features-artifact",
        archive_url: "/v1/artifacts/features-artifact/geo/vector.pmtiles",
        source_layer: "features",
        bounds: [100, 10, 110, 20],
        min_zoom: 0,
        max_zoom: 14,
        fields: [
          { id: "name", title: "Name", value_type: "text" },
          { id: "sheet", title: "Sheet", value_type: "text" },
        ],
      },
      style: {
        kind: "vector",
        fill: { enabled: true, color: "#2563eb", opacity: 0.4 },
        line: {
          enabled: true,
          color: "#1d4ed8",
          opacity: 1,
          width: 2,
        },
        outline: {
          enabled: true,
          color: "#172554",
          opacity: 0.8,
          width: 1,
        },
        point: {
          enabled: true,
          color: "#dc2626",
          opacity: 1,
          radius: 5,
          stroke_color: "#ffffff",
          stroke_width: 1,
        },
        label: {
          property: "name",
          color: "#111827",
          size: 12,
          halo_color: "#ffffff",
          halo_width: 1,
        },
      },
    },
    {
      id: "elevation",
      title: "Elevation",
      visible: true,
      opacity: 0.8,
      min_zoom: 0,
      max_zoom: 16,
      source: {
        kind: "raster",
        artifact_id: "raster-artifact",
        tilejson_url: "/v1/artifacts/raster-artifact/geo/raster/tilejson.json",
        bounds: [-5, 40, 10, 55],
        attribution: "Survey office",
      },
      style: {
        kind: "raster",
        opacity: 0.9,
        brightness_min: 0,
        brightness_max: 1,
        contrast: 0,
        saturation: 0,
        hue: 0,
        resampling: "linear",
      },
    },
  ],
};

const CATEGORIZED_GEO_RENDER_DESCRIPTOR: GeoRenderDescriptor = {
  artifact_id: "categorized-map-artifact",
  kind: "map_document",
  basemap: "openstreetmap",
  initial_bounds: [27, 51, 33, 56],
  layers: [
    {
      id: "chrzanowski-symbols",
      title: "Chrzanowski symbols",
      visible: true,
      opacity: 1,
      min_zoom: 0,
      max_zoom: 22,
      source: {
        kind: "vector",
        artifact_id: "chrzanowski-features",
        archive_url: "/v1/artifacts/chrzanowski-features/geo/vector.pmtiles",
        source_layer: "features",
        bounds: [27, 51, 33, 56],
        min_zoom: 0,
        max_zoom: 14,
      },
      style: {
        kind: "categorized_points",
        category_property: "type",
        categories: [
          {
            id: "cities",
            title: "Cities and towns",
            values: [1, 2, 3],
            point: {
              enabled: true,
              color: "#b91c1c",
              opacity: 1,
              radius: 7,
              stroke_color: "#ffffff",
              stroke_width: 1,
            },
            min_zoom: 6,
            max_zoom: 22,
          },
          {
            id: "villages",
            title: "Villages",
            values: [5, 7, 8, 9, 10],
            point: {
              enabled: true,
              color: "#d6a700",
              opacity: 0.85,
              radius: 4,
              stroke_color: "#ffffff",
              stroke_width: 1,
            },
            min_zoom: 10,
            max_zoom: 22,
          },
        ],
        label: {
          property: "transcription",
          color: "#111827",
          size: 12,
          halo_color: "#ffffff",
          halo_width: 1,
        },
      },
    },
  ],
};

const TABLE_ARTIFACT: ArtifactSummary = {
  artifact_id: "table-artifact",
  artifact_type: "table.data",
  schema_version: 1,
  content_type: "application/json",
  content_url: "./artifacts/table-artifact/content",
};

afterEach(() => {
  vi.unstubAllGlobals();
  maplibreMock.instances.length = 0;
});

describe("rendererCanBrush", () => {
  it("is true only for renderers that emit or accept a key-selection", () => {
    expect(rendererCanBrush(TABLE_ARTIFACT)).toBe(true);
    expect(rendererCanBrush(MAP_ARTIFACT)).toBe(true);
    expect(rendererCanBrush(MARKDOWN_ARTIFACT)).toBe(false);
    expect(rendererCanBrush(undefined)).toBe(false);
  });
});

describe("Table artifact rendering", () => {
  async function renderTablePage(page: TablePage, mode = "table") {
    const renderer = rendererFor(TABLE_ARTIFACT);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() =>
        Promise.resolve(
          new Response(JSON.stringify(page), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(
        createElement(
          SWRConfig,
          { value: { provider: () => new Map(), shouldRetryOnError: false } },
          createElement(renderer.Component, {
            artifact: TABLE_ARTIFACT,
            mode,
          }),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const markup = container.innerHTML;
    await act(async () => root.unmount());
    return markup;
  }

  it("does not use the complete artifact payload for its initial render", () => {
    const renderer = rendererFor(TABLE_ARTIFACT);
    const markup = renderToStaticMarkup(
      createElement(renderer.Component, {
        artifact: TABLE_ARTIFACT,
        payload: { rows: [{ geometry: "unbounded-full-value" }] },
        mode: "table",
      }),
    );
    expect(markup).toContain("Loading table page");
    expect(markup).not.toContain("unbounded-full-value");
  });

  it("renders one server page and preserves duplicate display titles", async () => {
    const page: TablePage = {
      columns: [
        { id: "column_1", title: "name", value_type: "text" },
        { id: "column_2", title: "name", value_type: "integer" },
      ],
      rows: [
        {
          column_1: {
            display: "Invoice",
            truncated: false,
            original_length: null,
          },
          column_2: { display: 42, truncated: false, original_length: null },
        },
        {
          column_1: { display: null, truncated: false, original_length: null },
          column_2: { display: 7, truncated: false, original_length: null },
        },
      ],
      offset: 0,
      limit: 50,
      total_rows: 102,
      column_offset: 0,
      column_limit: 25,
      total_columns: 2,
    };

    const renderer = rendererFor(TABLE_ARTIFACT);
    expect(renderer.id).toBe("table");
    expect(renderer.modes).toEqual(["table", "raw"]);
    expect(renderer.interaction).toEqual({
      emits: ["key-selection"],
      accepts: ["filter", "highlight"],
    });

    const markup = await renderTablePage(page);
    expect(markup).toContain('aria-label="Table preview"');
    expect(markup).toContain(">102</span>");
    expect(markup).toContain(">rows</span>");
    expect(markup.match(/>name<\/span>/g)).toHaveLength(2);
    expect(markup).toContain(">Invoice</td>");
    expect(markup).toContain(">—</td>");
    expect(markup).toContain("1–2 of 102");
    expect(markup).toContain("Page 1 of 3");
    expect(markup).toContain('aria-label="Choose visible table columns"');
    expect(markup).not.toContain("Next columns");
  });

  it("renders a useful empty state for zero-row tables", async () => {
    const page: TablePage = {
      columns: [{ id: "column_1", title: "id", value_type: "integer" }],
      rows: [],
      offset: 0,
      limit: 50,
      total_rows: 0,
      column_offset: 0,
      column_limit: 25,
      total_columns: 1,
    };
    const markup = await renderTablePage(page);

    expect(markup).toContain("This table has no rows");
    expect(markup).toContain(">0</span>");
    expect(markup).toContain("No rows");
  });

  it("renders only bounded cell previews and makes full retrieval explicit", async () => {
    const page: TablePage = {
      columns: [{ id: "geometry", title: "Geometry", value_type: "text" }],
      rows: [
        {
          geometry: {
            display: "MULTIPOLYGON (((preview…",
            truncated: true,
            original_length: 125_000,
          },
        },
      ],
      offset: 0,
      limit: 50,
      total_rows: 1,
      column_offset: 0,
      column_limit: 25,
      total_columns: 1,
    };
    const markup = await renderTablePage(page);

    expect(markup).toContain("MULTIPOLYGON (((preview…");
    expect(markup).toContain("Preview truncated; click to inspect");
    expect(markup).not.toContain("125000");
    expect(markup).toContain("Download JSON");
  });

  it("keeps row navigation and column visibility available in raw mode", async () => {
    const page: TablePage = {
      columns: [{ id: "value", title: "Value", value_type: "text" }],
      rows: [
        {
          value: { display: "first", truncated: false, original_length: null },
        },
      ],
      offset: 0,
      limit: 50,
      total_rows: 75,
      column_offset: 0,
      column_limit: 25,
      total_columns: 30,
    };
    const markup = await renderTablePage(page, "raw");

    expect(markup).toContain("total_rows");
    expect(markup).toContain('aria-label="Next page"');
    expect(markup).toContain('aria-label="Choose visible table columns"');
    expect(markup).not.toContain("Next columns");
  });

  it("keeps the previous page and recovery controls when the next page fails", async () => {
    const page: TablePage = {
      columns: [{ id: "value", title: "Value", value_type: "text" }],
      rows: Array.from({ length: 50 }, (_, index) => ({
        value: {
          display: index === 0 ? "still visible" : `row ${index + 1}`,
          truncated: false,
          original_length: null,
        },
      })),
      offset: 0,
      limit: 50,
      total_rows: 75,
      column_offset: 0,
      column_limit: 25,
      total_columns: 1,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(page), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(page), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockRejectedValueOnce(new Error("page unavailable"));
    vi.stubGlobal("fetch", fetchMock);
    const renderer = rendererFor(TABLE_ARTIFACT);
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(
        createElement(
          SWRConfig,
          { value: { provider: () => new Map(), shouldRetryOnError: false } },
          createElement(renderer.Component, {
            artifact: TABLE_ARTIFACT,
            mode: "table",
          }),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const nextButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Next page"]',
    );
    expect(nextButton).toBeDefined();
    await act(async () => {
      nextButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(fetchMock.mock.calls[2][0])).toContain("offset=50");
    expect(container.textContent).toContain("still visible");
    expect(container.textContent).toContain("previous page is still available");
    const previousButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Previous page"]',
    );
    expect(previousButton?.disabled).toBe(false);
    await act(async () => root.unmount());
  });

  it("retrieves a full cell only after the truncated preview is activated", async () => {
    const page: TablePage = {
      columns: [{ id: "geometry/wkt", title: "Geometry", value_type: "text" }],
      rows: [
        {
          "geometry/wkt": {
            display: "MULTIPOLYGON (((preview…",
            truncated: true,
            original_length: 125_000,
          },
        },
      ],
      offset: 0,
      limit: 50,
      total_rows: 1,
      column_offset: 0,
      column_limit: 25,
      total_columns: 1,
    };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.includes("/table/cell?")
        ? {
            row_index: 0,
            column_id: "geometry/wkt",
            value: "MULTIPOLYGON (((complete geometry)))",
            encoding: "native",
          }
        : page;
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const renderer = rendererFor(TABLE_ARTIFACT);
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(
        createElement(
          SWRConfig,
          { value: { provider: () => new Map(), shouldRetryOnError: false } },
          createElement(renderer.Component, {
            artifact: TABLE_ARTIFACT,
            mode: "table",
          }),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const previewButton = [...container.querySelectorAll("button")].find(
      (button) => button.textContent?.includes("MULTIPOLYGON"),
    );
    expect(previewButton).toBeDefined();
    await act(async () => {
      previewButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(fetchMock.mock.calls[2][0])).toContain(
      "/table/cell?row_index=0&column_id=geometry%2Fwkt",
    );
    expect(container.querySelector("textarea")?.value).toBe(
      "MULTIPOLYGON (((complete geometry)))",
    );
    await act(async () => root.unmount());
  });

  it("queries linked filters and emits mapped scalar values for a selected row", async () => {
    const page: TablePage = {
      columns: [
        { id: "place", title: "Place", value_type: "text" },
        { id: "district", title: "District", value_type: "text" },
      ],
      rows: [
        {
          place: {
            display: "Belynichi",
            truncated: false,
            original_length: null,
          },
          district: {
            display: "Mohilev",
            truncated: false,
            original_length: null,
          },
        },
      ],
      row_indices: [7],
      highlighted_row_indices: [7],
      offset: 0,
      limit: 50,
      total_rows: 1,
      column_offset: 0,
      column_limit: 25,
      total_columns: 2,
    };
    let releaseCells: (() => void) | undefined;
    const cellsReady = new Promise<void>((resolve) => {
      releaseCells = resolve;
    });
    const fetchMock = vi
      .fn()
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/table/schema")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                columns: page.columns,
                total_rows: 1,
              }),
              {
                status: 200,
                headers: { "Content-Type": "application/json" },
              },
            ),
          );
        }
        if (url.includes("/table/cell?")) {
          const columnId = new URL(url, "http://test.local").searchParams.get(
            "column_id",
          );
          return cellsReady.then(
            () =>
              new Response(
                JSON.stringify({
                  row_index: 7,
                  column_id: columnId,
                  value: columnId === "place" ? "Belynichi" : "Mohilev",
                  encoding: "native",
                }),
                {
                  status: 200,
                  headers: { "Content-Type": "application/json" },
                },
              ),
          );
        }
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toMatchObject({
          filter_groups: [
            {
              rows: [{ values: { status: "accepted" } }],
            },
          ],
        });
        return Promise.resolve(
          new Response(JSON.stringify(page), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      });
    vi.stubGlobal("fetch", fetchMock);
    const onSelectionChange = vi.fn();
    const onFieldsChange = vi.fn();
    const onActivityChange = vi.fn();
    const interaction: ArtifactViewerInteractionContext = {
      outgoingFields: ["place", "district"],
      selection: { kind: "key-selection", items: [] },
      incoming: [
        {
          bindingId: "binding-1",
          effects: ["filter", "highlight"],
          sourceSelectionCount: 1,
          rows: [{ status: "accepted" }],
        },
      ],
      onFieldsChange,
      onSelectionChange,
      onActivityChange,
    };
    const renderer = rendererFor(TABLE_ARTIFACT);
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(
        createElement(
          SWRConfig,
          { value: { provider: () => new Map(), shouldRetryOnError: false } },
          createElement(renderer.Component, {
            artifact: TABLE_ARTIFACT,
            mode: "table",
            interaction,
          }),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("/table/query"),
      ),
    ).toBe(true);
    expect(onFieldsChange).toHaveBeenCalledWith([
      { id: "place", title: "Place", valueType: "text" },
      { id: "district", title: "District", valueType: "text" },
    ]);
    const row = container.querySelector("tbody tr");
    expect(row?.getAttribute("aria-selected")).toBe("false");
    await act(async () => {
      row?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 220));
    });
    expect(onActivityChange).toHaveBeenLastCalledWith({
      state: "working",
      title: "Reading selected row",
      message: "Loading mapped values from row 8.",
    });
    await act(async () => {
      releaseCells?.();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(onSelectionChange).toHaveBeenCalledWith({
      kind: "key-selection",
      items: [
        {
          sourceIndex: 7,
          values: { place: "Belynichi", district: "Mohilev" },
        },
      ],
    });
    expect(onActivityChange).toHaveBeenLastCalledWith(null);
    await act(async () => root.unmount());
  });

  it("lets the latest row click win when an earlier cell read is still pending", async () => {
    const page: TablePage = {
      columns: [{ id: "place", title: "Place", value_type: "text" }],
      rows: [
        {
          place: {
            display: "First place",
            truncated: false,
            original_length: null,
          },
        },
        {
          place: {
            display: "Second place",
            truncated: false,
            original_length: null,
          },
        },
      ],
      row_indices: [0, 1],
      highlighted_row_indices: [],
      offset: 0,
      limit: 50,
      total_rows: 2,
      column_offset: 0,
      column_limit: 25,
      total_columns: 1,
    };
    const fetchMock = vi
      .fn()
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/table/schema")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                columns: page.columns,
                total_rows: 2,
              }),
              {
                status: 200,
                headers: { "Content-Type": "application/json" },
              },
            ),
          );
        }
        if (url.includes("/table/cell?")) {
          const rowIndex = Number(
            new URL(url, "http://test.local").searchParams.get("row_index"),
          );
          if (rowIndex === 0) {
            return new Promise<Response>((_, reject) => {
              const rejectAborted = () =>
                reject(new DOMException("Aborted", "AbortError"));
              if (init?.signal?.aborted) {
                rejectAborted();
              } else {
                init?.signal?.addEventListener("abort", rejectAborted, {
                  once: true,
                });
              }
            });
          }
          return Promise.resolve(
            new Response(
              JSON.stringify({
                row_index: 1,
                column_id: "place",
                value: "Second place",
                encoding: "native",
              }),
              {
                status: 200,
                headers: { "Content-Type": "application/json" },
              },
            ),
          );
        }
        return Promise.resolve(
          new Response(JSON.stringify(page), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      });
    vi.stubGlobal("fetch", fetchMock);
    const onSelectionChange = vi.fn();
    const interaction: ArtifactViewerInteractionContext = {
      outgoingFields: ["place"],
      selection: { kind: "key-selection", items: [] },
      incoming: [],
      onFieldsChange: vi.fn(),
      onSelectionChange,
      onActivityChange: vi.fn(),
    };
    const renderer = rendererFor(TABLE_ARTIFACT);
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(
        createElement(
          SWRConfig,
          { value: { provider: () => new Map(), shouldRetryOnError: false } },
          createElement(renderer.Component, {
            artifact: TABLE_ARTIFACT,
            mode: "table",
            interaction,
          }),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    const rows = container.querySelectorAll("tbody tr");
    await act(async () => {
      rows[0]?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      rows[1]?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(onSelectionChange).toHaveBeenCalledTimes(1);
    expect(onSelectionChange).toHaveBeenCalledWith({
      kind: "key-selection",
      items: [
        {
          sourceIndex: 1,
          values: { place: "Second place" },
        },
      ],
    });
    await act(async () => root.unmount());
  });

  it("emits integer-encoded cells as numbers so linked tables can match", async () => {
    const page: TablePage = {
      columns: [{ id: "parcel_id", title: "Parcel ID", value_type: "integer" }],
      rows: [
        {
          parcel_id: {
            display: "12",
            truncated: false,
            original_length: null,
          },
        },
      ],
      row_indices: [0],
      highlighted_row_indices: [],
      offset: 0,
      limit: 50,
      total_rows: 1,
      column_offset: 0,
      column_limit: 25,
      total_columns: 1,
    };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/table/schema")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              columns: page.columns,
              total_rows: 1,
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      }
      if (url.includes("/table/cell?")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              row_index: 0,
              column_id: "parcel_id",
              value: "12",
              encoding: "integer",
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(page), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSelectionChange = vi.fn();
    const interaction: ArtifactViewerInteractionContext = {
      outgoingFields: ["parcel_id"],
      selection: { kind: "key-selection", items: [] },
      incoming: [],
      onFieldsChange: vi.fn(),
      onSelectionChange,
      onActivityChange: vi.fn(),
    };
    const renderer = rendererFor(TABLE_ARTIFACT);
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(
        createElement(
          SWRConfig,
          { value: { provider: () => new Map(), shouldRetryOnError: false } },
          createElement(renderer.Component, {
            artifact: TABLE_ARTIFACT,
            mode: "table",
            interaction,
          }),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    await act(async () => {
      container
        .querySelector("tbody tr")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(onSelectionChange).toHaveBeenCalledWith({
      kind: "key-selection",
      items: [
        {
          sourceIndex: 0,
          values: { parcel_id: 12 },
        },
      ],
    });
    await act(async () => root.unmount());
  });

  it("keeps the visible table mounted while a linked highlight query loads", async () => {
    const page: TablePage = {
      columns: [{ id: "place", title: "Place", value_type: "text" }],
      rows: [
        {
          place: {
            display: "Belynichi",
            truncated: false,
            original_length: null,
          },
        },
      ],
      row_indices: [0],
      highlighted_row_indices: [],
      offset: 0,
      limit: 50,
      total_rows: 1,
      column_offset: 0,
      column_limit: 25,
      total_columns: 1,
    };
    let releaseQuery: (() => void) | undefined;
    const queryReady = new Promise<void>((resolve) => {
      releaseQuery = resolve;
    });
    const fetchMock = vi
      .fn()
      .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/table/schema")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                columns: page.columns,
                total_rows: 1,
              }),
              {
                status: 200,
                headers: { "Content-Type": "application/json" },
              },
            ),
          );
        }
        if (init?.method === "POST") {
          return queryReady.then(
            () =>
              new Response(
                JSON.stringify({
                  ...page,
                  highlighted_row_indices: [0],
                }),
                {
                  status: 200,
                  headers: { "Content-Type": "application/json" },
                },
              ),
          );
        }
        return Promise.resolve(
          new Response(JSON.stringify(page), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      });
    vi.stubGlobal("fetch", fetchMock);
    const cache = new Map();
    const renderer = rendererFor(TABLE_ARTIFACT);
    const container = document.createElement("div");
    const root = createRoot(container);
    const swrValue = {
      provider: () => cache,
      shouldRetryOnError: false,
    };
    const renderWithIncoming = async (
      incoming: ArtifactViewerInteractionContext["incoming"],
    ) => {
      await act(async () => {
        root.render(
          createElement(
            SWRConfig,
            { value: swrValue },
            createElement(renderer.Component, {
              artifact: TABLE_ARTIFACT,
              mode: "table",
              interaction: {
                outgoingFields: [],
                selection: { kind: "key-selection", items: [] },
                incoming,
                onFieldsChange: vi.fn(),
                onSelectionChange: vi.fn(),
                onActivityChange: vi.fn(),
              },
            }),
          ),
        );
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    };

    await renderWithIncoming([]);
    expect(container.textContent).toContain("Belynichi");
    expect(container.textContent).not.toContain("Loading table page");

    await renderWithIncoming([
      {
        bindingId: "binding-1",
        effects: ["highlight"],
        sourceSelectionCount: 1,
        rows: [{ place: "Belynichi" }],
      },
    ]);
    expect(container.textContent).toContain("Belynichi");
    expect(container.textContent).not.toContain("Loading table page");
    expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
    ).toBe(true);

    await act(async () => {
      releaseQuery?.();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(container.textContent).toContain("Belynichi");
    expect(container.textContent).not.toContain("Loading table page");
    await act(async () => root.unmount());
  });
});

describe("GIS map artifact rendering", () => {
  async function renderGeo(
    mode: "map" | "raw" = "map",
    descriptor = GEO_RENDER_DESCRIPTOR,
    interaction?: ArtifactViewerInteractionContext,
  ) {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            String(input).includes("/geo/query")
              ? {
                  artifact_id: descriptor.artifact_id,
                  bounds: [29, 53, 29, 53],
                  matched_feature_count: 1,
                  source_artifact_ids: ["features-artifact"],
                }
              : descriptor,
          ),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const renderer = rendererFor(MAP_ARTIFACT);
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(
        createElement(
          SWRConfig,
          { value: { provider: () => new Map(), shouldRetryOnError: false } },
          createElement(renderer.Component, {
            artifact: MAP_ARTIFACT,
            mode,
            availableHeight: 480,
            interaction,
          }),
        ),
      );
    });
    return { container, fetchMock, renderer, root };
  }

  async function clickButton(container: HTMLElement, name: string) {
    const button = [...container.querySelectorAll("button")].find(
      (candidate) =>
        candidate.textContent?.trim() === name ||
        candidate.getAttribute("aria-label") === name,
    );
    expect(button, `button ${name}`).toBeDefined();
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }

  it("fetches only the render descriptor after explicit load and unloads map resources", async () => {
    const { container, fetchMock, renderer, root } = await renderGeo();
    expect(renderer.id).toBe("geo-map");
    expect(renderer.modes).toEqual(["map", "raw"]);
    expect(renderer.interaction).toEqual({
      emits: ["key-selection"],
      accepts: ["filter", "highlight", "focus"],
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(container.textContent).toContain("GIS preview ready");

    await clickButton(container, "Load interactive map");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "/api/v1/workspaces/workspace-1/artifacts/map-artifact/geo/render",
    );
    expect(String(fetchMock.mock.calls[0][0])).not.toContain("/content");
    expect(String(fetchMock.mock.calls[0][0])).not.toContain("/geo/page");
    expect(maplibreMock.instances).toHaveLength(1);
    expect(maplibreMock.addProtocol).toHaveBeenCalledTimes(1);

    const firstMap = maplibreMock.instances[0] as unknown as {
      remove: ReturnType<typeof vi.fn>;
    };
    await clickButton(container, "Unload interactive map");
    expect(firstMap.remove).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("GIS preview ready");

    await clickButton(container, "Load interactive map");
    expect(maplibreMock.instances).toHaveLength(2);
    expect(maplibreMock.addProtocol).toHaveBeenCalledTimes(1);
    await act(async () => root.unmount());
  });

  it("builds ordered PMTiles and raster layers above the optional basemap", async () => {
    const { container, root } = await renderGeo();
    await clickButton(container, "Load interactive map");

    const map = maplibreMock.instances[0] as unknown as {
      options: {
        bounds?: [[number, number], [number, number]];
        fitBoundsOptions?: Record<string, unknown>;
        style: {
          sources: Record<string, Record<string, unknown>>;
          layers: Array<Record<string, unknown>>;
        };
      };
      fitBounds: ReturnType<typeof vi.fn>;
    };
    const { sources, layers } = map.options.style;
    expect(sources["grafy-geo-source-parcels"]).toMatchObject({
      type: "vector",
      url: "pmtiles:///api/v1/artifacts/features-artifact/geo/vector.pmtiles",
    });
    expect(sources["grafy-geo-source-elevation"]).toMatchObject({
      type: "raster",
      url: "/api/v1/artifacts/raster-artifact/geo/raster/tilejson.json",
    });
    expect(layers.map((layer) => layer.id)).toEqual([
      "grafy-openstreetmap-raster",
      "grafy-geo-parcels-fill",
      "grafy-geo-parcels-outline",
      "grafy-geo-parcels-line",
      "grafy-geo-parcels-point",
      "grafy-geo-parcels-label",
      "grafy-geo-elevation-raster",
    ]);
    for (const layer of layers.slice(1, 6)) {
      expect(layer["source-layer"]).toBe("features");
    }
    expect(map.options.bounds).toEqual([
      [-12, 35],
      [22, 61],
    ]);
    expect(map.options.fitBoundsOptions).toEqual({
      padding: 28,
      maxZoom: 14,
      duration: 0,
    });
    expect(map.fitBounds).not.toHaveBeenCalled();
    await act(async () => root.unmount());
  });

  it("applies linked filters and focuses exact features once per selection", async () => {
    const onActivityChange = vi.fn();
    const interaction: ArtifactViewerInteractionContext = {
      outgoingFields: [],
      selection: { kind: "key-selection", items: [] },
      incoming: [
        {
          bindingId: "binding-1",
          effects: ["filter", "highlight", "focus"],
          sourceSelectionCount: 1,
          rows: [{ name: "Control point 23", district: "Mohilev" }],
        },
      ],
      onFieldsChange: vi.fn(),
      onSelectionChange: vi.fn(),
      onActivityChange,
    };
    const { container, fetchMock, renderer, root } = await renderGeo(
      "map",
      GEO_RENDER_DESCRIPTOR,
      interaction,
    );
    await clickButton(container, "Load interactive map");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1][0])).toContain("/geo/query");
    const map = maplibreMock.instances[0] as unknown as {
      fitBounds: ReturnType<typeof vi.fn>;
      setFilter: ReturnType<typeof vi.fn>;
      setPaintProperty: ReturnType<typeof vi.fn>;
    };
    expect(
      map.setFilter.mock.calls.some(([, filter]) =>
        JSON.stringify(filter).includes("Control point 23"),
      ),
    ).toBe(true);
    expect(
      map.setPaintProperty.mock.calls.some(
        ([, , value]) => Array.isArray(value) && value[0] === "case",
      ),
    ).toBe(true);
    expect(map.fitBounds).toHaveBeenCalledWith(
      [
        [28.98, 52.98],
        [29.02, 53.02],
      ],
      expect.objectContaining({ duration: 450 }),
    );
    expect(onActivityChange).toHaveBeenLastCalledWith({
      state: "success",
      title: "Linked feature located",
      message: "Located 1 matching map feature.",
    });

    map.fitBounds.mockClear();
    await act(async () => {
      root.render(
        createElement(
          SWRConfig,
          { value: { provider: () => new Map(), shouldRetryOnError: false } },
          createElement(renderer.Component, {
            artifact: MAP_ARTIFACT,
            mode: "map",
            availableHeight: 480,
            interaction: {
              ...interaction,
              selection: {
                kind: "key-selection",
                items: [{ values: { name: "A different map feature" } }],
              },
              incoming: interaction.incoming.map((binding) => ({
                ...binding,
                rows: binding.rows.map((values) => ({ ...values })),
              })),
            },
          }),
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(map.fitBounds).not.toHaveBeenCalled();
    await act(async () => root.unmount());
  });

  it("reports linked focus progress and a zero-match result", async () => {
    const onActivityChange = vi.fn();
    const interaction: ArtifactViewerInteractionContext = {
      outgoingFields: [],
      selection: { kind: "key-selection", items: [] },
      incoming: [
        {
          bindingId: "binding-1",
          effects: ["focus"],
          sourceSelectionCount: 1,
          rows: [{ name: "Missing place" }],
        },
      ],
      onFieldsChange: vi.fn(),
      onSelectionChange: vi.fn(),
      onActivityChange,
    };
    const { container, fetchMock, root } = await renderGeo(
      "map",
      GEO_RENDER_DESCRIPTOR,
      interaction,
    );
    let resolveQuery: ((response: Response) => void) | undefined;
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      if (String(input).includes("/geo/query")) {
        return new Promise<Response>((resolve) => {
          resolveQuery = resolve;
        });
      }
      return Promise.resolve(
        new Response(JSON.stringify(GEO_RENDER_DESCRIPTOR), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    await clickButton(container, "Load interactive map");

    expect(resolveQuery).toBeDefined();
    expect(onActivityChange).toHaveBeenLastCalledWith({
      state: "working",
      title: "Locating linked selection",
      message: "Searching the map layers for matching features.",
    });
    await act(async () => {
      resolveQuery?.(
        new Response(
          JSON.stringify({
            artifact_id: GEO_RENDER_DESCRIPTOR.artifact_id,
            bounds: null,
            matched_feature_count: 0,
            source_artifact_ids: [],
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(onActivityChange).toHaveBeenLastCalledWith({
      state: "warning",
      title: "No linked feature found",
      message: "No map feature matched the linked selection.",
    });
    await act(async () => root.unmount());
  });

  it("explains when selected values cannot be mapped to map fields", async () => {
    const onActivityChange = vi.fn();
    const interaction: ArtifactViewerInteractionContext = {
      outgoingFields: [],
      selection: { kind: "key-selection", items: [] },
      incoming: [
        {
          bindingId: "binding-1",
          effects: ["focus"],
          sourceSelectionCount: 1,
          rows: [],
        },
      ],
      onFieldsChange: vi.fn(),
      onSelectionChange: vi.fn(),
      onActivityChange,
    };
    const { container, fetchMock, root } = await renderGeo(
      "map",
      GEO_RENDER_DESCRIPTOR,
      interaction,
    );
    await clickButton(container, "Load interactive map");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onActivityChange).toHaveBeenLastCalledWith({
      state: "warning",
      title: "Selection mapping failed",
      message:
        "The selected row does not provide all configured target fields.",
    });
    await act(async () => root.unmount());
  });

  it("renders categorized point filters and exposes an interactive legend", async () => {
    const { container, root } = await renderGeo(
      "map",
      CATEGORIZED_GEO_RENDER_DESCRIPTOR,
    );
    await clickButton(container, "Load interactive map");

    const map = maplibreMock.instances[0] as unknown as {
      options: {
        style: {
          layers: Array<Record<string, unknown>>;
        };
      };
      setLayoutProperty: ReturnType<typeof vi.fn>;
      setPaintProperty: ReturnType<typeof vi.fn>;
    };
    const categorizedLayers = map.options.style.layers.slice(1);
    expect(categorizedLayers.map((layer) => layer.id)).toEqual([
      "grafy-geo-chrzanowski-symbols-category-cities-point",
      "grafy-geo-chrzanowski-symbols-category-cities-label",
      "grafy-geo-chrzanowski-symbols-category-villages-point",
      "grafy-geo-chrzanowski-symbols-category-villages-label",
    ]);
    expect(categorizedLayers[0]).toMatchObject({
      minzoom: 6,
      maxzoom: 22,
      filter: [
        "all",
        [
          "any",
          ["==", ["geometry-type"], "Point"],
          ["==", ["geometry-type"], "MultiPoint"],
        ],
        ["in", ["get", "type"], ["literal", [1, 2, 3]]],
      ],
      paint: {
        "circle-color": "#b91c1c",
        "circle-radius": 7,
        "circle-pitch-scale": "viewport",
      },
    });
    expect(categorizedLayers[1]).toMatchObject({
      layout: {
        "text-variable-anchor": ["top", "bottom", "left", "right"],
        "text-radial-offset": 7 / 12 + 0.35,
        "text-justify": "auto",
      },
    });
    expect(categorizedLayers[2]).toMatchObject({
      minzoom: 10,
      paint: {
        "circle-color": "#d6a700",
        "circle-radius": 4,
        "circle-pitch-scale": "viewport",
      },
    });

    await clickButton(container, "1 layer");
    await clickButton(container, "1. Chrzanowski symbols");
    expect(container.textContent).toContain("Categories · type");
    expect(container.textContent).toContain("Cities and towns");
    expect(container.textContent).toContain("Villages");
    expect(container.textContent).toContain("5, 7, 8, 9, 10 · z10–22");

    const citiesRadius = container.querySelector<HTMLInputElement>(
      'input[aria-label="Cities and towns radius"]',
    );
    expect(citiesRadius?.value).toBe("7");
    await act(async () => {
      if (citiesRadius) {
        const valueSetter = Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          "value",
        )?.set;
        valueSetter?.call(citiesRadius, "9");
        citiesRadius.dispatchEvent(new Event("input", { bubbles: true }));
      }
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(map.setPaintProperty).toHaveBeenCalledWith(
      "grafy-geo-chrzanowski-symbols-category-cities-point",
      "circle-radius",
      9,
    );
    expect(map.setLayoutProperty).toHaveBeenCalledWith(
      "grafy-geo-chrzanowski-symbols-category-cities-label",
      "text-radial-offset",
      9 / 12 + 0.35,
    );
    const paintCallCountBeforeReset = map.setPaintProperty.mock.calls.length;
    await clickButton(container, "Reset layer");
    expect(citiesRadius?.value).toBe("7");
    expect(
      map.setPaintProperty.mock.calls.slice(paintCallCountBeforeReset),
    ).toContainEqual([
      "grafy-geo-chrzanowski-symbols-category-cities-point",
      "circle-radius",
      7,
    ]);

    const villagesToggle = container.querySelector<HTMLInputElement>(
      'input[aria-label="Show Villages"]',
    );
    expect(villagesToggle).not.toBeNull();
    await act(async () => {
      villagesToggle?.click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(map.setLayoutProperty).toHaveBeenCalledWith(
      "grafy-geo-chrzanowski-symbols-category-villages-point",
      "visibility",
      "none",
    );
    expect(map.setLayoutProperty).toHaveBeenCalledWith(
      "grafy-geo-chrzanowski-symbols-category-villages-label",
      "visibility",
      "none",
    );
    await act(async () => root.unmount());
  });

  it("uses feature hit-testing to expose a pointer and inspect vector properties", async () => {
    const onSelectionChange = vi.fn();
    const onFieldsChange = vi.fn();
    const { container, root } = await renderGeo("map", GEO_RENDER_DESCRIPTOR, {
      outgoingFields: ["name", "sheet"],
      selection: { kind: "key-selection", items: [] },
      incoming: [],
      onFieldsChange,
      onSelectionChange,
      onActivityChange: vi.fn(),
    });
    await clickButton(container, "Load interactive map");
    expect(onFieldsChange).toHaveBeenCalledWith([
      { id: "name", title: "Name", valueType: "text" },
      { id: "sheet", title: "Sheet", valueType: "text" },
    ]);
    await clickButton(container, "2 layers");

    const map = maplibreMock.instances[0] as unknown as {
      canvas: HTMLCanvasElement;
      canvasContainer: HTMLElement;
      emit: (event: string, payload: Record<string, unknown>) => void;
      isStyleLoaded: ReturnType<typeof vi.fn>;
      queryRenderedFeatures: ReturnType<typeof vi.fn>;
    };
    Object.defineProperties(map.canvas, {
      clientWidth: { configurable: true, value: 800 },
      clientHeight: { configurable: true, value: 480 },
    });
    vi.spyOn(map.canvas, "getBoundingClientRect").mockReturnValue({
      width: 400,
      height: 240,
    } as DOMRect);
    const pointerEvent = {
      point: { x: 420, y: 180 },
      lngLat: { lng: 19.93821, lat: 50.06143 },
    };
    map.queryRenderedFeatures.mockReturnValue([
      {
        type: "Feature",
        id: 23,
        properties: {
          name: "Control point 23",
          sheet: "A-17",
          surveyed: true,
        },
        geometry: {
          type: "Point",
          coordinates: [19.93821, 50.06143],
        },
        layer: { id: "grafy-geo-parcels-point" },
        source: "grafy-geo-source-parcels",
        sourceLayer: "features",
        state: {},
      },
    ]);
    map.isStyleLoaded.mockReturnValue(false);

    map.emit("mousemove", pointerEvent);
    expect(
      map.canvasContainer.classList.contains("maplibregl-track-pointer"),
    ).toBe(true);
    expect(map.queryRenderedFeatures).toHaveBeenLastCalledWith(
      [
        [816, 336],
        [864, 384],
      ],
      {
        layers: [
          "grafy-geo-parcels-fill",
          "grafy-geo-parcels-line",
          "grafy-geo-parcels-point",
        ],
      },
    );

    await act(async () => {
      map.emit("click", pointerEvent);
    });
    const featureDetails = container.querySelector(
      '[aria-label="Selected feature details"]',
    );
    expect(featureDetails?.textContent).toContain("Parcels · Point");
    expect(featureDetails?.textContent).toContain("Control point 23");
    expect(featureDetails?.textContent).toContain("ID 23");
    expect(featureDetails?.textContent).toContain("19.93821, 50.06143");
    expect(featureDetails?.textContent).toContain("sheet");
    expect(featureDetails?.textContent).toContain("A-17");
    expect(
      container.querySelector('[aria-label="Map layer inspector"]'),
    ).toBeNull();
    expect(onSelectionChange).toHaveBeenCalledWith({
      kind: "key-selection",
      items: [
        {
          values: {
            name: "Control point 23",
            sheet: "A-17",
            surveyed: true,
          },
        },
      ],
    });

    map.queryRenderedFeatures.mockReturnValue([]);
    map.emit("mousemove", pointerEvent);
    expect(
      map.canvasContainer.classList.contains("maplibregl-track-pointer"),
    ).toBe(false);
    await act(async () => {
      map.emit("click", pointerEvent);
    });
    expect(
      container.querySelector('[aria-label="Selected feature details"]'),
    ).toBeNull();
    expect(onSelectionChange).toHaveBeenLastCalledWith({
      kind: "key-selection",
      items: [],
    });

    await act(async () => root.unmount());
  });

  it("previews vector and raster inspector overrides locally", async () => {
    const { container, root } = await renderGeo();
    await clickButton(container, "Load interactive map");
    await clickButton(container, "2 layers");
    await clickButton(container, "1. Parcels");

    const layerOpacity = [...container.querySelectorAll("label")]
      .find((label) => label.textContent?.includes("Layer opacity"))
      ?.querySelector<HTMLInputElement>('input[type="range"]');
    expect(layerOpacity).not.toBeNull();
    await act(async () => {
      if (layerOpacity) {
        const valueSetter = Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          "value",
        )?.set;
        valueSetter?.call(layerOpacity, "0.5");
        layerOpacity.dispatchEvent(new Event("input", { bubbles: true }));
      }
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    const map = maplibreMock.instances[0] as unknown as {
      setLayoutProperty: ReturnType<typeof vi.fn>;
      setPaintProperty: ReturnType<typeof vi.fn>;
    };
    expect(map.setPaintProperty).toHaveBeenCalledWith(
      "grafy-geo-parcels-fill",
      "fill-opacity",
      0.2,
    );
    await clickButton(container, "Disable labels");
    expect(map.setLayoutProperty).toHaveBeenCalledWith(
      "grafy-geo-parcels-label",
      "visibility",
      "none",
    );
    await clickButton(container, "Enable labels");
    expect(map.setLayoutProperty).toHaveBeenCalledWith(
      "grafy-geo-parcels-label",
      "visibility",
      "visible",
    );
    await clickButton(container, "Hide Parcels");
    expect(map.setLayoutProperty).toHaveBeenCalledWith(
      "grafy-geo-parcels-fill",
      "visibility",
      "none",
    );

    await clickButton(container, "2. Elevation");
    const resampling = [...container.querySelectorAll("label")]
      .find((label) => label.textContent?.includes("Resampling"))
      ?.querySelector<HTMLSelectElement>("select");
    expect(resampling).not.toBeNull();
    await act(async () => {
      if (resampling) {
        resampling.value = "nearest";
        resampling.dispatchEvent(new Event("change", { bubbles: true }));
      }
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(map.setPaintProperty).toHaveBeenCalledWith(
      "grafy-geo-elevation-raster",
      "raster-resampling",
      "nearest",
    );
    expect(container.textContent).not.toContain("Features per page");
    await act(async () => root.unmount());
  });

  it("shows the immutable descriptor in raw mode without constructing a map", async () => {
    const { container, fetchMock, root } = await renderGeo("raw");
    expect(fetchMock).not.toHaveBeenCalled();
    await clickButton(container, "Load interactive map");

    expect(container.textContent).toContain('"kind": "map_document"');
    expect(container.textContent).toContain('"archive_url"');
    expect(container.textContent).toContain('"tilejson_url"');
    expect(maplibreMock.instances).toHaveLength(0);
    await act(async () => root.unmount());
  });
});

describe("JSON Schema artifact rendering", () => {
  it("unwraps and indents the schema value for the pretty view", () => {
    const payload = {
      value: '{"type":"object","properties":{"invoice_id":{"type":"string"}}}',
    };

    expect(formatJsonSchemaPayload(payload)).toBe(
      [
        "{",
        '  "type": "object",',
        '  "properties": {',
        '    "invoice_id": {',
        '      "type": "string"',
        "    }",
        "  }",
        "}",
      ].join("\n"),
    );

    const renderer = rendererFor(JSON_SCHEMA_ARTIFACT, payload);
    expect(renderer.id).toBe("json-schema");
    const markup = renderToStaticMarkup(
      createElement(renderer.Component, {
        artifact: JSON_SCHEMA_ARTIFACT,
        payload,
        mode: "pretty",
      }),
    );
    expect(markup).toContain("invoice_id");
    expect(markup).not.toContain("&quot;{\\&quot;type");
  });

  it("falls back safely for malformed or non-object schema payloads", () => {
    expect(formatJsonSchemaPayload({ value: "not-json" })).toBeNull();
    expect(formatJsonSchemaPayload({ value: "[]" })).toBeNull();
    expect(formatJsonSchemaPayload({ value: "true" })).toBeNull();
    expect(formatJsonSchemaPayload({})).toBeNull();
    expect(formatJsonSchemaPayload({ value: 42 })).toBeNull();
  });

  it("does not reinterpret JSON-shaped text artifacts", () => {
    const textArtifact: ArtifactSummary = {
      ...JSON_SCHEMA_ARTIFACT,
      artifact_id: "text-artifact",
      artifact_type: "scalar.text",
    };

    expect(rendererFor(textArtifact, { value: '{"type":"object"}' }).id).toBe(
      "json",
    );
  });

  it("keeps raw mode on the stored payload envelope", () => {
    const payload = { value: '{"type":"object"}' };
    const renderer = rendererFor(JSON_SCHEMA_ARTIFACT, payload);
    const markup = renderToStaticMarkup(
      createElement(renderer.Component, {
        artifact: JSON_SCHEMA_ARTIFACT,
        payload,
        mode: "raw",
      }),
    );

    expect(markup).toContain("value");
    expect(markup).toContain("\\&quot;type\\&quot;");
  });
});

describe("Markdown artifact rendering", () => {
  it("selects the nominal renderer before generic JSON and renders GFM", () => {
    const payload = {
      markdown: [
        "# Extracted content",
        "",
        "A **useful** result.",
        "",
        "- first",
        "- second",
        "",
        "| Field | Value |",
        "| --- | --- |",
        "| title | Example |",
      ].join("\n"),
    };

    expect(markdownPayload(payload)).toEqual(payload);
    const renderer = rendererFor(MARKDOWN_ARTIFACT, payload);
    expect(renderer.id).toBe("markdown");
    expect(renderer.modes).toEqual(["preview", "raw"]);

    const markup = renderToStaticMarkup(
      createElement(renderer.Component, {
        artifact: MARKDOWN_ARTIFACT,
        payload,
        mode: "preview",
      }),
    );

    expect(markup).toContain("<h1");
    expect(markup).toContain(">Extracted content</h1>");
    expect(markup).toContain("<strong>useful</strong>");
    expect(markup).toContain("<ul>");
    expect(markup).toContain("<table>");
    expect(markup).not.toContain("markdown<!-- -->");
  });

  it("shows the Markdown source itself in raw mode", () => {
    const payload = { markdown: "# Source\n\n`inline`" };
    const renderer = rendererFor(MARKDOWN_ARTIFACT, payload);
    const markup = renderToStaticMarkup(
      createElement(renderer.Component, {
        artifact: MARKDOWN_ARTIFACT,
        payload,
        mode: "raw",
      }),
    );

    expect(markup).toContain("# Source");
    expect(markup).toContain("`inline`");
    expect(markup).not.toContain("&quot;markdown&quot;");
    expect(markup).not.toContain("<h1>");
  });

  it("does not interpret raw HTML or unsafe link protocols", () => {
    const payload = {
      markdown: [
        "# Safe heading",
        "",
        '<script>alert("unsafe")</script>',
        "",
        '<img src="x" onerror="alert(1)">',
        "",
        "[unsafe link](javascript:alert(1))",
        "",
        "[unsafe data link](data:image/svg+xml;base64,PHN2Zy8+)",
        "",
        "[safe link](https://example.com)",
        "",
        "![tracking pixel](https://tracker.example/pixel.gif)",
        "",
        "![inline image](data:image/png;base64,iVBORw0KGgo=)",
      ].join("\n"),
    };
    const renderer = rendererFor(MARKDOWN_ARTIFACT, payload);
    const markup = renderToStaticMarkup(
      createElement(renderer.Component, {
        artifact: MARKDOWN_ARTIFACT,
        payload,
        mode: "preview",
      }),
    );

    expect(markup).toContain("<h1");
    expect(markup).toContain(">Safe heading</h1>");
    expect(markup).not.toContain("<script");
    expect(markup).toContain("&lt;script&gt;");
    expect(markup).toContain("&lt;img src=&quot;x&quot; onerror=");
    expect(markup).not.toContain("javascript:");
    expect(markup).not.toContain("data:image");
    expect(markup).toContain('href="https://example.com"');
    expect(markup).toContain('rel="noreferrer noopener"');
    expect(markup).not.toContain("<img");
    expect(markup).toContain("Image: tracking pixel");
    expect(markup).toContain('href="https://tracker.example/pixel.gif"');
  });

  it("falls back safely when the payload does not satisfy the contract", () => {
    expect(markdownPayload(undefined)).toBeNull();
    expect(markdownPayload({ markdown: 42 })).toBeNull();
    expect(markdownPayload({ value: "# wrong envelope" })).toBeNull();

    const renderer = rendererFor(MARKDOWN_ARTIFACT, { markdown: 42 });
    expect(() =>
      renderToStaticMarkup(
        createElement(renderer.Component, {
          artifact: MARKDOWN_ARTIFACT,
          payload: { markdown: 42 },
          mode: "preview",
        }),
      ),
    ).not.toThrow();
  });
});

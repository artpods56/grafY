// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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
  ArtifactTypeSpec,
  RunPortArtifact,
  RunPortOutput,
} from "@/lib/api";
import { ArtifactPortPreview, storedArtifactView } from "./ArtifactsAppendix";

/**
 * A stored result names its artifacts and nothing more: no content type, no
 * byte size, no inline text. Every fixture here is that reference.
 */
function referenceFor(
  artifactId: string,
  artifactType: string,
  schemaVersion = 1,
): RunPortArtifact {
  return {
    artifact_id: artifactId,
    artifact_type: artifactType,
    schema_version: schemaVersion,
    content_hash: null,
  };
}

function outputFor(
  artifacts: readonly RunPortArtifact[],
  kind: "single" | "sequence" = "single",
): RunPortOutput {
  const first = artifacts[0];
  const [firstRef] = artifacts;
  if (!first || !firstRef) {
    throw new Error("outputFor requires at least one artifact");
  }
  return {
    port: "result",
    kind,
    value:
      kind === "single"
        ? {
            artifact_id: firstRef.artifact_id,
            artifact_type: firstRef.artifact_type,
            schema_version: firstRef.schema_version,
          }
        : {
            artifact_type: first.artifact_type,
            schema_version: first.schema_version,
            index_key: "order_index",
            ordered: true,
            item_refs: artifacts.map((artifact) => ({
              artifact_id: artifact.artifact_id,
              artifact_type: artifact.artifact_type,
              schema_version: artifact.schema_version,
            })),
          },
    artifacts,
  };
}

function jsonType(id: string): ArtifactTypeSpec {
  return {
    key: { id, schema_version: 1 },
    title: `${id} value`,
    bundle: { format: "inline-json", version: 1 },
    payload_schema: {},
    field_projections: [],
  } as unknown as ArtifactTypeSpec;
}

async function renderPreview(
  output: RunPortOutput,
  artifactTypes: readonly ArtifactTypeSpec[] = [],
  mode: {
    modeChoice?: string | null;
    onModeChoiceChange?: (mode: string) => void;
  } = {},
): Promise<{ container: HTMLDivElement; root: Root }> {
  const container = document.createElement("div");
  const root = createRoot(container);
  await act(async () => {
    root.render(
      createElement(
        SWRConfig,
        { value: { provider: () => new Map(), shouldRetryOnError: false } },
        createElement(ArtifactPortPreview, {
          output,
          artifactTypes,
          previewHeight: 320,
          modeChoice: mode.modeChoice,
          onModeChoiceChange: mode.onModeChoiceChange,
        }),
      ),
    );
    await act(async () => {
      await Promise.resolve();
    });
  });
  return { container, root };
}

afterEach(() => vi.unstubAllGlobals());

describe("a stored reference's renderer view", () => {
  it("carries the declared type and no size the reference never had", () => {
    const view = storedArtifactView(
      "workspace-1",
      {
        artifact_id: "a1",
        artifact_type: "text.markdown",
        schema_version: 1,
        content_hash: "ab12",
      },
      jsonType("text.markdown"),
    );

    // The bytes are read back through the artifact's own route, the content type
    // is the one declared for its type, and the hash travels as the fingerprint it
    // is. A byte size, inline text and an uploaded filename belong to a Library
    // summary: a view built from a reference has none of them to hand a renderer.
    expect(view.content_type).toBe("application/json");
    expect(view.content_url).toContain("/artifacts/a1/content");
    expect(view.sha256).toBe("ab12");
    expect(view).not.toHaveProperty("byte_size");
    expect(view).not.toHaveProperty("metadata");
    expect(view).not.toHaveProperty("text");
  });
});

describe("artifact payload loading policy", () => {
  it("loads only the bounded page endpoint for table previews", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            columns: [],
            rows: [],
            offset: 0,
            limit: 50,
            total_rows: 0,
            column_offset: 0,
            column_limit: 25,
            total_columns: 0,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const artifact = referenceFor("table-artifact", "table.data");

    const { root } = await renderPreview(outputFor([artifact]));

    expect(
      fetchMock.mock.calls.some((call) =>
        String(call[0]).includes(
          "/v1/workspaces/workspace-1/artifacts/table-artifact/table/schema",
        ),
      ),
    ).toBe(true);
    expect(
      fetchMock.mock.calls.some((call) =>
        String(call[0]).includes(
          "/v1/workspaces/workspace-1/artifacts/table-artifact/table/page?",
        ),
      ),
    ).toBe(true);
    expect(
      fetchMock.mock.calls.every(
        (call) => !String(call[0]).includes("/content"),
      ),
    ).toBe(true);
    await act(async () => root.unmount());
  });

  it.each([
    "geo.feature_collection",
    "geo.raster_scan",
    "geo.map_layer",
    "geo.map_document",
  ])("never loads generic content for %s previews", async (artifactType) => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: "Render descriptor unavailable in this policy test",
        }),
        { status: 500, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const artifact = referenceFor(`map-${artifactType}`, artifactType);

    const { container, root } = await renderPreview(outputFor([artifact]));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Load interactive map");
    const loadButton = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Load interactive map",
    );
    await act(async () => {
      loadButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]![0])).toContain("/geo/render");
    expect(String(fetchMock.mock.calls[0]![0])).not.toContain("/geo/page");
    expect(String(fetchMock.mock.calls[0]![0])).not.toContain("/content");
    await act(async () => root.unmount());
  });

  it("reads a stored result's JSON bytes from the artifact's own route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ answer: 42 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const artifact = referenceFor("json-artifact", "json.object");

    const { container, root } = await renderPreview(outputFor([artifact]), [
      jsonType("json.object"),
    ]);

    expect(
      fetchMock.mock.calls.some((call) =>
        String(call[0]).includes(
          "/v1/workspaces/workspace-1/artifacts/json-artifact/content",
        ),
      ),
    ).toBe(true);
    expect(container.textContent).toContain("42");
    await act(async () => root.unmount());
  });

  it("does not read JSON bytes for a type the catalog stores as a file", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const artifact = referenceFor("geo-artifact", "geo.feature_collection");
    const geoType: ArtifactTypeSpec = {
      ...jsonType("geo.feature_collection"),
      bundle: { format: "binary-file", version: 1 },
    };

    const { root } = await renderPreview(outputFor([artifact]), [geoType]);

    expect(
      fetchMock.mock.calls.some((call) => String(call[0]).endsWith("/content")),
    ).toBe(false);
    await act(async () => root.unmount());
  });

  it("projects a sequence field by reading every item's content route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ row_count: 12 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const artifacts = ["first", "second"].map((id) =>
      referenceFor(id, "json.object"),
    );
    const artifactTypes: ArtifactTypeSpec[] = [
      {
        ...jsonType("json.object"),
        payload_schema: {
          type: "object",
          properties: { row_count: { type: "integer" } },
        },
      },
    ];

    const { container, root } = await renderPreview(
      outputFor(artifacts, "sequence"),
      artifactTypes,
    );

    const select = container.querySelector("select");
    expect(select).not.toBeNull();
    await act(async () => {
      if (!select) return;
      select.value = "row_count";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      await Promise.resolve();
    });

    const contentCalls = fetchMock.mock.calls
      .map((call) => String(call[0]))
      .filter((url) => url.endsWith("/content"))
      .join("\n");
    expect(contentCalls).toContain(
      "/workspaces/workspace-1/artifacts/first/content",
    );
    expect(contentCalls).toContain(
      "/workspaces/workspace-1/artifacts/second/content",
    );
    expect(container.textContent).not.toContain("Field projection is disabled");
    await act(async () => root.unmount());
  });

  it("keeps the ingest notice on a blob artifact and shows readable bytes", async () => {
    const fetchMock = vi.fn(
      async () => new Response('{"hello": "world"}', { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const artifact = referenceFor("blob-artifact", "file.blob");

    const { container, root } = await renderPreview(outputFor([artifact]));

    expect(container.textContent).toContain(
      "Format not recognized, stored as a blob.",
    );
    expect(container.textContent).toContain('"hello": "world"');
    await act(async () => root.unmount());
  });

  it("falls back to metadata for a blob artifact whose bytes are binary", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x00]), {
            status: 200,
          }),
      ),
    );
    const artifact = referenceFor("binary-artifact", "file.blob");

    const { container, root } = await renderPreview(outputFor([artifact]));

    expect(container.textContent).toContain("Binary content");
    expect(container.textContent).toContain("binary-artifact");
    await act(async () => root.unmount());
  });

  it("shows a scalar artifact as its JSON text by default", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response('{"value":5}', {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );
    const artifact = referenceFor("integer-artifact", "scalar.integer");

    const { container, root } = await renderPreview(outputFor([artifact]), [
      jsonType("scalar.integer"),
    ]);

    expect(container.querySelector("pre")?.textContent).toBe(
      '{\n  "value": 5\n}',
    );
    await act(async () => root.unmount());
  });
});

describe("the artifact view mode", () => {
  it("switches modes through one labelled radio group, not a row of toggles", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response('{"value":5}', {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );
    const onModeChoiceChange = vi.fn();
    const artifact = referenceFor("integer-artifact", "scalar.integer");

    const { container, root } = await renderPreview(
      outputFor([artifact]),
      [jsonType("scalar.integer")],
      { onModeChoiceChange },
    );

    const group = container.querySelector<HTMLElement>(
      '[role="radiogroup"][aria-label="Artifact view mode"]',
    );
    const radios = [
      ...(group?.querySelectorAll<HTMLElement>('[role="radio"]') ?? []),
    ];

    // The renderer declares raw and pretty, in that order, and the card shows
    // the first until someone chooses otherwise.
    expect(radios.map((radio) => radio.textContent)).toEqual(["raw", "pretty"]);
    expect(radios.map((radio) => radio.getAttribute("aria-checked"))).toEqual([
      "true",
      "false",
    ]);
    // One choice, so nothing in the row carries a pressed state any more.
    expect(group?.querySelectorAll("[aria-pressed]")).toHaveLength(0);
    // The row sits on a draggable card: the pointer must not drag or zoom the pane.
    expect(group?.className.split(" ")).toEqual(
      expect.arrayContaining(["nodrag", "nowheel"]),
    );

    const pretty = radios[1];
    if (!pretty) throw new Error("the scalar renderer has a pretty mode");
    await act(async () => {
      pretty.click();
    });

    expect(onModeChoiceChange).toHaveBeenCalledOnce();
    expect(onModeChoiceChange).toHaveBeenCalledWith("pretty");
    expect(pretty.getAttribute("aria-checked")).toBe("true");
    expect(radios[0]?.getAttribute("aria-checked")).toBe("false");

    await act(async () => root.unmount());
  });
});

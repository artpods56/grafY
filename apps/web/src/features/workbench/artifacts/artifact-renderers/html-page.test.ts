import { afterEach, describe, expect, it, vi } from "vitest";

import type { TablePage } from "@/lib/api";

import {
  assembleHtmlPage,
  HTML_PAGE_BYTE_LIMIT,
  HTML_PAGE_TABLE_ROW_LIMIT,
  loadHtmlPage,
  readWholeText,
  tableShortfall,
  type HtmlPageSourceRef,
  type NamedSource,
  type SourceFetch,
  type WholeText,
} from "./html-page";

afterEach(() => vi.unstubAllGlobals());

function source(
  name: string,
  artifactType: string,
  artifactId = name,
): NamedSource {
  const ref: HtmlPageSourceRef = {
    artifact_id: artifactId,
    artifact_type: artifactType,
    schema_version: 1,
  };
  return { name, ref };
}

function text(body: string): SourceFetch {
  return { kind: "text", text: { kind: "text", text: body } };
}

function pageJson(
  html: string,
  sources: Record<string, HtmlPageSourceRef>,
): WholeText {
  return {
    kind: "text",
    text: JSON.stringify({ html, sources }),
  };
}

function tablePage(rows: TablePage["rows"], totalRows: number): TablePage {
  return {
    columns: [{ id: "year", title: "Year", value_type: "text" }],
    rows,
    offset: 0,
    limit: HTML_PAGE_TABLE_ROW_LIMIT,
    total_rows: totalRows,
    column_offset: 0,
    column_limit: 1,
    total_columns: 1,
  };
}

describe("assembleHtmlPage", () => {
  it("fills a template from each kind of source", async () => {
    const baptisms = source("baptisms", "scalar.text");
    const note = source("note", "text.markdown");
    const parish = source("parish", "json.value");
    const people = source("people", "record.list");
    const years = source("years", "table.register");
    const loaded = await assembleHtmlPage(
      pageJson(
        "{{baptisms}}|{{note}}|{{parish.title}}|{{#people}}{{name}}{{/people}}|{{#years}}{{year}}{{/years}}",
        {
          baptisms: baptisms.ref,
          note: note.ref,
          parish: parish.ref,
          people: people.ref,
          years: years.ref,
        },
      ),
      (item) => {
        if (item.name === "baptisms") {
          return Promise.resolve(text(JSON.stringify({ value: "Ada" })));
        }
        if (item.name === "note") {
          return Promise.resolve(
            text(JSON.stringify({ markdown: "buried Tuesday" })),
          );
        }
        if (item.name === "parish") {
          return Promise.resolve(text(JSON.stringify({ title: "St Mary" })));
        }
        if (item.name === "people") {
          return Promise.resolve(
            text(JSON.stringify([{ name: "Byron" }, { name: "Ann" }])),
          );
        }
        return Promise.resolve({
          kind: "table",
          page: tablePage(
            [{ year: { display: 1815, truncated: false } }],
            1_204,
          ),
        });
      },
    );

    expect(loaded.status).toBe("ready");
    if (loaded.status !== "ready") return;
    expect(loaded.rendered).toBe("Ada|buried Tuesday|St Mary|ByronAnn|1815");
    expect(loaded.shortfalls).toEqual(["showing 1 of 1,204 rows of years"]);
    expect(loaded.sourceNames).toEqual([
      "baptisms",
      "note",
      "parish",
      "people",
      "years",
    ]);
  });

  it("escapes values and reports a broken template without rendering it", async () => {
    const name = source("name", "scalar.text");
    const escaped = await assembleHtmlPage(
      pageJson("<p>{{name}}</p>", { name: name.ref }),
      () =>
        Promise.resolve(
          text(
            JSON.stringify({
              value:
                "<script>alert(1)</script><img src=https://tracker.example/x>",
            }),
          ),
        ),
    );
    expect(escaped.status).toBe("ready");
    if (escaped.status !== "ready") return;
    expect(escaped.rendered).not.toContain("<script>");
    expect(escaped.rendered).toContain("&lt;script&gt;");

    const broken = await assembleHtmlPage(
      pageJson("{{#open}}hi", { name: name.ref }),
      () => Promise.resolve(text(JSON.stringify({ value: "Ada" }))),
    );
    expect(broken.status).toBe("template");
    if (broken.status !== "template") return;
    expect(broken.message).toContain('Unclosed section "open"');
    expect(broken.template).toBe("{{#open}}hi");
    expect("rendered" in broken).toBe(false);
  });

  it("treats a truncated source as unread and does not keep the partial text", async () => {
    const baptisms = source("baptisms", "scalar.text");
    const loaded = await assembleHtmlPage(
      pageJson("{{baptisms}}", { baptisms: baptisms.ref }),
      () =>
        Promise.resolve({
          kind: "text",
          text: { kind: "truncated" },
        }),
    );
    expect(loaded).toEqual({
      status: "sources",
      template: "{{baptisms}}",
      sourceNames: ["baptisms"],
      failures: [{ name: "baptisms", message: "baptisms could not be read" }],
    });
  });

  it("keeps every source failure when one of them cannot be read", async () => {
    const baptisms = source("baptisms", "scalar.text");
    const burials = source("burials", "json.value");
    let started = 0;
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const pending = assembleHtmlPage(
      pageJson("{{baptisms}}{{burials}}", {
        baptisms: baptisms.ref,
        burials: burials.ref,
      }),
      async (item) => {
        started += 1;
        await gate;
        if (item.name === "baptisms") return { kind: "failed" };
        return text("not json {");
      },
    );
    await vi.waitFor(() => expect(started).toBe(2));
    release();
    const loaded = await pending;
    expect(loaded.status).toBe("sources");
    if (loaded.status !== "sources") return;
    expect(loaded.failures.map((failure) => failure.message)).toEqual([
      "baptisms could not be read",
      "burials could not be read",
    ]);
    expect(JSON.stringify(loaded)).not.toContain("not json");
  });

  it("says when a table's cells came back cut short", async () => {
    const years = source("years", "table.register");
    const loaded = await assembleHtmlPage(
      pageJson("{{#years}}{{year}}{{/years}}", { years: years.ref }),
      async () => ({
        kind: "table",
        page: {
          rows: [{ year: { display: "18", truncated: true } }],
          total_rows: 1,
        } as never,
      }),
    );
    if (loaded.status !== "ready") throw new Error(loaded.status);
    expect(loaded.shortfalls).toEqual(["some cells of years are cut short"]);
  });

  it("states a table shortfall from the rows in hand", () => {
    expect(tableShortfall("baptisms", 100, 1_204)).toBe(
      "showing 100 of 1,204 rows of baptisms",
    );
    expect(tableShortfall("baptisms", 4, 4)).toBeNull();
  });
});

describe("readWholeText", () => {
  it("returns the body when it fits, and no text when it does not", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response('{"value":"Ada"}')),
    );
    await expect(readWholeText("/artifact")).resolves.toEqual({
      kind: "text",
      text: '{"value":"Ada"}',
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("x".repeat(HTML_PAGE_BYTE_LIMIT + 8))),
    );
    await expect(readWholeText("/artifact")).resolves.toEqual({
      kind: "truncated",
    });
  });
});

describe("loadHtmlPage", () => {
  it("asks the table route for the first page at its row limit", async () => {
    const pageId = "page-1";
    const tableId = "table-1";
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        if (url.includes(`/artifacts/${pageId}/content`)) {
          return Response.json({
            html: "{{#baptisms}}{{year}}{{/baptisms}}",
            sources: {
              baptisms: {
                artifact_id: tableId,
                artifact_type: "table.data",
                schema_version: 1,
              },
            },
          });
        }
        if (url.includes("/table/schema")) {
          return Response.json({
            columns: [{ id: "year", title: "Year", value_type: "text" }],
            total_rows: 1_204,
          });
        }
        if (url.includes("/table/page")) {
          return Response.json(
            tablePage([{ year: { display: "1815", truncated: false } }], 1_204),
          );
        }
        return new Response("missing", { status: 404 });
      }),
    );

    const loaded = await loadHtmlPage("workspace-1", pageId);
    expect(loaded.status).toBe("ready");
    if (loaded.status !== "ready") return;
    expect(loaded.rendered).toBe("1815");
    expect(loaded.shortfalls).toEqual(["showing 1 of 1,204 rows of baptisms"]);
    const pageCall = calls.find((url) => url.includes("/table/page"));
    expect(pageCall).toContain("limit=100");
    expect(pageCall).toContain("column_ids=year");
    expect(HTML_PAGE_TABLE_ROW_LIMIT).toBe(100);
  });
});

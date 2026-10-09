import type { Locator, Page } from "@playwright/test";
import type {
  LibraryList,
  TablePage,
  TableSchema,
} from "../src/lib/api/contract";
import { libraryStub } from "./library-folders-stub";
import { expect, nodeRegistry, test } from "./workbench.fixture";

const artifact = {
  artifact_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  artifact_type: "table.data",
  schema_version: 1,
  content_type: "application/json",
};
const library: LibraryList = {
  items: [
    {
      artifact,
      name: "Field survey",
      provenance: {
        source: "upload",
        saved_at: "2026-10-07T12:00:00Z",
        original_filename: "Field survey",
      },
      run: null,
    },
  ],
};
const schema: TableSchema = {
  total_rows: 128,
  columns: [
    { id: "station", title: "Station", value_type: "text" },
    { id: "samples", title: "Samples", value_type: "integer" },
    { id: "verified", title: "Verified", value_type: "boolean" },
    { id: "notes", title: "Notes", value_type: "text" },
  ],
};
const fullNotes = "Coordinates and field observations. ".repeat(30);
const sinkSeed = nodeRegistry.nodes[1];
if (!sinkSeed) throw new Error("Test registry has no sink node");
const tableSink = {
  ...sinkSeed,
  operator_id: "test.table_sink",
  title: "Table analysis",
  inputs: sinkSeed.inputs.map((port) => ({
    ...port,
    name: "table",
    title: "Table",
    artifact_type: { id: "table.data", schema_version: 1 },
  })),
};
test.use({ registry: { ...nodeRegistry, nodes: [tableSink] } });

async function placeTable(page: Page) {
  const stub = await libraryStub(page);
  stub.artifacts(library);
  await page.route("**/artifacts/*/table/schema", (route) =>
    route.fulfill({ json: schema }),
  );
  await page.route("**/artifacts/*/table/page?*", (route) => {
    const query = new URL(route.request().url()).searchParams;
    const offset = Number(query.get("offset"));
    const limit = Number(query.get("limit"));
    const ids = query.getAll("column_ids");
    const columns = schema.columns.filter((col) => ids.includes(col.id));
    const page: TablePage = {
      columns,
      total_rows: 128,
      total_columns: 4,
      offset,
      limit,
      column_offset: 0,
      column_limit: 25,
      rows: Array.from(
        { length: Math.min(limit, 128 - offset) },
        (_, index) => ({
          station: {
            display: `Station ${offset + index + 1}`,
            truncated: false,
          },
          samples: { display: offset + index, truncated: false },
          verified: { display: index % 2 === 0, truncated: false },
          notes: { display: fullNotes.slice(0, 256), truncated: true },
        }),
      ),
    };
    return route.fulfill({ json: page });
  });
  await page.route("**/artifacts/*/table/cell?*", (route) =>
    route.fulfill({
      json: {
        row_index: 0,
        column_id: "notes",
        value_type: "text",
        value: fullNotes,
      },
    }),
  );
  await page.reload();
  await expect(page.locator(".react-flow")).toBeVisible();
  const artifacts = page
    .getByRole("navigation", { name: "Graphs" })
    .getByRole("button", { name: "Artifacts", exact: true });
  if ((await artifacts.getAttribute("aria-expanded")) === "false")
    await artifacts.click();
  await page
    .getByRole("treeitem")
    .filter({ hasText: "Field survey" })
    .dragTo(page.locator(".react-flow"), {
      targetPosition: { x: 360, y: 300 },
    });
  const card = page.locator("[data-artifact-card-id]");
  await expect(card.getByRole("table")).toBeVisible();
  await page.getByRole("button", { name: "Collapse side panel" }).click();
  const navigation = await page
    .getByRole("complementary", { name: "Primary navigation" })
    .boundingBox();
  const size = page.viewportSize();
  if (!navigation || !size) throw new Error("Canvas layout missing");
  await expect
    .poll(async () => (await page.locator(".react-flow").boundingBox())?.width)
    .toBeCloseTo(size.width - navigation.width, 0);
  await page.getByRole("button", { name: "Fit", exact: true }).click();
  await expect
    .poll(async () => (await center(card)).x)
    .toBeCloseTo((navigation.width + size.width) / 2, 0);
  return card;
}

async function center(locator: Locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error("Table control has no visible bounds");
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

test("canvas tables page, scroll and inspect cells without moving the canvas", async ({
  page,
  hasTouch,
}) => {
  test.skip(hasTouch, "Library drag and mouse wheel workflow");
  const card = await placeTable(page);
  const viewport = card.getByRole("region", { name: "Table preview" });
  const transform = await page
    .locator(".react-flow__viewport")
    .getAttribute("style");
  const point = await center(viewport);
  await page.mouse.move(point.x, point.y);
  await page.mouse.wheel(400, 220);
  await expect
    .poll(() => viewport.evaluate((el) => el.scrollTop))
    .toBeGreaterThan(0);
  await expect
    .poll(() => viewport.evaluate((el) => el.scrollLeft))
    .toBeGreaterThan(0);
  expect(
    await page.locator(".react-flow__viewport").getAttribute("style"),
  ).toBe(transform);
  const header = await card
    .getByRole("columnheader", { name: "#", exact: true })
    .boundingBox();
  const bounds = await viewport.boundingBox();
  if (!header || !bounds) throw new Error("Table header missing");
  expect(Math.abs(header.x - bounds.x)).toBeLessThan(2);
  expect(Math.abs(header.y - bounds.y)).toBeLessThan(2);

  await viewport.evaluate((el) => {
    el.scrollTop = 0;
  });
  const preview = card.locator("tbody tr").first().getByRole("button");
  await preview.click();
  const fullValue = card.getByRole("textbox", { name: "Full cell value" });
  await expect(fullValue).toHaveValue(fullNotes);
  await expect(fullValue).toBeFocused();
  // The value opens over the rows, with the room they had, instead of being
  // squeezed in below the pager.
  const detailRegion = card.getByRole("region", {
    name: "Full table cell value",
  });
  const rows = await viewport.boundingBox();
  const detail = await detailRegion.boundingBox();
  if (!rows || !detail) throw new Error("Full cell value missing");
  expect(Math.abs(detail.y - rows.y)).toBeLessThan(2);
  expect(detail.height).toBeGreaterThan(rows.height - 2);
  expect(await detailRegion.evaluate((el) => el.scrollTop)).toBe(0);
  await page.keyboard.press("Escape");
  await expect(fullValue).toHaveCount(0);
  await expect(preview).toBeFocused();
  await preview.click();
  await card.getByRole("button", { name: "Close full cell value" }).click();
  await expect(fullValue).toHaveCount(0);
  await card
    .getByRole("button", { name: "Choose visible table columns" })
    .click();
  await page.getByRole("checkbox", { name: "Verified boolean" }).uncheck();
  await page.keyboard.press("Escape");
  await expect(
    card.getByRole("columnheader", { name: "Verified boolean" }),
  ).toHaveCount(0);
  await viewport.evaluate((el) => {
    el.scrollTop = el.scrollHeight;
  });
  await card.getByRole("button", { name: "Next page" }).click();
  await expect(card).toContainText("51–100 of 128");
  await expect(card.locator("tbody tr").first()).toContainText("Station 51");
  // A new page opens at its first row, not where the last one was left.
  await expect.poll(() => viewport.evaluate((el) => el.scrollTop)).toBe(0);
  await card
    .getByRole("combobox", { name: "Rows per page" })
    .selectOption("25");
  await expect(card).toContainText("1–25 of 128");
  expect(
    await page.locator(".react-flow__viewport").getAttribute("style"),
  ).toBe(transform);
});

test("a resized canvas table connects to a node through a real pointer drag", async ({
  page,
  hasTouch,
}) => {
  test.skip(hasTouch, "Desktop pointer resize and port wiring");
  const card = await placeTable(page);
  await page.getByRole("button", { name: "Canvas lab", exact: true }).click();
  const lab = page.getByRole("complementary", { name: "Canvas lab" });
  await lab.getByText("Advanced", { exact: true }).click();
  await lab.getByRole("switch", { name: "Workflow corner resize" }).click();
  await lab.getByRole("button", { name: "Close canvas lab" }).click();
  const body = card.locator("[data-artifact-table-body]");
  const before = await body.boundingBox();
  if (!before) throw new Error("Table body missing");
  const resize = await center(
    card.getByRole("button", { name: "Resize artifact" }),
  );
  await page.mouse.move(resize.x, resize.y);
  await page.mouse.down();
  await page.mouse.move(resize.x + 80, resize.y + 70, { steps: 12 });
  await page.mouse.up();
  await expect
    .poll(async () => (await body.boundingBox())?.height ?? 0)
    .toBeGreaterThan(before.height + 40);
  await expect
    .poll(async () => (await body.boundingBox())?.width ?? 0)
    .toBeGreaterThan(before.width + 40);

  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 80 } });
  await expect(page.locator(".react-flow__node.selected")).toHaveCount(0);
  const tableHead = await center(card.locator("[data-artifact-head]"));
  await page.mouse.move(tableHead.x, tableHead.y);
  await page.mouse.down();
  await page.mouse.move(tableHead.x - 350, tableHead.y - 160, { steps: 12 });
  await page.mouse.up();
  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 80 } });

  await page.getByRole("button", { name: "Add node", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Search nodes" })
    .fill("Table analysis");
  await page.getByRole("option", { name: /^Table analysis/ }).click();
  await page
    .getByRole("button", { name: "Add to canvas", exact: true })
    .click();
  const target = page
    .locator(".react-flow__node")
    .filter({ hasText: "Table analysis" });
  const targetHeader = target.locator("header");
  const headerBounds = await targetHeader.boundingBox();
  if (!headerBounds) throw new Error("Target header missing");
  const targetHead = {
    x: headerBounds.x + headerBounds.width - 40,
    y: headerBounds.y + headerBounds.height / 2,
  };
  await targetHeader.click({
    trial: true,
    position: { x: headerBounds.width - 40, y: headerBounds.height / 2 },
  });
  await page.mouse.move(targetHead.x, targetHead.y);
  await page.mouse.down();
  await page.mouse.move(targetHead.x, targetHead.y + 260, { steps: 12 });
  await page.mouse.up();
  await page.getByRole("button", { name: "Fit", exact: true }).click();
  await page.locator(".react-flow__pane").click({ position: { x: 10, y: 80 } });
  await card.locator("[data-artifact-head]").click();
  const output = card.locator(".react-flow__handle.source");
  await output.click({ trial: true });
  const from = await center(output);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(from.x + 20, from.y + 20, { steps: 3 });
  await expect(page.locator(".react-flow__connection-path")).toBeVisible();
  const input = target.locator(".react-flow__handle.target");
  await expect(input).toBeVisible();
  await target.evaluate((element) =>
    Promise.all(
      element
        .getAnimations({ subtree: true })
        .map((animation) => animation.finished),
    ),
  );
  const to = await center(input);
  await page.mouse.move(to.x, to.y, { steps: 12 });
  await expect(input).toHaveClass(/valid/);
  await page.mouse.up();
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);
  const shrink = await center(
    card.getByRole("button", { name: "Resize artifact" }),
  );
  await page.mouse.move(shrink.x, shrink.y);
  await page.mouse.down();
  await page.mouse.move(shrink.x - 420, shrink.y - 120, { steps: 12 });
  await page.mouse.up();
  const narrowBounds = await body.boundingBox();
  if (!narrowBounds) throw new Error("Narrow table missing");
  for (const name of [
    "Choose visible table columns",
    "Next page",
    "Rows per page",
  ]) {
    const control = await card.locator(`[aria-label="${name}"]`).boundingBox();
    if (!control) throw new Error(`Table control missing: ${name}`);
    expect(control.x).toBeGreaterThanOrEqual(narrowBounds.x);
    expect(control.x + control.width).toBeLessThanOrEqual(
      narrowBounds.x + narrowBounds.width,
    );
    expect(control.y + control.height).toBeLessThanOrEqual(
      narrowBounds.y + narrowBounds.height,
    );
  }
  await expect(
    card.getByRole("columnheader", { name: "Station text" }),
  ).toBeVisible();
});

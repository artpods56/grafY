import { expect, test } from "./workbench.fixture";
import type { LibraryList, TemplateList } from "../src/lib/api/contract";
import type { Page } from "@playwright/test";

const DOCKED_MIN_WIDTH = 1100;
const AUTO_OPEN_MIN_WIDTH = 1280;

const panel = (page: Page) =>
  page.getByRole("complementary", { name: "Workbench side panel" });
const panelButton = (page: Page) =>
  page.getByRole("button", { name: "Artifacts and templates panel" });
const tree = (page: Page) =>
  panel(page).getByRole("tree", { name: "Workspace Library" });

const LIBRARY: LibraryList = {
  items: [
    {
      artifact: {
        artifact_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        artifact_type: "file.csv",
        schema_version: 1,
        content_type: "text/csv",
        byte_size: 1024,
      },
      name: "measurements.csv",
      provenance: {
        source: "upload",
        saved_at: "2026-09-17T12:00:00Z",
        original_filename: "measurements.csv",
      },
      run: null,
    },
  ],
};

const EMPTY_LIBRARY: LibraryList = { items: [] };

const TEMPLATES: TemplateList = {
  templates: [
    {
      id: "77777777-7777-4777-8777-777777777777",
      workspace_id: "11111111-1111-4111-8111-111111111111",
      source_graph_id: "88888888-8888-4888-8888-888888888888",
      source_revision: 3,
      source_graph_name: "Photo review",
      name: "Photo review starter",
      description: "Drop a folder of photos and run.",
      state: "active",
      node_count: 4,
      edge_count: 3,
      created_at: "2026-09-11T12:00:00Z",
      updated_at: "2026-09-17T12:00:00Z",
    },
  ],
};

function viewportWidth(page: Page): number {
  return page.viewportSize()?.width ?? 0;
}

/**
 * The Library folder tree lives in the browser until its routes land. Tests name
 * the folders they make after themselves, so they never collide with the tree
 * another test left in the same workspace.
 */
async function stubResponses(page: Page, library: LibraryList): Promise<void> {
  await page.route("**/api/v1/workspaces/*/library/artifacts", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: library })
      : route.fallback(),
  );
  await page.route("**/api/v1/workspaces/*/templates", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: TEMPLATES })
      : route.fallback(),
  );
  await page.reload();
  await expect(page.locator(".react-flow")).toBeVisible();
}

async function openPanel(page: Page): Promise<void> {
  if ((await panelButton(page).getAttribute("aria-pressed")) === "false") {
    await panelButton(page).click();
  }
  await expect(panel(page)).toBeVisible();
}

/** Makes a folder through the toolbar and names it in place. */
async function makeFolder(page: Page, name: string): Promise<void> {
  await panel(page).getByRole("button", { name: "New folder" }).click();
  const rename = panel(page).getByRole("textbox", { name: "Folder name" });
  await expect(rename).toBeVisible();
  await rename.fill(name);
  await rename.press("Enter");
  await expect(folderRow(page, name)).toBeVisible();
}

/** Drops a row on the panel background, which files it at the root. */
async function dragToRoot(page: Page, source: ReturnType<Page["locator"]>) {
  const region = panel(page).getByRole("region", {
    name: "Workspace Library files",
  });
  const box = await region.boundingBox();
  if (!box) throw new Error("No Library drop region");
  await source.dragTo(region, {
    targetPosition: { x: box.width - 8, y: box.height - 8 },
  });
}

function folderRow(page: Page, name: string) {
  return panel(page).locator(`[data-tree-key^="folder:"][data-tree-label="${name}"]`);
}

function folderActions(page: Page, name: string) {
  return panel(page).getByRole("button", { name: `Actions for ${name}` });
}

async function addNode(page: Page, title: string) {
  await page.getByRole("button", { name: "Add node", exact: true }).click();
  await page.getByRole("textbox", { name: "Search nodes" }).fill(title);
  await page.getByRole("option", { name: new RegExp(`^${title}`) }).click();
  await page.getByRole("button", { name: `Add ${title}`, exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const node = page.locator(".react-flow__node").filter({ hasText: title });
  await expect(node).toBeVisible();
  return node;
}

test("a wide canvas opens with the Artifacts panel docked beside it", async ({
  page,
}) => {
  test.skip(
    viewportWidth(page) < AUTO_OPEN_MIN_WIDTH,
    "Only a wide canvas auto-opens the panel",
  );

  const drawer = panel(page);
  await expect(drawer).toBeVisible();
  await expect(panelButton(page)).toHaveAttribute("aria-pressed", "true");
  await expect(drawer.getByRole("tab", { name: "Artifacts" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

test("the docked panel takes layout space from the canvas", async ({
  page,
}) => {
  test.skip(
    viewportWidth(page) < AUTO_OPEN_MIN_WIDTH,
    "Only a wide canvas auto-opens the panel",
  );

  const drawerBox = await panel(page).boundingBox();
  const canvasBox = await page.locator(".react-flow").boundingBox();
  expect(drawerBox?.x ?? -1).toBeGreaterThanOrEqual(200);
  expect(drawerBox?.width ?? 0).toBeGreaterThanOrEqual(360);
  expect(drawerBox?.width ?? 0).toBeLessThanOrEqual(420);
  // The canvas starts where the panel ends instead of hiding underneath it.
  expect(canvasBox?.x ?? 0).toBeCloseTo(
    (drawerBox?.x ?? 0) + (drawerBox?.width ?? 0),
    1,
  );
  expect(canvasBox?.width ?? 0).toBeGreaterThan(400);
});

test("the Panel rail button docks and undocks the panel", async ({ page }) => {
  test.skip(viewportWidth(page) < DOCKED_MIN_WIDTH, "Docked panel layout");

  await openPanel(page);
  const openCanvas = await page.locator(".react-flow").boundingBox();

  await panelButton(page).click();
  await expect(panel(page)).toHaveCount(0);
  const closedCanvas = await page.locator(".react-flow").boundingBox();
  expect((closedCanvas?.width ?? 0) - (openCanvas?.width ?? 0)).toBeGreaterThan(
    200,
  );

  await panelButton(page).click();
  await expect(panel(page)).toBeVisible();
});

test("a folder is made from the toolbar and sits at the root", async ({
  page,
}) => {
  test.skip(viewportWidth(page) < DOCKED_MIN_WIDTH, "Docked panel layout");

  await stubResponses(page, EMPTY_LIBRARY);
  await openPanel(page);

  await makeFolder(page, "Kestrel tray");
  await expect(folderRow(page, "Kestrel tray")).toHaveAttribute("aria-level", "1");
  await expect(panel(page)).toContainText(/\d+ folders?/);
});

test("Library artifacts sit at the root and open on the tile below", async ({
  page,
}) => {
  test.skip(viewportWidth(page) < DOCKED_MIN_WIDTH, "Docked panel layout");

  await stubResponses(page, LIBRARY);
  await openPanel(page);

  const file = tree(page).getByRole("treeitem", { name: /measurements\.csv/ });
  await expect(file).toBeVisible();
  await expect(file).toHaveAttribute("aria-level", "1");
  await expect(file).toHaveAttribute("draggable", "true");
  await expect(file).toContainText("1.0 KB · uploaded");

  await file.click();
  const tile = page.getByRole("complementary", { name: "Selected artifact" });
  await expect(tile).toContainText("uploaded · measurements.csv");
  await expect(tile).toContainText("/ · file.csv@1");
});

test("folders nest, and an artifact dragged into one moves with its depth", async ({
  page,
}) => {
  test.skip(viewportWidth(page) < DOCKED_MIN_WIDTH, "Docked panel layout");

  await stubResponses(page, LIBRARY);
  await openPanel(page);

  await makeFolder(page, "Kestrel tray");
  await folderActions(page, "Kestrel tray").click();
  await page.getByRole("menuitem", { name: "New subfolder" }).click();
  const rename = panel(page).getByRole("textbox", { name: "Folder name" });
  await rename.fill("Tray two");
  await rename.press("Enter");

  const child = folderRow(page, "Tray two");
  await expect(child).toHaveAttribute("aria-level", "2");

  await tree(page)
    .getByRole("treeitem", { name: /measurements\.csv/ })
    .dragTo(child);
  const moved = tree(page).getByRole("treeitem", { name: /measurements\.csv/ });
  await expect(moved).toHaveAttribute("aria-level", "3");
  // A folder's count is everything filed beneath it, however deeply.
  await expect(folderRow(page, "Kestrel tray")).toContainText("1");
  await expect(folderRow(page, "Tray two")).toContainText("1");
});

test("a folder refuses deletion until it is empty", async ({ page }) => {
  test.skip(viewportWidth(page) < DOCKED_MIN_WIDTH, "Docked panel layout");

  await stubResponses(page, LIBRARY);
  await openPanel(page);

  await makeFolder(page, "Cold store");
  await tree(page)
    .getByRole("treeitem", { name: /measurements\.csv/ })
    .dragTo(folderRow(page, "Cold store"));

  await folderActions(page, "Cold store").click();
  const deleteWithContents = page.getByRole("menuitem", {
    name: /Delete folder/,
  });
  await expect(deleteWithContents).toHaveAttribute("aria-disabled", "true");
  await expect(deleteWithContents).toContainText("empty it first");
  await page.keyboard.press("Escape");

  await dragToRoot(
    page,
    tree(page).getByRole("treeitem", { name: /measurements\.csv/ }),
  );
  await expect(
    tree(page).getByRole("treeitem", { name: /measurements\.csv/ }),
  ).toHaveAttribute("aria-level", "1");

  await folderActions(page, "Cold store").click();
  await page.getByRole("menuitem", { name: /^Delete folder/ }).click();
  await expect(
    tree(page).getByRole("treeitem", { name: "Cold store" }),
  ).toHaveCount(0);
});

test("the Templates tab lists graph templates", async ({ page }) => {
  test.skip(viewportWidth(page) < DOCKED_MIN_WIDTH, "Docked panel layout");

  await stubResponses(page, LIBRARY);
  await openPanel(page);

  await panel(page).getByRole("tab", { name: "Templates" }).click();

  await expect(
    panel(page).getByRole("list", { name: "Graph templates" }),
  ).toBeVisible();
  await expect(
    panel(page)
      .getByRole("listitem")
      .filter({ hasText: "Photo review starter" }),
  ).toContainText("4 nodes");
  await expect(
    panel(page).getByRole("button", { name: "New graph from Photo review starter" }),
  ).toBeVisible();
});

test("a Library artifact drag still lands on an input port", async ({
  page,
}) => {
  test.skip(viewportWidth(page) < DOCKED_MIN_WIDTH, "Docked panel layout");

  await stubResponses(page, LIBRARY);
  await openPanel(page);

  const sink = await addNode(page, "Test text sink");
  const port = sink.locator("[data-input-port-name='text']");
  await expect(port).toBeVisible();

  await page.evaluate(() => {
    const drops: { types: string[]; onPort: boolean }[] = [];
    (globalThis as unknown as { __grafyDrops: typeof drops }).__grafyDrops =
      drops;
    document.addEventListener(
      "drop",
      (event) => {
        const onPort = (() => {
          for (const element of document.elementsFromPoint(
            event.clientX,
            event.clientY,
          )) {
            if (!(element instanceof Element)) continue;
            if (element.closest("[data-base-ui-portal]")) continue;
            if (element.closest("[data-input-node-id]")) return true;
          }
          return false;
        })();
        drops.push({
          types: Array.from(event.dataTransfer?.types ?? []),
          onPort,
        });
      },
      true,
    );
  });

  const source = tree(page)
    .getByRole("treeitem")
    .filter({ hasText: "measurements.csv" });
  const from = await source.boundingBox();
  const to = await port.boundingBox();
  if (!from || !to) throw new Error("Drag points missing");
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, {
    steps: 20,
  });
  await page.mouse.up();

  const drops = await page.evaluate(
    () =>
      (
        globalThis as unknown as {
          __grafyDrops: { types: string[]; onPort: boolean }[];
        }
      ).__grafyDrops,
  );
  expect(
    drops.some(
      (drop) =>
        drop.types.includes("application/x-grafy-artifact") && drop.onPort,
    ),
  ).toBe(true);
});

test("a narrow canvas keeps the panel closed until it is asked for", async ({
  page,
}) => {
  test.skip(viewportWidth(page) >= DOCKED_MIN_WIDTH, "Narrow canvas layout");

  await expect(panel(page)).toHaveCount(0);
  await expect(panelButton(page)).toHaveAttribute("aria-pressed", "false");

  const beforeOpen = await page.locator(".react-flow").boundingBox();
  await panelButton(page).click();
  await expect(
    page.getByRole("tabpanel").getByRole("tree", { name: "Workspace Library" }),
  ).toBeVisible();

  // The slide-over covers the canvas rather than shrinking it.
  const afterOpen = await page.locator(".react-flow").boundingBox();
  expect(afterOpen?.x ?? -1).toBeCloseTo(beforeOpen?.x ?? -2, 1);
  expect(afterOpen?.width ?? -1).toBeCloseTo(beforeOpen?.width ?? -2, 1);

  await page.keyboard.press("Escape");
  await expect(panel(page)).toHaveCount(0);
});

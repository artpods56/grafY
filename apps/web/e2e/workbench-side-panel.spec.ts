import { expect, nodeRegistry, test } from "./workbench.fixture";
import type {
  LibraryList,
  NodeRegistry,
  RunExecution,
  TemplateList,
} from "../src/lib/api/contract";
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

const IMAGE_LIBRARY: LibraryList = {
  items: [
    {
      ...LIBRARY.items[0],
      artifact: {
        ...LIBRARY.items[0].artifact,
        artifact_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        artifact_type: "file.png",
        content_type: "image/svg+xml",
      },
      name: "coast.png",
      provenance: {
        ...LIBRARY.items[0].provenance,
        original_filename: "coast.png",
      },
    },
  ],
};

const SEQUENCE_LIBRARY: LibraryList = {
  items: [
    LIBRARY.items[0],
    {
      ...LIBRARY.items[0],
      artifact: {
        ...LIBRARY.items[0].artifact,
        artifact_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      },
      name: "forecast.csv",
      provenance: {
        ...LIBRARY.items[0].provenance,
        original_filename: "forecast.csv",
      },
    },
  ],
};

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
  return panel(page).locator(
    `[data-tree-key^="folder:"][data-tree-label="${name}"]`,
  );
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
  await expect(folderRow(page, "Kestrel tray")).toHaveAttribute(
    "aria-level",
    "1",
  );
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
    panel(page).getByRole("button", {
      name: "New graph from Photo review starter",
    }),
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

test("an artifact dragged out of the Library onto empty canvas lands on it", async ({
  page,
}) => {
  test.skip(viewportWidth(page) < DOCKED_MIN_WIDTH, "Docked panel layout");

  await stubResponses(page, LIBRARY);
  await openPanel(page);

  const source = tree(page)
    .getByRole("treeitem")
    .filter({ hasText: "measurements.csv" });
  await source.dragTo(page.locator(".react-flow"), {
    targetPosition: { x: 520, y: 420 },
  });

  const card = page.locator("[data-artifact-card-id]");
  await expect(card).toBeVisible();
  await expect(card).toContainText("measurements.csv");
  await expect(card.locator('[title="file.csv@1"]')).toBeVisible();
  await expect(card.locator("[data-artifact-media]")).toHaveCount(0);
  await expect(
    card.locator('[aria-label="Connect file.csv@1 to a node input"]'),
  ).toBeVisible();

  // Ports sit in the side rails, a small gap away from the file body.
  await expect
    .poll(async () =>
      card
        .locator("[data-artifact-frame]")
        .evaluate((element) => getComputedStyle(element).columnGap),
    )
    .toBe("8px");
  const body = card.locator("[data-artifact-file-body]");
  const input = card.locator(
    '[aria-label="Input port Artifact, accepts any artifact"]',
  );
  const output = card.locator(
    '[aria-label="Connect file.csv@1 to a node input"]',
  );
  const label = card.locator("[data-artifact-label]");
  const bodyBox = await body.boundingBox();
  const labelBox = await label.boundingBox();
  const inputBox = await input.boundingBox();
  const outputBox = await output.boundingBox();
  if (!bodyBox || !labelBox || !inputBox || !outputBox) {
    throw new Error("Artifact body or connection ball has no bounds");
  }
  // A file card rail is wide enough for the two action buttons side by side,
  // so every mark centres 24px from the body rather than the image card's 15.
  expect(bodyBox.x - (inputBox.x + inputBox.width)).toBeGreaterThan(4);
  expect(bodyBox.x - (inputBox.x + inputBox.width)).toBeLessThan(20);
  expect(Math.abs(inputBox.y - bodyBox.y)).toBeLessThan(8);
  expect(outputBox.x - (bodyBox.x + bodyBox.width)).toBeGreaterThan(4);
  expect(outputBox.x - (bodyBox.x + bodyBox.width)).toBeLessThan(16);
  expect(
    Math.abs(outputBox.y + outputBox.height - (bodyBox.y + bodyBox.height)),
  ).toBeLessThan(8);
  const outputPort = card.locator('[data-artifact-port-side="output"]');
  await expect(outputPort).toHaveText("");
  expect(
    await card
      .getByRole("button", { name: "Inspect file.csv@1 artifact" })
      .evaluate((element) => getComputedStyle(element).borderTopWidth),
  ).toBe("0px");
  await expect(card.locator("[data-node-pickup-shadow]")).toHaveCount(0);
  expect(
    await card.evaluate((element) => getComputedStyle(element).boxShadow),
  ).toBe("none");
  // The plate is the card's one shadow scope, and it lifts on selection the way
  // an image's media box does.
  await expect(
    card.locator(
      '[data-artifact-file-body][data-artifact-shadow-scope="file"]',
    ),
  ).toHaveCount(1);
  expect(
    await body.evaluate((element) => getComputedStyle(element).boxShadow),
  ).not.toBe("none");
  expect(labelBox.y + labelBox.height).toBeLessThanOrEqual(bodyBox.y + 1);
  const actions = card.getByRole("button", { name: "Actions for file.csv@1" });
  const inspect = card.getByRole("button", {
    name: "Inspect file.csv@1 artifact",
  });
  const actionBox = await inspect.boundingBox();
  const menuBox = await actions.boundingBox();
  if (!actionBox || !menuBox) throw new Error("Actions missing");
  expect(actionBox.x - (bodyBox.x + bodyBox.width)).toBeGreaterThan(4);
  expect(actionBox.x - (bodyBox.x + bodyBox.width)).toBeLessThan(26);
  expect(Math.abs(actionBox.y - bodyBox.y)).toBeLessThan(8);
  // The rail holds one centreline. A short file card lays the two buttons side
  // by side, so the pair straddles it evenly instead of each sitting on it.
  const csvOutputCentreX = outputBox.x + outputBox.width / 2;
  const chromeBox = await card.locator("[data-artifact-chrome]").boundingBox();
  if (!chromeBox) throw new Error("Action chrome has no bounds");
  expect(
    Math.abs(chromeBox.x + chromeBox.width / 2 - csvOutputCentreX),
  ).toBeLessThan(1);
  expect(
    Math.abs(actionBox.x + actionBox.width / 2 - csvOutputCentreX),
  ).toBeCloseTo(
    Math.abs(csvOutputCentreX - (menuBox.x + menuBox.width / 2)),
    0,
  );
  const flow = await page.locator(".react-flow").boundingBox();
  if (!flow) throw new Error("No canvas box");
  await page.mouse.click(flow.x + flow.width - 40, flow.y + flow.height - 40);

  await expect(actions).toBeHidden();
  await expect(card.locator('[data-artifact-ports="off"]')).toHaveCount(2);
  await expect
    .poll(() => body.evaluate((element) => getComputedStyle(element).boxShadow))
    .toBe("none");
  await card.click();
  await expect(actions).toBeVisible();
  await expect(card.locator('[data-artifact-ports="on"]')).toHaveCount(2);
  await expect
    .poll(() => body.evaluate((element) => getComputedStyle(element).boxShadow))
    .not.toBe("none");
});

test("an image keeps dimmed metadata above its pixels and external controls reachable", async ({
  page,
}) => {
  test.skip(viewportWidth(page) < DOCKED_MIN_WIDTH, "Docked panel layout");

  await page.route("**/api/v1/workspaces/*/artifacts/*/content", (route) =>
    route.fulfill({
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><defs><linearGradient id="sky" x2="0" y2="1"><stop stop-color="#1d476a"/><stop offset="1" stop-color="#efae78"/></linearGradient></defs><path fill="url(#sky)" d="M0 0h640v360H0z"/><path fill="#164954" d="M0 240q130-80 240-30t400-20v170H0z"/><path fill="#72b5ba" d="M0 280q200-25 340 20t300-30v90H0z"/></svg>',
    }),
  );
  await stubResponses(page, IMAGE_LIBRARY);
  await openPanel(page);
  await tree(page)
    .getByRole("treeitem")
    .filter({ hasText: "coast.png" })
    .dragTo(page.locator(".react-flow"), {
      targetPosition: { x: 520, y: 420 },
    });

  const card = page.locator("[data-artifact-card-id]");
  const image = card.locator("[data-artifact-media] img");
  await expect(image).toBeVisible();
  await expect
    .poll(() =>
      image.evaluate((element: HTMLImageElement) => element.naturalWidth),
    )
    .toBe(640);
  const flow = await page.locator(".react-flow").boundingBox();
  if (!flow) throw new Error("No canvas box");
  await page.mouse.click(flow.x + flow.width - 40, flow.y + flow.height - 40);

  const actions = card.getByRole("button", { name: "Actions for file.png@1" });
  await expect(actions).toBeHidden();
  await expect(card.locator('[data-artifact-ports="off"]')).toHaveCount(2);

  const header = card.locator("[data-artifact-image-header]");
  await expect(header).toContainText("coast.png");
  await expect(header).toContainText("file.png@1");
  await expect
    .poll(() =>
      header.evaluate((element) => Number(getComputedStyle(element).opacity)),
    )
    .toBeLessThan(1);
  const media = card.locator("[data-artifact-media]");
  const headerBox = await header.boundingBox();
  const mediaBox = await media.boundingBox();
  if (!headerBox || !mediaBox)
    throw new Error("Image or metadata bounds missing");
  expect(headerBox.y + headerBox.height).toBeLessThanOrEqual(mediaBox.y + 1);
  expect(mediaBox.width / mediaBox.height).toBeCloseTo(640 / 360, 1);
  expect(
    await header.evaluate(
      (element) => getComputedStyle(element).backdropFilter,
    ),
  ).toBe("none");

  await media.click();
  await expect
    .poll(() => header.evaluate((element) => getComputedStyle(element).opacity))
    .toBe("1");
  await expect(actions).toBeVisible();
  await expect(card.locator('[data-artifact-ports="on"]')).toHaveCount(2);
  await expect
    .poll(async () =>
      card
        .locator("[data-artifact-frame]")
        .evaluate((element) => getComputedStyle(element).columnGap),
    )
    .toBe("8px");
  const pickedMedia = await media.boundingBox();
  const actionBox = await card
    .getByRole("button", { name: "Inspect file.png@1 artifact" })
    .boundingBox();
  const inputBox = await card
    .locator('[aria-label="Input port Artifact, accepts any artifact"]')
    .boundingBox();
  const outputBox = await card
    .locator('[aria-label="Connect file.png@1 to a node input"]')
    .boundingBox();
  if (!pickedMedia || !actionBox || !inputBox || !outputBox) {
    throw new Error("Image chrome has no bounds");
  }
  expect(actionBox.x - (pickedMedia.x + pickedMedia.width)).toBeGreaterThan(4);
  expect(actionBox.x - (pickedMedia.x + pickedMedia.width)).toBeLessThan(16);
  expect(Math.abs(actionBox.y - pickedMedia.y)).toBeLessThan(8);
  expect(pickedMedia.x - (inputBox.x + inputBox.width)).toBeGreaterThan(4);
  expect(pickedMedia.x - (inputBox.x + inputBox.width)).toBeLessThan(16);
  expect(Math.abs(inputBox.y - pickedMedia.y)).toBeLessThan(8);
  expect(outputBox.x - (pickedMedia.x + pickedMedia.width)).toBeGreaterThan(4);
  expect(outputBox.x - (pickedMedia.x + pickedMedia.width)).toBeLessThan(16);
  expect(
    Math.abs(
      outputBox.y + outputBox.height - (pickedMedia.y + pickedMedia.height),
    ),
  ).toBeLessThan(8);
  // Both rails are a single column: the action buttons and the output ball
  // share one centreline, so the chrome reads as part of the rail.
  const moreBox = await actions.boundingBox();
  if (!moreBox) throw new Error("Action menu has no bounds");
  const outputCentreX = outputBox.x + outputBox.width / 2;
  expect(
    Math.abs(actionBox.x + actionBox.width / 2 - outputCentreX),
  ).toBeLessThan(1);
  expect(Math.abs(moreBox.x + moreBox.width / 2 - outputCentreX)).toBeLessThan(
    1,
  );
  expect(
    Math.abs(
      actionBox.y + actionBox.height / 2 - (inputBox.y + inputBox.height / 2),
    ),
  ).toBeLessThan(1);
  const outputPort = card.locator('[data-artifact-port-side="output"]');
  const width = (await outputPort.boundingBox())?.width;
  await outputPort.hover();
  expect((await outputPort.boundingBox())?.width).toBe(width);
  await card
    .getByRole("button", { name: "Inspect file.png@1 artifact" })
    .click();
  await expect(page.getByText("1.0 KB · 640 × 360")).toBeVisible();
  await expect(
    page.getByText("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
  ).toBeVisible();
});

test("Collect replaces selected artifacts and Ungroup restores them in sequence order", async ({
  page,
}) => {
  test.skip(viewportWidth(page) < DOCKED_MIN_WIDTH, "Docked panel layout");

  await stubResponses(page, SEQUENCE_LIBRARY);
  await openPanel(page);
  const canvas = page.locator(".react-flow");
  await tree(page)
    .getByRole("treeitem")
    .filter({ hasText: "measurements.csv" })
    .dragTo(canvas, { targetPosition: { x: 250, y: 270 } });
  await tree(page)
    .getByRole("treeitem")
    .filter({ hasText: "forecast.csv" })
    .dragTo(canvas, { targetPosition: { x: 580, y: 270 } });

  const cards = page.locator("[data-artifact-card-id]");
  await expect(cards).toHaveCount(2);
  const first = await cards.nth(0).boundingBox();
  const second = await cards.nth(1).boundingBox();
  if (!first || !second) throw new Error("Artifact cards have no bounds");
  const start = {
    x: Math.min(first.x, second.x) - 22,
    y: Math.min(first.y, second.y) - 22,
  };
  const end = {
    x: Math.max(first.x + first.width, second.x + second.width) + 22,
    y: Math.max(first.y + first.height, second.y + second.height) + 22,
  };
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(end.x, end.y, { steps: 12 });
  await page.mouse.up();

  await expect(page.locator(".react-flow__node.selected")).toHaveCount(2);
  await page.getByRole("button", { name: "Collect", exact: true }).click();
  await expect(cards).toHaveCount(1);
  await expect(cards).toContainText("Sequence<file.csv@1>");
  await expect(cards.getByLabel("2 items in sequence")).toBeVisible();
  await cards.getByRole("button", { name: "Rearrange", exact: true }).click();
  const sequenceRows = cards
    .getByRole("list", { name: "Sequence order" })
    .getByRole("listitem");
  const initiallyFirst = (await sequenceRows.nth(0).innerText()).match(
    /(?:forecast|measurements)\.csv/,
  )?.[0];
  const initiallySecond = (await sequenceRows.nth(1).innerText()).match(
    /(?:forecast|measurements)\.csv/,
  )?.[0];
  if (!initiallyFirst || !initiallySecond)
    throw new Error("Sequence filenames missing");
  await cards
    .getByRole("button", { name: "Move later in the order" })
    .first()
    .click();
  await expect(sequenceRows.nth(0)).toContainText(initiallySecond);
  await cards.getByRole("button", { name: "Close sequence order" }).click();
  await cards.getByRole("button", { name: "Ungroup", exact: true }).click();
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(0)).toContainText(initiallySecond);
  await expect(cards.nth(1)).toContainText(initiallyFirst);
  await page.getByRole("button", { name: "Tidy-up", exact: true }).click();
  const restoredFirst = await cards.nth(0).boundingBox();
  const restoredSecond = await cards.nth(1).boundingBox();
  if (!restoredFirst || !restoredSecond)
    throw new Error("Restored artifacts missing");
  expect(restoredFirst.x + restoredFirst.width).toBeLessThan(restoredSecond.x);
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

test.describe("artifact wiring", () => {
  test.use({
    registry: {
      ...nodeRegistry,
      nodes: [
        ...nodeRegistry.nodes,
        {
          operator_id: "test.csv_source",
          operator_version: 1,
          plugin_slug: "builtin",
          origin: "builtin",
          title: "CSV source",
          description: "Produces a CSV artifact.",
          catalog_visible: true,
          runnable: true,
          config_schema: {},
          input_schema: {},
          output_schema: {},
          inputs: [],
          outputs: [
            {
              name: "file",
              title: "File",
              description: "Produced CSV file",
              direction: "output",
              artifact_type: { id: "file.csv", schema_version: 1 },
              artifact_type_variable: null,
              shape: "one",
              accepted_shapes: ["one"],
              instance_plugs: false,
              variadic: false,
              required: true,
            },
          ],
        },
        {
          operator_id: "test.csv_sink",
          operator_version: 1,
          plugin_slug: "builtin",
          origin: "builtin",
          title: "CSV sink",
          description: "Accepts a CSV artifact.",
          catalog_visible: true,
          runnable: true,
          config_schema: {},
          input_schema: {},
          output_schema: {},
          inputs: [
            {
              name: "file",
              title: "File",
              description: "CSV input",
              direction: "input",
              artifact_type: { id: "file.csv", schema_version: 1 },
              artifact_type_variable: null,
              shape: "one",
              accepted_shapes: ["one"],
              instance_plugs: false,
              variadic: false,
              required: true,
            },
          ],
          outputs: [],
        },
      ],
    } satisfies NodeRegistry,
  });

  test("the detached output ball wires to a node through a real drag", async ({
    page,
  }) => {
    test.skip(viewportWidth(page) < DOCKED_MIN_WIDTH, "Docked panel layout");

    await stubResponses(page, LIBRARY);
    await openPanel(page);
    const sink = await addNode(page, "CSV sink");
    const header = await sink.locator("header").boundingBox();
    if (!header) throw new Error("CSV sink header has no bounds");
    await page.mouse.move(
      header.x + header.width / 2,
      header.y + header.height / 2,
    );
    await page.mouse.down();
    await page.mouse.move(
      header.x + header.width / 2 + 340,
      header.y + header.height / 2 + 150,
      { steps: 12 },
    );
    await page.mouse.up();

    await tree(page)
      .getByRole("treeitem")
      .filter({ hasText: "measurements.csv" })
      .dragTo(page.locator(".react-flow"), {
        targetPosition: { x: 250, y: 270 },
      });
    const card = page.locator("[data-artifact-card-id]");
    await expect(card).toBeVisible();
    await page.getByRole("button", { name: "Fit", exact: true }).click();

    const source = card.locator(".react-flow__handle.source");
    const target = sink.locator(".react-flow__handle.target");
    await source.click({ trial: true });
    await target.click({ trial: true });
    const from = await source.boundingBox();
    const to = await target.boundingBox();
    if (!from || !to) throw new Error("Artifact connection ball has no bounds");
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
    await page.mouse.down();
    await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, {
      steps: 12,
    });
    await page.mouse.up();

    await expect(page.locator(".react-flow__edge")).toHaveCount(1);
  });

  test("a completed output dragged onto blank canvas becomes an artifact", async ({
    page,
  }) => {
    test.skip(viewportWidth(page) < DOCKED_MIN_WIDTH, "Docked panel layout");

    const source = await addNode(page, "CSV source");
    const nodeId = await source.getAttribute("data-id");
    if (!nodeId) throw new Error("CSV source has no node ID");
    const artifact = LIBRARY.items[0].artifact;
    const completedRun = {
      execution_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      status: "succeeded",
      active_node_id: null,
      error: null,
      result: {
        status: "succeeded",
        node_runs: [
          {
            node_id: nodeId,
            status: "succeeded",
            error: null,
            outputs: [
              {
                port: "file",
                kind: "single",
                value: {
                  artifact_id: artifact.artifact_id,
                  artifact_type: artifact.artifact_type,
                  schema_version: artifact.schema_version,
                },
                artifacts: [artifact],
              },
            ],
          },
        ],
      },
    } satisfies RunExecution;
    await page.route("**/api/v1/workspaces/*/executions", (route) =>
      route.request().method() === "POST"
        ? route.fulfill({ json: completedRun })
        : route.fallback(),
    );
    await page.route("**/api/v1/workspaces/*/executions/*/events", (route) =>
      route.fulfill({ contentType: "text/event-stream", body: "" }),
    );

    await page.getByRole("button", { name: "Run", exact: true }).click();
    await expect(page.locator("main > span[role='status']")).toHaveText(
      "Execution completed successfully.",
    );

    const output = source.locator(".react-flow__handle.source");
    await output.click({ trial: true });
    const from = await output.boundingBox();
    const canvas = await page.locator(".react-flow").boundingBox();
    if (!from || !canvas) throw new Error("Output or canvas has no bounds");
    const to = {
      x: Math.min(from.x + from.width / 2 + 260, canvas.x + canvas.width - 80),
      y: Math.min(
        from.y + from.height / 2 + 140,
        canvas.y + canvas.height - 80,
      ),
    };
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
    await page.mouse.down();
    await page.mouse.move(to.x, to.y, { steps: 14 });
    await page.mouse.up();

    const card = page.locator("[data-artifact-card-id]");
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute("aria-label", "Artifact file.csv@1");
    await expect(card).toContainText("CSV source → File");
    await expect(card.locator("[data-artifact-content]")).toBeVisible();
    await expect(page.locator(".react-flow__edge")).toHaveCount(1);
  });
});

test("image resizing and a two-image stack preserve image geometry", async ({
  page,
}, testInfo) => {
  test.skip(viewportWidth(page) < DOCKED_MIN_WIDTH, "Docked panel layout");
  await page.route("**/api/v1/workspaces/*/artifacts/*/content", (route) =>
    route.fulfill({
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><path fill="#91b9ca" d="M0 0h640v360H0z"/><path fill="#34635f" d="M0 360 180 90 400 360z"/><path fill="#66938a" d="m250 360 190-180 200 180z"/></svg>',
    }),
  );
  const original = IMAGE_LIBRARY.items[0];
  await stubResponses(page, {
    items: [
      original,
      {
        ...original,
        name: "ridge.png",
        artifact: {
          ...original.artifact,
          artifact_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        },
        provenance: { ...original.provenance, original_filename: "ridge.png" },
      },
    ],
  });
  await openPanel(page);
  await tree(page)
    .getByRole("treeitem")
    .filter({ hasText: "coast.png" })
    .dragTo(page.locator(".react-flow"), {
      targetPosition: { x: 240, y: 320 },
    });
  const cards = page.locator("[data-artifact-card-id]");
  const image = cards.locator("[data-artifact-media] img");
  await expect
    .poll(() =>
      image.evaluate((element: HTMLImageElement) => element.naturalWidth),
    )
    .toBe(640);
  const before = await image.boundingBox();
  if (!before) throw new Error("Image missing");
  await page.getByRole("button", { name: "Canvas lab", exact: true }).click();
  const lab = page.getByRole("complementary", { name: "Canvas lab" });
  await lab.getByText("Advanced", { exact: true }).click();
  await lab.getByRole("switch", { name: "Workflow corner resize" }).click();
  await lab.getByRole("button", { name: "Close canvas lab" }).click();
  const resize = await cards
    .getByRole("button", { name: "Resize artifact" })
    .boundingBox();
  if (!resize) throw new Error("Resize handle missing");
  await page.mouse.move(
    resize.x + resize.width / 2,
    resize.y + resize.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    resize.x + resize.width / 2 + 90,
    resize.y + resize.height / 2 + 50,
    { steps: 12 },
  );
  await page.mouse.up();
  await expect
    .poll(async () => (await image.boundingBox())?.width ?? 0)
    .toBeGreaterThan(before.width + 40);
  const resized = await image.boundingBox();
  if (!resized) throw new Error("Resized image missing");
  expect(resized.width / resized.height).toBeCloseTo(640 / 360, 1);

  await tree(page)
    .getByRole("treeitem")
    .filter({ hasText: "ridge.png" })
    .dragTo(page.locator(".react-flow"), {
      targetPosition: { x: 610, y: 320 },
    });
  const first = await cards.nth(0).boundingBox();
  const second = await cards.nth(1).boundingBox();
  if (!first || !second) throw new Error("Images missing");
  await page.mouse.move(
    Math.min(first.x, second.x) - 25,
    Math.min(first.y, second.y) - 25,
  );
  await page.mouse.down();
  await page.mouse.move(
    Math.max(first.x + first.width, second.x + second.width) + 45,
    Math.max(first.y + first.height, second.y + second.height) + 25,
    { steps: 12 },
  );
  await page.mouse.up();
  await page.getByRole("button", { name: "Collect", exact: true }).click();
  await expect(cards).toHaveCount(1);
  await expect(cards).toContainText("2 items");
  await expect(cards).toContainText("Sequence<file.png@1>");
  const layers = cards.locator("[data-artifact-media]");
  await expect(layers).toHaveCount(2);
  const front = await layers.nth(0).boundingBox();
  const back = await layers.nth(1).boundingBox();
  const stack = await cards.boundingBox();
  if (!front || !back || !stack) throw new Error("Stack geometry missing");
  expect(front.x).toBeGreaterThan(back.x);
  expect(front.y).toBeLessThan(back.y);
  expect(front.x + front.width).toBeCloseTo(stack.x + stack.width, 0);
  expect(front.width / front.height).toBeCloseTo(640 / 360, 1);
  await page.screenshot({
    path: testInfo.outputPath("image-artifact-stack.png"),
  });
  await cards.getByRole("button", { name: "Ungroup", exact: true }).click();
  await expect(cards).toHaveCount(2);
  await expect(cards.filter({ hasText: "coast.png" })).toBeVisible();
  await expect(cards.filter({ hasText: "ridge.png" })).toBeVisible();
});

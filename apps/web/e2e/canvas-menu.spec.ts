import { expect, test } from "./workbench.fixture";
import type { Locator, Page } from "@playwright/test";

/**
 * The canvas right-click menu. It opens where the right button is released,
 * but only when it did not move: a right drag still pans the canvas.
 */

const menu = (page: Page) => page.getByRole("menu", { name: "Canvas menu" });

function viewportWidth(page: Page): number {
  return page.viewportSize()?.width ?? 0;
}

async function paneBox(page: Page) {
  await expect(page.locator(".react-flow")).toBeVisible();
  const box = await page.locator(".react-flow__pane").boundingBox();
  if (!box) throw new Error("No canvas pane");
  return box;
}

async function addFromMenu(
  page: Page,
  at: { x: number; y: number },
  title: string,
): Promise<Locator> {
  await page.mouse.click(at.x, at.y, { button: "right" });
  await menu(page).getByRole("menuitem", { name: "Add node" }).hover();
  await page.getByRole("menuitem", { name: "Built-in" }).hover();
  await page.getByRole("menuitem", { name: title, exact: true }).click();
  await expect(menu(page)).toBeHidden();
  const node = page.locator(".react-flow__node").filter({ hasText: title });
  await expect(node).toBeVisible();
  return node;
}

const mouseOnly = (page: Page) =>
  test.skip(viewportWidth(page) < 1024, "A mouse's right button");

test("the toolbar and canvas menu omit the deprecated Artifact Viewer", async ({
  page,
}) => {
  mouseOnly(page);
  const box = await paneBox(page);
  await expect(
    page.getByRole("button", { name: "Add Artifact Viewer", exact: true }),
  ).toHaveCount(0);
  await page.mouse.click(box.x + 80, box.y + 100, { button: "right" });
  await expect(menu(page)).toBeVisible();
  await expect(
    menu(page).getByRole("menuitem", { name: "Artifact viewer", exact: true }),
  ).toHaveCount(0);
  await expect(
    menu(page).getByRole("menuitem", { name: "Add node", exact: true }),
  ).toBeVisible();
});

test("a right click on the canvas adds a node where it was made", async ({
  page,
}) => {
  mouseOnly(page);
  const box = await paneBox(page);
  // The first node on an empty canvas is framed by the initial fit view, so
  // placement is measured on the second.
  await addFromMenu(
    page,
    { x: box.x + box.width * 0.3, y: box.y + 140 },
    "Test text source",
  );
  // Clear of the first node, which the fit view put mid-canvas.
  const at = { x: box.x + 60, y: box.y + box.height - 280 };
  const sink = await addFromMenu(page, at, "Test text sink");

  const placed = await sink.boundingBox();
  // The plate's corner sits at the click; the box also holds the name row
  // above it and the port balls to its left.
  expect(Math.abs((placed?.x ?? 0) - at.x)).toBeLessThan(40);
  expect(Math.abs((placed?.y ?? 0) - at.y)).toBeLessThan(40);
});

test("a right drag pans the canvas and opens nothing", async ({ page }) => {
  mouseOnly(page);
  const box = await paneBox(page);
  const node = await addFromMenu(
    page,
    { x: box.x + box.width * 0.4, y: box.y + 160 },
    "Test text source",
  );
  const before = await node.boundingBox();

  await page.mouse.move(box.x + 120, box.y + box.height - 220);
  await page.mouse.down({ button: "right" });
  await page.mouse.move(box.x + 200, box.y + box.height - 170, { steps: 8 });
  await page.mouse.up({ button: "right" });

  await expect(menu(page)).toHaveCount(0);
  const after = await node.boundingBox();
  expect((after?.x ?? 0) - (before?.x ?? 0)).toBeGreaterThan(40);
});

test("a node's menu acts on it, and a selection's on all of it", async ({
  page,
}) => {
  mouseOnly(page);
  const box = await paneBox(page);
  const source = await addFromMenu(
    page,
    { x: box.x + box.width * 0.3, y: box.y + 140 },
    "Test text source",
  );
  await addFromMenu(
    page,
    { x: box.x + 60, y: box.y + box.height - 280 },
    "Test text sink",
  );

  // A right click on a node's name opens on that node.
  const header = source.locator("header").first();
  const headerBox = await header.boundingBox();
  if (!headerBox) throw new Error("No node header");
  await page.mouse.click(headerBox.x + 12, headerBox.y + headerBox.height / 2, {
    button: "right",
  });
  await expect(menu(page)).toContainText("Test text source");
  await expect(
    menu(page).getByRole("menuitem", { name: "Duplicate" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menu(page)).toBeHidden();

  await page.mouse.click(box.x + box.width - 80, box.y + 90, {
    button: "right",
  });
  await menu(page).getByRole("menuitem", { name: "Select all" }).click();
  await page.mouse.click(headerBox.x + 12, headerBox.y + headerBox.height / 2, {
    button: "right",
  });
  await expect(menu(page)).toContainText("2 nodes selected");
  await menu(page).getByRole("menuitem", { name: "Delete 2 nodes" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(0);
});

test("a long press opens the menu on touch", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.use.hasTouch, "Touch screens");
  const box = await paneBox(page);
  const client = await page.context().newCDPSession(page);
  const point = { x: box.x + box.width / 2, y: box.y + box.height / 2 };

  await client.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [point],
  });
  await page.waitForTimeout(650);
  await client.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });

  // It opens on the lift and the lift's own tap does not close it.
  await expect(menu(page)).toBeVisible();
  await page.waitForTimeout(300);
  await expect(menu(page)).toBeVisible();
  await menu(page).getByRole("menuitem", { name: "Fit view" }).tap();
  await expect(menu(page)).toBeHidden();
});

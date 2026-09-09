import type { CDPSession, Locator, Page } from "@playwright/test";

import { expect, test } from "./workbench.fixture";

async function viewportTransform(page: Page) {
  return page.locator(".react-flow__viewport").evaluate((element) => {
    const transform = new DOMMatrixReadOnly(getComputedStyle(element).transform);
    return { x: transform.e, y: transform.f, zoom: transform.a };
  });
}

async function touch(
  page: Page,
  client: CDPSession,
  type: "touchStart" | "touchMove" | "touchEnd" | "touchCancel",
  points: { x: number; y: number; id: number }[],
) {
  await client.send("Input.dispatchTouchEvent", { type, touchPoints: points });
  await expect(page.locator(".react-flow__selection")).toHaveCount(0);
}

async function addNode(page: Page, title: string, hasTouch: boolean) {
  const open = page.getByRole("button", { name: "Add node", exact: true });
  if (hasTouch) await open.tap();
  else await open.click();
  await page.getByRole("textbox", { name: "Search nodes" }).fill(title);
  const option = page.getByRole("option", { name: new RegExp(`^${title}`) });
  if (hasTouch) await option.tap();
  else await option.click();
  const add = page.getByRole("button", { name: `Add ${title}`, exact: true });
  if (hasTouch) await add.tap();
  else await add.click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const node = page.locator(".react-flow__node").filter({ hasText: title });
  await expect(node).toBeVisible();
  return node;
}

async function center(locator: Locator) {
  const bounds = await locator.boundingBox();
  if (!bounds) throw new Error(`Canvas element has no visible bounds: ${locator}`);
  return { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 };
}

test("one finger pans without starting a selection", async ({ page, hasTouch }) => {
  test.skip(!hasTouch, "Requires a touch-enabled browser");
  const client = await page.context().newCDPSession(page);
  const point = await center(page.locator(".react-flow__pane"));
  const before = await viewportTransform(page);

  await touch(page, client, "touchStart", [{ ...point, id: 1 }]);
  for (const distance of [20, 40, 60, 80]) {
    await touch(page, client, "touchMove", [{ x: point.x + distance, y: point.y + distance, id: 1 }]);
    await expect(page.locator(".react-flow__selection")).toHaveCount(0);
  }
  await touch(page, client, "touchEnd", []);

  await expect.poll(() => viewportTransform(page)).toMatchObject({ zoom: before.zoom });
  const after = await viewportTransform(page);
  expect(after.x - before.x).toBeGreaterThan(50);
  expect(after.y - before.y).toBeGreaterThan(50);
  await expect(page.locator(".react-flow__selection")).toHaveCount(0);
});

test("a pan can become a pinch and return to one finger", async ({ page, hasTouch }) => {
  test.skip(!hasTouch, "Requires a touch-enabled browser");
  const client = await page.context().newCDPSession(page);
  const point = await center(page.locator(".react-flow__pane"));
  const before = await viewportTransform(page);

  await touch(page, client, "touchStart", [{ x: point.x - 40, y: point.y, id: 1 }]);
  await touch(page, client, "touchMove", [{ x: point.x - 30, y: point.y + 10, id: 1 }]);
  await touch(page, client, "touchStart", [
    { x: point.x - 30, y: point.y + 10, id: 1 },
    { x: point.x + 30, y: point.y + 10, id: 2 },
  ]);
  for (const distance of [40, 50, 60]) {
    await touch(page, client, "touchMove", [
      { x: point.x - distance, y: point.y + 10, id: 1 },
      { x: point.x + distance, y: point.y + 10, id: 2 },
    ]);
    await expect(page.locator(".react-flow__selection")).toHaveCount(0);
  }
  await expect.poll(async () => (await viewportTransform(page)).zoom).toBeGreaterThan(before.zoom + 0.1);
  expect(await page.evaluate(() => window.visualViewport?.scale)).toBe(1);

  // A targeted CDP touchEnd releases finger 2 while finger 1 stays down.
  await touch(page, client, "touchEnd", [{ x: point.x + 60, y: point.y + 10, id: 2 }]);
  const afterPinch = await viewportTransform(page);
  await touch(page, client, "touchMove", [{ x: point.x - 30, y: point.y + 40, id: 1 }]);
  await touch(page, client, "touchEnd", []);
  const afterPan = await viewportTransform(page);
  expect(afterPan.x - afterPinch.x).toBeGreaterThan(20);
  expect(afterPan.zoom).toBeCloseTo(afterPinch.zoom);
  await expect(page.locator(".react-flow__selection")).toHaveCount(0);
});

test("cancelling a touch gesture leaves the next drag usable", async ({ page, hasTouch }) => {
  test.skip(!hasTouch, "Requires a touch-enabled browser");
  const client = await page.context().newCDPSession(page);
  const point = await center(page.locator(".react-flow__pane"));
  await touch(page, client, "touchStart", [{ ...point, id: 1 }]);
  await touch(page, client, "touchMove", [{ x: point.x + 30, y: point.y, id: 1 }]);
  await touch(page, client, "touchCancel", []);
  await expect(page.locator(".react-flow__selection")).toHaveCount(0);

  const before = await viewportTransform(page);
  await touch(page, client, "touchStart", [{ ...point, id: 2 }]);
  await touch(page, client, "touchMove", [{ x: point.x + 60, y: point.y, id: 2 }]);
  await touch(page, client, "touchEnd", []);
  const after = await viewportTransform(page);
  expect(after.x - before.x).toBeGreaterThan(30);
  await expect(page.locator(".react-flow__selection")).toHaveCount(0);
});

test("mouse drag selection and right-button panning remain available", async ({ page }) => {
  const point = await center(page.locator(".react-flow__pane"));
  const before = await viewportTransform(page);
  await page.mouse.move(point.x, point.y);
  await page.mouse.down();
  await page.mouse.move(point.x + 70, point.y + 70, { steps: 5 });
  await expect(page.locator(".react-flow__selection")).toBeVisible();
  await page.mouse.up();
  await expect(page.locator(".react-flow__selection")).toHaveCount(0);
  expect(await viewportTransform(page)).toEqual(before);

  await page.mouse.move(point.x, point.y);
  await page.mouse.down({ button: "right" });
  await page.mouse.move(point.x + 70, point.y + 70, { steps: 5 });
  await page.mouse.up({ button: "right" });
  const after = await viewportTransform(page);
  expect(after.x - before.x).toBeGreaterThan(50);
  expect(after.y - before.y).toBeGreaterThan(50);
});

test("touch can select and move a node without moving the viewport", async ({ page, hasTouch }) => {
  test.skip(!hasTouch, "Requires a touch-enabled browser");
  const node = await addNode(page, "Test text source", hasTouch);
  await page.getByRole("button", { name: "Fit", exact: true }).tap();
  const pane = await page.locator(".react-flow__pane").boundingBox();
  if (!pane) throw new Error("Workflow canvas has no visible bounds");
  const settings = page.getByRole("button", { name: "Canvas lab", exact: true });
  await settings.tap();
  await expect(settings).toHaveAttribute("aria-pressed", "true");
  // The mobile settings panel fills most of the canvas; tap its exposed gutter.
  await page.locator(".react-flow__pane").tap({ position: { x: 4, y: 80 } });
  await expect(node).not.toHaveClass(/selected/);
  await expect(settings).toHaveAttribute("aria-pressed", "false");
  await node.locator("header").tap();
  await expect(node).toHaveClass(/selected/);

  const beforeViewport = await viewportTransform(page);
  const beforePosition = await node.getAttribute("style");
  const point = await center(node.locator("header"));
  const client = await page.context().newCDPSession(page);
  await touch(page, client, "touchStart", [{ ...point, id: 1 }]);
  for (const distance of [20, 40, 60]) {
    await touch(page, client, "touchMove", [{ x: point.x + distance, y: point.y + distance, id: 1 }]);
  }
  await touch(page, client, "touchEnd", []);
  await expect(node).not.toHaveAttribute("style", beforePosition ?? "");
  expect(await viewportTransform(page)).toEqual(beforeViewport);
});

test("ports still connect through a real drag", async ({ page, hasTouch }) => {
  const source = await addNode(page, "Test text source", hasTouch);
  const target = await addNode(page, "Test text sink", hasTouch);
  // New nodes open near the viewport center. Move the sink below the source
  // through the UI so its card does not cover the source's output handle.
  const header = await center(target.locator("header"));
  if (hasTouch) {
    const client = await page.context().newCDPSession(page);
    await touch(page, client, "touchStart", [{ ...header, id: 1 }]);
    for (const distance of [40, 80, 120, 160, 200]) {
      await touch(page, client, "touchMove", [{ x: header.x, y: header.y + distance, id: 1 }]);
    }
    await touch(page, client, "touchEnd", []);
  } else {
    await page.mouse.move(header.x, header.y);
    await page.mouse.down();
    await page.mouse.move(header.x, header.y + 200, { steps: 10 });
    await page.mouse.up();
  }
  await page.getByRole("button", { name: "Fit", exact: true }).click();
  await expect(source).toBeInViewport({ ratio: 1 });
  await expect(target).toBeInViewport({ ratio: 1 });
  const pane = await page.locator(".react-flow__pane").boundingBox();
  if (!pane) throw new Error("Workflow canvas has no visible bounds");
  if (hasTouch) await page.touchscreen.tap(pane.x + 20, pane.y + 80);
  else await page.mouse.click(pane.x + 20, pane.y + 80);
  await expect(page.locator(".react-flow__node.selected")).toHaveCount(0);
  await source.locator(".react-flow__handle.source").click({ trial: true });
  await target.locator(".react-flow__handle.target").click({ trial: true });
  const from = await center(source.locator(".react-flow__handle.source"));
  const to = await center(target.locator(".react-flow__handle.target"));

  if (hasTouch) {
    const client = await page.context().newCDPSession(page);
    await touch(page, client, "touchStart", [{ ...from, id: 1 }]);
    for (let step = 1; step <= 10; step += 1) {
      await touch(page, client, "touchMove", [{
        x: from.x + (to.x - from.x) * step / 10,
        y: from.y + (to.y - from.y) * step / 10,
        id: 1,
      }]);
    }
    await touch(page, client, "touchEnd", []);
  } else {
    await page.mouse.move(from.x, from.y);
    await page.mouse.down();
    await page.mouse.move(to.x, to.y, { steps: 10 });
    await page.mouse.up();
  }
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);
});

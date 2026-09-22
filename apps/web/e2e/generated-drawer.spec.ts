import type { Page } from "@playwright/test";

import { expect, test } from "./workbench.fixture";

const viewportShift = (page: Page) =>
  page
    .locator(".react-flow__viewport")
    .evaluate(
      (element) => new DOMMatrixReadOnly(getComputedStyle(element).transform).e,
    );

/**
 * The Runs drawer is docked, not floating: below 721px it is an overlay like
 * the other workbench drawers, and above that it takes width off the canvas so
 * the canvas chrome stays centred on the canvas.
 */
test("docks the Runs drawer on the canvas' right edge", async ({ page }) => {
  const viewport = page.viewportSize();
  if (!viewport) throw new Error("Playwright page has no viewport");
  const docked = viewport.width > 720;
  const touch = Boolean(test.info().project.use.hasTouch);

  // The Next.js dev overlay floats over the drawer's own top-right controls.
  await page.addStyleTag({
    content: "nextjs-portal { display: none !important; }",
  });

  const canvas = page.getByRole("region", { name: "Workflow canvas" });
  const drawer = page.getByRole("complementary", {
    name: "Generated",
    exact: true,
  });
  await expect(drawer).toHaveCount(0);

  await page.getByRole("button", { name: "Generated artifacts" }).click();

  await expect(drawer).toBeVisible();
  const drawerBox = await drawer.boundingBox();
  const canvasBox = await canvas.boundingBox();
  if (!drawerBox || !canvasBox) {
    throw new Error("Expected a visible Generated drawer over a canvas");
  }

  if (docked) {
    // The drawer owns the right edge and the canvas stops at its left edge.
    expect(drawerBox.x + drawerBox.width).toBeCloseTo(viewport.width, 0);
    expect(drawerBox.y).toBeCloseTo(0, 0);
    expect(canvasBox.x + canvasBox.width).toBeCloseTo(drawerBox.x, 0);
  } else {
    // The drawer floats over a canvas that keeps the whole viewport.
    expect(canvasBox.x + canvasBox.width).toBeCloseTo(viewport.width, 0);
    expect(drawerBox.x).toBeGreaterThan(canvasBox.x);
  }

  // The tool dock centres on the canvas, not on the canvas plus the drawer.
  const dockBox = await page
    .getByRole("complementary", { name: "Canvas actions", exact: true })
    .boundingBox();
  if (!dockBox) throw new Error("Canvas actions dock has no visible bounds");
  expect(dockBox.x + dockBox.width / 2).toBeCloseTo(
    canvasBox.x + canvasBox.width / 2,
    0,
  );

  // Panning the canvas still works while the drawer takes its width, from
  // wherever the canvas is exposed.
  const before = await viewportShift(page);
  const from = {
    x: docked ? canvasBox.x + canvasBox.width / 2 : canvasBox.x + 4,
    y: canvasBox.y + canvasBox.height / 2,
  };
  if (touch) {
    const client = await page.context().newCDPSession(page);
    await client.send("Input.dispatchTouchEvent", {
      type: "touchStart",
      touchPoints: [{ ...from, id: 1 }],
    });
    await client.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [{ x: from.x + 60, y: from.y, id: 1 }],
    });
    await client.send("Input.dispatchTouchEvent", {
      type: "touchEnd",
      touchPoints: [],
    });
    await client.detach();
  } else {
    await page.mouse.move(from.x, from.y);
    await page.mouse.down({ button: "right" });
    await page.mouse.move(from.x + 60, from.y, { steps: 5 });
    await page.mouse.up({ button: "right" });
  }
  await expect.poll(() => viewportShift(page)).toBeGreaterThan(before + 50);

  await page.getByRole("button", { name: "Close Generated" }).click();
  await expect(drawer).toHaveCount(0);
  const releasedBox = await canvas.boundingBox();
  if (!releasedBox) throw new Error("Canvas lost its bounds");
  expect(releasedBox.x + releasedBox.width).toBeCloseTo(viewport.width, 0);
});

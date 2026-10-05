import { expect, test } from "./workbench.fixture";

test("shows Generated inside the existing docked workbench side panel", async ({
  page,
}) => {
  const viewport = page.viewportSize();
  if (!viewport) throw new Error("Playwright page has no viewport");

  const canvas = page.getByRole("region", { name: "Workflow canvas" });
  // Wide screens auto-open Artifacts; measure the closed stage explicitly.
  const closePanel = page.getByRole("button", { name: "Collapse side panel" });
  if (await closePanel.isVisible()) {
    await closePanel.click();
    await expect(closePanel).toBeHidden();
  }
  const canvasBefore = await canvas.boundingBox();
  if (!canvasBefore) throw new Error("Workflow canvas has no visible bounds");

  await page.getByRole("button", { name: "Generated artifacts" }).click();

  const panel =
    viewport.width >= 1100
      ? page.getByRole("complementary", { name: "Workbench side panel" })
      : page.getByRole("dialog");
  const generated = page.getByRole("region", {
    name: "Generated artifacts",
  });
  await expect(panel).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Generated artifacts" }),
  ).toHaveAttribute("aria-expanded", "true");
  await expect(generated).toBeVisible();
  await expect(
    page.getByRole("complementary", { name: "Generated", exact: true }),
  ).toHaveCount(0);

  if (viewport.width >= 1100) {
    const panelBox = await panel.boundingBox();
    const canvasWithPanel = await canvas.boundingBox();
    if (!panelBox || !canvasWithPanel) {
      throw new Error("Expected the side panel and canvas to have bounds");
    }
    expect(panelBox.x + panelBox.width).toBeCloseTo(canvasWithPanel.x, 0);
    expect(canvasWithPanel.width).toBeLessThan(canvasBefore.width);
  }
});

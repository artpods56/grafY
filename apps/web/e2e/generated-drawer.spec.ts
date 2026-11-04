import { expect, test } from "./workbench.fixture";

/**
 * Generated lists the results this canvas' Project stores, by node instance,
 * so it is a view a draft cannot offer: an unsaved canvas has no Project to
 * read results back from. The journey therefore starts by saving — the same
 * rail Save the person uses — and only then opens Generated from the rail.
 */
test("shows Generated inside the existing docked workbench side panel", async ({
  page,
}) => {
  const viewport = page.viewportSize();
  if (!viewport) throw new Error("Playwright page has no viewport");

  // A draft with something on it: Save needs a dirty canvas to be worth
  // pressing, and the Run surface the panel later reads needs a node.
  await page.getByRole("button", { name: "Add node", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Search nodes" })
    .fill("Test text source");
  await page.getByRole("option", { name: /^Test text source/ }).click();
  await page
    .getByRole("button", { name: "Add to canvas", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // A narrow viewport folds the rail into a navigation drawer; its controls
  // (Save, Generated) are only reachable once it is open.
  const openNavigation = page.getByRole("button", { name: "Open navigation" });
  if (await openNavigation.isVisible()) await openNavigation.click();

  // An unnamed draft is named through a prompt. `window.prompt` opens while
  // the Save click is still being dispatched, so the answer cannot live after
  // `await click()` — the click would wait for the dialog and the dialog
  // would wait for an answer that never arrives.
  page.once("dialog", (dialog) => void dialog.accept("Pilot pipeline"));
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page).toHaveURL(
    /\/workspaces\/mobile-test\/projects\/[0-9a-f-]{36}$/,
  );

  const canvas = page.getByRole("region", { name: "Workflow canvas" });
  // Wide screens auto-open Artifacts; measure the closed stage explicitly.
  const closePanel = page.getByRole("button", { name: "Collapse side panel" });
  if (await closePanel.isVisible()) {
    await closePanel.click();
    await expect(closePanel).toBeHidden();
  }
  const canvasBefore = await canvas.boundingBox();
  if (!canvasBefore) throw new Error("Workflow canvas has no visible bounds");

  // On a phone the rail is a navigation drawer that has to be opened first.
  if (await openNavigation.isVisible()) await openNavigation.click();
  const generatedButton = page.getByRole("button", {
    name: "Generated artifacts",
    // The opened drawer adds "Refresh…" and "Close…" header buttons; only the
    // rail item carries the expansion state this spec reads.
    exact: true,
  });
  await generatedButton.click();

  const panel =
    viewport.width >= 1100
      ? page.getByRole("complementary", { name: "Workbench side panel" })
      : page.getByRole("dialog");
  const generated = page.getByRole("region", {
    name: "Generated artifacts",
  });
  await expect(panel).toBeVisible();
  await expect(generated).toBeVisible();
  await expect(
    page.getByRole("complementary", { name: "Generated", exact: true }),
  ).toHaveCount(0);

  if (viewport.width >= 1100) {
    // Docked, the rail stays reachable. Below that the panel is a modal
    // slide-over that hides it from the accessibility tree.
    await expect(generatedButton).toHaveAttribute("aria-expanded", "true");
    // The panel slides open over SIDE_PANEL_MOTION_MS and the canvas edge moves
    // with it, so measure once the edges have met rather than mid-slide.
    await expect(async () => {
      const panelBox = await panel.boundingBox();
      const canvasWithPanel = await canvas.boundingBox();
      if (!panelBox || !canvasWithPanel) {
        throw new Error("Expected the side panel and canvas to have bounds");
      }
      expect(panelBox.x + panelBox.width).toBeCloseTo(canvasWithPanel.x, 0);
      expect(canvasWithPanel.width).toBeLessThan(canvasBefore.width);
    }).toPass();
  }
});

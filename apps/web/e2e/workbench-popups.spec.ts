import type { Locator } from "@playwright/test";

import type { NodeRegistry } from "../src/lib/api/contract";
import { expect, nodeRegistry, test } from "./workbench.fixture";

const catalog = {
  ...nodeRegistry,
  nodes: [
    ...nodeRegistry.nodes,
    ...Array.from({ length: 22 }, (_, index) => ({
      ...nodeRegistry.nodes[0],
      operator_id: `test.catalog_${index}`,
      title: `Catalog node ${String(index + 1).padStart(2, "0")}`,
      description:
        "A node with a longer description to check that results stay easy to scan on a narrow screen.",
    })),
  ],
  artifact_types: [
    {
      key: { id: "scalar.text", schema_version: 1 },
      title: "Text payload",
      bundle: { format: "inline-json", version: 1 },
      field_projections: [],
      payload_schema: {
        type: "object",
        properties: {
          metadata: {
            type: "object",
            properties: { language: { type: "string" } },
          },
          ...Object.fromEntries(
            Array.from({ length: 25 }, (_, index) => [
              `field_${index}`,
              { type: "string" },
            ]),
          ),
        },
      },
    },
  ],
} satisfies NodeRegistry;

test.use({ registry: catalog });

async function expectInsideViewport(locator: Locator) {
  // IntersectionObserver rounds ratios for fractionally positioned popovers.
  await expect(locator).toBeInViewport({ ratio: 0.999 });
  const bounds = await locator.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return {
      left: rect.left,
      top: rect.top,
      right: rect.right,
      bottom: rect.bottom,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      scrollWidth: element.scrollWidth,
      width: element.clientWidth,
    };
  });
  expect(bounds.left).toBeGreaterThanOrEqual(0);
  expect(bounds.top).toBeGreaterThanOrEqual(0);
  expect(bounds.right).toBeLessThanOrEqual(bounds.viewportWidth);
  expect(bounds.bottom).toBeLessThanOrEqual(bounds.viewportHeight);
  expect(bounds.scrollWidth).toBeLessThanOrEqual(bounds.width + 1);
}

test("catalog fits the screen and keeps search when returning from details", async ({
  page,
  viewport,
}, testInfo) => {
  await page.getByRole("button", { name: "Add node", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Add node", exact: true });
  const results = page.getByRole("listbox", { name: "Node results" });
  await expectInsideViewport(dialog);
  await expectInsideViewport(results);
  expect((await dialog.boundingBox())?.height).toBeLessThanOrEqual(680);
  // A real catalog must leave room to scan several choices before scrolling.
  await expect(results.getByRole("option").nth(5)).toBeInViewport({ ratio: 1 });
  await page.screenshot({ path: testInfo.outputPath("node-browser.png") });

  const search = page.getByRole("textbox", { name: "Search nodes" });
  await search.fill("Test text source");
  const option = page.getByRole("option", { name: /^Test text source/ });
  await option.click();
  const add = page.getByRole("button", {
    name: "Add Test text source",
    exact: true,
  });
  await expectInsideViewport(add);
  if (viewport && viewport.width <= 720) {
    await expect(results).toBeHidden();
    await expect(search).toBeHidden();
    const back = page.getByRole("button", { name: "Back to results" });
    await expect(back).toBeFocused();
    await page.screenshot({ path: testInfo.outputPath("node-details.png") });
    await back.click();
    await expect(search).toHaveValue("Test text source");
    await expect(option).toBeFocused();
    await option.click();
  }
  await add.click();
  await expect(dialog).toBeHidden();
  await expect(page.locator(".react-flow__node")).toHaveCount(1);
});

test("compact filters are optional and preserve the chosen source", async ({
  page,
  viewport,
}) => {
  test.skip(!viewport || viewport.width > 1024, "Compact source controls");
  await page.getByRole("button", { name: "Add node", exact: true }).click();
  const source = page.getByRole("combobox", { name: "Node source" });
  await source.selectOption({ label: "Built-in" });
  const artifact = page.getByRole("combobox", { name: "Artifact type" });
  await expect(artifact).toBeHidden();
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  await artifact.selectOption({ label: "Text payload" });
  await page.getByRole("checkbox", { name: "Input nodes only" }).check();
  const filters = page.getByRole("button", {
    name: "Filters (2)",
    exact: true,
  });
  await filters.click();
  await expect(artifact).toBeHidden();
  await expect(source.locator("option:checked")).toHaveText("Built-in");
  await expect(
    page.getByRole("option", { name: /^Test text sink/ }),
  ).toHaveCount(0);
  await page.getByRole("option", { name: /^Test text source/ }).click();
  if (viewport && viewport.width <= 720) {
    await page.getByRole("button", { name: "Back to results" }).click();
  }
  await expect(filters).toHaveAttribute("aria-expanded", "false");
  await expect(source.locator("option:checked")).toHaveText("Built-in");
});

test("Canvas lab reveals advanced controls without covering the canvas", async ({
  page,
}, testInfo) => {
  await page.getByRole("button", { name: "Canvas lab", exact: true }).click();
  const panel = page.getByRole("complementary", { name: "Canvas lab" });
  await expectInsideViewport(panel);
  const bounds = await panel.boundingBox();
  expect(bounds?.width).toBeLessThanOrEqual(296);
  expect(bounds?.height).toBeLessThan(480);
  await expect(
    panel.getByRole("switch", { name: "Show grid lines" }),
  ).toBeVisible();
  const renderVisible = panel.getByRole("switch", {
    name: "Render visible elements only",
  });
  await expect(renderVisible).toBeHidden();
  await page.screenshot({ path: testInfo.outputPath("canvas-lab.png") });
  await panel.getByText("Advanced", { exact: true }).click();
  await renderVisible.click();
  await expect(renderVisible).toHaveAttribute("aria-checked", "true");
  await panel.getByRole("button", { name: "Close canvas lab" }).click();
  await expect(panel).toBeHidden();
});

test("port schema fits the viewport and supports drilling back", async ({
  page,
}, testInfo) => {
  await page.getByRole("button", { name: "Add node", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Search nodes" })
    .fill("Test text source");
  await page.getByRole("option", { name: /^Test text source/ }).click();
  await page
    .getByRole("button", { name: "Add Test text source", exact: true })
    .click();
  await page.getByRole("button", { name: "Fit", exact: true }).click();
  await page.getByRole("button", { name: "Inspect Text type" }).click();
  const popup = page.getByRole("dialog");
  await expectInsideViewport(popup);
  const fields = popup.getByRole("region", { name: "Payload schema fields" });
  await expect(fields).toBeVisible();
  // The canvas dock must not cover the scrollable schema at the bottom.
  await expect
    .poll(() =>
      fields.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        const hit = document.elementFromPoint(
          rect.left + rect.width / 2,
          rect.bottom - 4,
        );
        return hit !== null && element.contains(hit);
      }),
    )
    .toBe(true);
  await page.screenshot({ path: testInfo.outputPath("port-schema.png") });
  await fields.getByRole("button", { name: /metadata/ }).click();
  await expect(fields).toContainText("language");
  await popup
    .getByRole("navigation", { name: "Payload schema path" })
    .getByRole("button", { name: "Text payload" })
    .click();
  await expect(fields.getByRole("button", { name: /metadata/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(popup).toBeHidden();
  await page.setViewportSize({ width: 568, height: 360 });
  await page.getByRole("button", { name: "Fit", exact: true }).click();
  await page.getByRole("button", { name: "Inspect Text type" }).click();
  await expectInsideViewport(popup);
  await expectInsideViewport(fields);
  await page.keyboard.press("Escape");
  await expect(popup).toBeHidden();
  await expect(page.locator(".react-flow__selection")).toHaveCount(0);
});

test("node insertion remains reachable in a short landscape viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 568, height: 360 });
  await page.getByRole("button", { name: "Add node", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Search nodes" })
    .fill("Test text source");
  await page.getByRole("option", { name: /^Test text source/ }).click();
  const dialog = page.getByRole("dialog", { name: "Add node" });
  await expectInsideViewport(dialog);
  const add = page.getByRole("button", {
    name: "Add Test text source",
    exact: true,
  });
  await expectInsideViewport(add);
  await add.click();
  await expect(dialog).toBeHidden();
});

test("small dialogs use only the space their content needs", async ({
  page,
}) => {
  const navigation = page.getByRole("button", {
    name: "Open navigation",
    exact: true,
  });
  if (await navigation.isVisible()) await navigation.click();
  await page
    .getByRole("button", { name: "Workspace invitations", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Workspace invitations" });
  await expectInsideViewport(dialog);
  expect((await dialog.boundingBox())?.height).toBeLessThan(400);
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  await expect(dialog).toBeHidden();
});

import { expect, test } from "./workbench.fixture";

test("switches Graphs, calls one from another and refuses to delete a called Graph", async ({
  page,
}) => {
  page.once("dialog", (dialog) => void dialog.accept("Graphs project"));
  const nav = page.getByRole("button", { name: "Open navigation" });
  if (await nav.isVisible()) await nav.click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/);

  const tabs = page.getByRole("tablist", { name: "Graphs in this Project" });
  await expect(tabs.getByRole("tab")).toHaveCount(1);

  // A second Graph opens as soon as it exists, named for the next free number.
  await page.getByRole("button", { name: "Add Graph", exact: true }).click();
  await expect(tabs.getByRole("tab")).toHaveCount(2);
  await expect(tabs.getByRole("tab", { selected: true })).toHaveText("Graph 2");

  // Its interface is declared with a boundary node.
  await page.getByRole("button", { name: "Add node", exact: true }).click();
  await page.getByRole("textbox", { name: "Search nodes" }).fill("Graph input");
  await page.getByRole("option", { name: /^Graph input/ }).click();
  await page
    .getByRole("button", { name: "Add to canvas", exact: true })
    .click();
  await expect(
    page.locator(".react-flow__node").filter({ hasText: "Graph input" }),
  ).toHaveCount(1);

  // The first Graph can call it; Graph 2 itself is not offered to itself.
  await tabs.getByRole("tab").first().click();
  await expect(tabs.getByRole("tab", { selected: true })).not.toHaveText(
    "Graph 2",
  );
  await page.getByRole("button", { name: "Add node", exact: true }).click();
  await page.getByRole("textbox", { name: "Search nodes" }).fill("Graph 2");
  await page.getByRole("option", { name: /^Graph 2/ }).click();
  await page
    .getByRole("button", { name: "Add to canvas", exact: true })
    .click();
  const callNode = page
    .locator(".react-flow__node")
    .filter({ hasText: "Graph 2" });
  await expect(callNode).toHaveCount(1);
  // The call node's port follows the callee's interface.
  await expect(callNode).toContainText("input");

  // Deleting a Graph that still has a caller is refused, in words.
  await tabs.getByRole("tab", { name: "Graph 2" }).click();
  await page.getByRole("button", { name: "Delete Graph", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Workflow canvas" }).getByRole("alert"),
  ).toContainText("is still called from");
  await expect(tabs.getByRole("tab")).toHaveCount(2);
});

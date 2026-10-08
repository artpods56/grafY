import type { Locator } from "@playwright/test";
import { expect, test, nodeRegistry } from "./workbench.fixture";
import { pythonCatalog } from "./python-presets-fixture";

const registry = {
  ...nodeRegistry,
  nodes: [...nodeRegistry.nodes, ...pythonCatalog.nodes],
  plugins: [...nodeRegistry.plugins, ...pythonCatalog.plugins],
  artifact_types: pythonCatalog.artifact_types,
  presets: pythonCatalog.presets,
};
test.use({ registry });

async function center(locator: Locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error("Element has no bounds");
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

test("Python presets show params, keep drafts local, and confirm breaking wires", async ({
  page,
  hasTouch,
}) => {
  test.skip(hasTouch, "Desktop editor and pointer flow");
  const requests: string[] = [];
  await page.route("**/python/apply", async (route) => {
    const payload: { code: string } = route.request().postDataJSON();
    requests.push(payload.code);
    const invalid = payload.code.includes("unsupported: dict");
    await route.fulfill({
      json: invalid
        ? {
            code_sha256: "a".repeat(64),
            contract: null,
            diagnostics: [
              { line: 2, column: 4, message: "Unsupported Params field" },
            ],
          }
        : {
            code_sha256: "b".repeat(64),
            diagnostics: [],
            contract: {
              input_name: "text",
              input: {
                artifact_type: { id: "scalar.integer", schema_version: 1 },
                shape: "one",
              },
              output: {
                artifact_type: { id: "scalar.text", schema_version: 1 },
                shape: "one",
              },
              params_schema: null,
            },
          },
    });
  });
  async function insert(title: string) {
    await page.getByRole("button", { name: "Add node", exact: true }).click();
    await page.getByRole("textbox", { name: "Search nodes" }).fill(title);
    await page.getByRole("option", { name: new RegExp(`^${title}`) }).click();
    await page
      .getByRole("button", { name: "Add to canvas", exact: true })
      .click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    return page.locator(".react-flow__node").filter({ hasText: title });
  }
  const source = await insert("Test text source");
  const target = await insert("Replace text");
  await expect(target.locator("details")).not.toHaveAttribute("open");
  await expect(
    target.getByRole("textbox", { name: "Search *", exact: true }),
  ).toBeVisible();
  await target.getByRole("textbox").first().fill("first");
  const beforePosition = await target.getAttribute("style");
  const header = await center(target.locator("header"));
  await page.mouse.move(header.x, header.y);
  await page.mouse.down();
  await page.mouse.move(header.x + 320, header.y + 260, { steps: 10 });
  await page.mouse.up();
  await expect(target).not.toHaveAttribute("style", beforePosition ?? "");
  await page.getByRole("button", { name: "Fit", exact: true }).click();
  await expect(source).toBeInViewport({ ratio: 1 });
  await expect(target).toBeInViewport({ ratio: 1 });
  const pane = await page.locator(".react-flow__pane").boundingBox();
  if (!pane) throw new Error("Canvas has no bounds");
  await page.mouse.click(pane.x + 20, pane.y + 80);
  await expect(page.locator(".react-flow__node.selected")).toHaveCount(0);
  const sourceHeader = await center(source.locator("header"));
  await page.mouse.click(sourceHeader.x, sourceHeader.y);
  const output = source.locator(".react-flow__handle.source");
  await output.click({ trial: true });
  const from = await center(output);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(from.x + 20, from.y + 20, { steps: 3 });
  const input = target.locator(".react-flow__handle.target");
  await expect(input).toBeVisible();
  await page.waitForTimeout(350);
  const to = await center(input);
  await page.mouse.move(to.x, to.y, { steps: 10 });
  await page.mouse.up();
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);
  await target.locator("summary").click();
  const editor = target.getByRole("textbox", { name: "Python transform code" });
  await editor.fill("def transform(text: int) -> str:\n    return str(text)");
  expect(requests).toEqual([]);
  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toContain("Apply will disconnect these wires:");
    await dialog.dismiss();
  });
  await target.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);
  await expect(target.getByText("Unapplied changes")).toBeVisible();
  page.once("dialog", async (dialog) => {
    await dialog.accept();
  });
  await target.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(page.locator(".react-flow__edge")).toHaveCount(0);
  await expect(target.getByText("Unapplied changes")).toHaveCount(0);
  await editor.fill(
    "class Params(BaseModel):\n    unsupported: dict\ndef transform(text: str, params: Params) -> str:\n    return text",
  );
  await target.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(target.getByRole("alert")).toContainText(
    "Line 2: Unsupported Params field",
  );
});

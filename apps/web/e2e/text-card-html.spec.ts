import { expect, test } from "./workbench.fixture";

const NOW = "2026-01-01T00:00:00Z";
const HTML_ARTIFACT = "11111111-1111-4111-8111-111111111111";
const HTML = `<!doctype html><html><head><style>h1 { color: rgb(200, 90, 40); }</style></head><body>
<h1>Parish register</h1><p id="ran">not run</p>
<a id="out" href="https://tracker.example/out" target="_blank">Leave</a>
<!-- ${"A page runs well past what a card reads of other files. ".repeat(200)} -->
<img src="https://tracker.example/pixel.png" alt="remote">
<script>document.getElementById("ran").textContent = "script ran"; parent.document.title = "escaped";</script>
</body></html>`;

test("renders HTML in a text card without running it or fetching anything", async ({
  page,
}) => {
  const remote: string[] = [];
  await page.route("https://tracker.example/**", (route) => {
    remote.push(route.request().url());
    return route.abort();
  });
  await page.route(`**/artifacts/${HTML_ARTIFACT}/content`, (route) =>
    route.fulfill({ json: { value: HTML } }),
  );
  const events = [
    {
      sequence: 1,
      turn_id: "55555555-5555-4555-8555-555555555555",
      created_at: NOW,
      payload: {
        kind: "tool_result",
        call_id: "c1",
        tool_id: "t1",
        tool_name: "render",
        ok: true,
        fingerprint: "f".repeat(64),
        artifacts: [
          {
            port: "page",
            artifact: {
              artifact_id: HTML_ARTIFACT,
              artifact_type: "scalar.text",
              schema_version: 1,
            },
          },
        ],
        model_view: "a page",
        error: null,
      },
    },
  ];
  await page.route("**/api/**/agents/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const parts = path.split("/");
    let json: unknown = null;
    if (path.endsWith("/model"))
      json = {
        source: "deployment",
        model_name: "Test model",
        base_url: "",
        key_configured: true,
      };
    else if (path.endsWith("/conversations"))
      json = {
        conversations: [
          {
            id: "44444444-4444-4444-8444-444444444444",
            title: "Pages",
            agent_id: parts[parts.indexOf("agents") + 1],
            graph_id: parts[parts.indexOf("graphs") + 1],
            created_at: NOW,
            updated_at: NOW,
          },
        ],
      };
    else if (path.endsWith("/events"))
      json = { events, last_sequence: 1, next_sequence: 1 };
    await route.fulfill({ json });
  });
  // A drag is a pointer gesture; a touch screen has no native drag to give it.
  if ((page.viewportSize()?.width ?? 0) < 800) return;

  await page.getByRole("button", { name: "Add Agent", exact: true }).click();
  page.once("dialog", (dialog) => void dialog.accept("Pages"));
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/);
  const agent = page.locator(".react-flow__node-grafyAgent");
  const flow = page.locator(".react-flow");
  const bounds = await flow.boundingBox();
  if (!bounds) throw new Error("Canvas not visible");
  await agent
    .getByLabel(/^page: /)
    .dragTo(flow, { targetPosition: { x: bounds.width - 640, y: 60 } });
  const card = page.locator("[data-artifact-card-id]");
  await expect(card).toHaveCount(1);

  // It opens rendered, in the HTML's own styles.
  const frame = card.frameLocator('iframe[title="Rendered HTML"]');
  const heading = frame.getByRole("heading", { name: "Parish register" });
  await expect(heading).toBeVisible();
  await expect(heading).toHaveCSS("color", "rgb(200, 90, 40)");
  // It takes up the room it was given, not the default height of a frame.
  const box = await card.locator("iframe").boundingBox();
  expect(box?.height).toBeGreaterThan(400);
  expect(box?.width).toBeGreaterThan(500);

  // A selected page can be made bigger, from its corner.
  const handle = card.getByRole("button", { name: "Resize artifact" });
  const corner = await handle.boundingBox();
  if (!box || !corner) throw new Error("Page not visible");
  await page.mouse.move(
    corner.x + corner.width / 2,
    corner.y + corner.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(corner.x - 60, corner.y - 60, { steps: 8 });
  await page.mouse.up();
  await expect
    .poll(async () => (await card.locator("iframe").boundingBox())?.width ?? 0)
    .toBeLessThan(box.width - 30);

  // What it says it would do, it did not.
  await expect(frame.locator("#ran")).toHaveText("not run");
  await expect(page).not.toHaveTitle("escaped");
  expect(remote).toEqual([]);

  // A link must not carry the frame, or this page, off to the address it named.
  await frame.locator("#out").click();
  await expect(
    frame.getByRole("heading", { name: "Parish register" }),
  ).toBeVisible();
  await expect(frame.locator("#out")).toHaveText("Leave");
  expect(remote).toEqual([]);

  // Selected, as a drop leaves it, the frame takes the pointer: it can be scrolled.
  await expect(card.locator("iframe")).not.toHaveCSS("pointer-events", "none");

  // Otherwise the frame leaves the pointer to the canvas, so the card still drags.
  await page.mouse.click(bounds.x + 40, bounds.y + bounds.height / 2);
  await expect(card.locator("iframe")).toHaveCSS("pointer-events", "none");
  const before = await card.boundingBox();
  if (!before) throw new Error("Card not visible");
  await page.mouse.move(before.x + 60, before.y + 60);
  await page.mouse.down();
  await page.mouse.move(before.x + 60, before.y + 180, { steps: 8 });
  await page.mouse.up();
  await expect
    .poll(async () => (await card.boundingBox())?.y ?? 0)
    .toBeGreaterThan(before.y + 80);
  await expect(card.locator("iframe")).not.toHaveCSS("pointer-events", "none");

  // The words are a click away.
  await card
    .getByRole("radiogroup", { name: "Read this text as" })
    .getByText("Text", { exact: true })
    .click();
  await expect(card).toContainText("<h1>Parish register</h1>");
});

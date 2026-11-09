import type { Locator, Page } from "@playwright/test";

import { expect, test } from "./workbench.fixture";

const NOW = "2026-01-01T00:00:00Z";
const PAGE = "a1111111-1111-4111-8111-111111111111";
const PAGE_MISSING = "a2222222-2222-4222-8222-222222222222";
const BAPTISMS = "b1111111-1111-4111-8111-111111111111";
const MARRIAGES = "c1111111-1111-4111-8111-111111111111";
const BURIALS = "d1111111-1111-4111-8111-111111111111";
const BURIALS_MISSING = "d2222222-2222-4222-8222-222222222222";
const DEATHS = "e1111111-1111-4111-8111-111111111111";

const TEMPLATE = `<!doctype html><html><body><h1>Parish</h1><table>
{{#baptisms}}<tr><td>{{name}}</td><td>{{year}}</td></tr>{{/baptisms}}
{{#marriages}}<tr><td>{{couple}}</td></tr>{{/marriages}}
{{#burials}}<tr><td>{{person}}</td></tr>{{/burials}}
{{#deaths}}<tr><td>{{note}}</td></tr>{{/deaths}}
</table></body></html>`;

const LEAK = "<script>alert(1)</script><img src=https://tracker.example/x>";

function source(artifactId: string) {
  return {
    artifact_id: artifactId,
    artifact_type: "json.document",
    schema_version: 1,
  };
}

function pageBody(burialsId: string) {
  return {
    html: TEMPLATE,
    sources: {
      baptisms: source(BAPTISMS),
      marriages: source(MARRIAGES),
      burials: source(burialsId),
      deaths: source(DEATHS),
    },
  };
}

async function stubAgents(page: Page, pageId: string) {
  const events = [
    {
      sequence: 1,
      turn_id: "55555555-5555-4555-8555-555555555555",
      created_at: NOW,
      payload: {
        kind: "tool_result",
        call_id: "c1",
        tool_id: "t1",
        tool_name: "create_artifact",
        ok: true,
        fingerprint: "f".repeat(64),
        artifacts: [
          {
            port: "page",
            artifact: {
              artifact_id: pageId,
              artifact_type: "html.page",
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
}

async function stubSources(
  page: Page,
  pageId: string,
  burialsId: string,
  burialsMissing: boolean,
) {
  await page.route(`**/artifacts/${pageId}/content`, (route) =>
    route.fulfill({ json: pageBody(burialsId) }),
  );
  await page.route(`**/artifacts/${BAPTISMS}/content`, (route) =>
    route.fulfill({
      json: [
        { name: "Ada Lovelace", year: 1815 },
        { name: LEAK, year: 1852 },
      ],
    }),
  );
  await page.route(`**/artifacts/${MARRIAGES}/content`, (route) =>
    route.fulfill({ json: [{ couple: "Ada and William" }] }),
  );
  await page.route(`**/artifacts/${burialsId}/content`, (route) =>
    burialsMissing
      ? route.fulfill({ status: 404, body: "missing" })
      : route.fulfill({ json: [{ person: "Byron" }] }),
  );
  await page.route(`**/artifacts/${DEATHS}/content`, (route) =>
    route.fulfill({ json: [{ note: "Ada in 1852" }] }),
  );
}

async function dropPage(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: "Add Agent", exact: true }).click();
  page.once("dialog", (dialog) => void dialog.accept("Pages"));
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/);
  const flow = page.locator(".react-flow");
  const bounds = await flow.boundingBox();
  if (!bounds) throw new Error("Canvas not visible");
  await page
    .locator(".react-flow__node-grafyAgent")
    .getByLabel(/^page: /)
    .dragTo(flow, { targetPosition: { x: bounds.width - 640, y: 40 } });
  const card = page.locator("[data-artifact-card-id]");
  await expect(card).toHaveCount(1);
  return card;
}

test("fills an html page from the artifacts it names", async ({ page }) => {
  const remote: string[] = [];
  await page.route("https://tracker.example/**", (route) => {
    remote.push(route.request().url());
    return route.abort();
  });
  await stubSources(page, PAGE, BURIALS, false);
  await stubAgents(page, PAGE);
  // A drag is a pointer gesture; a touch screen has no native drag to give it.
  if ((page.viewportSize()?.width ?? 0) < 800) return;

  const card = await dropPage(page);
  await expect(card.locator("[data-html-page]")).toHaveAttribute(
    "data-html-page",
    "ready",
  );
  const frame = card.frameLocator('iframe[title="Rendered HTML"]');
  await expect(frame.getByRole("cell", { name: "Ada Lovelace" })).toBeVisible();
  await expect(frame.getByRole("cell", { name: "1815" })).toBeVisible();
  await expect(
    frame.getByRole("cell", { name: "1852", exact: true }),
  ).toBeVisible();
  await expect(
    frame.getByRole("cell", { name: "Ada and William" }),
  ).toBeVisible();
  await expect(frame.getByRole("cell", { name: "Byron" })).toBeVisible();
  await expect(frame.getByRole("cell", { name: "Ada in 1852" })).toBeVisible();
  await expect(frame.getByRole("row")).toHaveCount(5);

  // The dangerous value is text in a cell, not a tag the frame fetches.
  const html = await frame.locator("body").innerHTML();
  expect(html).toContain("&lt;script&gt;");
  expect(html).toContain("tracker.example");
  expect(html).not.toContain("<script");
  expect(html).not.toContain("<img");
  await expect(frame.locator("script")).toHaveCount(0);
  await expect(frame.locator("img")).toHaveCount(0);
  expect(remote).toEqual([]);

  await expect(
    card.getByText("Reads baptisms, marriages, burials, deaths"),
  ).toBeVisible();

  const box = await card.boundingBox();
  const viewport = page.viewportSize();
  if (!box || !viewport) throw new Error("Card not visible");
  const x = Math.max(0, box.x - 8);
  const y = Math.max(0, box.y - 8);
  await page.screenshot({
    path: "/tmp/grafy-html-page-card.png",
    clip: {
      x,
      y,
      width: Math.min(viewport.width - x, box.width + 16),
      height: Math.min(viewport.height - y, box.height + 80),
    },
  });

  await card
    .getByRole("radiogroup", { name: "Read this text as" })
    .getByText("Text", { exact: true })
    .click();
  await expect(card.getByText("{{#baptisms}}")).toBeVisible();
  await expect(card.locator("iframe")).toHaveCount(0);
  expect(remote).toEqual([]);
});

test("names a source it could not read and still shows the template", async ({
  page,
}) => {
  await stubSources(page, PAGE_MISSING, BURIALS_MISSING, true);
  await stubAgents(page, PAGE_MISSING);
  if ((page.viewportSize()?.width ?? 0) < 800) return;

  const card = await dropPage(page);
  await expect(card.locator("[data-html-page]")).toHaveAttribute(
    "data-html-page",
    "sources",
  );
  await expect(card.getByText("burials could not be read")).toBeVisible();
  await expect(card.locator("iframe")).toHaveCount(0);
  // What could not be read can be asked for again, and here it now reads.
  await page.unroute(`**/artifacts/${BURIALS_MISSING}/content`);
  await page.route(`**/artifacts/${BURIALS_MISSING}/content`, (route) =>
    route.fulfill({ json: [{ person: "Recovered burial" }] }),
  );
  await card.getByRole("button", { name: "Try again" }).click();
  await expect(
    card
      .frameLocator('iframe[title="Rendered HTML"]')
      .getByText("Recovered burial"),
  ).toBeVisible();
  await expect(card.getByText("Ada Lovelace")).toHaveCount(0);
  await expect(card.getByText("Ada and William")).toHaveCount(0);
  await expect(
    card.getByText("Reads baptisms, marriages, burials, deaths"),
  ).toBeVisible();

  await card
    .getByRole("radiogroup", { name: "Read this text as" })
    .getByText("Text", { exact: true })
    .click();
  await expect(card.getByText("{{#baptisms}}")).toBeVisible();
  await expect(card.getByText("burials could not be read")).toHaveCount(0);
});

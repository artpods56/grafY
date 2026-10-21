import { expect, test as base, type Page } from "@playwright/test";

import type {
  SavedGraphList,
  SavedGraphSummary,
  Workspace,
} from "../src/lib/api/contract";
import { mockGrafyApi } from "./workbench.fixture";

/**
 * The graph browser's filters live in the address, so the person can reload it,
 * send it to a teammate, and take it back with Back. This spec drives the real
 * browser through all of that: a shared address, typed keystrokes, a reload,
 * history, and the resets that must take a filter back out again.
 *
 * Two locations with different graphs are what makes the assertions mean
 * something: a list that only has to be non-empty cannot show a filter leaked
 * across locations or dropped a match on the floor.
 */

const PERSONAL_ID = "11111111-1111-4111-8111-111111111111";
const ATLAS_ID = "22222222-2222-4222-8222-222222222222";

const personal = {
  id: PERSONAL_ID,
  slug: "personal",
  name: "Personal",
  kind: "personal",
  role: "owner",
  capabilities: ["view_graph", "create_graph"],
} satisfies Workspace;

const atlas = {
  id: ATLAS_ID,
  slug: "atlas",
  name: "Atlas",
  kind: "shared",
  role: "editor",
  capabilities: ["view_graph", "create_graph"],
} satisfies Workspace;

function graph(id: string, name: string, updatedAt: string): SavedGraphSummary {
  return {
    id,
    name,
    node_count: 3,
    edge_count: 2,
    revision: 4,
    updated_at: `${updatedAt}T10:00:00Z`,
    draft_pending: false,
  };
}

const atlasGraphs = {
  graphs: [
    graph("atlas-invoice-intake", "Invoice intake", "2026-08-12"),
    graph("atlas-invoice-audit", "Invoice archive audit", "2026-08-11"),
    graph("atlas-nightly-sync", "Nightly sync", "2026-08-10"),
  ],
} satisfies SavedGraphList;

const personalGraphs = {
  graphs: [
    graph("personal-palette", "Personal palette", "2026-08-09"),
    graph("personal-ledger", "Personal ledger", "2026-08-08"),
  ],
} satisfies SavedGraphList;

const test = base.extend<{ graphApiFixtures: void }>({
  // Automatic: every test here gets the mocked endpoints, plus the guarantee
  // that these pages asked for no endpoint this fixture did not offer.
  graphApiFixtures: [
    async ({ page }, runFixture) => {
      const unhandled = await mockGrafyApi(page, {
        workspaces: [personal, atlas],
        graphsByWorkspace: {
          [PERSONAL_ID]: personalGraphs,
          [ATLAS_ID]: atlasGraphs,
        },
      });
      await runFixture(undefined);
      expect(unhandled(), "Unhandled Playwright API requests").toEqual([]);
    },
    { auto: true },
  ],
});

const search = (page: Page) => page.getByLabel("Search graphs");
const rowTitles = (page: Page) => page.locator(".grafy-graphs__row-title");
const tab = (page: Page, name: "Recent" | "All") =>
  page.getByRole("button", { name, exact: true });
/** A graph row is addressed by the workbench path it opens. */
const rowFor = (page: Page, slug: string, graphId: string) =>
  page.locator(`a[href="/workspaces/${slug}/graphs/${graphId}"]`);

async function titles(page: Page): Promise<string[]> {
  return (await rowTitles(page).allTextContents()).map((title) => title.trim());
}

/**
 * Address, input, list, and tabs read in one pass through the page, so a
 * result either agrees everywhere or fails the assertion.
 */
async function snapshot(page: Page) {
  return page.evaluate(() => {
    const url = new URL(window.location.href);
    const input = document.querySelector<HTMLInputElement>(
      'input[aria-label="Search graphs"]',
    );
    return {
      address: `${url.pathname}${url.search}`,
      query: input?.value ?? null,
      titles: Array.from(
        document.querySelectorAll(".grafy-graphs__row-title"),
      ).map((title) => title.textContent?.trim() ?? ""),
      pressed: Array.from(
        document.querySelectorAll("[aria-pressed='true']"),
      ).map((button) => button.textContent?.trim() ?? ""),
    };
  });
}

test("opens the location, the search, and the view the address asked for", async ({
  page,
}) => {
  await page.goto("/graphs?location=atlas&q=invoice&view=all&utm_source=email");

  await expect(page).toHaveURL(
    "/workspaces/atlas/graphs?q=invoice&view=all&utm_source=email",
  );
  await expect(search(page)).toHaveValue("invoice");
  await expect(tab(page, "All")).toHaveAttribute("aria-pressed", "true");
  await expect(tab(page, "Recent")).toHaveAttribute("aria-pressed", "false");
  await expect
    .poll(() => titles(page))
    .toEqual(["Invoice intake", "Invoice archive audit"]);
  await expect(rowFor(page, "atlas", "atlas-nightly-sync")).toHaveCount(0);
  await expect(rowFor(page, "personal", "personal-palette")).toHaveCount(0);
  await expect(page.getByText("2 graphs")).toBeVisible();
});

test("opens the same address again after a reload", async ({ page }) => {
  await page.goto("/workspaces/atlas/graphs?view=all&q=invoice");

  await page.reload();

  await expect(page).toHaveURL("/workspaces/atlas/graphs?view=all&q=invoice");
  await expect(search(page)).toHaveValue("invoice");
  await expect(tab(page, "All")).toHaveAttribute("aria-pressed", "true");
  await expect
    .poll(() => titles(page))
    .toEqual(["Invoice intake", "Invoice archive audit"]);
});

test("keeps a location the person cannot reach from becoming a page", async ({
  page,
}) => {
  // `ghost-team` is not one of the two locations this account can see. The
  // search is still worth keeping; the location named in the address is not.
  await page.goto("/graphs?location=ghost-team&q=invoice");

  await expect(page).toHaveURL("/workspaces/personal/graphs?q=invoice");
  await expect(search(page)).toHaveValue("invoice");
  await expect(rowTitles(page)).toHaveCount(0);
  await expect(page.getByText("No graphs match your search")).toBeVisible();
});

test("writes the address while typing without stacking a step per keystroke", async ({
  page,
}) => {
  await page.goto("/graphs?location=personal");
  await expect(page).toHaveURL("/workspaces/personal/graphs");
  await expect
    .poll(() => titles(page))
    .toEqual(["Personal palette", "Personal ledger"]);

  await page.goto("/workspaces/atlas/graphs");
  await expect
    .poll(() => titles(page))
    .toEqual(["Invoice intake", "Invoice archive audit", "Nightly sync"]);

  await search(page).pressSequentially("sync", { delay: 25 });

  // Every surface agrees on the word that was typed, in one read of the page:
  // the address, the box, the list, and the view that is showing it.
  await expect
    .poll(() => snapshot(page))
    .toEqual({
      address: "/workspaces/atlas/graphs?q=sync",
      query: "sync",
      titles: ["Nightly sync"],
      pressed: ["Recent"],
    });
  await expect(rowFor(page, "atlas", "atlas-invoice-intake")).toHaveCount(0);

  // Five keystrokes, one address: Back leaves the page instead of unwinding
  // the word a letter at a time.
  await page.goBack();
  await expect(page).toHaveURL("/workspaces/personal/graphs");
});

test("gives history the last word about the filters", async ({ page }) => {
  await page.goto("/workspaces/atlas/graphs");
  await expect.poll(() => titles(page)).toHaveLength(3);

  await page.goto("/workspaces/atlas/graphs?q=invoice&view=all");
  await expect
    .poll(() => titles(page))
    .toEqual(["Invoice intake", "Invoice archive audit"]);

  await page.goBack();
  await expect(page).toHaveURL("/workspaces/atlas/graphs");
  await expect(search(page)).toHaveValue("");
  await expect.poll(() => titles(page)).toHaveLength(3);

  await page.goForward();
  await expect(page).toHaveURL("/workspaces/atlas/graphs?q=invoice&view=all");
  await expect(search(page)).toHaveValue("invoice");
  await expect(tab(page, "All")).toHaveAttribute("aria-pressed", "true");
  await expect
    .poll(() => titles(page))
    .toEqual(["Invoice intake", "Invoice archive audit"]);
});

test("takes a filter back out of the address when it is reset", async ({
  page,
}) => {
  await page.goto("/workspaces/atlas/graphs?q=nothing&view=all");
  await expect(page.getByText("No graphs match your search")).toBeVisible();

  await page.getByRole("button", { name: "Clear search" }).click();
  await expect(page).toHaveURL("/workspaces/atlas/graphs?view=all");
  await expect(search(page)).toHaveValue("");
  await expect.poll(() => titles(page)).toHaveLength(3);

  // Recent is the default view, so leaving it takes the parameter with it.
  await tab(page, "Recent").click();
  await expect(page).toHaveURL("/workspaces/atlas/graphs");
  await expect.poll(() => titles(page)).toHaveLength(3);
});

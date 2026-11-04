import type { Locator, Page } from "@playwright/test";

import { expect, test } from "./workbench.fixture";

/**
 * Issue #211 asked what a phone user actually gets from the controls on a canvas,
 * because nothing had ever measured it. Two rules are deliberate, and this is the
 * only place either is asserted:
 *
 * 1. Canvas *chrome* — the dock, the selection toolbar — grows to a 44px target at
 *    the workbench's own 720px breakpoint. `phoneTouch.rail` is what carries that,
 *    so if the kit's chrome sizes ever stop reaching it, this fails.
 * 2. A control *inside a card* keeps the pixel size it has on a desktop, because a
 *    card is a fixed-size object on the canvas and not a page. It therefore stays
 *    under a thumb target on a phone. That is the accepted cost of rule 2, not an
 *    oversight — issue #211 leaves open whether the rule should stand, and the
 *    recorded numbers are what that decision needs.
 *
 * A unit test cannot produce either number: StyleX is mocked in Vitest and no layout
 * runs, so this belongs to the browser suite CI runs on `main`.
 */

async function bounds(locator: Locator, name: string) {
  const box = await locator.boundingBox();
  if (!box) throw new Error(`Canvas control has no visible bounds: ${name}`);
  return box;
}

async function addTextAnnotation(page: Page, hasTouch: boolean) {
  const open = page.getByRole("button", { name: "Add shape or text" });
  if (hasTouch) await open.tap();
  else await open.click();
  const item = page.getByRole("menuitem", { name: "Text", exact: true });
  if (hasTouch) await item.tap();
  else await item.click();
  // A new annotation lands selected, so its toolbar is already up.
  await expect(
    page.getByRole("button", { name: "Remove annotation" }),
  ).toBeVisible();
}

test("the canvas dock reaches a thumb target on a phone and the kit's size above it", async ({
  page,
}, testInfo) => {
  const width = testInfo.project.use.viewport?.width ?? 0;
  const dock = await bounds(
    page.getByRole("button", { name: "Add node", exact: true }),
    "dock Add node",
  );

  if (width <= 720) {
    expect(dock.height, `dock at ${width}px`).toBeGreaterThanOrEqual(44);
    expect(dock.width, `dock at ${width}px`).toBeGreaterThanOrEqual(44);
  } else {
    // `IconButton size="lg"`, untouched: a pointer does not need more than this.
    expect(dock.height, `dock at ${width}px`).toBeLessThanOrEqual(32);
  }
});

test("a card's own control keeps its pixel size at every viewport", async ({
  page,
  hasTouch,
}, testInfo) => {
  const width = testInfo.project.use.viewport?.width ?? 0;
  await addTextAnnotation(page, hasTouch);

  const chrome = await bounds(
    page.getByRole("button", { name: "Canvas lab", exact: true }),
    "dock Canvas lab",
  );
  // The toolbar a selected card shows is the card's furniture: a kit
  // `IconButton size="xs"`, which is 22px wherever the canvas happens to be.
  const card = await bounds(
    page.getByRole("button", { name: "Remove annotation" }),
    "annotation Remove",
  );

  test.info().annotations.push({
    type: "measurement",
    description: `at ${width}px: canvas chrome ${Math.round(chrome.height)}px, card control ${Math.round(card.height)}px`,
  });

  expect(card.height, `card control at ${width}px`).toBeLessThanOrEqual(24);
  if (width <= 720) {
    expect(chrome.height).toBeGreaterThanOrEqual(44);
    // The gap is the open question in issue #211, asserted so that closing it —
    // in either direction — has to be a decision someone made here.
    expect(card.height).toBeLessThan(chrome.height);
  }
});

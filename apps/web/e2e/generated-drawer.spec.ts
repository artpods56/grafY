import type { Page } from "@playwright/test";

import { expect, test } from "./workbench.fixture";
import type {
  GraphExecutionDetail,
  GraphExecutionList,
  GraphExecutionSummary,
} from "../src/lib/api/contract";

const panel = (page: Page) =>
  page.getByRole("complementary", { name: "Workbench side panel" });
const panelButton = (page: Page) =>
  page.getByRole("button", { name: "Artifacts and templates panel" });
const drawer = (page: Page) =>
  page.getByRole("region", { name: "Generated", exact: true });

function summary(
  executionId: string,
  createdAt: string,
): GraphExecutionSummary {
  return {
    execution_id: executionId,
    graph_id: "graph-1",
    graph_revision: 4,
    status: "succeeded",
    scope: "all",
    requested_node_ids: ["resize-1"],
    created_at: createdAt,
    started_at: createdAt,
    finished_at: createdAt,
    workflow_run_id: `workflow-${executionId}`,
    error: null,
    node_count: 1,
    artifact_count: 1,
  };
}

function detailFor(execution: GraphExecutionSummary): GraphExecutionDetail {
  return {
    ...execution,
    node_results: [
      {
        node_id: "resize-1",
        position: 0,
        status: "succeeded",
        error: null,
        completed_at: execution.finished_at ?? execution.created_at,
        outputs: [
          {
            port: "tables",
            kind: "single" as const,
            value: {
              artifact_id: `artifact-${execution.execution_id}`,
              artifact_type: "table.data",
              schema_version: 1,
            },
            artifacts: [
              {
                artifact_id: `artifact-${execution.execution_id}`,
                artifact_type: "table.data",
                schema_version: 1,
                content_type: "application/json",
                metadata: {},
                sha256: `sha-${execution.execution_id}`,
              },
            ],
          },
        ],
      },
    ],
  };
}

const RUNS: GraphExecutionList = {
  items: [
    summary("execution-2", "2026-07-18T09:00:00Z"),
    summary("execution-1", "2026-07-18T08:00:00Z"),
  ],
  next_cursor: null,
};

/** Stubs the runs of this graph so the drawer has two batches to show. */
async function stubRuns(page: Page): Promise<void> {
  const details = new Map(
    RUNS.items.map((item) => [item.execution_id, detailFor(item)]),
  );
  await page.route(
    (url) => /\/graphs\/[^/]+\/executions(\/.*)?$/.test(url.pathname),
    (route) => {
      const id = route.request().url().split("/executions/")[1];
      const detail = id ? details.get(id) : undefined;
      if (detail) {
        void route.fulfill({ json: detail });
        return;
      }
      void route.fulfill({ json: RUNS });
    },
  );
}

async function openGeneratedTab(page: Page): Promise<void> {
  if ((await panelButton(page).getAttribute("aria-pressed")) === "false") {
    await panelButton(page).click();
  }
  await expect(panel(page)).toBeVisible();
  await panel(page).getByRole("tab", { name: "Generated" }).click();
}

/**
 * The Runs drawer is one tab of the workbench side panel, not a second dock: it
 * renders inside the panel's tab panel and gives the canvas no new neighbour on
 * the right. It stays per canvas, newest first, and rows from an older run are
 * draggable onto ports.
 */
test("shows the Runs drawer as a tab of the side panel", async ({ page }) => {
  await stubRuns(page);
  await openGeneratedTab(page);

  const region = drawer(page);
  await expect(region).toBeVisible();
  await expect(region).toHaveAttribute(
    "aria-labelledby",
    "grafy-side-panel-tab-generated",
  );
  await expect(
    region.evaluate((element) => element.closest('[role="tabpanel"]') !== null),
  ).toBe(true);

  // Newest first, in the batches the drawer names.
  await expect(region.getByText("Latest run")).toBeVisible();
  const previousRuns = region.getByRole("button", { name: /Previous runs/ });
  await expect(previousRuns).toBeVisible();

  // The panel is the only dock: the canvas still reaches the window's right edge.
  const canvas = page.getByRole("region", { name: "Workflow canvas" });
  const canvasBox = await canvas.boundingBox();
  const viewport = page.viewportSize();
  if (!canvasBox || !viewport) throw new Error("Canvas has no visible bounds");
  expect(canvasBox.x + canvasBox.width).toBeCloseTo(viewport.width, 0);

  // An older run expands into its producing node's group, and its rows drag.
  await previousRuns.click();
  const rows = region.locator("[data-artifact-row]");
  await expect(rows.first()).toBeVisible();
  await expect(rows.first()).toHaveAttribute("draggable", "true");
});

test("collapsing the panel takes the Runs drawer with it", async ({
  page,
}) => {
  await stubRuns(page);
  await openGeneratedTab(page);
  await expect(drawer(page)).toBeVisible();

  await panel(page).getByRole("button", { name: "Collapse side panel" }).click();

  await expect(panel(page)).toHaveCount(0);
  await expect(drawer(page)).toHaveCount(0);
});

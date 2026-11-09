import { expect, test } from "./workbench.fixture";

const NOW = "2026-01-01T00:00:00Z";
const CONVERSATION = "44444444-4444-4444-8444-444444444444";
const TEXT_ARTIFACT = "77777777-7777-4777-8777-777777777777";
const BLOCKS_ARTIFACT = "88888888-8888-4888-8888-888888888888";
const ROW_ARTIFACT = "99999999-9999-4999-8999-999999999999";

test("connects a node as a tool, shows its calls and results, and drags a result onto the canvas", async ({
  page,
}) => {
  // The thread already holds a turn that called the tool: the API's own replay of one.
  const events = [
    { payload: { kind: "user_message", text: "What does the source say?" } },
    {
      payload: {
        kind: "tool_call",
        call_id: "call-1",
        tool_id: "tool-1",
        tool_name: "test_text_source",
        arguments: { query: "dear sir" },
      },
    },
    {
      payload: {
        kind: "tool_result",
        call_id: "call-1",
        tool_id: "tool-1",
        tool_name: "test_text_source",
        ok: true,
        fingerprint: "f".repeat(64),
        artifacts: [
          {
            port: "text",
            artifact: {
              artifact_id: TEXT_ARTIFACT,
              artifact_type: "scalar.text",
              schema_version: 1,
            },
          },
        ],
        model_view: "dear sir",
        error: null,
      },
    },
    {
      payload: {
        kind: "tool_result",
        call_id: "call-2",
        tool_id: "tool-2",
        tool_name: "read_blocks",
        ok: true,
        fingerprint: "e".repeat(64),
        artifacts: [
          {
            port: "blocks",
            artifact: {
              artifact_id: BLOCKS_ARTIFACT,
              artifact_type: "table.data",
              schema_version: 1,
            },
          },
          {
            port: "markdown",
            artifact: {
              artifact_id: TEXT_ARTIFACT,
              artifact_type: "scalar.text",
              schema_version: 1,
            },
          },
        ],
        model_view: "two blocks",
        error: null,
      },
    },
    { payload: { kind: "assistant_message", text: "It greets a gentleman." } },
    { payload: { kind: "confirmation_requested", tool_calls: 10, limit: 10 } },
  ].map((event, index) => ({
    sequence: index + 1,
    turn_id: "55555555-5555-4555-8555-555555555555",
    created_at: NOW,
    ...event,
  }));
  const sent: unknown[] = [];
  // What the card shows once it holds the result.
  await page.route(`**/artifacts/${TEXT_ARTIFACT}/content`, (route) =>
    route.fulfill({ contentType: "text/plain", body: "dear sir" }),
  );
  await page.route(`**/artifacts/${ROW_ARTIFACT}/content`, (route) =>
    // As the API stores a text value; the card shows the words, not the wrapper.
    route.fulfill({ json: { value: "the **second** block" } }),
  );
  await page.route(`**/artifacts/${BLOCKS_ARTIFACT}/table/schema*`, (route) =>
    route.fulfill({
      json: {
        artifact_id: BLOCKS_ARTIFACT,
        columns: [
          { id: "kind", title: "kind", value_type: "text" },
          { id: "text", title: "text", value_type: "text" },
        ],
        total_rows: 2,
      },
    }),
  );
  await page.route(`**/artifacts/${BLOCKS_ARTIFACT}/table/page*`, (route) =>
    route.fulfill({
      json: {
        columns: [
          { id: "kind", title: "kind", value_type: "text" },
          { id: "text", title: "text", value_type: "text" },
        ],
        rows: [
          {
            kind: { display: "header", truncated: false },
            text: { display: "- 8 -", truncated: false },
          },
          {
            kind: { display: "table", truncated: false },
            text: { display: "<table><td>the second block", truncated: true },
          },
        ],
        offset: 0,
        limit: 100,
        total_rows: 2,
        column_offset: 0,
        total_columns: 2,
      },
    }),
  );
  await page.route(
    `**/artifacts/${BLOCKS_ARTIFACT}/table/text-artifacts`,
    (route) =>
      route.fulfill({
        json: {
          rows: [
            { row_index: 0, artifact: null },
            {
              row_index: 1,
              artifact: {
                artifact_id: ROW_ARTIFACT,
                artifact_type: "scalar.text",
                schema_version: 1,
              },
            },
          ],
          total_rows: 2,
        },
      }),
  );
  await page.route("**/api/**/agents/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    const parts = path.split("/");
    const graphId = parts[parts.indexOf("graphs") + 1] ?? "";
    const agentId = parts[parts.indexOf("agents") + 1] ?? "";
    let json: unknown = null;
    if (path.endsWith("/model"))
      json = {
        source: "deployment",
        model_name: "Test model",
        base_url: "",
        key_configured: false,
      };
    else if (path.endsWith("/conversations") && method === "GET")
      json = {
        conversations: [
          {
            id: CONVERSATION,
            title: "New conversation",
            agent_id: agentId,
            graph_id: graphId,
            created_at: NOW,
            updated_at: NOW,
          },
        ],
      };
    else if (path.endsWith("/events"))
      json = {
        events,
        last_sequence: events.length,
        next_sequence: events.length,
      };
    else if (path.endsWith("/active-turn")) json = null;
    else if (path.endsWith("/turns")) {
      sent.push(route.request().postDataJSON());
      json = {
        id: "66666666-6666-4666-8666-666666666666",
        client_turn_id: route.request().postDataJSON().client_turn_id,
        conversation_id: CONVERSATION,
        status: "running",
      };
    } else throw new Error(`Unexpected Agent request ${method} ${path}`);
    await route.fulfill({ json });
  });

  await page.getByRole("button", { name: "Add node", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Search nodes" })
    .fill("Test text source");
  await page.getByRole("option", { name: /^Test text source/ }).click();
  await page
    .getByRole("button", { name: "Add to canvas", exact: true })
    .click();
  await page.getByRole("button", { name: "Add Agent", exact: true }).click();
  // Up and away from the canvas actions, as the Agent spec does: the settings card
  // is taller with tools in it and would otherwise sit under them.
  const placed = page.locator(".react-flow__node-grafyAgent");
  const header = placed.locator("header");
  const box = await header.boundingBox();
  if (!box) throw new Error("Agent not visible");
  await page.mouse.move(box.x + 35, box.y + 10);
  await page.mouse.down();
  await page.mouse.move(box.x - 80, box.y - 260, { steps: 12 });
  await page.mouse.up();
  page.once("dialog", (dialog) => void dialog.accept("Agent tools"));
  const nav = page.getByRole("button", { name: "Open navigation" });
  if (await nav.isVisible()) await nav.click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/);

  // Connecting the node: it is offered from the Agent's own settings.
  const agent = page.locator(".react-flow__node-grafyAgent");
  await agent.getByRole("button", { name: "Configure", exact: true }).click();
  const settings = page.getByRole("form", { name: "Agent settings" });
  await settings
    .getByRole("combobox", { name: "Add a node as a tool" })
    .selectOption({ label: "Test text source" });
  await expect(
    settings.getByRole("group", { name: "Tool test_text_source" }),
  ).toBeVisible();
  await settings.getByRole("button", { name: "Save", exact: true }).click();
  await expect(settings).toHaveCount(0);
  // It stuck: the saved Agent still carries the tool.
  await agent.getByRole("button", { name: "Configure", exact: true }).click();
  await expect(
    page.getByRole("group", { name: "Tool test_text_source" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();

  // The thread tells what the model did.
  await expect(agent.getByText("Called")).toBeVisible();
  await expect(
    agent.getByRole("group", { name: "Tool result: test_text_source" }),
  ).toContainText("returned");
  const chip = agent.getByLabel(/^text: /);
  await expect(chip).toBeVisible();

  // Asked whether to go on, the person can.
  await agent.getByRole("button", { name: "Continue", exact: true }).click();
  await expect.poll(() => sent.length).toBe(1);

  // A result is a thing: it can be taken out of the thread and put on the canvas.
  // A drag is a pointer gesture; a touch screen has no native drag to give it.
  if ((page.viewportSize()?.width ?? 0) < 800) return;
  const cards = page.locator("[data-artifact-card-id]");
  await expect(cards).toHaveCount(0);
  await chip.dragTo(page.locator(".react-flow"), {
    targetPosition: { x: 520, y: 520 },
  });
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toContainText("dear sir");

  // So can what is inside one: a row of a table result comes out as its own text.
  await agent.getByRole("button", { name: "2 results" }).click();
  await page.getByRole("menuitem", { name: /^blocks/ }).click();
  const row = page.getByRole("menuitem", { name: /table: the second block/ });
  await expect(row).toBeVisible();
  // A row with nothing in it cannot be taken.
  await expect(
    page.getByRole("menuitem", { name: /header: - 8 -/ }),
  ).toHaveAttribute("aria-disabled", "true");
  await row.dragTo(page.locator(".react-flow"), {
    targetPosition: { x: 520, y: 720 },
  });
  await expect(cards).toHaveCount(2);
  await expect(cards.last()).toContainText("the **second** block");
  await expect(cards.last()).not.toContainText('"value"');
  // Its words can be read as Markdown, once the card is selected.
  await cards.last().click();
  await cards
    .last()
    .getByRole("radiogroup", { name: "Read this text as" })
    .getByText("Markdown", { exact: true })
    .click();
  await expect(cards.last()).toContainText("the second block");
  await expect(row).toHaveCount(0);
});

import { expect, test } from "./workbench.fixture";
test("places an Agent, streams a reply, stops and reloads durable history", async ({
  page,
  agentRoom,
}) => {
  // Forward the existing fixture room while retaining its outbound model boundary.
  // Agent HTTP state below is durable across page reloads.
  let conversation: Record<string, unknown> | null = null;
  let events: Record<string, unknown>[] = [];
  let active: Record<string, unknown> | null = null;
  let configuredKey = false;
  let agentId = "";
  let graphId = "";
  const now = "2026-01-01T00:00:00Z";
  await page.route("**/api/**/agents/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    const parts = path.split("/");
    graphId = parts[parts.indexOf("graphs") + 1] ?? "";
    agentId = parts[parts.indexOf("agents") + 1] ?? "";
    let json: unknown = null;
    if (path.endsWith("/key")) {
      configuredKey = method === "PUT";
      json = { agent_id: agentId, configured: configuredKey };
    } else if (path.endsWith("/model"))
      json = {
        source: "deployment",
        model_name: "Test model",
        base_url: "",
        key_configured: configuredKey,
      };
    else if (path.endsWith("/conversations") && method === "GET")
      json = { conversations: conversation ? [conversation] : [] };
    else if (path.endsWith("/conversations")) {
      conversation = {
        id: "44444444-4444-4444-8444-444444444444",
        title: "New conversation",
        agent_id: agentId,
        graph_id: graphId,
        created_at: now,
        updated_at: now,
      };
      json = conversation;
    } else if (path.endsWith("/events"))
      json = {
        events,
        last_sequence: events.length,
        next_sequence: events.length,
      };
    else if (path.endsWith("/active-turn")) json = active;
    else if (path.endsWith("/turns")) {
      const body = route.request().postDataJSON();
      const turn = {
        id: "55555555-5555-4555-8555-555555555555",
        client_turn_id: body.client_turn_id,
        conversation_id: conversation?.id,
        status: "running",
      };
      events = [
        {
          sequence: 1,
          turn_id: turn.id,
          created_at: now,
          payload: { kind: "user_message", text: body.text },
        },
      ];
      active = {
        turn,
        message_id: "66666666-6666-4666-8666-666666666666",
        partial_text: "Hello 😀",
        partial_offset: 7,
      };
      json = turn;
    } else if (path.endsWith("/cancel")) {
      const turn = active?.turn;
      events.push({
        sequence: 2,
        turn_id: "55555555-5555-4555-8555-555555555555",
        created_at: now,
        payload: { kind: "assistant_message", text: "Hello 😀, final answer" },
      });
      active = null;
      json = turn;
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
  await expect(
    page
      .locator(".react-flow__node.selected")
      .filter({ hasText: "Test text source" }),
  ).toHaveCount(0);

  const node = page.locator(".react-flow__node-grafyAgent");
  await expect(node).toBeVisible();
  const header = node.locator("header");
  const box = await header.boundingBox();
  if (!box) throw new Error("Agent not visible");
  await page.mouse.move(box.x + 35, box.y + 10);
  await page.mouse.down();
  await page.mouse.move(box.x - 80, box.y - 80, { steps: 12 });
  await page.mouse.up();
  await expect
    .poll(async () => (await header.boundingBox())?.x)
    .toBeLessThan(box.x - 30);
  page.once("dialog", (dialog) => void dialog.accept("Agent Project"));
  const nav = page.getByRole("button", { name: "Open navigation" });
  if (await nav.isVisible()) await nav.click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/);
  await node
    .getByRole("button", { name: "New conversation", exact: true })
    .click();
  await node
    .getByRole("textbox", { name: "Message", exact: true })
    .fill("Hello");
  await node.getByRole("button", { name: "Send", exact: true }).click();
  await expect(node.getByLabel("Streaming reply")).toHaveText("Hello 😀");
  if (!agentRoom.send) throw new Error("Project room did not connect");
  agentRoom.send({
    protocol_version: 1,
    type: "agent.delta",
    graph_id: graphId,
    agent_id: agentId,
    conversation_id: "44444444-4444-4444-8444-444444444444",
    turn_id: "55555555-5555-4555-8555-555555555555",
    message_id: "66666666-6666-4666-8666-666666666666",
    offset: 7,
    text: ", streaming",
  });
  await expect(node.getByLabel("Streaming reply")).toHaveText(
    "Hello 😀, streaming",
  );
  await expect(
    node.getByRole("textbox", { name: "Message", exact: true }),
  ).toBeDisabled();
  await node.getByRole("button", { name: "Stop", exact: true }).click();
  await expect(
    node.getByText("Hello 😀, final answer", { exact: true }),
  ).toBeVisible();
  await expect(node.getByLabel("Streaming reply")).toHaveCount(0);
  await node.getByRole("button", { name: "Configure", exact: true }).click();
  // Settings open beside the Agent (or in a dialog where there is no room),
  // and the conversation stays as it was while they are open.
  const settings = page.getByRole("form", { name: "Agent settings" });
  await expect(settings).toBeVisible();
  await expect(
    node.getByText("Hello 😀, final answer", { exact: true }),
  ).toBeVisible();
  // The key belongs to an Agent's own endpoint, so it is offered once one is chosen.
  await expect(settings.getByLabel("API key", { exact: true })).toHaveCount(0);
  await settings
    .getByRole("radio", { name: "Custom endpoint", exact: true })
    .click();
  await settings.getByLabel("API key", { exact: true }).fill("test-only-key");
  await settings.getByRole("button", { name: "Set key", exact: true }).click();
  await expect(settings.getByLabel("API key", { exact: true })).toHaveValue("");
  await expect.poll(() => configuredKey).toBe(true);
  await settings
    .getByRole("button", { name: "Clear key", exact: true })
    .click();
  await expect.poll(() => configuredKey).toBe(false);
  await settings.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(settings).toHaveCount(0);
  await page.reload();
  await expect(node).toBeVisible();
  await expect(
    node.getByText("Hello 😀, final answer", { exact: true }),
  ).toBeVisible();
});

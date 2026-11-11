import { test } from "@e2e-dev/web";
import { expect } from "e2e";

test("sign in, create a Graph, and run a Text input", async ({
  app,
  browser,
  screen,
}) => {
  await browser.onDialog((dialog) => dialog.accept("E2E pilot"));
  await app.open("/");
  await screen.getByRole("button", { name: "Continue with SSO" }).click();
  await screen
    .getByRole("textbox", { name: "Username or email" })
    .fill("owner");
  // Public fixture account in the disposable repository realm.
  await screen
    .getByRole("textbox", { name: "Password", exact: true })
    .fill("owner");
  await screen.getByRole("button", { name: "Sign In", exact: true }).click();
  await expect(
    browser.locator(".grafy-workspace-rail__account-email"),
  ).toContainText("owner@grafy.local", { timeout: 120_000 });

  const rail = screen.getByRole("navigation", { name: "Graphs" });
  await rail.getByRole("button", { name: "New graph" }).click();
  await expect(browser).toHaveURL(/\/workspaces\/[^/]+\/projects\/new$/, {
    timeout: 120_000,
  });
  await browser.locator(".react-flow__pane").secondaryTap();
  await screen.getByRole("menuitem", { name: "Add node", exact: true }).hover();
  await screen.getByRole("menuitem", { name: "Text", exact: true }).hover();
  await screen
    .getByRole("menuitem", { name: "Text input", exact: true })
    .click();
  const node = browser
    .locator(".react-flow__node")
    .filter({ hasText: "Text input" });
  await expect(node).toHaveCount(1);
  await node.getByRole("textbox").fill("Hello from e2e");
  await rail.getByRole("button", { name: /^Save/ }).click();
  await expect(browser).toHaveURL(
    /\/workspaces\/[^/]+\/projects\/[0-9a-f-]{36}$/,
  );
  await expect(rail.getByRole("button", { name: /^Save/ })).toHaveText("Saved");
  await node.click();
  await screen.getByRole("button", { name: "Run", exact: true }).click();
  await expect(
    node.getByRole("status", { name: "Execution succeeded", exact: true }),
  ).toBeVisible();
});

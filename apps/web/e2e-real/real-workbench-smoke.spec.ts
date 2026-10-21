import { expect, test, type Page } from "@playwright/test";

/**
 * The one journey that exercises both applications as shipped: a browser signs in
 * through a real OIDC round trip with the repository's own provider, creates a
 * graph, edits a node, and finds that edit again after a reload. Nothing is
 * stubbed with `page.route`; every response comes from the FastAPI process behind
 * the Next proxy.
 *
 * `npm run test:e2e:real` starts the API, the dev server, and Keycloak; see
 * `scripts/real-smoke.mjs`.
 */

const origin = process.env.REAL_SMOKE_ORIGIN;
if (!origin) {
  throw new Error(
    "REAL_SMOKE_ORIGIN is not set. Run this suite with npm run test:e2e:real.",
  );
}

// The test user the repository's committed realm ships with. A fixture, not a
// secret: it exists in a container that this run created and removes, so that
// signing in is a step the suite has to take.
const ISSUER_USER = "owner";
const ISSUER_PASSWORD = "owner";
const ISSUER_EMAIL = "owner@grafy.local";

const GRAPH_NAME = "Real backend smoke";
// Distinct per run, so a value read back after a reload cannot be a cached one.
const NODE_TEXT = `persisted ${Date.now().toString(36)}`;

// The dev server compiles a route the first time it is asked for it, and this app
// compiles with Babel rather than SWC. A cold run — every CI run, and any local run
// after the build cache is gone — can spend well over half a minute on a single
// route, so the three navigations that reach a new route get a wider ceiling than an
// ordinary assertion. The rest keep the config's 30s and fail fast.
const COLD_ROUTE_MS = 120_000;

const rail = (page: Page) => page.getByRole("navigation", { name: "Graphs" });
const saveButton = (page: Page) =>
  rail(page).getByRole("button", { name: /^Save/ });
const textNode = (page: Page) =>
  page.locator(".react-flow__node").filter({ hasText: "Text input" });
// Keycloak gives its visibility toggle an aria-controls on the password input, so
// the label alone resolves to two elements.
const issuerField = (page: Page, name: string) =>
  page.getByRole("textbox", { name });
const loginStart = (page: Page) =>
  page.getByRole("button", { name: "Continue with SSO" });

/** The canvas menu opens under the pointer, which needs a desktop mouse. */
async function addTextNode(page: Page): Promise<void> {
  const pane = page.locator(".react-flow__pane");
  await expect(pane).toBeVisible();
  const box = await pane.boundingBox();
  if (!box) throw new Error("The canvas pane has no box");
  await page.mouse.click(box.x + 150, box.y + 150, { button: "right" });
  const menu = page.getByRole("menu", { name: "Canvas menu" });
  await menu.getByRole("menuitem", { name: "Add node" }).hover();
  await page.getByRole("menuitem", { name: "Text", exact: true }).hover();
  await page.getByRole("menuitem", { name: "Text input", exact: true }).click();
  await expect(menu).toBeHidden();
  await expect(textNode(page)).toHaveCount(1);
}

test("the provider signs a person in, and their graph edit survives a reload", async ({
  page,
}) => {
  // Naming a graph on first save goes through a prompt; the suite names it.
  page.on("dialog", (dialog) => void dialog.accept(GRAPH_NAME));

  // 1. An unauthenticated visit offers the login start. No session is handed over.
  await page.goto(`${origin}/graphs`);
  await expect(loginStart(page)).toBeVisible();

  // 2. A wrong password is refused by the provider itself, and Grafy mints nothing
  //    for a login that never happened: back at the app, there is still no session.
  await loginStart(page).click();
  // The provider's own login page, from the pinned image in the smoke compose file.
  await expect(
    page.getByRole("heading", { name: "Sign in to your account" }),
  ).toBeVisible();
  await issuerField(page, "Username or email").fill(ISSUER_USER);
  await issuerField(page, "Password").fill("not-the-fixture-password");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByText("Invalid username or password.")).toBeVisible();
  await page.goto(`${origin}/graphs`);
  await expect(loginStart(page)).toBeVisible();

  // 3. The callback exchanges the code, provisions that identity, and sets its own
  //    session cookie: the app shows the signed-in account, not a fixture user.
  await loginStart(page).click();
  await issuerField(page, "Username or email").fill(ISSUER_USER);
  await issuerField(page, "Password").fill(ISSUER_PASSWORD);
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(
    page.locator(".grafy-workspace-rail__account-email"),
  ).toContainText(ISSUER_EMAIL, { timeout: COLD_ROUTE_MS });

  // 4. A graph made through the UI gets a server-assigned id in its own URL.
  await rail(page).getByRole("button", { name: "New graph" }).click();
  await page.waitForURL(/\/workspaces\/[^/]+\/graphs\/new$/, {
    timeout: COLD_ROUTE_MS,
  });
  await addTextNode(page);
  const field = textNode(page).locator("textarea");
  await expect(field).toHaveCount(1);
  await field.fill(NODE_TEXT);

  // 5. Saving creates the durable graph. The room and the checkpoint are the API's,
  //    so the URL changes to the id the API issued.
  await saveButton(page).click();
  await page.waitForURL(/\/workspaces\/[^/]+\/graphs\/[0-9a-f-]{36}$/, {
    timeout: COLD_ROUTE_MS,
  });
  const savedUrl = page.url();
  await expect(saveButton(page)).toHaveText("Saved");

  // 6. A reload asks the API for the graph. Both the node and its text come out of
  //    the saved document, not out of this page's memory.
  await page.reload();
  await expect(textNode(page)).toHaveCount(1);
  await expect(textNode(page).locator("textarea")).toHaveValue(NODE_TEXT);
  expect(page.url()).toBe(savedUrl);

  // 7. The graph browser lists it by name: it exists as a graph of that workspace,
  //    not only as a canvas that can be redrawn.
  await page.goto(`${origin}/graphs`);
  await expect(
    page.getByRole("link", { name: new RegExp(GRAPH_NAME) }),
  ).toBeVisible();
});

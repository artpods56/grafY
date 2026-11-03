import { request, type FullConfig } from "@playwright/test";

/**
 * The dev server compiles a route the first time something asks for it, and a
 * lazy compile mid-suite broadcasts a webpack hot-update that reloads every
 * open page. A page reloaded mid-journey is a page with its panels closed and
 * its drafts gone, which is how a spec watching a just-opened panel fails with
 * “element(s) not found” on a server that is perfectly healthy. The webServer
 * probe warms only the one address it checks; this warms every address the
 * suite navigates to, once, before any test drives a page.
 */
const WARM_PATHS = [
  "/graphs",
  "/workspaces/mobile-test/projects",
  "/workspaces/mobile-test/projects/new",
];

const SERVER_DEADLINE_MS = 180_000;
const RETRY_DELAY_MS = 1_000;

async function warm(
  context: Awaited<ReturnType<typeof request.newContext>>,
  path: string,
): Promise<void> {
  const deadline = Date.now() + SERVER_DEADLINE_MS;
  let lastFailure = "the server never answered";
  for (;;) {
    try {
      const response = await context.get(path, { timeout: 60_000 });
      if (response.ok()) return;
      lastFailure = `answered ${response.status()}`;
    } catch (error) {
      lastFailure = String(error);
    }
    if (Date.now() > deadline) {
      throw new Error(`Dev server never served ${path}: ${lastFailure}`);
    }
    await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
  }
}

export default async function globalSetup(config: FullConfig): Promise<void> {
  const baseURL = config.projects[0]?.use?.baseURL;
  if (typeof baseURL !== "string") {
    throw new Error("The e2e projects must carry a baseURL for the warm-up");
  }
  const context = await request.newContext({ baseURL });
  try {
    // One at a time: parallel cold compiles are exactly the churn this avoids.
    for (const path of WARM_PATHS) await warm(context, path);
  } finally {
    await context.dispose();
  }
}

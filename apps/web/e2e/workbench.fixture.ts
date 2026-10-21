import { expect, test as base } from "@playwright/test";
import type { Page } from "@playwright/test";

import { libraryStub } from "./library-folders-stub";
import type {
  NodeRegistry,
  SavedGraphList,
  Session,
  Workspace,
  WorkspaceInvitationForRecipient,
} from "../src/lib/api/contract";

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const WORKBENCH_PATH = "/workspaces/mobile-test/graphs/new";

const session = {
  id: "22222222-2222-4222-8222-222222222222",
  user_id: "33333333-3333-4333-8333-333333333333",
  display_name: "Mobile Test User",
  email: "mobile-test@grafy.invalid",
  created_at: "2026-01-01T00:00:00Z",
  expires_at: "2030-01-01T00:00:00Z",
  last_used_at: "2026-01-01T00:00:00Z",
  revoked_at: null,
  current: true,
} satisfies Session;

const workspace = {
  id: WORKSPACE_ID,
  slug: "mobile-test",
  name: "Mobile test",
  kind: "personal",
  role: "owner",
  capabilities: [
    "view_graph",
    "view_artifacts",
    "view_materializations",
    "view_history",
    "view_execution",
    "join_graph_room",
    "publish_presence",
    "create_graph",
    "edit_graph",
    "checkpoint_graph",
    "execute_graph",
    "cancel_execution",
    "publish_module",
    "manage_secrets",
    "delete_graph",
    "manage_members",
    "rename_workspace",
  ],
} satisfies Workspace;

const savedGraphs = { graphs: [] } satisfies SavedGraphList;
export const nodeRegistry = {
  artifact_conversions: [],
  artifact_types: [],
  nodes: [
    {
      operator_id: "test.text_source",
      operator_version: 1,
      plugin_slug: "builtin",
      origin: "builtin",
      title: "Test text source",
      description: "Produces text for browser interaction tests.",
      catalog_visible: true,
      runnable: true,
      config_schema: {},
      input_schema: {},
      output_schema: {},
      inputs: [],
      outputs: [
        {
          name: "text",
          title: "Text",
          description: "Produced text.",
          direction: "output",
          artifact_type: { id: "scalar.text", schema_version: 1 },
          artifact_type_variable: null,
          shape: "one",
          accepted_shapes: ["one"],
          instance_plugs: false,
          variadic: false,
          required: true,
        },
      ],
    },
    {
      operator_id: "test.text_sink",
      operator_version: 1,
      plugin_slug: "builtin",
      origin: "builtin",
      title: "Test text sink",
      description: "Accepts text for browser interaction tests.",
      catalog_visible: true,
      runnable: true,
      config_schema: {},
      input_schema: {},
      output_schema: {},
      inputs: [
        {
          name: "text",
          title: "Text",
          description: "Text to accept.",
          direction: "input",
          artifact_type: { id: "scalar.text", schema_version: 1 },
          artifact_type_variable: null,
          shape: "one",
          accepted_shapes: ["one"],
          instance_plugs: false,
          variadic: false,
          required: true,
        },
      ],
      outputs: [],
    },
  ],
  plugins: [
    {
      slug: "builtin",
      title: "Built-in",
      origin: "builtin",
      entry_kind: "plugin",
      runnable: true,
    },
  ],
  unavailable_modules: [],
} satisfies NodeRegistry;
const invitations: readonly WorkspaceInvitationForRecipient[] = [];

/**
 * `/api/v1/workspaces/{workspace_id}/{tail}` — the shape every location-scoped
 * endpoint shares, so `graphs` and `nodes` are matched as siblings by one read
 * of the tail. Matching them in sequence instead lets a broad `graphs` rule
 * swallow `/nodes`, and a spec then fails on a catalog that never arrived.
 */
const WORKSPACE_SCOPED = /^\/api\/v1\/workspaces\/([^/]+)\/([^/]+)$/;

export interface GrafyApiFixtures {
  readonly workspaces: readonly Workspace[];
  /** Saved-graph lists keyed by workspace id, the way the API addresses them. */
  readonly graphsByWorkspace: Readonly<Record<string, SavedGraphList>>;
  readonly registry?: NodeRegistry;
  readonly invitations?: readonly WorkspaceInvitationForRecipient[];
}

/** The one-person, one-workspace world every workbench spec already expects. */
export const workbenchApiFixtures: GrafyApiFixtures = {
  workspaces: [workspace],
  graphsByWorkspace: { [WORKSPACE_ID]: savedGraphs },
  registry: nodeRegistry,
};

type FixtureBody =
  | Session
  | readonly Workspace[]
  | SavedGraphList
  | NodeRegistry
  | readonly WorkspaceInvitationForRecipient[];

/**
 * The answer this fixture world gives for one GET, or `undefined` when it has
 * none: an endpoint it was not given, or a workspace it was given no graph list
 * for. Both end in the same loud 501 below.
 */
function fixtureBody(
  path: string,
  fixtures: GrafyApiFixtures,
): FixtureBody | undefined {
  if (path === "/api/v1/auth/session") return session;
  if (path === "/api/v1/workspaces") return fixtures.workspaces;
  if (path === "/api/v1/me/invitations")
    return fixtures.invitations ?? invitations;

  const scoped = path.match(WORKSPACE_SCOPED);
  const workspaceId = scoped?.[1];
  const tail = scoped?.[2];
  if (workspaceId === undefined || tail === undefined) return undefined;
  // A saved graph's own document (`/graphs/{graph_id}`) is deliberately not
  // here: these specs author drafts, and a spec that starts opening one should
  // see a 501 rather than a blank canvas it mistakes for the app being broken.
  if (tail === "nodes") return fixtures.registry;
  if (tail === "graphs") return fixtures.graphsByWorkspace[workspaceId];
  return undefined;
}

/**
 * Answer the endpoints the web app calls, and hand back a reader for anything
 * this fixture did not cover. A spec that starts asking for an endpoint it was
 * not given sees a 501 and a non-empty list instead of a silent hole.
 */
export async function mockGrafyApi(
  page: Page,
  fixtures: GrafyApiFixtures = workbenchApiFixtures,
): Promise<() => readonly string[]> {
  const unhandledApiRequests: string[] = [];

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    const body = method === "GET" ? fixtureBody(path, fixtures) : undefined;

    if (body !== undefined) {
      await route.fulfill({ json: body });
      return;
    }

    const unhandledRequest = `${method} ${path}`;
    unhandledApiRequests.push(unhandledRequest);
    await route.fulfill({
      status: 501,
      contentType: "application/json",
      body: JSON.stringify({
        detail: `Unhandled Playwright API fixture: ${unhandledRequest}`,
      }),
    });
  });

  return () => unhandledApiRequests;
}

export const test = base.extend<{ registry: NodeRegistry }>({
  registry: [nodeRegistry, { option: true }],
  page: async ({ page, registry }, runTest) => {
    const unhandled = await mockGrafyApi(page, {
      ...workbenchApiFixtures,
      registry,
    });

    // The Library folder tree is the server's now, so every workbench test needs
    // it: the panel lists it on open and an artifact card reads its path from it.
    // Registered after the catch-all above, so these routes win for /library.
    await libraryStub(page);

    await page.goto(WORKBENCH_PATH);
    await expect(page.locator(".react-flow")).toBeVisible();
    await runTest(page);
    expect(unhandled(), "Unhandled Playwright API requests").toEqual([]);
  },
});

export { expect };

import { expect, test as base } from "@playwright/test";

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
    "manage_module_library",
    "create_template",
    "manage_template_library",
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
const invitations = [] satisfies WorkspaceInvitationForRecipient[];

export const test = base.extend<{ registry: NodeRegistry }>({
  registry: [nodeRegistry, { option: true }],
  page: async ({ page, registry }, runTest) => {
    const unhandledApiRequests: string[] = [];
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      const method = request.method();

      let body:
        | Session
        | readonly Workspace[]
        | SavedGraphList
        | NodeRegistry
        | readonly WorkspaceInvitationForRecipient[]
        | undefined;
      if (method === "GET" && path === "/api/v1/auth/session") {
        body = session;
      } else if (method === "GET" && path === "/api/v1/workspaces") {
        body = [workspace];
      } else if (method === "GET" && path === "/api/v1/me/invitations") {
        body = invitations;
      } else if (
        method === "GET" &&
        path === `/api/v1/workspaces/${WORKSPACE_ID}/graphs`
      ) {
        body = savedGraphs;
      } else if (
        method === "GET" &&
        path === `/api/v1/workspaces/${WORKSPACE_ID}/nodes`
      ) {
        body = registry;
      }

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

    await page.goto(WORKBENCH_PATH);
    await expect(page.locator(".react-flow")).toBeVisible();
    await runTest(page);
    expect(unhandledApiRequests, "Unhandled Playwright API requests").toEqual(
      [],
    );
  },
});

export { expect };

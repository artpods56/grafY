# Connect an MCP client to Grafy

The API serves a Model Context Protocol server over stateless Streamable HTTP with
JSON responses. Every tool acts as your token through the same REST routes the
Workbench uses, so a tool can do exactly what the token could do over HTTP and
nothing more. A personal access token is bound to one Workspace, and every tool takes
that Workspace from the token, never from an argument. See ADR 0023.

## Get a token

Locally, once the owner has signed in to this database, run `just dev-pat`. It mints a
new PAT for the owner's personal Workspace and prints it with the workspace id. It
defaults to the `view_project` scope and a one-day lifetime; repeat `--scope` for more
capabilities and `--name` labels it in the UI. Run it from the same checkout and with
the same settings as the API.

```bash
just dev-pat --json --name 'Claude Code' \
  --scope view_project --scope view_artifacts --scope view_runs
```

The JSON contains `token` and `workspace_id`. The requested lifetime must fit
`GRAFY_PERSONAL_ACCESS_TOKEN_MAX_LIFETIME_SECONDS`.

In a deployment, sign in to the Workbench and create the token under **Access tokens**
on the Workspace's settings page (`/workspaces/{workspace_id}/settings`). That screen is
the only way in: the token routes accept a browser session, not a token, so a PAT
cannot mint another PAT.

Grant only the scopes a client needs. A token can hold any of:

| Purpose | Scopes |
| --- | --- |
| Read projects, canvases, results | `view_project`, `view_artifacts`, `view_runs` |
| Edit canvases, create projects | `edit_project`, `create_project` |
| Checkpoints and restore | `checkpoint_project` |
| Start and cancel runs | `start_run`, `cancel_run` |
| Node secrets | `manage_secrets` |

Effective permission is the token's scopes intersected with the holder's Workspace
role, so an editor token in a viewer's Workspace still cannot edit. Revoke a token on
the same **Access tokens** screen; anything using it stops at once. Tokens also expire
on their own.

## Connect a client

The endpoint is `/mcp` on the API, and `/api/mcp` behind the gateway:

- Local: `http://localhost:8000/mcp`
- Deployment: `https://your-grafy-host/api/mcp`

Authenticate with `Authorization: Bearer <token>`. With Claude Code:

```bash
claude mcp add --transport http grafy http://localhost:8000/mcp \
  --header "Authorization: Bearer $GRAFY_PAT"
```

Any Streamable-HTTP client takes the same shape as a JSON config entry:

```json
{
  "mcpServers": {
    "grafy": {
      "type": "http",
      "url": "https://your-grafy-host/api/mcp",
      "headers": { "Authorization": "Bearer ${GRAFY_PAT}" }
    }
  }
}
```

Keep the token out of committed files and out of shell history you share. The endpoint
refuses a request that also carries the browser session cookie, so signing in to the
Workbench never authorizes MCP.

## What the tools cover

| Area | Examples |
| --- | --- |
| discovery | `get_workspace`, `list_nodes`, `describe_node`, `list_packs` |
| projects | `list_projects`, `create_project`, `add_graph`, `archive_project`, `restore_checkpoint` |
| authoring | `author_graph`, `apply_project_commands`, `checkpoint_project` |
| canvas | `get_canvas`, `add_nodes`, `connect`, `configure_node`, `move_items`, `arrange_graph` |
| runs | `start_run`, `wait_for_run`, `list_instances`, `get_instance_result`, `cancel_run` |
| library | `list_library`, `upload_file`, `save_result_to_library`, `create_library_folder` |
| artifacts | `list_authorable_artifact_types`, `create_artifact`, `read_artifact_text`, `read_table_page`, `query_table`, `get_geo_render`, `get_image_info` |
| secrets | `get_node_secrets`, `set_node_secret`, `bind_node_secret`, `verify_node_secret` |
| agents | `list_agent_conversations`, `send_agent_message`, `read_agent_events`, `cancel_agent_turn` |

The server also offers a `build-graph` prompt that plans a Graph for a goal, and two
resources: `grafy://catalog` (every node the Workspace can use, with its ports) and
`grafy://projects/{project_id}/graphs/{graph_id}/canvas`. Artifacts are referenced as
`id@version`, for example `file.csv@1`.

## Troubleshooting

- **401 from the endpoint.** The bearer token is missing, expired, revoked, or not a
  PAT — or the request also carries the browser session cookie.
- **A tool error containing 403.** The token lacks that scope, or the holder's role
  does not have the capability in this Workspace.
- **A 409 on a canvas edit.** The Graph changed since you read it. Call `get_canvas`
  again and retry against the new head; a stale edit is refused rather than
  overwriting someone else's change.
- **A 413.** The request body is over the 4 MiB the gate reads. Large files go through
  the staged upload API instead — `upload_file` is inline only and refuses anything
  over 2 MiB.

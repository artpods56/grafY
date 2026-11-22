# Canvas lab reference

Run `bun install` in `apps/web` in a fresh worktree. Run `just lab-web 3301`
from the repo root. Choose a free loopback port per worktree. The recipe sets
`NEXT_PUBLIC_GRAFY_DEV_SESSION=1`, so the sandbox renders with its recorded
registry and skips the API session request and Keycloak.

```text
http://127.0.0.1:3301/sandbox/cell-canvas?nodes=ask-model,schema-builder&tab=nodes&lab=1:well:punched,fill:72&sel=ask-model&theme=dark&freeze=1&inspect=1
```

| Query | Effect |
| --- | --- |
| `lab=1:<key>:<value>,…` | Overrides canvas appearance and routing. `help=1` lists keys, allowed values, and ranges. |
| `fixture=ask-a-model@1` | Uses the versioned fixture catalog. Omit it to use the same catalog by default. |
| `nodes=ask-model,schema-builder,text-input` | Shows the named nodes in the canvas. Omit `nodes` for Ask a model. Use `nodes=` for an empty canvas. |
| `tab=nodes` | Opens the Nodes tab. Omit the parameter to open Canvas. |
| `sel=ask-model` | Selects the card and uses its selected chrome. |
| `hot=port:ask-model/input:messages` | Highlights the input named `messages`. The address is `port:<card-id>/<input-or-output>:<port-id>`. `hover` accepts the same address. |
| `zoom=1` | Centres the card at 100%. Values range from 0.15 to 2. Omit the parameter to fit. |
| `freeze=1` | Disables CSS transitions and animations in the fixture. |
| `theme=light` or `theme=dark` | Sets the fixture's colour scheme. Omit the parameter to inherit the app theme. |
| `inspect=1` | Publishes geometry at `window.__grafy` and prints a card summary in the browser console. |

Use **Canvas** for appearance, pipe routing, zoom, and render diagnostics.
Use **Nodes** to choose visible nodes, select a node, or highlight one of its ports.
The controls update the query without reloading. **Copy link** copies the current
URL. **Reset** clears the render options. Use a fixed viewport and zoom for
geometry comparisons.

`window.__grafy` contains `look`, `routing`, and a live `cards` snapshot.
Each card has an `id`, `rect`, `ports`, and `tabs`. Port entries include a
direction and centre. Tab entries include the row. Rectangles report viewport
CSS pixels after zoom. The DOM hooks are `data-cell-card`, `data-card-id`,
`data-port-id`, `data-port-direction`, `data-port-tab`, and `data-port-row`.

For an authenticated workbench, use a normal dev server. Append `lab=1` to the
workbench URL or start its server with `NEXT_PUBLIC_GRAFY_DEV_LO=1`. Open
**Canvas lab** from the canvas context menu. The workbench accepts the same
versioned appearance and routing query. Existing grid preferences apply until
the URL sets `grid`.

The sandbox needs no API process. When a task needs the running API, reuse its
session and workspace root. The API holds an exclusive workspace lock. Stop
only processes whose PIDs you captured when starting them.

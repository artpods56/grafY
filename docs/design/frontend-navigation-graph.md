# Frontend navigation graph

- **Status:** Reference map (current implementation)
- **Date:** 2026-08-12
- **Audience:** Engineers tracing how the web frontend moves between URLs, or
  changing routing/navigation
- **App:** `apps/web` (Next.js 16 App Router)
- **Related:** [Graph browser organization](graph-browser-organization.md)

This document is a *navigation graph*: the set of URL routes the frontend can
reach, and the edges between them. It is written so a reader can trace "what
happens when I click / open X" without reading every component.

## Route inventory

The App Router derives routes from `src/app`. Each route renders a feature
component. Dynamic segments are shown as `[segment]`; the workbench graph
route accepts a real graph UUID **or** the reserved literal `new`.

| URL | Component | Purpose |
|---|---|---|
| `/` | `GraphBrowser` (`graphs/GraphBrowser`) | Graph discovery ("My graphs") |
| `/graphs` | `GraphBrowser` | Same browser, "Your work" entry |
| `/workspaces` | `WorkspacesPage` | Teams & access directory |
| `/workspaces/[workspaceSlug]` | `WorkspaceOverview` | Team / personal settings |
| `/workspaces/[workspaceSlug]/graphs/[graphId]` | `Workbench` | The canvas; `graphId` is a UUID or `new` |
| `(login)` | `AuthSessionBoundary` | SSO threshold rendered over any route |

> The `/templates` and `/templates/new` routes are gone: the Template aggregate
> was withdrawn in favour of duplicating a graph
> ([ADR 0016](../adr/0016-graph-reuse-is-copies-and-modules.md)).

### `/` vs `/graphs`

These are **aliases of one logical route**. `app/page.tsx` and `app/graphs/page.tsx`
both re-export the same `GraphBrowser` component (`page.test.tsx` asserts this),
and `WorkspaceLayout.tsx` treats both as the active "graph browser"
(`pathname === "/" || pathname === "/graphs"`). `/` is the post-login root;
`/graphs` is the explicit "All graphs" destination the rail pushes to. They are
interchangeable — the graph below draws an alias edge `ROOT --> GRAPHS` rather
than treating them as distinct screens.

## Query strings

Only the graph browser puts state in the address, and only three parameters are
its own. `apps/web/src/features/graphs/browser-filters.ts` owns reading and
writing them, so no route parses `q` by hand.

| Parameter | Values | Omitted when |
|---|---|---|
| `q` | Free-form search text, bounded to 200 characters | Empty |
| `view` | `recent` or `all` | `recent` (the default) |
| `location` | A Workspace **slug** — never an id | Absent, blank, or read by a non-entry route |

Rules that hold across the family:

- **Defaults leave the address.** A browsed list is as short as a shared one, so
  `?view=recent` is never written.
- **Unrecognised values read as the default.** `?view=archive` is Recent; the
  bad value is cleaned out of the next address the browser writes.
- **Any other parameter belongs to another writer** (an analytics tag, a return
  path) and travels through untouched.
- **`location` is entry-only.** `/` and `/graphs` read it, then drop it when they
  hand off to `/workspaces/[slug]/graphs`; on the browser it is someone else's
  parameter.
- **A slug in the address is a request, not a fact.** The entry route matches it
  against the locations the person can actually reach and falls back to their
  usual location otherwise, so a stale bookmark never opens a Workspace they
  cannot read. The filters are still carried.
- **Commits use `router.replace`.** Typing does not leave one history entry per
  keystroke, so Back leaves the page instead of unwinding a word letter by
  letter.

The search field is deliberately uncontrolled: a field whose value comes back
from the address can be written back to a value the person already typed past,
which is how keystrokes get lost. `use-graph-browser-filters.ts` writes the
field only when the *address* moved (reload, Back, Forward, a control such as
Clear search), never while a keystroke of the person's own is still in flight.
Playwright covers this in `e2e/graph-browser-filters.spec.ts`, and it fails when
the field is made controlled again.

## Navigation mechanisms

The app uses four distinct navigation primitives. Knowing which one an edge
uses matters for back-button / history semantics.

| Mechanism | Where | History semantics |
|---|---|---|
| `<Link>` (`next/link`) | GraphBrowser rows, WorkspaceOverview | Normal push; browser back returns |
| `router.push(...)` | Programmatic flows (create workspace, open graph, new graph, switch workspace) | Normal push |
| `router.replace(...)` | Post-save / post-delete / room-terminal redirects | **Replaces** current history entry (back skips it) |
| `window.open(...)` | Workbench "open module source graph" | New tab |
| `window.location.assign(...)` | SSO login | Full navigation |

## Graph

```mermaid
flowchart TD
    subgraph Auth["Auth threshold (any route)"]
        A[Signed out / expired] --> LOGIN[OIDC login] --> RET[Return to original URL]
    end

    ROOT["/ — GraphBrowser"]
    GRAPHS["/graphs — GraphBrowser"]
    WS["/workspaces — Teams & access"]
    WSS["/workspaces/[workspaceSlug] — WorkspaceOverview"]
    WB_NEW["/workspaces/[slug]/graphs/new — blank canvas"]
    WB_G["/workspaces/[slug]/graphs/[graphId] — canvas"]

    %% Graph discovery → everywhere
    ROOT --> GRAPHS
    ROOT --> WS
    ROOT --> WSS
    GRAPHS --> ROOT
    GRAPHS --> WS
    GRAPHS --> WSS

    %% Teams & access → workspace settings
    WS --> WSS

    %% Workspace settings → out
    WSS --> ROOT

    %% Open / create graph from discovery & settings
    ROOT --> WB_NEW
    GRAPHS --> WB_NEW
    ROOT --> WB_G
    GRAPHS --> WB_G
    WSS --> WB_G
    WSS --> WB_NEW

    %% Rail: switch workspace / brand / settings (router.push)
    ROOT --> WSS
    GRAPHS --> WSS
    WB_NEW --> WSS
    WB_G --> WSS
    WSS --> WS

    %% In-canvas graph switching (router.push)
    WB_G --> WB_NEW
    WB_G --> WB_G
    WB_NEW --> WB_G

    %% Post-save / post-delete (router.replace)
    WB_NEW -. replace .-> WB_G
    WB_G -. replace .-> WB_NEW

    %% Room terminal close (access revoked / graph deleted) — router.replace
    WB_G -. replace .-> WSS

    %% Open module source graph — window.open (new tab)
    WB_G -. new tab .-> WB_G
```

*Dashed edges are `router.replace` (history-replacing) and `window.open` (new
tab). Solid edges are normal `<Link>` / `router.push`.*

## Edge detail

Each edge below names the file that owns it, the trigger, and the mechanism.
Dotted edges replace history; plain edges push.

### From graph discovery (`/`, `/graphs`)

| Trigger | Destination | Mechanism | Owner |
|---|---|---|---|
| Click a graph row | `/workspaces/[slug]/graphs/[id]` | `<Link>` | `graphs/GraphBrowser.tsx` (`GraphRow`) |
| "New graph" (one location) | `/workspaces/[slug]/graphs/new` | `router.push` | `graphs/GraphBrowser.tsx` (`startGraph`) |
| "New graph" (choose location dialog) | `/workspaces/[slug]/graphs/new` | `router.push` | `graphs/GraphBrowser.tsx` (dialog) |
| Rail brand / "All graphs" | `/graphs` | `router.push` | `workspaces/WorkspaceLayout.tsx` (`goGraphs`) |
| Rail "Teams & access" | `/workspaces` | `router.push` | `workspaces/WorkspaceLayout.tsx` |
| Rail workspace switcher | `/workspaces/[slug]` | `router.push` | `workspaces/WorkspaceLayout.tsx` |
| Header "My graphs" | `/` | `<Link>` | `WorkspaceOverview.tsx` |

### From `/workspaces` (Teams & access)

| Trigger | Destination | Mechanism | Owner |
|---|---|---|---|
| Click a location row | `/workspaces/[slug]` | `<Link>` | `app/workspaces/page.tsx` (`LocationRow`) |
| Create team (submit) | `/workspaces/[slug]` | `router.push` | `app/workspaces/page.tsx` |

### From `/workspaces/[workspaceSlug]` (overview)

| Trigger | Destination | Mechanism | Owner |
|---|---|---|---|
| "Browse graphs" button | `/graphs` | `<Link>` | `workspaces/WorkspaceOverview.tsx` |
| Rail brand | `/graphs` | `router.push` | `workspaces/WorkspaceLayout.tsx` |

### In the workbench canvas

The workbench keeps one route family; graph switching happens *within* the same
route segment so the canvas can confirm unsaved changes before swapping.

| Trigger | Destination | Mechanism | Owner |
|---|---|---|---|
| Rail "New graph" | `/workspaces/[slug]/graphs/new` | `router.push` | `workspaces/WorkspaceLayout.tsx` |
| Rail recent graph row | `/workspaces/[slug]/graphs/[id]` | `router.push` | `workspaces/WorkspaceLayout.tsx` |
| Quick-switch panel row | `/workspaces/[slug]/graphs/[id]` | `router.push` | `workspaces/WorkspaceGraphPanel.tsx` |
| Save a **new** graph (first save) | `/workspaces/[slug]/graphs/[id]` | `router.replace` | `workbench/ui/useSavedGraphLifecycle.ts` |
| Delete the **active** graph | `/workspaces/[slug]/graphs/new` | `router.replace` | `workbench/ui/useSavedGraphLifecycle.ts` |
| "New graph" already on `new` route | *(no nav)* blank canvas | — | `useSavedGraphLifecycle.ts` (`requestNewGraph`) |
| Browser history nav / back | current vs route graph id, confirm then push/replace | `router.push` | `useSavedGraphLifecycle.ts` (effect) |
| Module source graph (node / library) | `/workspaces/[slug]/graphs/[id]` | `window.open` (new tab) | `workbench/ui/Workbench.tsx` (`openGraphInNewTab`) |
| Room terminal close: access revoked / graph deleted | `/workspaces/[slug]` | `router.replace` | `workbench/ui/Workbench.tsx` |
| Rail "Save" (existing graph) | *(no nav)* | — | `workbench/ui/Workbench.tsx` |
| Rail "Runs" / duplicate / delete | *(no nav)* in-canvas panels | — | `workbench/ui/Workbench.tsx` |

> **Important:** the workbench is keyed/kept alive across graph-id changes within
> `/workspaces/[slug]/graphs/…` (`graphs/layout.tsx` renders `<Workbench>` for
> any supported route id). Route changes are the *boundary* that replaces the
> canvas draft, so unsaved-change confirmation is enforced before a `push`.

### Module library flows (`WorkspaceLibraryDialog`)

| Trigger | Destination | Mechanism | Owner |
|---|---|---|---|
| "Open source graph" (module row) | `/workspaces/[slug]/graphs/[id]` | `router.push` | `workspaces/WorkspaceLibraryDialog.tsx` |

## Auth / SSO

`AuthSessionBoundary` wraps every route. On `signed-out` or `expired` it
renders a login threshold; "Continue with SSO" does
`window.location.assign(oidcLoginUrl(safeReturnPath(currentUrl)))`, so after a
successful login the browser returns to the *original* URL that triggered the
login. Logout stays in-place (`signed-out` threshold), it does not navigate
away.

## Reasoning guide

- **"Where do I go to open a graph?"** → `GraphBrowser` rows `<Link>` into
  `/workspaces/[slug]/graphs/[id]`; the rail and quick-switch use `router.push`
  to the same family.
- **"How does the canvas URL change when I save a new graph?"** → first save
  calls `router.replace` from `…/graphs/new` to `…/graphs/[id]` so the back
  button does not land on a blank-draft URL.
- **"Why is graph switching done in-canvas instead of full page?"** →
  `graphs/layout.tsx` keeps `<Workbench>` alive across supported route ids, and
  `useSavedGraphLifecycle` confirms unsaved changes before a `push`.

# ADR 0001: Organize the Workbench as a feature-first vertical slice

- **Status:** Accepted
- **Date:** 2026-07-17
- **Scope:** `apps/web`

## Context

The Workbench is one highly interactive editor. Canvas state, node and edge
authoring, selection, graph persistence, execution, notifications, and dialogs
coordinate within the same client lifecycle.

An islands architecture is designed for independently interactive regions within
otherwise static content. Treating Workbench regions as islands would not remove
their shared graph and execution policies. It would move that coordination into
a shared store or event bus and make cross-region invariants harder to follow.
Server components may still validate routes or preload data around the editor,
but islands are not the organizing pattern for the interactive Workbench itself.

The current frontend also spreads Workbench ownership across route files,
Workbench components, canvas components, hooks, and API modules. The refactor
needs a structure that can be adopted incrementally without introducing a full
Clean Architecture or Feature-Sliced Design taxonomy.

## Decision

Organize Workbench code as one feature-first vertical slice under
`src/features/workbench`, split inside into vertical slices that each own one
capability end to end.

```text
src/
  app/                         # Next.js routes and application composition
  features/
    workbench/
      index.ts                 # Public client feature API
      routes.ts                # Public server-safe route API
      shell/                   # Workbench composition, chrome, and menus
      cell-canvas/             # Canvas engine, cards, and pointer gestures
      artifacts/               # Artifact cards, viewers, renderers, and the library panel
      authoring/               # Graph document, authoring commands, and layout contracts
      config-ui/               # Node configuration surfaces: selector, schema, handles
      execution/               # Run planning, execution, and history
      collaboration/           # Rooms, presence, autosave, and saved-graph lifecycle
      agents/                  # Agent links, tool events, and agent chat
      test/                    # Feature-local test support (no product code)
  components/                  # Reusable, feature-agnostic UI and providers
  lib/
    api/                       # Generated contracts and concrete HTTP adapter
```

The Workbench remains one client feature. Its UI may be split into components,
and its policies may be split into model modules, without introducing independent
hydration boundaries.

### Dependency direction

```mermaid
flowchart LR
    App["app routes"] --> Public["features/workbench public entry points"]
    Public --> Shell["shell"]
    Shell --> Slices["cell-canvas, execution, collaboration, agents"]
    Shell --> Artifacts["artifacts"]
    Slices --> Artifacts
    Slices --> Authoring["authoring"]
    Artifacts --> Authoring
    Artifacts --> Config["config-ui"]
    Authoring --> Config
    Config --> Artifacts
    Slices --> Shared["shared components"]
    Slices --> API["lib/api"]
```

Imports follow these rules:

1. `app` owns route parameters, route validation, layouts, and application-level
   providers. It imports the client Workbench through `@/features/workbench` and
   server-safe route helpers through `@/features/workbench/routes`.
2. `features/workbench/index.ts` is the public client entry point and exports
   only `Workbench`. `routes.ts` is a second, deliberately named public entry
   point so server-only route code does not evaluate the client bundle. Neither
   entry point wildcard-exports feature internals.
3. `shell` is the composition slice and the only one that may reach every other
   slice, including `cell-canvas`. No other slice imports `shell`, so wiring the
   editor together stays a single place and a card change cannot pull in the chrome.
4. The domain slices import downward: `cell-canvas` over `artifacts`, `authoring`,
   and `config-ui`; `artifacts` over `authoring`, `config-ui`, and `agents`;
   `authoring` and `config-ui` over each other's published modules and `artifacts`;
   `execution` over `authoring`, `collaboration`, and `config-ui`; `collaboration`
   over `agents`, `artifacts`, `authoring`, and `execution`; `agents` over
   `artifacts` and `authoring`. `routes.ts` is a leaf the slices that build links
   may read. The architecture test enforces this matrix, acyclic imports, and a
   fixed set of slice directories, and keeps route and sandbox code out of features.
5. A slice owns its own rendering and its own policy. Deterministic policy that no
   component renders stays in a plain module the slice can test without jsdom, and
   imports no React hook, Next.js, StyleX, or the concrete HTTP client. Type-only
   imports from stable API contract aliases are allowed when duplicating the
   contract would be worse. Move the canonical graph contract inward only when that
   work can migrate the existing callers together.
6. Shared components and `lib/api` never import from `features/workbench`.
   Code becomes shared only after an independent consumer needs the same
   responsibility.
7. Feature-internal code imports sibling modules directly rather than importing
   its own public index, which avoids circular dependencies.

### Async lifecycle ownership

Long-running Workbench actions must distinguish draft changes from document
identity changes. A graph fingerprint detects edits within the same document;
it is not sufficient to decide whether a late save, open, or delete response
still owns the active document.

The saved-graph lifecycle therefore owns a monotonic document generation, while
individual open requests also own an `AbortController`. Code that resumes after
an asynchronous boundary rechecks the relevant generation or request identity
before mutating document state, navigation, errors, or UI. Server-backed lists
and registries may still refresh after a successful stale response because the
remote mutation happened even when the current document no longer accepts it.

### HTTP boundary

`lib/api` remains the concrete, typed HTTP adapter. There is one production
implementation, so the feature will not add repository, gateway, port, factory,
or use-case interfaces merely to wrap those functions. Introduce an interface
only when a real caller needs multiple implementations or a stable boundary that
cannot be expressed by the existing module API.

Tests should exercise pure model behavior directly and mock at the existing
module or network boundary when an API dependency is involved. Test convenience
alone does not justify another production abstraction.

Hook lifecycle tests opt into jsdom per test file and use the feature-local,
test-only renderer under `test/`. They control promises and timers explicitly,
mock the concrete API and router module boundaries, and exercise the hook's
public callbacks and observable state. Production hooks do not gain injection
parameters or interfaces solely for tests.

### Naming and ownership

- Name files after the capability or policy they own, such as
  `execution-plan.ts`, `connection-policy.ts`, or `LibraryPanel.tsx`.
- Avoid generic ownership names such as `utils`, `helpers`, `manager`, or
  `services` inside the feature.
- Use PascalCase for component files and `use` prefixes for genuine React hooks.
- Keep one-call constructor and method wrappers inline with their owner.
- Keep feature-local types private unless another module consumes the contract;
  export public types deliberately from the module that owns them.
- Colocate behavioral tests with the model or component they protect.
- Keep styles with the component that renders them.
- Move code into shared folders only when its responsibility is feature-agnostic,
  not merely because more than one Workbench file imports it.

## Consequences

- Route code sees a small, stable feature API.
- Graph and execution policies can be tested without rendering the full editor.
- Canvas view contracts live in `authoring`, alongside the authored graph document.
  The architecture test checks imports across the slices for cycles and for a
  violation of the one-way slice matrix.
- The refactor can move one responsibility at a time while preserving behavior.
- The Workbench remains one client bundle and one coordinated interaction
  boundary; this decision does not promise independent hydration.
- The previous `components/workbench` and `components/canvas` locations are no
  longer valid feature dependencies; new imports must follow the direction
  above.

## Alternatives considered

### Independent islands

Rejected as the organizing pattern because Workbench regions are not independent.
They share live graph state, execution lifecycle, persistence decisions, and
interaction invariants.

### Full Clean or hexagonal architecture

Rejected for the frontend feature. Its inward dependency principle is useful,
but ports and adapters for a single concrete HTTP client would add indirection
without an actual substitution requirement.

### Full Feature-Sliced Design taxonomy

Rejected for now. The repository has one active frontend product slice, so global
`widgets`, `entities`, `features`, and `shared` layers would cause broad movement
without clarifying Workbench ownership. This decision borrows the useful
feature-first boundary and vertical slices inside the feature instead.

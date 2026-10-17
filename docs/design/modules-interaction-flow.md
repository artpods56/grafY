# Modules interaction structure

- **Status:** Draft; breadboards on the conceptual-model hypothesis
- **Date:** 2026-08-08
- **Audience:** Designers and engineers shaping Workbench add/insert, module
  publish, and workspace library management
- **Document type:** Explanation — Layers of Product Design interaction layer
- **Related:** [modules conceptual model](modules-conceptual-model.md),
  [modules surface](modules-surface.md),
  [modules domain map](modules-domain.md),
  [product vocabulary](../../CONTEXT.md)

## Summary

Breadboards for how people **publish**, **browse/insert**, **upgrade**, and
**import** modules. Interaction logic only — not visual design.

**Foundation:** [modules-conceptual-model.md](modules-conceptual-model.md).
Flows use that ubiquitous language. If the model changes, revisit these
breadboards.

**Redesign of:** today’s single Node catalog dialog where any tip with valid
boundaries appears under a Modules plugin origin.

## Job stories

Three journeys share places; each is a complete job.

1. **Compose — insert a module call**  
   When I am editing a graph and need a reusable building block, I want to find
   a published Module in this workspace library and insert a call pinned to its
   current library release, so I can wire its contract without rebuilding it.

2. **Author — publish a release**  
   When my source graph’s contract is valid, I want to publish a Module release
   into this workspace library, so teammates (or my future self) can insert it.

Success criteria:

1. Containing graph has a Module call pinned to a release; canvas focus returns.
2. Workspace library lists the Module (published); Insert offers that release.
3. Destination workspace has a new source graph + Module, or home library no
   longer offers the Module for insert while pins still resolve.

---

## Places (shared map)

| Place | Role |
| --- | --- |
| Workbench canvas | Editing one Saved graph in one Workspace |
| Add node | Fast search/insert for operators **and** published Modules |
| Module contract | Inspect one Module release before insert or upgrade |
| Workspace library | Browse this Workspace’s published Modules and their releases |
| Publish release | Confirm publishing a validated revision from the source graph |
| Source graph workbench | Same Workbench canvas on the Module’s source graph |
| Module call on canvas | Selected Module call node (inline affordances) |

**Collapsed deliberately:** no separate “module settings” place — stewardship
lives in Workspace library; authoring lives on the source graph; composition
uses Add node + Module contract.

---

## Journey A — Insert a module call

### Current flow (rough)

Workbench → Node catalog → filter Modules origin → pick tip revision → inspect
ports → Add. Self-graph hidden; invalid tips listed as “unavailable.”

### Breadboard

```
Workbench canvas
- open Add node → Add node
- open Workspace library → Workspace library
- select Module call → Module call on canvas
[ active graph; selection; whether library has published modules ]

Add node
- search / filter → stays Add node (filtered)
- choose built-in or external operator → insert on Workbench canvas
- choose published Module → Module contract (intent: insert)
- open Workspace library → Workspace library
- cancel / dismiss → Workbench canvas
[ search field; groups: Built-in, External, Workspace library modules;
  module rows show name and current release number;
  empty: "No published modules in this workspace" + affordance
  "Open workspace library"; loading; error retry ]

Module contract (insert)
- pick release (current library release default; older releases allowed)
- insert module call → Workbench canvas (new Module call selected)
- open source graph → Source graph workbench
- back → Add node
- cancel → Workbench canvas
[ module name, description; release picker across published releases;
  module ports in/out with types and requiredness;
  disabled Insert when module is source of active graph (self-call) ]

Module call on canvas
- upgrade module call → Module contract (intent: upgrade)
- open source graph → Source graph workbench
- remove → Workbench canvas
[ pinned release; whether a newer library release exists; port wiring ]

Workspace library (from compose)
- select Module → Module contract (intent: inspect / insert)
- publish guidance when empty → Source graph workbench or graphs list
  (see open decisions)
- back → Workbench canvas or Add node (return to opener)
[ see Journey C content ]
```

### Flow diagram (insert)

```mermaid
graph LR
  Canvas[Workbench_canvas] --> AddNode[Add_node]
  AddNode --> ContractInsert[Module_contract]
  ContractInsert --> Canvas
  AddNode --> Library[Workspace_library]
  Library --> ContractInsert
  Canvas --> CallNode[Module_call_on_canvas]
  CallNode --> ContractUpgrade[Module_contract_upgrade]
  ContractUpgrade --> Canvas
  CallNode --> Source[Source_graph_workbench]
  ContractInsert --> Source
```

### Edge cases — insert

| Case | Behaviour |
| --- | --- |
| Empty library | Add node Modules group empty; CTA to Workspace library explaining Publish release |
| Loading library | Inline loading in Add node module group; Insert disabled until loaded |
| Self-call | Module whose source is the active graph omitted or Insert disabled with reason |
| Retired Module (stored deprecated/withdrawn) | Not listed in Add node or library; existing calls remain on canvas and keep resolving |
| Insert failure | Stay on Module contract; error + retry; no partial node |
| Post-insert | Return to canvas with new Module call selected; pin = chosen Module release at confirm time (defaults to current library release) |
| Newer release exists | Module call shows upgrade affordance → Module contract (upgrade) |
| Upgrade cancel | Stay on Module call; pin unchanged |

**Optimistic vs pessimistic:** Pessimistic insert/upgrade — wait for server
accept before placing or repinning. Open engineering question if collaboration
command batching needs optimistic placeholder.

---

## Journey B — Publish a release

### Breadboard

```
Source graph workbench
- declare module boundaries → stays (nodes added)
- open Publish release → Publish release
  (only if chosen revision contract validates; else blocked with reason)
- open Workspace library → Workspace library
[ graph canvas; boundary nodes; readiness: no boundaries | broken | valid;
  if Module exists: current library release number ]

Publish release
- confirm publish → Source graph workbench (success) 
  and workspace library now lists Module / new release
- cancel → Source graph workbench
[ source graph name; revision to publish (tip by default);
  derived module contract preview; name/description fields for Module
  on first publish; note that callers pin this release and do not auto-track;
  validation errors if contract broken — Confirm disabled ]

Workspace library
- shows new/updated Module as published with that release as current
```

### Flow diagram (publish)

```mermaid
graph LR
  Source[Source_graph_workbench] --> Publish[Publish_release]
  Publish --> Source
  Publish --> Library[Workspace_library]
  Source --> Library
```

### Edge cases — publish

| Case | Behaviour |
| --- | --- |
| No boundaries | Publish affordance absent or explains Declare module boundaries |
| Contract broken | Publish opens in blocked state or stays on canvas with diagnostics; Confirm disabled |
| First publish | Creates Module; requires name (default from graph name); enters Published |
| Later publish | New Module release; becomes current library release; old releases remain for pins |
| Concurrent edit / revision mismatch | Failure on Publish release; stay with refresh tip + retry |
| Permission denied | Affordance hidden or error on confirm; Publish requires Editor/Owner |
| Post-publish | Toast/inline success on source graph; library and Add node reflect new release before next insert (freshness requirement from conceptual model) |

---

## Journey C — Steward: library browse

### Breadboard

```
Workspace library
- filter / search → stays
- select Module → Module contract (intent: manage)
- open source graph → Source graph workbench
- back → Workbench canvas (or workspace graphs entry — see open decisions)
[ modules: name, current release, release count;
  empty state: how to Declare boundaries + Publish release;
  loading; error ]

Module contract (manage)
- insert module call → Workbench canvas
  (only if a graph is active in this workspace; else disabled)
- publish release → Publish release
  (if user can open source and contract valid — or deep-link source)
- open source graph → Source graph workbench
- back → Workspace library
[ full contract; release history list for inspect ]
```

Publishing is the only transition a steward can take. There is no place in this
journey to retire a Module: a release is a freeze, and stopping its use means
publishing a better one and letting each owner repoint their pin
([ADR 0016](../adr/0016-graph-reuse-is-copies-and-modules.md)).

### Flow diagram (steward)

```mermaid
graph LR
  Library[Workspace_library] --> Contract[Module_contract]
  Contract --> Library
  Contract --> Source[Source_graph_workbench]
  Library --> Source
  Contract --> Publish[Publish_release]
```

### Edge cases — steward

| Case | Behaviour |
| --- | --- |
| Module with active pins | Nothing to warn about; no release is removed |
| Retired Module in storage | Hidden from the list; its pins still resolve |

---

## Challenge notes

- **Add node vs Workspace library:** Add node is for composition speed; library
  is for stewardship and empty-state education. Both list the same published
  Modules — not two divergent catalogs.
- **Vocabulary check:** Uses Publish release, Insert module call, Upgrade
  module call, and Open source graph. Avoids Share/Public/Private for these
  actions.
- **Broken objects:** Module attributes (current release, contract) and actions
  (publish, open source) meet on Module contract and Workspace library with
  cross-links.
- **Isolated relationships:** Module → source graph and Module call → release
  are navigable via Open source graph and Upgrade.
- **Simpler alternative rejected:** Publishing automatically on every valid tip
  checkpoint — rejected by conceptual model (silent library pollution).

## Resolved decisions (binding)

1. **Workspace library entry points** — both Workbench and workspace graphs
   overview.
2. **Release picker on insert** — allow picking an older Module release at
   insert time (not only the current library release).
3. **Capabilities:** Publish release = Editor + Owner. Nothing else to gate.
4. **No delete and no retirement:** pins keep resolving and stay that way.
5. **v1 scope:** Publish, Add node library listing, Workspace library browse.

## Remaining open decisions

1. **Upgrade UX** — one-click to current library release vs always through
   Module contract?
3. **Empty library education** — link to a specific graph, graphs list, or
   short inline steps only?
4. **Viewer role** — can Viewers open Module contract read-only from Add node
   without Insert?
5. Rename propagation remains open in the conceptual model.

## Risks

- Conceptual model is a **hypothesis** without research; browse places may be
  wrong if “library” is not how users think.
- Collaboration freshness after Publish (multiplayer Add node open during
  publish) needs an engineering rule so Insert does not offer a stale release.
- Surface work must not collapse Module back into “another plugin row” without
  release number and Open source graph.

## Next step

Surface audit and decision inventory:
[modules-surface.md](modules-surface.md). Keep the conceptual model stable
before large UI rewrites.

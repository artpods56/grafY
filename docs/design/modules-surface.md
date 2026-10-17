# Modules surface

- **Status:** Draft; audit of current Workbench UI + decision inventory for the
  redesigned places
- **Date:** 2026-08-08
- **Audience:** Designers and engineers implementing Add node, Workspace
  library, Publish release, and Module call surfaces
- **Document type:** Explanation — Layers of Product Design surface layer
- **Related:** [modules conceptual model](modules-conceptual-model.md),
  [modules interaction structure](modules-interaction-flow.md),
  [modules domain map](modules-domain.md)
- **Medium:** Screen UI (Workbench web app)
- **Existing surface audited:** `NodeSelector` (“Node catalog”) and module
  badges on catalog rows / inspector (`Open source graph`)

## Summary

Part 1 audits today’s Node catalog against the conceptual model and
breadboards. Part 2 inventories surface decisions for the redesigned places.
Lower-layer gaps that block a correct surface are listed separately.

**Emotional / social jobs (assumed):** composers want confidence the contract
won’t surprise them; authors want control over what teammates depend on;
stewards want to retire a Module without looking reckless about breaking pins.

---

## Part 1 — Audit (current surface)

### Frame

Existing surface is a single dialog: **Node catalog** — search, plugin groups
(Built-in / Modules / External), node list, inspector with ports and
compatibility, Add. Modules appear as plugin origin `module` with badges like
`Module · r{n}`. Invalid tips show under **Unavailable as modules**. Self-graph
is hidden with an explanatory note. Inspector offers **Open source graph**.

No Publish release, Workspace library, or Upgrade module call surfaces exist
yet.

### Vocabulary and language

| Surface copy | Model term | Finding |
| --- | --- | --- |
| Node catalog | Add node (compose place) | **Unlisted / outdated** — breadboard renames the compose place; “catalog” is rejected as an object |
| saved graph modules | Module | Close; prefer **Module** / **Workspace library** |
| Module · r{n} | Module release | **Partial** — shows revision, not “release” or publication state |
| Open source graph | Open source graph | **Honours model** — keep |
| Unavailable as modules | Contract broken (authoring) | **Deeper** — mixes stewardship diagnostics into compose; broken tips should not be a library browse concept |
| catalog-visible modules | published Modules | **Direct violation** — implementation jargon on empty state |
| Add (implied “add node”) | Insert module call vs insert operator | **Flattening** — one verb for operators and Modules; model wants **Insert module call** when the selection is a Module |
| Works with / ports | Module contract | Partial — contract inspect exists; not named as such for Modules |

**Tone:** Diagnostic and engineer-facing (“catalog-visible”, “unavailable as
modules”). For publish, tone should stay precise but less like a compiler log.

### Object consistency

| Object | Current representation | Issue |
| --- | --- | --- |
| Module | Row in Modules plugin list, same chrome as operators | **Masked** — reads as another node type/plugin, not a library building block with publication state |
| Module release | `r{n}` badge only | Thin; no current-vs-pinned distinction on canvas |
| Module contract | Inspector ports section | Present for insert; not reused for publish preview / upgrade |
| Module call | Ordinary workflow node once placed | OK if upgrade/open-source affordances appear when selected |
| Workspace library | Absent | Missing place |
| Publication state | Absent (auto tip visibility) | Missing |

Shapeshifter risk if Workspace library cards look unrelated to Add node module
rows — establish one **Module row/card treatment** (name, state, release,
contract summary) reused in both places.

### Completeness vs breadboard

| Breadboard affordance | Current surface |
| --- | --- |
| open Add node | Present (as Node catalog) |
| choose published Module → Module contract | Partial (inspector, no publish state) |
| insert module call | Present as add node |
| open Workspace library | **Missing** |
| Publish release | **Missing** |
| Upgrade module call | **Missing** |
| Open source graph | Present in inspector |
| Empty library education | **Missing** (only search-empty / unavailable diagnostics) |

**Surface without model:** “Unavailable as modules” list inside compose — after
redesign, move contract-broken diagnostics to **source graph** / publish
readiness, not the insert surface.

### Emotional register

| Job | Current misalignment |
| --- | --- |
| Confidence in contract | Inspector helps; silent tip publish undermines trust (“why is my WIP here?”) |
| Control over what others depend on | No publish gate — social risk |

---

## Part 2 — Decision inventory

### Feedback and errors (decide with implementation)

| Action / state | Success | In progress | Failure (diagnose · explain · recover) |
| --- | --- | --- | --- |
| Insert module call | Return to canvas; new Module call selected; optional brief confirmation | Disable Insert; spinner on button | “Couldn’t insert {name}.” · server/network reason · Retry / Back to Add node |
| Upgrade module call | Pin updates on selected node; release number refreshes | Disable Upgrade | “Couldn’t upgrade pin.” · conflict · Retry or stay on current release |
| Publish release | Success on source graph (“Published release {n} to workspace library”); library/Add reflect it | Confirm disabled + progress | Validation: list contract errors + fix on canvas; revision conflict: refresh tip and retry; permission: who can publish |
| Empty library | — | — | Educational empty, not an error |
| Self-call blocked | — | — | “Can’t insert a Module into its own source graph.” · Open library / pick another |

Every user-visible error must include all three parts. Ban “Something went
wrong” alone.

### Hierarchy and emphasis (per place)

| Place | Primary | Must not dominate |
| --- | --- | --- |
| Add node | Search + choosing what to insert | Stewardship diagnostics, unavailable tips |
| Module contract (insert) | Port contract + Insert | Long operator ids; plugin chrome |
| Module contract (manage) | Release list + Open source graph | Accidental Insert when no graph active |
| Workspace library | Module list with releases | Looking like a second full node catalog |
| Publish release | Contract preview + Confirm publish | Scary internals; unrelated graph settings |
| Module call on canvas | Pinned release + Upgrade when newer exists | Crowding ordinary node config |

### Accessibility decisions (screen UI)

1. Add node, Workspace library, Publish release: focus trap and restore
   focus to the opener (canvas or module call) on dismiss.
2. Module rows and release badges: text, not colour-only; `aria-pressed` /
   selected state on lists.
3. Insert / Publish: announce success and errors via assertive live
   region or focus move to the message.
4. Keyboard: full list navigation + Enter to open Module contract; primary
   action reachable without pointer.
5. Touch targets ≥ existing Workbench control sizes; don’t rely on tiny `r{n}`
   badges alone for release identity — include visible “Release {n}” text in
   contract header.
6. Self-call and permission-disabled actions: exposed as disabled with
   accessible name that includes the reason, not silent omission only (omission
   in lists is OK if explained in empty/filter copy).

### Consistency

- **Same:** Module row treatment in Add node and Workspace library; Module
  contract layout for insert, upgrade, and manage (action set changes by
  intent).
- **Different:** Insert (primary, constructive) vs Publish (destructive-adjacent
  confirm: it freezes a revision).
- **Platform:** Keep dialog/sheet patterns already used by Workbench
  (`Dialog`); don’t invent a second modal system for Publish.
- **Internal fix:** Stop presenting Modules as a `Package` plugin twin to
  External without state — Modules section label should read as **Workspace
  library** (or under that heading), not only “Modules” plugin slug chrome.

### Copy-first strings (committed direction)

Use these unless lower layers change:

- Place title (compose): **Add node**
- Modules group: **Workspace library**
- Primary insert CTA: **Insert module call**
- Inspect eyebrow when Module selected: **Module · release {n}** + state chip
- Author CTA: **Publish release**
- Canvas: **Upgrade to release {n}**, **Open source graph**

---

## Cross-layer issues (resolved for v1)

1. **Capabilities:** Publish release = Editor + Owner. Surface hides/disables
   accordingly. There is no library-management capability to gate.
2. **No delete:** the surface offers no way to remove a Module or a release, and
   no retirement affordance to explain.
3. **Library entry points:** Workbench and workspace graphs overview.
4. **Older-release insert:** Module contract includes a release picker.
5. Auto-catalog of valid tips must be removed — surface copy alone cannot fix
   silent publish.

## Remaining cross-layer / polish

- Upgrade one-click vs always through Module contract
- Import landing place
- Viewer read-only Module contract from Add node
- Rename propagation

---

## Surface decisions for implementation

1. **Add node naming** — rename dialog from “Node catalog” to **Add node**.
2. **Module visual token** — distinct from External badge; release number in one
   consistent cluster.
3. **Unavailable tips** — remove from Add node; show as publish readiness on
   source graph only.
4. **Success feedback** — toast/inline success for Publish (align with
   Workbench global issue/toast patterns).

### Deferred

- Motion/transition details between Add node and Module contract
- Marketing-level empty-state illustration
- CONTEXT.md / OpenAPI field rename of `public_name` → port name (engineering
  follow-through; surface already says “port name”)

---

## What’s working (keep)

- Three-pane browse → inspect → act pattern fits Module contract
- **Open source graph** already matches ubiquitous language
- Self-call exclusion with explanation is the right kind of recovery copy
- Port/compatibility inspector is the right emphasis for insert confidence
- Search across titles/ports/types is the right primary affordance in Add node

### Amended conclusion (2026-08-12)

Full contract inspection remains appropriate for **Modules**. It is not the
default depth for every operation in Add node. Ordinary operators use a concise
purpose summary (required inputs, produced outputs, configuration) with
artifact IDs, schema versions, operator identity, cardinality, conversions, and
complete schemas behind **Technical details**. See
[node discovery interaction](node-discovery-interaction.md).

---

## Next step

Implement in the real medium against
[modules-interaction-flow.md](modules-interaction-flow.md), or resolve
cross-layer open questions first where they block affordance visibility.

The surface is the layer users encounter. Everything decided below either gets
honoured here or undermined here. Revisit this skill after any significant
change to the conceptual model or interaction structure.

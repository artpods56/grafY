# Node contracts split by use case

Rating: **complex**. The module moves are mechanical; inlining annotation branches requires careful control flow translation. A weaker implementation model must follow the branch mapping below and stop on ambiguity.

## Base and hard rules

Base: `origin/main` at `a27c9d79946083d7abb66563b4ea39e9df350956`. Local `main` is stale at `4509c248`; do not use it as the baseline. Every source line below refers to the pinned origin/main commit, which matches the production source in the authoring checkout. The reference spec is `docs/design/artifacts-service-split.md` on origin/main.

Zero behavior change: identical OpenAPI, Python call signatures, return values, serialization, exception types, exact messages, validation order and mutation order. Move existing objects; do not replace them with subclasses, forwarding functions or duplicate definitions. No new abstraction layers, metaprogramming, registries, protocols or generic utilities. No nested defs or closures in touched production files. Do not replace removed helpers with differently named wrappers. No private imports between modules. A retained helper shared across modules must have the explicitly authorized public name.

Read CONTEXT.md and ADRs 0007, 0017 and 0020. No domain decision changes. If main advances, rebase and remeasure before implementation. If a mapping, caller or test disagrees with this spec, stop and record it under Blockers. Never widen the allowlist or improvise a redesign.

## Survey and selection

Surveyed Python source under apps/api, libs and plugins by physical line count and AST definition/call inspection; also reviewed the previous round's survey and file ownership. These are the best remaining bounded splits with local proof, rather than simply the largest files.

| Candidate | Lines on base | Decision |
|---|---:|---|
| Core node contracts, `libs/core/src/grafy_core/nodes.py` | 812 | Select: port declarations, annotation derivation, execution context and binding resolution can be separated without caller edits |
| Core spatial contracts, `libs/core/src/grafy_core/spatial_contracts.py` | 687 | Select: styles, feature validation, map composition and stored metadata are independent use cases with producer/reader tests |
| Agent turns, `apps/api/src/grafy_api/agents/turns.py` | 1584 | Defer: admission, cancellation and streaming share mutable lifecycle state |
| Identity application service | 1212 | Defer: authorization, owner invariants and revocation transactions |
| Collaboration application service / domain module | 1139 / 1417 | Defer: command order, checkpoint and idempotency semantics make the split less bounded |
| Core Plugin registration, `libs/core/src/grafy_core/plugins.py` | 1129 | Defer: nested decorators and dynamic adapter classes require a separate design to preserve registration semantics |
| Persistence project repository | 911 | Defer: relational proof requires a disposable PostgreSQL database |
| GIS GDAL adapter | 846 | Defer: native process and environment boundary needs broader integration proof |
| API run contract binder | 716 | Defer: helper inlining would enlarge the binding algorithm; separating core contracts first has broader payoff |
| API uploads / node secrets | 569 / 553 | Defer: completion races and cryptographic binding validation are less suitable for an unattended pass |
| Web Workbench | 5220 in previous survey | Defer: UI behavior and browser proof are a separate task; generated API types are not refactor candidates |

The two selected allowlists are disjoint. Shared tests are read-only. Read both night-two specs using `git show docs/night-refactor-2-specs:docs/design/night-refactor-2-in-memory.md` and `git show docs/night-refactor-2-specs:docs/design/night-refactor-2-agent-project-tools.md` before implementing.

## Do not touch

Everything outside the exact allowlist is read-only, including:

- `libs/core/src/grafy_core/runtime/in_memory.py` and every path under `libs/core/src/grafy_core/runtime/in_memory/`.
- `apps/api/src/grafy_api/agents/{project_tools,tool_ports,tool_arguments,tool_views,project_context}.py`.
- `tests/unit/architecture/test_in_memory_boundaries.py`, `tests/unit/architecture/test_project_tool_boundaries.py` and both night-two spec files.
- All API artifact modules and artifact routes, `apps/tiler/`, all other apps/api files, web, generated clients, Plugins, persistence, configuration and lockfiles.
- Existing tests, CONTEXT.md and ADRs. The sibling night-three area owns its own files.

These exclusions cover both the edited and newly created files owned by the unmerged night-two branches. Reading a test or running it does not authorize editing it.
## Allowed file set

Edit `libs/core/src/grafy_core/nodes.py`. Create exactly:

- `libs/core/src/grafy_core/node_ports.py`
- `libs/core/src/grafy_core/node_context.py`
- `libs/core/src/grafy_core/node_derivation.py`
- `tests/unit/architecture/test_node_contract_boundaries.py`

The only other editable file is `docs/design/night-refactor-3-node-contracts.md`, solely for Blockers. No deletions. No caller edits.

## Exact split

All source locations in this table are in `libs/core/src/grafy_core/nodes.py`. Move whole definitions with decorators and unchanged fields, defaults and validators. Keep all original public names importable from grafy_core.nodes using explicit same-name aliases, such as `InPort as InPort`. Do not add wrappers or dynamic exports. The consumer table below identifies existing imports; all remain unchanged.

| Source definition and line | Destination | Callers / use |
|---|---|---|
| `PortShape:38`, `NodeContractError:43`, `NodeContractResolutionError:47` | node_ports.py | Port validation, derivation and resolve_node_contracts; external consumers below |
| `ArtifactTypeVariable:73`, `ArtifactTypeContract:91`, `InPort:95`, `OutPort:129` | node_ports.py | Annotation metadata and binding resolution |
| `InputPortSpec:141`, `OutputPortSpec:190`, `InputContract:201`, `OutputContract:207`, `ConfigContract:213`, `ResolvedNodeContracts:218` | node_ports.py | derive_input_contract, derive_output_contract, Node.__init_subclass__, resolve_node_contracts |
| `MAX_NODE_PROGRESS_MESSAGE_LENGTH:33`, `MAX_NODE_PROGRESS_COUNTER:34`, `MAX_NODE_ERROR_MESSAGE_LENGTH:35`, `UserFacingNodeError:51` | node_context.py | NodeExecutionContext.progress, UserFacingNodeError.__init__; external consumers |
| `NodeProgressReporter:223`, `NodeExecutionContext:237` | node_context.py | Node.run and runtime consumers; progress callback contract stays unchanged |
| `derive_input_contract:338`, `derive_output_contract:390` and retained helpers below | node_derivation.py | Node.__init_subclass__:648 and external consumers |
| `Node:634`, `resolve_node_contracts:702` | Stay in nodes.py | External consumers; resolution calls node.validate_artifact_type_bindings:688 |

Import direction: nodes -> node_ports, node_context, node_derivation; node_derivation -> node_ports; node_ports and node_context never import each other, nodes or node_derivation. Existing grafy_core.artifacts imports remain allowed. No API, Plugin, HTTP or storage imports. Preserve Node's existing __init_subclass__ machinery verbatim; add no metaprogramming. Keep Node and resolve_node_contracts together to avoid circular imports.

## Exhaustive private helper inventory

All source paths are `libs/core/src/grafy_core/nodes.py`. Call sites are lexical calls on the base, not runtime frequency. Inline leaf helpers before their parents. A return in an inlined branch assigns the local result and ends only that branch, never the outer derive loop.

| Helper at file:line suffix | Exact callers at call lines | Decision |
|---|---|---|
| `_artifact_type_contract:319` | derive_input_contract:370; derive_output_contract:403 | Inline `value.key if isinstance(value, ArtifactTypeSpec) else value`, using port.accepts or port.produces |
| `_concrete_artifact_type_key:327` | derive_input_contract:372 | Inline into an ordered loop over port.also_accepts. Preserve Spec then Key checks and exact error. Build tuple before InputPortSpec construction, after primary accepts normalization |
| `_single_port_meta:413` | derive_input_contract:341; derive_output_contract:393 | Inline forbidden check then metadata filtering then duplicate check in each loop. Input expects InPort / forbids OutPort; output reverses them. Use a separate local metadata_ports list so the result ports dict is not overwritten. Missing metadata still continues the field loop |
| `_config_shaped_input_allows_none:436` | derive_input_contract:345 | Inline annotation unwrap and union-set check in shape_field branch. Assign allows_none on success, then the same shape, accepted_shapes, target_type and preserves_ref_container. Same failure message |
| `_input_annotation_contract:459` | derive_input_contract:361 | Inline in the non-shape_field branch using the mutually exclusive branch mapping below |
| `_output_annotation_shape:557` | derive_output_contract:396 | Inline optional unwrap; ArtifactRef -> ONE, ArtifactRefSequence -> MANY, sequence-origin -> validate item then MANY, otherwise ONE |
| `_unwrap_optional:579` | _input_annotation_contract:514,522,538; _output_annotation_shape:563; itself:582 | Keep recursive helper private in node_derivation.py; calls relocate with inlining |
| `_is_sequence_origin:593` | _input_annotation_contract:531; _output_annotation_shape:568; _sequence_item_type:605 | Keep private in node_derivation.py, three sites |
| `_sequence_item_type:597` | _input_annotation_contract:487,516,532; _output_annotation_shape:569 | Keep private in node_derivation.py, four sites |
| `_concrete_type:620` | _input_annotation_contract:509,539,551 | Keep private in node_derivation.py, three distinct validation sites |
| `_config_shape:794` | resolve_node_contracts:775,785 | Inline twice in nodes.py. If config is absent or field missing, use port.shape. Otherwise convert a string with PortShape; preserve caught ValueError followed by exact NodeContractResolutionError. Only replace port after successful validation |

For `_input_annotation_contract`, bind annotation to field.annotation and use model/name in messages. Translate the existing returns to assignments of `(shape, accepted_shapes, target_type, preserves_ref_container, allows_none)`:

1. `port.instance_plugs`: retain variadic and exact-list guards, then item-type validation. The exact ArtifactRef | ArtifactRefSequence union assigns `(ONE, (ONE, MANY), None, True, False)`. Otherwise assign `(ONE, (ONE,), _concrete_type(...), False, False)`.
2. Only in the `else` of instance_plugs, unwrap optional annotation, apply the variadic item unwrap if requested, and combine allows_none using the existing `or`.
3. Use one exclusive chain: ArtifactRef assigns ONE/ref preservation; ArtifactRefSequence assigns MANY/ref preservation; sequence origin validates item, unwraps it and calls _concrete_type then assigns MANY without ref preservation; final scalar branch calls _concrete_type and assigns ONE without ref preservation.
4. Construct InputPortSpec once after the branches. No added continue, return, loop reordering or validation. Keep every keyword and field.is_required() call.

## Constructor wrappers and nested functions

| Source | Inventory | Decision |
|---|---|---|
| nodes.py:338,390,702 | derive_input_contract, derive_output_contract, resolve_node_contracts end with construction but perform validation/derivation | Keep public functions; they are not mere constructor wrappers |
| Entire nodes.py | Zero mere constructor wrappers; zero nested defs | Introduce none. Class methods and the existing subclass hook are not nested function factories |

Preserve progress validation order and best-effort reporter exception handling. Preserve binding-name validation before unknown/missing checks, then key validation, then the node hook, then ordered input/output replacement. Never mutate the original port maps. Do not normalize additional values or tighten accepted annotation forms.

## Ordered commits

1. `refactor: inline node contract helper chains`. Apply all inline rows in nodes.py, keeping retained helpers there temporarily. Run `uv run pytest -q tests/unit/core/test_node_contracts.py tests/unit/core/test_invocation.py tests/unit/core/test_plugins.py`.
2. `refactor: separate node ports context and derivation`. Apply the exact split and explicit re-exports. Run `uv run pytest -q tests/unit/core/test_node_contracts.py tests/unit/core/test_invocation.py tests/unit/core/test_plugins.py tests/unit/runs/test_node_runner.py tests/unit/architecture/ tests/integration/ops/test_openapi.py`.
3. `test: enforce node contract module boundaries`. Add only the allowlisted architecture test. Enforce the import directions, no nested defs and no private cross-module imports with AST inspection; assert original imports identify the moved class/function objects. Do not assert exact source strings or line counts. Run all finish-line commands.

## Surface checklist

Contract: no routes or schemas change. Builtin families and all Plugin hosts continue importing the same Node and contract objects. Tenancy: NodeExecutionContext workspace/project/graph fields unchanged; no authorization decision moves. Reverse states: valid and invalid binding paths and reporter success/failure remain covered; no new lifecycle operation. Docs: no domain decision or vocabulary change. Web: no edits needed.

## Existing import consumers

All files below are read-only. Names in each row continue to resolve through grafy_core.nodes; internal call sites are enumerated above.

| Import site | Imported names |
|---|---|
| `apps/api/src/grafy_api/agents/project_tools.py:57` | `ArtifactTypeVariable`, `resolve_node_contracts` |
| `apps/api/src/grafy_api/runs/contract.py:50` | `ArtifactTypeVariable`, `InputPortSpec`, `Node`, `NodeContractResolutionError`, `PortShape`, `ResolvedNodeContracts`, `resolve_node_contracts` |
| `apps/api/src/grafy_api/runs/edge_values.py:22` | `NodeExecutionContext` |
| `apps/api/src/grafy_api/runs/node_execution.py:20` | `NodeExecutionContext`, `PortShape` |
| `apps/api/src/grafy_api/runs/node_runner.py:24` | `NodeExecutionContext` |
| `apps/api/src/grafy_api/v1/routes/catalog/models.py:11` | `ArtifactTypeVariable`, `InputPortSpec`, `OutputPortSpec`, `PortShape` |
| `libs/client/src/grafy_client/graph_builder.py:20` | `ArtifactTypeVariable`, `Node` |
| `libs/client/src/grafy_client/models.py:7` | `PortShape` |
| `libs/core/src/grafy_core/callable_nodes.py:34` | `ConfigContract`, `InPort`, `Node`, `NodeContractError`, `NodeExecutionContext`, `OutPort`, `derive_input_contract`, `derive_output_contract` |
| `libs/core/src/grafy_core/plugins.py:35` | `ArtifactTypeContract`, `ArtifactTypeVariable`, `ConfigContract`, `Node`, `NodeExecutionContext`, `derive_input_contract`, `derive_output_contract` |
| `libs/core/src/grafy_core/runtime/execution.py:16` | `InputContract`, `Node`, `NodeExecutionContext`, `UserFacingNodeError`, `resolve_node_contracts` |
| `libs/core/src/grafy_core/runtime/invocation.py:7` | `InputContract`, `OutputContract`, `PortShape`, `ResolvedNodeContracts` |
| `libs/core/src/grafy_core/runtime/materialization.py:13` | `InputContract`, `PortShape` |
| `libs/core/src/grafy_core/runtime/persistence.py:17` | `NodeExecutionContext`, `OutputContract`, `OutputPortSpec`, `PortShape` |
| `libs/workbench/src/grafy_workbench/file/nodes.py:28` | `ArtifactTypeVariable`, `InPort`, `Node`, `NodeContractResolutionError`, `NodeExecutionContext`, `OutPort`, `UserFacingNodeError` |
| `libs/workbench/src/grafy_workbench/schema/nodes.py:21` | `InPort`, `Node`, `NodeExecutionContext`, `OutPort` |
| `libs/workbench/src/grafy_workbench/sequence/nodes.py:18` | `ArtifactTypeVariable`, `InPort`, `OutPort`, `UserFacingNodeError` |
| `libs/workbench/src/grafy_workbench/text/nodes.py:20` | `OutPort` |
| `libs/workbench/src/grafy_workbench/value/nodes.py:12` | `OutPort` |
| `libs/workbench/tests/schema/test_schema.py:8` | `NodeExecutionContext`, `PortShape` |
| `libs/workbench/tests/sequence/test_sequence.py:12` | `ArtifactTypeVariable`, `NodeContractResolutionError`, `NodeExecutionContext`, `PortShape` |
| `libs/workbench/tests/table/test_tables.py:9` | `NodeExecutionContext` |
| `libs/workbench/tests/test_scalar_persistence.py:10` | `NodeExecutionContext` |
| `libs/workbench/tests/text/test_text.py:15` | `NodeExecutionContext` |
| `plugins/gis/src/grafy_plugin_gis/nodes.py:17` | `InPort`, `Node`, `NodeExecutionContext`, `OutPort` |
| `plugins/gis/src/grafy_plugin_gis/smoke.py:10` | `NodeExecutionContext` |
| `plugins/image/src/grafy_plugin_image/nodes.py:31` | `InPort`, `Node`, `NodeExecutionContext`, `OutPort`, `UserFacingNodeError` |
| `plugins/image/tests/test_draw_regions.py:16` | `NodeExecutionContext` |
| `plugins/image/tests/test_image_persistence.py:12` | `NodeExecutionContext` |
| `plugins/llm/src/grafy_plugin_llm/openai_compatible.py:18` | `InPort`, `Node`, `NodeExecutionContext`, `OutPort`, `UserFacingNodeError` |
| `plugins/llm/src/grafy_plugin_llm/prompt.py:13` | `InPort`, `OutPort` |
| `plugins/mistral/src/grafy_plugin_mistral/ocr.py:34` | `InPort`, `Node`, `NodeExecutionContext`, `OutPort`, `UserFacingNodeError` |
| `plugins/reducto/src/grafy_plugin_reducto/ocr.py:23` | `InPort`, `Node`, `NodeExecutionContext`, `OutPort`, `UserFacingNodeError` |
| `plugins/table/src/grafy_plugin_table/nodes.py:10` | `InPort`, `Node`, `NodeExecutionContext`, `OutPort` |
| `scripts/smoke_workbench.py:17` | `NodeExecutionContext` |
| `tests/integration/artifacts/test_file_interpret.py:29` | `ArtifactTypeVariable`, `NodeContractResolutionError`, `NodeExecutionContext`, `resolve_node_contracts` |
| `tests/integration/artifacts/test_image_pipeline.py:13` | `NodeExecutionContext` |
| `tests/integration/artifacts/test_replacement_file_nodes.py:33` | `NodeExecutionContext` |
| `tests/integration/node_secrets/test_node_secrets.py:25` | `Node`, `NodeExecutionContext` |
| `tests/support/scenarios/arithmetic.py:20` | `InPort`, `OutPort` |
| `tests/support/scenarios/sequences.py:15` | `ArtifactTypeVariable`, `InPort`, `OutPort`, `UserFacingNodeError` |
| `tests/unit/client/test_graph_builder.py:26` | `ArtifactTypeVariable`, `InPort`, `Node`, `NodeExecutionContext`, `OutPort`, `PortShape` |
| `tests/unit/core/test_invocation.py:17` | `InPort`, `Node`, `NodeExecutionContext`, `OutPort`, `PortShape`, `derive_input_contract`, `derive_output_contract` |
| `tests/unit/core/test_node_contracts.py:15` | `MAX_NODE_ERROR_MESSAGE_LENGTH`, `ArtifactTypeVariable`, `InPort`, `InputPortSpec`, `Node`, `NodeContractError`, `NodeContractResolutionError`, `NodeExecutionContext`, `OutPort`, `PortShape`, `UserFacingNodeError`, `derive_input_contract`, `resolve_node_contracts` |
| `tests/unit/core/test_plugins.py:24` | `MAX_NODE_PROGRESS_COUNTER`, `InPort`, `Node`, `NodeExecutionContext` |
| `tests/unit/plugins/test_gis_plugin.py:18` | `NodeExecutionContext` |
| `tests/unit/plugins/test_mistral_ocr.py:21` | `NodeExecutionContext`, `PortShape` |
| `tests/unit/plugins/test_openai_compatible_node.py:9` | `NodeExecutionContext`, `PortShape` |
| `tests/unit/plugins/test_reducto_ocr.py:21` | `NodeExecutionContext` |
| `tests/unit/runs/fakes.py:39` | `Node` |
| `tests/unit/runs/test_node_runner.py:49` | `InPort`, `Node`, `NodeExecutionContext`, `OutPort` |

## Baseline and finish line

On unchanged pinned main, the exact pytest selection below passed: **139 passed, 0 skipped, 20 warnings**. Ruff check and Ruff format --check passed on the original source module. Pyright strict reported **0 errors, 0 warnings** on both original source modules. Baselines were executed, not inferred from collection. No PostgreSQL or Docker coverage is claimed. Existing warnings are dependency deprecations. The architecture and OpenAPI tests are included in each count, so the counts overlap.

Before production edits, in the clean implementation checkout at the pinned base:

```bash
proof_dir=$(mktemp -d /tmp/grafy-night3-node-contracts.XXXXXX)
uv run python -m grafy_api.openapi "$proof_dir/main.json"
git show a27c9d79946083d7abb66563b4ea39e9df350956:apps/web/openapi/grafy.json > "$proof_dir/committed-main.json"
diff -u "$proof_dir/committed-main.json" "$proof_dir/main.json"
```

Authoring verified that this diff is empty. Keep the proof directory and schema exports outside git. After all commits, run from the repository root in the same shell:

```bash
files=(libs/core/src/grafy_core/nodes.py libs/core/src/grafy_core/node_ports.py libs/core/src/grafy_core/node_context.py libs/core/src/grafy_core/node_derivation.py tests/unit/architecture/test_node_contract_boundaries.py)
uv run ruff check "${files[@]}"
uv run ruff format --check "${files[@]}"
uv run pyright "${files[@]}"
uv run pytest -q -rs tests/unit/core/test_node_contracts.py tests/unit/core/test_invocation.py tests/unit/core/test_plugins.py tests/unit/runs/test_node_runner.py tests/unit/architecture/ tests/integration/ops/test_openapi.py
uv run python -m grafy_api.openapi "$proof_dir/refactored.json"
diff -u "$proof_dir/main.json" "$proof_dir/refactored.json"
git diff --check a27c9d79946083d7abb66563b4ea39e9df350956
git diff --name-status a27c9d79946083d7abb66563b4ea39e9df350956
```

All commands must exit zero. Pyright must have zero new diagnostics versus main, which here means zero total errors and warnings, including new test files. No suppressions, broadened Any types or removed runtime guards. OpenAPI diff must be empty; do not regenerate web types or update the schema to make it pass. Confirm every changed file is in the allowlist. Run only these focused suites, never the repo-wide suite. New architecture tests add to the baseline count.

## Blockers

None at authoring time. If blocked, replace this paragraph with the exact command, exit status, source file:line, expected and actual behavior, and smallest owner decision needed. Stop the affected implementation. A moved Pydantic definition changing OpenAPI references is a blocker, not permission to rename schemas or edit routes. Do not repair unrelated failures or weaken tests.

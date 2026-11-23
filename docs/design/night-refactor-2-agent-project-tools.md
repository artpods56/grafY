# Agent project-tool adapters split by use case

Difficulty: **complex**.

Base: fetched `origin/main` at `a27c9d79946083d7abb66563b4ea39e9df350956`, the merge of PR #237. Local `main` was stale during authoring. All source line references below refer to this immutable commit. Reference format: `docs/design/artifacts-service-split.md` on that commit.

Zero behavior change. Preserve HTTP/OpenAPI paths, parameter names, schemas, status codes, headers, error types, exact messages, validation order, transaction boundaries, iteration order, and cancellation behavior. Preserve public Python imports and call signatures. Source file locations and private helper names may change only as mapped here.

Follow the tables literally. If the base differs semantically, a caller exists outside the allowlist, a new module is needed, or verification fails unexpectedly, fill Blockers and stop. Do not invent a replacement design.

## Survey and selection

Surveyed tracked source on fetched `origin/main`, excluding `apps/api/src/grafy_api/artifacts/`, route artifact directories, and `apps/tiler/`. Python AST measurements count physical lines, class spans from `class` through its last statement, and lexical call sites. A private helper candidate has one or two call sites; decorators and protocol callbacks require manual review. Constructor wrappers below are manually confirmed, not every function whose last statement is a call.

| Candidate | File lines | Largest class lines | Private helper candidates | Nested defs | Decision |
|---|---:|---:|---:|---:|---|
| `apps/api/src/grafy_api/agents/turns.py` | 1584 | AgentService 1126 | 29 | 1 | Defer: admission, cancellation and streaming share mutable lifecycle state |
| `libs/core/src/grafy_core/runtime/in_memory.py` | 1525 | InMemoryProjectRepository 324 | 6, including one constructor wrapper | 0 | Select: nine repository adapters already have separate contracts |
| `libs/core/src/grafy_core/domain/collaboration.py` | 1417 | ProjectHead 89 | 10 | 0 | Defer: large command union and validation dispatch, rather than a single God class |
| `libs/core/src/grafy_core/application/identity.py` | 1212 | IdentityService 1113 | 5 | 0 | Defer: authorization, owner invariants and revocation transactions |
| `libs/core/src/grafy_core/application/collaboration.py` | 1139 | CollaborationService 1000 | 8 | 0 | Defer: checkpoint and idempotency transaction coordination |
| `apps/api/src/grafy_api/agents/project_tools.py` | 612 | ArtifactModelViews 133 | 13 | 1 | Select: five existing adapters, concentrated helper chains, dedicated tests |

The selected areas have respectively one and zero mere constructor wrappers. Candidate counts for deferred areas are syntactic screening counts, not approved removal inventories. Only the exhaustive tables in each selected spec authorize edits.

The broader inventory found 106 API Python files / 20,257 lines after artifact exclusions, 176 library source files / 31,738 lines, and 47 Plugin Python files / 7,579 lines. No tracked `workers/` or `packages/` source trees exist. Persistence's `repositories/projects.py` is 911 lines with a 607-line class, but its relational proof requires PostgreSQL. The web inventory has 404 TypeScript files / 124,101 lines: generated API types are 7,840 lines and `Workbench.tsx` is 5,220 lines. Those are lower priority for this Python-focused overnight pass. No web edits are authorized.

These choices prioritize payoff that can be checked locally, not just the largest file. Read ADR 0002 for collaboration ownership and ADR 0021 for Agent context and tools. No domain decision changes.
This needs a stronger model than Qwen for implementation. Moving the existing classes is mechanical; inlining the rendering chain duplicates control flow into three terminal paths. Do not assign the complete spec to Qwen unattended. No alternative design is authorized.

## Baseline

The Finish line pytest selection ran on unchanged main: **193 passed, 0 skipped, 20 warnings, 4.25s**. Scoped ruff lint and format pass. Pyright reports one existing `reportUnknownArgumentType` in `_writable_json_type` at line 252, where `set(properties)` receives a partially unknown dictionary.

## Allowed file set

Edit only `apps/api/src/grafy_api/agents/project_tools.py` among existing production files. Create:

- `apps/api/src/grafy_api/agents/tool_ports.py`
- `apps/api/src/grafy_api/agents/tool_arguments.py`
- `apps/api/src/grafy_api/agents/tool_views.py`
- `apps/api/src/grafy_api/agents/project_context.py`

Create `tests/unit/architecture/test_project_tool_boundaries.py`. The only other editable file is `docs/design/night-refactor-2-agent-project-tools.md`, solely for Blockers. Existing tests and callers are read-only.

## Module split

All destinations below are relative to `apps/api/src/grafy_api/agents/`. Keep the five existing classes, bases, constructor signatures and public method signatures. Do not add services or protocols. Remove only the methods listed in the inline tables.

| Source class and line | Destination | Exact retained methods |
|---|---|---|
| `RegistryNodePorts` at `apps/api/src/grafy_api/agents/project_tools.py:77` | `tool_ports.py` | `__init__`, `input_ports`, `output_ports`, `title` |
| `ContentAddressedArguments` at `apps/api/src/grafy_api/agents/project_tools.py:145` | `tool_arguments.py` | `__init__`, `json_type`, `ref_for`, `page_for`, `get_artifact` |
| `ArtifactModelViews` at `apps/api/src/grafy_api/agents/project_tools.py:257` | `tool_views.py` | `__init__`, `render`, `render_library_item` |
| `ProjectToolComputation` at `apps/api/src/grafy_api/agents/project_tools.py:419` | `project_tools.py` | `__init__`, `__call__` |
| `ProjectContextReader` at `apps/api/src/grafy_api/agents/project_tools.py:446` | `project_context.py` | `__init__`, `read` |

Move `ARGUMENT_ARTIFACT_NAMESPACE:64` to `tool_arguments.py`; move `MAX_VIEW_CHARS:68`, `TABLE_VIEW_ROWS:71`, `SEQUENCE_VIEW_ITEMS:74`, and `_clip:411` to `tool_views.py`. `_clip` has four lexical call sites and stays. Preserve constant values. Move `logger:66` to `project_context.py` but construct it with `logging.getLogger("grafy_api.agents.project_tools")` to preserve the existing log identity.

Keep `build_toolbox_factory:562` in `project_tools.py`, with the flattening below. Explicitly re-export the moved classes and all four constants from `project_tools.py` using same-name aliases. Keep the existing `__all__` list unchanged. `MAX_VIEW_CHARS` remains importable even though absent from `__all__`. Existing imports in `services/application.py`, `test_project_tools.py`, and `test_agent_context.py` stay unchanged.

Dependency direction: `project_tools -> project_context, tool_ports, tool_arguments, tool_views`; `project_context -> tool_ports, tool_views`; the three `tool_*` modules never import each other or project_tools/project_context/turns. Existing imports of toolbox interfaces are allowed. Only `project_tools.py` retains the existing import of `AgentToolboxFactory` from turns. No new imports from HTTP routes. Keep existing RunService dependencies in ProjectToolComputation and ProjectContextReader.

Source class spans: RegistryNodePorts 59, ContentAddressedArguments 99, ArtifactModelViews 133, ProjectToolComputation 25, ProjectContextReader 114. Do not split these classes further. No line cap is imposed on `tool_views.py`: the requested inlining deliberately duplicates the render branches.

## Every private helper to inline

All source locations below are in `apps/api/src/grafy_api/agents/project_tools.py`. Apply from the deepest helpers outward. A helper's early return becomes a local result plus an exclusive branch when embedded in a caller; it must not accidentally return from `render` before remaining output ports are processed.

| Helper / source line | Exact callers | Rewrite |
|---|---|---|
| `_concrete:138` | `RegistryNodePorts._ports:97`, input and output loops | Inline `None if isinstance(contract, ArtifactTypeVariable) else contract`, using accepts or produces |
| `_writable_json_type:246` | `ContentAddressedArguments.__init__:148` | Inline the two guards as loop continues, then store string/integer type. Preserve order and exact schema-key check |
| `_ports:97` | `input_ports:83`, `output_ports:86` | Copy registration lookup and resolution into both, retain only the matching input/output loop; preserve UnknownOperatorError -> None |
| `_addressed:205` | `ref_for:164`, `page_for:175` | Copy serialization, digest/id derivation and transaction into each after payload creation. No commit or rollback reordering |
| `_scalar_text:392` | `_render_body:323` | Inline single-key, accepted-key and scalar type checks. Preserve bool handling via str |
| `_compact_json:405` | `_render_body:323`, `_render_stored_json:341` | Inline json.dumps with exact ensure_ascii, sort_keys and separators arguments |
| `_render_stored_json:341` | `_render_body:323` | Embed bounded read, finally-close, decode, parse and truncation branches; preserve every marker and limit |
| `_render_table:371` | `_render_body:323` | Embed page load and header/row rendering; preserve order, missing values, and clipping |
| `_render_body:323` | `_render_artifact:319` | Embed all branches into local `body`, then prefix the artifact id exactly once |
| `_render_artifact:319` | `render_library_item:293`, `_render_ref:307` | Embed body rendering and prefix construction after each existing missing-artifact guard |
| `_render_ref:307` | `_render_value:279`, sequence and scalar branches | Embed lookup and missing-ref formatting separately in each branch. Sequence list comprehension becomes ordered loop; same awaits in the same order |
| `_render_value:279` | `render:273` | Embed scalar/sequence logic per output port, assigning rendered text before appending section. Preserve five-item limit and indentation |
| `_node_output:531` | `ProjectContextReader.read:462` | Embed instance_result and missing/stored branches inside node_output link branch, retaining surrounding try/except and label construction |

Final private helper inventory: only module-level `_clip` remains from this table's area. The callback added below is retained because it implements the callable contract, not because it shortens a caller. Do not leave helper chains under new names or move them into staticmethods.

## Constructor wrappers

| Source | Count | Decision |
|---|---:|---|
| Entire project_tools.py | 0 mere constructor wrappers | No additional deletion. `AgentToolbox.build` can return None and performs availability logic. ProjectToolComputation is an existing callable adapter, not a constructor helper |

## Nested function to flatten

| Nested definition | Caller / capture | Exact destination |
|---|---|---|
| `build_toolbox_factory.factory:576` | Returned at line 601; captures ports, arguments, runs, registry, unit_of_work_factory, storage | Module-level `_build_project_toolbox` in project_tools.py, bound with functools.partial |

`_build_project_toolbox` takes the existing five positional arguments unchanged: `workspace_id: UUID`, `project_id: UUID`, `graph_id: str`, `agent: GraphAgent`, `document: GraphDocument`. Add keyword-only `ports: RegistryNodePorts`, `arguments: ContentAddressedArguments`, `runs: RunService`, `registry: PluginRegistry`, `unit_of_work_factory: Callable[[], UnitOfWorkPort]`, `storage: FileStoragePort`. Return type remains `AgentToolbox | None`. Copy the nested factory's AgentToolbox.build call exactly.

`build_toolbox_factory` still creates ports and arguments once, then returns `partial(_build_project_toolbox, ports=ports, arguments=arguments, runs=runs, registry=registry, unit_of_work_factory=unit_of_work_factory, storage=storage)`. Views and computation are constructed once per callback invocation, exactly as before. No captured mutable defaults, nested defs, replacement lambda, callable factory class, decorator, or registry.

## Behavior and exclusions

Keep JSON byte serialization, UUID namespace and digest input identical. Preserve reuse of an existing artifact, rollback after ObjectAlreadyExistsError, and write metadata. Keep content reads outside the completed lookup transaction. Every stream still closes in finally. Keep table-first dispatch, JSON content-type matching, clipping messages, sequence limits, context ordering and per-link exception handling unchanged. Do not add caching, concurrent rendering, streaming, data sanitization or new validation.

Do not edit `turns.py`, `toolbox.py`, `context.py`, RunService, composition, storage, in-memory adapters, routes, artifacts, Plugins, tiler, web, models or configuration. No new abstraction layers or metaprogramming. Inlining duplicates code here; do not undo it with a new helper or common base.

Surface checklist: HTTP/OpenAPI unchanged; builtin/Plugin port and artifact registration reads unchanged for every provider; Workspace ids and lookup scoping unchanged; unavailable/missing/error paths retained; ADR 0021 and domain vocabulary unchanged; web not applicable.

## Ordered commits

1. `refactor: inline agent port and argument helpers`. Inline `_concrete`, `_ports`, `_writable_json_type`, `_addressed` in the original module. Run `uv run pytest -q tests/unit/api/agents/test_project_tools.py tests/unit/api/agents/test_toolbox.py`.
2. `refactor: inline agent artifact rendering helpers`. Apply the rendering rows in the stated order, then `_node_output`. Run `uv run pytest -q tests/unit/api/agents/test_project_tools.py tests/unit/api/agents/test_agent_context.py tests/unit/api/agents/test_agent_turn_tools.py`.
3. `refactor: split agent project tool adapters`. Move exactly the classes and constants above and flatten factory with partial. Run the complete Finish line pytest selection. All existing public imports must work unchanged.
4. `test: enforce agent project tool boundaries`. Add the allowlisted architecture test: parse imports to enforce dependency directions and no nested production defs; assert public re-exports identify the original class objects. Do not assert exact source text. Run all Finish line commands.

## Finish line

Run from the repository root. No repo-wide lint or test suites. Every created or edited Python file, including the area-specific architecture test, is in `files` below.

```bash
files=(apps/api/src/grafy_api/agents/project_tools.py apps/api/src/grafy_api/agents/tool_ports.py apps/api/src/grafy_api/agents/tool_arguments.py apps/api/src/grafy_api/agents/tool_views.py apps/api/src/grafy_api/agents/project_context.py tests/unit/architecture/test_project_tool_boundaries.py)
uv run ruff check "${files[@]}"
uv run ruff format --check "${files[@]}"
uv run pyright "${files[@]}"
uv run pytest -q -rs tests/unit/api/agents/ tests/unit/architecture/ tests/integration/ops/test_openapi.py
git diff --check a27c9d79946083d7abb66563b4ea39e9df350956
git diff --name-status a27c9d79946083d7abb66563b4ea39e9df350956
```

One baseline pyright diagnostic is allowed: `reportUnknownArgumentType` from `set(properties)` in the inlined schema check, formerly project_tools.py:252, now tool_arguments.py. Do not change runtime validation or suppress the diagnostic. No new diagnostic or suppression is accepted. Compare diagnostics by rule and affected expression, not shifted line numbers. Existing diagnostics are an explicit exception to a zero-exit pyright gate; report them, do not silently claim a clean typecheck. New files must pass formatting, including moved pre-existing code. Check every changed path against the allowlist.

Before production edits, export the schema from the clean implementation base, which must match the pinned main commit. Keep exports outside the checkout:

```bash
proof_dir=$(mktemp -d /tmp/grafy-night-openapi.XXXXXX)
uv run python -m grafy_api.openapi "$proof_dir/main.json"
git show a27c9d79946083d7abb66563b4ea39e9df350956:apps/web/openapi/grafy.json > "$proof_dir/committed-main.json"
diff -u "$proof_dir/committed-main.json" "$proof_dir/main.json"
```

After all commits, in the same shell:

```bash
uv run python -m grafy_api.openapi "$proof_dir/refactored.json"
diff -u "$proof_dir/main.json" "$proof_dir/refactored.json"
```

Both diffs must be empty. Authoring verified that the generated schema matches the committed schema on main. Do not export over `apps/web/openapi/grafy.json`, regenerate clients, or add schema snapshots to git. If main advances, rebase and remeasure the baseline before implementing; do not compare a changed main schema against an old export.

## Blockers

None. The missing imports and the inlined table row-count variable collision are resolved. The known baseline pyright limitation remains as documented above.

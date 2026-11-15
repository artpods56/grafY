# Spatial contracts split by use case

Rating: **mechanical**. Move existing models and aliases, inline one small bounds helper, and give one shared validator a public name. Recursive geometry traversal stays unchanged.

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

Edit `libs/core/src/grafy_core/spatial_contracts.py`. Create exactly:

- `libs/core/src/grafy_core/spatial_bounds.py`
- `libs/core/src/grafy_core/spatial_styles.py`
- `libs/core/src/grafy_core/spatial_features.py`
- `libs/core/src/grafy_core/spatial_maps.py`
- `libs/core/src/grafy_core/spatial_metadata.py`
- `tests/unit/architecture/test_spatial_contract_boundaries.py`

The only other editable file is `docs/design/night-refactor-3-spatial-contracts.md`, solely for Blockers. No deletions. No caller edits, including API artifact readers and GIS producers.

## Exact split

All source locations below are in `libs/core/src/grafy_core/spatial_contracts.py`. Move complete definitions with decorators, fields, validators, aliases and defaults intact. The original file becomes an explicit import facade with its current module docstring; no forwarding functions, star imports, dynamic exports or new classes. Re-export every public definition and type alias listed below using same-name aliases. Do not re-export private helpers. The consumer table below records import sites; they stay unchanged.

| Source definition and line | Destination | Callers / use |
|---|---|---|
| `GeoBounds:24`, `Bounds:260` | spatial_bounds.py | Payload/metadata bounds and validated producer/map bounds respectively; keep these two types distinct |
| `_validated_bounds:309` | spatial_bounds.py as public `validated_bounds` | Four validators listed in helper table |
| `HexColor:101`, `RasterResampling:104`, `GeoCategoryValue:135` | spatial_styles.py | Style model fields |
| `GeoFillStyle:107`, `GeoLineStyle:115`, `GeoPointStyle:124`, `GeoPointCategory:138`, `GeoLabelStyle:169` | spatial_styles.py | Vector and categorized styles |
| `GeoVectorStyle:186`, `GeoCategorizedPointStyle:197`, `GeoFeatureStyle:229`, `GeoRasterStyle:235`, `GeoLayerStyle:254` | spatial_styles.py | GeoMapLayer.style and external GIS/API consumers |
| `GeoFeatureCollectionPayload:27`, `GeoFeatureCollection:338`, `_UploadedFeatureCollection:403` | spatial_features.py | Stored reader, producer factory and GeoFeatureCollection.from_geojson_bytes:372 respectively |
| `_validate_geometry:584`, `_collect_positions:623` | spatial_features.py | Recursive feature validation; exact calls below |
| `WmsVersion:300`, `WmsImageFormat:303`, `BasemapKind:306` | spatial_maps.py | GeoWmsSource and GeoMapDocument fields |
| `_validate_ref:324`, `GeoFeatureArtifactSource:410`, `GeoRasterArtifactSource:427`, `GeoWmsSource:444`, `GeoLayerSource:477` | spatial_maps.py | Map source validation and GeoMapLayer.source |
| `GeoMapLayer:483`, `GeoMapDocument:527` | spatial_maps.py | GIS builders and API readers, imports below |
| `GeoFeatureCollectionMetadata:45`, `GeoVectorProjectionMetadata:54`, `GeoRasterProjectionMetadata:76` | spatial_metadata.py | Stored metadata readers and producer subclasses |
| `VectorProjectionMetadata:557`, `RasterProjectionMetadata:568` | spatial_metadata.py | Producer-side defaults and bounds validation |
| `GeoPropertyValueType:663`, `GeoFeaturePropertyMetadata:674`, `GeoStoredFeatureCollectionMetadata:682` | spatial_metadata.py | Stored property metadata; external consumers below |
| `_bounds:655` | Delete after inlining | GeoFeatureCollection.validate_features:359 and from_features:399 |

Within these modules, allowed dependency edges are spatial_features -> spatial_bounds; spatial_maps -> spatial_bounds, spatial_styles; spatial_metadata -> spatial_bounds. spatial_bounds and spatial_styles import none of the other split modules. The facade imports all five leaves; leaves never import the facade. Existing imports from grafy_core.artifacts and grafy_core.egress remain allowed. No API, Plugin or HTTP imports. The shared validator is public specifically to avoid a private cross-module import; do not add a generic validators module.

Move every class intact. Keep all validators on their original classes, in their original order and modes, with their original signatures. This preserves the intentional distinction between permissive stored readers and stricter producers. Do not collapse producer and reader models or replace inheritance with composition.

## Exhaustive helper inventory

All source paths are `libs/core/src/grafy_core/spatial_contracts.py`. Locations after the colon below refer to that file.

| Helper | Exact callers at call lines | Decision |
|---|---|---|
| `_validated_bounds:309` | GeoWmsSource.validate_bounds:466; GeoMapDocument.validate_initial_bounds:539; VectorProjectionMetadata.validate_bounds:565; RasterProjectionMetadata.validate_bounds:578 | Move unchanged to spatial_bounds.py and rename to validated_bounds. Update those four calls/imports only. Preserve None handling and finite, longitude, latitude, ordering checks in that order |
| `_validate_ref:324` | GeoFeatureArtifactSource.validate_artifact:418; GeoRasterArtifactSource.validate_artifact:435; GeoMapDocument.validate_layer_refs:545 | Keep private in spatial_maps.py, three sites, no cross-module import |
| `_validate_geometry:584` | GeoFeatureCollection.validate_features:357; GeoFeatureCollection.from_features:393; itself:614 | Keep private in spatial_features.py. Recursion is required; do not unroll or inline recursive traversal |
| `_collect_positions:623` | _validate_geometry:620; itself:652 | Keep private in spatial_features.py. Recursive algorithm, not an orphan wrapper despite two lexical sites |
| `_bounds:655` | GeoFeatureCollection.validate_features:359; GeoFeatureCollection.from_features:399 | Inline twice. If coordinate list empty, result is None; else build longitude and latitude lists and assign `(min(longitudes), min(latitudes), max(longitudes), max(latitudes))`. In validate_features use observed and assign calculated before comparison; in from_features use coordinates and assign calculated before cls(..., bounds=calculated) |

For inlining `_bounds`, annotate calculated as `Bounds | None` if needed. Preserve coordinate traversal and floating-point conversion. Do not sort, deduplicate, clamp or round. No private helpers may be imported by another split module. Final private helper set is exactly _validate_ref, _validate_geometry and _collect_positions, plus the private _UploadedFeatureCollection model. It is used only within spatial_features.py.

## Constructor wrappers and nested functions

| Source | Callers / inventory | Decision |
|---|---|---|
| `GeoFeatureCollection.from_geojson_bytes:372` | External GIS ingestion and tests; calls from_features after guarded parsing | Keep: parses content and translates errors, not a mere constructor wrapper |
| `GeoFeatureCollection.from_features:384` | from_geojson_bytes:381 and external callers | Keep: traverses geometry and derives bounds before construction |
| Entire spatial_contracts.py | Zero mere constructor wrappers; zero nested defs | Introduce none. Pydantic validators stay methods, not nested functions |

Keep JSON serialization flags and bytes unchanged. GeoFeatureCollectionPayload must still accept unbounded stored payloads that GeoFeatureCollection rejects. Keep source-name validation differences. Preserve discriminated-union order, type alias names, strict scalar distinctions, defaults, field titles and json_schema_extra. Preserve bool versus int distinction in categorized values and geometry coordinates. Preserve map reference order, duplicate detection order, category zoom checks and WMS destination validation. No new DNS call, caching, geometry repair, normalization or validation.

## Ordered commits

1. `refactor: inline spatial feature bounds helper`. Inline _bounds at both sites in the original module and delete it. Run `uv run pytest -q tests/unit/plugins/test_spatial_contracts.py tests/unit/plugins/test_gis_plugin.py`.
2. `refactor: split spatial contracts by use case`. Move precisely the definitions above, make validated_bounds public and replace the original module with explicit re-exports. Run `uv run pytest -q tests/unit/plugins/test_spatial_contracts.py tests/unit/plugins/test_gis_plugin.py tests/integration/artifacts/test_gis_artifacts.py tests/integration/artifacts/test_spatial_storage.py tests/unit/architecture/ tests/integration/ops/test_openapi.py`.
3. `test: enforce spatial contract module boundaries`. Add only the allowlisted architecture test. Assert the dependency edges and absence of nested defs/private cross-module imports through AST inspection. Assert public facade exports are the same objects as the leaf definitions, including producer/reader classes and aliases. Do not assert exact source text or line counts. Run all finish-line commands.

## Surface checklist

Contract: identical Pydantic/OpenAPI schemas, no route changes. Builtin families/Plugins: GIS producers and API readers keep the same imports; image, llm, mistral, reducto and table hosts need no edits because their registration/contract paths are unchanged. Tenancy: no Workspace lookup or permission changes. Reverse states: valid and invalid geometry, bounds, style and reference cases retain their existing acceptance/errors; no lifecycle state changes. Docs: no domain decision or vocabulary changes. Web: unchanged schemas require no client regeneration. Artifact and tiler consumers stay read-only.

## Existing import consumers

All files below are read-only. Public imports continue to resolve through grafy_core.spatial_contracts. Internal validator/factory call sites are listed above.

| Import site | Imported names |
|---|---|
| `apps/api/src/grafy_api/artifacts/geo.py:9` | `GeoVectorStyle` |
| `apps/api/src/grafy_api/artifacts/models.py:23` | `GeoPropertyValueType`, `GeoRasterStyle`, `GeoBounds`, `GeoFeatureCollectionPayload`, `GeoFeatureCollectionMetadata`, `GeoVectorProjectionMetadata`, `GeoRasterProjectionMetadata` |
| `libs/core/src/grafy_core/spatial_storage.py:9` | `GeoFeatureCollectionMetadata`, `GeoFeatureCollectionPayload` |
| `plugins/gis/src/grafy_plugin_gis/artifacts.py:10` | `GeoMapDocument`, `GeoMapLayer` |
| `plugins/gis/src/grafy_plugin_gis/nodes.py:57` | `BasemapKind`, `Bounds`, `GeoFeatureArtifactSource`, `GeoFeatureCollection`, `GeoFeatureStyle`, `GeoMapDocument`, `GeoMapLayer`, `GeoRasterArtifactSource`, `GeoRasterStyle`, `GeoVectorStyle`, `GeoWmsSource`, `WmsImageFormat`, `WmsVersion` |
| `plugins/gis/src/grafy_plugin_gis/persistence.py:18` | `GeoPropertyValueType`, `GeoFeaturePropertyMetadata`, `GeoStoredFeatureCollectionMetadata` |
| `plugins/gis/src/grafy_plugin_gis/persistence.py:50` | `GeoFeatureCollection`, `RasterProjectionMetadata`, `VectorProjectionMetadata` |
| `plugins/gis/src/grafy_plugin_gis/plugin.py:17` | `GeoMapDocument`, `GeoMapLayer` |
| `plugins/gis/src/grafy_plugin_gis/smoke.py:15` | `RasterProjectionMetadata` |
| `plugins/gis/src/grafy_plugin_gis/wfs.py:26` | `Bounds`, `GeoFeatureCollection` |
| `tests/unit/plugins/test_gis_plugin.py:43` | `GeoCategorizedPointStyle`, `GeoFeatureArtifactSource`, `GeoFeatureCollection`, `GeoMapLayer`, `GeoRasterStyle`, `GeoVectorStyle`, `RasterProjectionMetadata`, `VectorProjectionMetadata` |
| `tests/unit/plugins/test_spatial_contracts.py:6` | `GeoFeatureCollectionPayload`, `GeoRasterProjectionMetadata`, `GeoVectorProjectionMetadata` |
| `tests/unit/plugins/test_spatial_contracts.py:11` | `GeoFeatureCollection`, `RasterProjectionMetadata`, `VectorProjectionMetadata` |

## Baseline and finish line

On unchanged pinned main, the exact pytest selection below passed: **91 passed, 0 skipped, 20 warnings**. Ruff check and Ruff format --check passed on the original source module. Pyright strict reported **0 errors, 0 warnings** on both original source modules. Baselines were executed, not inferred from collection. No PostgreSQL or Docker coverage is claimed. Existing warnings are dependency deprecations. The architecture and OpenAPI tests are included in each count, so the counts overlap.

Before production edits, in the clean implementation checkout at the pinned base:

```bash
proof_dir=$(mktemp -d /tmp/grafy-night3-spatial-contracts.XXXXXX)
uv run python -m grafy_api.openapi "$proof_dir/main.json"
git show a27c9d79946083d7abb66563b4ea39e9df350956:apps/web/openapi/grafy.json > "$proof_dir/committed-main.json"
diff -u "$proof_dir/committed-main.json" "$proof_dir/main.json"
```

Authoring verified that this diff is empty. Keep the proof directory and schema exports outside git. After all commits, run from the repository root in the same shell:

```bash
files=(libs/core/src/grafy_core/spatial_contracts.py libs/core/src/grafy_core/spatial_bounds.py libs/core/src/grafy_core/spatial_styles.py libs/core/src/grafy_core/spatial_features.py libs/core/src/grafy_core/spatial_maps.py libs/core/src/grafy_core/spatial_metadata.py tests/unit/architecture/test_spatial_contract_boundaries.py)
uv run ruff check "${files[@]}"
uv run ruff format --check "${files[@]}"
uv run pyright "${files[@]}"
uv run pytest -q -rs tests/unit/plugins/test_spatial_contracts.py tests/unit/plugins/test_gis_plugin.py tests/integration/artifacts/test_gis_artifacts.py tests/integration/artifacts/test_spatial_storage.py tests/unit/architecture/ tests/integration/ops/test_openapi.py
uv run python -m grafy_api.openapi "$proof_dir/refactored.json"
diff -u "$proof_dir/main.json" "$proof_dir/refactored.json"
git diff --check a27c9d79946083d7abb66563b4ea39e9df350956
git diff --name-status a27c9d79946083d7abb66563b4ea39e9df350956
```

All commands must exit zero. Pyright must have zero new diagnostics versus main, which here means zero total errors and warnings, including new test files. No suppressions, broadened Any types or removed runtime guards. OpenAPI diff must be empty; do not regenerate web types or update the schema to make it pass. Confirm every changed file is in the allowlist. Run only these focused suites, never the repo-wide suite. New architecture tests add to the baseline count.

## Blockers

None at authoring time. If blocked, replace this paragraph with the exact command, exit status, source file:line, expected and actual behavior, and smallest owner decision needed. Stop the affected implementation. A moved Pydantic definition changing OpenAPI references is a blocker, not permission to rename schemas or edit routes. Do not repair unrelated failures or weaken tests.

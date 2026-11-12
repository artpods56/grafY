# Artifacts service split and helper cleanup

This specification defines a mechanical refactor of `apps/api/src/grafy_api/artifacts/service.py` (1,648 lines), a targeted `uow` naming cleanup, and removal of single-purpose private helpers and constructor wrappers in the touched files.

The implementation agent must follow every mapping, signature, table decision, and commit boundary in this document verbatim. Do not invent extra modules, base classes, protocols, registries, or cleanups outside the tables below. If anything in the checkout contradicts this specification, stop immediately, record the discrepancy under [Blockers](#blockers), and make no improvised edits.

## Base state and baseline verification

- Base branch: `origin/main`
- Base commit SHA: `6f9c6cfb7f1eba1acc771ba10af783a461a3bbd5` (`Merge pull request #236 from artpods56/fix/publish-images-needs-web-e2e`)
- Implementation branch: `refactor/artifacts-split`
- Public HTTP and OpenAPI change: none. Every route path, method, parameter, status code, header, and response schema stays identical.

Baseline check results recorded on `6f9c6cfb7f1eba1acc771ba10af783a461a3bbd5`:

1. `uv run ruff check`
   - Result: exit 0 (`All checks passed!`).
2. `uv run ruff format --check`
   - Repo-wide result: exit 1 because 12 unrelated files on `origin/main` are unformatted (`apps/api/src/grafy_api/auth/service.py`, `apps/api/src/grafy_api/auth/transactions.py`, `infra/db/migrations/versions/0001_baseline.py`, `infra/e2e/openai-provider/server.py`, `libs/core/src/grafy_core/domain/agent_keys.py`, `libs/core/src/grafy_core/runtime/in_memory.py`, `libs/persistence/src/grafy_persistence/adapters/repositories/agent_conversations.py`, `plugins/llm/src/grafy_plugin_llm/openai_compatible_sdk.py`, `tests/unit/agents/test_conversations.py`, `tests/unit/persistence/test_agent_conversation_persistence.py`, `tests/unit/persistence/test_agent_key_persistence.py`, `tests/unit/plugins/test_openai_compatible_provider.py`). Do not touch those 12 files.
   - Scoped result on all files in this specification: exit 0 (`21 files already formatted`).
3. `uv run pyright`
   - Repo-wide result: exit 1 (`1448 errors` pre-existing across the workspace; CI runs `uv run pyright libs/client`, which exits 0 with `0 errors`).
   - Scoped result on non-route production files in this specification: `1 error` on `apps/api/src/grafy_api/artifacts/service.py:356` (`dict[str, str]` passed to `JsonObject | None`, fixed when inlining `_cell_text_artifact` by annotating `payload: JsonObject = {"value": value}`), and `0 errors` on `dependencies.py`, `composition.py`, `app_state.py`, `library/service.py`, `library/folders.py`, `artifact_availability.py`, and `runs/edge_values.py`.
   - `apps/api/src/grafy_api/v1/routes/artifacts/views.py` has `61 errors` pre-existing, all caused by the repo-wide FastAPI pattern `access: require_workspace_capability(...)`. Do not alter `require_workspace_capability` annotations.
   - `apps/api/src/grafy_api/artifacts/models.py` has `6 errors` pre-existing (`Field(default_factory=list)` without type arguments). Leave unrelated fields in `models.py` untouched.
   - Scoped test files have `3 errors` pre-existing: `test_artifact_wms.py:172` and `test_composition.py:124` (missing `assert read is not None` before `read.content`, add that assertion while updating those two tests), and `test_node_runner.py:287` (`_clear_echo_runs` unused, out of scope).
4. Focused pytest baseline:
   ```bash
   uv run pytest \
     tests/unit/architecture/test_import_boundaries.py \
     tests/unit/api/test_single_owner.py \
     tests/unit/api/services/ \
     tests/unit/runs/test_node_runner.py \
     tests/integration/artifacts/test_gis_artifacts.py \
     tests/integration/artifacts/test_spatial_storage.py \
     tests/integration/library/ \
     tests/integration/ops/test_openapi.py
   ```
   - Result: exit 0 (`159 passed, 0 failed, 20 warnings in 27.94s`).

## Hard rules for implementation

1. **Zero behavior change.** Keep all error types, HTTP status codes, detail strings, headers, caching directives, and OpenAPI schemas identical.
2. **No new abstractions.** Do not introduce base classes, mixins, `Protocol` classes, ABCs, decorators, registries, or metaprogramming.
3. **Strict file allowlist.** Create, edit, or delete only the files listed in [Allowed file set](#allowed-file-set). Do not format, lint-fix, or touch any other file.
4. **Act only on the helper tables.** Inline, flatten, move, or keep helpers strictly according to [Orphan helpers and constructor wrappers](#orphan-helpers-and-constructor-wrappers) and [Nested functions and lambdas](#nested-functions-and-lambdas). Do not hunt for additional helpers in any file.
5. **Preserve acyclic package imports.** Inside `grafy_api/artifacts/`, imports flow strictly upward:
   - `errors.py` and `models.py` import nothing from other `grafy_api.artifacts.*` modules.
   - `wms.py` and `tables.py` import from `models.py` only (never from `content.py`, `geo.py`, or `geo_tiles.py`).
   - `geo.py` imports from `models.py` only (never from `geo_tiles.py`, `content.py`, `tables.py`, `wms.py`, or `errors.py`).
   - `geo_tiles.py` imports from `errors.py`, `models.py`, `wms.py`, and `geo.py`.
   - `content.py` imports from `errors.py`, `models.py`, and `geo.py`.
   - None of `grafy_api/artifacts/*.py` may import `fastapi`, `starlette`, `grafy_api.app_state`, or `grafy_api.v1.routes.*`.
6. **Module size cap.** Every new module split out of `service.py` (`errors.py`, `wms.py`, `content.py`, `tables.py`, `geo.py`, `geo_tiles.py`, `__init__.py`) must stay at or below 450 lines after `ruff format`. Pre-existing `artifacts/models.py` (689 lines on `main`, ~645 lines after removing 5 orphan classmethods) is not split in this task. `apps/api/src/grafy_api/artifacts/service.py` must be deleted.
7. **Stop on mismatch.** If a test fails for an unexpected reason or a file differs from what this specification describes, stop, document the exact error and file path in [Blockers](#blockers), and do not improvise workarounds.

## Allowed file set

Created:
- `apps/api/src/grafy_api/artifacts/errors.py`
- `apps/api/src/grafy_api/artifacts/wms.py`
- `apps/api/src/grafy_api/artifacts/content.py`
- `apps/api/src/grafy_api/artifacts/tables.py`
- `apps/api/src/grafy_api/artifacts/geo.py`
- `apps/api/src/grafy_api/artifacts/geo_tiles.py`

Deleted:
- `apps/api/src/grafy_api/artifacts/service.py`

Edited production files:
- `apps/api/src/grafy_api/artifacts/__init__.py`
- `apps/api/src/grafy_api/artifacts/models.py`
- `apps/api/src/grafy_api/v1/routes/artifacts/dependencies.py`
- `apps/api/src/grafy_api/v1/routes/artifacts/views.py`
- `apps/api/src/grafy_api/services/composition.py`
- `apps/api/src/grafy_api/app_state.py`
- `apps/api/src/grafy_api/library/service.py`
- `apps/api/src/grafy_api/library/models.py`
- `apps/api/src/grafy_api/library/folders.py`
- `apps/api/src/grafy_api/artifact_availability.py`
- `apps/api/src/grafy_api/runs/edge_values.py`

Edited test files:
- `tests/support/workbench.py`
- `tests/unit/api/test_single_owner.py`
- `tests/unit/api/services/test_table_text_artifacts.py`
- `tests/unit/api/services/test_composition.py`
- `tests/unit/api/services/test_artifact_wms.py`
- `tests/unit/api/services/test_artifact_streaming.py`
- `tests/unit/runs/test_node_runner.py`
- `tests/integration/artifacts/test_gis_artifacts.py`
- `tests/integration/artifacts/test_spatial_storage.py`

## Target modules in `apps/api/src/grafy_api/artifacts/`

Note on `geo.py` vs `geo_tiles.py`: non-WMS spatial code in today's `service.py` spans ~810 lines (`L182-320` and `L648-1359`), which cannot fit into one module under the 450-line limit. Splitting spatial operations into `geo.py` (map render descriptors and linked feature queries) and `geo_tiles.py` (PMTiles archives, exact feature reads, and raster TileJSON/XYZ/WMS tiles) keeps every split module under 450 lines without duplicating helpers.

### 1. `apps/api/src/grafy_api/artifacts/errors.py` (~35 lines)

Moves from `service.py`:
- `GeoRangeNotSatisfiableError` (`service.py:236-248`)
- `ArtifactResponseTooLargeError` (`service.py:251-264`)

Constructor dependencies:
- `GeoRangeNotSatisfiableError(*, total_size: int, etag: str, reason: str | None = None)` (subclasses `ValueError`)
- `ArtifactResponseTooLargeError(*, artifact_id: UUID, byte_size: int, max_byte_size: int)` (subclasses `WorkbenchOperationError` from `grafy_api.services.errors`)

Public `__all__` imported by callers:
- `ArtifactResponseTooLargeError`
- `GeoRangeNotSatisfiableError`

### 2. `apps/api/src/grafy_api/artifacts/wms.py` (~140 lines)

Moves from `service.py`:
- `WMS_RESPONSE_BYTE_BUDGET = 5 * 1_024 * 1_024` (`service.py:88`)
- `GeoTileRead` frozen slots dataclass (`service.py:108-112`)
- HTTP client setup and egress policy from `ArtifactService.__init__` (`service.py:384-395`)
- `ArtifactService.close` (`service.py:426-427`) -> `WmsTileClient.close`
- `ArtifactService._load_wms_tile` (`service.py:1361-1453`) -> `WmsTileClient.fetch_tile`, with `_web_mercator_tile_bounds` (`service.py:323-332`) inlined directly before `parameters = {...}`

Class contract:
```python
class WmsTileClient:
    """Fetches remote WMS raster tiles through the deployment egress guard."""

    def __init__(
        self,
        *,
        egress_policy: EgressPolicy | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._egress_policy = (
            default_egress_policy() if egress_policy is None else egress_policy
        )
        self._client = (
            httpx.AsyncClient(
                timeout=httpx.Timeout(15.0),
                follow_redirects=False,
                http2=False,
                trust_env=False,
                verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            )
            if client is None
            else client
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_tile(
        self,
        source: GeoWmsSourcePayload,
        *,
        z: int,
        x: int,
        y: int,
    ) -> GeoTileRead: ...
```

Public `__all__` imported by callers:
- `GeoTileRead`
- `WMS_RESPONSE_BYTE_BUDGET`
- `WmsTileClient`

### 3. `apps/api/src/grafy_api/artifacts/content.py` (~240 lines)

Moves from `service.py`:
- `ARTIFACT_RESPONSE_CHUNK_SIZE = 1 * 1_024 * 1_024` (`service.py:89`)
- `BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES = 64 * 1_024 * 1_024` (`service.py:90`)
- `ArtifactContentRead` frozen slots dataclass (`service.py:115-138`)
- `ArtifactContentService`:
  - `__init__` (`service.py:371-383`, narrowed to `uow`, `storage`, `artifact_types`)
  - `export_formats` (`service.py:397-419`, with `_artifact_is_json` from `L421-424` inlined as `if artifact.inline_payload is not None or artifact.content_type == "application/json":`)
  - `get` (`service.py:429-435`, using `async with self._uow as uow:`)
  - `load_content` (`service.py:437-471`, importing `GEO_FEATURE_COLLECTION_ARTIFACT_TYPE` and `feature_count` from `grafy_api.artifacts.geo`, and inlining `_load_stored_content` from `L612-627` at the end of `load_content`)
  - `open_content` (`service.py:473-535`)
  - `load_download` (`service.py:537-600`, with `_text_value` from `L602-610` inlined into the `if format == "txt":` branch)
  - `_open_stored_content` (`service.py:629-646`, kept because both `open_content` and `load_content` call it)

Constructor signature:
```python
class ArtifactContentService:
    """Loads persisted artifact bytes, streams, and download exports."""

    def __init__(
        self,
        uow: UnitOfWorkPort,
        storage: FileStoragePort,
        artifact_types: Mapping[tuple[str, int], ArtifactTypeSpec] | None = None,
    ) -> None:
        self._uow = uow
        self._storage = storage
        self._artifact_types = artifact_types or {}
```
`ArtifactContentService` owns no network client and has no `close()` method.

Public `__all__` imported by callers:
- `ARTIFACT_RESPONSE_CHUNK_SIZE`
- `ArtifactContentRead`
- `ArtifactContentService`
- `BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES`

### 4. `apps/api/src/grafy_api/artifacts/tables.py` (~225 lines)

Moves from `service.py`:
- `TABLE_INTERACTION_ROW_LIMIT = 250_000` (`service.py:93`)
- `_TABLE_CELL_ARTIFACT_NAMESPACE = UUID("3f0c1d7e-9a64-4b52-8c1e-7d2a6e5f4b10")` (`service.py:335`)
- `TableQueryPage` frozen slots dataclass (`service.py:141-145`)
- `_table_row_matches_group` (`service.py:169-179`, calling `interaction_values_equal` imported from `grafy_api.artifacts.models`)
- `ArtifactTableService`:
  - `__init__(self, uow: UnitOfWorkPort, storage: FileStoragePort) -> None` (`self._uow = uow`, `self._storage = storage`)
  - `get(self, workspace_id: UUID, artifact_id: UUID) -> ArtifactObject | None` (`async with self._uow as uow: return await uow.artifacts.get(workspace_id, artifact_id)`)
  - `load_table_page` (`service.py:1455-1480`)
  - `load_table_cell` (`service.py:1482-1499`)
  - `text_artifacts_for_column` (`service.py:1501-1553`, using `async with self._uow as uow:` and inlining `_cell_text_artifact` from `L338-365` directly inside the `for index, row in enumerate(page.rows):` loop with `payload: JsonObject = {"value": value}` so pyright sees `JsonObject`)
  - `load_table_query_page` (`service.py:1555-1637`)

Public `__all__` imported by callers:
- `ArtifactTableService`
- `TABLE_INTERACTION_ROW_LIMIT`
- `TableQueryPage`

### 5. `apps/api/src/grafy_api/artifacts/geo.py` (~420 lines)

Moves from `service.py`:
- `GEO_FEATURE_COLLECTION_ARTIFACT_TYPE = "geo.feature_collection"` (`service.py:84`)
- `GEO_RASTER_SCAN_ARTIFACT_TYPE = "geo.raster_scan"` (`service.py:85`)
- `GEO_MAP_LAYER_ARTIFACT_TYPE = "geo.map_layer"` (`service.py:86`)
- `GEO_MAP_DOCUMENT_ARTIFACT_TYPE = "geo.map_document"` (`service.py:87`)
- `GEO_INTERACTION_FEATURE_LIMIT = 250_000` (`service.py:94`)
- `_coordinate_bounds` (`service.py:197-214`)
- `_geometry_bounds` (`service.py:217-233`)
- `_bounds_union` (`service.py:303-313`)
- `feature_count(artifact: ArtifactObject) -> int` (promoted from `ArtifactService._feature_count` at `service.py:648-659`)
- `source_name(artifact: ArtifactObject) -> str` (promoted from `ArtifactService._source_name` at `service.py:997-1003`)
- `resolve_exact_artifacts(availability: ArtifactAvailability, refs: list[GeoArtifactRefPayload], *, expected_type: str, context: str, workspace_id: UUID) -> list[ArtifactObject]` (promoted from `ArtifactService._get_exact_artifacts` at `service.py:1172-1204`)
- `ArtifactGeoService`:
  - `__init__(self, uow: UnitOfWorkPort, storage: FileStoragePort, *, availability: ArtifactAvailability) -> None` (`self._uow = uow`, `self._storage = storage`, `self._availability = availability`)
  - `get(self, workspace_id: UUID, artifact_id: UUID) -> ArtifactObject | None` (`async with self._uow as uow: return await uow.artifacts.get(workspace_id, artifact_id)`)
  - `query_geo_features` (`service.py:709-792`, using `async with self._uow as uow:`, `feature_count(...)`, `interaction_values_equal(...)` from `models.py`, and inlining `_geo_feature_matches` from `L182-194` inside the `for feature in page.collections[0].items:` loop)
  - `load_geo_render` (`service.py:895-995`, using `source_name(artifact)`, `resolve_exact_artifacts(self._availability, ...)`, `GeoVectorStyle.model_validate(StoredGeoVectorStyle())` in place of `GeoVectorStyle.default()`, and inlining `_raster_render_layer` from `L1063-1093` for the `GEO_RASTER_SCAN_ARTIFACT_TYPE` branch)
  - `_feature_render_layer` (`service.py:1026-1061`, using `feature_count(artifact)` and inlining `_feature_fields` from `L1005-1024`)
  - `_resolve_render_layer` (`service.py:1095-1170`, using `resolve_exact_artifacts(self._availability, ...)` and inlining `_raster_render_layer` from `L1063-1093` for the `layer.source.kind == "raster_scan"` branch)

Public `__all__` imported by callers:
- `ArtifactGeoService`
- `GEO_FEATURE_COLLECTION_ARTIFACT_TYPE`
- `GEO_INTERACTION_FEATURE_LIMIT`
- `GEO_MAP_DOCUMENT_ARTIFACT_TYPE`
- `GEO_MAP_LAYER_ARTIFACT_TYPE`
- `GEO_RASTER_SCAN_ARTIFACT_TYPE`
- `feature_count`
- `resolve_exact_artifacts`
- `source_name`

### 6. `apps/api/src/grafy_api/artifacts/geo_tiles.py` (~370 lines)

Moves from `service.py`:
- `PMTILES_RESPONSE_MAX_BYTES = 16 * 1_024 * 1_024` (`service.py:91`)
- `IMMUTABLE_CACHE_CONTROL = "private, max-age=31536000, immutable"` (`service.py:92`)
- `GeoArchiveRead` frozen slots dataclass (`service.py:97-105`)
- `_single_byte_range` (`service.py:273-300`)
- `ArtifactGeoTileService`:
  - `__init__(self, uow: UnitOfWorkPort, storage: FileStoragePort, *, availability: ArtifactAvailability, wms: WmsTileClient) -> None` (`self._uow = uow`, `self._storage = storage`, `self._availability = availability`, `self._wms = wms`)
  - `get(self, workspace_id: UUID, artifact_id: UUID) -> ArtifactObject | None` (`async with self._uow as uow: return await uow.artifacts.get(workspace_id, artifact_id)`)
  - `load_exact_feature` (`service.py:661-707`, using `feature_count(artifact)` from `geo.py`)
  - `load_vector_archive` (`service.py:794-893`, using `feature_count(artifact)` from `geo.py`, `GeoRangeNotSatisfiableError` and `ArtifactResponseTooLargeError` from `errors.py`, and inlining `_etag` from `L267-270`)
  - `load_raster_tilejson` (`service.py:1206-1269`, using `source_name` and `resolve_exact_artifacts` from `geo.py`)
  - `load_raster_tile` (`service.py:1271-1359`, inlining `_valid_tile_coordinates` from `L316-320` as `if z < 0 or z > 24 or x < 0 or y < 0 or x >= (1 << z) or y >= (1 << z): return None`, delegating WMS layers to `await self._wms.fetch_tile(layer.source, z=z, x=x, y=y)`, resolving `projection` for both `GEO_RASTER_SCAN_ARTIFACT_TYPE` and `raster_scan` map layers, and running the stored-tile read from `L1333-1359` once inline at the end of `load_raster_tile`)

Public `__all__` imported by callers:
- `ArtifactGeoTileService`
- `GeoArchiveRead`
- `IMMUTABLE_CACHE_CONTROL`
- `PMTILES_RESPONSE_MAX_BYTES`

### 7. `apps/api/src/grafy_api/artifacts/models.py` (edited, ~655 lines)

Changes in `models.py`:
- Add `re` import and move `_CANONICAL_INTEGER`, `_interaction_int` (`service.py:148-158`), and `interaction_values_equal` (renamed from `_interaction_values_equal` at `service.py:161-166`) directly above `ArtifactExactMatchRow`, adding `"interaction_values_equal"` to `__all__`.
- Remove the 5 orphan constructor-wrapper classmethods listed in the helper table:
  - `ArtifactExportFormatResponse.from_export_format` (`models.py:52-58`)
  - `ArtifactSummaryResponse.from_artifact` (`models.py:75-92`)
  - `TableColumnResponse.from_column` (`models.py:104-110`), updating `models.py:200` in `TablePageResponse.from_page` to `TableColumnResponse(id=column.id, title=column.title, value_type=column.value_type)`
  - `TableSchemaResponse.from_page` (`models.py:117-124`)
  - `GeoVectorStyle.default` (`models.py:467-469`, remove in Commit 4 alongside deleting `service.py`; also drop the then-unused `StoredGeoVectorStyle` import on `models.py:27`)

### 8. `apps/api/src/grafy_api/artifacts/__init__.py` (~25 lines)

Export the split service and client classes for package-level clarity:
```python
"""Artifact reads and the pydantic models those reads return."""

from grafy_api.artifacts.content import ArtifactContentRead, ArtifactContentService
from grafy_api.artifacts.errors import (
    ArtifactResponseTooLargeError,
    GeoRangeNotSatisfiableError,
)
from grafy_api.artifacts.geo import ArtifactGeoService
from grafy_api.artifacts.geo_tiles import (
    ArtifactGeoTileService,
    GeoArchiveRead,
    IMMUTABLE_CACHE_CONTROL,
)
from grafy_api.artifacts.tables import ArtifactTableService, TableQueryPage
from grafy_api.artifacts.wms import GeoTileRead, WmsTileClient

__all__ = [
    "ArtifactContentRead",
    "ArtifactContentService",
    "ArtifactGeoService",
    "ArtifactGeoTileService",
    "ArtifactResponseTooLargeError",
    "ArtifactTableService",
    "GeoArchiveRead",
    "GeoRangeNotSatisfiableError",
    "GeoTileRead",
    "IMMUTABLE_CACHE_CONTROL",
    "TableQueryPage",
    "WmsTileClient",
]
```

## `uow` naming cleanup

Standardize `self._unit_of_work` and `unit_of_work as unit_of_work` to `self._uow` and `as uow` in every file below. Preserve external keyword parameter names where callers outside the allowlist pass `unit_of_work=...` by keyword.

| File | Exact change |
| --- | --- |
| `apps/api/src/grafy_api/artifact_availability.py` | In `ArtifactAvailability.__init__`, rename parameter `unit_of_work: UnitOfWorkPort` to `uow: UnitOfWorkPort` and `self._unit_of_work` to `self._uow` (`L46-47`). On `L62-65`, change `async with self._unit_of_work as unit_of_work:` to `async with self._uow as uow:` and `unit_of_work.artifacts.get_many` to `uow.artifacts.get_many`. |
| `apps/api/src/grafy_api/library/folders.py` | In `LibraryFoldersService.__init__`, rename `unit_of_work: WorkbenchUnitOfWorkPort` to `uow: WorkbenchUnitOfWorkPort` and `self._unit_of_work` to `self._uow` (`L24-25`). In all 6 `async with` blocks (`L28, 42, 61, 82, 108, 148`), change `async with self._unit_of_work as unit_of_work:` to `async with self._uow as uow:` and update body references to `uow`. In `_require_folder`, `_require_folder_when_set`, and `_require_name_free` (`L168-215`), rename parameter `unit_of_work: WorkbenchUnitOfWorkPort` to `uow: WorkbenchUnitOfWorkPort`. |
| `apps/api/src/grafy_api/library/service.py` | In `LibraryService.__init__`, rename `unit_of_work: LibraryUnitOfWorkPort` to `uow: LibraryUnitOfWorkPort` and `self._unit_of_work` to `self._uow` (`L30-35`). In all 4 `async with` blocks (`L55, 87, 157, 171`), change `async with self._unit_of_work as uow:` to `async with self._uow as uow:`. |
| `apps/api/src/grafy_api/runs/edge_values.py` | Keep keyword parameter `unit_of_work: UnitOfWorkPort` in `EdgeValueResolver.__init__` (`runs/node_runner.py:161` passes `unit_of_work=unit_of_work` by keyword, and `node_runner.py` is outside the allowlist). Change `self._unit_of_work = unit_of_work` to `self._uow = unit_of_work` (`L44`), and on `L137-140` change `async with self._unit_of_work as unit_of_work:` to `async with self._uow as uow:`. |
| `apps/api/src/grafy_api/services/composition.py` | Keep keyword parameter `unit_of_work: LibraryUnitOfWorkPort` on `build_workbench_components` (`L75`). Replace `resolved_unit_of_work = unit_of_work` (`L89`) with `uow = unit_of_work` (or use `uow` directly on `L109, 124, 168-192`). |
| `apps/api/src/grafy_api/artifacts/{content,tables,geo,geo_tiles}.py` | Use parameter `uow: UnitOfWorkPort`, attribute `self._uow = uow`, and `async with self._uow as uow:` throughout. |
| `tests/unit/runs/test_node_runner.py` | On `L155-156` and `L165-166`, change `async with self.unit_of_work as unit_of_work:` to `async with self.unit_of_work as uow:` and update the inner `uow.artifacts.*` call. Keep the test harness dataclass field name `self.unit_of_work`. |

## Orphan helpers and constructor wrappers

Every private helper (`_*`) and constructor-wrapping classmethod or function in the scoped files was audited by grepping call sites across the entire repository. Act on every row below and nothing else.

Note: `apps/api/src/grafy_api/app_state.py`, `apps/api/src/grafy_api/artifact_availability.py`, and `apps/api/src/grafy_api/v1/routes/artifacts/dependencies.py` contain zero private helpers and zero constructor wrappers.

| # | Base location | Symbol | Verified callers | Decision | Reason |
| --- | --- | --- | --- | --- | --- |
| 1 | `artifacts/service.py:151` | `_interaction_int` | 2 (`service.py:164, 165`) | **keep** (in `models.py`) | Avoids duplicating `bool` exclusion and `_CANONICAL_INTEGER` regex parsing for `left` and `right`. |
| 2 | `artifacts/service.py:161` | `_interaction_values_equal` | 2 (`service.py:175, 192`) | **keep** (move to `models.py` as `interaction_values_equal`) | Shared scalar/canonical-int equality rule used by both `tables.py` and `geo.py`. |
| 3 | `artifacts/service.py:169` | `_table_row_matches_group` | 2 (`service.py:1611, 1616`) | **keep** (in `tables.py`) | Avoids duplicating a 2-level `any(all(...))` predicate across filter and highlight checks. |
| 4 | `artifacts/service.py:182` | `_geo_feature_matches` | 1 (`service.py:775`) | **inline** (into `query_geo_features` in `geo.py`) | Single caller; extracting `feature.get("properties")` once per feature in the loop is clearer. |
| 5 | `artifacts/service.py:197` | `_coordinate_bounds` | 2 (`service.py:212` self, `233`) | **keep** (in `geo.py`) | Recursive traversal over nested GeoJSON coordinate arrays; cannot be inlined. |
| 6 | `artifacts/service.py:217` | `_geometry_bounds` | 2 (`service.py:230` self, `778`) | **keep** (in `geo.py`) | Recursive `GeometryCollection` and geometry bounds dispatch; cannot be inlined. |
| 7 | `artifacts/service.py:267` | `_etag` | 1 (`service.py:828`) | **inline** (into `load_vector_archive` in `geo_tiles.py`) | Single caller; 3-line ETag quoting expression. |
| 8 | `artifacts/service.py:273` | `_single_byte_range` | 1 (`service.py:834`) | **keep** (in `geo_tiles.py`) | Named RFC byte-range parser whose `ValueError` boundary maps cleanly to HTTP 416. |
| 9 | `artifacts/service.py:303` | `_bounds_union` | 4 (`service.py:214, 226, 789, 979`) | **keep** (in `geo.py`) | 4 callers across geometry traversal, feature queries, and map document bounds. |
| 10 | `artifacts/service.py:316` | `_valid_tile_coordinates` | 1 (`service.py:1280`) | **inline** (into `load_raster_tile` in `geo_tiles.py`) | Single caller; 2-line coordinate guard reads directly at top of `load_raster_tile`. |
| 11 | `artifacts/service.py:323` | `_web_mercator_tile_bounds` | 1 (`service.py:1373`) | **inline** (into `WmsTileClient.fetch_tile` in `wms.py`) | Single caller; 6 straight arithmetic lines right above `bbox` parameter assembly. |
| 12 | `artifacts/service.py:338` | `_cell_text_artifact` | 1 (`service.py:1527`) | **inline** (into `text_artifacts_for_column` in `tables.py`) | Single-caller `ArtifactObject` constructor helper; also fixes `payload: JsonObject` typing. |
| 13 | `artifacts/service.py:421` | `ArtifactService._artifact_is_json` | 1 (`service.py:406`) | **inline** (into `export_formats` in `content.py`) | Single caller; 1-line boolean expression. |
| 14 | `artifacts/service.py:602` | `ArtifactService._text_value` | 1 (`service.py:567`) | **inline** (into `load_download` in `content.py`) | Single caller; simple dict lookup used only by `format == "txt"`. |
| 15 | `artifacts/service.py:612` | `ArtifactService._load_stored_content` | 1 (`service.py:471`) | **inline** (into `load_content` in `content.py`) | Single caller; fallback branch at the end of `load_content`. |
| 16 | `artifacts/service.py:629` | `ArtifactService._open_stored_content` | 2 (`service.py:516, 623`) | **keep** (in `content.py`) | Shared storage-stream open and `ArtifactContentUnavailableError` translation. |
| 17 | `artifacts/service.py:648` | `ArtifactService._feature_count` | 6 (`service.py:455, 676, 749, 762, 807, 1039`) | **keep** (promote to `feature_count` in `geo.py`) | 6 callers across `content.py`, `geo.py`, and `geo_tiles.py`. |
| 18 | `artifacts/service.py:997` | `ArtifactService._source_name` | 3 (`service.py:910, 929, 1221`) | **keep** (promote to `source_name` in `geo.py`) | 3 callers across `geo.py` and `geo_tiles.py`. |
| 19 | `artifacts/service.py:1005` | `ArtifactService._feature_fields` | 1 (`service.py:1058`) | **inline** (into `_feature_render_layer` in `geo.py`) | Single caller; metadata validation sits directly above `GeoVectorRenderSourceResponse`. |
| 20 | `artifacts/service.py:1026` | `ArtifactService._feature_render_layer` | 2 (`service.py:907, 1120`) | **keep** (in `geo.py`) | Shared ~50-line empty-collection, `vector_projection`, and `property_fields` validation. |
| 21 | `artifacts/service.py:1063` | `ArtifactService._raster_render_layer` | 2 (`service.py:926, 1141`) | **inline** (into `load_geo_render` and `_resolve_render_layer` in `geo.py`) | Thin 8-argument pass-through wrapper around `GeoRenderLayerResponse` construction. |
| 22 | `artifacts/service.py:1095` | `ArtifactService._resolve_render_layer` | 2 (`service.py:944, 966`) | **keep** (in `geo.py`) | Shared ~80-line polymorphic layer resolution for `map_layer` and `map_document`. |
| 23 | `artifacts/service.py:1172` | `ArtifactService._get_exact_artifacts` | 5 (`service.py:958, 1111, 1132, 1240, 1301`) | **keep** (promote to `resolve_exact_artifacts` in `geo.py`) | 5 callers across `geo.py` and `geo_tiles.py`. |
| 24 | `artifacts/service.py:1325` | `ArtifactService._load_stored_raster_tile` | 2 (`service.py:1287, 1311`) | **inline** (once at bottom of `load_raster_tile` in `geo_tiles.py`) | Both `load_raster_tile` branches resolve `projection` first, then run stored-tile read once inline. |
| 25 | `artifacts/service.py:1361` | `ArtifactService._load_wms_tile` | 1 (`service.py:1317`) | **move** (to `WmsTileClient.fetch_tile` in `wms.py`) | Public method on the extracted WMS HTTP client boundary. |
| 26 | `artifacts/models.py:53` | `ArtifactExportFormatResponse.from_export_format` | 1 (`library/models.py:60`) | **inline** (into `LibraryService._present` and delete) | Single-caller 3-field pass-through constructor wrapper. |
| 27 | `artifacts/models.py:76` | `ArtifactSummaryResponse.from_artifact` | 1 (`library/models.py:57`) | **inline** (into `LibraryService._present` and delete) | Single-caller constructor wrapper. |
| 28 | `artifacts/models.py:105` | `TableColumnResponse.from_column` | 2 (`artifacts/models.py:121, 200`) | **inline** (at call sites and delete) | Thin 3-field pass-through constructor wrapper. |
| 29 | `artifacts/models.py:118` | `TableSchemaResponse.from_page` | 1 (`v1/routes/artifacts/views.py:392`) | **inline** (into `get_table_artifact_schema` in `views.py` and delete) | Single-caller 2-field constructor wrapper. |
| 30 | `artifacts/models.py:133` | `TableCellPreviewResponse.from_value` | 1 (`artifacts/models.py:204`) | **keep** | Carries JS-safe integer stringification, JSON serialization, and cell truncation inside a comprehension. |
| 31 | `artifacts/models.py:172` | `TablePageResponse.from_page` | 2 (`v1/routes/artifacts/views.py:350, 436`) | **keep** | Carries 50 lines of column slicing, `column_ids` validation, and cell-preview projection. |
| 32 | `artifacts/models.py:310` | `TableCellResponse.from_value` | 1 (`v1/routes/artifacts/views.py:486`) | **keep** | Carries type-discriminated `"native" \| "integer" \| "json"` wire-encoding logic. |
| 33 | `artifacts/models.py:468` | `GeoVectorStyle.default` | 1 (`artifacts/service.py:915`) | **inline** (as `GeoVectorStyle.model_validate(StoredGeoVectorStyle())` in `geo.py` and delete) | Single-caller 1-line constructor wrapper. |
| 34 | `artifacts/models.py:523` | `GeoRasterStyle.default` | 4 (`service.py:934`, `test_composition.py:83`, `test_artifact_wms.py:70, 131`) | **keep** | 4 callers across production and test suites. |
| 35 | `v1/routes/artifacts/views.py:42` | `_artifact_streaming_response` | 2 (`views.py:561, 616`) | **inline** (into `get_artifact_content` and `get_artifact_download`) | Thin `StreamingResponse` constructor wrapper with side-effect `headers` mutation. |
| 36 | `services/composition.py:64` | `ComputationLimits.from_config` | 1 (`services/application.py:162`) | **keep** | Sole caller is in `services/application.py`, which is outside the allowed file set. |
| 37 | `library/service.py:40` | `LibraryService._artifact_name` | 1 (`library/service.py:217`) | **inline** (into `LibraryService._present`) | Single caller. |
| 38 | `library/service.py:154` | `LibraryService._record` | 2 (`library/service.py:141, 146`) | **keep** | Shared transactional provenance write and idempotency check for both Library save routes. |
| 39 | `library/service.py:200` | `LibraryService._delete_stored_object` | 1 (`library/service.py:198`) | **inline** (into `LibraryService.delete_artifact`) | Single caller; 8-line tail of `delete_artifact`. |
| 40 | `library/service.py:212` | `LibraryService._present` | 2 (`library/service.py:68, 165`) | **keep** | Shared ~30-line response builder once rows 26, 27, 37, and 41 are inlined into it. |
| 41 | `library/models.py:48` | `LibraryItemResponse.from_item` | 1 (`library/service.py:215`) | **inline** (into `LibraryService._present` and delete; remove unused imports in `library/models.py`) | Single-caller wrapper in a 4-layer constructor chain. |
| 42 | `library/models.py:104` | `LibraryFolderResponse.from_folder` | 4 (`library/folders.py:30, 52, 78, 132`) | **keep** | 4 callers. |
| 43 | `library/folders.py:168` | `LibraryFoldersService._require_folder` | 4 (`library/folders.py:62, 83, 109, 188`) | **keep** | 4 callers. |
| 44 | `library/folders.py:179` | `LibraryFoldersService._require_folder_when_set` | 3 (`library/folders.py:43, 110, 149`) | **keep** | 3 callers. |
| 45 | `library/folders.py:190` | `LibraryFoldersService._require_name_free` | 3 (`library/folders.py:44, 68, 122`) | **keep** | 3 callers. |
| 46 | `runs/edge_values.py:93` | `EdgeValueResolver._project_value` | 1 (`edge_values.py:88`) | **inline** (into `EdgeValueResolver.resolve`) | Single caller; removes redundant `projection is None` check and extra hop in `resolve`. |
| 47 | `runs/edge_values.py:126` | `EdgeValueResolver._project_ref` | 2 (`edge_values.py:103, 106`) | **keep** | 72-line per-item projection workflow shared by scalar and sequence branches. |
| 48 | `runs/edge_values.py:199` | `EdgeValueResolver._convert_value` | 1 (`edge_values.py:90`) | **inline** (into `EdgeValueResolver.resolve`) | Single caller; removes redundant `not conversions` check and extra hop in `resolve`. |
| 49 | `runs/edge_values.py:232` | `EdgeValueResolver._convert_ref` | 2 (`edge_values.py:210, 213`) | **keep** | 92-line per-item conversion workflow shared by scalar and sequence branches. |
| 50 | `runs/edge_values.py:326` | `_in_port_order` | 1 (`edge_values.py:68`) | **inline** (into `EdgeValueResolver.assemble_inputs`) | Single caller; places plug-order validation directly beside `plan.instance_plugs` handling. |
| 51 | `runs/edge_values.py:344` | `_conversion_path_metadata` | 2 (`edge_values.py:220, 285`) | **keep** | Avoids duplicating 20-line provenance dictionary shape across sequence and item metadata. |
| 52 | `runs/edge_values.py:369` | `_validated_conversion_value` | 3 (`edge_values.py:252, 264, 268`) | **keep** | 3 callers. |

## Nested functions and lambdas

All scoped production files contain zero nested `def` or `async def` blocks at depth >= 2. Every nested `lambda` in scoped production files and every nested `async def` closure in scoped test files is listed below.

| # | Base location | Symbol | Depth | Decision | Reason |
| --- | --- | --- | --- | --- | --- |
| 1 | `artifacts/service.py:593` | `lambda: iter_table_csv(artifact, self._storage)` in `load_download` | 2 | **keep** (in `content.py`) | 1-expression deferred async-iterator thunk matching `ArtifactContentRead.body`. |
| 2 | `services/composition.py:109` | `lambda: resolved_unit_of_work` in `build_workbench_components` | 2 | **keep** (as `lambda: uow`) | 1-expression zero-arg callable adapter required by `UploadService.from_config`. |
| 3 | `library/service.py:64` | `lambda item: (...)` in `list_items` | 2 | **keep** | Standard `list.sort` key expression. |
| 4 | `tests/unit/api/services/test_artifact_streaming.py:82` | `async def read_and_close()` in `test_stored_artifact_content_streams_fixed_chunks_and_closes_source` | 2 | **flatten** | Make outer test `async def`; `ArtifactContentService` has no `close()` and `asyncio_mode = auto`. |
| 5 | `tests/unit/api/services/test_artifact_streaming.py:132` | `async def open_and_close()` in `test_buffered_reconstruction_is_rejected_before_loading_storage` | 2 | **flatten** | Make outer test `async def` and drop `asyncio.run(...)` + `service.close()`. |
| 6 | `tests/unit/api/services/test_artifact_streaming.py:162` | `async def open_and_close()` in `test_small_inline_content_without_size_metadata_remains_available` | 2 | **flatten** | Make outer test `async def` and drop `asyncio.run(...)` + `service.close()`. |

*(Note: local helper functions inside `test_single_owner.py:85, 89`, `test_table_text_artifacts.py:37`, `test_composition.py:101`, `test_artifact_wms.py:150`, and `test_gis_artifacts.py:801, 819` are monkeypatch/transport doubles at depth 2 with no inner `def`s; keep their structure while updating the target service types).*

## Callers to update

### Production callers

1. **`apps/api/src/grafy_api/services/composition.py`**
   - Replace `artifacts: ArtifactService` on `WorkbenchComponents` (`L47`) with five fields:
     ```python
     artifact_content: ArtifactContentService
     artifact_tables: ArtifactTableService
     artifact_geo: ArtifactGeoService
     artifact_geo_tiles: ArtifactGeoTileService
     wms: WmsTileClient
     ```
   - In `build_workbench_components`, construct:
     ```python
     availability = ArtifactAvailability(uow)
     wms = WmsTileClient(egress_policy=resolved_egress_policy)
     artifact_content = ArtifactContentService(
         uow,
         resolved_storage,
         artifact_types=artifact_types,
     )
     artifact_tables = ArtifactTableService(uow, resolved_storage)
     artifact_geo = ArtifactGeoService(
         uow,
         resolved_storage,
         availability=availability,
     )
     artifact_geo_tiles = ArtifactGeoTileService(
         uow,
         resolved_storage,
         availability=availability,
         wms=wms,
     )
     library = LibraryService(
         uow,
         artifact_content,
         artifact_types=artifact_types,
         storage=resolved_storage,
     )
     ```
2. **`apps/api/src/grafy_api/app_state.py`**
   - On `L66` in `AppResources.cleanup`, replace `await self.workbench.artifacts.close()` with `await self.workbench.wms.close()`. Shutdown order (`agent_turns` -> `project_room_hub` -> `runs` -> `wms`) stays identical.
3. **`apps/api/src/grafy_api/library/service.py`**
   - Update import `from grafy_api.artifacts.service import ArtifactService` (`L20`) to `from grafy_api.artifacts.content import ArtifactContentService` and type `artifacts: ArtifactContentService` in `LibraryService.__init__` (`L31`).
4. **`apps/api/src/grafy_api/v1/routes/artifacts/dependencies.py`**
   - Replace `artifact_service` and `ArtifactDependency` with four narrow dependencies:
     - `artifact_content_service(request: Request) -> ArtifactContentService` returning `get_resources(request.app).workbench.artifact_content` and `ArtifactContentDependency = Annotated[ArtifactContentService, Depends(artifact_content_service)]`
     - `artifact_table_service(request: Request) -> ArtifactTableService` returning `get_resources(request.app).workbench.artifact_tables` and `ArtifactTableDependency = Annotated[ArtifactTableService, Depends(artifact_table_service)]`
     - `artifact_geo_service(request: Request) -> ArtifactGeoService` returning `get_resources(request.app).workbench.artifact_geo` and `ArtifactGeoDependency = Annotated[ArtifactGeoService, Depends(artifact_geo_service)]`
     - `artifact_geo_tile_service(request: Request) -> ArtifactGeoTileService` returning `get_resources(request.app).workbench.artifact_geo_tiles` and `ArtifactGeoTileDependency = Annotated[ArtifactGeoTileService, Depends(artifact_geo_tile_service)]`
   - Export all eight names in `__all__`.
5. **`apps/api/src/grafy_api/v1/routes/artifacts/views.py`**
   - Replace `ArtifactDependency` on each route with the single matching dependency:
     - `ArtifactGeoDependency`: `get_geo_render_descriptor` (`L69`), `query_geo_features` (`L97`)
     - `ArtifactGeoTileDependency`: `get_geo_vector_pmtiles` (`L131`), `get_geo_exact_feature` (`L189`), `get_geo_raster_tilejson` (`L221`), `get_geo_raster_tile` (`L266`)
     - `ArtifactTableDependency`: `get_table_artifact_page` (`L317`), `get_table_artifact_schema` (`L378`), `query_table_artifact_page` (`L407`), `get_table_artifact_cell` (`L466`), `create_table_text_artifacts` (`L505`)
     - `ArtifactContentDependency`: `get_artifact_content` (`L545`), `get_artifact_download` (`L580`)
   - Update imports from `grafy_api.artifacts.service` to `grafy_api.artifacts.errors` (`ArtifactResponseTooLargeError`, `GeoRangeNotSatisfiableError`) and `grafy_api.artifacts.geo_tiles` (`IMMUTABLE_CACHE_CONTROL`).
   - Inline `_artifact_streaming_response` (`L42-54`) into `get_artifact_content` and `get_artifact_download`, and inline `TableSchemaResponse.from_page(page)` (`L392`) as `TableSchemaResponse(columns=[TableColumnResponse(id=col.id, title=col.title, value_type=col.value_type) for col in page.columns], total_rows=page.total_rows)` (importing `TableColumnResponse` from `grafy_api.artifacts.models`).

### Test callers

1. **`tests/support/workbench.py`**
   - Replace `artifact_service: lambda: components.artifacts` with overrides for `artifact_content_service`, `artifact_table_service`, `artifact_geo_service`, and `artifact_geo_tile_service` pointing to `components.artifact_content`, `components.artifact_tables`, `components.artifact_geo`, and `components.artifact_geo_tiles`.
2. **`tests/unit/api/test_single_owner.py`**
   - Import `WmsTileClient` from `grafy_api.artifacts.wms` instead of `ArtifactService`.
   - On `L83-94`, monkeypatch `WmsTileClient.close` instead of `ArtifactService.close` (keeping `shutdown_order.append("artifacts")` or updating both the append and `assert shutdown_order == [...]` on `L102` consistently so the shutdown-order assertion passes).
3. **`tests/unit/api/services/test_table_text_artifacts.py`**
   - Import `ArtifactTableService` from `grafy_api.artifacts.tables` instead of `ArtifactService` (drop unused `ArtifactAvailability` import).
   - Construct `ArtifactTableService(unit_of_work, storage)` in `harness(...)`.
4. **`tests/unit/api/services/test_composition.py`**
   - On `L115-126`, read via `components.artifact_geo_tiles.get(...)` and `components.artifact_geo_tiles.load_raster_tile(...)`, add `assert read is not None` before `return read.content`, and call `await components.wms.close()` in `finally:`.
5. **`tests/unit/api/services/test_artifact_wms.py`**
   - Import `ArtifactGeoService` from `grafy_api.artifacts.geo`, `ArtifactGeoTileService` from `grafy_api.artifacts.geo_tiles`, and `WmsTileClient` from `grafy_api.artifacts.wms`.
   - In `test_stored_wms_layer_rejects_unsafe_endpoint_before_dns` (`L35-107`): construct `wms = WmsTileClient()`, `geo = ArtifactGeoService(unit_of_work, storage, availability=availability)`, and `tiles = ArtifactGeoTileService(unit_of_work, storage, availability=availability, wms=wms)`, dispatch `"render"` to `geo.load_geo_render` and `"tilejson"` / `"tile"` to `tiles`, and `await wms.close()` in `finally:`.
   - In `test_wms_tile_is_dialed_from_a_trusted_destination_only` (`L137-193`): construct `wms = WmsTileClient(egress_policy=egress_policy)` and `tiles = ArtifactGeoTileService(unit_of_work, storage, availability=ArtifactAvailability(unit_of_work), wms=wms)`, add `assert read is not None` before `return read.content`, and `await wms.close()` in `finally:`.
   - In `test_wms_tile_fetch_has_no_resolver_of_its_own` (`L196-207`): assert `"getaddrinfo" not in path.read_text(encoding="utf-8")` across every `path` in `Path("apps/api/src/grafy_api/artifacts").glob("*.py")`.
6. **`tests/unit/api/services/test_artifact_streaming.py`**
   - Import `ARTIFACT_RESPONSE_CHUNK_SIZE`, `BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES`, `ArtifactContentRead`, `ArtifactContentService` from `grafy_api.artifacts.content`, and `ArtifactResponseTooLargeError` from `grafy_api.artifacts.errors` (drop unused `asyncio` and `ArtifactAvailability` imports).
   - Construct `ArtifactContentService(unit_of_work, cast(FileStoragePort, storage))`.
   - Flatten all 3 tests (`L64`, `L109`, `L144`) into `async def test_...` functions directly awaiting `service.open_content(artifact)` without inner `read_and_close` / `open_and_close` functions, `asyncio.run(...)`, or `service.close()`.
7. **`tests/integration/artifacts/test_spatial_storage.py`**
   - Import `ArtifactContentService` from `grafy_api.artifacts.content` and `ArtifactContentUnavailableError` from `grafy_api.services.errors` (drop unused `ArtifactAvailability` import).
   - Construct `service = ArtifactContentService(uow, storage)` on `L132` and remove the `finally: if service is not None: await service.close()` block (`L153-155`), since `ArtifactContentService` has no `close()`.
8. **`tests/integration/artifacts/test_gis_artifacts.py`**
   - Import `geo_tiles` (`from grafy_api.artifacts import geo_tiles`), `ArtifactGeoService` (`from grafy_api.artifacts.geo import ArtifactGeoService`), `ArtifactGeoTileService` (`from grafy_api.artifacts.geo_tiles import ArtifactGeoTileService`), `WmsTileClient` (`from grafy_api.artifacts.wms import WmsTileClient`), and `artifact_geo_service, artifact_geo_tile_service` from `grafy_api.v1.routes.artifacts.dependencies`.
   - In `geo_artifact_client` (`L141-166`): construct `availability = ArtifactAvailability(unit_of_work)`, `wms = WmsTileClient()`, `geo = ArtifactGeoService(unit_of_work, storage, availability=availability)`, and `tiles = ArtifactGeoTileService(unit_of_work, storage, availability=availability, wms=wms)`. Override both `artifact_geo_service` and `artifact_geo_tile_service` on `application.dependency_overrides`, and run `asyncio.run(wms.close())` after `yield`.
   - On `L596`, change `monkeypatch.setattr(artifact_services, "PMTILES_RESPONSE_MAX_BYTES", 8)` to `monkeypatch.setattr(geo_tiles, "PMTILES_RESPONSE_MAX_BYTES", 8)`.
   - In `test_wms_tile_pins_validated_address_against_dns_rebinding` (`L793-891`): construct `mock_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))`, `wms = WmsTileClient(client=mock_client)`, and `tiles = ArtifactGeoTileService(unit_of_work, storage, availability=ArtifactAvailability(unit_of_work), wms=wms)`. Call `await tiles.load_raster_tile(...)` and `await wms.close()` in `finally:`.

## Ordered commit plan

Make four small, green commits in the exact order below. Do not squash them and do not push.

### Commit 1: `refactor(api): standardize unit-of-work fields and inline edge-value wrappers`

Files:
- `apps/api/src/grafy_api/artifact_availability.py`
- `apps/api/src/grafy_api/library/folders.py`
- `apps/api/src/grafy_api/library/service.py` (`uow` / `self._uow` rename only)
- `apps/api/src/grafy_api/runs/edge_values.py` (`self._uow` / `as uow` rename + inline `_project_value`, `_convert_value`, `_in_port_order` per rows 46, 48, 50)
- `tests/unit/runs/test_node_runner.py` (`as uow` rename)

Verify after Commit 1:
```bash
uv run ruff check apps/api/src/grafy_api/artifact_availability.py apps/api/src/grafy_api/library/ apps/api/src/grafy_api/runs/edge_values.py tests/unit/runs/test_node_runner.py
uv run ruff format --check apps/api/src/grafy_api/artifact_availability.py apps/api/src/grafy_api/library/ apps/api/src/grafy_api/runs/edge_values.py tests/unit/runs/test_node_runner.py
uv run pyright apps/api/src/grafy_api/artifact_availability.py apps/api/src/grafy_api/library/folders.py apps/api/src/grafy_api/library/service.py apps/api/src/grafy_api/runs/edge_values.py
uv run pytest tests/unit/architecture/test_import_boundaries.py tests/unit/runs/test_node_runner.py tests/unit/api/services/test_library_instance_routes.py tests/integration/library/
```

### Commit 2: `refactor(library): inline single-caller model and deletion wrappers`

Files:
- `apps/api/src/grafy_api/artifacts/models.py` (remove `from_export_format`, `from_artifact`, `from_column`, `TableSchemaResponse.from_page` per rows 26..29; keep `GeoVectorStyle.default` until Commit 4)
- `apps/api/src/grafy_api/library/models.py` (remove `LibraryItemResponse.from_item` per row 41 and clean unused imports)
- `apps/api/src/grafy_api/library/service.py` (inline `_artifact_name`, `from_item`, `from_artifact`, `from_export_format` into `_present`, and inline `_delete_stored_object` into `delete_artifact` per rows 37, 39)
- `apps/api/src/grafy_api/v1/routes/artifacts/views.py` (inline `TableSchemaResponse.from_page` in `get_table_artifact_schema` per row 29)

Verify after Commit 2:
```bash
uv run ruff check apps/api/src/grafy_api/artifacts/models.py apps/api/src/grafy_api/library/ apps/api/src/grafy_api/v1/routes/artifacts/views.py
uv run ruff format --check apps/api/src/grafy_api/artifacts/models.py apps/api/src/grafy_api/library/ apps/api/src/grafy_api/v1/routes/artifacts/views.py
uv run pyright apps/api/src/grafy_api/library/service.py apps/api/src/grafy_api/library/models.py
uv run pytest tests/unit/architecture/test_import_boundaries.py tests/unit/api/services/test_library_instance_routes.py tests/integration/library/ tests/integration/ops/test_openapi.py
```

### Commit 3: `refactor(artifacts): add focused content, tables, geo, geo_tiles, wms, and errors modules`

Files:
- `apps/api/src/grafy_api/artifacts/errors.py` (new)
- `apps/api/src/grafy_api/artifacts/wms.py` (new, with row 11 inlined)
- `apps/api/src/grafy_api/artifacts/content.py` (new, with rows 13, 14, 15 inlined)
- `apps/api/src/grafy_api/artifacts/tables.py` (new, with row 12 inlined)
- `apps/api/src/grafy_api/artifacts/geo.py` (new, with rows 4, 19, 21, 33 inlined)
- `apps/api/src/grafy_api/artifacts/geo_tiles.py` (new, with rows 7, 10, 24 inlined)
- `apps/api/src/grafy_api/artifacts/models.py` (add `_CANONICAL_INTEGER`, `_interaction_int`, `interaction_values_equal` per rows 1..2)
- `apps/api/src/grafy_api/artifacts/__init__.py` (export new public types)

Keep `service.py` untouched in Commit 3 so existing callers still pass before rewiring.

Verify after Commit 3:
```bash
uv run ruff check apps/api/src/grafy_api/artifacts/
uv run ruff format --check apps/api/src/grafy_api/artifacts/
uv run pyright apps/api/src/grafy_api/artifacts/errors.py apps/api/src/grafy_api/artifacts/wms.py apps/api/src/grafy_api/artifacts/content.py apps/api/src/grafy_api/artifacts/tables.py apps/api/src/grafy_api/artifacts/geo.py apps/api/src/grafy_api/artifacts/geo_tiles.py apps/api/src/grafy_api/artifacts/__init__.py
uv run pytest tests/unit/architecture/test_import_boundaries.py tests/integration/artifacts/test_gis_artifacts.py tests/integration/artifacts/test_spatial_storage.py
```

### Commit 4: `refactor(artifacts): wire narrow services, update callers, and remove service.py`

Files:
- Delete `apps/api/src/grafy_api/artifacts/service.py`
- `apps/api/src/grafy_api/artifacts/models.py` (remove `GeoVectorStyle.default` per row 33 and drop unused `StoredGeoVectorStyle` import)
- `apps/api/src/grafy_api/services/composition.py`
- `apps/api/src/grafy_api/app_state.py`
- `apps/api/src/grafy_api/library/service.py` (`ArtifactContentService` type annotation)
- `apps/api/src/grafy_api/v1/routes/artifacts/dependencies.py`
- `apps/api/src/grafy_api/v1/routes/artifacts/views.py` (narrow dependencies + inline `_artifact_streaming_response` per row 35)
- `tests/support/workbench.py`
- `tests/unit/api/test_single_owner.py`
- `tests/unit/api/services/test_table_text_artifacts.py`
- `tests/unit/api/services/test_composition.py`
- `tests/unit/api/services/test_artifact_wms.py`
- `tests/unit/api/services/test_artifact_streaming.py` (including flattening nested closures per Nested rows 4..6)
- `tests/integration/artifacts/test_gis_artifacts.py`
- `tests/integration/artifacts/test_spatial_storage.py`

Verify after Commit 4: run every command in [Finish line](#finish-line).

## Finish line

Every command below must succeed before finishing:

1. **Removed monolith and module line caps** (`errors.py`, `wms.py`, `content.py`, `tables.py`, `geo.py`, `geo_tiles.py`, `__init__.py` each <= 450 lines; `service.py` absent):
   ```bash
   test ! -e apps/api/src/grafy_api/artifacts/service.py
   wc -l apps/api/src/grafy_api/artifacts/__init__.py \
     apps/api/src/grafy_api/artifacts/errors.py \
     apps/api/src/grafy_api/artifacts/wms.py \
     apps/api/src/grafy_api/artifacts/content.py \
     apps/api/src/grafy_api/artifacts/tables.py \
     apps/api/src/grafy_api/artifacts/geo.py \
     apps/api/src/grafy_api/artifacts/geo_tiles.py
   ```
2. **Repo-wide lint:**
   ```bash
   uv run ruff check
   ```
3. **Format check on every touched and created Python file** (note: repo-wide `uv run ruff format --check` exits 1 on `origin/main` due to 12 untouched files listed in the baseline; verify both that all in-scope files pass with 0 reformats and that `git diff --name-only origin/main` contains only allowed files):
   ```bash
   uv run ruff format --check \
     apps/api/src/grafy_api/artifacts/ \
     apps/api/src/grafy_api/v1/routes/artifacts/ \
     apps/api/src/grafy_api/services/composition.py \
     apps/api/src/grafy_api/app_state.py \
     apps/api/src/grafy_api/library/service.py \
     apps/api/src/grafy_api/library/models.py \
     apps/api/src/grafy_api/library/folders.py \
     apps/api/src/grafy_api/artifact_availability.py \
     apps/api/src/grafy_api/runs/edge_values.py \
     tests/support/workbench.py \
     tests/unit/api/test_single_owner.py \
     tests/unit/api/services/test_table_text_artifacts.py \
     tests/unit/api/services/test_composition.py \
     tests/unit/api/services/test_artifact_wms.py \
     tests/unit/api/services/test_artifact_streaming.py \
     tests/unit/runs/test_node_runner.py \
     tests/integration/artifacts/test_gis_artifacts.py \
     tests/integration/artifacts/test_spatial_storage.py
   ```
4. **Typecheck** (`0 errors` on `libs/client` and on all non-route production files and updated service unit tests):
   ```bash
   uv run pyright libs/client \
     apps/api/src/grafy_api/artifacts/__init__.py \
     apps/api/src/grafy_api/artifacts/errors.py \
     apps/api/src/grafy_api/artifacts/wms.py \
     apps/api/src/grafy_api/artifacts/content.py \
     apps/api/src/grafy_api/artifacts/tables.py \
     apps/api/src/grafy_api/artifacts/geo.py \
     apps/api/src/grafy_api/artifacts/geo_tiles.py \
     apps/api/src/grafy_api/v1/routes/artifacts/dependencies.py \
     apps/api/src/grafy_api/services/composition.py \
     apps/api/src/grafy_api/app_state.py \
     apps/api/src/grafy_api/library/service.py \
     apps/api/src/grafy_api/library/models.py \
     apps/api/src/grafy_api/library/folders.py \
     apps/api/src/grafy_api/artifact_availability.py \
     apps/api/src/grafy_api/runs/edge_values.py \
     tests/support/workbench.py \
     tests/unit/api/test_single_owner.py \
     tests/unit/api/services/test_table_text_artifacts.py \
     tests/unit/api/services/test_composition.py \
     tests/unit/api/services/test_artifact_wms.py \
     tests/unit/api/services/test_artifact_streaming.py \
     tests/integration/artifacts/test_gis_artifacts.py \
     tests/integration/artifacts/test_spatial_storage.py
   ```
5. **Architecture, unit, integration, and OpenAPI contract tests** (`159 passed, 0 failed`):
   ```bash
   uv run pytest \
     tests/unit/architecture/test_import_boundaries.py \
     tests/unit/api/test_single_owner.py \
     tests/unit/api/services/ \
     tests/unit/runs/test_node_runner.py \
     tests/integration/artifacts/test_gis_artifacts.py \
     tests/integration/artifacts/test_spatial_storage.py \
     tests/integration/library/ \
     tests/integration/ops/test_openapi.py
   ```
6. **Byte-for-byte OpenAPI schema equality** (proves zero public schema drift without requiring a web `node_modules` install):
   ```bash
   uv run python -m grafy_api.openapi apps/web/openapi/grafy.json && git diff --exit-code apps/web/openapi/grafy.json
   ```

## Open questions for the maintainer

1. **`geo.py` + `geo_tiles.py` split vs single `geo.py`.** Non-WMS spatial logic in `service.py` is ~810 lines (`L182-320` and `L648-1359`), so a single `geo.py` cannot meet the <= 450-line cap. This spec splits it into `geo.py` (~420 lines: map render descriptors and linked feature queries) and `geo_tiles.py` (~370 lines: PMTiles archives, exact feature reads, and raster TileJSON/XYZ/WMS tiles). Confirm this 6-module split (`errors`, `wms`, `content`, `tables`, `geo`, `geo_tiles`), or waive the 450-line cap for a single `geo.py`.
2. **Pre-existing `artifacts/models.py` length.** `apps/api/src/grafy_api/artifacts/models.py` is 689 lines on `origin/main` (~645 lines after deleting the 5 orphan wrappers). This spec leaves `models.py` as one file rather than splitting Pydantic models across multiple files. Confirm that the 450-line cap applies only to the service modules extracted from `service.py`.

## Blockers

None recorded during specification authoring. If the implementation agent encounters a blocker, record the exact command, file:line, and mismatch here and stop.

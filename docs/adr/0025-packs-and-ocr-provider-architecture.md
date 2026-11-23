# ADR 0025: Packs, three-kind plugin boundaries, and greenfield OCR service contracts

- **Status:** Proposed
- **Amends:** [ADR 0011](0011-shared-configuration-is-a-leaf-package.md) (adds `CatalogConfig` as the eleventh config section), [ADR 0017](0017-plugins-are-application-code-in-process.md) (separates code packaging under `plugins/` from UI discovery through Packs), [ADR 0023 (service outputs)](0023-service-outputs-are-execution-local.md) (scopes service features per contract, enforces single-contract providers in v1, and moves feature-output validation into `NodeRuntime.run_node`)
- **Related:** `CONTEXT.md` (Pack, Plugin, Builtin family, Service contract, Provider node, OCR node), `docs/design/plugin-development.md`, `docs/design/provider-operation-cache.md`, ADR 0010, ADR 0016

## Context

Under ADR 0017 every node family in `libs/workbench` and `plugins/` is application code loaded into one `PluginRegistry`. That removed the plugin release lifecycle, but left one coupling intact: the Workbench Step Picker projected backend Python package boundaries directly into user-facing tabs.

That coupling produced four concrete defects for non-technical users (specifically historians adopting grafY for archival OCR):

1. **Packaging leaked into UX.** `external.table` and builtin `table` produced two separate `Table` tabs; vendor packages (`Mistral`, `Reducto`) sat beside capability categories (`OCR`, `Maps`, `Lists`) and CS primitives (`Schema`, `Value`); and client-synthesized `Graph input` / `Graph output` occupied the top slots of the picker.
2. **Duplicate and blurred OCR abstractions.** Legacy vendor-bound operators (`mistral.ocr.process`, `reducto.ocr.process`) duplicated the vendor-neutral `ocr.read` + provider model. Meanwhile the builtin `ocr` family mixed page-level OCR (`OcrReader`) with an experimental, project-specific TIFF map-toponym pipeline (`TextDetector`, `TextRecognizer`, Visual Jev on `api.typesafe.ai`, Label Studio, and IH PAN's LiteLLM endpoints on `ai-test.ihpan.edu.pl`).
3. **Provider caching and feature checks were coupled to specific vendors.** `tiff_scan.py` and `tiff_recognition.py` hardcoded CRAFT and PaddleOCR deployment/revision constants into `ProviderCache`, so any second detector or recognizer would receive stale CRAFT/Paddle readings. Optional output gating duplicated a manual `_FEATURE_PORTS` table on the backend and a port-name equality heuristic on the frontend (`provider-outputs.ts`), while `OcrReader.title` duplicated the node registration title.
4. **No way to tailor the toolbox per Workspace or deployment.** Every Workspace saw all 40+ operators at once, with no way for a deployment operator to disable unpolished nodes via configuration or for a Workspace owner to expose only the tools needed for a specific research project.

Backward compatibility with the initial OCR service contracts (`ocr.reader@1`, `ocr.text_detector@1`, `ocr.text_recognizer@1`) and legacy `mistral.ocr.process` / `reducto.ocr.process` operators is not required.

## Decision

### 1. Three plugin kinds under `plugins/`

`plugins/` remains strictly a backend packaging and dependency boundary. It explicitly accommodates three kinds of in-process packages:

1. **Vendor / gateway provider plugins** (`plugins/mistral`, `plugins/reducto`, `plugins/litellm_ocr`, `plugins/llm`, future `plugins/tesseract`): grouped by vendor or model gateway so SDKs, egress rules, credential verifiers, and HTTP clients live in one place.
2. **Heavy native-dependency domain plugins** (`plugins/gis`, `plugins/image`, `plugins/table`): broadly reusable domains whose native or third-party dependencies stay out of `grafy-workbench`.
3. **Experimental / project-specific vertical plugins** (such as `plugins/map_toponyms`): domain-specific research pipelines whose nodes work primarily together or call specialized endpoints (Visual Jev, Label Studio, Cyrillic place matching). Putting them in their own plugin package and opt-in Pack keeps `grafy-workbench` clean without forcing premature generic abstractions.

`grafy-workbench` holds only broadly reusable, dependency-light, vendor-neutral builtins and consumer nodes. Shared pooled HTTP client helpers (`provider_http.py`) live in `grafy_core` so both `grafy_api` shutdown hooks and multiple plugins can use them without cross-plugin imports.

### 2. Greenfield OCR service contracts and runner-enforced feature gating

The three OCR service contracts live under `grafy_core.contracts.ocr` and are named by their input/output unit:

- `DocumentOcr` (`ocr.document@1`, `"Document OCR"`): whole page or PDF (`RasterImage | PdfFile`) -> `DocumentOcrResult(markdown, blocks?, regions?)`, advertising `DocumentOcrFeature` (`BLOCKS`, `REGIONS`). Document-by-URL input and legacy `mistral.ocr.process` / `reducto.ocr.process` are removed.
- `TextBoxDetector` (`ocr.box_detector@1`, `"Text box detector"`): TIFF window PNG -> pixel polygons, with instance method `cache_identity() -> ServiceCacheIdentity(deployment, revision, options)`.
- `CropTextReader` (`ocr.crop_reader@1`, `"Crop text reader"`): pre-cut label crops -> readings, with instance method `cache_identity() -> ServiceCacheIdentity(deployment, revision, options)`.

When `cache_identity().revision` is `None`, consumers bypass `ProviderCache` (honoring `docs/design/provider-operation-cache.md`).

Service provider registration is validated in `Plugin.node` and `validate_service_node`:
- Every registered node (operator or provider) must define its own non-empty `__doc__` (`node_class.__dict__.get("__doc__")`), preventing `ABC.__doc__` leaks.
- A provider node has zero input ports, exactly one service output port, and implements **one** service contract in v1 (multi-contract providers are deferred until cache-identity and cost semantics warrant them; invalid shapes raise `NodeContractError`).
- Optional consumer output ports declare `RequiresServiceFeature(input_port, feature)`. Provider `service_features` are scoped by contract key in `PortResponse`. `NodeRuntime.run_node` enforces feature/output agreement generically (covering both scalar and `MAP` runs) using provider metadata passed from `node_runner.py`, eliminating `OcrReader.title`, `_FEATURE_PORTS`, and the frontend port-name matching heuristic.

### 3. Curated Packs, deployment `catalog.toml`, and Workspace subscriptions (discovery only)

A **Pack** is a code-defined, task-oriented discovery bundle that groups explicit operator ids plus contract-matched providers (`include_providers_for=(ServiceContractKey(...),)`), so new provider plugins automatically join the right Pack.

Visibility in `/v1/workspaces/{workspace_id}/nodes` is governed by two layers:

1. **Deployment configuration (`GRAFY_CATALOG_CONFIG`):** an optional TOML file (`CatalogConfig.catalog_config` in `grafy_shared` per ADR 0011, validated against `PluginRegistry` at `apps/api` composition) specifying default Workspace Packs and deployment-wide Pack or operator-id disablement. No database-backed admin catalog UI is added in v1.
2. **Workspace Pack subscriptions (`workspace_packs`):** persisted per Workspace, initialized from deployment defaults for every new Personal, shared, or OIDC domain-granted Workspace, and managed by Workspace `owner` through `WorkspaceCapability.MANAGE_PACKS` (excluded from PATs). `always_on` Packs (such as `essentials`) cannot be unsubscribed. Client-synthesized boundary and call nodes (`Graph input`, `Graph output`) follow the `subgraphs` Pack on the client.

**Discovery-only invariant:** Packs and `catalog.toml` only toggle `catalog_visible` (`listed`). Every registered node remains present in `/v1/workspaces/{workspace_id}/nodes` so existing saved Projects always hydrate, render, and execute cleanly without turning into `runnable: false` placeholders. Pack state never enters node fingerprints, execution signatures, or stored results.

### 4. Separate provider cards with auto-prompted connection and seeded starter Projects

Provider nodes remain separate canvas objects because each provider owns independent configuration and Vault credential selection. When a user locally places a consumer with an unsatisfied required service input, the workbench auto-wires (and writes the Shared credential binding when applicable) only when a single enabled provider is unambiguously auto-bindable (0 secrets, deployment default, or 1 matching Shared Workspace credential), opens the contextual engine picker beside the port otherwise, or shows an empty-state port affordance when no provider is enabled. Starter OCR recipes are created as ordinary copied Projects (ADR 0016) referencing a bundled public-domain sample scan stored at the Workspace Library root (no server-created folders, honoring ADR 0010) rather than a separate template aggregate.

## Consequences

- **Breaking change for OCR contracts and legacy vendor operators:** saved graphs referencing `mistral.ocr.process`, `reducto.ocr.process`, `ocr.read`, or old service contract keys will not compile; this is accepted because no production migration is required.
- **Credentials survive intact:** `plugins/litellm_ocr` keeps `provider_kind="litellm"` and `plugins/map_toponyms` keeps `"jev"`, `"label_studio"`, and `"s3"`, so existing encrypted Vault credentials stay valid.
- **Discovery is not entitlement:** disabling a Pack or operator in `catalog.toml` or unsubscribing a Workspace hides it from Add-node and contextual discovery, but does not block execution of existing graphs or direct programmatic authoring. Data-residency enforcement, if required later, will be a separate runtime policy.
- **Clean extension path:** adding a new engine such as Tesseract requires only a new `plugins/tesseract` package implementing `DocumentOcr` (using `bounded_subprocess` with zero secrets); it joins the `Document OCR` Pack and the canvas engine picker automatically.

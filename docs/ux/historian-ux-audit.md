# Historian UX audit

Audience: someone digitizing and transcribing archival documents, not someone who builds graphs. This spec is the work. Do not treat it as a suggestion list.

Labels below were read from the components that render them. The app was not exercised in a browser for this pass.

## Summary

The workbench speaks in implementation names. A finished transcription is `Sequence<Markdown>`, a port is `document_url` or `· many`, and the same idea is also `list[Markdown]` in the type popover. OCR cards put the model id, page range, table format, and time limit on the face of the card, with choices `r-1` and `md`. Failures quote plug UUIDs, node ids, and `file_format_mismatch`, and they do not say what to do. Run state says Fresh, Stale, fingerprint, and artifact. A collection’s extra socket is hidden until the card is selected. An empty canvas does not say how to add a step.

Out of scope: canvas edge routing, edge geometry, handle measurement, and connection hit testing. Do not edit `apps/web/src/features/workbench/canvas/edges/`. Do not change artifact type ids, operator ids, stored config keys, or the meaning of stored defaults.

Execute every task whose class is `mechanical`. Leave every `needs-design` task unimplemented. Do not approximate a needs-design task with a partial behavior change.

## Task index

| Id | Severity | Type | Class |
| --- | --- | --- | --- |
| HX-01 | high | copy-only | mechanical |
| HX-02 | high | copy-only | mechanical |
| HX-03 | high | copy-only | mechanical |
| HX-04 | high | copy-only | mechanical |
| HX-05 | medium | copy-only | mechanical |
| HX-06 | high | hide-or-default | mechanical |
| HX-07 | high | copy-only | mechanical |
| HX-08 | high | copy-only | mechanical |
| HX-09 | high | copy-only | mechanical |
| HX-10 | high | copy-only | mechanical |
| HX-11 | high | copy-only | mechanical |
| HX-12 | high | copy-only | mechanical |
| HX-13 | medium | copy-only | mechanical |
| HX-14 | medium | copy-only | mechanical |
| HX-15 | medium | copy-only | mechanical |
| HX-16 | medium | copy-only | mechanical |
| HX-17 | medium | copy-only | mechanical |
| HX-18 | medium | copy-only | mechanical |
| HX-19 | medium | copy-only | mechanical |
| HX-20 | medium | visual | mechanical |
| HX-21 | low | copy-only | mechanical |
| HX-22 | medium | copy-only | mechanical |
| HX-23 | medium | behavior | needs-design |
| HX-24 | high | behavior | needs-design |
| HX-25 | medium | behavior | needs-design |
| HX-26 | medium | behavior | needs-design |
| HX-27 | medium | behavior | needs-design |

Mechanical: 22. Needs design: 5.

## HX-01 — One plain name for a list of documents

- Severity: high
- Type: copy-only
- Class: mechanical
- Files:
  - `formatArtifactTypeSequence` and `formatArtifactTypeSequenceTooltip` in `apps/web/src/features/workbench/canvas/artifact-type-label.ts`
  - `PortTab` and `usePortBallTypeProps` in `apps/web/src/features/workbench/canvas/nodes/workflow/ports.tsx`
  - `PortTypePopover` in `apps/web/src/features/workbench/canvas/nodes/type-inspector.tsx`
  - The artifact-type label bullet in `apps/web/AGENTS.md`

Current:

- `formatArtifactTypeSequence` returns `` `Sequence<${label}>` ``. With the catalog title this is `Sequence<Markdown>` and `Sequence<Text value>`.
- `PortTab` shows `· many` when `shape === "many"`.
- The same function builds the accessible name with `` shape === "many" ? `list[${artifactContract}]` : artifactContract ``.
- `usePortBallTypeProps` builds the ball tip with `` shape === "many" ? `Sequence<${inner}>` : ... `` and uses the word `any` when the type is unset (`inner` is `"any"`).
- `PortTypePopover` shows `` shape === "many" ? `list[${contract}]` : contract ``.

New:

- `formatArtifactTypeSequence` returns `` `List of ${label}` ``. Tooltip helper uses that same function, so the tooltip is `List of text.markdown@1` when the catalog has no title, and `List of Transcribed text` after HX-02.
- Delete the local `Sequence<…>` and `list[…]` builders. Call `formatArtifactTypeContract` (or `formatArtifactTypeSequence` on an already formatted label) for the ball tip, the port accessible name, and the type popover header.
- Replace the visible mark `· many` with `· list`.
- When the type is unset and the shape is `many`, the ball tip type is `List of any type`, not `Sequence<any>`. `ANY_TYPE_LABEL` stays `Any type` for a single unset port.
- In `apps/web/AGENTS.md`, replace the examples `Sequence<Text value>` and `Sequence<Text value>` in the artifact-type label bullet with `List of Text value`. Leave the rule that `@1` stays off the visible label and that a missing catalog falls back to the full identity.

Acceptance:

- No rendered workbench string contains `Sequence<` or `list[`.
- A sequence port’s visible mark, accessible name, ball tip, and type popover all contain `List of`.
- `formatArtifactTypeLabel` still returns the full identity (`scalar.text@1`) when the catalog is `null`.

Tests:

- Update `apps/web/src/features/workbench/canvas/artifact-type-label.test.ts` (`Sequence<Text value>` → `List of Text value`, and the `Table · v2` and `scalar.text@1` sequence cases).
- Update `apps/web/src/features/workbench/canvas/artifact-card.test.ts` (`Sequence<file.jpg@1>`).
- Update `apps/web/src/features/workbench/canvas/nodes/ArtifactCardBody.test.tsx` (`Sequence<file.jpeg@1>`, `Sequence<file.csv@1>`).
- Update `apps/web/src/features/workbench/ui/ArtifactFolderDropDialog.test.tsx` (`Place Sequence<file.csv@1>`).
- Update `apps/web/src/features/workbench/agents/ToolEvents.test.tsx` (`Sequence<scalar.text@2>`).
- Add an assertion in `apps/web/src/features/workbench/canvas/nodes/type-inspector.test.tsx` that a `many` port header renders `List of`, not `list[`.

## HX-02 — Catalog titles a historian can read

- Severity: high
- Type: copy-only
- Class: mechanical
- Files: the `title=` on each `ArtifactTypeSpec` below. Do not change `key` ids.

| File | Current title | New title |
| --- | --- | --- |
| `libs/core/src/grafy_core/artifact_contracts.py` `MARKDOWN` | `Markdown` | `Transcribed text` |
| same file, text value spec | `Text value` | `Text` |
| same file, integer spec | `Integer value` | `Number` |
| same file, `RASTER_IMAGE` | `Raster image` | `Image` |
| same file, image regions spec | `Image regions` | `Boxes on the page` |
| same file, HTML page spec | `HTML page` | `Web page` |
| `libs/core/src/grafy_core/file_contracts.py` blob spec | `Binary blob` | `Unrecognized file` |
| `libs/core/src/grafy_core/prompt_contracts.py` `PROMPT_MESSAGE` | `Prompt message` | `Instruction` |
| `libs/core/src/grafy_core/schema_contracts.py` | `JSON Schema` | `Answer format` |

Leave file titles that already name a format (`PNG image`, `CSV file`, `Excel workbook`, `Text file`, `JSON document`, `GeoJSON document`, `TIFF image`). Leave `Table`.

Acceptance: the registry title for `text.markdown@1` is `Transcribed text`. The id stays `text.markdown`. Cards that already use `formatArtifactTypeLabel` pick the new title up with no extra mapping.

Tests: grep the old titles. Update assertions that read these registry titles. Do not edit fixture catalogs inside web unit tests unless that fixture is asserting the registry title itself. `apps/web/src/features/workbench/canvas/artifact-type-label.test.ts` builds its own catalog and can keep `Text value` as fixture input.

## HX-03 — Name ports in plain language

- Severity: high
- Type: copy-only
- Class: mechanical
- Why: `InputPortSpec.title` is `field.title` (`libs/core/src/grafy_core/node_derivation.py`). Pydantic leaves `title` empty unless `Field(title=…)` is set. The card then uses `port.title ?? port.name` (`PortTab` and `InstancePlugPort`), so the canvas shows `document_url`, `markdown`, `blocks`, `items`.

Set `title` and replace `description` on these fields. Do not rename the Python attribute.

`plugins/reducto/src/grafy_plugin_reducto/ocr.py` and the matching fields in `plugins/mistral/src/grafy_plugin_mistral/ocr.py`:

| Field | New title | New description |
| --- | --- | --- |
| `document_url` | Document link | Web address of the PDF or scan. Leave empty when a page image is connected. |
| `image` | Page image | One scanned page. Leave empty when a document link is connected. |
| `markdown` | Transcription | The reading, with pages kept in order. |
| `blocks` | Text blocks | One row per piece the reader found: page, kind of region, text, and box. |
| `regions` (Mistral only) | Boxes on the page | Where each region sits on the page, in pixels. |

`libs/workbench/src/grafy_workbench/sequence/nodes.py`:

| Field | New title | New description |
| --- | --- | --- |
| `CollectInput.items` | Documents | Pages or files, in the order you add them. |
| `CollectOutput.items` | List | Everything above, as one list. |
| `CountInput.items` | List | The list to count. |
| `CountOutput.count` | How many | How many items are in the list. |
| `SliceInput.items` / `SliceOutput.items` | List | The list to take a range from. / The items you kept. |
| `ItemAtInput.items` | List | The list to pick from. |
| `ItemAtOutput.item` | Item | The one item at that position. |

`libs/workbench/src/grafy_workbench/file/nodes.py`:

| Field | New title | New description |
| --- | --- | --- |
| `InterpretFileInput.file` | File | The file whose type is still unrecognized. |
| `InterpretFileOutput.file` | File | The same bytes, labeled as the type you chose. |

`plugins/table/src/grafy_plugin_table/nodes.py`: input title `Spreadsheet`, description `A CSV or Excel file.`; output title `Table`, description `The rows and columns from that file.`

`plugins/image/src/grafy_plugin_image/nodes.py`: `Decode images` input title `Image files`, output title `Images`. Draw/crop `image` title `Image`, `regions` title `Boxes`.

`plugins/llm/src/grafy_plugin_llm/prompt.py`: text input title `Words`, image input title `Pictures`, output title `Instruction`.

`plugins/llm/src/grafy_plugin_llm/openai_compatible.py`: `messages` title `Instructions`. The schema port already has `title="JSON Schema"`; change that title to `Answer format`. Output title `Answer`.

Acceptance: a Reducto OCR card does not show `document_url`, `markdown`, or `blocks`. A Collect card shows `Documents`.

Tests: extend `apps/web/src/features/workbench/canvas/nodes/WorkflowNode.test.tsx` if it asserts a raw port name as visible text. Add a focused assertion only where a test already renders one of these cards. Do not add a new snapshot of the whole card.

## HX-04 — Node names and the sentence under them

- Severity: high
- Type: copy-only
- Class: mechanical
- Why: `node_class.description = getdoc(node_class)` in `libs/core/src/grafy_core/plugins.py`. The card menu and Add node dialog show that docstring (`NodeHeader` falls back to `No description is available for this node.`).

Change `title=` and the docstring only. Leave `operator_id` and `version` as they are.

| File | Current title | Current docstring (first line) | New title | New docstring |
| --- | --- | --- | --- | --- |
| `plugins/reducto/src/grafy_plugin_reducto/ocr.py` `ReductoOcrNode` | `Reducto OCR` | `Parses a document URL or raster image with the Reducto Parse API.` | `Read with Reducto` | `Reads a PDF or a scanned page into text. You need a Reducto key.` |
| `plugins/mistral/src/grafy_plugin_mistral/ocr.py` `MistralOcrNode` | `Mistral OCR` | `Recognizes a document URL or raster image with Mistral OCR.` | `Read with Mistral` | `Reads a PDF or a scanned page into text. You need a Mistral key.` |
| `libs/workbench/src/grafy_workbench/file/nodes.py` `InterpretFileNode` | `Interpret file` | `Confirm blob bytes against one claimed file.* format and claim them.` | `Set file type` | `Tells Grafy what kind of file this is, when the upload was not recognized. Pick the type that matches the file.` |
| `libs/workbench/src/grafy_workbench/sequence/nodes.py` `collect` | `Collect` | `Collects homogeneous artifact refs without rewriting their payloads.` | `Group into a list` | `Keeps pages or files together, in the order you add them. Every item has to be the same kind of thing.` |
| same file `count` | `Count` | `Counts the refs in an artifact sequence.` | `Count items` | `Counts how many items are in a list.` |
| same file `slice_sequence` | `Slice` | `Selects a contiguous range from an ordered artifact sequence.` | `Take a range` | `Keeps a stretch of items from a list. The first item is number 0.` |
| same file `item_at` | `Pick item` | `Picks one artifact ref from an ordered artifact sequence.` | `Pick one` | `Picks one item from a list. The first item is number 0.` |
| `plugins/llm/src/grafy_plugin_llm/openai_compatible.py` | `OpenAI-compatible Chat Completion` | `Calls a saved graph's OpenAI-compatible Chat Completions endpoint.` | `Ask a model` | `Sends the instructions to a chat model and keeps the answer.` |
| `plugins/llm/src/grafy_plugin_llm/prompt.py` | `Create prompt message` | (use the current docstring’s first line if you need to find it) | `Write an instruction` | `The words, and any pictures, you want the model to read.` |
| `plugins/image/src/grafy_plugin_image/nodes.py` | `Decode images` | | `Read images` | `Turns image files into pictures on the canvas.` |
| same file | `Draw regions` | | `Draw boxes` | `Draws the boxes from a reading onto the page.` |
| same file | `Crop regions` | | `Crop boxes` | `Cuts out each box as its own picture.` |
| `plugins/table/src/grafy_plugin_table/nodes.py` | `Import table` | `Import one persisted CSV or XLSX file artifact as a table.` | `Read a spreadsheet` | `Reads a CSV or Excel file into a table.` |

Acceptance: Add node and the card menu show the new title and the new sentence. They do not show `blob`, `artifact ref`, `raster`, or `operator`.

Tests: any catalog test that asserts these titles. Search `Reducto OCR`, `Interpret file`, `OpenAI-compatible Chat Completion`, `Create prompt message`.

## HX-05 — Source names in Add node

- Severity: medium
- Type: copy-only
- Class: mechanical
- Files: `title=` on the plugin object.

| File | Current | New |
| --- | --- | --- |
| `plugins/llm/src/grafy_plugin_llm/declaration.py` | `LLM` | `Language model` |
| `plugins/gis/src/grafy_plugin_gis/declaration.py` | `GIS` | `Maps` |
| `libs/workbench/src/grafy_workbench/sequence/declaration.py` | `Sequence` | `Lists` |

Leave `Reducto`, `Mistral`, `Image`, `Table`, `Text`, `File`, `Schema`, `Value`. Those are either product names or already plain.

`buildSourceFilters` in `apps/web/src/features/workbench/model/node-catalog.ts` shows `plugin.title` in the canvas menu (`CanvasContextMenu` submenu labels). No web change if the plugin title changes.

Tests: update a test that asserts the plugin title `LLM`, `GIS`, or `Sequence` as a menu label.

## HX-06 — Hide specialist settings behind Advanced

- Severity: high
- Type: hide-or-default
- Class: mechanical
- Files:
  - `apps/web/src/features/workbench/canvas/config-schema.ts` (`SchemaField`, `schemaFields`)
  - `apps/web/src/features/workbench/canvas/nodes/workflow/config-fields.tsx` (`ConfigField`)
  - `apps/web/src/features/workbench/canvas/nodes/workflow/generic-body.tsx` (`GenericBody`)
  - `apps/web/src/features/workbench/ui/CatalogNodePreview.tsx`
  - The node config classes named below

Do not change defaults. `tests/unit/plugins/test_reducto_ocr.py` asserts `(config.model, config.table_format, config.timeout_s) == ("r-1", "md", 300)`. That assertion stays.

Web:

- On `SchemaField`, add `advanced: boolean` and `enumLabels: Readonly<Record<string, string>> | undefined`.
- In `schemaFields`, set `advanced` when the resolved property has `x-grafy-ui === "advanced"`.
- Set `enumLabels` from `x-grafy-enum-labels` when that value is an object whose values are strings. Ignore anything else.
- `ConfigField` renders `field.enumLabels?.[String(option)] ?? String(option)` as the option text. The `<option value>` stays the stored value.
- `GenericBody` splits bricks. Secret bricks and fields with `advanced === false` stay on the existing board. Advanced fields go in a closed `<details class="nodrag nowheel">` whose summary text is `Advanced`. If a config issue names an advanced field, render that `<details open>`.
- `CatalogNodePreview` currently does `fields.slice(0, 4)`. Filter out `advanced` fields before that slice. `NodeInspector` still lists every field inside its existing Details disclosure.

Python: add `title`, `description`, and `json_schema_extra` on the existing fields. Do not add fields.

`ReductoOcrConfig` in `plugins/reducto/src/grafy_plugin_reducto/ocr.py`. All four fields are advanced.

| Field | Title | Description | Extra |
| --- | --- | --- | --- |
| `model` | Reading model | Standard reads most documents. Faster does not read spreadsheets. | `{"x-grafy-ui": "advanced", "x-grafy-enum-labels": {"r-1": "Standard", "r-1-mini": "Faster (not for spreadsheets)"}}` |
| `page_start` | First page | Leave empty to start at the first page. Page 1 is the first page. | `{"x-grafy-ui": "advanced"}` |
| `page_end` | Last page | Leave empty to read through the last page. | `{"x-grafy-ui": "advanced"}` |
| `table_format` | Tables | Use HTML when a table has merged cells. | `{"x-grafy-ui": "advanced", "x-grafy-enum-labels": {"md": "Markdown", "html": "HTML"}}` |
| `timeout_s` | Time limit (seconds) | How long to wait for the reader. The default is 300. | `{"x-grafy-ui": "advanced"}` |

`MistralOcrConfig` in `plugins/mistral/src/grafy_plugin_mistral/ocr.py`. All of these are advanced.

| Field | Title | Enum labels |
| --- | --- | --- |
| `table_format` | Tables | `markdown` → `Markdown`, `html` → `HTML` |
| `extract_header` | Pull headers out of the text | |
| `extract_footer` | Pull footers out of the text | |
| `confidence_scores_granularity` | Confidence | `page` → `One score per page`, `block` → `One score per region` |
| `timeout_ms` | Time limit (milliseconds) | |
| `max_retries` | Extra attempts | |

Descriptions: replace the current ones with one short sentence that matches the title. Do not mention `provider`, `SDK`, or `HTTP status`.

`OpenAICompatibleConfig` in `plugins/llm/src/grafy_plugin_llm/openai_compatible.py`:

- `model` stays on the card. Title `Model`. Description `The model name your account expects.`
- Advanced: `base_url` title `Service address`, `temperature` title `Variation`, `max_completion_tokens` title `Length limit`, `timeout_ms` title `Time limit (milliseconds)`, `max_retries` title `Extra attempts`, `schema_name` title `Answer name`, `strict` title `Require the answer format`.

`TableImportConfig` in `plugins/table/src/grafy_plugin_table/nodes.py`:

- On the card: `header_row` title `Header row`, `sheet_name` title `Sheet name`.
- Advanced: `delimiter` title `Column separator`, `skip_empty_rows` title `Skip blank rows`.

`DrawRegionsConfig` and the crop config in `plugins/image/src/grafy_plugin_image/nodes.py`:

- `page` stays on the card. Title `Page`. Description `0 is the first page.` Do not change the default `0` in this task (HX-25 owns a 1-based control).
- Advanced: `kinds` title `Which boxes`, `line_width` title `Line width`, `fill_opacity` title `Fill strength`, `label_text` title `Labels on boxes` with enum labels `kind` → `Kind of region`, `label` → `The region’s own label`, `none` → `No label`.

`SliceConfig` and `ItemAtConfig` in `libs/workbench/src/grafy_workbench/sequence/nodes.py`:

- Titles `Start at` and `How many` for slice; `Position` for pick. Descriptions say `0 is the first item.` They stay on the card. HX-25 owns a 1-based control.

Acceptance:

- A new Reducto card shows the API key and a closed `Advanced` disclosure. Opening it shows Reading model, First page, Last page, Tables, and Time limit (seconds). The model menu shows `Standard` and `Faster (not for spreadsheets)`, and saving still writes `r-1` or `r-1-mini`.
- Defaults are unchanged.

Tests:

- Add a case in `apps/web/src/features/workbench/canvas/config-schema.test.ts` that a property with `x-grafy-ui: "advanced"` and `x-grafy-enum-labels` becomes `advanced: true` and the label map.
- Add a render assertion in `apps/web/src/features/workbench/canvas/nodes/WorkflowNode.test.tsx` that a config schema marked advanced is inside a closed `details` whose summary is `Advanced`, and that the option label is the mapped word while the value attribute is the stored token.
- Do not change `tests/unit/plugins/test_reducto_ocr.py` default tuple.

## HX-07 — Say “API key”, not “secret”

- Severity: high
- Type: copy-only
- Class: mechanical
- Files:
  - `SecretInputField` in `apps/web/src/features/workbench/canvas/nodes/workflow/config-fields.tsx`
  - `NodeSecretInput` descriptions on the Reducto, Mistral, and OpenAI-compatible nodes

Current (`config-fields.tsx`):

- Placeholder `Replace secret` / `Enter secret`.
- Hint `Save the changed secret settings, then apply a new secret.`
- Hint `Save this node before configuring this secret.`
- Hint `Apply a key for the current endpoint.`
- Fallback `Write-only · the stored value cannot be read back.`
- Button `Apply`.
- Status `Not configured`, `Configured`, `Stale`, `Action failed`.

New:

- Placeholder `Replace key` / `Paste key`.
- `Save the changed settings, then paste the key again.`
- `Save this step before adding the key.`
- `Paste a key for the current service address.`
- Fallback `Grafy stores the key and does not show it again.`
- Button stays `Apply`.
- Status: `No key`, `Key saved`, `Key out of date`, `Could not save the key`. Leave `Checking…`, `Applying…`, `Removing…`, `Status unavailable`.

Secret descriptions:

| Current | New |
| --- | --- |
| `Write-only bearer credential for the Reducto platform API.` | `The key from your Reducto account.` |
| `Write-only bearer credential for the configured API origin.` | `The key from your Mistral account.` |
| `Write-only bearer credential for the configured API base URL.` | `The key for this service address.` |

Acceptance: the Reducto card does not contain the word `secret` or `bearer`.

Tests: `apps/web/src/features/workbench/ui/useNodeSecrets.test.ts` if it asserts those sentences. Otherwise add one assertion on `SecretInputField` in `WorkflowNode.test.tsx` for the unconfigured placeholder `Paste key`.

## HX-08 — Multi-input rows

- Severity: high
- Type: copy-only
- Class: mechanical
- File: `apps/web/src/features/workbench/canvas/nodes/workflow/instance-plug.tsx`

Current:

- Header rule `` `${acceptedShapeLabel} · plug order` ``. `acceptedShapeLabel` is `sequence` or `single`, joined by ` or `.
- Row meta joins `sequence` or `single`, `` `feed ${binding.conversionLabel}` ``, and `binding.contributionLabel`. Empty rows say `` `Accepts ${acceptedShapeLabel}` ``.
- Button text `Add input`.
- Accessible names already say `input`.

New:

- Map `many` → `a list` and `one` → `one item` before joining with ` or `.
- Header rule: `In this order`. Drop `plug`.
- Row meta: drop the word `feed`. Show `a list` or `one item`, then the conversion label only when it exists, then the contribution label. Join with ` · `. Empty row: `Nothing connected yet`.
- Button: `Add another`.
- Accessible names stay specific (`Documents input 1`). Do not put the word `plug` in a string a person can read, including `title` and `aria-label`.

Acceptance: the Collect card does not show `plug`, `feed`, `single`, or `sequence`.

Tests: `apps/web/src/features/workbench/canvas/nodes/WorkflowNode.test.tsx` asserts `"Add input"`. Change that expectation to `Add another`.

## HX-09 — What a step is doing

- Severity: high
- Type: copy-only
- Class: mechanical
- Files:
  - `NodeHeader` in `apps/web/src/features/workbench/canvas/nodes/workflow/node-header.tsx`
  - `STATE_LABELS`, `STATE_EXPLANATIONS`, `CollapsedFootprint`, `ResultPanel` in `apps/web/src/features/workbench/canvas/nodes/NodeExecutionAppendix.tsx`

Current header: the status is an 8px dot or a spinner. The accessible name is `` `Execution ${executionLabel}` `` where `executionLabel` is `running`, `cancelling`, `succeeded`, `failed`, or `queued`. There is no visible word.

Current appendix:

```
fresh: "Fresh" / "Its current fingerprint has a stored result."
stale: "Stale" / "The graph changed since this instance last computed."
queued: "Queued" / "A Run is waiting to compute it."
running: "Running" / "A computation for it is in flight."
failed: "Failed" / "Its last attempt failed; a Run retries it."
```

Collapsed footprint: `` `${stateLabel} result · ${artifactCount} artifact` `` / `artifacts`. Result tab: `This node has not been in a Run yet.` and `No stored result for this instance.` The fingerprint row prints `run.result_fingerprint.slice(0, 12)`.

New header: keep the dot or spinner, and add a visible word next to it: `Waiting`, `Working`, `Stopping`, `Done`, `Failed`. Accessible name is that word plus the node title, for example `Read with Reducto failed`.

New appendix copy:

| State | Label | Explanation |
| --- | --- | --- |
| fresh | Up to date | This is the result for the documents and settings connected now. |
| stale | Out of date | Something changed after this result. Run it again. |
| queued | Waiting | It will start when the current run reaches it. |
| running | Working | This step is running. |
| failed | Failed | The last run stopped. The message below says why. |

- Footprint: `Up to date · 3 results` (use `result` / `results`, not `artifact`).
- `Not run yet.`
- `No result saved for this step yet.`
- Delete the fingerprint row. Do not show the hash.

Acceptance: selecting a node that has never run shows `Not run yet.` The menu and the appendix do not contain `fingerprint`, `artifact`, or `Run` as a proper noun. `Run` as the verb on the toolbar is HX-17 and stays.

Tests: `apps/web/src/features/workbench/canvas/nodes/NodeExecutionAppendix.test.tsx` (it expects `No stored result for this instance.` and `Running`). `apps/web/src/features/workbench/canvas/nodes/WorkflowNode.test.tsx` expects `Execution failed`.

## HX-10 — Why Run is blocked

- Severity: high
- Type: copy-only
- Class: mechanical
- File: `executionValidationIssue` and the missing-input message in `apps/web/src/features/workbench/model/execution-plan.ts`
- Also `runRejectionMessage` in `apps/web/src/features/workbench/ui/useRunExecution.ts`

Current:

- `Add at least one node before running the workflow.`
- `Select at least one node before running a selection.`
- `` `${first.nodeTitle}.${first.portName} is required but unconnected in this run.` `` `portName` is the raw port name, or `` `${port.name} input ${index + 1}` ``.
- `` `Cannot run connection ${incompatibleEdge.id}: …` ``
- `This Graph is no longer in the Project. Reload it before running.`
- `A node this Run was asked for is no longer on the canvas. Select the nodes again.`
- `A node in this Run is not in the live node registry.`
- `The Graph cannot be run as it is saved.`

New:

- `Add a step before running.`
- `Select a step to run.`
- Use `port.title` when it is a non-empty string, otherwise the port name with underscores replaced by spaces. Message: `` `${first.nodeTitle} needs “${portLabel}” connected before it can run.` `` For an extra slot: `` `${first.nodeTitle} needs item ${index + 1} of “${portLabel}” connected before it can run.` ``
- `` `A connection on ${targetTitle} cannot be run. ${issues}` `` Do not print `incompatibleEdge.id`.
- `This canvas is no longer in the project. Reload before running.`
- `A step in this run is no longer on the canvas. Select the steps again.`
- `A step in this run is not available. Remove it, or restore the plugin it came from.`
- `This canvas cannot be run as it is saved.`

Acceptance: the blocked-run sentence does not contain a UUID or `nodeTitle.portName`.

Tests: `apps/web/src/features/workbench/model/execution-plan.test.ts` and `apps/web/src/features/workbench/ui/useRunExecution.test.ts`.

## HX-11 — Failure sentences from the readers

- Severity: high
- Type: copy-only
- Class: mechanical
- The card prints `execution.error` and `run.error` unchanged (`NodeExecutionAppendix`, `CollectionCard`). Change the sentence at the source.

| File | Current | New |
| --- | --- | --- |
| `plugins/reducto/src/grafy_plugin_reducto/ocr.py` | `Reducto OCR requires exactly one of a document URL or a raster image on node {id!r}` | `Connect either a document link or a page image, not both, and not neither.` |
| same | `document_url must use HTTPS` | `The document link has to start with https://.` |
| `plugins/mistral/src/grafy_plugin_mistral/ocr.py` and `ocr_sdk.py` | `Mistral OCR requires exactly one of a document URL or a raster image` | `Connect either a document link or a page image, not both, and not neither.` |
| `libs/workbench/src/grafy_workbench/sequence/nodes.py` `collect` | `Collect inputs must share one artifact type; expected {id}@{version}, got {id}@{version} at input {index}` | `Every item in the group has to be the same kind. Item {index + 1} does not match the first item.` Do not print type ids. |
| same, slice | `Cannot slice unordered sequence {sequence_id}` | `This list has no order, so a range cannot be taken from it.` |
| same, pick | `Cannot pick an item from unordered sequence {sequence_id}` | `This list has no order, so one item cannot be picked by position.` |
| same, pick | `Cannot pick index {index} from sequence {sequence_id} with length {length}` | `There is no item at position {index}. This list has {length} items, and 0 is the first.` |
| `libs/workbench/src/grafy_workbench/file/nodes.py` | `Interpret file needs an explicit format: bind its file output to one claimed file.* artifact type.` | `Choose the file type on this step before running it.` |
| same | `Interpret file does not know artifact type {id}@{version}` | `This file type is not available. Choose another type.` |
| same | `{id}@{version} is not a claimed file format; choose a file.* type the deployment recognizes.` | `That choice is not a file type this copy of Grafy knows. Choose another type.` |
| same | `file_format_mismatch: {label} does not look like a {expected} file. Bind the file output to another format or convert the file, then try again.` | `{label} does not look like a {expected} file. Choose another type, or replace the file, then run again.` |
| `plugins/reducto/.../ocr.py` `validate_page_range` | `page_end must not precede page_start` | `The last page cannot come before the first page.` |

Do not change `tests/integration/uploads/test_uploads.py`. That test asserts an API error code `file_format_mismatch` on upload, which is a different path.

Tests: `tests/integration/artifacts/test_file_interpret.py` matches `file_format_mismatch`. Point it at `does not look like a`. Add one assertion each in the existing Reducto and sequence unit tests if those files already test the failure; do not create a new test module.

## HX-12 — Plug failures must not quote ids

- Severity: high
- Type: copy-only
- Class: mechanical
- File: `_validate_input_plugs` in `apps/api/src/grafy_api/runs/contract.py`
- `apps/api/src/grafy_api/runs/errors.py` says this message is what a participant sees on a failed node.

Current, among others:

```
Node {graph_node.id!r} input plug {plug_id!r} requires exactly one incoming connection
```

Also the messages in that function that include `input plug`, `instance plugs`, `instance-plug`, and `collection mode 'map'`.

New sentences, still raised as `NodeComputationError`, with no node id and no plug id:

| Situation | New message |
| --- | --- |
| Duplicate plug id | `This step has two slots with the same identity. Remove the extra slot and add it again.` |
| Plug references an unknown port | `A slot on this step points at an input that no longer exists. Remove the step and add it again.` |
| Port does not accept plugs | `This input cannot take more than one connection.` |
| Required plug port has no plugs | `Add at least one slot on “{port.title or port name}”.` |
| Item declares a plug on a port that does not accept them | `That connection was aimed at a slot this input does not have.` |
| Map mode on a plug input | `This input takes slots one by one. It cannot take a mapped list.` |
| Missing plug target | `This connection is not aimed at a slot.` |
| Unknown plug | `This connection points at a slot that was removed.` |
| Plug belongs to another port | `This connection is aimed at a slot on a different input.` |
| Plug does not have exactly one connection | `Each slot needs exactly one connection. An empty extra slot, or two connections into one slot, blocks the run.` |

Use the port title when `InputPortSpec.title` is set, otherwise the port name with underscores turned into spaces. Never interpolate `graph_node.id` or `plug.id`.

Acceptance: a failed node whose slots are wrong does not show a UUID.

Tests: search `requires exactly one incoming`. No test asserts that sentence today. Add one unit test next to the existing contract tests that feeds a plug with zero connections and expects `Each slot needs exactly one connection`. If there is no nearby test module for `_validate_input_plugs`, add the test in the unit test file that already imports `NodeComputationError` from `grafy_api.runs`. Do not create a new package.

## HX-13 — Opening a saved canvas

- Severity: medium
- Type: copy-only
- Class: mechanical
- File: `apps/web/src/features/workbench/canvas/saved-graph.ts`, every `SavedGraphHydrationError` message, plus the in-card issue `` `Saved connection ${savedEdge.id} references removed input ${savedEdge.to_port}.` ``

Current messages include `node ${savedNode.id}`, `input plug ${plug.id}`, `edge ${savedEdge.id}`, `collection mode`, `artifact type variable`, and `operator_id`.

New rule: the sentence starts with `Cannot open “${savedGraph.name}”.` Then one of:

- `A step has a slot the input does not allow.`
- `A step has two slots with the same identity.`
- `A connection points at a step that is not on the canvas.`
- `A connection points at an input that is not on that step.`
- `A connection points at a slot that was removed.`
- `Two connections land on the same slot.`
- `A connection uses a list mode this input does not accept.`
- `A connection joins two kinds of document that do not fit.`
- `A step’s type is not available.`
- `This file has two connections with the same identity.`

Do not include ids. Keep the throw. Change only the string.

The in-card issue becomes `A saved connection points at an input this step no longer has.`

Tests: `apps/web/src/features/workbench/canvas/saved-graph.test.ts`. Update assertions that match the old sentences. Add one assertion that a duplicate plug throws a message containing `same identity` and not the plug id, if that case is not already covered.

## HX-14 — Reader cards and lists of files

- Severity: medium
- Type: copy-only
- Class: mechanical
- Files:
  - `apps/web/src/features/workbench/canvas/nodes/ArtifactCardBody.tsx`
  - `CELL_VIEW_LABEL` in `apps/web/src/features/workbench/canvas/nodes/artifact-renderers/table/cell-views.ts`

Current:

- Sequence title falls back to `File sequence`.
- Waiting copy: `Waiting for output`, `Waiting for this graph to run`, `` `Waiting for ${port}` ``, `` `${title} is running` ``, `` `Run ${title} to fill it` ``.
- Group label `` `Artifact ${contract}` ``.
- View labels: `Text`, `Markdown`, `JSON`, `HTML`. The switch is `Read this text as`.

New:

- Sequence title: `List` when it is not images. Image sequences already say `N items`; keep that.
- `Waiting for a result`
- `Waiting for a run`
- `` `Waiting for ${port title}` `` (already uses `feedPort?.title` once HX-03 lands; keep the fallback `result` instead of `output`)
- `` `${title} is working` ``
- `` `Run ${title} to fill this card` ``
- Group label `` `Document ${contract}` `` for one item and `` `List of ${contract without a second "List of" prefix}` ``. If `contract` already starts with `List of `, the group label is just `contract`.
- View labels: `Plain text`, `Formatted text`, `Data`, `Web page`. Keep the accessible name `Read this text as`.

Acceptance: a markdown card’s switch says `Formatted text`. A sequence of files is not titled `File sequence`.

Tests: `ArtifactCardBody.test.tsx` and `apps/web/src/features/workbench/canvas/nodes/artifact-renderers.test.tsx` if they assert `Markdown` or `File sequence`.

## HX-15 — Collections and a dropped folder

- Severity: medium
- Type: copy-only
- Class: mechanical
- Files:
  - `apps/web/src/features/workbench/canvas/nodes/CollectionCard.tsx`
  - `apps/web/src/features/workbench/ui/ArtifactFolderDropDialog.tsx`
  - Collect strings in `apps/web/src/features/workbench/ui/Workbench.tsx` (`Put this artifact in a sequence`, `ordered sequence`, `Collect ${n} selected artifacts into an ordered sequence`)

Current collection card:

- Empty body: `Wire outputs or drop artifacts here`
- `Waiting for outputs` / `` `Waiting for ${label}` ``
- Menu info title `Collection`
- `` `${libraryCount} from the Library · ${outputCount} from outputs` ``
- `` `${pending.length} waiting for a run` ``
- Member source `Output · waiting for a run`
- Spare ball title `Wire an output or a card here to add it to the collection` and `ariaLabel="Add to collection"`
- `` `${filled.length} members · in the order they pass on` ``
- Fallback name `ref.artifact_type` (the raw id) when a library item has no name

New:

- `Drop files here, or connect a result`
- `Waiting for a result`
- Info title `Group`
- `` `${libraryCount} from the library · ${outputCount} from earlier steps` ``
- `` `${pending.length} waiting to be run` ``
- `Waiting for a result`
- Spare: accessible name `Add to this group`, title `Connect a result here, or drop a file on the card`
- `` `${filled.length} items · in this order` ``
- Fallback name `Document`, never `ref.artifact_type`

Folder dialog:

- Title `` `${name} holds ${n} kinds of file` ``
- Description `A list holds one kind of file, so each kind needs its own list.`
- Button `Create ${n} lists` / detail `one per kind of file`
- `Or place just one kind:` / `Choose which kind to place:`
- The count already says `1 artifact`. Change `artifact` / `artifacts` to `file` / `files`.

Selection toolbar and context menu, same Workbench strings:

- `Put this file in a list`
- `Group ${n} selected files into one list`
- `Select files of the same kind to group them`
- Button label stays `Collect` (it is short and already on the toolbar). Title attributes use the new sentences.

Acceptance: the empty collection does not say `Wire` or `artifact`.

Tests: `apps/web/src/features/workbench/ui/ArtifactFolderDropDialog.test.tsx`, collection card tests if they assert the empty string. Search `Wire outputs`.

## HX-16 — Add node

- Severity: medium
- Type: copy-only
- Class: mechanical
- Files:
  - `buildCatalogFilters` in `apps/web/src/features/workbench/model/node-catalog.ts`
  - `NodeInspector` and `PortChips` in `apps/web/src/features/workbench/ui/node-selector/NodeInspector.tsx`
  - Empty copy in `apps/web/src/features/workbench/ui/NodeSelector.tsx`
  - `ContextualNodeDiscovery.tsx` strings `No description is available.`, `Choose which output feeds this input`, `Choose how this output arrives`

Current filters: `All nodes`, `Single value`, `Sequence`, `Any artifact`.

Current inspector: section title `Ports`, the line `` `${operator_id}@${version}` ``, chips `Takes` / `Makes`, empty `Nothing — it starts a workflow` / `Nothing — it ends a branch`, `Select a node to inspect its contract.`

New:

- Filters: `All steps`, `One item`, `Lists`, `Any kind`.
- Section title `Inputs and outputs`.
- Keep `` `${operator_id}@${version}` `` inside that Details block. It is already behind the disclosure. Label it with a heading `Technical id` above the mono line.
- Chip empty copy: `Nothing. This step starts the work.` / `Nothing. This step ends the work.`
- `Select a step to see what it needs and what it produces.`
- Discovery: `No description yet.`, `Choose which result fills this input`, `Choose how this result arrives`.
- `No nodes found.` → `No steps found.`
- `No nodes match the current search or filter.` → `No steps match this search.`
- Placeholder `Search nodes, types, settings…` → `Search steps`.

Acceptance: the filter row does not say `Sequence` or `artifact`.

Tests: `apps/web/src/features/workbench/ui/NodeSelector.test.tsx`.

## HX-17 — Canvas dock and the selection toolbar

- Severity: medium
- Type: copy-only
- Class: mechanical
- File: `apps/web/src/features/workbench/ui/Workbench.tsx`

Current:

- Icon button label `Canvas lab`, title `Experiment with canvas behavior`.
- `With dependencies`, title `Run the selection and every upstream dependency (…)`.
- `Run only the selected nodes; latest accessible upstream outputs are pinned`.
- `Unavailable or invalid upstream dependencies cannot run`.
- `Fit` / `Fit workflow`.
- `Runs` / `Browse this Project's Runs`.
- Context menu `Canvas settings…` already exists (`CanvasContextMenu`).

New:

- Label `Canvas settings`, title `Grid and snap`.
- Button `Also run earlier steps`. Title `Runs the selection and the steps that feed it (${n} steps).`
- `Run the selected steps. Earlier results that are already saved are reused.`
- `An earlier step is missing or cannot run.`
- Title `Fit the canvas`.
- Label `Past runs`, title `Past runs in this project`. Disabled title `Save the project to see past runs.`

Do not retitle the product objects Project and Graph in the shell navigation. This task is the workbench dock only.

Tests: search `Canvas lab` and `With dependencies` in `apps/web/src/features/workbench/ui`.

## HX-18 — Connection loss and “bind the type”

- Severity: medium
- Type: copy-only
- Class: mechanical
- Files:
  - `apps/web/src/features/workbench/ui/GraphRoomRecoveryNotice.tsx`
  - `GenericArtifactTypeState` in `apps/web/src/features/workbench/canvas/nodes/workflow/generic-body.tsx`

Current recovery:

- `Stale graph — read only`
- `Graph unavailable`
- `The last confirmed graph is shown. Server-accepted work is preserved; visible local changes stay on this device until reconnection confirms them.`
- `No confirmed graph is available yet.`
- `The client and server collaboration protocols are incompatible. Reload the graph after updating either side.`
- `Automatic reconnection stopped. Retry the connection to request a fresh graph.`
- `Connecting and loading the current graph.`
- `Reconnecting and loading a fresh graph before graph operations resume.`

New:

- `Showing the last saved canvas. Editing is paused.`
- `Canvas unavailable`
- `This is the last canvas the server confirmed. Work the server accepted is kept. Changes that are only on this computer stay here until the connection returns.`
- `Nothing is loaded yet.`
- `This page and the server are out of date with each other. Reload after updating one of them.`
- `Reconnection stopped. Try again to load the canvas.`
- `Connecting.`
- `Reconnecting. Editing waits until the canvas has loaded.`

Current generic type row: label `Type` or `Type ${variable}`, `aria-label` `` `Bind artifact type ${variable}` ``, title `Bind ${variable} to an artifact type`, `Disconnect this node before changing its type`, button `Reset artifact type ${variable}`.

New: label `Kind of file` (when there is one variable) or `Kind ${variable}` (when there are several). Accessible name `Choose the kind of file`. Title `Choose the kind of file`. Locked title `Disconnect this step before changing the kind of file.` Reset name `Clear the kind of file`.

Acceptance: the recovery banner does not say `protocol` or `graph operations`. The type row does not say `Bind` or `artifact type`.

Tests: `apps/web/src/features/workbench/ui/GraphRoomRecoveryNotice.test.tsx`.

## HX-19 — A step the server no longer knows

- Severity: medium
- Type: copy-only
- Class: mechanical
- Files:
  - `IncompatibleWorkflowNodeCard` in `apps/web/src/features/workbench/canvas/nodes/workflow/cards.tsx`
  - `CompatibilityPort` in `apps/web/src/features/workbench/canvas/nodes/workflow/ports.tsx`

Current:

- Badge text is `compatibility.status` (`unavailable` or `invalid`). Title `` `${title} is ${compatibility.status}` ``.
- About: `` `This node is ${status}. Remove it, or restore the plugin release it was saved with.` ``
- Summary `Saved configuration`, then `JSON.stringify(data.config)`.
- Port label `` `${portName} · ${plugId}` `` and title `Historical ${direction} ${label}`. Ball title `This historical ${direction} cannot accept new connections.`

New:

- Badge `Unavailable` for both statuses. Title `` `${title} cannot run` ``.
- About: `This step cannot run. Remove it, or restore the plugin it was saved with.`
- Summary `Saved settings`. Keep the JSON inside the closed disclosure. It is the only record of what was stored. The summary is the plain label.
- Port label is the port name with underscores turned into spaces. Do not append the plug id.
- Title `Saved ${direction}`. Ball title `This saved input cannot take new connections.` (use `input` or `output`).

Acceptance: an unavailable card does not show a plug UUID on the port row.

Tests: `WorkflowNode.test.tsx` if it renders an unavailable node and asserts `unavailable`.

## HX-20 — Type size and hit area on the card

- Severity: medium
- Type: visual
- Class: mechanical
- Files:
  - `apps/web/src/features/workbench/canvas/nodes/NodeExecutionAppendix.tsx` styles `footprint`, `tab`, `tabCount`, `row`, `state`, `omission`
  - `plugAction`, `plugGrip`, `plugRow` in `apps/web/src/features/workbench/canvas/nodes/workflow/instance-plug.tsx`

Current: appendix copy is `fontSize: "9px"` (`footprint`, `tab`, `row`, `state`). Tabs are `minHeight: "22px"`, uppercase, `letterSpacing: "0.04em"`. Plug actions are `width: "18px"`, `height: "20px"`. The grip is `20px` by `26px`. The row is `minHeight: "38px"`.

`apps/web/AGENTS.md` forbids `phoneTouch` on controls inside a canvas card. Do not add it.

New:

- Appendix text `12px`. Tab `minHeight: "28px"`, `fontSize: "12px"`, remove `textTransform: "uppercase"` and the letter spacing. Tab words stay `Events` and `Result`.
- `plugAction`: `width: "24px"`, `height: "24px"`.
- `plugGrip`: `width: "24px"`, `height: "32px"`.
- `plugRow` `minHeight: "44px"`.
- Leave the port ring geometry in `handle-style.ts` alone.

Acceptance: the plug remove control is 24 by 24. Appendix text is 12px. No `phoneTouch` import in these two files.

Tests: `WorkflowNode.test.tsx` plug-row test still finds the buttons by accessible name. No pixel assertion is required.

## HX-21 — Technical id off the card menu

- Severity: low
- Type: copy-only
- Class: mechanical
- Files: `NodeHeader` in `node-header.tsx`, the incompatible card in `cards.tsx`, `operatorCopy` in `apps/web/src/features/workbench/canvas/nodes/workflow/styles.ts`

Current footer: `` `${data.spec.operator_id}@${data.spec.operator_version}` `` inside the card’s info menu.

New: pass no `aboutFooter` from these two call sites. The id remains in Add node Details (HX-16). If `operatorCopy` has no remaining use, delete it from `styles.ts`.

Acceptance: opening a card’s menu does not show `reducto.ocr.process@1` or any `operator_id@version`.

Tests: a render of `NodeHeader` or the workflow card, asserting the menu text does not include `@1`.

## HX-22 — A connection that is switched off

- Severity: medium
- Type: copy-only
- Class: mechanical
- File: `OptionalConnectionToggle` in `apps/web/src/features/workbench/canvas/nodes/workflow/ports.tsx`

Current: `aria-label` `` `${label} connection enabled` ``, title `Disable connection` / `Enable connection`. The wire stays drawn. Do not change how the wire is drawn.

New:

- Accessible name `` `${label} is used` `` when checked and `` `${label} is not used` `` when unchecked.
- Title `Stop using this connection` / `Use this connection`.
- `PortTab`, when `connectionDisabled`, appends a visible ` · not used` after the port name, in the existing `tabShape` style.

Acceptance: a switched-off port shows `not used` on the row. Edge files are untouched.

Tests: add a case in `WorkflowNode.test.tsx` if an optional port is already rendered there. Otherwise add the assertion beside the existing port-rail test in that file.

## HX-23 — Empty canvas tells you what to do

- Severity: medium
- Type: behavior
- Class: needs-design
- Do not implement in the mechanical pass.

Desired behavior, for a later change in `apps/web/src/features/workbench/ui/Workbench.tsx`: when the canvas has no workflow nodes, no artifact cards, no collection cards, and no annotations, and the project room is not in a loading or recovery state, show one centered note: `Drop files on the canvas, or use + to add a step.` Right-click still opens the canvas menu. The note is not a hit target and disappears as soon as any of those objects exist. It must not appear over a canvas that failed to load (HX-18’s banner covers that).

## HX-24 — The spare slot on a group

- Severity: high
- Type: behavior
- Class: needs-design
- Do not implement in the mechanical pass. Do not edit `canvas/edges/` when it is implemented.

`CollectionCard` draws the spare `PortBall` with `revealed={active || portReveal.connecting || membersWired}`. Until the card is selected, connecting, or already wired, the extra socket is not there. Members are listed without empty plugs (`managing` comment in the same file).

Desired behavior: the spare socket stays visible on an editable collection, with the HX-15 name `Add to this group`. Empty plugs are still omitted from the member list. Do not change edge paths, dock geometry, or which plug a drop binds to (`data-input-plug-id` already points at the spare).

## HX-25 — Page and position numbers start at 1 on screen

- Severity: medium
- Type: behavior
- Class: needs-design
- Do not implement in the mechanical pass.

Stored values stay 0-based: `DrawRegionsConfig.page`, `SliceConfig.start`, `ItemAtConfig.index`. A later change may show `stored + 1` in the input and write `displayed - 1`, and only when the displayed value is an integer ≥ 1. Empty stays empty. HX-06’s descriptions (`0 is the first page`, `0 is the first item`) are the honest copy until that control exists. When HX-25 lands, replace those descriptions with `The first page is 1.` and `The first item is 1.`

## HX-26 — Do not flash raw type ids while the catalog loads

- Severity: medium
- Type: behavior
- Class: needs-design
- Do not implement in the mechanical pass.

`useArtifactTypeCatalog` returns `[]` until `useNodeRegistry` resolves. `formatArtifactTypeLabel` then falls back to `text.markdown@1` because the empty list does not contain the type. `apps/web/AGENTS.md` requires a `null` catalog to return the full identity, so do not change that fallback.

Desired behavior: while the registry request is in flight, cards and ports show `…` as the type, and the tooltip can still be the identity. After the registry loads, they show the catalog title. A sandbox with no workspace keeps the full identity.

## HX-27 — A missing connection is visible before Run

- Severity: medium
- Type: behavior
- Class: needs-design
- Do not implement in the mechanical pass.

`missingRequiredInputsFor` in `execution-plan.ts` already knows a required port is empty. The card shows nothing about that until Run fails or the appendix is opened. A later change may show the HX-10 sentence on the card while the node is selected and idle. Do not invent a second copy of the sentence. Do not draw a new wire.

## Checks

From `apps/web`:

```
npx vitest run src/features/workbench/canvas/artifact-type-label.test.ts src/features/workbench/canvas/artifact-card.test.ts src/features/workbench/canvas/config-schema.test.ts src/features/workbench/canvas/nodes/WorkflowNode.test.tsx src/features/workbench/canvas/nodes/NodeExecutionAppendix.test.tsx src/features/workbench/canvas/nodes/ArtifactCardBody.test.tsx src/features/workbench/canvas/nodes/type-inspector.test.tsx src/features/workbench/canvas/saved-graph.test.ts src/features/workbench/model/execution-plan.test.ts src/features/workbench/ui/NodeSelector.test.tsx src/features/workbench/ui/ArtifactFolderDropDialog.test.tsx src/features/workbench/ui/GraphRoomRecoveryNotice.test.tsx src/features/workbench/ui/useRunExecution.test.ts src/features/workbench/agents/ToolEvents.test.tsx
```

From the repo root, the Python tests named in HX-11 and HX-12, plus `tests/unit/plugins/test_reducto_ocr.py` to prove defaults did not move.

Done means those tests pass and a search of `apps/web/src/features/workbench` finds no user-visible `Sequence<`, `plug order`, `Canvas lab`, or `file_format_mismatch`.

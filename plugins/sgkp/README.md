# Grafy SGKP plugin

The SGKP plugin repairs settlement types on gazetteer entries that are currently
typed as `odsyłacz`. It is a Workspace Plugin: publish it into the IHPAN
Workspace rather than the System inventory.

The expert settlement-type catalog and SGKP abbreviation glossary ship inside
the package.

## Nodes

### `sgkp.dataset.import_json@1`

Connect a `file.json@1` artifact holding one `sgkp_XX.json` array of records. The
node reads the file and emits `sgkp.dataset@1` named after the artifact's
original filename.

### `sgkp.references.select@1`

Scan the dataset for `odsyłacz` entries. By default it keeps only candidates
with a text or field signal. Set `all_references` to include every cross-reference
that has text. Outputs a sequence of `sgkp.reference.candidate@1` plus an
inspectable `table.data@1`.

### `sgkp.references.classify@1`

Classify one candidate with an OpenAI-compatible Chat Completions endpoint.
Bind the write-only `api_key` secret. Defaults:

- `base_url`: `https://ai-test.ihpan.edu.pl/v1`
- `model`: `gemma-4-31b-it`

Map this node over the candidate sequence. Invalid JSON is retried with the
validator message; transient HTTP failures are retried without changing the
prompt.

### `sgkp.references.apply@1`

Merge validated decisions back into the dataset. High-confidence
`dodaj_typ_miejscowosci` decisions update `typ`. `typ_punktu_osadniczego` is
updated only when the decision also has explicit administrative location.
Medium confidence is applied only when `apply_medium_confidence` is on.

## Verify the plugin

Run these commands from this directory:

```shell
uv sync --locked --no-sources --find-links wheels
uv run pytest -q
```

## Publish to the IHPAN Workspace

Use a Workspace PAT with `publish_plugin` issued in the IHPAN Workspace:

```shell
grafy plugin check plugins/sgkp
grafy plugin publish plugins/sgkp --slug sgkp
```

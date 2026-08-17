# Example Plugin: Notes

This is the intended **Plugin** shape from
[plugin unification](../../docs/design/workspace-plugins/README.md): a uv-managed
project you can open in Cursor, not a `grafy.plugins` entry point loaded into
FastAPI.

It is **not** discovered by the API. Publication would freeze this tree into an
isolated runtime image. `RUNTIME_PROFILE = "python-uv"` is wheels-only; GDAL
would be a different pinned profile, not `apt` here.

## What it demonstrates

| Point | How |
| --- | --- |
| Always a Plugin, even for one node | Slug `notes`; two nodes share one lockfile |
| Typed like host plugins | `function_node` + Pydantic `InPort` / `OutPort` |
| Depend on core, not other plugin packages | `table.data@1` and `scalar.text@1` from `grafy-core` |
| New artifact type | `notes.table_summary@1` with writer and resolver in *this* package |
| No host import | This `pyproject.toml` has no `grafy.plugins` entry point |
| Isolated persistence | Writer/resolver factories take a UoW; they are not API process code |

A Pillow `Image` field would **not** be a catalog type until this project also
shipped blob storage adapters for it. JSON `TableSummary` is enough because
`InlineModelOutputWriter` can persist it.

## Nodes

1. `notes.table.summarize@1` — `table.data` → `notes.table_summary`
2. `notes.summary.render@1` — `notes.table_summary` → `scalar.text`

## Run its tests

From the repository root (after `uv sync`):

```bash
uv run pytest examples/plugin-notes/tests tests/unit/examples/test_plugin_notes.py
```

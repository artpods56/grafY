# Plugin freeze fixture: Notes

A standalone uv-managed Plugin project that `tests/unit/api/test_plugin_publishing.py`
freezes. It is a test asset, not a template to copy: Workspace Plugins do not
exist, and nothing here is published by hand.

The project declares two typed `callable_node` functions, so a freeze exercises
derived config and port contracts rather than a hand-written manifest:

1. `notes.table.summarize@1` — `table.data@1` to `notes.table_summary@1`
2. `notes.summary.render@1` — `notes.table_summary@1` to `scalar.text@1`

It also owns the writer and resolver for `notes.table_summary@1`, which uses the
canonical inline JSON bundle. That keeps the fixture's freeze honest about the
artifact contract a release carries.

The versioned Grafy Plugin SDK wheel (`grafy-core`) is vendored under `wheels/`
and pinned by `[tool.uv.sources]`, so the project and its `uv.lock` resolve
without a monorepo-relative path dependency. `tests/unit/architecture/` pins the
wheel digest; rebuild it with `just sdk-wheel` when `libs/core` changes a module
a Plugin imports.

# Example Plugin: Notes

This is a standalone uv-managed Plugin project following
[Plugin unification](../../docs/design/plugin-unification.md). It has its own
`uv.lock` and is published as an immutable Workspace release; installing the
project never loads its working copy into FastAPI.

The project declares two typed `callable_node` functions. You can call them as
ordinary Python functions, while Grafy derives their config and port contracts:

1. `notes.table.summarize@1` — `table.data@1` to `notes.table_summary@1`
2. `notes.summary.render@1` — `notes.table_summary@1` to `scalar.text@1`

It also owns the writer and resolver for `notes.table_summary@1`. That type uses
the canonical inline JSON bundle within this release. Another Plugin cannot
consume it merely by importing this working copy: the other release must
independently declare and support the same stable artifact contract. Releases
without that support remain non-runnable.

The versioned Grafy Plugin SDK wheel (`grafy-core`) is vendored under `wheels/`
and pinned by `[tool.uv.sources]`, so the project and its `uv.lock` are fully
self-contained: publication never resolves a monorepo-relative path
dependency. Deployments that build their own SDK wheels may instead point the
publisher's `UV_FIND_LINKS` wheelhouse at their own `grafy-core` build; the
vendored copy keeps the example freezeable as-is.

Publish it after configuring a Workspace credential:

```bash
grafy plugin check examples/plugin-notes
grafy plugin publish examples/plugin-notes --slug notes
```

Grafy derives the target Workspace and User from the configured credential.

Publication builds an immutable runtime image containing the locked project.
At execution, `table.data@1` crosses the networkless sandbox boundary as the
versioned `grafy.plugin.table-bundle.v1` archive: the host authorizes and
validates canonical chunks, while the vendored SDK resolves and writes the
portable Table inside the image.

The catalog derives `runnable` from the complete release contract. This example
is runnable only when its image uses the current invocation protocol, the
deployment has the `python-uv` runtime adapter, and every declared capability
and artifact bundle is supported. Source-only, old-protocol, or partially
supported releases remain visible for pinned history but disabled for new
authoring.

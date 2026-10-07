# Issue 138 verification

The implementation follows [ADR 0012](../adr/0012-python-node-runs-on-a-system-plugin-release.md).

## Behavioral checks

- Real Docker graph: text.input → Split preset → map Replace preset → Join preset produces `changed,second,changed`, identical to the old operators on the same input.
- The second run reuses every Python result without another guest invocation. All five first-run guest invocations share one container. Network access fails, cancellation removes the container, and closing a scope leaves no orphan.
- Browser: insert Replace text, edit params without opening Code, drag an actual wire, edit code without network requests, cancel then confirm a port retype, and show an Apply error on its editor line. Passed on this worktree's port 3138.
- Library and both contextual discovery directions exclude the four hidden text operators. They remain registered; `tests/integration/artifacts/test_text.py` is unchanged.
- All five preset contracts are derived from their copied code. Unsupported Params and port types produce line diagnostics. Table payload classes have real annotations. Host output schema failure prevents artifact persistence. Remote schema references are rejected without retrieval; the final host artifact suite passed all 33 tests.

## Falsification

- Changed the Split output annotation from `list[str]` to `str` in a copied test input. The stored-contract assertion failed. The original preset passed.
- Bypassed host payload validation in an isolated test process. The expected rejection assertion failed. Restoring validation rejected the output and left no persisted artifact.
- Marked the four old operators listed in a temporary copy of the catalog test. The hidden-library assertion failed. The original test passed.

## Checks

- Web tests: 1,006 passed.
- Focused backend sandbox, code-model and architecture tests: 43 passed.
- Web pointer/Apply test: 1 passed.
- Python and web lint, TypeScript, API contract generation, formatting and production web build passed.
- Bare `just check` loaded the local `.env`, causing six unrelated settings/network-policy tests to fail. Those files are unchanged. All 57 tests in those suites pass without that injected environment; the same six failures occur against an archived baseline with the local environment injected.
- Python type checking reports 993 errors on both this change and an archived `f4a519a0` baseline with the same environment and checker. Comparing normalized file/message pairs finds no added diagnostics. Main's CI checks a narrower Python scope, so this is local baseline evidence, not a claim that the same CI job failed on main.

`just --no-dotenv check` passed the backend suite with 1,917 passed and 55 skipped, the web suite with 1,006 passed, and lint. It stopped at the same 993 baseline Python type errors. API contract and production build passed separately. This work does not weaken the type-check gate or repair unrelated type errors.

## Scope and deployment

`external.python` must be published and promoted through the existing System Plugin workflow before the presets are available. Supported port types are the release's declared Text, Integer, Markdown and Table contracts. Further artifact types require a new runner release.

No custom sandbox, live editor services, user-defined port types, multiple data ports, cache override, preset-reset UI or saved-graph migration was added. Saved-graph hydration only resolves the stored per-instance shapes; its error handling is unchanged.

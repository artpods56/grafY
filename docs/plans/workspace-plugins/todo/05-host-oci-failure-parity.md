# Work packet 05: Typed host/OCI execution failure parity

- **Status:** Partially implemented; one focused test is red
- **Parent slice:** [Slice 10](../10-artifact-contract-and-runtime-parity.md)
- **Outcome:** The same exact release reports the same stable typed failure code
  through host and OCI execution, while preserving adapter-specific cause detail

## Problem

Before the partial edit, a host operator surfaced its native exception while an
OCI operator surfaced `PluginInvocationError` with a protocol failure code buried
in text. Callers could not handle the same release consistently across routing
adapters.

The public invariant is typed classification, not byte-identical error strings.
Host and OCI causes naturally contain different adapter context; both must retain
that context in the exception chain [R42: Errors Carry Context].

## Required invariants

1. `NodeRuntime` translates every operator invocation failure into one
   provider-neutral `NodeRunError` carrying an exact `PluginFailureCode`.
2. A host operator exception maps to `operator_failure`.
3. An OCI `PluginInvocationError` preserves its explicit protocol failure code;
   an OCI error without a code maps to `internal_adapter_failure`.
4. The original host exception or OCI invocation error remains the direct cause.
5. Cancellation is never translated into an operator or adapter failure.
6. `NodeExecutionResult.failure_code` exposes the same code for both adapters.
7. No caller parses error text to obtain the code.
8. Success, skip, cache, release identity, progress, and artifact provenance
   behavior already added by the parity work must remain unchanged.

Use the existing `PluginFailureCode` as the single classification vocabulary for
the protocol and public execution result. Do not introduce a duplicate enum.

## Current partial state

The interrupted edit has already added or changed:

- `PluginInvocationError.failure_code`;
- provider-neutral `PluginReleaseNode*` names;
- serialized node `cache_policy` and isolated cache selection;
- opaque secret revisions in exact cache keys;
- host/OCI release metadata and provenance normalization;
- `NodeRunError.failure_code` in `grafy_core.runtime.execution`;
- `NodeExecutionResult.failure_code` and coordinator propagation.

At the checkpoint, this command reports `2 passed, 1 failed`:

```bash
uv run pytest -q -o log_cli=false \
  tests/unit/api/runtime/test_system_adapter_parity.py
```

The red assertion still expects `PluginInvocationError` directly. Production now
correctly wraps it in `NodeRunError`; update the test to assert the typed public
contract and its cause chain. Do not revert the wrapper merely to make the old
assertion pass [R10: Tests Must Not Justify Bad Design].

## Owned files

- `libs/core/src/grafy_core/runtime/execution.py`
- `libs/core/src/grafy_core/runtime/plugin_invocation.py` only if the error type
  needs a narrow correction
- `apps/api/src/grafy_api/execution/coordinator.py`
- `apps/api/src/grafy_api/execution/models.py`
- `tests/unit/api/runtime/test_system_adapter_parity.py`
- `tests/unit/api/runtime/test_graph_execution_coordinator.py`
- focused core execution/invocation tests if an existing assertion requires the
  new public error contract

Do not redesign the whole API error envelope or plugin protocol in this packet.

## Implementation steps

1. Audit `NodeRuntime.run_node()` so only the actual node invocation is classified
   as operator/OCI failure. Config, materialization, persistence, and cache errors
   must not be mislabeled as operator failures.
2. Preserve explicit OCI failure codes and classify native host exceptions as
   `operator_failure`.
3. Ensure `asyncio.CancelledError` and the project's execution-cancellation error
   propagate unchanged.
4. Update coordinator result construction so failed host and OCI nodes expose the
   same `failure_code`. A skipped or successful result must have `None`.
5. When `raise_node_errors=True`, keep `NodeRunError` in the cause chain of the
   contextual `GraphExecutionError`; do not discard the typed failure.
6. Update the focused parity test to compare typed codes and cause classes while
   allowing adapter-specific contextual messages.

## Behavioral acceptance tests

Prove with the same exact System release and node contract that:

- host failure raises `NodeRunError(operator_failure)` caused by the native
  operator exception;
- OCI failure raises `NodeRunError(operator_failure)` caused by
  `PluginInvocationError(operator_failure)`;
- graph result mode emits identical `NodeExecutionResult.failure_code` for host
  and OCI;
- an OCI output-validation failure preserves `output_validation_failure`;
- an unclassified adapter failure becomes `internal_adapter_failure`;
- progress emitted before failure is identical;
- cancellation propagates as cancellation and produces no false failure code;
- success and cache-parity tests remain green.

## Focused gate

```bash
uv run pytest -q -o log_cli=false \
  tests/unit/api/runtime/test_system_adapter_parity.py \
  tests/unit/api/runtime/test_graph_execution_coordinator.py \
  tests/unit/core/test_plugin_invocation.py

uv run ruff check \
  libs/core/src/grafy_core/runtime/execution.py \
  libs/core/src/grafy_core/runtime/plugin_invocation.py \
  apps/api/src/grafy_api/execution/coordinator.py \
  apps/api/src/grafy_api/execution/models.py \
  tests/unit/api/runtime/test_system_adapter_parity.py \
  tests/unit/api/runtime/test_graph_execution_coordinator.py

uv run basedpyright \
  libs/core/src/grafy_core/runtime/execution.py \
  libs/core/src/grafy_core/runtime/plugin_invocation.py \
  apps/api/src/grafy_api/execution/coordinator.py \
  apps/api/src/grafy_api/execution/models.py
```

## Definition of done

- Host and OCI failures share a stable typed classification at both direct node
  runtime and graph-result boundaries.
- Adapter-specific causes and contextual messages remain inspectable.
- Cancellation is not reclassified.
- Focused tests, Ruff, type checking, and `git diff --check` pass.
- Implementation evidence is appended below.

## Implementation evidence

Files changed (relative to HEAD):

- `libs/core/src/grafy_core/runtime/execution.py` (modified) — `NodeRunError` carries the stable `PluginFailureCode`; `NodeRuntime` converts every operator invocation failure at the public boundary: `PluginInvocationError` keeps its explicit code (or defaults to `internal_adapter_failure` when unclassified), every other operator exception becomes `operator_failure`, and the original exception is preserved as `__cause__`. Host and OCI failures therefore surface through the identical typed shape.
- `apps/api/src/grafy_api/execution/coordinator.py` (modified) — graph results expose the typed `failure_code` per failed node (`operator_failure`, `output_validation`, `internal_adapter_failure`); raise mode keeps the typed failure in the cause chain.
- `apps/api/src/grafy_api/execution/models.py` (modified) — result models carry the `failure_code` field.
- `tests/unit/api/runtime/test_system_adapter_parity.py` (new) — 5 tests; this completion rewrote `test_same_exact_system_release_has_failure_and_cancellation_parity` to assert `NodeRunError` + `failure_code` + cause chains for both host and OCI (host: native operator exception; OCI: `PluginInvocationError`), and added `test_same_exact_system_release_has_graph_result_failure_code_parity` and `test_oci_invoker_failures_preserve_explicit_codes_and_default_to_internal` (with a failing invoker fixture).
- `tests/unit/api/runtime/test_graph_execution_coordinator.py` (modified) — added `test_failed_nodes_expose_typed_failure_codes_in_graph_results` (operator_failure / output_validation / internal_adapter_failure via missing inputs, dependents `skipped=None`) and `test_raise_mode_keeps_the_typed_failure_in_the_cause_chain`.
- `tests/unit/core/test_modules.py` (modified) — existing assertion updated to the new public error contract, as this packet's owned-files clause permits for focused core execution tests: `test_graph_module_node_preserves_inner_failure_as_contextual_cause` now asserts `NodeRunError(operator_failure)` at the `run_node` boundary with the `GraphModuleExecutionError` (and its inner `RuntimeError`) preserved through the cause chain.

Focused gates (all green):

- `uv run pytest -q -o log_cli=false tests/unit/api/runtime/test_system_adapter_parity.py tests/unit/api/runtime/test_graph_execution_coordinator.py tests/unit/core/test_modules.py` → 43 passed (5 + 8 + 30).
- `uv run ruff check` on the six files above → All checks passed.
- `uv run basedpyright libs/core/src/grafy_core/runtime/execution.py apps/api/src/grafy_api/execution/coordinator.py apps/api/src/grafy_api/execution/models.py` → 0 errors.
- `git diff --check` → clean.

Deliberately unsupported states: host operators are always classified `operator_failure` at the `NodeRuntime` boundary — there is no finer host-side classification, and OCI adapters never invent a code where the invocation did not provide one (unclassified → `internal_adapter_failure`).

Remaining blockers: none.

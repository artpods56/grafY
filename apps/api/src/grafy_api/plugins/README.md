# Plugin publication ownership

This package owns the API application's Plugin publication adapters and shared
runtime profiles. Immutable releases, installations, and selections remain owned
by `grafy_core`; database implementations remain in `grafy_persistence`.

| Module | Responsibility |
| --- | --- |
| `profiles.py` | Deployment-owned image pins, capabilities, and resource limits shared by publication and execution. |
| `publication/authoring.py` | Working-copy scaffolding, reservations, review diffs, and review fences. |
| `publication/source.py` | Source validation, deterministic archives, inspection, and verified candidates. |
| `publication/sandbox.py` | Docker-isolated source inspection. |
| `publication/oci.py` | Build and store immutable OCI images from verified candidates. |
| `publication/workflow.py` | Coordinate publication and revocation with release services and System inventory. |

Import the owning module directly. Keep package initializers free of re-exports
so importing a runtime profile does not import publication workflows or image
builders. Execution and admission consume `profiles.py`; they do not need an
OCI builder to read deployment limits.

The `grafy` CLI remains in `grafy_api.cli`. Runtime execution adapters, egress,
admission, and System deployment keep their existing owners. Package grouping
does not change the isolation policy in ADR 0007 or publication authority in
ADR 0006.

Run the API and client regression checks from the repository root:

```sh
uv run --all-extras pytest -q -o log_cli=false tests/unit/api tests/unit/client tests/integration/catalog tests/integration/executions/test_routes.py
```

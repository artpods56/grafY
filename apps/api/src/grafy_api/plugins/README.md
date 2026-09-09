# Plugin application ownership

This package owns application Plugin publication and runtime hosting. Immutable
release facts remain in `grafy_core`; database implementations remain in
`grafy_persistence`.

| Module | Responsibility |
| --- | --- |
| `profiles.py` | Image pins, capabilities, and resource limits shared by publication and execution. |
| `publication/authoring.py` | Working-copy scaffolding, reservations, review diffs, and review fences. |
| `publication/source.py` | Source validation, deterministic archives, inspection, and verified candidates. |
| `publication/sandbox.py` | Docker-isolated source inspection. |
| `publication/oci.py` | Build and store immutable OCI images from verified candidates. |
| `publication/workflow.py` | Coordinate verified publication and System promotion. |
| `runtime/admission.py` | Decide whether an exact release can execute under deployment policy. |
| `runtime/artifacts.py` | Stage invocation artifacts and exchange requests and results with guests. |
| `runtime/docker.py` | Run isolated Plugin containers and enforce their runtime limits. |
| `runtime/sandbox.py` | Track sandbox scopes and their cleanup lifecycle. |
| `runtime/egress.py` | Coordinate the egress broker with Plugin sandboxes. |
| `runtime/network_policy.py` | Validate and resolve deployment network-access profiles. |

Import the owning module directly. Package initializers do not re-export runtime
classes or publication tools. Runtime profiles can be imported without loading an
OCI builder. Plugin hosting does not import the graph execution engine.

The `grafy` CLI remains in `grafy_api.cli`. It calls the core release service for
System revocation. The broker executable belongs to `apps/plugin-egress-broker`;
API runtime hosting exchanges versioned policy and readiness messages with its
container. Historical host-deployment tools belong to `plugins/compatibility`,
with explicit aliases for their old public imports. Their commands and supported
historical policies remain available.

Run API and client regression checks from the repository root:

```sh
uv run --all-extras pytest -q -o log_cli=false tests/unit/api tests/unit/client tests/integration/catalog tests/integration/executions/test_routes.py
```

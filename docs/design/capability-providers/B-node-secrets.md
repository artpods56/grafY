# Node-scoped secrets on the execution context

Part of the capability-provider plan. After G. Independent of F.

## Problem

To read its own API key, a node calls `NodeSecretResolverPort.resolve_secret` and passes six things execution already knows. Workspace, Project, Graph and node ids, the secret name, and config dependencies. Every node that holds a key needs a constructor and a factory only to receive that port (`build_mistral_ocr_node`, `build_reducto_ocr_node`). A node could also pass another node's address by mistake.

## Design

```python
API_KEY = NodeSecretInput(
    name="api_key",
    title="API key",
    description="Your Mistral API key.",
    config_dependencies=(),
)

@MISTRAL.function_node(
    operator_id="...",
    version=1,
    title="...",
    secret_inputs=(API_KEY,),
)
async def some_node(
    context: NodeExecutionContext,
    config: SomeConfig,
    inputs: NoInput,
    /,
) -> SomeOutput:
    api_key = await context.secrets.require(API_KEY.name)
```

- `NodeExecutionContext.secrets` is a `NodeSecrets` with one method, `async require(name: str) -> SecretStr`.
- The runner in `apps/api/src/grafy_api/runs/node_runner.py` builds the context. It binds secrets to the executing node. That means the node's Workspace, Project, Graph and node ids, the registration's `secret_inputs`, and the config dependency values from the validated config.
- `require` with a name the node did not declare raises immediately. That is a programming error, not a user error.
- A missing secret raises the same user-facing error the nodes raise today, "could not resolve its API key".
- `function_node` gains `secret_inputs=`. Today only the class decorator has it.
- Deployment defaults in `apps/api/src/grafy_api/node_secrets.py` (`_deployment_default`) keep working through the same resolver underneath.

## Scope

- Core context type, runner binding, `function_node` parameter.
- Migrate the existing Mistral and Reducto nodes to `context.secrets.require`. Drop the resolver from their constructors and factories where nothing else needs it.
- Fingerprint secret revisions in `apps/api/src/grafy_api/runs/facts.py` stay as they are. They already come from the declared `secret_inputs`.

## Tests

- Two contexts for two nodes resolve each node's own stored secret.
- An undeclared name raises. A declared but unset name raises the user-facing error.
- A declared secret with `config_dependencies=("base_url",)` resolves using the config's `base_url`.
- Existing Mistral and Reducto tests pass. Their doubles move from a resolver argument to a context with `secrets`.

## Surfaces

No API or web change.
## ASSUMPTION

Choices the spec left open, each the smallest one consistent with it.

- The runner binds identity and declaration; the validated configuration arrives one
  step later, where the configuration is actually validated. `NodeRuntime.run_node`
  calls `bind_node_secret_config` on the context it was handed, so a secret's
  dependency values come from `model_dump(mode="json")` of the node's own validated
  config — the same reading `facts._effective_config` makes, which is why a document
  that omits a defaulted field resolves the same secret the fingerprint was taken
  under. `NodeExecutionContext.secrets` without that step holds no values, and a
  declared dependency it cannot supply raises `NodeSecretRequirementError` like any
  other misuse.
- `NodeExecutionContext.secrets` defaults to an unbound `NodeSecrets`: no Workspace, no
  declaration, no resolver. A context the runner never built — a preview, a materializer
  fallback, a test that calls a node directly — therefore refuses every name as the
  programming error it is, instead of reaching some ambient store.
- The user-facing sentence for a declared secret nobody has set is
  `Node '<id>' could not resolve its <title>`, which for these three declarations reads
  `... could not resolve its API key`. The node bodies no longer wrap `require`, so the
  node's own error class no longer covers a missing credential.
- `function_node` gains `secret_inputs=` and forwards it to the same registration the
  class decorator writes; the class decorator's parameter stays as it was.
- Deployment defaults needed no change: `require` calls the same
  `NodeSecretResolverPort` the nodes called directly, so `NodeSecretService` still
  answers from `_deployment_default` for the operators it knows.

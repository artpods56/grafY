# Service outputs and interface-typed inputs

Part of the capability-provider plan. After G. Independent of F.

G's startup pass skips a port whose class is a service contract. This issue adds that kind of port. It does not add `InPort` or `OutPort`.

## Problem

Every node output today is an artifact. It is written, keyed by fingerprint, and reused by a later Run with the same fingerprint. A provider's output is a live object, a reader holding config and a credential. It must never be stored, and it must be built from the provider node the edge actually points at.

The planner in `libs/core/src/grafy_core/kernel/planning.py` walks upstream from the targets and stops at an instance whose fingerprint already has a stored result. Everything stale becomes its own computation. A provider has no stored result, so under today's rules it would be stale forever, scheduled on its own, with nowhere to put the object.

## Contract and implementation

```python
@service_contract("ocr.reader", version=1, title="OCR service")
class OcrReader(Protocol):
    async def read(self, document: RasterImage | PdfFile) -> OcrResult: ...


class MistralReader(OcrReader):
    def __init__(self, *, config: MistralOcrConfig, api_key: SecretStr) -> None: ...
    async def read(self, document): ...
```

`service_contract` records an id, version and title on the Protocol. The plugin that defines it registers the contract in the catalog the way it registers an artifact type.

A class implements a contract only by subclassing it. A method named `read` is not enough.

## Ports

```python
class MistralProviderOutput(NodeOutput):
    reader: MistralReader


class OcrInput(NodeInput):
    document: RasterImage | PdfFile
    reader: OcrReader
```

Derivation from G treats a class that subclasses at least one service contract as a service output. The port produces every contract that class subclasses. A field typed as the Protocol itself is a service input. It accepts that contract.

v1 restrictions, checked at registration. A node with a service output has no input ports. A service port is `ONE`-shaped, not variadic, not instance plugs. A service output feeds only service inputs, and the reverse.

## Execution

The planner never plans a service node. When the walk reaches one it stops. No store lookup, no computation. The provider's fingerprint still enters the consumer's fingerprint through `upstream_fingerprints`. Changing the provider, its config or its key makes the consumer stale.

The consumer's computation builds the object. Before invoking the consumer, the runner runs each connected service node in-process, with that node's config and a context bound to that node's address, so `context.secrets` reads the provider's key. It passes the returned object into the consumer. Built once per consumer computation. A MAP consumer shares it across items.

Two identical provider nodes that share a fingerprint still each supply their own credentials, because the object is built from the connected instance.

The object is never stored, never part of `metadata`, never logged. The consumer's output metadata records the provider's operator id, version and config, with no secrets.

If the consumer's result is already in the store, the service node is not run.

A failure while building the object fails the consumer's computation and names the provider node.

The provider node does not go through `NodeRuntime.run_node`. That path ends in the output persister, which would look for a writer and fail. The consumer's runner validates the provider's config, builds its context, calls `node.run`, and takes the service field from the returned output.

`InputMaterializer` gains a third case beside "pass the ref through" and "resolve the ref". A service port receives the object the runner built and passes it on. It skips the artifact-type check.

v1 has no open or close lifecycle. A reader opens its client inside `read()`.

## State and Run validation

A service node never has a result. Its instance state must not show "stale" or "never run". It shows its own condition, such as a missing required secret, or nothing. Pick the state from the existing machine in `kernel/state.py`. Do not invent a parallel one.

An unfed service input is the existing "every plug must be fed" refusal.

A Run that targets a service node directly is refused with a message that says there is nothing to compute.

## Catalog

Service contracts appear with id, version and title.

Port specs carry a kind, `artifact` or `service`, and the contract keys they accept or produce. The web matches connections on those keys.

Adding `kind` changes `PortResponse`. That is an OpenAPI change. Regenerate with `npm run generate:api` from `apps/web`, and keep `npm run check:api` clean after regeneration. Do this in C, not in G. G forbids an OpenAPI diff.

## Scope

Core contract declaration, port derivation, planner rule, runner construction, metadata record, catalog and API models, regenerated web types. No OCR code. Tests use a fake contract and two fake providers.

## Tests

- A provider output produces every contract its class subclasses. A consumer input accepts its contract. A non-subclass with the same method does not satisfy it. The v1 restrictions raise at registration.
- A service node is never in `RunPlan.computations`. Changing its config changes the consumer's fingerprint.
- Two identical fake providers with different secrets feed two consumers. Each consumer sees its own secret.
- A fresh consumer does not run its provider.
- Consumer metadata contains the provider record and no secret value.
- An unfed service plug is refused.

## Docs

`CONTEXT.md` entries for "service contract" and "service port". A short ADR for "service outputs are execution-local and never planned".

An agent tool never offers a service input to the model. That is the same outcome as `agent_default="hidden"`, applied to every service input, not a per-port option.

## ASSUMPTIONS

- A service node with no in-flight or failed condition is omitted from instance-state listings rather than reported with a null state.
- An empty Run target list skips service operators among the root instances. When that leaves no targets, the Run is refused with `nothing_to_compute`. An explicit target that names a service node is refused the same way. A tool call that names a service node is refused too.

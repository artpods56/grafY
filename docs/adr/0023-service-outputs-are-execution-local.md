# ADR 0023: Service outputs are execution-local and never planned

- **Status:** Accepted
- **Amends:** ADR 0020 (a node may produce a live object with no stored result)
- **Related:** `docs/design/capability-providers/C-service-outputs.md`,
  `CONTEXT.md` (service contract, service port)

## Context

Every node output was an artifact: written under a fingerprint and reused by a
later Run. A provider that hands a live reader (config plus a credential) to a
consumer cannot store that object. Under the ADR 0020 planner rules a provider
with no stored result would stay stale forever and be scheduled on its own.

## Decision

A **service contract** is a nominal protocol a plugin registers. A class
implements it only by subclassing it. A **service port** carries contract keys,
not an artifact type.

The planner never plans a service node. Its fingerprint still enters each
consumer through `upstream_fingerprints`. When a consumer computation runs, the
runner builds each connected provider in-process, with that node's config and a
context bound to that node's address, and passes the object in. The object is
never stored, never logged, and never part of metadata. The consumer's metadata
may record the provider's operator id, version and public config.

A Run that targets a service node is refused: there is nothing to compute. A
service node's derived state is not stale and not never-run; with nothing in
flight and no failure it shows no instance state.

## Consequences

- Agent tools never offer a service input to the model.
- Catalog `PortResponse` carries `kind` (`artifact` or `service`) and the
  contract keys a service port accepts or produces.
- Two providers that share a fingerprint still each supply their own credentials,
  because the object is built from the connected instance.

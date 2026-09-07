# Slice 4: OCI image and Docker runtime

- **Status:** Complete
- **Updated:** 2026-08-24
- **Depends on:** [Slice 1](01-source-freeze-and-convention.md) and
  [Slice 3](03-artifact-invocation-protocol.md)
- **Outcome:** Publication stores an immutable OCI runtime artifact and the
  provider-neutral Plugin invocation port executes it through a hardened local
  Docker adapter scoped to one top-level graph execution

## Why this slice exists

Workspace Plugin code must not run inside FastAPI, and graph execution must not
install dependencies or use the network. Publication therefore needs to build
the complete runtime artifact in advance, while graph execution needs a narrow
adapter that can start, invoke, cancel, and destroy isolated local sandboxes.

Docker is the first adapter for the single-VPS deployment. Docker container
identities and command flags are infrastructure details, not graph or Plugin
domain concepts.

## Scope

- Deployment-owned default runtime profile pinned to an OCI base digest.
- Reproducible runtime image construction from the frozen source snapshot.
- Local storage and restoration of the immutable OCI runtime artifact.
- Docker implementation of the `PluginInvoker` port.
- Explicit `PluginSandboxScopeId` shared by nested Module execution.
- One sandbox per `(scope, exact Plugin release)`.
- Fresh Python child process and scratch directory per scalar invocation.
- Runtime cancellation, timeout, resource limits, and orphan cleanup.
- Local performance measurements and operational diagnostics.

## Non-goals

- Kubernetes, remote workers, or multiple API owners.
- Podman/containerd implementations.
- Cross-execution warm pools or global prewarming.
- Plugin-authored Dockerfiles.
- Runtime package installation or image pulls.
- Secrets, object-store credentials, or outbound network.
- Hard isolation for hostile public multi-tenancy.

## Fixed decisions

Image construction and image execution are separate boundaries:

```text
publish:
  frozen source + approved profile → immutable OCI image

run:
  exact image digest + invocation bundles → offline child process
```

The runtime artifact reference may identify an OCI image and storage blob, but
core invocation contracts do not contain Docker container IDs, mount flags, or
CLI arguments.

The sandbox key is:

```text
(PluginSandboxScopeId, Plugin release identity)
```

`PluginSandboxScopeId` is created once for a top-level graph execution and is
propagated into nested Modules. It is not `workflow_run_id`, because the current
inline engine creates a new workflow runner for nested Module entry.

Container reuse is limited to one top-level execution and one exact release.
Each scalar invocation still starts a fresh `.venv/bin/python -I` child with a
new invocation directory and `TMPDIR`.

The reusable container is the isolation boundary for one exact Plugin release
within one top-level execution. Docker cannot add a new bind mount to an
existing container during `exec`, so invocation bundles are streamed into
unique mode-restricted directories on a bounded scope/release tmpfs instead of
being mounted one at a time. Concurrent children of the same exact release may
observe that shared sandbox namespace; they never share it with another
release, Workspace execution scope, the API filesystem, or the host. This is
an accepted trust-boundary correction to the original mount-only wording, not
hostile-code isolation between invocations of the same Plugin release.

## Expected ownership

- Runtime profile configuration at the API/infrastructure composition boundary
- OCI image builder as a publication adapter
- Runtime artifact storage through the existing object-store boundary
- Docker `PluginInvoker` adapter in API infrastructure, not core
- Sandbox-scope propagation near `RunGraph` execution control
- Sandbox lifecycle owner composed once for the single API process

Do not create a generalized container-management framework. Add only the
operations required by image publication and Plugin invocation.

## Implementation checklist

### Runtime profile and image construction

- [x] Define one deployment-owned runtime profile with a pinned base image
      digest, supported Python version, Plugin protocol version, and default
      resource ceilings.
- [x] Reject unknown profile names rather than treating them as arbitrary image
      references.
- [x] Build from the exact frozen source archive produced by Slice 1.
- [x] Install only locked dependencies from approved package sources during
      publication.
- [x] Include the fixed guest entrypoint, Plugin source, and ready-to-run
      virtual environment in the final image.
- [x] Run the final image as a non-root user.
- [x] Label the image with source, contract, profile, base-image, and protocol
      digests for diagnostics.
- [x] Compute and record an immutable OCI manifest digest.
- [x] Export the OCI image/layout into durable local object storage so Docker's
      cache is not the only release copy.
- [x] Record a provider-neutral runtime artifact reference on the immutable
      Plugin release descriptor.

### Catalog-only release transition

- [x] Decide how existing source-only releases remain addressable but
      permanently non-runnable.
- [x] Make the first image-backed publish create an immutable image-backed
      release rather than mutating an existing source-only release.
- [x] Change publication idempotency to compare the complete release descriptor
      inputs, not source digest alone, once image artifacts participate.
- [x] Ensure identical source, contract, profile, capability, and image inputs
      remain idempotent.
- [x] Ensure a changed base/profile/image produces a distinct release even when
      source bytes are unchanged.

### Sandbox scope

- [x] Introduce a typed `PluginSandboxScopeId` distinct from provider workflow
      IDs and graph/module definition paths.
- [x] Create the scope once at top-level `RunGraph` entry.
- [x] Propagate the scope through nested Modules using the existing execution-
      control context pattern or an equally explicit owner.
- [x] Reset scope context in `finally` so concurrent executions cannot leak it.
- [x] Key sandbox lookup by scope and exact Plugin release.
- [x] Test nested and mapped child tasks using the same top-level scope.

### Docker invocation adapter

- [x] Resolve only the image digest stored on the exact release.
- [x] Load a missing image from the frozen local OCI artifact; never pull or
      rebuild during graph execution.
- [x] Lazily create one container on first invocation for a scope/release pair.
- [x] Start a fresh isolated Python child for every scalar invocation.
- [x] Stream only the authorized invocation bundle into a unique
      mode-restricted input/output/scratch directory on the bounded
      scope/release tmpfs.
- [x] Use unique invocation paths and `TMPDIR` values under concurrent MAP.
- [x] Pass the typed manifest as data without shell interpolation.
- [x] Bound and capture stdout/stderr separately from the result manifest.
- [x] Return typed protocol failures with execution, node, invocation, and
      release context.
- [x] Destroy a sandbox instead of reusing it after uncertain child cleanup,
      protocol corruption, timeout escalation, or resource exhaustion.

### Runtime hardening

- [x] Use `--pull=never`, `--network none`, a read-only root filesystem, and a
      non-root user.
- [x] Drop all Linux capabilities and enable `no-new-privileges`.
- [x] Apply an approved seccomp policy and expose no devices or privileged mode.
- [x] Enforce CPU, memory, PID, wall-time, open-file, log, input, output, and
      scratch limits. Set `--memory-swap` equal to `--memory` for publisher,
      guest, and egress-broker containers so the configured memory ceiling is
      also the total physical-memory-plus-swap ceiling on Linux hosts.
- [x] Keep the Docker socket, API filesystem, database, object-store
      credentials, and working copy out of the Plugin container.
- [x] Put writable temporary data only in bounded scope/release tmpfs with
      unique invocation directories.
- [x] Document that local Docker protects against mistakes and ordinary unsafe
      code but is not a hostile-public-tenant kernel boundary.

### Lifecycle, cancellation, and operations

- [x] Destroy all scope-owned containers in a top-level execution `finally`
      path.
- [x] Stop a release sandbox after its last known use (the terminal top-level
      scope path) or evict it when global
      capacity requires room.
- [x] On cancellation, terminate the child and escalate to container
      destruction if it does not stop promptly.
- [x] Label containers with Grafy scope, release, and creation metadata.
- [x] Remove orphaned Grafy containers and scratch directories during startup
      recovery.
- [x] Remove unreferenced Docker cache images by comparing image labels with
      runtime artifacts referenced by retained release rows. Keep durable OCI
      blobs while their append-only releases are retained; failed-publication
      blob GC remains deferred until storage listing and cleanup coordination
      have an explicit owner.
- [x] Document the Docker-socket authority risk for the chosen deployment.
- [x] Keep open the deployment option of a narrow same-VPS local runner without
      changing the invocation port.

## Verification checklist

- [x] Two builds from the same source, profile, and dependency inputs produce
      the intended stable release identity or document any unavoidable OCI
      byte variance separately from semantic release identity.
- [x] Runtime starts with Docker network disabled and cannot reach a test
      endpoint.
- [x] Runtime cannot read a sentinel host file, working copy, or Docker socket.
- [x] Runtime uses no `uv`, package installation, image pull, or external
      network during graph execution.
- [x] Repeated nodes from one release reuse a container only within one scope.
- [x] Two releases in one graph receive separate containers.
- [x] Two concurrent graph executions receive distinct typed scopes; the
      runtime's container key and host scratch root both include that scope.
- [x] Concurrent MAP children use distinct processes and invocation paths.
- [x] Nested Modules reuse the top-level sandbox scope.
- [x] Cancellation and timeout leave no running child or orphaned container.
- [x] Missing Docker cache is restored from the frozen local OCI artifact.
- [x] The CPU ceiling is present on the live container; its memory and total
      memory-plus-swap ceilings are equal; and memory, PID, output, and log
      limit outcomes are deterministic.
- [x] Cold container and child-process invocation latency are measured on a
      representative deployment-sized Linux VM and recorded under Agent
      handoff. The production VPS should rerun the same test before rollout.
- [x] Core models and compiler code contain no Docker-specific types.

## Exit criteria

- [x] Every executable Plugin release has one immutable local OCI runtime
      artifact.
- [x] `PluginInvoker` has a working Docker adapter without changing protocol
      semantics.
- [x] Sandbox lifetime follows top-level execution scope across Modules.
- [x] Runtime is offline, bounded, non-root, and cleans up on every terminal
      path.
- [x] Existing source-only releases remain safely non-runnable.
- [x] Catalog nodes remained fail-closed until Slice 5 added derived readiness
      for complete supported artifact contracts.

## Agent handoff

- **Owner:** Codex
- **Branch or PR:** —
- **Implementation evidence:** `plugins/profiles.py` owns the pinned `python-uv`
  build profile; `plugins/publication/oci.py` owns the content-addressed OCI
  archive; `plugin_docker.py` owns the
  local Docker lifecycle; `plugin_sandbox.py` and `RunGraph` own typed scope
  propagation; migration `0017_plugin_runtime_artifact.py` and the release
  descriptor persist immutable runtime artifacts. Production uses the pinned
  Docker CLI in `infra/docker/api.Dockerfile` and the explicit
  `compose.plugin-runtime.yaml` socket-authority override.
- **Verification evidence:** 13 release/profile/persistence unit tests, 16
  artifact-boundary tests, 3 scope/nested/cancellation tests, migration/schema
  verification, production API image build plus Docker/buildx smoke, Compose
  rendering, and the real Docker integration in
  `test_workspace_plugin_docker.py`. The integration builds the OCI archive
  twice, deletes Docker's cache, restores it from object storage, runs ordinary
  and Table invocations across two exact releases, inspects sandbox hardening,
  proves host/network/socket isolation, and checks cache reuse and
  reference-aware cache eviction. Its test-only probe also runs concurrent
  children and proves distinct PID/TMPDIR identity; injects PID, output, timeout,
  cancellation, log, and memory outcomes; and leaves no Grafy container or
  invocation scratch directory.
- **VPS benchmark evidence:** Colima Linux VM (`linux/arm64`, Ubuntu kernel
  `6.8.0-64-generic`, Docker server `28.4.0`, overlayfs), 4 vCPU and
  8,304,754,688 bytes RAM, 2026-08-24: cold cache-restore/container/child
  invocation `3.287s`; warm child invocation `1.582s`. The complete Docker
  integration passed in `34.15s`. This is representative deployment evidence,
  not a claim about the eventual production VPS.
- **Open decisions or blockers:** None for this slice. Durable OCI blobs remain
  retained with append-only releases; safe failed-publication blob GC is
  deferred until storage listing and cleanup coordination have an explicit
  owner. Same-release invocations share the bounded sandbox tmpfs namespace as
  documented above.

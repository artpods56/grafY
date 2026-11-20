"""Compute one node instance from the results its upstream instances stored.

The scheduler hands over a ``ComputationRequest``: the fingerprint to store under,
the expanded instance to compute, and the fingerprint of every upstream instance
this one reads from. Artifact upstreams are read from the Workspace-bound result
store. A service upstream is not stored: the runner builds that object from the
connected provider instance, with that instance's config and a context bound to
its address, and passes the object into the consumer. The object is built once
for the computation. The runner never writes the store: the scheduler appends
the returned outputs under the fingerprint it asked for (ADR 0020).

One call is independent of every other: the runner holds no state a computation
can disturb, so a scheduler may run any number of them concurrently.
"""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from typing import cast
from uuid import UUID

from pydantic import SecretStr, ValidationError

from grafy_core.artifacts import JsonObject
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.project import GRAPH_BOUNDARY_PORT
from grafy_core.kernel.results import ResultStore
from grafy_core.kernel.scheduler import ComputationRequest, ComputationRunner
from grafy_core.nodes import (
    NodeExecutionContext,
    NodeProgressReporter,
    UserFacingNodeError,
    bind_node_secret_config,
    bind_node_secrets,
)
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.node_secrets import NodeSecretResolverPort
from grafy_core.runtime.artifact_values import ArtifactValues
from grafy_core.runtime.execution import NodeRuntime

from grafy_api.runs.contract import (
    BoundNode,
    NodeContractBinder,
    ServiceFeed,
    is_boundary,
)
from grafy_api.runs.edge_values import EdgeValueResolver
from grafy_api.runs.errors import NodeComputationError
from grafy_api.runs.node_execution import NodeExecutionService


class NodeComputationRunner:
    """The kernel's ``ComputationRunner`` for one Project and one result store."""

    def __init__(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        store: ResultStore,
        binder: NodeContractBinder,
        edge_values: EdgeValueResolver,
        node_execution: NodeExecutionService,
        node_secrets: NodeSecretResolverPort,
        progress_reporter_factory: Callable[[], NodeProgressReporter] | None = None,
    ) -> None:
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._store = store
        self._binder = binder
        self._edge_values = edge_values
        self._node_execution = node_execution
        self._node_secrets = node_secrets
        self._progress_reporter_factory = progress_reporter_factory

    async def __call__(
        self,
        request: ComputationRequest,
    ) -> Mapping[str, ArtifactOutputValue]:
        instance = request.instance
        upstream = await self._read_upstream(request)
        context = NodeExecutionContext(
            workspace_id=self._workspace_id,
            project_id=self._project_id,
            graph_id=instance.key.graph_id,
            node_id=instance.key.node_id,
            call_path=instance.key.call_path,
            fingerprint=request.fingerprint,
            progress_reporter=(
                self._progress_reporter_factory()
                if self._progress_reporter_factory
                else None
            ),
        )
        if is_boundary(instance):
            # A Graph's own input or output is no operator: the one value that
            # reaches it is what the interface port carries. A projection or
            # conversion on that edge still writes, because the next graph
            # reads a stored ref.
            slot = self._binder.boundary_input(instance, upstream)
            value, transform = self._edge_values.describe(slot)
            if transform.rewrites:
                value = await self._edge_values.store(
                    value,
                    transform,
                    context,
                    port_name=slot.to_port,
                )
            return {GRAPH_BOUNDARY_PORT: value}

        unsupported = await self._unsupported_outputs(upstream)
        bound = self._binder.bind(
            instance,
            upstream,
            request.service_sources,
            unsupported,
        )
        # Secrets belong to the node that is about to run, so they are bound here,
        # once, to this Project's identity and to the operator's own declaration:
        # a node names a credential, it never names where one lives.
        context = bind_node_secrets(
            context,
            self._node_secrets,
            bound.registration.secret_inputs,
        )
        service_inputs, provider_records = await self._build_service_inputs(
            request,
            bound,
        )
        assembled = await self._edge_values.assemble_inputs(
            slots=bound.slots,
            ports=bound.ports,
            context=context,
        )
        inputs = dict(assembled.values)
        inputs.update(service_inputs)
        metadata: JsonObject | None = None
        if provider_records:
            # JsonObject values are ``object``; a list of records is one value.
            providers: object = list(provider_records)
            metadata = {"service_providers": providers}
        return await self._node_execution.execute(
            bound=bound,
            inputs=inputs,
            transforms=assembled.transforms,
            context=context,
            metadata=metadata,
        )

    async def _unsupported_outputs(
        self,
        upstream: Mapping[InstanceKey, Mapping[str, ArtifactOutputValue]],
    ) -> dict[InstanceKey, dict[str, str]]:
        """Read ``unsupported_outputs`` from any sibling artifact of each source.

        An optional OCR output the provider does not produce is omitted from the
        stored result and named in that metadata, so a downstream binder can say
        who left the port empty.
        """

        from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence

        found: dict[InstanceKey, dict[str, str]] = {}
        for key, outputs in upstream.items():
            for value in outputs.values():
                raw: object | None = None
                if isinstance(value, ArtifactRefSequence):
                    raw = value.metadata.get("unsupported_outputs")
                elif isinstance(value, ArtifactRef):
                    stored = await self._edge_values.values.open(
                        value, self._workspace_id
                    )
                    raw = stored.row.metadata.get("unsupported_outputs")
                if not isinstance(raw, dict):
                    continue
                mapping = {
                    str(port): str(provider)
                    for port, provider in raw.items()
                    if isinstance(port, str) and isinstance(provider, str)
                }
                if mapping:
                    found[key] = mapping
                    break
        return found

    async def _read_upstream(
        self, request: ComputationRequest
    ) -> dict[InstanceKey, Mapping[str, ArtifactOutputValue]]:
        instance = request.instance
        service_keys = set(request.service_sources)
        sources = sorted(
            {
                connection.source
                for connection in instance.connections
                if connection.source not in service_keys
            },
            key=lambda key: key.sort_key,
        )
        results = await asyncio.gather(
            *(self._stored_output(request, source) for source in sources)
        )
        return dict(zip(sources, results, strict=True))

    async def _stored_output(
        self,
        request: ComputationRequest,
        source: InstanceKey,
    ) -> Mapping[str, ArtifactOutputValue]:
        fingerprint = request.upstream_fingerprints.get(source)
        if fingerprint is None:
            raise NodeComputationError(
                f"Node {request.instance.key.node_id!r} is fed by an instance the "
                "computation was given no fingerprint for"
            )
        stored = await self._store.get_result(fingerprint)
        if stored is None:
            raise NodeComputationError(
                f"Node {request.instance.key.node_id!r} reads the result stored "
                f"under fingerprint {fingerprint}, which the result store does not "
                "hold"
            )
        return stored.outputs

    async def _build_service_inputs(
        self,
        request: ComputationRequest,
        bound: BoundNode,
    ) -> tuple[dict[str, object], list[JsonObject]]:
        """Build each connected service once, and the credential-free record of it.

        The provider does not go through ``NodeRuntime.run_node``. That path
        persists outputs, and a service output is not stored. The context is
        bound to the provider's address, so ``context.secrets`` reads the
        provider's key rather than the consumer's.
        """

        consumer_id = request.instance.key.node_id
        values: dict[str, object] = {}
        records: list[JsonObject] = []
        for feed in bound.service_feeds:
            value, record = await self._build_service(consumer_id, request, feed)
            values[feed.to_port] = value
            records.append(record)
        return values, records

    async def _build_service(
        self,
        consumer_id: str,
        request: ComputationRequest,
        feed: ServiceFeed,
    ) -> tuple[object, JsonObject]:
        source = feed.source
        provider_id = source.key.node_id
        node, registration = self._binder.build_node(source.node)
        try:
            validated_config = node.config_contract.model.model_validate(
                source.node.config_dict()
            )
            empty_inputs = node.input_contract.model.model_validate({})
        except ValidationError as exc:
            raise _service_build_error(consumer_id, provider_id, exc) from exc
        context = bind_node_secret_config(
            bind_node_secrets(
                NodeExecutionContext(
                    workspace_id=self._workspace_id,
                    project_id=self._project_id,
                    graph_id=source.key.graph_id,
                    node_id=source.key.node_id,
                    call_path=source.key.call_path,
                    fingerprint=request.upstream_fingerprints.get(source.key),
                ),
                self._node_secrets,
                registration.secret_inputs,
            ),
            validated_config,
        )
        try:
            produced = await node.run(context, validated_config, empty_inputs)
        except UserFacingNodeError as exc:
            raise NodeComputationError(
                f"Node {consumer_id!r} could not build the service from node "
                f"{provider_id!r}: {exc}"
            ) from exc
        except Exception as exc:
            raise _service_build_error(consumer_id, provider_id, exc) from exc
        try:
            validated_output = node.output_contract.model.model_validate(produced)
        except ValidationError as exc:
            raise _service_build_error(consumer_id, provider_id, exc) from exc
        return getattr(validated_output, feed.from_port), {
            "input": feed.to_port,
            "operator_id": node.operator_id,
            "operator_version": node.operator_version,
            "config": _public_config(source.node.config_dict()),
        }


def _service_build_error(
    consumer_id: str,
    provider_id: str,
    exc: Exception,
) -> NodeComputationError:
    """Name the provider without copying an exception that might carry a secret."""

    return NodeComputationError(
        f"Node {consumer_id!r} could not build the service from node "
        f"{provider_id!r} ({type(exc).__name__})"
    )


def _public_config(config: Mapping[str, object]) -> dict[str, object]:
    """The saved config, with any secret value removed.

    A node's secrets are not part of its config. This still drops a ``SecretStr``
    so a credential cannot ride into the consumer's output metadata.
    """

    redacted: dict[str, object] = {}
    for key, value in config.items():
        redacted[key] = _public_value(value)
    return redacted


def _public_value(value: object) -> object:
    if isinstance(value, SecretStr):
        return ""
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {str(key): _public_value(item) for key, item in mapping.items()}
    if isinstance(value, list):
        items = cast(list[object], value)
        return [_public_value(item) for item in items]
    return value


class NodeComputationRunnerFactory:
    """Builds the kernel ``ComputationRunner`` for one Project.

    The adapters are the same ones the rest of the workbench runs nodes with, and
    every ``for_project`` call returns a fresh runner over the caller's result
    store: nothing is shared between Projects and nothing a runner mutates
    outlives one computation.

    ``plugin_context`` is what an operator needing runtime services -- storage,
    a workbench workspace -- is built with; an operator that needs none is built
    from its class and the runner works without one. ``node_secrets`` is what a
    node reads its own credential through: the runner binds it to the executing
    node on that node's execution context, while the secret revisions that make a
    node stale enter its fingerprint outside the runner.
    """

    def __init__(
        self,
        *,
        registry: PluginRegistry,
        runtime: NodeRuntime,
        node_secrets: NodeSecretResolverPort,
        values: ArtifactValues,
        max_map_concurrency: int = 1,
        plugin_context: PluginRuntimeContext | None = None,
        progress_reporter_factory: Callable[[], NodeProgressReporter] | None = None,
    ) -> None:
        self._binder = NodeContractBinder(
            registry=registry,
            plugin_context=plugin_context,
        )
        self._edge_values = EdgeValueResolver(values=values)
        self._node_execution = NodeExecutionService(
            runtime=runtime,
            max_map_concurrency=max_map_concurrency,
        )
        self._node_secrets = node_secrets
        self._progress_reporter_factory = progress_reporter_factory

    def for_project(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        store: ResultStore,
    ) -> ComputationRunner:
        return NodeComputationRunner(
            workspace_id=workspace_id,
            project_id=project_id,
            store=store,
            binder=self._binder,
            edge_values=self._edge_values,
            node_execution=self._node_execution,
            node_secrets=self._node_secrets,
            progress_reporter_factory=self._progress_reporter_factory,
        )


__all__: Sequence[str] = ["NodeComputationRunner", "NodeComputationRunnerFactory"]

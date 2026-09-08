"""Execution semantics for one compiled logical node."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast
from uuid import UUID, uuid4

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
)
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.nodes import NodeExecutionContext
from grafy_core.plugins import NodeCachePolicy
from grafy_core.ports.node_secrets import NodeSecretResolverPort
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.invocation import InvocationError, InvocationMode
from grafy_core.runtime.plugin_invocation import PluginReleaseNode
from grafy_core.runtime.persistence import PersistedNodeOutput

from grafy_api.execution.control import RunExecutionControl
from grafy_api.execution.edge_values import EdgeValueResolver
from grafy_api.execution.models import (
    CompiledEdge,
    CompiledNode,
    PreparedGraphExecution,
)


class _MappedItemExecutionError(InvocationError):
    def __init__(
        self,
        *,
        operator_id: str,
        map_input: str,
        index: int,
        ref: ArtifactRef,
    ) -> None:
        self.index = index
        super().__init__(
            f"Node {operator_id!r} MAP input {map_input!r} failed at "
            f"item {index} ({ref.artifact_id})"
        )


class NodeExecutionService:
    """Resolve inputs and execute the ONCE or MAP semantics of one node."""

    def __init__(
        self,
        *,
        runtime: NodeRuntime,
        edge_values: EdgeValueResolver,
        node_secrets: NodeSecretResolverPort,
        max_map_concurrency: int = 1,
    ) -> None:
        if max_map_concurrency < 1:
            raise ValueError("MAP max concurrency must be at least one")
        self._runtime = runtime
        self._edge_values = edge_values
        self._node_secrets = node_secrets
        self._max_map_concurrency = max_map_concurrency

    async def execute(
        self,
        *,
        execution: PreparedGraphExecution,
        compiled_node: CompiledNode,
        incoming_edges: Sequence[CompiledEdge],
        outputs: Mapping[str, Mapping[str, ArtifactOutputValue]],
        workflow_run_id: UUID,
        node_run_id: UUID,
    ) -> dict[str, ArtifactOutputValue]:
        node_request = compiled_node.request
        inputs = await self._edge_values.assemble_inputs(
            compiled_node,
            incoming_edges,
            outputs,
            workflow_run_id,
            execution.workspace_id,
        )
        node_context = NodeExecutionContext(
            workflow_run_id=workflow_run_id,
            node_run_id=node_run_id,
            workspace_id=execution.workspace_id,
            graph_id=execution.graph_id,
            graph_revision=execution.graph_revision,
            secret_graph_id=(
                execution.secret_graph_id
                if node_request.id in execution.secret_node_ids
                else None
            ),
            secret_graph_revision=(
                execution.secret_graph_revision
                if node_request.id in execution.secret_node_ids
                else None
            ),
            node_id=node_request.id,
            invocation_path=execution.invocation_path,
            module_path=execution.module_path,
            node_path=(*execution.node_path, node_request.id),
            progress_reporter=execution.control,
        )
        registration = compiled_node.registration
        # Both routes retain the exact release contract's cache semantics. The
        # in-process route has additionally matched the loaded registration.
        if registration is not None:
            cache_policy = registration.cache_policy
        elif isinstance(compiled_node.node, PluginReleaseNode):
            cache_policy = compiled_node.node.cache_policy
        else:
            cache_policy = NodeCachePolicy.NEVER
        opaque_secret_revisions: dict[str, str] = {}
        if (
            cache_policy is NodeCachePolicy.EXACT
            and registration is not None
            and registration.secret_inputs
        ):
            secret_inputs = registration.secret_inputs
            effective_config = (
                registration.node_class.config_contract.model.model_validate(
                    node_request.config
                ).model_dump(mode="json")
            )
        elif (
            cache_policy is NodeCachePolicy.EXACT
            and isinstance(compiled_node.node, PluginReleaseNode)
            and compiled_node.node.contract.secret_inputs
        ):
            secret_inputs = compiled_node.node.contract.secret_inputs
            effective_config = node_request.config
        else:
            secret_inputs = ()
            effective_config = {}
        for secret_input in secret_inputs:
            missing_dependencies = sorted(
                set(secret_input.config_dependencies) - set(effective_config)
            )
            if missing_dependencies:
                raise InvocationError(
                    f"Node {node_request.id!r} cache identity cannot resolve "
                    f"secret {secret_input.name!r} dependencies: "
                    + ", ".join(missing_dependencies)
                )
            secret_dependencies = {
                dependency: cast(JsonValue, effective_config[dependency])
                for dependency in secret_input.config_dependencies
            }
            opaque_secret_revisions[
                secret_input.name
            ] = await self._node_secrets.cache_revision(
                workspace_id=node_context.workspace_id,
                graph_id=node_context.secret_graph_id,
                graph_revision=node_context.secret_graph_revision,
                node_id=node_context.node_id,
                name=secret_input.name,
                dependencies=secret_dependencies,
            )

        if compiled_node.invocation.mode is InvocationMode.MAP:
            result = await self._run_mapped(
                compiled_node=compiled_node,
                context=node_context,
                inputs=inputs,
                cache_policy=cache_policy,
                opaque_secret_revisions=opaque_secret_revisions,
                control=execution.control,
            )
        else:
            result = await self._runtime.run_node(
                compiled_node.node,
                node_context,
                inputs,
                config=node_request.config,
                artifact_type_bindings=compiled_node.artifact_type_bindings,
                cache_policy=cache_policy,
                opaque_secret_revisions=opaque_secret_revisions,
                plugin_release=compiled_node.plugin_release,
                implementation=compiled_node.implementation,
            )

        node_outputs: dict[str, ArtifactOutputValue] = {}
        if isinstance(result, PersistedNodeOutput):
            for name in compiled_node.resolved_contracts.output_contract.ports:
                value = result.values.get(name)
                if isinstance(value, ArtifactRef | ArtifactRefSequence):
                    node_outputs[name] = value
        return node_outputs

    async def _run_mapped(
        self,
        *,
        compiled_node: CompiledNode,
        context: NodeExecutionContext,
        inputs: Mapping[str, object],
        cache_policy: NodeCachePolicy,
        opaque_secret_revisions: Mapping[str, str],
        control: RunExecutionControl | None,
    ) -> PersistedNodeOutput:
        node = compiled_node.node
        invocation = compiled_node.invocation
        map_input = invocation.map_input
        if map_input is None:
            raise InvocationError(
                f"Node {node.operator_id!r} MAP invocation requires a map_input"
            )
        raw_sequence = inputs.get(map_input)
        if not isinstance(raw_sequence, ArtifactRefSequence):
            raise InvocationError(
                f"Node {node.operator_id!r} MAP input {map_input!r} expected an "
                f"ArtifactRefSequence, got {type(raw_sequence).__name__}"
            )
        if not raw_sequence.item_refs:
            raise InvocationError(
                f"Node {node.operator_id!r} MAP input {map_input!r} must not be empty"
            )

        input_port = compiled_node.resolved_contracts.input_contract.ports[map_input]
        if not isinstance(input_port.accepts, ArtifactTypeKey):
            raise InvocationError(
                f"Node {node.operator_id!r} MAP input {map_input!r} has an "
                "unresolved artifact type contract"
            )
        sequence_key = ArtifactTypeKey(
            raw_sequence.artifact_type,
            raw_sequence.schema_version,
        )
        if sequence_key != input_port.accepts:
            raise InvocationError(
                f"Node {node.operator_id!r} MAP input {map_input!r} expected "
                f"{input_port.accepts.id}@{input_port.accepts.schema_version}, got "
                f"{sequence_key.id}@{sequence_key.schema_version}"
            )

        output_contract = compiled_node.resolved_contracts.output_contract
        refs_by_output: dict[str, list[ArtifactRef]] = {
            name: [] for name in output_contract.ports
        }
        limiter = asyncio.Semaphore(self._max_map_concurrency)
        item_tasks: list[asyncio.Task[PersistedNodeOutput]] = []
        try:
            async with asyncio.TaskGroup() as task_group:
                for index, ref in enumerate(raw_sequence.item_refs):
                    item_tasks.append(
                        task_group.create_task(
                            self._run_mapped_item(
                                compiled_node=compiled_node,
                                context=context,
                                inputs=inputs,
                                map_input=map_input,
                                index=index,
                                ref=ref,
                                cache_policy=cache_policy,
                                opaque_secret_revisions=opaque_secret_revisions,
                                control=control,
                                limiter=limiter,
                            ),
                            name=f"grafy-map-{compiled_node.request.id}-{index}",
                        )
                    )
        except* _MappedItemExecutionError as errors:
            failures = [
                error
                for error in errors.exceptions
                if isinstance(error, _MappedItemExecutionError)
            ]
            if not failures:
                raise
            failure = min(failures, key=lambda error: error.index)
            raise InvocationError(str(failure)) from failure.__cause__

        cache_hits = 0
        cache_misses = 0
        for index, item_task in enumerate(item_tasks):
            item_result = item_task.result()
            cache_hits += item_result.cache_hits
            cache_misses += item_result.cache_misses
            for name in output_contract.ports:
                value = item_result.values.get(name)
                if not isinstance(value, ArtifactRef):
                    raise InvocationError(
                        f"Node {node.operator_id!r} MAP output {name!r} at item "
                        f"{index} expected an ArtifactRef, got "
                        f"{type(value).__name__}"
                    )
                refs_by_output[name].append(value)

        values: dict[str, object] = {}
        for name, output_port in output_contract.ports.items():
            if not isinstance(output_port.produces, ArtifactTypeKey):
                raise InvocationError(
                    f"Node {node.operator_id!r} MAP output {name!r} has an "
                    "unresolved artifact type contract"
                )
            values[name] = ArtifactRefSequence(
                artifact_type=output_port.produces.id,
                schema_version=output_port.produces.schema_version,
                item_refs=refs_by_output[name],
                ordered=raw_sequence.ordered,
                index_key=raw_sequence.index_key,
                metadata={
                    "invocation_mode": InvocationMode.MAP.value,
                    "map_input": map_input,
                    "source_sequence_id": str(raw_sequence.sequence_id),
                },
            )
        return PersistedNodeOutput(
            values=values,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
        )

    async def _run_mapped_item(
        self,
        *,
        compiled_node: CompiledNode,
        context: NodeExecutionContext,
        inputs: Mapping[str, object],
        map_input: str,
        index: int,
        ref: ArtifactRef,
        cache_policy: NodeCachePolicy,
        opaque_secret_revisions: Mapping[str, str],
        control: RunExecutionControl | None,
        limiter: asyncio.Semaphore,
    ) -> PersistedNodeOutput:
        async with limiter:
            if control is not None:
                control.check_cancelled()
            item_inputs = dict(inputs)
            item_inputs[map_input] = ref
            item_context = replace(
                context,
                node_run_id=uuid4(),
                invocation_index=index,
                invocation_path=(*context.invocation_path, index),
            )

            try:
                return cast(
                    PersistedNodeOutput,
                    await self._runtime.run_node(
                        compiled_node.node,
                        item_context,
                        item_inputs,
                        config=compiled_node.request.config,
                        artifact_type_bindings=compiled_node.artifact_type_bindings,
                        cache_policy=cache_policy,
                        opaque_secret_revisions=opaque_secret_revisions,
                        plugin_release=compiled_node.plugin_release,
                        implementation=compiled_node.implementation,
                    ),
                )
            except Exception as exc:
                raise _MappedItemExecutionError(
                    operator_id=compiled_node.node.operator_id,
                    map_input=map_input,
                    index=index,
                    ref=ref,
                ) from exc


__all__ = ["NodeExecutionService"]

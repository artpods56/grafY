"""Execution semantics for one bound node: run it once, or once per item.

The connections that feed a node decide which: a connection in ``map`` collection
mode carries a sequence and the node runs once per item of it, every map-driven
input advancing together. Everything else about the node is already resolved by
the binder -- operator, contracts, artifact type bindings, input values -- and the
result is a plain ``port -> artifact`` mapping the scheduler stores under the
instance's fingerprint. Nothing here caches or remembers a result: reuse is the
result store's job (ADR 0020).
"""

import asyncio
import json
from collections.abc import Mapping
from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence, ArtifactTypeKey
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.nodes import NodeExecutionContext, PortShape
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.invocation import InvocationMode
from grafy_core.runtime.persistence import PersistedNodeOutput

from grafy_api.runs.contract import BoundNode
from grafy_api.runs.errors import NodeComputationError


class _MappedItemError(NodeComputationError):
    """One MAP item failed; the smallest index explains the computation."""

    def __init__(
        self,
        *,
        operator_id: str,
        mapped_refs: Mapping[str, ArtifactRef],
        index: int,
    ) -> None:
        self.index = index
        if len(mapped_refs) == 1:
            map_input, ref = next(iter(mapped_refs.items()))
            message = (
                f"Node {operator_id!r} MAP input {map_input!r} failed at "
                f"item {index} ({ref.artifact_id})"
            )
        else:
            refs = ", ".join(
                f"{name}={ref.artifact_id}" for name, ref in mapped_refs.items()
            )
            message = f"Node {operator_id!r} MAP inputs failed at item {index} ({refs})"
        super().__init__(message)


class NodeExecutionService:
    """Run the ONCE or MAP semantics of one node instance."""

    def __init__(
        self,
        *,
        runtime: NodeRuntime,
        max_map_concurrency: int = 1,
    ) -> None:
        if max_map_concurrency < 1:
            raise ValueError("MAP max concurrency must be at least one")
        self._runtime = runtime
        self._max_map_concurrency = max_map_concurrency

    async def execute(
        self,
        *,
        bound: BoundNode,
        inputs: Mapping[str, object],
        context: NodeExecutionContext,
    ) -> dict[str, ArtifactOutputValue]:
        if bound.invocation.mode is InvocationMode.MAP:
            return await self._run_mapped(bound=bound, inputs=inputs, context=context)
        result = await self._runtime.run_node(
            bound.node,
            context,
            inputs,
            config=bound.config,
            artifact_type_bindings=bound.artifact_type_bindings,
        )
        return _persisted_outputs(bound, result)

    async def _run_mapped(
        self,
        *,
        bound: BoundNode,
        inputs: Mapping[str, object],
        context: NodeExecutionContext,
    ) -> dict[str, ArtifactOutputValue]:
        node = bound.node
        map_inputs = bound.invocation.map_inputs
        contracts = bound.resolved_contracts
        output_contract = contracts.output_contract

        sequences: dict[str, ArtifactRefSequence] = {}
        for map_input in map_inputs:
            raw_sequence = inputs.get(map_input)
            if not isinstance(raw_sequence, ArtifactRefSequence):
                raise NodeComputationError(
                    f"Node {node.operator_id!r} MAP input {map_input!r} expected an "
                    f"ArtifactRefSequence, got {type(raw_sequence).__name__}"
                )
            if not raw_sequence.item_refs:
                raise NodeComputationError(
                    f"Node {node.operator_id!r} MAP input {map_input!r} must not be "
                    "empty"
                )
            input_port = contracts.input_contract.ports[map_input]
            accepted_types = input_port.accepted_types
            if not accepted_types:
                raise NodeComputationError(
                    f"Node {node.operator_id!r} MAP input {map_input!r} has an "
                    "unresolved artifact type contract"
                )
            sequence_key = ArtifactTypeKey(
                raw_sequence.artifact_type,
                raw_sequence.schema_version,
            )
            if sequence_key not in accepted_types:
                expected = ", ".join(
                    f"{key.id}@{key.schema_version}" for key in accepted_types
                )
                raise NodeComputationError(
                    f"Node {node.operator_id!r} MAP input {map_input!r} expected "
                    f"{expected}, got "
                    f"{sequence_key.id}@{sequence_key.schema_version}"
                )
            if len(map_inputs) > 1 and not raw_sequence.ordered:
                raise NodeComputationError(
                    f"Node {node.operator_id!r} MAP inputs cannot pair unordered "
                    f"sequence {map_input!r}"
                )
            sequences[map_input] = raw_sequence

        first_sequence = next(iter(sequences.values()))
        item_count = len(first_sequence.item_refs)
        if any(
            len(sequence.item_refs) != item_count for sequence in sequences.values()
        ):
            lengths = ", ".join(
                f"{name}={len(sequence.item_refs)}"
                for name, sequence in sequences.items()
            )
            raise NodeComputationError(
                f"Node {node.operator_id!r} MAP inputs have different lengths: "
                f"{lengths}"
            )

        refs_by_output: dict[str, list[ArtifactRef]] = {
            name: [] for name in output_contract.ports
        }
        limiter = asyncio.Semaphore(self._max_map_concurrency)

        async def run_item(index: int) -> PersistedNodeOutput:
            mapped_refs = {
                name: sequence.item_refs[index] for name, sequence in sequences.items()
            }
            async with limiter:
                item_inputs = dict(inputs)
                input_ports = contracts.input_contract.ports
                for name, ref in mapped_refs.items():
                    item_inputs[name] = (
                        _single_item_sequence(ref)
                        if input_ports[name].shape is PortShape.MANY
                        else ref
                    )
                item_context = replace(
                    context,
                    invocation_index=index,
                    invocation_path=(*context.invocation_path, index),
                )
                try:
                    result = await self._runtime.run_node(
                        bound.node,
                        item_context,
                        item_inputs,
                        config=bound.config,
                        artifact_type_bindings=bound.artifact_type_bindings,
                    )
                except Exception as exc:
                    raise _MappedItemError(
                        operator_id=node.operator_id,
                        mapped_refs=mapped_refs,
                        index=index,
                    ) from exc
            if not isinstance(result, PersistedNodeOutput):
                raise NodeComputationError(
                    f"Node {node.operator_id!r} MAP output at item {index} was not "
                    "persisted"
                )
            return result

        item_tasks: list[asyncio.Task[PersistedNodeOutput]] = []
        try:
            async with asyncio.TaskGroup() as task_group:
                for index in range(item_count):
                    item_tasks.append(
                        task_group.create_task(
                            run_item(index),
                            name=f"grafy-map-{context.node_id}-{index}",
                        )
                    )
        except* _MappedItemError as failures:
            failure = min(
                (
                    error
                    for error in failures.exceptions
                    if isinstance(error, _MappedItemError)
                ),
                key=lambda error: error.index,
            )
            raise NodeComputationError(str(failure)) from failure.__cause__

        for index, item_task in enumerate(item_tasks):
            item_result = item_task.result()
            for name in output_contract.ports:
                value = item_result.values.get(name)
                if not isinstance(value, ArtifactRef):
                    raise NodeComputationError(
                        f"Node {node.operator_id!r} MAP output {name!r} at item "
                        f"{index} expected an ArtifactRef, got "
                        f"{type(value).__name__}"
                    )
                refs_by_output[name].append(value)

        values: dict[str, ArtifactOutputValue] = {}
        for name, output_port in output_contract.ports.items():
            if not isinstance(output_port.produces, ArtifactTypeKey):
                raise NodeComputationError(
                    f"Node {node.operator_id!r} MAP output {name!r} has an "
                    "unresolved artifact type contract"
                )
            identity: dict[str, object] = {
                "node_id": context.node_id,
                "call_path": list(context.call_path),
                "output": name,
                "items": [str(ref.artifact_id) for ref in refs_by_output[name]],
            }
            metadata: dict[str, object] = {"invocation_mode": InvocationMode.MAP.value}
            if len(sequences) == 1:
                identity["source"] = str(first_sequence.sequence_id)
                metadata["map_input"] = next(iter(sequences))
                metadata["source_sequence_id"] = str(first_sequence.sequence_id)
            else:
                source_ids = [
                    str(sequence.sequence_id) for sequence in sequences.values()
                ]
                identity["sources"] = source_ids
                metadata["map_inputs"] = list(map_inputs)
                metadata["source_sequence_ids"] = source_ids
            values[name] = ArtifactRefSequence(
                sequence_id=uuid5(NAMESPACE_URL, _canonical(identity)),
                artifact_type=output_port.produces.id,
                schema_version=output_port.produces.schema_version,
                item_refs=refs_by_output[name],
                ordered=first_sequence.ordered,
                index_key=first_sequence.index_key,
                metadata=metadata,
            )
        return values


def _persisted_outputs(
    bound: BoundNode,
    result: PersistedNodeOutput | object,
) -> dict[str, ArtifactOutputValue]:
    if not isinstance(result, PersistedNodeOutput):
        return {}
    outputs: dict[str, ArtifactOutputValue] = {}
    for name in bound.resolved_contracts.output_contract.ports:
        value = result.values.get(name)
        if isinstance(value, ArtifactRef | ArtifactRefSequence):
            outputs[name] = value
    return outputs


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _single_item_sequence(ref: ArtifactRef) -> ArtifactRefSequence:
    """Hand one mapped item to a sequence input as a sequence of one."""
    identity = _canonical({"item": str(ref.artifact_id)})
    return ArtifactRefSequence(
        sequence_id=uuid5(NAMESPACE_URL, identity),
        artifact_type=ref.artifact_type,
        schema_version=ref.schema_version,
        item_refs=[ref],
    )


__all__ = ["NodeExecutionService"]

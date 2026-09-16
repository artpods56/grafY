from collections.abc import Mapping
from dataclasses import replace
from typing import Any, cast

from pydantic import BaseModel

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    JsonObject,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.invocation_cache import InvocationCacheEntry
from grafy_core.domain.implementation import ImplementationIdentity
from grafy_core.domain.plugin_releases import PluginReleaseIdentity
from grafy_core.nodes import (
    InputContract,
    Node,
    NodeExecutionContext,
    OutputContract,
    PortShape,
    UserFacingNodeError,
    resolve_node_contracts,
)
from grafy_core.plugins import NodeCachePolicy
from grafy_core.runtime.invocation_cache import (
    DisabledInvocationCache,
    InvocationCachePort,
    invocation_cache_key,
)
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import OutputPersister, PersistedNodeOutput
from grafy_core.runtime.plugin_invocation import PluginInvocationError
from grafy_core.runtime.plugin_protocol import PluginFailureCode


class NodeRunError(RuntimeError):
    """A node operator failed with stable execution context and classification."""

    def __init__(
        self,
        message: str,
        *,
        failure_code: PluginFailureCode,
    ) -> None:
        super().__init__(message)
        self.failure_code = failure_code


class NodeRuntime:
    def __init__(
        self,
        *,
        materializer: InputMaterializer,
        persister: OutputPersister,
        invocation_cache: InvocationCachePort | None = None,
    ) -> None:
        self._materializer = materializer
        self._persister = persister
        self._invocation_cache = invocation_cache or DisabledInvocationCache()

    async def run_node[
        ConfigT: NodeConfig,
        InputT: NodeInput,
        OutputT: NodeOutput,
    ](
        self,
        node: Node[ConfigT, InputT, OutputT],
        context: NodeExecutionContext,
        inputs: Mapping[str, object],
        config: JsonObject | None = None,
        artifact_type_bindings: Mapping[str, ArtifactTypeKey] | None = None,
        cache_policy: NodeCachePolicy = NodeCachePolicy.NEVER,
        opaque_secret_revisions: Mapping[str, str] | None = None,
        plugin_release: PluginReleaseIdentity | None = None,
        implementation: ImplementationIdentity | None = None,
    ) -> PersistedNodeOutput | BaseModel:
        effective_bindings = artifact_type_bindings or {}
        resolved_contracts = resolve_node_contracts(
            node,
            effective_bindings,
        )
        context = replace(
            context,
            artifact_type_bindings=effective_bindings,
        )
        raw_config: JsonObject = {} if config is None else config
        validated_config = node.config_contract.model.model_validate(raw_config)

        cache_key: str | None = None
        cache_misses = 0
        if cache_policy is NodeCachePolicy.EXACT:
            cache_misses = 1
            if _contract_supports_cache(resolved_contracts.output_contract):
                cache_key = invocation_cache_key(
                    node=node,
                    context=context,
                    inputs=inputs,
                    config=validated_config,
                    artifact_type_bindings=effective_bindings,
                    opaque_secret_revisions=opaque_secret_revisions or {},
                    implementation=implementation,
                )
            if cache_key is not None:
                cached_entry = await self._invocation_cache.get(
                    context.workspace_id,
                    cache_key,
                )
                if cached_entry is not None:
                    cached_values = _validated_cached_outputs(
                        resolved_contracts.output_contract,
                        cached_entry.outputs,
                    )
                    if cached_values is not None:
                        return PersistedNodeOutput(
                            values=cast(dict[str, object], cached_values),
                            cache_hits=1,
                        )
                    await self._invocation_cache.remove_if_current(
                        context.workspace_id,
                        cache_key,
                        cached_entry.generation,
                    )

        materialized_inputs, provenance = await self._materializer.materialize(
            contract=cast(InputContract[InputT], resolved_contracts.input_contract),
            inputs=inputs,
            workspace_id=context.workspace_id,
        )
        try:
            run_output = await node.run(
                context,
                cast(ConfigT, validated_config),
                materialized_inputs,
            )
        except PluginInvocationError as exc:
            failure_code = (
                exc.failure_code
                if exc.failure_code is not None
                else PluginFailureCode.INTERNAL_ADAPTER_FAILURE
            )
            public_context = f": {exc}" if exc.user_facing else ""
            raise NodeRunError(
                f"Node {context.node_id!r} operator {node.operator_id}@"
                f"{node.operator_version} failed ({failure_code.value})"
                f"{public_context}",
                failure_code=failure_code,
            ) from exc
        except UserFacingNodeError as exc:
            raise NodeRunError(
                f"Node {context.node_id!r} operator {node.operator_id}@"
                f"{node.operator_version} failed "
                f"({PluginFailureCode.OPERATOR_FAILURE.value}): {exc}",
                failure_code=PluginFailureCode.OPERATOR_FAILURE,
            ) from exc
        except Exception as exc:
            raise NodeRunError(
                f"Node {context.node_id!r} operator {node.operator_id}@"
                f"{node.operator_version} failed "
                f"({PluginFailureCode.OPERATOR_FAILURE.value})",
                failure_code=PluginFailureCode.OPERATOR_FAILURE,
            ) from exc
        persisted = await self._persister.persist(
            contract=resolved_contracts.output_contract,
            context=context,
            output=run_output,
            provenance=provenance,
            metadata=(
                {}
                if implementation is None
                else {"implementation": implementation.provenance_document()}
            ),
        )
        if not isinstance(persisted, PersistedNodeOutput):
            return persisted

        cache_outputs = _validated_persisted_outputs(
            resolved_contracts.output_contract,
            persisted,
        )
        if cache_key is not None and cache_outputs is not None:
            await self._invocation_cache.put_if_absent(
                InvocationCacheEntry(
                    workspace_id=context.workspace_id,
                    key_sha256=cache_key,
                    outputs=cache_outputs,
                )
            )
        return replace(persisted, cache_misses=cache_misses)


def _contract_supports_cache(contract: OutputContract[Any]) -> bool:
    return bool(contract.ports) and set(contract.model.model_fields) == set(
        contract.ports
    )


def _validated_persisted_outputs(
    contract: OutputContract[Any],
    persisted: PersistedNodeOutput,
) -> dict[str, ArtifactOutputValue] | None:
    outputs: dict[str, ArtifactOutputValue] = {}
    for name in contract.ports:
        value = persisted.values.get(name)
        if not isinstance(value, ArtifactRef | ArtifactRefSequence):
            return None
        outputs[name] = value
    return _validated_cached_outputs(contract, outputs)


def _validated_cached_outputs(
    contract: OutputContract[Any],
    outputs: Mapping[str, ArtifactOutputValue],
) -> dict[str, ArtifactOutputValue] | None:
    if not _contract_supports_cache(contract) or set(outputs) != set(contract.ports):
        return None
    validated: dict[str, ArtifactOutputValue] = {}
    for name, spec in contract.ports.items():
        if not isinstance(spec.produces, ArtifactTypeKey):
            return None
        value = outputs[name]
        if isinstance(value, ArtifactRef):
            if spec.shape is not PortShape.ONE or value.key() != spec.produces:
                return None
        elif (
            spec.shape is not PortShape.MANY
            or value.artifact_type != spec.produces.id
            or value.schema_version != spec.produces.schema_version
        ):
            return None
        validated[name] = value.model_copy(deep=True)
    return validated

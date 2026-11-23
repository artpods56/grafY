from collections.abc import Mapping, Sequence
from dataclasses import replace
from enum import StrEnum
from typing import cast

from pydantic import BaseModel

from grafy_core.artifacts import (
    ArtifactTypeKey,
    JsonObject,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.nodes import (
    InputContract,
    Node,
    NodeExecutionContext,
    OutputContract,
    UserFacingNodeError,
    bind_node_secret_config,
    resolve_node_contracts,
)
from grafy_core.runtime.edge_transform import EdgeTransform
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import OutputPersister, PersistedNodeOutput
from grafy_core.service_contracts import BoundServiceProvider


class PluginFailureCode(StrEnum):
    """How one node execution failed, independent of which family ran it."""

    CONTRACT_FAILURE = "contract_failure"
    MATERIALIZATION_FAILURE = "materialization_failure"
    OPERATOR_FAILURE = "operator_failure"
    OUTPUT_VALIDATION = "output_validation"
    TIMEOUT = "timeout"
    CANCELLATION = "cancellation"
    INTERNAL_ADAPTER_FAILURE = "internal_adapter_failure"


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
    """Run one node: materialize its inputs, call its operator, persist outputs.

    The runtime caches nothing. A result is reused by fingerprint in the project
    result store (ADR 0020), which is the only place a successful node output is
    remembered.
    """

    def __init__(
        self,
        *,
        materializer: InputMaterializer,
        persister: OutputPersister,
    ) -> None:
        self._materializer = materializer
        self._persister = persister

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
        transforms: Mapping[str, Sequence[EdgeTransform]] | None = None,
        metadata: JsonObject | None = None,
        *,
        bound_services: Mapping[str, BoundServiceProvider] | None = None,
    ) -> PersistedNodeOutput | BaseModel:
        effective_bindings = artifact_type_bindings or {}
        raw_config: JsonObject = {} if config is None else config
        resolved_contracts = resolve_node_contracts(
            node,
            effective_bindings,
            raw_config,
        )
        context = replace(
            context,
            artifact_type_bindings=effective_bindings,
        )
        validated_config = node.config_contract.model.model_validate(raw_config)
        context = bind_node_secret_config(context, validated_config)

        materialized_inputs, provenance = await self._materializer.materialize(
            contract=cast(InputContract[InputT], resolved_contracts.input_contract),
            inputs=inputs,
            workspace_id=context.workspace_id,
            transforms=transforms,
            node_context=context,
            item_index=context.invocation_index,
        )
        try:
            run_output = await node.run(
                context,
                cast(ConfigT, validated_config),
                materialized_inputs,
            )
        except UserFacingNodeError as exc:
            raise NodeRunError(
                f"Node {context.node_id!r} operator {node.operator_id}@"
                f"{node.operator_version} failed "
                f"({PluginFailureCode.OPERATOR_FAILURE.value}): {exc}",
                failure_code=PluginFailureCode.OPERATOR_FAILURE,
            ) from exc
        except NodeRunError:
            # An operator that classified its own failure keeps that classification;
            # re-wrapping it here would report every typed failure as operator_failure.
            raise
        except Exception as exc:
            raise NodeRunError(
                f"Node {context.node_id!r} operator {node.operator_id}@"
                f"{node.operator_version} failed "
                f"({PluginFailureCode.OPERATOR_FAILURE.value})",
                failure_code=PluginFailureCode.OPERATOR_FAILURE,
            ) from exc
        output_contract = resolved_contracts.output_contract
        validated_output = output_contract.model.model_validate(run_output)
        unsupported = _unsupported_outputs(
            output_contract, validated_output, bound_services or {}
        )
        if unsupported:
            context.output_metadata["unsupported_outputs"] = unsupported
        recorded: JsonObject = {} if metadata is None else dict(metadata)
        if context.output_metadata:
            recorded.update(context.output_metadata)
        persisted = await self._persister.persist_validated(
            contract=output_contract,
            context=context,
            validated_output=validated_output,
            provenance=provenance,
            metadata=recorded,
        )
        return persisted


def _unsupported_outputs(
    contract: OutputContract[BaseModel],
    output: BaseModel,
    bound_services: Mapping[str, BoundServiceProvider],
) -> dict[str, str]:
    unsupported: dict[str, str] = {}
    for port in contract.ports.values():
        requirement = port.requires_service_feature
        if requirement is None:
            continue
        provider = bound_services[requirement.input_port]
        feature = requirement.feature
        value: object = getattr(output, port.name)
        if feature in provider.features:
            if value is None:
                raise UserFacingNodeError(
                    f"{provider.title} declared {feature} but returned none"
                )
        elif value is not None:
            raise UserFacingNodeError(
                f"{provider.title} returned {feature} without declaring it"
            )
        else:
            unsupported[port.name] = provider.title
    return unsupported

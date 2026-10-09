from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from grafy_core.nodes import (
    InputContract,
    OutputContract,
    PortShape,
    ResolvedNodeContracts,
)


class InvocationMode(StrEnum):
    ONCE = "once"
    MAP = "map"


class NodeInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: InvocationMode = InvocationMode.ONCE
    map_input: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_map_input(self) -> Self:
        if self.mode is InvocationMode.MAP:
            if self.map_input is None or self.map_input.strip() == "":
                raise ValueError("MAP invocation requires exactly one map_input")
            return self
        if self.map_input is not None:
            raise ValueError("ONCE invocation does not accept map_input")
        return self


class InvocationError(RuntimeError):
    pass


class NodeContractProvider(Protocol):
    operator_id: ClassVar[str]
    input_contract: ClassVar[InputContract[Any]]
    output_contract: ClassVar[OutputContract[Any]]


@dataclass(frozen=True, slots=True)
class ResolvedNodeContractView:
    """One node instance's contracts after its bindings and config resolved.

    Shapes a node chooses through config exist only on resolved contracts, so
    invocation checks for a compiled node read this view, not the operator.
    """

    operator_id: str
    input_contract: InputContract[Any]
    output_contract: OutputContract[Any]

    @classmethod
    def of(
        cls,
        operator_id: str,
        resolved: ResolvedNodeContracts,
    ) -> "ResolvedNodeContractView":
        return cls(
            operator_id=operator_id,
            input_contract=resolved.input_contract,
            output_contract=resolved.output_contract,
        )


NodeContractSource = (
    NodeContractProvider | type[NodeContractProvider] | ResolvedNodeContractView
)


def map_input_candidates(node: NodeContractSource) -> tuple[str, ...]:
    if not _supports_mapped_outputs(node):
        return ()
    return tuple(
        name
        for name, port in node.input_contract.ports.items()
        if not port.variadic and port.shape is PortShape.ONE
    )


def supported_invocation_modes(
    node: NodeContractSource,
) -> tuple[InvocationMode, ...]:
    if map_input_candidates(node):
        return InvocationMode.ONCE, InvocationMode.MAP
    return (InvocationMode.ONCE,)


def validate_invocation(
    node: NodeContractSource,
    invocation: NodeInvocation,
) -> None:
    if invocation.mode is InvocationMode.ONCE:
        return

    map_input = invocation.map_input
    if map_input is None:
        raise InvocationError(
            f"Node {node.operator_id!r} MAP invocation requires a map_input"
        )

    input_port = node.input_contract.ports.get(map_input)
    if input_port is None:
        raise InvocationError(
            f"Node {node.operator_id!r} MAP input {map_input!r} does not exist"
        )
    if input_port.variadic:
        raise InvocationError(
            f"Node {node.operator_id!r} MAP input {map_input!r} cannot be variadic"
        )
    if input_port.shape is not PortShape.ONE:
        raise InvocationError(
            f"Node {node.operator_id!r} MAP input {map_input!r} must have shape "
            f"{PortShape.ONE.value!r}, got {input_port.shape.value!r}"
        )

    output_ports = node.output_contract.ports
    if not output_ports:
        raise InvocationError(
            f"Node {node.operator_id!r} MAP invocation requires at least one "
            "artifact output port"
        )
    non_port_fields = set(node.output_contract.model.model_fields) - set(output_ports)
    if non_port_fields:
        fields = ", ".join(sorted(non_port_fields))
        raise InvocationError(
            f"Node {node.operator_id!r} MAP output model has non-port fields: {fields}"
        )
    for name, output_port in output_ports.items():
        if not output_port.required:
            raise InvocationError(
                f"Node {node.operator_id!r} MAP output {name!r} must be required"
            )
        if output_port.shape is not PortShape.ONE:
            raise InvocationError(
                f"Node {node.operator_id!r} MAP output {name!r} must have shape "
                f"{PortShape.ONE.value!r}, got {output_port.shape.value!r}"
            )


def effective_input_shape(
    node: NodeContractSource,
    invocation: NodeInvocation,
    port_name: str,
) -> PortShape:
    validate_invocation(node, invocation)
    port = node.input_contract.ports.get(port_name)
    if port is None:
        raise InvocationError(
            f"Node {node.operator_id!r} has no input port {port_name!r}"
        )
    if invocation.mode is InvocationMode.MAP and invocation.map_input == port_name:
        return PortShape.MANY
    return port.shape


def effective_output_shape(
    node: NodeContractSource,
    invocation: NodeInvocation,
    port_name: str,
) -> PortShape:
    validate_invocation(node, invocation)
    port = node.output_contract.ports.get(port_name)
    if port is None:
        raise InvocationError(
            f"Node {node.operator_id!r} has no output port {port_name!r}"
        )
    if invocation.mode is InvocationMode.MAP:
        return PortShape.MANY
    return port.shape


def _supports_mapped_outputs(node: NodeContractSource) -> bool:
    output_ports = node.output_contract.ports
    if not output_ports:
        return False
    if set(node.output_contract.model.model_fields) != set(output_ports):
        return False
    return all(
        port.required and port.shape is PortShape.ONE for port in output_ports.values()
    )

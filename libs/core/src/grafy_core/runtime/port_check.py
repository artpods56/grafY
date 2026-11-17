"""Startup check that a derived port agrees with the declaration of its key."""

from collections.abc import Sequence

from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.plugins import NodeRegistration, PluginRegistrationError
from grafy_core.runtime.artifact_values import ArtifactValues


def check_port_declarations(
    nodes: Sequence[NodeRegistration],
    values: ArtifactValues,
) -> None:
    """Fail when a value port's class is not the class declared for its key.

    Ref ports are skipped. Their type is chosen per instance. A service port
    carries no artifact class, so this pass skips it.
    """

    for registration in nodes:
        node = registration.node_class
        operator = f"{node.operator_id}@{node.operator_version}"
        for port in node.input_contract.ports.values():
            if port.kind == "service" or not port.value_types:
                continue
            for key in port.accepted_types:
                _require_value_class(
                    operator=operator,
                    direction="input",
                    port_name=port.name,
                    key=key,
                    values=values,
                    expected=port.value_types,
                )
        for port in node.output_contract.ports.values():
            produces = port.produces
            if (
                port.kind == "service"
                or port.value_type is None
                or not isinstance(produces, ArtifactTypeKey)
            ):
                continue
            _require_value_class(
                operator=operator,
                direction="output",
                port_name=port.name,
                key=produces,
                values=values,
                expected=(port.value_type,),
            )


def _require_value_class(
    *,
    operator: str,
    direction: str,
    port_name: str,
    key: ArtifactTypeKey,
    values: ArtifactValues,
    expected: tuple[type[object], ...],
) -> None:
    declaration = values.declaration_for(key)
    if declaration is not None and declaration.value_type in expected:
        return
    raise PluginRegistrationError(
        f"operator {operator} {direction} port {port_name!r} "
        f"does not match {key.id}@{key.schema_version}"
    )

from collections.abc import Sequence
from typing import Any, cast
from grafy_api.agents.toolbox import (
    NodePorts,
    PortFacts,
)
from grafy_core.domain.graph_documents import (
    GraphNode,
)
from grafy_core.nodes import ArtifactTypeVariable, resolve_node_contracts
from grafy_core.plugins import PluginRegistry, UnknownOperatorError


class RegistryNodePorts(NodePorts):
    """A node's ports as its registered operator declares them."""

    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry

    def input_ports(self, node: GraphNode) -> Sequence[PortFacts] | None:
        try:
            registration = self._registry.node_registration(
                node.operator_id, node.operator_version
            )
        except UnknownOperatorError:
            return None
        # A node's own bindings decide what a generic port is. The class carries the
        # contract; resolving never builds the node, so one that needs runtime services is
        # described like any other.
        resolved = resolve_node_contracts(
            cast(Any, registration.node_class),
            node.artifact_type_binding_map(),
            node.config_dict(),
        )
        facts: list[PortFacts] = []
        for name, port in resolved.input_contract.ports.items():
            if port.kind == "service":
                # A service input is never a model parameter. The Graph feeds it.
                continue
            facts.append(
                PortFacts(
                    name=name,
                    artifact_type=None
                    if isinstance(port.accepts, ArtifactTypeVariable)
                    else port.accepts,
                    required=port.required,
                    title=port.title,
                    description=port.description,
                )
            )
        return facts

    def output_ports(self, node: GraphNode) -> Sequence[PortFacts] | None:
        try:
            registration = self._registry.node_registration(
                node.operator_id, node.operator_version
            )
        except UnknownOperatorError:
            return None
        # A node's own bindings decide what a generic port is. The class carries the
        # contract; resolving never builds the node, so one that needs runtime services is
        # described like any other.
        resolved = resolve_node_contracts(
            cast(Any, registration.node_class),
            node.artifact_type_binding_map(),
            node.config_dict(),
        )
        facts: list[PortFacts] = []
        for name, out in resolved.output_contract.ports.items():
            if out.kind == "service":
                continue
            facts.append(
                PortFacts(
                    name=name,
                    artifact_type=None
                    if isinstance(out.produces, ArtifactTypeVariable)
                    else out.produces,
                    required=out.required,
                    title=out.title,
                    description=out.description,
                )
            )
        return facts

    def title(self, node: GraphNode) -> str:
        try:
            return self._registry.node_registration(
                node.operator_id, node.operator_version
            ).title
        except UnknownOperatorError:
            return node.operator_id

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from uuid import UUID

from grafy_core.artifacts import ArtifactFieldProjection, ArtifactTypeKey
from grafy_core.conversions import ArtifactConversion
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.implementation import ImplementationIdentity
from grafy_core.domain.plugin_releases import PluginReleaseIdentity
from grafy_core.nodes import Node, ResolvedNodeContracts
from grafy_core.plugins import NodeRegistration
from grafy_core.runtime.invocation import NodeInvocation
from grafy_core.runtime.plugin_protocol import PluginFailureCode

from grafy_api.execution.requests import (
    RunEdgeRequest,
    RunNodeRequest,
)
from grafy_api.execution.control import RunExecutionControl

type OutputEndpoint = tuple[str, str]


@dataclass(frozen=True, slots=True)
class CompiledEdge:
    request: RunEdgeRequest
    projection: ArtifactFieldProjection | None
    conversion_path: tuple[ArtifactConversion[Any, Any], ...]


@dataclass(frozen=True, slots=True)
class CompiledNode:
    request: RunNodeRequest
    node: Node[Any, Any, Any]
    registration: NodeRegistration | None
    resolved_contracts: ResolvedNodeContracts
    invocation: NodeInvocation
    artifact_type_bindings: Mapping[str, ArtifactTypeKey]
    plugin_release: PluginReleaseIdentity | None = None
    implementation: ImplementationIdentity | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "artifact_type_bindings",
            MappingProxyType(dict(self.artifact_type_bindings)),
        )


@dataclass(frozen=True, slots=True)
class CompiledGraph:
    nodes: tuple[CompiledNode, ...]
    edges: tuple[CompiledEdge, ...]
    pinned_outputs: Mapping[OutputEndpoint, ArtifactOutputValue]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "pinned_outputs",
            MappingProxyType(dict(self.pinned_outputs)),
        )


@dataclass(frozen=True, slots=True)
class PreparedGraphExecution:
    """Validated, compiled inputs required to execute one graph run."""

    plan: CompiledGraph
    initial_outputs: Mapping[str, Mapping[str, ArtifactOutputValue]]
    workspace_id: UUID
    graph_id: UUID | None
    graph_revision: int | None
    secret_graph_id: UUID | None
    secret_graph_revision: int | None
    secret_node_ids: frozenset[str]
    module_path: tuple[str, ...]
    raise_node_errors: bool
    node_path: tuple[str, ...] = ()
    invocation_path: tuple[int, ...] = ()
    control: RunExecutionControl | None = None

    def __post_init__(self) -> None:
        copied_outputs = {
            node_id: MappingProxyType(
                {
                    port: value.model_copy(deep=True)
                    for port, value in node_outputs.items()
                }
            )
            for node_id, node_outputs in self.initial_outputs.items()
        }
        object.__setattr__(
            self,
            "initial_outputs",
            MappingProxyType(copied_outputs),
        )
        object.__setattr__(self, "secret_node_ids", frozenset(self.secret_node_ids))
        object.__setattr__(self, "module_path", tuple(self.module_path))
        object.__setattr__(self, "node_path", tuple(self.node_path))
        object.__setattr__(self, "invocation_path", tuple(self.invocation_path))


@dataclass(frozen=True, slots=True)
class NodeExecutionResult:
    node_id: str
    status: Literal["succeeded", "failed", "skipped"]
    error: str | None
    outputs: Mapping[str, ArtifactOutputValue]
    plugin_release: PluginReleaseIdentity | None = None
    failure_code: PluginFailureCode | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "outputs",
            MappingProxyType(dict(self.outputs)),
        )


@dataclass(frozen=True, slots=True)
class GraphExecutionResult:
    workflow_run_id: UUID
    status: Literal["succeeded", "failed"]
    node_results: tuple[NodeExecutionResult, ...]
    outputs: Mapping[str, Mapping[str, ArtifactOutputValue]]

    def __post_init__(self) -> None:
        copied_outputs = {
            node_id: MappingProxyType(dict(node_outputs))
            for node_id, node_outputs in self.outputs.items()
        }
        object.__setattr__(
            self,
            "outputs",
            MappingProxyType(copied_outputs),
        )


__all__ = [
    "CompiledEdge",
    "CompiledGraph",
    "CompiledNode",
    "GraphExecutionResult",
    "NodeExecutionResult",
    "OutputEndpoint",
    "PreparedGraphExecution",
]

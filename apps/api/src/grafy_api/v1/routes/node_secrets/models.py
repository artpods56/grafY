from typing import TYPE_CHECKING, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from grafy_api.node_secrets import NodeSecretResolutionReason

if TYPE_CHECKING:
    from grafy_api.node_secrets import (
        GraphNodeSecretState,
        NodeSecretResolutionState,
        NodeSecretState,
    )


class NodeSecretApiModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")


class ConfigureNodeSecretRequest(NodeSecretApiModel):
    value: SecretStr
    expected_graph_revision: int = Field(ge=1)


class NodeSecretStatusResponse(NodeSecretApiModel):
    node_id: str
    name: str
    configured: bool

    @classmethod
    def from_state(cls, state: "NodeSecretState") -> "NodeSecretStatusResponse":
        return cls(
            node_id=state.node_id,
            name=state.name,
            configured=state.configured,
        )


class NodeSecretResolutionResponse(NodeSecretApiModel):
    node_id: str
    status: Literal["unresolved"]
    reason: NodeSecretResolutionReason

    @classmethod
    def from_state(
        cls,
        state: "NodeSecretResolutionState",
    ) -> "NodeSecretResolutionResponse":
        return cls(
            node_id=state.node_id,
            status=state.status.value,
            reason=state.reason,
        )


class GraphNodeSecretsResponse(NodeSecretApiModel):
    graph_id: UUID
    graph_revision: int
    secrets: list[NodeSecretStatusResponse]
    unresolved_nodes: list[NodeSecretResolutionResponse]

    @classmethod
    def from_state(
        cls,
        state: "GraphNodeSecretState",
    ) -> "GraphNodeSecretsResponse":
        return cls(
            graph_id=state.graph_id,
            graph_revision=state.graph_revision,
            secrets=[
                NodeSecretStatusResponse.from_state(secret) for secret in state.secrets
            ],
            unresolved_nodes=[
                NodeSecretResolutionResponse.from_state(node)
                for node in state.unresolved_nodes
            ],
        )

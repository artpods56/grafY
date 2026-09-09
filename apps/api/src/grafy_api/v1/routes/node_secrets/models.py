from typing import TYPE_CHECKING, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

if TYPE_CHECKING:
    from grafy_api.node_secrets import (
        GraphNodeSecretState,
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


class GraphNodeSecretsResponse(NodeSecretApiModel):
    graph_id: UUID
    graph_revision: int
    secrets: list[NodeSecretStatusResponse]

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
        )

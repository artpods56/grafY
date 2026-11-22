from typing import TYPE_CHECKING, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from grafy_api.node_secrets import NodeSecretResolutionReason, NodeSecretSource
from grafy_core.domain.credentials import (
    CredentialVerificationStatus,
    SharedCredentialBindingMode,
    UserCredentialOverrideMode,
)

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
    expected_head_sequence: int = Field(ge=0)


class SharedCredentialBindingRequest(NodeSecretApiModel):
    mode: SharedCredentialBindingMode | Literal["none"]
    credential_id: UUID | None = None
    expected_head_sequence: int = Field(ge=0)


class PersonalCredentialSelectionRequest(NodeSecretApiModel):
    mode: UserCredentialOverrideMode | Literal["none"]
    credential_id: UUID | None = None


class VerifyNodeSecretRequest(NodeSecretApiModel):
    value: SecretStr | None = None


class ConfigureNodeSecretResponse(NodeSecretApiModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)
    node_id: str
    name: str
    configured: bool


class NodeSecretStatusResponse(ConfigureNodeSecretResponse):
    provider_kind: str = "generic"
    effective_source: NodeSecretSource = "none"
    effective_credential_id: UUID | None = None
    effective_credential_label: str | None = None
    effective_verification_status: CredentialVerificationStatus | None = None
    shared_binding_mode: SharedCredentialBindingMode | Literal["none"] = "none"
    shared_credential_id: UUID | None = None
    shared_credential_label: str | None = None
    shared_credential_missing: bool = False
    personal_override_mode: UserCredentialOverrideMode | Literal["none"] = "none"
    personal_credential_id: UUID | None = None
    personal_credential_label: str | None = None
    deployment_default_available: bool = False
    supports_verification: bool = False

    @classmethod
    def from_state(cls, state: "NodeSecretState") -> "NodeSecretStatusResponse":
        return cls.model_validate(state)


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


class ProjectNodeSecretsResponse(NodeSecretApiModel):
    """Secret status for one Graph of a Project's live head."""

    project_id: UUID
    graph_id: str
    head_sequence: int
    secrets: list[NodeSecretStatusResponse]
    unresolved_nodes: list[NodeSecretResolutionResponse]

    @classmethod
    def from_state(
        cls,
        state: "GraphNodeSecretState",
    ) -> "ProjectNodeSecretsResponse":
        return cls(
            project_id=state.project_id,
            graph_id=state.graph_id,
            head_sequence=state.head_sequence,
            secrets=[
                NodeSecretStatusResponse.from_state(secret) for secret in state.secrets
            ],
            unresolved_nodes=[
                NodeSecretResolutionResponse.from_state(node)
                for node in state.unresolved_nodes
            ],
        )

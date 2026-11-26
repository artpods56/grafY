from datetime import datetime
from typing import ClassVar, Literal, Self
from uuid import UUID

from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
from grafy_core.domain.agent_conversations import AgentConversationEventPayload
from grafy_core.domain.agent_turns import AgentTurnStatus
from grafy_core.domain.credentials import (
    CredentialVerificationStatus,
    SharedCredentialBindingMode,
    UserCredentialOverrideMode,
)
from grafy_core.kernel.project import ProjectDocument
from grafy_core.nodes import PortShape
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClientModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class CreatedArtifact(ArtifactRef):
    derived_from_artifact_id: UUID | None
    created_at: datetime


class ServiceContractKey(ClientModel):
    id: str
    version: int


class ServiceContract(ClientModel):
    id: str
    version: int
    title: str


class ServiceContractFeatures(ClientModel):
    contract: ServiceContractKey
    features: tuple[str, ...]


class RequiresServiceFeature(ClientModel):
    input_port: str
    feature: str


class CatalogPort(ClientModel):
    name: str
    title: str | None = None
    description: str | None = None
    direction: Literal["input", "output"]
    kind: Literal["artifact", "service"] = "artifact"
    artifact_type: ArtifactTypeKey | None = None
    artifact_type_variable: str | None = None
    also_accepts: tuple[ArtifactTypeKey, ...] = ()
    service_contracts: tuple[ServiceContractKey, ...] = ()
    service_features: tuple[ServiceContractFeatures, ...] = ()
    requires_service_feature: RequiresServiceFeature | None = None
    requires_input: str | None = None
    exclusive_group: str | None = None
    shape: PortShape
    accepted_shapes: tuple[PortShape, ...]
    instance_plugs: bool = False
    variadic: bool = False
    required: bool = True
    shape_field: str | None = None
    agent_default: Literal["hidden"] | None = None

    @model_validator(mode="after")
    def require_port_contract(self) -> Self:
        if self.kind == "service":
            if (
                self.artifact_type is not None
                or self.artifact_type_variable is not None
                or self.also_accepts
            ):
                raise ValueError(
                    "Catalog service port cannot declare an artifact type or variable"
                )
            if not self.service_contracts:
                raise ValueError(
                    "Catalog service port must name at least one service contract"
                )
            return self
        if self.service_contracts:
            raise ValueError("Catalog artifact port cannot declare a service contract")
        if (self.artifact_type is None) == (self.artifact_type_variable is None):
            raise ValueError(
                "Catalog port must declare exactly one artifact type or variable"
            )
        if self.also_accepts and self.artifact_type is None:
            raise ValueError(
                "Catalog port additional accepted artifact types require an "
                "artifact type"
            )
        return self


class CatalogNode(ClientModel):
    origin: Literal["builtin"] = "builtin"
    role: Literal["operator", "provider"] = "operator"
    operator_id: str
    operator_version: int
    plugin_slug: str
    pack_slugs: tuple[str, ...]
    title: str
    description: str
    config_schema: dict[str, object]
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    inputs: tuple[CatalogPort, ...]
    outputs: tuple[CatalogPort, ...]
    secret_inputs: tuple[dict[str, object], ...] = ()
    catalog_visible: bool = True
    runnable: bool = True


class CatalogConversionKey(ClientModel):
    id: str
    version: int


class CatalogConversion(ClientModel):
    key: CatalogConversionKey
    source_artifact_type: ArtifactTypeKey
    target_artifact_type: ArtifactTypeKey
    title: str

    @property
    def source(self) -> ArtifactTypeKey:
        return self.source_artifact_type

    @property
    def target(self) -> ArtifactTypeKey:
        return self.target_artifact_type


class CatalogPack(ClientModel):
    slug: str
    title: str
    description: str
    always_on: bool
    subscribed: bool
    operator_count: int
    provider_count: int
    includes_project_graphs: bool


class NodeCatalog(ClientModel):
    packs: tuple[CatalogPack, ...]
    plugins: tuple[dict[str, object], ...]
    artifact_types: tuple[dict[str, object], ...]
    service_contracts: tuple[ServiceContract, ...] = ()
    nodes: tuple[CatalogNode, ...]
    artifact_conversions: tuple[CatalogConversion, ...]


class Workspace(ClientModel):
    """One Workspace the caller reaches, with the capabilities it holds there.

    A personal access token lists only the Workspace it is bound to, and its
    capabilities are its scopes intersected with the member's current role.
    """

    id: UUID
    slug: str
    name: str
    kind: Literal["personal", "shared"]
    role: Literal["viewer", "editor", "owner"]
    capabilities: tuple[str, ...]


class ProjectSummary(ClientModel):
    """A Project as the Workspace list shows it: counts describe the live head."""

    id: UUID
    name: str
    revision: int
    graph_count: int
    node_count: int
    edge_count: int
    updated_at: datetime
    draft_pending: bool


class Project(ClientModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class ProjectHead(ClientModel):
    """Collaboration metadata paired with the Project document."""

    project_id: UUID
    room_epoch: UUID
    collaboration_sequence: int
    checkpoint_sequence: int
    checkpoint_revision: int
    name: str
    updated_at: datetime
    document: ProjectDocument


class ProjectExport(ClientModel):
    """Versioned portable JSON envelope for a whole Project."""

    format: Literal["grafy.project"] = "grafy.project"
    format_version: Literal[1] = 1
    name: str
    document: ProjectDocument


ProjectImportWarningCode = Literal[
    "unknown_operator",
    "stripped_origins",
    "stripped_artifact_cards",
    "stripped_library_context_links",
    "stripped_card_context_links",
    "stripped_legacy_config_keys",
    "credentials_required",
    "custom_agent_model",
]


class ProjectImportWarning(ClientModel):
    code: ProjectImportWarningCode
    message: str
    graph_id: str | None = None
    node_id: str | None = None
    operator_id: str | None = None
    operator_version: int | None = None
    agent_id: str | None = None


class ImportedProject(ClientModel):
    project: Project
    warnings: tuple[ProjectImportWarning, ...] = ()


class CommandReceipt(ClientModel):
    command_id: UUID
    outcome: Literal["accepted", "idempotent_replay"]
    accepted_sequence: int
    room_epoch: UUID
    deduplicated: bool


class SubmittedCommands(ClientModel):
    head: ProjectHead
    receipt: CommandReceipt


class UploadItem(ClientModel):
    upload_key: str
    filename: str
    byte_size: int
    artifact_id: UUID | None = None
    artifact_type: str | None = None
    notice: str | None = None


class UploadTarget(ClientModel):
    """Where the bytes of one reserved upload go.

    ``api`` targets are this API's own content route and take the bearer token;
    ``storage`` targets are signed object-storage URLs whose signature is the
    credential, so they take only ``headers``.
    """

    kind: Literal["api", "storage"] = "api"
    upload_id: str
    url: str
    method: str
    expires_at: datetime
    headers: dict[str, str] = Field(default_factory=dict)


class TableColumn(ClientModel):
    id: str
    title: str
    value_type: str


class TableSchema(ClientModel):
    columns: tuple[TableColumn, ...]
    total_rows: int


class TableCell(ClientModel):
    display: str | float | bool | None
    truncated: bool
    original_length: int | None = None


class TablePage(ClientModel):
    """A bounded window of a table artifact; long cells arrive truncated."""

    columns: tuple[TableColumn, ...]
    rows: tuple[dict[str, TableCell], ...]
    row_indices: tuple[int, ...] = ()
    highlighted_row_indices: tuple[int, ...] = ()
    offset: int
    limit: int
    total_rows: int
    column_offset: int
    column_limit: int
    total_columns: int


class GeoRender(ClientModel):
    """The render descriptor of a geo artifact: layers, bounds, basemap.

    Layer entries stay JSON objects; they carry tile URLs relative to the API.
    """

    artifact_id: UUID
    kind: str
    basemap: Literal["openstreetmap", "none"]
    initial_bounds: tuple[float, float, float, float] | None
    layers: tuple[dict[str, object], ...]


class GeoFeatureMatch(ClientModel):
    artifact_id: UUID
    bounds: tuple[float, float, float, float] | None
    matched_feature_count: int
    source_artifact_ids: tuple[UUID, ...]


class NodeSecretStatus(ClientModel):
    node_id: str
    name: str
    configured: bool


class RunTarget(ClientModel):
    node_id: str
    call_path: tuple[str, ...] = ()


class Run(ClientModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    graph_id: str
    targets: tuple[RunTarget, ...]
    started_by_user_id: UUID | None
    status: Literal["running", "succeeded", "failed", "cancelled", "interrupted"]
    created_at: datetime
    finished_at: datetime | None
    error: str | None

    @property
    def terminal(self) -> bool:
        return self.status != "running"


class InstanceKey(ClientModel):
    project_id: UUID
    graph_id: str
    call_path: tuple[str, ...]
    node_id: str
    map_index: int | None = None


class InstanceState(ClientModel):
    key: InstanceKey
    state: Literal["fresh", "stale", "queued", "running", "failed"]
    fingerprint: str
    last_result_fingerprint: str | None
    error: str | None


class InstanceResult(ClientModel):
    """The last result of one node instance; it may be stale."""

    instance: InstanceState
    result_fingerprint: str | None
    outputs: dict[str, object] | None
    created_at: datetime | None


class ProjectFolder(ClientModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class ProjectOrganization(ClientModel):
    folder_id: UUID | None
    archived: bool
    archived_at: datetime | None
    updated_at: datetime


class UserProjectState(ClientModel):
    starred: bool
    last_opened_at: datetime | None


class ProjectCheckpointSummary(ClientModel):
    """One retained checkpoint without its document."""

    revision: int
    name: str
    created_at: datetime


class ProjectCheckpoint(ProjectCheckpointSummary):
    """One retained checkpoint with the exact document it froze."""

    document: ProjectDocument


class NodeSecretDetail(ClientModel):
    node_id: str
    name: str
    configured: bool
    provider_kind: str = "generic"
    effective_source: Literal[
        "personal_credential",
        "shared_credential",
        "deployment_default",
        "inline_legacy",
        "none",
    ] = "none"
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


class NodeSecretResolution(ClientModel):
    node_id: str
    status: Literal["unresolved"]
    reason: Literal["contract_unavailable", "invalid_configuration"]


class ProjectNodeSecrets(ClientModel):
    """Secret status for one Graph of a Project's live head."""

    project_id: UUID
    graph_id: str
    head_sequence: int
    secrets: tuple[NodeSecretDetail, ...]
    unresolved_nodes: tuple[NodeSecretResolution, ...]


class CredentialVerification(ClientModel):
    status: CredentialVerificationStatus
    message: str
    account_hint: str | None


class TableCellValue(ClientModel):
    row_index: int
    column_id: str
    value: str | float | bool | None
    encoding: Literal["native", "integer", "json"] = "native"


class ImageInfo(ClientModel):
    width: int
    height: int
    page_count: int
    has_alpha: bool
    tile_size: Literal[256, 512]
    min_level: int
    max_level: int
    tile_format: Literal["jpg", "png"]
    georeferenced: bool = False
    bounds_wgs84: tuple[float, float, float, float] | None = None


class AgentConversation(ClientModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    graph_id: str
    agent_id: str
    author_user_id: UUID
    title: str
    source_conversation_id: UUID | None
    source_sequence: int | None
    last_sequence: int
    created_at: datetime
    updated_at: datetime


class AgentConversationEvent(ClientModel):
    sequence: int
    turn_id: UUID
    payload: AgentConversationEventPayload
    created_at: datetime


class AgentConversationEvents(ClientModel):
    events: tuple[AgentConversationEvent, ...]
    next_sequence: int
    last_sequence: int


class AgentTurn(ClientModel):
    id: UUID
    conversation_id: UUID
    client_turn_id: str
    status: AgentTurnStatus
    model_source: str
    model_name: str
    requested_by_user_id: UUID
    user_message_sequence: int
    outcome_detail: str | None
    created_at: datetime
    finished_at: datetime | None

    @property
    def terminal(self) -> bool:
        return self.status != AgentTurnStatus.RUNNING


class ActiveAgentTurn(ClientModel):
    turn: AgentTurn
    message_id: UUID | None
    partial_offset: int
    partial_text: str


class AgentModel(ClientModel):
    source: str
    model_name: str
    base_url: str
    key_configured: bool


__all__ = [
    "ActiveAgentTurn",
    "AgentConversation",
    "AgentConversationEvent",
    "AgentConversationEvents",
    "AgentModel",
    "AgentTurn",
    "CreatedArtifact",
    "CatalogConversion",
    "CatalogConversionKey",
    "CatalogNode",
    "CatalogPack",
    "CatalogPort",
    "CommandReceipt",
    "CredentialVerification",
    "GeoFeatureMatch",
    "GeoRender",
    "ImageInfo",
    "ImportedProject",
    "InstanceKey",
    "InstanceResult",
    "InstanceState",
    "NodeCatalog",
    "NodeSecretDetail",
    "NodeSecretResolution",
    "NodeSecretStatus",
    "Project",
    "ProjectCheckpoint",
    "ProjectCheckpointSummary",
    "ProjectExport",
    "ProjectFolder",
    "ProjectHead",
    "ProjectImportWarning",
    "ProjectImportWarningCode",
    "ProjectNodeSecrets",
    "ProjectOrganization",
    "ProjectSummary",
    "Run",
    "RunTarget",
    "ServiceContract",
    "ServiceContractKey",
    "SubmittedCommands",
    "TableCell",
    "TableCellValue",
    "TableColumn",
    "TablePage",
    "TableSchema",
    "UploadItem",
    "UploadTarget",
    "UserProjectState",
    "Workspace",
]

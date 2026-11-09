from datetime import datetime
from typing import ClassVar, Literal, Self
from uuid import UUID

from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.kernel.project import ProjectDocument
from grafy_core.nodes import PortShape
from pydantic import BaseModel, ConfigDict, model_validator


class ClientModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class CatalogPort(ClientModel):
    name: str
    title: str | None = None
    description: str | None = None
    direction: Literal["input", "output"]
    artifact_type: ArtifactTypeKey | None = None
    artifact_type_variable: str | None = None
    also_accepts: tuple[ArtifactTypeKey, ...] = ()
    shape: PortShape
    accepted_shapes: tuple[PortShape, ...]
    instance_plugs: bool = False
    variadic: bool = False
    required: bool = True
    shape_field: str | None = None
    agent_default: Literal["hidden"] | None = None

    @model_validator(mode="after")
    def require_one_artifact_contract(self) -> Self:
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
    operator_id: str
    operator_version: int
    plugin_slug: str
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


class NodeCatalog(ClientModel):
    plugins: tuple[dict[str, object], ...]
    artifact_types: tuple[dict[str, object], ...]
    nodes: tuple[CatalogNode, ...]
    artifact_conversions: tuple[CatalogConversion, ...]


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


__all__ = [
    "CatalogConversion",
    "CatalogConversionKey",
    "CatalogNode",
    "CatalogPort",
    "CommandReceipt",
    "InstanceKey",
    "InstanceResult",
    "InstanceState",
    "NodeCatalog",
    "NodeSecretStatus",
    "Project",
    "ProjectHead",
    "Run",
    "RunTarget",
    "SubmittedCommands",
    "UploadItem",
]

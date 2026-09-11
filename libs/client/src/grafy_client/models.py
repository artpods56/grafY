from datetime import datetime
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.domain.saved_graphs import (
    SavedGraphDocument,
    SavedGraphPluginReleasePin,
)
from grafy_core.nodes import PortShape


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
    origin: Literal["builtin", "plugin", "module"] = "builtin"
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
    module_graph_id: UUID | None = None
    module_graph_revision: int | None = None
    module_id: UUID | None = None
    publication_state: str | None = None
    is_current_library_release: bool | None = None
    catalog_visible: bool = True
    plugin_revision: int | None = None
    plugin_release: SavedGraphPluginReleasePin | None = None
    runnable: bool = True
    non_runnable_reason: str | None = None
    non_runnable_detail: str | None = None


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
    unavailable_modules: tuple[dict[str, object], ...] = ()


class SavedGraph(ClientModel):
    id: UUID
    name: str
    revision: int
    created_at: datetime
    updated_at: datetime
    document: SavedGraphDocument


class UploadItem(ClientModel):
    upload_key: str
    filename: str
    byte_size: int


class NodeSecretStatus(ClientModel):
    node_id: str
    name: str
    configured: bool


class ExecutionArtifact(ClientModel):
    artifact_id: UUID
    artifact_type: str
    schema_version: int
    content_type: str
    byte_size: int | None = None
    sha256: str | None = None
    text: str | None = None
    content_url: str | None = None
    download_formats: tuple[dict[str, object], ...] = ()
    metadata: dict[str, object] = Field(default_factory=dict)


class ExecutionOutput(ClientModel):
    port: str
    kind: Literal["single", "sequence"]
    value: object
    artifacts: tuple[ExecutionArtifact, ...]

    @property
    def artifact_id(self) -> UUID:
        if len(self.artifacts) != 1:
            raise ValueError(
                f"Execution output {self.port!r} contains {len(self.artifacts)} "
                "artifacts, not one"
            )
        return self.artifacts[0].artifact_id

    @property
    def artifact_type(self) -> str:
        if len(self.artifacts) != 1:
            raise ValueError(
                f"Execution output {self.port!r} contains {len(self.artifacts)} "
                "artifacts, not one"
            )
        return self.artifacts[0].artifact_type


class ExecutionNodeResult(ClientModel):
    node_id: str
    status: Literal["succeeded", "failed", "skipped"]
    error: str | None
    outputs: tuple[ExecutionOutput, ...]

    def output(self, port: str) -> ExecutionOutput:
        matching = [output for output in self.outputs if output.port == port]
        if len(matching) != 1:
            raise KeyError(
                f"Node {self.node_id!r} has {len(matching)} outputs named {port!r}"
            )
        return matching[0]


class ExecutionResult(ClientModel):
    status: Literal["succeeded", "failed"]
    node_runs: tuple[ExecutionNodeResult, ...]

    def node(self, node_id: str) -> ExecutionNodeResult:
        matching = [node for node in self.node_runs if node.node_id == node_id]
        if len(matching) != 1:
            raise KeyError(f"Execution has {len(matching)} nodes named {node_id!r}")
        return matching[0]


class ExecutionState(ClientModel):
    execution_id: UUID
    status: Literal[
        "queued",
        "running",
        "cancelling",
        "cancelled",
        "succeeded",
        "failed",
    ]
    active_node_id: str | None
    result: ExecutionResult | None
    error: str | None
    queue_position: int | None = None

    @property
    def terminal(self) -> bool:
        return self.status in {"cancelled", "succeeded", "failed"}


__all__ = [
    "CatalogConversion",
    "CatalogConversionKey",
    "CatalogNode",
    "CatalogPort",
    "ExecutionArtifact",
    "ExecutionNodeResult",
    "ExecutionOutput",
    "ExecutionResult",
    "ExecutionState",
    "NodeCatalog",
    "NodeSecretStatus",
    "SavedGraph",
    "UploadItem",
]

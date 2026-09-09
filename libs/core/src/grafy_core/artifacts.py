from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Literal,
    Self,
    TypeAlias,
    Any,
    Callable,
)
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from grafy_core.plugins import PluginRuntimeContext
    from grafy_core.runtime.persistence import ArtifactOutputWriter
    from grafy_core.runtime.resolvers import Resolver

JsonObject: TypeAlias = dict[str, object]
MaterializedJsonType: TypeAlias = Literal["string", "integer"]
ArtifactBundleFormat: TypeAlias = Literal[
    "inline-json",
    "table-bundle",
    "binary-file",
    "object-set",
]
ArtifactReferenceShape: TypeAlias = Literal["one", "many"]


class NodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class NodeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoConfig(NodeConfig):
    pass


def artifact_id() -> UUID:
    return uuid4()


def sequence_id() -> UUID:
    return uuid4()


@dataclass(frozen=True, slots=True)
class ArtifactTypeKey:
    id: str
    schema_version: int


@dataclass(frozen=True, slots=True)
class ArtifactFieldProjection:
    path: tuple[str, ...]
    target: ArtifactTypeKey
    title: str


@dataclass(frozen=True, slots=True)
class ArtifactExportFormat:
    """One downloadable rendering of an artifact type, beyond the universal JSON.

    `json` is always available for any artifact with a payload (it is the
    canonical whole-artifact document). `export_formats` declares the additional
    formats a type can be rendered into, e.g. bare text for text scalars.
    """

    format: str
    content_type: str
    filename: str


@dataclass(frozen=True, slots=True)
class ArtifactBundleContract:
    """Portable representation used to carry an artifact across runtimes."""

    format: ArtifactBundleFormat
    version: int

    def __post_init__(self) -> None:
        if self.format not in {
            "inline-json",
            "table-bundle",
            "binary-file",
            "object-set",
        }:
            raise ValueError(f"Unsupported artifact bundle format {self.format!r}")
        if isinstance(self.version, bool) or self.version < 1:
            raise ValueError("Artifact bundle version must be positive")


@dataclass(frozen=True, slots=True)
class ArtifactReferenceContract:
    """One JSON field whose value names other persisted artifacts."""

    path: tuple[str, ...]
    target: ArtifactTypeKey
    shape: ArtifactReferenceShape

    def __post_init__(self) -> None:
        if not self.path or any(
            segment == "" or segment != segment.strip() for segment in self.path
        ):
            raise ValueError("Artifact reference path must contain nonblank segments")


@dataclass(frozen=True, slots=True)
class ArtifactTypeSpec:
    key: ArtifactTypeKey
    title: str
    payload_schema: JsonObject = field(default_factory=dict)
    field_projections: tuple[ArtifactFieldProjection, ...] = ()
    materialized_json_type: MaterializedJsonType | None = None
    export_formats: tuple[ArtifactExportFormat, ...] = ()
    references: tuple[ArtifactReferenceContract, ...] = ()
    bundle: ArtifactBundleContract = ArtifactBundleContract(
        format="inline-json",
        version=1,
    )

    def __post_init__(self) -> None:
        paths = [reference.path for reference in self.references]
        if len(paths) != len(set(paths)):
            raise ValueError("Artifact reference paths must be unique")
        if self.references and self.bundle.format != "inline-json":
            raise ValueError(
                "Artifact references currently require the inline-json bundle"
            )


@dataclass(frozen=True, slots=True)
class Artifact:
    spec: ArtifactTypeSpec
    resolver: "Callable[[PluginRuntimeContext], Resolver[Any]]"
    writer: "Callable[[PluginRuntimeContext], ArtifactOutputWriter]"


class ArtifactRef(BaseModel):
    artifact_id: UUID
    artifact_type: str
    schema_version: int
    content_hash: str | None = None

    @classmethod
    def from_key(
        cls,
        *,
        artifact_id: UUID,
        key: ArtifactTypeKey,
        content_hash: str | None = None,
    ) -> Self:
        return cls(
            artifact_id=artifact_id,
            artifact_type=key.id,
            schema_version=key.schema_version,
            content_hash=content_hash,
        )

    def key(self) -> ArtifactTypeKey:
        return ArtifactTypeKey(self.artifact_type, self.schema_version)


class ArtifactRefSequence(BaseModel):
    sequence_id: UUID = Field(default_factory=sequence_id)
    artifact_type: str
    schema_version: int
    item_refs: list[ArtifactRef]
    ordered: bool = True
    index_key: str = "order_index"
    metadata: JsonObject = Field(default_factory=dict)

    @classmethod
    def from_key(
        cls,
        *,
        key: ArtifactTypeKey,
        item_refs: list[ArtifactRef],
        metadata: JsonObject | None = None,
    ) -> Self:
        return cls(
            artifact_type=key.id,
            schema_version=key.schema_version,
            item_refs=item_refs,
            metadata=metadata or {},
        )

    @model_validator(mode="after")
    def validate_item_refs(self) -> Self:
        for item_ref in self.item_refs:
            if item_ref.artifact_type != self.artifact_type:
                message = (
                    f"ArtifactSequence item type mismatch: expected "
                    f"{self.artifact_type}, got {item_ref.artifact_type}"
                )
                raise ValueError(message)
            if item_ref.schema_version != self.schema_version:
                message = (
                    f"ArtifactSequence schema version mismatch: expected "
                    f"{self.schema_version}, got {item_ref.schema_version}"
                )
                raise ValueError(message)
        return self


@dataclass
class ArtifactObject:
    workspace_id: UUID
    artifact_type: str
    schema_version: int
    content_type: str
    id: UUID = field(default_factory=artifact_id)
    storage_backend: str = "local"
    bucket: str | None = None
    object_key: str | None = None
    inline_payload: JsonObject | None = None
    byte_size: int | None = None
    sha256: str | None = None
    metadata: JsonObject = field(default_factory=dict)

    def ref(self) -> ArtifactRef:
        return ArtifactRef.from_key(
            artifact_id=self.id,
            key=ArtifactTypeKey(self.artifact_type, self.schema_version),
            content_hash=self.sha256,
        )


if TYPE_CHECKING:
    from grafy_core.ports.artifacts import (
        ArtifactRepositoryPort as ArtifactRepositoryPort,
        UnitOfWorkPort as UnitOfWorkPort,
    )

    from grafy_core.runtime.in_memory import (
        InMemoryArtifactRepository as InMemoryArtifactRepository,
        InMemoryDataStore as InMemoryDataStore,
        InMemoryGraphExecutionHistoryRepository as InMemoryGraphExecutionHistoryRepository,
        InMemoryInvocationCacheRepository as InMemoryInvocationCacheRepository,
        InMemoryMaterializedNodeOutputsRepository as InMemoryMaterializedNodeOutputsRepository,
        InMemoryStagedUploadRepository as InMemoryStagedUploadRepository,
        InMemoryUnitOfWork as InMemoryUnitOfWork,
    )


def __getattr__(name: str) -> object:
    # Legacy SDK exports must be lazy: importing ports or runtime while artifact
    # models initialize re-enters the domain package through its public exports.
    if name in {"ArtifactRepositoryPort", "UnitOfWorkPort"}:
        from grafy_core.ports import artifacts

        return getattr(artifacts, name)
    if name in {
        "InMemoryArtifactRepository",
        "InMemoryDataStore",
        "InMemoryGraphExecutionHistoryRepository",
        "InMemoryInvocationCacheRepository",
        "InMemoryMaterializedNodeOutputsRepository",
        "InMemoryStagedUploadRepository",
        "InMemoryUnitOfWork",
    }:
        from grafy_core.runtime import in_memory

        return getattr(in_memory, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Artifact",
    "ArtifactBundleContract",
    "ArtifactBundleFormat",
    "ArtifactExportFormat",
    "ArtifactFieldProjection",
    "ArtifactObject",
    "ArtifactRef",
    "ArtifactRefSequence",
    "ArtifactReferenceContract",
    "ArtifactReferenceShape",
    "ArtifactRepositoryPort",
    "ArtifactTypeKey",
    "ArtifactTypeSpec",
    "InMemoryArtifactRepository",
    "InMemoryDataStore",
    "InMemoryGraphExecutionHistoryRepository",
    "InMemoryInvocationCacheRepository",
    "InMemoryMaterializedNodeOutputsRepository",
    "InMemoryStagedUploadRepository",
    "InMemoryUnitOfWork",
    "JsonObject",
    "MaterializedJsonType",
    "NoConfig",
    "NodeConfig",
    "NodeInput",
    "NodeOutput",
    "UnitOfWorkPort",
    "artifact_id",
    "sequence_id",
]

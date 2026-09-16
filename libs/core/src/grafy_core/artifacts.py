import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Self,
    TypeAlias,
)
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
ConfirmationRule: TypeAlias = Literal["magic", "json", "json_document", "none"]

_EXTENSION_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,14}[a-z0-9])?$")


def validate_extension_claims(
    artifact_type_id: str,
    extensions: tuple[str, ...],
) -> None:
    """Enforce the extension claim rules shared by specs and release contracts."""

    if len(extensions) != len(set(extensions)):
        raise ValueError("Artifact type extensions must be unique")
    if artifact_type_id == "file.blob" and extensions:
        raise ValueError("file.blob may not declare extensions")
    if extensions and not artifact_type_id.startswith("file."):
        raise ValueError(
            f"Artifact type {artifact_type_id!r} may not declare extensions; "
            "only file.* types claim extensions"
        )
    for extension in extensions:
        if not _EXTENSION_PATTERN.fullmatch(extension):
            raise ValueError(
                f"Artifact type extension {extension!r} must be a lowercase "
                "alphanumeric token of 1 to 16 characters without a dot, "
                "whitespace, or a leading or trailing dash"
            )


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

#[TODO] Artifact types could be typed
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
class MagicSegment:
    """One offset-and-bytes segment that must match at the start of a file."""

    offset: int
    value: bytes

    def __post_init__(self) -> None:
        if isinstance(self.offset, bool) or self.offset < 0:
            raise ValueError("Magic signature segment offset must not be negative")
        if not self.value:
            raise ValueError("Magic signature segment bytes must not be empty")

    def matches(self, content: bytes) -> bool:
        return content[self.offset : self.offset + len(self.value)] == self.value


@dataclass(frozen=True, slots=True)
class MagicSignature:
    """One alternative magic signature: every segment must match."""

    segments: tuple[MagicSegment, ...]

    def __post_init__(self) -> None:
        if not self.segments:
            raise ValueError("Magic signature must contain at least one segment")

    def matches(self, content: bytes) -> bool:
        return all(segment.matches(content) for segment in self.segments)


@dataclass(frozen=True, slots=True)
class ArtifactConfirmationRule:
    """How ingest confirms bytes agree with a declared file format."""

    rule: ConfirmationRule = "none"
    signatures: tuple[MagicSignature, ...] = ()

    def __post_init__(self) -> None:
        if self.rule == "magic":
            if not self.signatures:
                raise ValueError("A magic confirmation rule requires a signature")
            return
        if self.signatures:
            raise ValueError("Only a magic confirmation rule may declare signatures")

    def confirms(self, content: bytes) -> bool:
        if self.rule == "none":
            return True
        if self.rule == "magic":
            return any(signature.matches(content) for signature in self.signatures)
        try:
            document = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        if self.rule == "json":
            return isinstance(document, dict)
        return isinstance(document, (dict, list))


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
    extensions: tuple[str, ...] = ()
    confirmation_rule: ArtifactConfirmationRule = ArtifactConfirmationRule()

    def __post_init__(self) -> None:
        paths = [reference.path for reference in self.references]
        if len(paths) != len(set(paths)):
            raise ValueError("Artifact reference paths must be unique")
        if self.references and self.bundle.format != "inline-json":
            raise ValueError(
                "Artifact references currently require the inline-json bundle"
            )
        validate_extension_claims(self.key.id, self.extensions)


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

#[TODO] Review if this is really needed to represent a sequence of artifacts
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


type LibrarySource = Literal["run", "upload"]

_GRAPH_TITLE_MAX_LENGTH = 160
_NODE_TITLE_MAX_LENGTH = 160
_NODE_ID_MAX_LENGTH = 255
_FILENAME_MAX_LENGTH = 255


def _required_text(value: str, *, label: str, max_length: int) -> str:
    text = value.strip()
    if text == "":
        raise ValueError(f"Library provenance {label} must not be blank")
    if len(text) > max_length:
        raise ValueError(
            f"Library provenance {label} must be at most {max_length} characters"
        )
    return text

#[TODO] from_run and from_upload apply validation but it should be moved to the field definitions so its also applied on direct object construction
class LibraryProvenance(BaseModel):
    """Birth record written once when an artifact enters a Workspace Library.

    The run facts are a snapshot of the save gesture: the graph and node titles
    are frozen here so later renames, replacements, or deletions of the source
    never rewrite this row. Nothing in the record is resolved live.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: LibrarySource
    saved_at: datetime
    graph_id: UUID | None = None
    graph_title: str | None = None
    node_id: str | None = None
    node_title: str | None = None
    graph_revision: int | None = None
    execution_id: UUID | None = None
    original_filename: str | None = None

    @field_validator("saved_at")
    @classmethod
    def require_aware_saved_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Library provenance save time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_source_shape(self) -> Self:
        if self.source == "run":
            missing = [
                label
                for label, value in (
                    ("graph id", self.graph_id),
                    ("graph title", self.graph_title),
                    ("node id", self.node_id),
                    ("node title", self.node_title),
                    ("graph revision", self.graph_revision),
                    ("execution id", self.execution_id),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    "A run Library provenance requires " + ", ".join(missing)
                )
            if self.graph_revision is not None and self.graph_revision < 1:
                raise ValueError("Library provenance graph revision must be positive")
            if self.original_filename is not None:
                raise ValueError(
                    "A run Library provenance cannot carry an uploaded filename"
                )
            return self
        if self.original_filename is None:
            raise ValueError("An uploaded Library provenance requires a filename")
        if any(
            value is not None
            for value in (
                self.graph_id,
                self.graph_title,
                self.node_id,
                self.node_title,
                self.graph_revision,
                self.execution_id,
            )
        ):
            raise ValueError(
                "An uploaded Library provenance cannot carry run facts"
            )
        return self

    @classmethod
    def from_run(
        cls,
        *,
        saved_at: datetime,
        graph_id: UUID,
        graph_title: str,
        node_id: str,
        node_title: str,
        graph_revision: int,
        execution_id: UUID,
    ) -> Self:
        return cls(
            source="run",
            saved_at=saved_at,
            graph_id=graph_id,
            graph_title=_required_text(
                graph_title,
                label="graph title",
                max_length=_GRAPH_TITLE_MAX_LENGTH,
            ),
            node_id=_required_text(
                node_id,
                label="node id",
                max_length=_NODE_ID_MAX_LENGTH,
            ),
            node_title=_required_text(
                node_title,
                label="node title",
                max_length=_NODE_TITLE_MAX_LENGTH,
            ),
            graph_revision=graph_revision,
            execution_id=execution_id,
        )

    @classmethod
    def from_upload(cls, *, saved_at: datetime, original_filename: str) -> Self:
        return cls(
            source="upload",
            saved_at=saved_at,
            original_filename=_required_text(
                original_filename,
                label="original filename",
                max_length=_FILENAME_MAX_LENGTH,
            ),
        )


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
    library_provenance: LibraryProvenance | None = None

    def ref(self) -> ArtifactRef:
        return ArtifactRef.from_key(
            artifact_id=self.id,
            key=ArtifactTypeKey(self.artifact_type, self.schema_version),
            content_hash=self.sha256,
        )


if TYPE_CHECKING:
    from grafy_core.ports.artifacts import (
        ArtifactRepositoryPort as ArtifactRepositoryPort,
    )
    from grafy_core.ports.artifacts import (
        UnitOfWorkPort as UnitOfWorkPort,
    )
    from grafy_core.runtime.in_memory import (
        InMemoryArtifactRepository as InMemoryArtifactRepository,
    )
    from grafy_core.runtime.in_memory import (
        InMemoryDataStore as InMemoryDataStore,
    )
    from grafy_core.runtime.in_memory import (
        InMemoryGraphExecutionHistoryRepository as InMemoryGraphExecutionHistoryRepository,
    )
    from grafy_core.runtime.in_memory import (
        InMemoryInvocationCacheRepository as InMemoryInvocationCacheRepository,
    )
    from grafy_core.runtime.in_memory import (
        InMemoryMaterializedNodeOutputsRepository as InMemoryMaterializedNodeOutputsRepository,
    )
    from grafy_core.runtime.in_memory import (
        InMemoryUnitOfWork as InMemoryUnitOfWork,
    )
    from grafy_core.runtime.in_memory import (
        InMemoryUploadRepository as InMemoryUploadRepository,
    )

#[TODO] Remove whatever this is, probably dead code
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
        "InMemoryUploadRepository",
        "InMemoryUnitOfWork",
    }:
        from grafy_core.runtime import in_memory

        return getattr(in_memory, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Artifact",
    "ArtifactBundleContract",
    "ArtifactBundleFormat",
    "ArtifactConfirmationRule",
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
    "InMemoryUploadRepository",
    "InMemoryUnitOfWork",
    "ConfirmationRule",
    "JsonObject",
    "MagicSegment",
    "MagicSignature",
    "MaterializedJsonType",
    "NoConfig",
    "NodeConfig",
    "NodeInput",
    "NodeOutput",
    "UnitOfWorkPort",
    "artifact_id",
    "sequence_id",
    "validate_extension_claims",
]

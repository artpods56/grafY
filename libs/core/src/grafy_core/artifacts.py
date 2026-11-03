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


# [TODO] Artifact types could be typed
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


# [TODO] Review if this is really needed to represent a sequence of artifacts
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


type LibrarySource = Literal["instance", "upload"]

_GRAPH_TITLE_MAX_LENGTH = 160
_NODE_TITLE_MAX_LENGTH = 160
_NODE_ID_MAX_LENGTH = 255
_FILENAME_MAX_LENGTH = 255
_LIBRARY_NAME_MAX_LENGTH = 160


def _required_text(value: str, *, label: str, max_length: int) -> str:
    text = value.strip()
    if text == "":
        raise ValueError(f"Library provenance {label} must not be blank")
    if len(text) > max_length:
        raise ValueError(
            f"Library provenance {label} must be at most {max_length} characters"
        )
    return text


class LibraryProvenance(BaseModel):
    """Immutable source of the exact node result or upload saved to the Library."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: LibrarySource
    saved_at: datetime
    project_id: UUID | None = None
    project_title: str | None = Field(default=None, min_length=1, max_length=160)
    graph_id: str | None = Field(default=None, min_length=1, max_length=255)
    graph_title: str | None = Field(default=None, min_length=1, max_length=160)
    call_path: tuple[str, ...] = ()
    node_id: str | None = Field(default=None, min_length=1, max_length=255)
    node_title: str | None = Field(default=None, min_length=1, max_length=160)
    map_index: int | None = Field(default=None, ge=0)
    result_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    output_port: str | None = Field(default=None, min_length=1, max_length=255)
    item_index: int | None = Field(default=None, ge=0)
    original_filename: str | None = Field(default=None, min_length=1, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("saved_at")
    @classmethod
    def require_aware_saved_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Library provenance save time must be timezone-aware")
        return value

    @field_validator(
        "project_title",
        "graph_id",
        "graph_title",
        "node_id",
        "node_title",
        "output_port",
        "original_filename",
        "name",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("call_path")
    @classmethod
    def validate_call_path(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for segment in value:
            _required_text(segment, label="call path", max_length=255)
        return value

    @model_validator(mode="after")
    def validate_source_shape(self) -> Self:
        instance_fields = (
            self.project_id,
            self.project_title,
            self.graph_id,
            self.graph_title,
            self.node_id,
            self.node_title,
            self.result_fingerprint,
            self.output_port,
        )
        if self.source == "instance":
            if any(value is None for value in instance_fields):
                raise ValueError(
                    "Instance Library provenance requires full instance and result identity"
                )
            if self.original_filename is not None:
                raise ValueError(
                    "Instance Library provenance cannot carry an upload filename"
                )
        else:
            if self.original_filename is None:
                raise ValueError("Upload Library provenance requires a filename")
            if (
                any(
                    value is not None
                    for value in (
                        *instance_fields,
                        self.map_index,
                        self.item_index,
                        self.name,
                    )
                )
                or self.call_path
            ):
                raise ValueError(
                    "Upload Library provenance cannot carry instance facts"
                )
        return self

    @classmethod
    def from_instance(
        cls,
        *,
        saved_at: datetime,
        project_id: UUID,
        project_title: str,
        graph_id: str,
        graph_title: str,
        node_id: str,
        node_title: str,
        result_fingerprint: str,
        output_port: str,
        call_path: tuple[str, ...] = (),
        map_index: int | None = None,
        item_index: int | None = None,
        name: str | None = None,
    ) -> Self:
        return cls(
            source="instance",
            saved_at=saved_at,
            project_id=project_id,
            project_title=project_title,
            graph_id=graph_id,
            graph_title=graph_title,
            node_id=node_id,
            node_title=node_title,
            call_path=call_path,
            map_index=map_index,
            result_fingerprint=result_fingerprint,
            output_port=output_port,
            item_index=item_index,
            name=name,
        )

    @classmethod
    def from_upload(cls, *, saved_at: datetime, original_filename: str) -> Self:
        return cls(
            source="upload", saved_at=saved_at, original_filename=original_filename
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
    "ArtifactTypeKey",
    "ArtifactTypeSpec",
    "ConfirmationRule",
    "JsonObject",
    "MagicSegment",
    "MagicSignature",
    "MaterializedJsonType",
    "NoConfig",
    "NodeConfig",
    "NodeInput",
    "NodeOutput",
    "artifact_id",
    "sequence_id",
    "validate_extension_claims",
]

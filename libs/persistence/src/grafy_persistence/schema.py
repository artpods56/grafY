from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeVar, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import Uuid as SaUuid
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from grafy_core.domain.artifact_outputs import (
    ArtifactOutputValue,
    artifact_outputs_from_storage,
    artifact_outputs_to_storage,
)
from grafy_core.domain.agent_authoring import (
    AgentEnvironmentStatus,
    AgentEventKind,
    AgentEventPayload,
    AgentRunStatus,
    AnchoredPortContract,
    BuildArtifactSet,
    CapabilityManifest,
    DraftNodeStatus,
    GeneratedNodeManifest,
    NodeBuildStatus,
)
from grafy_core.domain.saved_graphs import SavedGraphDocument
from grafy_core.domain.identity import (
    WorkspaceCapability,
    WorkspaceKind,
    WorkspaceRole,
)
from grafy_core.domain.module_library import ModulePublicationState
from grafy_core.domain.templates import TemplateState
from grafy_core.domain.security_audit import (
    SecurityAuditActorKind,
    SecurityAuditOutcome,
)


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


PydanticModelT = TypeVar("PydanticModelT", bound=BaseModel)
StrEnumT = TypeVar("StrEnumT", bound=StrEnum)


class PydanticModelType(TypeDecorator[PydanticModelT]):
    """Persist one domain-owned Pydantic value as canonical JSON."""

    impl = JSON
    cache_ok = True

    def __init__(self, model_type: type[PydanticModelT]) -> None:
        super().__init__()
        self.model_type = model_type

    def process_bind_param(
        self,
        value: PydanticModelT | None,
        dialect: Dialect,
    ) -> dict[str, object] | None:
        del dialect
        if value is None:
            return None
        return value.model_dump(mode="json")

    def process_result_value(
        self,
        value: object | None,
        dialect: Dialect,
    ) -> PydanticModelT | None:
        del dialect
        if value is None:
            return None
        return self.model_type.model_validate(value)


class DomainStrEnumType(TypeDecorator[StrEnumT]):
    """Round-trip a domain StrEnum without leaking strings into aggregates."""

    impl = String
    cache_ok = True

    def __init__(self, enum_type: type[StrEnumT], *, length: int) -> None:
        super().__init__(length=length)
        self.enum_type = enum_type
        self.length = length

    def process_bind_param(
        self,
        value: StrEnumT | None,
        dialect: Dialect,
    ) -> str | None:
        del dialect
        return None if value is None else self.enum_type(value).value

    def process_result_value(
        self,
        value: str | None,
        dialect: Dialect,
    ) -> StrEnumT | None:
        del dialect
        return None if value is None else self.enum_type(value)


class UUIDTupleType(TypeDecorator[tuple[UUID, ...]]):
    impl = JSON
    cache_ok = True

    def process_bind_param(
        self,
        value: tuple[UUID, ...] | None,
        dialect: Dialect,
    ) -> list[str] | None:
        del dialect
        return None if value is None else [str(item) for item in value]

    def process_result_value(
        self,
        value: object | None,
        dialect: Dialect,
    ) -> tuple[UUID, ...] | None:
        del dialect
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("Stored UUID tuple is not a JSON string list")
        items: list[str] = []
        for item in cast(list[object], value):
            if not isinstance(item, str):
                raise ValueError("Stored UUID tuple is not a JSON string list")
            items.append(item)
        return tuple(UUID(item) for item in items)


class SavedGraphDocumentType(TypeDecorator[SavedGraphDocument]):
    impl = JSON
    cache_ok = True

    def process_bind_param(
        self,
        value: SavedGraphDocument | None,
        dialect: Dialect,
    ) -> dict[str, object] | None:
        del dialect
        if value is None:
            return None
        return value.model_dump(mode="json")

    def process_result_value(
        self,
        value: object | None,
        dialect: Dialect,
    ) -> SavedGraphDocument | None:
        del dialect
        if value is None:
            return None
        return SavedGraphDocument.model_validate(value)


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTCDateTime requires a timezone-aware datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        del dialect
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class ArtifactOutputsType(
    TypeDecorator[dict[str, ArtifactOutputValue]],
):
    impl = JSON
    cache_ok = True

    def process_bind_param(
        self,
        value: dict[str, ArtifactOutputValue] | None,
        dialect: Dialect,
    ) -> list[dict[str, object]] | None:
        del dialect
        if value is None:
            return None
        return artifact_outputs_to_storage(value)

    def process_result_value(
        self,
        value: object | None,
        dialect: Dialect,
    ) -> dict[str, ArtifactOutputValue] | None:
        del dialect
        if value is None:
            return None
        return artifact_outputs_from_storage(value)


class WorkspaceCapabilityTupleType(TypeDecorator[tuple[WorkspaceCapability, ...]]):
    impl = JSON
    cache_ok = True

    def process_bind_param(
        self,
        value: tuple[WorkspaceCapability, ...] | None,
        dialect: Dialect,
    ) -> list[str] | None:
        del dialect
        return None if value is None else [capability.value for capability in value]

    def process_result_value(
        self,
        value: object | None,
        dialect: Dialect,
    ) -> tuple[WorkspaceCapability, ...] | None:
        del dialect
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("Stored string tuple is not a JSON string list")
        items: list[str] = []
        for item in cast(list[object], value):
            if not isinstance(item, str):
                raise ValueError("Stored string tuple is not a JSON string list")
            items.append(item)
        try:
            return tuple(WorkspaceCapability(item) for item in items)
        except ValueError as exc:
            raise ValueError("Stored workspace capability is unknown") from exc


class WorkspaceKindType(TypeDecorator[WorkspaceKind]):
    impl = String(16)
    cache_ok = True

    def process_bind_param(
        self,
        value: WorkspaceKind | None,
        dialect: Dialect,
    ) -> str | None:
        del dialect
        return None if value is None else WorkspaceKind(value).value

    def process_result_value(
        self,
        value: str | None,
        dialect: Dialect,
    ) -> WorkspaceKind | None:
        del dialect
        return None if value is None else WorkspaceKind(value)


class WorkspaceRoleType(TypeDecorator[WorkspaceRole]):
    impl = String(16)
    cache_ok = True

    def process_bind_param(
        self,
        value: WorkspaceRole | None,
        dialect: Dialect,
    ) -> str | None:
        del dialect
        return None if value is None else WorkspaceRole(value).value

    def process_result_value(
        self,
        value: str | None,
        dialect: Dialect,
    ) -> WorkspaceRole | None:
        del dialect
        return None if value is None else WorkspaceRole(value)


class ModulePublicationStateType(TypeDecorator[ModulePublicationState]):
    impl = String(32)
    cache_ok = True

    def process_bind_param(
        self,
        value: ModulePublicationState | None,
        dialect: Dialect,
    ) -> str | None:
        del dialect
        return None if value is None else ModulePublicationState(value).value

    def process_result_value(
        self,
        value: str | None,
        dialect: Dialect,
    ) -> ModulePublicationState | None:
        del dialect
        return None if value is None else ModulePublicationState(value)


class TemplateStateType(TypeDecorator[TemplateState]):
    impl = String(16)
    cache_ok = True

    def process_bind_param(
        self,
        value: TemplateState | None,
        dialect: Dialect,
    ) -> str | None:
        del dialect
        return None if value is None else TemplateState(value).value

    def process_result_value(
        self,
        value: str | None,
        dialect: Dialect,
    ) -> TemplateState | None:
        del dialect
        return None if value is None else TemplateState(value)


class SecurityAuditActorKindType(TypeDecorator[SecurityAuditActorKind]):
    impl = String(24)
    cache_ok = True

    def process_bind_param(
        self,
        value: SecurityAuditActorKind | None,
        dialect: Dialect,
    ) -> str | None:
        del dialect
        return None if value is None else SecurityAuditActorKind(value).value

    def process_result_value(
        self,
        value: str | None,
        dialect: Dialect,
    ) -> SecurityAuditActorKind | None:
        del dialect
        return None if value is None else SecurityAuditActorKind(value)


class SecurityAuditOutcomeType(TypeDecorator[SecurityAuditOutcome]):
    impl = String(16)
    cache_ok = True

    def process_bind_param(
        self,
        value: SecurityAuditOutcome | None,
        dialect: Dialect,
    ) -> str | None:
        del dialect
        return None if value is None else SecurityAuditOutcome(value).value

    def process_result_value(
        self,
        value: str | None,
        dialect: Dialect,
    ) -> SecurityAuditOutcome | None:
        del dialect
        return None if value is None else SecurityAuditOutcome(value)


graph_folders = Table(
    "graph_folders",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", String(160), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    UniqueConstraint("workspace_id", "id", name="uq_graph_folders_workspace_id_id"),
    UniqueConstraint(
        "workspace_id",
        "name",
        name="uq_graph_folders_workspace_id_name",
    ),
    Index("ix_graph_folders_workspace_name", "workspace_id", "name"),
)


saved_graphs = Table(
    "saved_graphs",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "created_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("name", String(160), nullable=False),
    Column("document", SavedGraphDocumentType(), nullable=False),
    Column("revision", Integer, nullable=False, default=1),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    UniqueConstraint("workspace_id", "id", name="uq_saved_graphs_workspace_id_id"),
    Index("ix_saved_graphs_workspace_updated_at", "workspace_id", "updated_at"),
    Index("ix_saved_graphs_workspace_id", "workspace_id", "id"),
)


saved_graph_revisions = Table(
    "saved_graph_revisions",
    metadata,
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        primary_key=True,
    ),
    Column(
        "graph_id",
        SaUuid(as_uuid=True),
        primary_key=True,
    ),
    Column("revision", Integer, primary_key=True),
    Column("name", String(160), nullable=False),
    Column("document", SavedGraphDocumentType(), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id"),
        ("saved_graphs.workspace_id", "saved_graphs.id"),
        ondelete="CASCADE",
    ),
    Index(
        "ix_saved_graph_revisions_workspace_graph_revision",
        "workspace_id",
        "graph_id",
        "revision",
    ),
)


graph_organizations = Table(
    "graph_organizations",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("graph_id", SaUuid(as_uuid=True), primary_key=True),
    Column("folder_id", SaUuid(as_uuid=True), nullable=True),
    Column("archived_at", UTCDateTime(), nullable=True),
    Column("updated_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id"),
        ("saved_graphs.workspace_id", "saved_graphs.id"),
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "folder_id"),
        ("graph_folders.workspace_id", "graph_folders.id"),
        ondelete="RESTRICT",
    ),
    Index(
        "ix_graph_organizations_workspace_folder_archived",
        "workspace_id",
        "folder_id",
        "archived_at",
    ),
)


user_graph_states = Table(
    "user_graph_states",
    metadata,
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        primary_key=True,
    ),
    Column("graph_id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("starred", Boolean, nullable=False, default=False),
    Column("last_opened_at", UTCDateTime(), nullable=True),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id"),
        ("saved_graphs.workspace_id", "saved_graphs.id"),
        ondelete="CASCADE",
    ),
    Index(
        "ix_user_graph_states_user_starred",
        "user_id",
        "starred",
    ),
    Index(
        "ix_user_graph_states_user_last_opened",
        "user_id",
        "last_opened_at",
    ),
)


artifact_objects = Table(
    "artifact_objects",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("artifact_type", String(255), nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("content_type", String(255), nullable=False),
    Column("storage_backend", String(40), nullable=False),
    Column("bucket", String(255), nullable=True),
    Column("object_key", String(2048), nullable=True),
    Column("inline_payload", JSON, nullable=True),
    Column("byte_size", BigInteger, nullable=True),
    Column("sha256", String(64), nullable=True),
    Column("metadata", JSON, nullable=False),
    UniqueConstraint("workspace_id", "id", name="uq_artifact_objects_workspace_id_id"),
    Index(
        "ix_artifact_objects_workspace_type",
        "workspace_id",
        "artifact_type",
        "schema_version",
    ),
    Index("ix_artifact_objects_workspace_sha256", "workspace_id", "sha256"),
)


invocation_cache_entries = Table(
    "invocation_cache_entries",
    metadata,
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("key_sha256", String(64), primary_key=True),
    Column("generation", SaUuid(as_uuid=True), nullable=False),
    Column("outputs", ArtifactOutputsType(), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
)


materialized_node_outputs = Table(
    "materialized_node_outputs",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "graph_id",
        SaUuid(as_uuid=True),
        primary_key=True,
    ),
    Column("graph_revision", Integer, primary_key=True),
    Column("node_id", String(255), primary_key=True),
    Column("workflow_run_id", SaUuid(as_uuid=True), nullable=False),
    Column("outputs", ArtifactOutputsType(), nullable=False),
    Column("materialized_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id", "graph_revision"),
        (
            "saved_graph_revisions.workspace_id",
            "saved_graph_revisions.graph_id",
            "saved_graph_revisions.revision",
        ),
        ondelete="CASCADE",
    ),
    Index(
        "ix_materialized_node_outputs_graph_revision",
        "workspace_id",
        "graph_id",
        "graph_revision",
        "materialized_at",
    ),
)


graph_executions = Table(
    "graph_executions",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), nullable=False),
    Column("execution_id", SaUuid(as_uuid=True), primary_key=True),
    Column("graph_id", SaUuid(as_uuid=True), nullable=False),
    Column("graph_revision", Integer, nullable=False),
    Column("status", String(24), nullable=False),
    Column("scope", String(32), nullable=False),
    Column("workflow_run_id", SaUuid(as_uuid=True), nullable=True),
    Column("error", Text, nullable=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("started_at", UTCDateTime(), nullable=True),
    Column("finished_at", UTCDateTime(), nullable=True),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id", "graph_revision"),
        (
            "saved_graph_revisions.workspace_id",
            "saved_graph_revisions.graph_id",
            "saved_graph_revisions.revision",
        ),
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "workspace_id",
        "execution_id",
        name="uq_graph_executions_workspace_id_execution_id",
    ),
    Index(
        "ix_graph_executions_graph_created",
        "workspace_id",
        "graph_id",
        "created_at",
        "execution_id",
    ),
    Index(
        "ix_graph_executions_graph_revision_created",
        "workspace_id",
        "graph_id",
        "graph_revision",
        "created_at",
        "execution_id",
    ),
    Index("ix_graph_executions_workspace_status", "workspace_id", "status"),
)


graph_execution_requested_nodes = Table(
    "graph_execution_requested_nodes",
    metadata,
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        primary_key=True,
    ),
    Column(
        "execution_id",
        SaUuid(as_uuid=True),
        primary_key=True,
    ),
    Column("node_id", String(255), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "execution_id"),
        ("graph_executions.workspace_id", "graph_executions.execution_id"),
        name="fk_exec_req_nodes_workspace_execution",
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "workspace_id",
        "execution_id",
        "position",
        name="uq_graph_execution_requested_nodes_execution_position",
    ),
    Index(
        "ix_graph_execution_requested_nodes_node_execution",
        "workspace_id",
        "node_id",
        "execution_id",
    ),
)


graph_execution_node_results = Table(
    "graph_execution_node_results",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "execution_id",
        SaUuid(as_uuid=True),
        primary_key=True,
    ),
    Column("node_id", String(255), primary_key=True),
    Column("position", Integer, nullable=False),
    Column("status", String(16), nullable=False),
    Column("outputs", ArtifactOutputsType(), nullable=False),
    Column("artifact_count", Integer, nullable=False),
    Column("error", Text, nullable=True),
    Column("completed_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "execution_id"),
        ("graph_executions.workspace_id", "graph_executions.execution_id"),
        name="fk_exec_result_nodes_workspace_execution",
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "workspace_id",
        "execution_id",
        "position",
        name="uq_graph_execution_node_results_execution_position",
    ),
    Index(
        "ix_graph_execution_node_results_node_execution",
        "workspace_id",
        "node_id",
        "execution_id",
    ),
)


node_secrets = Table(
    "node_secrets",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "graph_id",
        SaUuid(as_uuid=True),
        primary_key=True,
    ),
    Column("node_id", String(255), primary_key=True),
    Column("name", String(255), primary_key=True),
    Column("operator_id", String(255), nullable=False),
    Column("operator_version", Integer, nullable=False),
    Column("key_id", String(64), nullable=False),
    Column("aad_version", Integer, nullable=False),
    Column("dependency_sha256", String(64), nullable=False),
    Column("nonce", LargeBinary(12), nullable=False),
    Column("ciphertext", LargeBinary(), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id"),
        ("saved_graphs.workspace_id", "saved_graphs.id"),
        ondelete="CASCADE",
    ),
    CheckConstraint("aad_version IN (1, 2)", name="ck_node_secrets_aad_version"),
    Index("ix_node_secrets_workspace_graph", "workspace_id", "graph_id"),
)


staged_uploads = Table(
    "staged_uploads",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("upload_key", String(1024), primary_key=True),
    Column(
        "created_by_user_id",
        SaUuid(as_uuid=True),
        nullable=True,
    ),
    Column("original_filename", String(255), nullable=False),
    Column("byte_size", BigInteger, nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id",),
        ("workspaces.id",),
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ("created_by_user_id",),
        ("users.id",),
        ondelete="SET NULL",
    ),
    CheckConstraint("byte_size >= 0", name="ck_staged_uploads_byte_size_nonnegative"),
    CheckConstraint(
        "length(original_filename) BETWEEN 1 AND 255",
        name="ck_staged_uploads_original_filename_bounded",
    ),
    CheckConstraint(
        "length(upload_key) BETWEEN 1 AND 1024",
        name="ck_staged_uploads_upload_key_bounded",
    ),
    CheckConstraint(
        "upload_key NOT IN ('.', '..')",
        name="ck_staged_uploads_upload_key_not_dot_path",
    ),
    CheckConstraint(
        "upload_key NOT LIKE '%/%'",
        name="ck_staged_uploads_upload_key_no_slash",
    ),
    CheckConstraint(
        "instr(upload_key, char(92)) = 0",
        name="ck_staged_uploads_upload_key_no_backslash",
    ).ddl_if(dialect="sqlite"),
    CheckConstraint(
        "position(chr(92) in upload_key) = 0",
        name="ck_staged_uploads_upload_key_no_backslash",
    ).ddl_if(dialect="postgresql"),
    CheckConstraint(
        "instr(upload_key, char(0)) = 0",
        name="ck_staged_uploads_upload_key_no_nul",
    ).ddl_if(dialect="sqlite"),
    Index("ix_staged_uploads_workspace_created_at", "workspace_id", "created_at"),
)


users = Table(
    "users",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column("email", String(320), nullable=True),
    Column("display_name", String(160), nullable=True),
    Column("active", Boolean, nullable=False, default=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    Index("ix_users_active_updated_at", "active", "updated_at"),
)


oidc_identities = Table(
    "oidc_identities",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("issuer", String(2048), nullable=False),
    Column("subject", String(512), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    UniqueConstraint("issuer", "subject", name="uq_oidc_identities_issuer_subject"),
    Index("ix_oidc_identities_user_id", "user_id"),
)


oidc_login_transactions = Table(
    "oidc_login_transactions",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column("state_digest", LargeBinary(64), nullable=False),
    Column("nonce_digest", LargeBinary(64), nullable=False),
    Column("encrypted_pkce_verifier", LargeBinary(), nullable=False),
    Column("pkce_key_version", Integer, nullable=False),
    Column("return_path", String(2048), nullable=False),
    Column("expires_at", UTCDateTime(), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("consumed_at", UTCDateTime(), nullable=True),
    CheckConstraint(
        "pkce_key_version >= 1",
        name="ck_oidc_login_transactions_pkce_key_version_positive",
    ),
    Index(
        "ix_oidc_login_transactions_expiry_consumed",
        "expires_at",
        "consumed_at",
    ),
)


workspaces = Table(
    "workspaces",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column("slug", String(80), nullable=False),
    Column("name", String(160), nullable=False),
    Column("kind", WorkspaceKindType(), nullable=False),
    Column(
        "personal_owner_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    UniqueConstraint("slug", name="uq_workspaces_slug"),
    UniqueConstraint(
        "personal_owner_user_id",
        name="uq_workspaces_personal_owner_user_id",
    ),
    CheckConstraint(
        "length(slug) BETWEEN 1 AND 80 AND "
        "slug = lower(trim(slug)) AND "
        "slug NOT LIKE '-%' AND slug NOT LIKE '%-'",
        name="ck_workspaces_slug_normalized",
    ),
    CheckConstraint(
        "kind IN ('personal', 'shared')",
        name="ck_workspaces_kind_choice",
    ),
    CheckConstraint(
        "(kind = 'personal' AND personal_owner_user_id IS NOT NULL) OR "
        "(kind = 'shared' AND personal_owner_user_id IS NULL)",
        name="ck_workspaces_personal_owner_shape",
    ),
    Index("ix_workspaces_kind", "kind"),
)


workspace_memberships = Table(
    "workspace_memberships",
    metadata,
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("role", WorkspaceRoleType(), nullable=False),
    Column("authorization_version", BigInteger, nullable=False, default=1),
    Column("revoked_at", UTCDateTime(), nullable=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    CheckConstraint(
        "role IN ('viewer', 'editor', 'owner')",
        name="ck_workspace_memberships_role_choice",
    ),
    CheckConstraint(
        "authorization_version >= 1",
        name="ck_workspace_memberships_authorization_version_positive",
    ),
    Index(
        "ix_workspace_memberships_user_active",
        "user_id",
        "revoked_at",
    ),
    Index(
        "ix_workspace_memberships_workspace_role_active",
        "workspace_id",
        "role",
        "revoked_at",
    ),
)


oidc_bootstrap_owner_mappings = Table(
    "oidc_bootstrap_owner_mappings",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("issuer", String(2048), nullable=False),
    Column("subject", String(512), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("consumed_at", UTCDateTime(), nullable=True),
    UniqueConstraint(
        "workspace_id",
        name="uq_oidc_bootstrap_owner_mappings_workspace_id",
    ),
    Index(
        "ix_oidc_bootstrap_owner_mappings_unconsumed",
        "workspace_id",
        "consumed_at",
    ),
)


auth_sessions = Table(
    "auth_sessions",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("secret_digest", LargeBinary(64), nullable=False),
    Column("csrf_digest", LargeBinary(64), nullable=False),
    Column("expires_at", UTCDateTime(), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("last_used_at", UTCDateTime(), nullable=True),
    Column("revoked_at", UTCDateTime(), nullable=True),
    UniqueConstraint("secret_digest", name="uq_auth_sessions_secret_digest"),
    Index("ix_auth_sessions_user_revoked", "user_id", "revoked_at"),
    Index("ix_auth_sessions_expiry_revoked", "expires_at", "revoked_at"),
)


personal_access_tokens = Table(
    "personal_access_tokens",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("public_prefix", String(32), nullable=False),
    Column("secret_digest", LargeBinary(64), nullable=False),
    Column("label", String(160), nullable=False),
    Column("scopes", WorkspaceCapabilityTupleType(), nullable=False),
    Column("expires_at", UTCDateTime(), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("last_used_at", UTCDateTime(), nullable=True),
    Column("revoked_at", UTCDateTime(), nullable=True),
    UniqueConstraint("public_prefix", name="uq_personal_access_tokens_public_prefix"),
    UniqueConstraint("secret_digest", name="uq_personal_access_tokens_secret_digest"),
    Index(
        "ix_personal_access_tokens_workspace_revoked",
        "workspace_id",
        "revoked_at",
    ),
    Index(
        "ix_personal_access_tokens_expiry_revoked",
        "expires_at",
        "revoked_at",
    ),
)


security_audit_events = Table(
    "security_audit_events",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column("occurred_at", UTCDateTime(), nullable=False),
    Column("actor_kind", SecurityAuditActorKindType(), nullable=False),
    Column("user_id", SaUuid(as_uuid=True), nullable=True),
    Column("credential_reference", String(120), nullable=True),
    Column("workspace_id", SaUuid(as_uuid=True), nullable=True),
    Column("resource_type", String(80), nullable=True),
    Column("resource_id", String(255), nullable=True),
    Column("operation", String(120), nullable=False),
    Column("outcome", SecurityAuditOutcomeType(), nullable=False),
    Column("error_code", String(80), nullable=True),
    CheckConstraint(
        "actor_kind IN ('authenticated', 'unauthenticated', 'system')",
        name="ck_security_audit_events_actor_kind_choice",
    ),
    CheckConstraint(
        "outcome IN ('success', 'failure')",
        name="ck_security_audit_events_outcome_choice",
    ),
    Index(
        "ix_security_audit_events_workspace_occurred_at",
        "workspace_id",
        "occurred_at",
    ),
    Index(
        "ix_security_audit_events_actor_occurred_at",
        "actor_kind",
        "user_id",
        "occurred_at",
    ),
    Index(
        "ix_security_audit_events_operation_occurred_at",
        "operation",
        "occurred_at",
    ),
    Index("ix_security_audit_events_retention", "occurred_at"),
)


collaborative_graph_heads = Table(
    "collaborative_graph_heads",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("graph_id", SaUuid(as_uuid=True), primary_key=True),
    Column("room_epoch", SaUuid(as_uuid=True), nullable=False),
    Column("collaboration_sequence", Integer, nullable=False),
    Column("checkpoint_sequence", Integer, nullable=False),
    Column("checkpoint_revision", Integer, nullable=False),
    Column("name", String(160), nullable=False),
    Column("document", SavedGraphDocumentType(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    CheckConstraint(
        "collaboration_sequence >= 0",
        name="ck_collaborative_graph_heads_collaboration_sequence_nonneg",
    ),
    CheckConstraint(
        "checkpoint_sequence >= 0",
        name="ck_collaborative_graph_heads_checkpoint_sequence_nonneg",
    ),
    CheckConstraint(
        "checkpoint_sequence <= collaboration_sequence",
        name="ck_collaborative_graph_heads_checkpoint_lte_head",
    ),
    CheckConstraint(
        "checkpoint_revision >= 1",
        name="ck_collaborative_graph_heads_checkpoint_revision_positive",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id"),
        ("saved_graphs.workspace_id", "saved_graphs.id"),
        ondelete="CASCADE",
    ),
    Index(
        "ix_collaborative_graph_heads_workspace_updated_at",
        "workspace_id",
        "updated_at",
    ),
)


graph_command_journal = Table(
    "graph_command_journal",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("graph_id", SaUuid(as_uuid=True), primary_key=True),
    Column("accepted_sequence", Integer, primary_key=True),
    Column("room_epoch", SaUuid(as_uuid=True), nullable=False),
    Column("command_id", SaUuid(as_uuid=True), nullable=False),
    Column("command_hmac", LargeBinary(64), nullable=False),
    Column("hmac_key_version", Integer, nullable=False),
    Column("actor_kind", String(32), nullable=False),
    Column("actor_user_id", SaUuid(as_uuid=True), nullable=True),
    Column("graph_room_session_id", SaUuid(as_uuid=True), nullable=True),
    Column("authorization_version", Integer, nullable=True),
    Column("command_kind", String(80), nullable=False),
    Column("command_payload", JSON, nullable=False),
    Column("accepted_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id"),
        (
            "collaborative_graph_heads.workspace_id",
            "collaborative_graph_heads.graph_id",
        ),
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "workspace_id",
        "graph_id",
        "command_id",
        name="uq_graph_command_journal_command_id",
    ),
)


graph_command_receipts = Table(
    "graph_command_receipts",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("graph_id", SaUuid(as_uuid=True), primary_key=True),
    Column("command_id", SaUuid(as_uuid=True), primary_key=True),
    Column("command_hmac", LargeBinary(64), nullable=False),
    Column("hmac_key_version", Integer, nullable=False),
    Column("actor_kind", String(32), nullable=False),
    Column("actor_user_id", SaUuid(as_uuid=True), nullable=True),
    Column("room_epoch", SaUuid(as_uuid=True), nullable=False),
    Column("accepted_sequence", Integer, nullable=False),
    Column("outcome", String(40), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id"),
        (
            "collaborative_graph_heads.workspace_id",
            "collaborative_graph_heads.graph_id",
        ),
        ondelete="CASCADE",
    ),
)


graph_checkpoint_mappings = Table(
    "graph_checkpoint_mappings",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("graph_id", SaUuid(as_uuid=True), primary_key=True),
    Column("room_epoch", SaUuid(as_uuid=True), primary_key=True),
    Column("collaboration_sequence", Integer, primary_key=True),
    Column("saved_revision", Integer, nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id"),
        (
            "collaborative_graph_heads.workspace_id",
            "collaborative_graph_heads.graph_id",
        ),
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id", "saved_revision"),
        (
            "saved_graph_revisions.workspace_id",
            "saved_graph_revisions.graph_id",
            "saved_graph_revisions.revision",
        ),
        ondelete="RESTRICT",
    ),
)


graph_execution_idempotency = Table(
    "graph_execution_idempotency",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("graph_id", SaUuid(as_uuid=True), primary_key=True),
    Column("client_request_id", SaUuid(as_uuid=True), primary_key=True),
    Column("request_hmac", LargeBinary(64), nullable=False),
    Column("hmac_key_version", Integer, nullable=False),
    Column("actor_user_id", SaUuid(as_uuid=True), nullable=False),
    Column("room_epoch", SaUuid(as_uuid=True), nullable=False),
    Column("head_sequence", Integer, nullable=False),
    Column("execution_id", SaUuid(as_uuid=True), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id"),
        (
            "collaborative_graph_heads.workspace_id",
            "collaborative_graph_heads.graph_id",
        ),
        ondelete="CASCADE",
    ),
)


graph_active_execution_slots = Table(
    "graph_active_execution_slots",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("graph_id", SaUuid(as_uuid=True), primary_key=True),
    Column("execution_id", SaUuid(as_uuid=True), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id"),
        (
            "collaborative_graph_heads.workspace_id",
            "collaborative_graph_heads.graph_id",
        ),
        ondelete="CASCADE",
    ),
)


modules = Table(
    "modules",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("source_graph_id", SaUuid(as_uuid=True), nullable=False),
    Column("name", String(160), nullable=False),
    Column("description", String(1000), nullable=True),
    Column("publication_state", ModulePublicationStateType(), nullable=False),
    Column("current_library_release", Integer, nullable=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    UniqueConstraint("workspace_id", "id", name="uq_modules_workspace_id_id"),
    UniqueConstraint(
        "workspace_id",
        "source_graph_id",
        name="uq_modules_workspace_source_graph",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "source_graph_id"),
        ("saved_graphs.workspace_id", "saved_graphs.id"),
        name="fk_modules_source_graph_id_saved_graphs",
    ),
    CheckConstraint(
        "publication_state IN ('published', 'deprecated', 'withdrawn')",
        name="module_publication_state",
    ),
    CheckConstraint(
        "current_library_release IS NULL OR current_library_release >= 1",
        name="module_current_library_release",
    ),
    Index("ix_modules_workspace_updated_at", "workspace_id", "updated_at"),
)


module_releases = Table(
    "module_releases",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("module_id", SaUuid(as_uuid=True), primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("source_graph_id", SaUuid(as_uuid=True), nullable=False),
    Column("published_at", UTCDateTime(), nullable=False),
    Column(
        "published_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    ForeignKeyConstraint(
        ("workspace_id", "module_id"),
        ("modules.workspace_id", "modules.id"),
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "source_graph_id", "revision"),
        (
            "saved_graph_revisions.workspace_id",
            "saved_graph_revisions.graph_id",
            "saved_graph_revisions.revision",
        ),
        ondelete="RESTRICT",
        name="fk_module_releases_saved_graph_revision",
    ),
    CheckConstraint("revision >= 1", name="module_release_revision"),
    Index(
        "ix_module_releases_workspace_module_revision",
        "workspace_id",
        "module_id",
        "revision",
    ),
)


templates = Table(
    "templates",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("source_graph_id", SaUuid(as_uuid=True), nullable=False),
    Column("source_revision", Integer, nullable=False),
    Column("source_graph_name", String(160), nullable=False),
    Column("snapshot_document", SavedGraphDocumentType(), nullable=False),
    Column("name", String(160), nullable=False),
    Column("description", String(1000), nullable=True),
    Column("state", TemplateStateType(), nullable=False),
    Column(
        "created_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    UniqueConstraint("workspace_id", "id", name="uq_templates_workspace_id_id"),
    CheckConstraint("source_revision >= 1", name="template_source_revision"),
    CheckConstraint(
        "state IN ('active', 'archived')",
        name="template_state",
    ),
    Index("ix_templates_workspace_name", "workspace_id", "name"),
    Index("ix_templates_workspace_updated_at", "workspace_id", "updated_at"),
)


agent_environments = Table(
    "agent_environments",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("name", String(160), nullable=False),
    Column("profile_id", String(255), nullable=False),
    Column("provider", String(255), nullable=False),
    Column(
        "status",
        DomainStrEnumType(AgentEnvironmentStatus, length=32),
        nullable=False,
    ),
    Column("provider_environment_id", String(1024), nullable=True),
    Column("provisioning_owner", String(255), nullable=True),
    Column("provisioning_token", SaUuid(as_uuid=True), nullable=True),
    Column("provisioning_expires_at", UTCDateTime(), nullable=True),
    Column("provisioning_fencing_token", BigInteger, nullable=False),
    Column("active_run_id", SaUuid(as_uuid=True), nullable=True),
    Column("failure_message", Text, nullable=True),
    Column(
        "created_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    Column("last_used_at", UTCDateTime(), nullable=True),
    UniqueConstraint(
        "workspace_id",
        "id",
        name="uq_agent_environments_workspace_id_id",
    ),
    UniqueConstraint(
        "workspace_id",
        "name",
        name="uq_agent_environments_workspace_name",
    ),
    CheckConstraint(
        "status IN ('provisioning', 'creating', 'ready', 'suspended', 'failed', "
        "'archived')",
        name="status",
    ),
    CheckConstraint(
        "provisioning_fencing_token >= 0",
        name="provisioning_fencing_token",
    ),
    Index(
        "ix_agent_environments_provision_queue",
        "status",
        "provisioning_expires_at",
        "created_at",
        "id",
    ),
    Index(
        "ix_agent_environments_workspace_updated",
        "workspace_id",
        "updated_at",
    ),
)


agent_threads = Table(
    "agent_threads",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("environment_id", SaUuid(as_uuid=True), nullable=False),
    Column("title", String(160), nullable=False),
    Column("event_sequence", BigInteger, nullable=False),
    Column(
        "created_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "environment_id"),
        ("agent_environments.workspace_id", "agent_environments.id"),
        name="fk_agent_threads_environment",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "workspace_id",
        "id",
        name="uq_agent_threads_workspace_id_id",
    ),
    UniqueConstraint(
        "workspace_id",
        "id",
        "environment_id",
        name="uq_agent_threads_workspace_id_environment",
    ),
    CheckConstraint("event_sequence >= 0", name="event_sequence"),
    Index("ix_agent_threads_workspace_updated", "workspace_id", "updated_at"),
)


draft_nodes = Table(
    "draft_nodes",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("thread_id", SaUuid(as_uuid=True), nullable=False),
    Column("graph_id", SaUuid(as_uuid=True), nullable=False),
    Column("title", String(160), nullable=False),
    Column("description", String(1000), nullable=False),
    Column("prompt", Text, nullable=False),
    Column(
        "status",
        DomainStrEnumType(DraftNodeStatus, length=32),
        nullable=False,
    ),
    Column(
        "anchor",
        PydanticModelType(AnchoredPortContract),
        nullable=False,
    ),
    Column("build_attempt_number", Integer, nullable=False),
    Column("published_revision", Integer, nullable=False),
    Column(
        "created_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id"),
        ("saved_graphs.workspace_id", "saved_graphs.id"),
        name="fk_draft_nodes_graph",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "thread_id"),
        ("agent_threads.workspace_id", "agent_threads.id"),
        name="fk_draft_nodes_thread",
        ondelete="CASCADE",
    ),
    UniqueConstraint("workspace_id", "id", name="uq_draft_nodes_workspace_id_id"),
    UniqueConstraint(
        "workspace_id",
        "id",
        "thread_id",
        name="uq_draft_nodes_workspace_id_thread",
    ),
    CheckConstraint("build_attempt_number >= 0", name="build_attempt_number"),
    CheckConstraint("published_revision >= 0", name="published_revision"),
    CheckConstraint(
        "status IN ('draft', 'authoring', 'awaiting_approval', 'published', "
        "'failed', 'cancelled')",
        name="status",
    ),
    Index("ix_draft_nodes_workspace_graph", "workspace_id", "graph_id"),
    Index(
        "ix_draft_nodes_workspace_thread",
        "workspace_id",
        "thread_id",
        "updated_at",
    ),
)


agent_runs = Table(
    "agent_runs",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("thread_id", SaUuid(as_uuid=True), nullable=False),
    Column("environment_id", SaUuid(as_uuid=True), nullable=False),
    Column("target_draft_ids", UUIDTupleType(), nullable=False),
    Column("instructions", Text, nullable=False),
    Column("idempotency_key", String(255), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column(
        "created_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("continued_from_run_id", SaUuid(as_uuid=True), nullable=True),
    Column(
        "status",
        DomainStrEnumType(AgentRunStatus, length=24),
        nullable=False,
    ),
    Column("attempt", Integer, nullable=False),
    Column("lease_owner", String(255), nullable=True),
    Column("lease_token", SaUuid(as_uuid=True), nullable=True),
    Column("lease_expires_at", UTCDateTime(), nullable=True),
    Column("lease_heartbeat_at", UTCDateTime(), nullable=True),
    Column("fencing_token", BigInteger, nullable=False),
    Column("cancellation_requested_at", UTCDateTime(), nullable=True),
    Column("terminal_error", Text, nullable=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "thread_id", "environment_id"),
        (
            "agent_threads.workspace_id",
            "agent_threads.id",
            "agent_threads.environment_id",
        ),
        name="fk_agent_runs_thread_environment",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "continued_from_run_id"),
        ("agent_runs.workspace_id", "agent_runs.id"),
        name="fk_agent_runs_continued_from_run",
        ondelete="CASCADE",
    ),
    UniqueConstraint("workspace_id", "id", name="uq_agent_runs_workspace_id_id"),
    UniqueConstraint(
        "workspace_id",
        "id",
        "thread_id",
        name="uq_agent_runs_workspace_id_thread",
    ),
    UniqueConstraint(
        "workspace_id",
        "idempotency_key",
        name="uq_agent_runs_workspace_idempotency",
    ),
    CheckConstraint("attempt >= 0", name="attempt"),
    CheckConstraint("fencing_token >= 0", name="fencing_token"),
    CheckConstraint(
        "status IN ('queued', 'claimed', 'running', 'awaiting_approval', "
        "'completed', 'failed', 'cancelling', 'cancelled', 'interrupting', "
        "'interrupted')",
        name="status",
    ),
    Index(
        "uq_agent_runs_active_environment",
        "workspace_id",
        "environment_id",
        unique=True,
        postgresql_where=text(
            "status IN ('claimed', 'running', 'cancelling', 'interrupting')"
        ),
        sqlite_where=text(
            "status IN ('claimed', 'running', 'cancelling', 'interrupting')"
        ),
    ),
    Index("ix_agent_runs_claim_queue", "status", "created_at", "id"),
    Index("ix_agent_runs_expiring_lease", "status", "lease_expires_at"),
)


node_build_attempts = Table(
    "node_build_attempts",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("thread_id", SaUuid(as_uuid=True), nullable=False),
    Column("draft_node_id", SaUuid(as_uuid=True), nullable=False),
    Column("run_id", SaUuid(as_uuid=True), nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("prompt", Text, nullable=False),
    Column(
        "status",
        DomainStrEnumType(NodeBuildStatus, length=32),
        nullable=False,
    ),
    Column(
        "manifest",
        PydanticModelType(GeneratedNodeManifest),
        nullable=True,
    ),
    Column(
        "capabilities",
        PydanticModelType(CapabilityManifest),
        nullable=True,
    ),
    Column("capability_digest", String(64), nullable=True),
    Column("artifacts", PydanticModelType(BuildArtifactSet), nullable=True),
    Column("failure_message", Text, nullable=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "draft_node_id", "thread_id"),
        ("draft_nodes.workspace_id", "draft_nodes.id", "draft_nodes.thread_id"),
        name="fk_node_build_attempts_draft_thread",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "run_id", "thread_id"),
        ("agent_runs.workspace_id", "agent_runs.id", "agent_runs.thread_id"),
        name="fk_node_build_attempts_run_thread",
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "workspace_id",
        "id",
        name="uq_node_build_attempts_workspace_id_id",
    ),
    UniqueConstraint(
        "workspace_id",
        "id",
        "draft_node_id",
        name="uq_node_build_attempts_identity_draft",
    ),
    UniqueConstraint(
        "workspace_id",
        "id",
        "draft_node_id",
        "thread_id",
        name="uq_node_build_attempts_identity_context",
    ),
    UniqueConstraint(
        "workspace_id",
        "draft_node_id",
        "attempt_number",
        name="uq_node_build_attempts_draft_attempt",
    ),
    CheckConstraint("attempt_number >= 1", name="attempt_number"),
    CheckConstraint(
        "status IN ('queued', 'preparing', 'coding', 'testing', "
        "'awaiting_approval', 'failed', 'cancelled', 'superseded', 'published')",
        name="status",
    ),
    Index(
        "uq_node_build_attempts_active_draft",
        "workspace_id",
        "draft_node_id",
        unique=True,
        postgresql_where=text(
            "status IN ('queued', 'preparing', 'coding', 'testing', "
            "'awaiting_approval')"
        ),
        sqlite_where=text(
            "status IN ('queued', 'preparing', 'coding', 'testing', "
            "'awaiting_approval')"
        ),
    ),
    Index(
        "ix_node_build_attempts_run",
        "workspace_id",
        "run_id",
        "attempt_number",
    ),
)


agent_events = Table(
    "agent_events",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("thread_id", SaUuid(as_uuid=True), nullable=False),
    Column("sequence", BigInteger, nullable=False),
    Column(
        "kind",
        DomainStrEnumType(AgentEventKind, length=80),
        nullable=False,
    ),
    Column("payload", PydanticModelType(AgentEventPayload), nullable=False),
    Column("run_id", SaUuid(as_uuid=True), nullable=True),
    Column("created_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "thread_id"),
        ("agent_threads.workspace_id", "agent_threads.id"),
        name="fk_agent_events_thread",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "run_id", "thread_id"),
        (
            "agent_runs.workspace_id",
            "agent_runs.id",
            "agent_runs.thread_id",
        ),
        name="fk_agent_events_run_thread",
        ondelete="CASCADE",
    ),
    UniqueConstraint("workspace_id", "id", name="uq_agent_events_workspace_id_id"),
    UniqueConstraint(
        "workspace_id",
        "thread_id",
        "sequence",
        name="uq_agent_events_thread_sequence",
    ),
    CheckConstraint("sequence >= 1", name="sequence"),
    Index(
        "ix_agent_events_workspace_run",
        "workspace_id",
        "run_id",
        "sequence",
    ),
)


capability_approvals = Table(
    "capability_approvals",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("draft_node_id", SaUuid(as_uuid=True), nullable=False),
    Column("build_attempt_id", SaUuid(as_uuid=True), nullable=False),
    Column("capability_digest", String(64), nullable=False),
    Column(
        "approved_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("approved_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "build_attempt_id", "draft_node_id"),
        (
            "node_build_attempts.workspace_id",
            "node_build_attempts.id",
            "node_build_attempts.draft_node_id",
        ),
        name="fk_capability_approvals_build_draft",
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "workspace_id",
        "id",
        name="uq_capability_approvals_workspace_id_id",
    ),
    UniqueConstraint(
        "workspace_id",
        "id",
        "build_attempt_id",
        "draft_node_id",
        "approved_by_user_id",
        "capability_digest",
        name="uq_capability_approvals_identity_context",
    ),
    UniqueConstraint(
        "workspace_id",
        "build_attempt_id",
        name="uq_capability_approvals_build_attempt",
    ),
)


node_releases = Table(
    "node_releases",
    metadata,
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("node_id", SaUuid(as_uuid=True), primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("draft_node_id", SaUuid(as_uuid=True), nullable=False),
    Column("build_attempt_id", SaUuid(as_uuid=True), nullable=False),
    Column("capability_approval_id", SaUuid(as_uuid=True), nullable=False),
    Column("thread_id", SaUuid(as_uuid=True), nullable=False),
    Column("environment_id", SaUuid(as_uuid=True), nullable=False),
    Column("manifest", PydanticModelType(GeneratedNodeManifest), nullable=False),
    Column("capabilities", PydanticModelType(CapabilityManifest), nullable=False),
    Column("capability_digest", String(64), nullable=False),
    Column("artifacts", PydanticModelType(BuildArtifactSet), nullable=False),
    Column(
        "approved_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "created_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("created_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "build_attempt_id", "draft_node_id", "thread_id"),
        (
            "node_build_attempts.workspace_id",
            "node_build_attempts.id",
            "node_build_attempts.draft_node_id",
            "node_build_attempts.thread_id",
        ),
        name="fk_node_releases_build_context",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        (
            "workspace_id",
            "capability_approval_id",
            "build_attempt_id",
            "draft_node_id",
            "approved_by_user_id",
            "capability_digest",
        ),
        (
            "capability_approvals.workspace_id",
            "capability_approvals.id",
            "capability_approvals.build_attempt_id",
            "capability_approvals.draft_node_id",
            "capability_approvals.approved_by_user_id",
            "capability_approvals.capability_digest",
        ),
        name="fk_node_releases_capability_approval_context",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "draft_node_id"),
        ("draft_nodes.workspace_id", "draft_nodes.id"),
        name="fk_node_releases_draft",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "thread_id", "environment_id"),
        (
            "agent_threads.workspace_id",
            "agent_threads.id",
            "agent_threads.environment_id",
        ),
        name="fk_node_releases_thread_environment",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "workspace_id",
        "build_attempt_id",
        name="uq_node_releases_build_attempt",
    ),
    CheckConstraint("revision >= 1", name="revision"),
    CheckConstraint("node_id = draft_node_id", name="node_is_draft"),
    Index(
        "ix_node_releases_workspace_node_revision",
        "workspace_id",
        "node_id",
        "revision",
    ),
)

"""Project SQL schema (ADR 0020): identity, checkpoints, head, receipts, filing.

The Project is the Workspace-owned collaborative document. Its identity lives in
``projects`` with no document or revision counter of its own; the live collaborative
state lives in ``project_heads`` and the durable revisions in the append-only
``project_checkpoints``. Command receipts and checkpoint mappings keep the
collaboration idempotent. Filing (folders, archive, per-user star/last-opened) is
Workspace-scoped beside it.

Every table is keyed by ``workspace_id`` and joins the Project through the
``(workspace_id, id)`` pair on ``projects``, so a Project of another Workspace is a
foreign key miss rather than a row to filter out.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy import Uuid as SaUuid

from grafy_persistence.column_types import (
    ProjectDocumentType,
    UTCDateTime,
)

from .base import metadata

projects = Table(
    "projects",
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
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    # A Project carries no document and no revision: the head and the checkpoints
    # own the content, so nothing here has to agree with a counter it does not own.
    UniqueConstraint("workspace_id", "id", name="uq_projects_workspace_id_id"),
    Index("ix_projects_workspace_updated_at", "workspace_id", "updated_at"),
    Index("ix_projects_workspace_id", "workspace_id", "id"),
)


project_folders = Table(
    "project_folders",
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
    UniqueConstraint("workspace_id", "id", name="uq_project_folders_workspace_id_id"),
    UniqueConstraint(
        "workspace_id",
        "name",
        name="uq_project_folders_workspace_id_name",
    ),
    Index("ix_project_folders_workspace_name", "workspace_id", "name"),
)


project_checkpoints = Table(
    "project_checkpoints",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("project_id", SaUuid(as_uuid=True), primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("name", String(160), nullable=False),
    Column("document", ProjectDocumentType(), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    CheckConstraint(
        "revision >= 1",
        name="ck_project_checkpoints_revision_positive",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "project_id"),
        ("projects.workspace_id", "projects.id"),
        ondelete="CASCADE",
    ),
    Index(
        "ix_project_checkpoints_workspace_project_revision",
        "workspace_id",
        "project_id",
        "revision",
    ),
)


project_heads = Table(
    "project_heads",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("project_id", SaUuid(as_uuid=True), primary_key=True),
    Column("room_epoch", SaUuid(as_uuid=True), nullable=False),
    Column("collaboration_sequence", BigInteger, nullable=False),
    Column("checkpoint_sequence", BigInteger, nullable=False),
    Column("checkpoint_revision", BigInteger, nullable=False),
    Column("name", String(160), nullable=False),
    Column("document", ProjectDocumentType(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    # The same invariants the ProjectHead dataclass enforces in memory.
    CheckConstraint(
        "collaboration_sequence >= 0",
        name="ck_project_heads_collaboration_sequence_nonneg",
    ),
    CheckConstraint(
        "checkpoint_sequence >= 0",
        name="ck_project_heads_checkpoint_sequence_nonneg",
    ),
    CheckConstraint(
        "checkpoint_sequence <= collaboration_sequence",
        name="ck_project_heads_checkpoint_lte_head",
    ),
    CheckConstraint(
        "checkpoint_revision >= 1",
        name="ck_project_heads_checkpoint_revision_positive",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "project_id"),
        ("projects.workspace_id", "projects.id"),
        ondelete="CASCADE",
    ),
    Index("ix_project_heads_workspace_updated_at", "workspace_id", "updated_at"),
)


project_command_receipts = Table(
    "project_command_receipts",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("project_id", SaUuid(as_uuid=True), primary_key=True),
    Column("command_id", SaUuid(as_uuid=True), primary_key=True),
    Column("command_hmac", LargeBinary(64), nullable=False),
    Column("hmac_key_version", Integer, nullable=False),
    Column("actor_kind", String(32), nullable=False),
    Column("actor_user_id", SaUuid(as_uuid=True), nullable=True),
    Column("room_epoch", SaUuid(as_uuid=True), nullable=False),
    Column("accepted_sequence", BigInteger, nullable=False),
    Column("outcome", String(40), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    # One row per accepted command id: the primary key is the idempotency guard the
    # application layer relies on to answer a replay, so it is append-only.
    ForeignKeyConstraint(
        ("workspace_id", "project_id"),
        ("project_heads.workspace_id", "project_heads.project_id"),
        ondelete="CASCADE",
    ),
)


project_checkpoint_mappings = Table(
    "project_checkpoint_mappings",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("project_id", SaUuid(as_uuid=True), primary_key=True),
    Column("room_epoch", SaUuid(as_uuid=True), primary_key=True),
    Column("collaboration_sequence", BigInteger, primary_key=True),
    Column("checkpoint_revision", BigInteger, nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "project_id"),
        ("project_heads.workspace_id", "project_heads.project_id"),
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "project_id", "checkpoint_revision"),
        (
            "project_checkpoints.workspace_id",
            "project_checkpoints.project_id",
            "project_checkpoints.revision",
        ),
        ondelete="CASCADE",
    ),
)


project_organizations = Table(
    "project_organizations",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("project_id", SaUuid(as_uuid=True), primary_key=True),
    Column("folder_id", SaUuid(as_uuid=True), nullable=True),
    Column("archived_at", UTCDateTime(), nullable=True),
    Column("updated_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "project_id"),
        ("projects.workspace_id", "projects.id"),
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "folder_id"),
        ("project_folders.workspace_id", "project_folders.id"),
        ondelete="RESTRICT",
    ),
    Index(
        "ix_project_organizations_workspace_folder_archived",
        "workspace_id",
        "folder_id",
        "archived_at",
    ),
)


user_project_states = Table(
    "user_project_states",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("project_id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("starred", Boolean, nullable=False, default=False),
    Column("last_opened_at", UTCDateTime(), nullable=True),
    ForeignKeyConstraint(
        ("workspace_id", "project_id"),
        ("projects.workspace_id", "projects.id"),
        ondelete="CASCADE",
    ),
    Index("ix_user_project_states_user_starred", "user_id", "starred"),
    Index("ix_user_project_states_user_last_opened", "user_id", "last_opened_at"),
)

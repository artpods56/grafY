from sqlalchemy import (
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
    SavedGraphDocumentType,
    UTCDateTime,
)

from .base import metadata

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

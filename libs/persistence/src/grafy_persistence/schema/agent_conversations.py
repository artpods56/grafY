"""Agent conversation SQL schema (ADR 0021, issue #202).

Two tables carry one durable promise: history is appended and never rewritten.

``agent_conversations`` is the row a thread owns: where its Agent sits (Workspace,
Project, Graph, Agent id), who started it, and ``next_sequence`` — the sequence its next
event takes. The only way the row changes in place is that counter moving forward.

``agent_conversation_events`` holds the history itself, keyed by the sequence it was
appended at. There is no mutable column: a row is written once and read forever. Forking
copies rows into a new conversation rather than trimming the source, and the fork keeps
the conversation and sequence it copied.

Both tables are Workspace-keyed and reach the Project through the ``(workspace_id, id)``
pair on ``projects``, so a Project of another Workspace is a foreign key miss.
``author_user_id`` is a bare id, like a command receipt's actor: conversations are shared
with everyone who can read the Project, so they outlive the account that started them
rather than disappearing with it.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy import Uuid as SaUuid

from grafy_persistence.column_types import UTCDateTime

from .base import metadata

agent_conversations = Table(
    "agent_conversations",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column("workspace_id", SaUuid(as_uuid=True), nullable=False),
    Column("project_id", SaUuid(as_uuid=True), nullable=False),
    Column("graph_id", String(255), nullable=False),
    Column("agent_id", String(255), nullable=False),
    Column("author_user_id", SaUuid(as_uuid=True), nullable=False),
    Column("title", String(500), nullable=False),
    # A fork names where it was cut. Cascading the source drops the lines drawn from it
    # rather than leaving a conversation whose beginning is missing.
    Column(
        "source_conversation_id",
        SaUuid(as_uuid=True),
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        nullable=True,
    ),
    Column("source_sequence", Integer, nullable=True),
    Column("next_sequence", BigInteger, nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    UniqueConstraint(
        "workspace_id", "id", name="uq_agent_conversations_workspace_id_id"
    ),
    CheckConstraint(
        "next_sequence >= 1",
        name="ck_agent_conversations_next_sequence_positive",
    ),
    # Either both halves of a fork are recorded or neither is: a conversation that says
    # it was cut somewhere has to say where.
    CheckConstraint(
        "(source_conversation_id IS NULL) = (source_sequence IS NULL)",
        name="ck_agent_conversations_fork_records_source_and_sequence",
    ),
    CheckConstraint(
        "source_sequence IS NULL OR source_sequence >= 1",
        name="ck_agent_conversations_source_sequence_positive",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "project_id"),
        ("projects.workspace_id", "projects.id"),
        ondelete="CASCADE",
    ),
    Index(
        "ix_agent_conversations_workspace_project_graph_agent",
        "workspace_id",
        "project_id",
        "graph_id",
        "agent_id",
    ),
)

agent_conversation_events = Table(
    "agent_conversation_events",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("conversation_id", SaUuid(as_uuid=True), primary_key=True),
    Column("sequence", BigInteger, primary_key=True),
    Column("turn_id", SaUuid(as_uuid=True), nullable=False),
    # The payload discriminator, stored beside the payload so a reader can narrow a
    # range of history without parsing every row.
    Column("kind", String(32), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    CheckConstraint(
        "sequence >= 1",
        name="ck_agent_conversation_events_sequence_positive",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "conversation_id"),
        ("agent_conversations.workspace_id", "agent_conversations.id"),
        ondelete="CASCADE",
    ),
    Index(
        "ix_agent_conversation_events_conversation_turn",
        "conversation_id",
        "turn_id",
    ),
)

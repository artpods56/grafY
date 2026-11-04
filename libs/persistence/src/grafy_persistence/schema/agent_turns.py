"""Agent turn SQL schema (ADR 0021, issue #202).

``agent_turns`` is the durable half of "one turn at a time per conversation, and a retry
of a send is the same turn". The conversation's own ``next_sequence`` already refuses a
second event at a taken sequence; that alone would make a retry of an accepted send a
confusing error rather than the same answer, because a receipt is keyed by what the client
chose, not by where the history happened to be.

Two structural rules, both enforced by the database:

* ``uq_agent_turns_conversation_client_turn`` makes ``(workspace_id, conversation_id,
  client_turn_id)`` unique, which is the idempotency key. It is scoped to the conversation
  because a client turn id means "this send", and a client that reuses one id across two
  threads is not retrying anything.
* ``uq_agent_turns_one_running_per_conversation`` is a *partial* unique index on
  ``(workspace_id, conversation_id)`` for the rows still in ``status = 'running'``. Any
  number of finished turns may pile up beside each other, and exactly one live turn may
  exist, so "is this conversation busy?" is answered by the write itself rather than by a
  read that two senders can both pass.

Everything else is the turn's own account: where it sits (Workspace, Project, Graph,
Agent), who asked, the instruction and model snapshot the turn was accepted with, and the
sequence its user message took. No key material and no endpoint URL: a credential belongs
to ``agent_keys`` and to the clients a live turn holds open, and a row in this table is
readable by anyone who can read the conversation.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import Uuid as SaUuid

from grafy_persistence.column_types import UTCDateTime

from .base import metadata

_TURN_STATUSES = ("running", "completed", "cancelled", "failed", "interrupted")
_RUNNING = "status = 'running'"

agent_turns = Table(
    "agent_turns",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column("workspace_id", SaUuid(as_uuid=True), nullable=False),
    Column("project_id", SaUuid(as_uuid=True), nullable=False),
    Column("graph_id", String(255), nullable=False),
    Column("agent_id", String(255), nullable=False),
    Column("conversation_id", SaUuid(as_uuid=True), nullable=False),
    # The client's own id for this send. Unique per conversation, so a retry is answered
    # with the turn it already created instead of a second model call.
    Column("client_turn_id", String(200), nullable=False),
    Column("requested_by_user_id", SaUuid(as_uuid=True), nullable=False),
    Column("status", String(32), nullable=False),
    # SHA-256 of the admitted user text, so a reused turn id with different content is a
    # conflict rather than a silent replay of a message nobody just sent.
    Column("request_digest", String(64), nullable=False),
    CheckConstraint(
        "length(request_digest) = 64",
        name="ck_agent_turns_request_digest_is_a_digest",
    ),
    # The dense per-conversation sequence the admitted user message took, same type the
    # event rows key on.
    Column("user_message_sequence", BigInteger, nullable=False),
    CheckConstraint(
        "user_message_sequence >= 1",
        name="ck_agent_turns_user_message_sequence_positive",
    ),
    # The Agent as it was when the turn was accepted. History must be explicable after the
    # canvas moves: an Agent renamed, re-pointed at another model or removed still has the
    # instructions and model name its turn ran under.
    Column("instructions", Text, nullable=False),
    Column("model_source", String(16), nullable=False),
    CheckConstraint(
        "model_source IN ('deployment', 'agent')",
        name="ck_agent_turns_model_source_known",
    ),
    Column("model_name", String(255), nullable=False),
    Column("outcome_detail", Text, nullable=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("finished_at", UTCDateTime(), nullable=True),
    CheckConstraint(
        f"status IN ({', '.join(repr(status) for status in _TURN_STATUSES)})",
        name="ck_agent_turns_status_known",
    ),
    # A turn is running exactly while it has no finish stamp, mirroring the domain
    # invariant rather than trusting whoever wrote the row.
    CheckConstraint(
        f"({_RUNNING}) = (finished_at IS NULL)",
        name="ck_agent_turns_running_iff_unfinished",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "project_id"),
        ("projects.workspace_id", "projects.id"),
        ondelete="CASCADE",
    ),
    # A turn's history goes with its conversation; the conversation is never deleted under
    # it, and a cascade keeps a turn from outliving the thread it receipts.
    ForeignKeyConstraint(
        ("workspace_id", "conversation_id"),
        ("agent_conversations.workspace_id", "agent_conversations.id"),
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "workspace_id",
        "conversation_id",
        "client_turn_id",
        name="uq_agent_turns_conversation_client_turn",
    ),
    Index(
        "ix_agent_turns_workspace_conversation_created",
        "workspace_id",
        "conversation_id",
        "created_at",
    ),
    Index(
        "uq_agent_turns_one_running_per_conversation",
        "workspace_id",
        "conversation_id",
        unique=True,
        sqlite_where=text(_RUNNING),
        postgresql_where=text(_RUNNING),
    ),
)

__all__ = ["agent_turns"]

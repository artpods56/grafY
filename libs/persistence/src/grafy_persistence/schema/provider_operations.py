"""Stored answers to provider requests (provider-operation cache).

One row is one Workspace's answer to one request, addressed by the sha256 of the
canonical identity that produced it: operation id, deployment identity,
implementation revision, result schema version, and the request itself. See
``docs/design/provider-operation-cache.md``.

``workspace_id`` leads the primary key and is a real foreign key rather than a
decorative column: the partition is enforced by storage, and deleting a Workspace
takes its cached provider answers with it. Rows are bounded by ``expires_at``,
not by count, so the sweep reads this table by expiry alone.

A row whose ``expires_at`` has passed is invisible to readers but still occupies
the table until a sweep takes it. ``expires_at >= stored_at`` allows a write with
a zero ttl, which is how a caller retires a row it can no longer decode.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    Table,
)
from sqlalchemy import Uuid as SaUuid

from grafy_persistence.column_types import UTCDateTime

from .base import metadata

provider_operations = Table(
    "provider_operations",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("key_sha256", String(64), primary_key=True),
    Column("payload", LargeBinary(), nullable=False),
    Column("stored_at", UTCDateTime(), nullable=False),
    Column("expires_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ["workspace_id"],
        ["workspaces.id"],
        ondelete="CASCADE",
    ),
    CheckConstraint(
        "expires_at >= stored_at",
        name="expiry_not_before_write",
    ),
    Index("ix_provider_operations_expires_at", "expires_at"),
)

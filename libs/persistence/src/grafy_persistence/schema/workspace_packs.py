from sqlalchemy import Column, DateTime, ForeignKey, String, Table, Uuid

from .base import metadata


workspace_packs = Table(
    "workspace_packs",
    metadata,
    Column(
        "workspace_id",
        Uuid(),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("pack_slug", String(80), primary_key=True),
    Column("enabled_at", DateTime(timezone=True), nullable=False),
    Column("enabled_by_user_id", Uuid(), ForeignKey("users.id", ondelete="SET NULL")),
)

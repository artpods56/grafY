"""Remove the special local workspace and bootstrap-owner mapping.

Revision ID: 0023_remove_local_workspace
Revises: 0022_workspace_invitations
Create Date: 2026-08-26
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from alembic import op
import sqlalchemy as sa


revision: str = "0023_remove_local_workspace"
down_revision: str | Sequence[str] | None = "0022_workspace_invitations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LOCAL_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")
# UTCDateTime persists UTC timestamps in timezone-naive database columns.
MIGRATION_TIMESTAMP = datetime(2026, 8, 26)

_DIRECT_WORKSPACE_RESOURCES = (
    "artifact_objects",
    "graph_folders",
    "invocation_cache_entries",
    "modules",
    "personal_access_tokens",
    "plugin_release_revocations",
    "plugin_release_selections",
    "plugin_releases",
    "saved_graphs",
    "staged_uploads",
    "templates",
    "workspace_memberships",
)


def upgrade() -> None:
    connection = op.get_bind()
    local_workspace = connection.execute(
        sa.text("SELECT id, kind FROM workspaces WHERE slug = 'local'")
    ).one_or_none()

    if local_workspace is not None:
        local_workspace_id, kind = local_workspace
        if UUID(str(local_workspace_id)) != LOCAL_WORKSPACE_ID or kind != "shared":
            raise RuntimeError(
                "Cannot remove local workspace: slug 'local' is not the expected "
                "legacy shared workspace"
            )

        local_id = sa.bindparam("local_id", type_=sa.Uuid())
        active_owner_count = connection.execute(
            sa.text(
                "SELECT COUNT(*) FROM workspace_memberships "
                "WHERE workspace_id = :local_id AND role = 'owner' "
                "AND revoked_at IS NULL"
            ).bindparams(local_id),
            {"local_id": LOCAL_WORKSPACE_ID},
        ).scalar_one()
        resource_counts = {
            table_name: connection.execute(
                sa.text(
                    f"SELECT COUNT(*) FROM {table_name} WHERE workspace_id = :local_id"
                ).bindparams(local_id),
                {"local_id": LOCAL_WORKSPACE_ID},
            ).scalar_one()
            for table_name in _DIRECT_WORKSPACE_RESOURCES
        }
        populated_resources = {
            table_name: count
            for table_name, count in resource_counts.items()
            if table_name != "workspace_memberships" and count > 0
        }
        membership_count = resource_counts["workspace_memberships"]

        if active_owner_count == 0 and (populated_resources or membership_count):
            details = ", ".join(
                f"{table_name}={count}"
                for table_name, count in sorted(resource_counts.items())
                if count > 0
            )
            raise RuntimeError(
                "Cannot remove an unowned local workspace containing tenant data "
                f"({details}). Bootstrap its owner with the previous Grafy release "
                "before upgrading."
            )

        if active_owner_count == 0:
            connection.execute(
                sa.text("DELETE FROM workspaces WHERE id = :local_id").bindparams(
                    local_id
                ),
                {"local_id": LOCAL_WORKSPACE_ID},
            )
        else:
            migrated_slug = "migrated-workspace"
            suffix = 2
            while (
                connection.execute(
                    sa.text("SELECT 1 FROM workspaces WHERE slug = :slug"),
                    {"slug": migrated_slug},
                ).first()
                is not None
            ):
                migrated_slug = f"migrated-workspace-{suffix}"
                suffix += 1
            connection.execute(
                sa.text(
                    "UPDATE workspaces SET slug = :slug, name = :name, "
                    "updated_at = :updated_at WHERE id = :local_id"
                ).bindparams(
                    local_id,
                    sa.bindparam("updated_at", type_=sa.DateTime()),
                ),
                {
                    "local_id": LOCAL_WORKSPACE_ID,
                    "slug": migrated_slug,
                    "name": "Migrated workspace",
                    "updated_at": MIGRATION_TIMESTAMP,
                },
            )

    op.drop_index(
        "ix_oidc_bootstrap_owner_mappings_unconsumed",
        table_name="oidc_bootstrap_owner_mappings",
    )
    op.drop_table("oidc_bootstrap_owner_mappings")


def downgrade() -> None:
    connection = op.get_bind()
    conflicting_local = connection.execute(
        sa.text("SELECT id FROM workspaces WHERE slug = 'local'")
    ).one_or_none()
    if conflicting_local is not None:
        raise RuntimeError(
            "Cannot downgrade 0022: workspace slug 'local' is already in use"
        )

    local_id = sa.bindparam("local_id", type_=sa.Uuid())
    migrated_workspace = connection.execute(
        sa.text("SELECT id FROM workspaces WHERE id = :local_id").bindparams(local_id),
        {"local_id": LOCAL_WORKSPACE_ID},
    ).one_or_none()
    if migrated_workspace is None:
        workspaces = sa.table(
            "workspaces",
            sa.column("id", sa.Uuid()),
            sa.column("slug", sa.String()),
            sa.column("name", sa.String()),
            sa.column("kind", sa.String()),
            sa.column("personal_owner_user_id", sa.Uuid()),
            sa.column("created_at", sa.DateTime()),
            sa.column("updated_at", sa.DateTime()),
        )
        op.bulk_insert(
            workspaces,
            [
                {
                    "id": LOCAL_WORKSPACE_ID,
                    "slug": "local",
                    "name": "Local workspace",
                    "kind": "shared",
                    "personal_owner_user_id": None,
                    "created_at": MIGRATION_TIMESTAMP,
                    "updated_at": MIGRATION_TIMESTAMP,
                }
            ],
        )
    else:
        connection.execute(
            sa.text(
                "UPDATE workspaces SET slug = 'local', name = 'Local workspace', "
                "updated_at = :updated_at WHERE id = :local_id"
            ).bindparams(
                local_id,
                sa.bindparam("updated_at", type_=sa.DateTime()),
            ),
            {
                "local_id": LOCAL_WORKSPACE_ID,
                "updated_at": MIGRATION_TIMESTAMP,
            },
        )

    op.create_table(
        "oidc_bootstrap_owner_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=2048), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_oidc_bootstrap_owner_mappings_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_oidc_bootstrap_owner_mappings"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            name="uq_oidc_bootstrap_owner_mappings_workspace_id",
        ),
    )
    op.create_index(
        "ix_oidc_bootstrap_owner_mappings_unconsumed",
        "oidc_bootstrap_owner_mappings",
        ["workspace_id", "consumed_at"],
        unique=False,
    )

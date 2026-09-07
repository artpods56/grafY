"""Separate scope-neutral Plugin releases from scoped installations.

Revision ID: 0024_plugin_installations
Revises: 0023_remove_local_workspace
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0024_plugin_installations"
down_revision: str | Sequence[str] | None = "0023_remove_local_workspace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _require_empty(connection: sa.Connection, table_names: tuple[str, ...]) -> None:
    populated = {
        table_name: connection.execute(
            sa.text(f"SELECT COUNT(*) FROM {table_name}")
        ).scalar_one()
        for table_name in table_names
    }
    populated = {name: count for name, count in populated.items() if count}
    if populated:
        detail = ", ".join(
            f"{table_name}={count}"
            for table_name, count in sorted(populated.items())
        )
        raise RuntimeError(
            "Plugin release and installation cutover requires empty Plugin "
            f"registry tables; found {detail}"
        )


def _create_release_tables() -> None:
    op.create_table(
        "plugin_releases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("catalog", sa.JSON(), nullable=False),
        sa.Column("contract_digest", sa.String(length=64), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("capability_digest", sa.String(length=64), nullable=False),
        sa.Column("protocol_digest", sa.String(length=64), nullable=True),
        sa.Column("profile_digest", sa.String(length=64), nullable=True),
        sa.Column("source_object_key", sa.String(length=2048), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("lock_digest", sa.String(length=64), nullable=False),
        sa.Column("runtime_profile", sa.String(length=100), nullable=False),
        sa.Column("loader_target", sa.String(length=255), nullable=False),
        sa.Column("runtime_image_digest", sa.String(length=64), nullable=True),
        sa.Column("runtime_artifact", sa.JSON(), nullable=True),
        sa.Column("descriptor_digest", sa.String(length=64), nullable=True),
        sa.Column("published_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("published_by_platform_actor", sa.String(length=255), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_plugin_releases_plugin_release_revision"),
        sa.CheckConstraint(
            "published_by_user_id IS NULL OR published_by_platform_actor IS NULL",
            name="ck_plugin_releases_plugin_release_single_publisher",
        ),
        sa.CheckConstraint(
            "length(capability_digest) = 64",
            name="ck_plugin_releases_plugin_release_capability_digest",
        ),
        sa.CheckConstraint(
            "length(source_digest) = 64",
            name="ck_plugin_releases_plugin_release_source_digest",
        ),
        sa.CheckConstraint(
            "length(lock_digest) = 64",
            name="ck_plugin_releases_plugin_release_lock_digest",
        ),
        sa.CheckConstraint(
            "runtime_image_digest IS NULL OR length(runtime_image_digest) = 64",
            name="ck_plugin_releases_plugin_release_runtime_image_digest",
        ),
        sa.CheckConstraint(
            "descriptor_digest IS NULL OR length(descriptor_digest) = 64",
            name="ck_plugin_releases_plugin_release_descriptor_digest",
        ),
        sa.CheckConstraint(
            "contract_digest IS NULL OR length(contract_digest) = 64",
            name="ck_plugin_releases_plugin_release_contract_digest",
        ),
        sa.CheckConstraint(
            "protocol_digest IS NULL OR length(protocol_digest) = 64",
            name="ck_plugin_releases_plugin_release_protocol_digest",
        ),
        sa.CheckConstraint(
            "profile_digest IS NULL OR length(profile_digest) = 64",
            name="ck_plugin_releases_plugin_release_profile_digest",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"],
            ["users.id"],
            name=op.f("fk_plugin_releases_published_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plugin_releases")),
    )
    op.create_index(
        "uq_plugin_releases_slug_revision",
        "plugin_releases",
        ["slug", "revision"],
        unique=True,
    )
    op.create_index(
        "uq_plugin_releases_slug_descriptor",
        "plugin_releases",
        ["slug", "descriptor_digest"],
        unique=True,
        sqlite_where=sa.text("descriptor_digest IS NOT NULL"),
        postgresql_where=sa.text("descriptor_digest IS NOT NULL"),
    )

    op.create_table(
        "plugin_installations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("release_revision", sa.Integer(), nullable=False),
        sa.Column("execution_policy", sa.String(length=24), nullable=False),
        sa.Column("distribution", sa.String(length=16), nullable=True),
        sa.Column("installed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("installed_by_platform_actor", sa.String(length=255), nullable=True),
        sa.Column("installed_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "scope IN ('system', 'workspace')",
            name="ck_plugin_installations_plugin_installation_scope",
        ),
        sa.CheckConstraint(
            "(scope = 'system' AND workspace_id IS NULL) OR "
            "(scope = 'workspace' AND workspace_id IS NOT NULL)",
            name="ck_plugin_installations_plugin_installation_scope_workspace",
        ),
        sa.CheckConstraint(
            "release_revision >= 1",
            name="ck_plugin_installations_plugin_installation_release_revision",
        ),
        sa.CheckConstraint(
            "execution_policy IN ('host-eligible', 'isolated-only')",
            name="ck_plugin_installations_plugin_installation_execution_policy",
        ),
        sa.CheckConstraint(
            "(scope = 'system' AND distribution IN "
            "('bundled', 'optional', 'published')) OR "
            "(scope = 'workspace' AND distribution IS NULL "
            "AND execution_policy = 'isolated-only')",
            name="ck_plugin_installations_plugin_installation_scope_policy",
        ),
        sa.CheckConstraint(
            "(scope = 'system' AND installed_by_user_id IS NULL "
            "AND installed_by_platform_actor IS NOT NULL "
            "AND length(trim(installed_by_platform_actor)) BETWEEN 1 AND 255) OR "
            "(scope = 'workspace' AND installed_by_user_id IS NOT NULL "
            "AND installed_by_platform_actor IS NULL)",
            name="ck_plugin_installations_plugin_installation_actor",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["plugin_releases.id"],
            name=op.f("fk_plugin_installations_release_id_plugin_releases"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_plugin_installations_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["installed_by_user_id"],
            ["users.id"],
            name=op.f("fk_plugin_installations_installed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plugin_installations")),
    )
    op.create_index(
        "uq_plugin_installations_system_slug_revision",
        "plugin_installations",
        ["slug", "release_revision"],
        unique=True,
        sqlite_where=sa.text("scope = 'system'"),
        postgresql_where=sa.text("scope = 'system'"),
    )
    op.create_index(
        "uq_plugin_installations_workspace_slug_revision",
        "plugin_installations",
        ["workspace_id", "slug", "release_revision"],
        unique=True,
        sqlite_where=sa.text("scope = 'workspace'"),
        postgresql_where=sa.text("scope = 'workspace'"),
    )

    _create_selection_table()
    _create_revocation_table(installation_foreign_key=True)


def _create_selection_table() -> None:
    op.create_table(
        "plugin_release_selections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("selected_release_id", sa.Uuid(), nullable=False),
        sa.Column("selected_revision", sa.Integer(), nullable=False),
        sa.Column("lifecycle", sa.String(length=16), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_actor", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "scope IN ('system', 'workspace')",
            name="ck_plugin_release_selections_plugin_release_selection_scope",
        ),
        sa.CheckConstraint(
            "(scope = 'system' AND workspace_id IS NULL) OR "
            "(scope = 'workspace' AND workspace_id IS NOT NULL)",
            name="ck_plugin_release_selections_plugin_release_selection_scope_workspace",
        ),
        sa.CheckConstraint(
            "selected_revision >= 1",
            name="ck_plugin_release_selections_plugin_release_selection_revision",
        ),
        sa.CheckConstraint(
            "generation >= 1",
            name="ck_plugin_release_selections_plugin_release_selection_generation",
        ),
        sa.CheckConstraint(
            "lifecycle IN ('published', 'deprecated', 'withdrawn')",
            name="ck_plugin_release_selections_plugin_release_selection_lifecycle",
        ),
        sa.CheckConstraint(
            "updated_by_actor IS NULL OR length(trim(updated_by_actor)) BETWEEN 1 AND 255",
            name="ck_plugin_release_selections_plugin_release_selection_actor",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_plugin_release_selections_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["selected_release_id"],
            ["plugin_releases.id"],
            name=op.f(
                "fk_plugin_release_selections_selected_release_id_plugin_releases"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plugin_release_selections")),
    )
    op.create_index(
        "uq_plugin_release_selections_system_slug",
        "plugin_release_selections",
        ["slug"],
        unique=True,
        sqlite_where=sa.text("scope = 'system'"),
        postgresql_where=sa.text("scope = 'system'"),
    )
    op.create_index(
        "uq_plugin_release_selections_workspace_slug",
        "plugin_release_selections",
        ["workspace_id", "slug"],
        unique=True,
        sqlite_where=sa.text("scope = 'workspace'"),
        postgresql_where=sa.text("scope = 'workspace'"),
    )


def _create_revocation_table(*, installation_foreign_key: bool) -> None:
    key_name = "installation_id" if installation_foreign_key else "release_id"
    target = "plugin_installations.id" if installation_foreign_key else "plugin_releases.id"
    op.create_table(
        "plugin_release_revocations",
        sa.Column(key_name, sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_by_platform_actor", sa.String(length=255), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("scope IN ('system', 'workspace')", name="ck_plugin_release_revocations_revocation_scope"),
        sa.CheckConstraint(
            "(scope = 'system' AND workspace_id IS NULL) OR "
            "(scope = 'workspace' AND workspace_id IS NOT NULL)",
            name="ck_plugin_release_revocations_revocation_scope_workspace",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_plugin_release_revocations_revocation_revision"),
        sa.CheckConstraint(
            "reason IN ('security', 'integrity', 'policy', 'operational')",
            name="ck_plugin_release_revocations_revocation_reason",
        ),
        sa.CheckConstraint(
            "(scope = 'system' AND revoked_by_user_id IS NULL "
            "AND revoked_by_platform_actor IS NOT NULL "
            "AND length(trim(revoked_by_platform_actor)) BETWEEN 1 AND 255) OR "
            "(scope = 'workspace' AND revoked_by_user_id IS NOT NULL "
            "AND revoked_by_platform_actor IS NULL)",
            name="ck_plugin_release_revocations_revocation_actor",
        ),
        sa.ForeignKeyConstraint(
            [key_name],
            [target],
            name=op.f(
                f"fk_plugin_release_revocations_{key_name}_{target.replace('.', '_')}"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_plugin_release_revocations_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"],
            ["users.id"],
            name=op.f("fk_plugin_release_revocations_revoked_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(key_name, name=op.f("pk_plugin_release_revocations")),
    )
    op.create_index(
        "ix_plugin_release_revocations_scoped_identity",
        "plugin_release_revocations",
        ["scope", "workspace_id", "slug", "revision"],
        unique=False,
    )


def upgrade() -> None:
    connection = op.get_bind()
    _require_empty(
        connection,
        (
            "plugin_release_revocations",
            "plugin_release_selections",
            "plugin_releases",
        ),
    )
    op.drop_table("plugin_release_revocations")
    op.drop_table("plugin_release_selections")
    op.drop_table("plugin_releases")
    _create_release_tables()


def downgrade() -> None:
    connection = op.get_bind()
    _require_empty(
        connection,
        (
            "plugin_release_revocations",
            "plugin_release_selections",
            "plugin_installations",
            "plugin_releases",
        ),
    )
    op.drop_table("plugin_release_revocations")
    op.drop_table("plugin_release_selections")
    op.drop_table("plugin_installations")
    op.drop_table("plugin_releases")
    _create_legacy_release_table()
    _create_selection_table()
    _create_revocation_table(installation_foreign_key=False)


def _create_legacy_release_table() -> None:
    op.create_table(
        "plugin_releases",
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("catalog", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("capability_digest", sa.String(length=64), nullable=False),
        sa.Column("source_object_key", sa.String(length=2048), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("lock_digest", sa.String(length=64), nullable=False),
        sa.Column("runtime_profile", sa.String(length=100), nullable=False),
        sa.Column("runtime_image_digest", sa.String(length=64), nullable=True),
        sa.Column("published_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("contract_digest", sa.String(length=64), nullable=True),
        sa.Column("protocol_digest", sa.String(length=64), nullable=True),
        sa.Column("profile_digest", sa.String(length=64), nullable=True),
        sa.Column("runtime_artifact", sa.JSON(), nullable=True),
        sa.Column("descriptor_digest", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("execution_policy", sa.String(length=24), nullable=False),
        sa.Column("distribution", sa.String(length=16), nullable=True),
        sa.Column("published_by_platform_actor", sa.String(length=255), nullable=True),
        sa.CheckConstraint("revision >= 1", name="ck_plugin_releases_plugin_release_revision"),
        sa.CheckConstraint("scope IN ('system', 'workspace')", name="ck_plugin_releases_plugin_release_scope"),
        sa.CheckConstraint(
            "(scope = 'system' AND workspace_id IS NULL) OR "
            "(scope = 'workspace' AND workspace_id IS NOT NULL)",
            name="ck_plugin_releases_plugin_release_scope_workspace",
        ),
        sa.CheckConstraint(
            "execution_policy IN ('host-eligible', 'isolated-only')",
            name="ck_plugin_releases_plugin_release_execution_policy",
        ),
        sa.CheckConstraint(
            "(scope = 'system' AND distribution IN ('bundled', 'optional', 'published')) OR "
            "(scope = 'workspace' AND distribution IS NULL AND execution_policy = 'isolated-only')",
            name="ck_plugin_releases_plugin_release_scope_policy",
        ),
        sa.CheckConstraint(
            "(scope = 'system' AND published_by_user_id IS NULL "
            "AND published_by_platform_actor IS NOT NULL "
            "AND length(trim(published_by_platform_actor)) BETWEEN 1 AND 255) OR "
            "(scope = 'workspace' AND published_by_platform_actor IS NULL)",
            name="ck_plugin_releases_plugin_release_scope_publisher",
        ),
        sa.CheckConstraint("length(capability_digest) = 64", name="ck_plugin_releases_plugin_release_capability_digest"),
        sa.CheckConstraint("length(source_digest) = 64", name="ck_plugin_releases_plugin_release_source_digest"),
        sa.CheckConstraint("length(lock_digest) = 64", name="ck_plugin_releases_plugin_release_lock_digest"),
        sa.CheckConstraint("runtime_image_digest IS NULL OR length(runtime_image_digest) = 64", name="ck_plugin_releases_plugin_release_runtime_image_digest"),
        sa.CheckConstraint("descriptor_digest IS NULL OR length(descriptor_digest) = 64", name="ck_plugin_releases_plugin_release_descriptor_digest"),
        sa.CheckConstraint("contract_digest IS NULL OR length(contract_digest) = 64", name="ck_plugin_releases_plugin_release_contract_digest"),
        sa.CheckConstraint("protocol_digest IS NULL OR length(protocol_digest) = 64", name="ck_plugin_releases_plugin_release_protocol_digest"),
        sa.CheckConstraint("profile_digest IS NULL OR length(profile_digest) = 64", name="ck_plugin_releases_plugin_release_profile_digest"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_plugin_releases_workspace_id_workspaces"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"], name=op.f("fk_plugin_releases_published_by_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plugin_releases")),
    )
    op.create_index("uq_plugin_releases_system_slug_revision", "plugin_releases", ["slug", "revision"], unique=True, sqlite_where=sa.text("scope = 'system'"), postgresql_where=sa.text("scope = 'system'"))
    op.create_index("uq_plugin_releases_workspace_slug_revision", "plugin_releases", ["workspace_id", "slug", "revision"], unique=True, sqlite_where=sa.text("scope = 'workspace'"), postgresql_where=sa.text("scope = 'workspace'"))
    op.create_index("uq_plugin_releases_system_slug_descriptor", "plugin_releases", ["slug", "descriptor_digest"], unique=True, sqlite_where=sa.text("scope = 'system' AND descriptor_digest IS NOT NULL"), postgresql_where=sa.text("scope = 'system' AND descriptor_digest IS NOT NULL"))
    op.create_index("uq_plugin_releases_workspace_slug_descriptor", "plugin_releases", ["workspace_id", "slug", "descriptor_digest"], unique=True, sqlite_where=sa.text("scope = 'workspace' AND descriptor_digest IS NOT NULL"), postgresql_where=sa.text("scope = 'workspace' AND descriptor_digest IS NOT NULL"))

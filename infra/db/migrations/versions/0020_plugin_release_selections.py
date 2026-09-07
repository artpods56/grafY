"""Persist explicit current Plugin release selections and System publishers.

Revision ID: 0020_plugin_release_selections
Revises: 0019_scoped_plugin_releases
Create Date: 2026-08-24
"""

from collections.abc import Sequence
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "0020_plugin_release_selections"
down_revision: str | Sequence[str] | None = "0019_scoped_plugin_releases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SYSTEM_SELECTION_INDEX = "uq_plugin_release_selections_system_slug"
_WORKSPACE_SELECTION_INDEX = "uq_plugin_release_selections_workspace_slug"


def _backfill_selections(connection: sa.Connection) -> None:
    releases = sa.table(
        "plugin_releases",
        sa.column("id", sa.Uuid()),
        sa.column("scope", sa.String(length=16)),
        sa.column("workspace_id", sa.Uuid()),
        sa.column("slug", sa.String(length=100)),
        sa.column("revision", sa.Integer()),
        sa.column("published_at", sa.DateTime()),
    )
    selections = sa.table(
        "plugin_release_selections",
        sa.column("id", sa.Uuid()),
        sa.column("scope", sa.String(length=16)),
        sa.column("workspace_id", sa.Uuid()),
        sa.column("slug", sa.String(length=100)),
        sa.column("selected_release_id", sa.Uuid()),
        sa.column("selected_revision", sa.Integer()),
        sa.column("lifecycle", sa.String(length=16)),
        sa.column("generation", sa.Integer()),
        sa.column("updated_at", sa.DateTime()),
        sa.column("updated_by_actor", sa.String(length=255)),
    )

    existing_families = {
        (scope, workspace_id, slug)
        for scope, workspace_id, slug in connection.execute(
            sa.select(
                selections.c.scope,
                selections.c.workspace_id,
                selections.c.slug,
            )
        )
    }
    release_rows = connection.execute(
        sa.select(
            releases.c.id,
            releases.c.scope,
            releases.c.workspace_id,
            releases.c.slug,
            releases.c.revision,
            releases.c.published_at,
        ).order_by(
            releases.c.scope.asc(),
            releases.c.workspace_id.asc(),
            releases.c.slug.asc(),
            releases.c.revision.desc(),
        )
    ).all()

    selected_families = set(existing_families)
    for (
        release_id,
        scope,
        workspace_id,
        slug,
        release_revision,
        published_at,
    ) in release_rows:
        family = (scope, workspace_id, slug)
        if family in selected_families:
            continue
        connection.execute(
            sa.insert(selections).values(
                id=uuid4(),
                scope=scope,
                workspace_id=workspace_id,
                slug=slug,
                selected_release_id=release_id,
                selected_revision=release_revision,
                lifecycle="published",
                generation=1,
                updated_at=published_at,
                updated_by_actor="migration:0020",
            )
        )
        selected_families.add(family)


def upgrade() -> None:
    with op.batch_alter_table("plugin_releases") as batch:
        batch.add_column(
            sa.Column(
                "published_by_platform_actor",
                sa.String(length=255),
                nullable=True,
            )
        )
        batch.create_check_constraint(
            "ck_plugin_releases_plugin_release_scope_publisher",
            "(scope = 'system' AND published_by_user_id IS NULL "
            "AND published_by_platform_actor IS NOT NULL "
            "AND length(trim(published_by_platform_actor)) BETWEEN 1 AND 255) OR "
            "(scope = 'workspace' AND published_by_platform_actor IS NULL)",
        )

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
            name=(
                "ck_plugin_release_selections_plugin_release_selection_scope_workspace"
            ),
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
            "updated_by_actor IS NULL OR "
            "length(trim(updated_by_actor)) BETWEEN 1 AND 255",
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
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_plugin_release_selections"),
        ),
    )
    op.create_index(
        _SYSTEM_SELECTION_INDEX,
        "plugin_release_selections",
        ["slug"],
        unique=True,
        sqlite_where=sa.text("scope = 'system'"),
        postgresql_where=sa.text("scope = 'system'"),
    )
    op.create_index(
        _WORKSPACE_SELECTION_INDEX,
        "plugin_release_selections",
        ["workspace_id", "slug"],
        unique=True,
        sqlite_where=sa.text("scope = 'workspace'"),
        postgresql_where=sa.text("scope = 'workspace'"),
    )
    _backfill_selections(op.get_bind())


def _require_workspace_selections_representable(
    connection: sa.Connection,
) -> None:
    """Refuse to drop explicit selection state that 0019 cannot represent.

    0019 has no selection rows: every family implicitly selects its highest
    retained revision. Downgrade is therefore lossless only while every
    Workspace family still carries exactly the untouched 0020 backfill
    selection. Any rollback, lifecycle change, generation, actor, or missing
    selection would silently change meaning under 0019.
    """

    releases = sa.table(
        "plugin_releases",
        sa.column("id", sa.Uuid()),
        sa.column("scope", sa.String(length=16)),
        sa.column("workspace_id", sa.Uuid()),
        sa.column("slug", sa.String(length=100)),
        sa.column("revision", sa.Integer()),
    )
    selections = sa.table(
        "plugin_release_selections",
        sa.column("id", sa.Uuid()),
        sa.column("scope", sa.String(length=16)),
        sa.column("workspace_id", sa.Uuid()),
        sa.column("slug", sa.String(length=100)),
        sa.column("selected_release_id", sa.Uuid()),
        sa.column("selected_revision", sa.Integer()),
        sa.column("lifecycle", sa.String(length=16)),
        sa.column("generation", sa.Integer()),
        sa.column("updated_by_actor", sa.String(length=255)),
    )

    maximum: dict[tuple[object, str], tuple[int, object]] = {}
    for row in connection.execute(
        sa.select(
            releases.c.workspace_id,
            releases.c.slug,
            releases.c.id,
            releases.c.revision,
        ).where(releases.c.scope == "workspace")
    ):
        family = (row.workspace_id, row.slug)
        current = maximum.get(family)
        if current is None or row.revision > current[0]:
            maximum[family] = (row.revision, row.id)

    selections_by_family: dict[tuple[object, str], list[sa.Row]] = {}
    for row in connection.execute(
        sa.select(
            selections.c.workspace_id,
            selections.c.slug,
            selections.c.selected_release_id,
            selections.c.selected_revision,
            selections.c.lifecycle,
            selections.c.generation,
            selections.c.updated_by_actor,
        ).where(selections.c.scope == "workspace")
    ):
        selections_by_family.setdefault((row.workspace_id, row.slug), []).append(row)

    for family in sorted(
        set(maximum) | set(selections_by_family),
        key=lambda item: (str(item[0]), item[1]),
    ):
        workspace_id, slug = family
        family_selections = selections_by_family.get(family, [])
        if not family_selections:
            raise RuntimeError(
                f"Cannot downgrade 0020: Workspace Plugin family {slug!r} of "
                f"workspace {workspace_id} has releases but no explicit "
                "selection; 0019 implicit maximum-revision behavior cannot be "
                "verified"
            )
        if len(family_selections) > 1:
            raise RuntimeError(
                f"Cannot downgrade 0020: Workspace Plugin family {slug!r} of "
                f"workspace {workspace_id} has {len(family_selections)} "
                "selections; 0019 implicit selection cannot represent that "
                "state"
            )
        (selection,) = family_selections
        if family not in maximum:
            raise RuntimeError(
                f"Cannot downgrade 0020: Workspace Plugin family {slug!r} of "
                f"workspace {workspace_id} has a selection but no retained "
                "release; 0019 cannot represent that state"
            )
        max_revision, max_release_id = maximum[family]
        problems: list[str] = []
        if (
            selection.selected_revision != max_revision
            or selection.selected_release_id != max_release_id
        ):
            problems.append(
                f"selects revision {selection.selected_revision} instead of "
                f"the family's maximum retained revision {max_revision}"
            )
        if selection.lifecycle != "published":
            problems.append(
                f"has lifecycle {selection.lifecycle!r} instead of 'published'"
            )
        if selection.generation != 1:
            problems.append(
                f"is at generation {selection.generation} instead of 1"
            )
        if selection.updated_by_actor != "migration:0020":
            problems.append(
                f"was last updated by {selection.updated_by_actor!r} instead "
                "of the 0020 migration backfill"
            )
        if problems:
            raise RuntimeError(
                f"Cannot downgrade 0020: Workspace Plugin family {slug!r} of "
                f"workspace {workspace_id} selection state {'; '.join(problems)}; "
                "0019 cannot represent the explicit selection state"
            )


def downgrade() -> None:
    connection = op.get_bind()
    system_release_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM plugin_releases WHERE scope = 'system'")
    ).scalar_one()
    if system_release_count:
        raise RuntimeError(
            "Cannot downgrade 0020: System Plugin publisher provenance cannot be "
            "represented by the 0019 schema"
        )

    _require_workspace_selections_representable(connection)

    op.drop_index(
        _WORKSPACE_SELECTION_INDEX,
        table_name="plugin_release_selections",
    )
    op.drop_index(
        _SYSTEM_SELECTION_INDEX,
        table_name="plugin_release_selections",
    )
    op.drop_table("plugin_release_selections")
    with op.batch_alter_table("plugin_releases") as batch:
        batch.drop_constraint(
            "ck_plugin_releases_plugin_release_scope_publisher",
            type_="check",
        )
        batch.drop_column("published_by_platform_actor")

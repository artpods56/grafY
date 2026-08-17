"""Rewrite retired Daytona environment identity onto Docker.

Revision ID: 0014_retire_daytona_provider
Revises: 0013_agent_authoring
Create Date: 2026-08-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0014_retire_daytona_provider"
down_revision: str | Sequence[str] | None = "0013_agent_authoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_PROVIDER = "daytona"
_NEW_PROVIDER = "docker-trusted-development"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE agent_environments
            SET
                provider = :new_provider,
                status = CASE
                    WHEN status = 'failed' AND provider_environment_id IS NULL
                    THEN 'provisioning'
                    ELSE status
                END,
                failure_message = CASE
                    WHEN status = 'failed' AND provider_environment_id IS NULL
                    THEN NULL
                    ELSE failure_message
                END
            WHERE provider = :old_provider
            """
        ),
        {"old_provider": _OLD_PROVIDER, "new_provider": _NEW_PROVIDER},
    )
    params = {"old_provider": _OLD_PROVIDER, "new_provider": _NEW_PROVIDER}
    if bind.dialect.name == "sqlite":
        artifact_sql = """
            UPDATE {table}
            SET artifacts = json_set(
                artifacts,
                '$.runtime_artifact.provider',
                :new_provider
            )
            WHERE json_extract(artifacts, '$.runtime_artifact.provider')
                = :old_provider
        """
    else:
        artifact_sql = """
            UPDATE {table}
            SET artifacts = jsonb_set(
                artifacts::jsonb,
                '{{runtime_artifact,provider}}',
                to_jsonb(CAST(:new_provider AS text))
            )::json
            WHERE artifacts -> 'runtime_artifact' ->> 'provider' = :old_provider
        """
    for table in ("node_build_attempts", "node_releases"):
        bind.execute(sa.text(artifact_sql.format(table=table)), params)


def downgrade() -> None:
    # Provider identity is durable. Restoring "daytona" would relabel Docker
    # environments created after this revision.
    return

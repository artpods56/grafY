from datetime import datetime
from typing import cast
from uuid import UUID

import pytest

from grafy_core.domain.plugin_releases import PluginReleaseScope
from grafy_core.domain.plugin_revocations import (
    PluginReleaseRevocation,
    PluginReleaseRevocationError,
    PluginReleaseRevocationReason,
)


RELEASE_ID = UUID("00000000-0000-0000-0000-000000000901")
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000902")
USER_ID = UUID("00000000-0000-0000-0000-000000000903")


def test_revocation_requires_platform_actor_provenance() -> None:
    with pytest.raises(
        PluginReleaseRevocationError,
        match="cannot be revoked by a Workspace user",
    ):
        PluginReleaseRevocation(
            installation_id=RELEASE_ID,
            scope=PluginReleaseScope.SYSTEM,
            workspace_id=None,
            slug="notes",
            revision=1,
            reason=PluginReleaseRevocationReason.SECURITY,
            revoked_by_user_id=USER_ID,
            revoked_by_platform_actor="ci:revoker",
        )

    with pytest.raises(
        PluginReleaseRevocationError,
        match="requires a platform actor",
    ):
        PluginReleaseRevocation(
            installation_id=RELEASE_ID,
            scope=PluginReleaseScope.SYSTEM,
            workspace_id=None,
            slug="notes",
            revision=1,
            reason=PluginReleaseRevocationReason.POLICY,
        )

    with pytest.raises(
        PluginReleaseRevocationError,
        match="visible only in the System namespace",
    ):
        PluginReleaseRevocation(
            installation_id=RELEASE_ID,
            scope=PluginReleaseScope.WORKSPACE,
            workspace_id=WORKSPACE_ID,
            slug="notes",
            revision=1,
            reason=PluginReleaseRevocationReason.POLICY,
            revoked_by_platform_actor="ci:revoker",
        )


def test_revocation_rejects_unsafe_reason_and_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="not a valid PluginReleaseRevocationReason"):
        PluginReleaseRevocation(
            installation_id=RELEASE_ID,
            scope=PluginReleaseScope.SYSTEM,
            workspace_id=None,
            slug="notes",
            revision=1,
            reason=cast(
                PluginReleaseRevocationReason,
                "secret incident details",
            ),
            revoked_by_platform_actor="ci:revoker",
        )

    with pytest.raises(
        PluginReleaseRevocationError,
        match="timestamp must be timezone-aware",
    ):
        PluginReleaseRevocation(
            installation_id=RELEASE_ID,
            scope=PluginReleaseScope.SYSTEM,
            workspace_id=None,
            slug="notes",
            revision=1,
            reason=PluginReleaseRevocationReason.OPERATIONAL,
            revoked_by_platform_actor="ci:revoker",
            revoked_at=datetime(2026, 8, 24, 12, 0),
        )

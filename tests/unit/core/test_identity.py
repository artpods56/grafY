from datetime import UTC, datetime
from uuid import UUID

import pytest

from grafy_core.domain.errors import (
    CapabilityDeniedError,
    IdentityInvariantError,
    LastWorkspaceOwnerError,
)
from grafy_core.domain.identity import (
    ActorContext,
    AuthSession,
    OidcDomainWorkspaceGrant,
    OidcLoginTransaction,
    PAT_ALLOWED_CAPABILITIES,
    PersonalAccessToken,
    parse_oidc_domain_workspace_grants,
    Workspace,
    WorkspaceAccess,
    WorkspaceCapability,
    WorkspaceKind,
    WorkspaceMembership,
    WorkspaceRole,
    ensure_last_owner_can_change,
)
from grafy_core.domain.security_audit import (
    SecurityAuditActorKind,
    SecurityAuditEvent,
    SecurityAuditOutcome,
)


def test_oidc_domain_workspace_grant_matches_exact_verified_domain_only() -> None:
    grant = OidcDomainWorkspaceGrant(
        email_domain="ihpan.edu.pl",
        workspace_slug="ihpan",
        workspace_name="IHPAN",
    )

    assert grant.matches_normalized_email("anna.nowak@ihpan.edu.pl")
    assert not grant.matches_normalized_email("anna.nowak@staff.ihpan.edu.pl")
    assert not grant.matches_normalized_email("anna.nowak@example.ihpan.edu.pl")
    assert not grant.matches_normalized_email("not-ihpan.edu.pl@example.test")


def test_oidc_domain_workspace_grants_parse_deployment_strings() -> None:
    grants = parse_oidc_domain_workspace_grants("ihpan.edu.pl:ihpan:IHPAN")

    assert grants == (
        OidcDomainWorkspaceGrant(
            email_domain="ihpan.edu.pl",
            workspace_slug="ihpan",
            workspace_name="IHPAN",
        ),
    )
    with pytest.raises(ValueError, match="domain:slug"):
        parse_oidc_domain_workspace_grants("ihpan.edu.pl")
    with pytest.raises(ValueError, match="duplicate"):
        parse_oidc_domain_workspace_grants(
            "ihpan.edu.pl:ihpan,ihpan.edu.pl:other:Other"
        )


def test_role_policy_is_explicit_and_owner_is_the_union_of_capabilities() -> None:
    viewer = WorkspaceMembership(
        workspace_id=UUID(int=1),
        user_id=UUID(int=2),
        role=WorkspaceRole.VIEWER,
    )
    editor = WorkspaceMembership(
        workspace_id=UUID(int=1),
        user_id=UUID(int=3),
        role=WorkspaceRole.EDITOR,
    )
    owner = WorkspaceMembership(
        workspace_id=UUID(int=1),
        user_id=UUID(int=4),
        role=WorkspaceRole.OWNER,
    )

    assert viewer.grants(WorkspaceCapability.VIEW_GRAPH)
    assert not viewer.grants(WorkspaceCapability.EDIT_GRAPH)
    assert editor.grants(WorkspaceCapability.CHECKPOINT_GRAPH)
    assert editor.grants(WorkspaceCapability.PUBLISH_MODULE)
    assert not editor.grants(WorkspaceCapability.PUBLISH_PLUGIN)
    assert not editor.grants(WorkspaceCapability.MANAGE_MODULE_LIBRARY)
    assert not editor.grants(WorkspaceCapability.MANAGE_SECRETS)
    assert owner.capabilities == frozenset(WorkspaceCapability)
    assert owner.grants(WorkspaceCapability.MANAGE_MODULE_LIBRARY)
    assert owner.grants(WorkspaceCapability.PUBLISH_PLUGIN)

    with pytest.raises(CapabilityDeniedError) as denied:
        WorkspaceAccess(
            actor=ActorContext(user_id=viewer.user_id),
            workspace_id=viewer.workspace_id,
            membership=viewer,
        ).require(WorkspaceCapability.EDIT_GRAPH)
    assert denied.value.capability == WorkspaceCapability.EDIT_GRAPH.value
    assert denied.value.workspace_id == viewer.workspace_id


def test_membership_state_changes_advance_authorization_version() -> None:
    membership = WorkspaceMembership(
        workspace_id=UUID(int=1),
        user_id=UUID(int=2),
        role=WorkspaceRole.VIEWER,
    )
    assert membership.authorization_version == 1

    membership.change_role(WorkspaceRole.EDITOR)
    assert membership.authorization_version == 2
    membership.revoke()
    assert membership.authorization_version == 3
    membership.reactivate(role=WorkspaceRole.OWNER)
    assert membership.authorization_version == 4
    assert membership.is_active


def test_last_shared_owner_cannot_be_removed_or_demoted() -> None:
    workspace = Workspace.shared(slug="shared", name="Shared")
    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=UUID(int=2),
        role=WorkspaceRole.OWNER,
    )

    with pytest.raises(LastWorkspaceOwnerError):
        ensure_last_owner_can_change(
            workspace=workspace,
            memberships=[membership],
            target=membership,
            replacement_role=WorkspaceRole.EDITOR,
        )
    with pytest.raises(LastWorkspaceOwnerError):
        ensure_last_owner_can_change(
            workspace=workspace,
            memberships=[membership],
            target=membership,
            removing=True,
        )


def test_personal_workspace_has_one_owner_shape() -> None:
    owner_id = UUID(int=22)
    workspace = Workspace.personal(owner_user_id=owner_id)
    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=owner_id,
        role=WorkspaceRole.OWNER,
    )

    assert workspace.slug == owner_id.hex
    assert workspace.personal_owner_user_id == owner_id
    assert membership.grants(WorkspaceCapability.MANAGE_MEMBERS)
    with pytest.raises(IdentityInvariantError):
        Workspace(slug="personal", name="Bad", kind=WorkspaceKind.PERSONAL)


def test_local_is_an_ordinary_shared_workspace_slug() -> None:
    workspace = Workspace.shared(slug="local", name="Local")

    assert workspace.slug == "local"


def test_sensitive_credential_material_is_not_in_default_repr() -> None:
    now = datetime(2026, 8, 7, tzinfo=UTC)
    transaction = OidcLoginTransaction(
        state_digest=b"state-digest",
        nonce_digest=b"nonce-digest",
        encrypted_pkce_verifier=b"encrypted-verifier",
        pkce_key_version=1,
        return_path="/",
        expires_at=now,
    )
    session = AuthSession(
        user_id=UUID(int=1),
        secret_digest=b"session-secret-digest",
        csrf_digest=b"csrf-digest",
        expires_at=now,
    )
    token = PersonalAccessToken(
        user_id=UUID(int=1),
        workspace_id=UUID(int=2),
        public_prefix="nrt_test",
        secret_digest=b"pat-secret-digest",
        label="test",
        scopes=(WorkspaceCapability.VIEW_GRAPH,),
        expires_at=now,
    )

    rendered = f"{transaction!r} {session!r} {token!r}"
    assert "encrypted-verifier" not in rendered
    assert "session-secret-digest" not in rendered
    assert "pat-secret-digest" not in rendered


def test_security_audit_requires_explicit_safe_attribution() -> None:
    event = SecurityAuditEvent(
        actor_kind=SecurityAuditActorKind.AUTHENTICATED,
        user_id=UUID(int=1),
        operation="workspace.membership.remove",
        outcome=SecurityAuditOutcome.SUCCESS,
    )
    assert event.user_id == UUID(int=1)
    with pytest.raises(ValueError):
        SecurityAuditEvent(
            actor_kind=SecurityAuditActorKind.UNAUTHENTICATED,
            user_id=UUID(int=1),
            operation="oidc.callback.failure",
            outcome=SecurityAuditOutcome.FAILURE,
            error_code="invalid_callback",
        )


def test_personal_access_tokens_allow_automation_but_exclude_administration() -> None:
    assert WorkspaceCapability.MANAGE_MEMBERS not in PAT_ALLOWED_CAPABILITIES
    assert WorkspaceCapability.MANAGE_SECRETS in PAT_ALLOWED_CAPABILITIES
    assert WorkspaceCapability.MANAGE_MODULE_LIBRARY not in PAT_ALLOWED_CAPABILITIES
    assert WorkspaceCapability.PUBLISH_PLUGIN in PAT_ALLOWED_CAPABILITIES
    assert WorkspaceCapability.PUBLISH_MODULE in PAT_ALLOWED_CAPABILITIES
    with pytest.raises(ValueError, match="scope is not available"):
        PersonalAccessToken(
            user_id=UUID(int=1),
            workspace_id=UUID(int=2),
            public_prefix="nrt_admin",
            secret_digest=b"pat-secret-digest",
            label="admin",
            scopes=(WorkspaceCapability.MANAGE_MEMBERS,),
            expires_at=datetime(2026, 8, 8, tzinfo=UTC),
        )

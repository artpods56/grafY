import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text

from grafy_core.application.identity import IdentityService
from grafy_core.domain.errors import (
    CredentialAuthenticationError,
    IdentityInvariantError,
    LastWorkspaceOwnerError,
    NotFoundError,
)
from grafy_core.domain.identity import (
    ActorContext,
    AuthSession,
    OidcDomainWorkspaceGrant,
    PersonalAccessToken,
    PlatformAccessToken,
    PlatformTokenScope,
    User,
    WorkspaceCapability,
    WorkspaceInvitation,
    WorkspaceInvitationStatus,
    WorkspaceKind,
    WorkspaceMembership,
    WorkspaceRole,
)
from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    created = create_database(
        f"sqlite+aiosqlite:///{tmp_path / 'identity-app.sqlite3'}"
    )
    async with created.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    try:
        yield created
    finally:
        await created.dispose()


_IHPAN_GRANT = OidcDomainWorkspaceGrant(
    email_domain="ihpan.edu.pl",
    workspace_slug="ihpan",
    workspace_name="IHPAN",
)


def _service(
    database: Database,
    domain_workspace_grants: tuple[OidcDomainWorkspaceGrant, ...] = (),
) -> IdentityService:
    return IdentityService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        domain_workspace_grants=domain_workspace_grants,
    )


def test_workspace_invitation_lifecycle_expires_at_the_boundary() -> None:
    now = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
    invitation = WorkspaceInvitation(
        workspace_id=UUID(int=1),
        invitee_user_id=UUID(int=2),
        invited_by_user_id=UUID(int=3),
        role=WorkspaceRole.VIEWER,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(days=7),
    )

    assert not invitation.expire_if_due(
        now=invitation.expires_at - timedelta(microseconds=1)
    )
    assert invitation.expire_if_due(now=invitation.expires_at)
    assert invitation.status is WorkspaceInvitationStatus.EXPIRED
    assert invitation.resolved_at == invitation.expires_at


@pytest.mark.asyncio
async def test_verified_email_invitation_grants_access_only_after_acceptance(
    database: Database,
) -> None:
    service = _service(database)
    owner = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="invitation-owner",
        email="owner@example.test",
        display_name="Owner",
        email_verified=True,
    )
    invitee = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="invitation-recipient",
        email="Invitee@Example.Test",
        display_name="Invitee",
        email_verified=True,
    )
    workspace = await service.create_shared_workspace(
        actor=ActorContext(user_id=owner.user.id, credential_reference="owner-session"),
        slug="invited-team",
        name="Invited team",
    )

    candidate = await service.resolve_workspace_invitation_candidate(
        actor=ActorContext(user_id=owner.user.id),
        workspace_id=workspace.id,
        email="invitee@example.test",
    )
    assert candidate.id == invitee.user.id
    invitation, _ = await service.create_workspace_invitation(
        actor=ActorContext(user_id=owner.user.id, credential_reference="owner-session"),
        workspace_id=workspace.id,
        email="INVITEE@example.test",
        role=WorkspaceRole.EDITOR,
    )
    assert all(
        listed_workspace.id != workspace.id
        for listed_workspace, _ in await service.list_workspaces(
            actor=ActorContext(user_id=invitee.user.id)
        )
    )

    pending = await service.list_my_workspace_invitations(
        actor=ActorContext(user_id=invitee.user.id)
    )
    assert [
        (item.id, listed_workspace.id) for item, listed_workspace, _ in pending
    ] == [(invitation.id, workspace.id)]
    acceptance = await service.accept_workspace_invitation(
        actor=ActorContext(
            user_id=invitee.user.id,
            credential_reference="invitee-session",
        ),
        invitation_id=invitation.id,
    )
    assert acceptance.invitation.status is WorkspaceInvitationStatus.ACCEPTED
    assert acceptance.workspace == workspace
    assert acceptance.membership.role is WorkspaceRole.EDITOR
    assert [
        (listed_workspace.id, listed_membership.role)
        for listed_workspace, listed_membership in await service.list_workspaces(
            actor=ActorContext(user_id=invitee.user.id)
        )
        if listed_workspace.id == workspace.id
    ] == [(workspace.id, WorkspaceRole.EDITOR)]

    unverified_user = User(
        email="unverified@example.test",
        display_name="Unverified user",
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.identity.add_user(unverified_user)
        await unit_of_work.commit()
    with pytest.raises(NotFoundError):
        await service.resolve_workspace_invitation_candidate(
            actor=ActorContext(user_id=owner.user.id),
            workspace_id=workspace.id,
            email="unverified@example.test",
        )

    with pytest.raises(IdentityInvariantError):
        await service.create_workspace_invitation(
            actor=ActorContext(user_id=owner.user.id),
            workspace_id=workspace.id,
            email="invitee@example.test",
            role=WorkspaceRole.VIEWER,
        )

    declining_user = User(
        email="decline@example.test",
        email_verified=True,
        display_name="Declining user",
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.identity.add_user(declining_user)
        await unit_of_work.commit()
    declining_invitation, _ = await service.create_workspace_invitation(
        actor=ActorContext(user_id=owner.user.id),
        workspace_id=workspace.id,
        email="decline@example.test",
        role=WorkspaceRole.VIEWER,
    )
    with pytest.raises(IdentityInvariantError):
        await service.create_workspace_invitation(
            actor=ActorContext(user_id=owner.user.id),
            workspace_id=workspace.id,
            email="decline@example.test",
            role=WorkspaceRole.OWNER,
        )
    declined = await service.decline_workspace_invitation(
        actor=ActorContext(user_id=declining_user.id),
        invitation_id=declining_invitation.id,
    )
    assert declined.status is WorkspaceInvitationStatus.DECLINED
    assert all(
        listed_workspace.id != workspace.id
        for listed_workspace, _ in await service.list_workspaces(
            actor=ActorContext(user_id=declining_user.id)
        )
    )


@pytest.mark.asyncio
async def test_oidc_provisioning_creates_only_a_personal_workspace(
    database: Database,
) -> None:
    service = _service(database)
    provisioned = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="new-user-subject",
        email="owner@example.test",
        display_name="Owner",
    )

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        workspaces = await unit_of_work.identity.list_workspaces_for_user(
            provisioned.user.id
        )
        provisioning_events = await unit_of_work.security_audit.list_for_workspace(
            provisioned.personal_workspace.id,
            limit=10,
        )
    assert workspaces == [provisioned.personal_workspace]
    assert any(
        event.operation == "oidc.identity.provision"
        and event.resource_type == "user"
        and event.resource_id == str(provisioned.user.id)
        for event in provisioning_events
    )


@pytest.mark.asyncio
async def test_ihpan_login_joins_the_shared_workspace_even_when_email_is_unverified(
    database: Database,
) -> None:
    service = _service(database, domain_workspace_grants=(_IHPAN_GRANT,))
    provisioned = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="ihpan-researcher",
        email="anna.nowak@ihpan.edu.pl",
        display_name="Anna Nowak",
        email_verified=False,
    )

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        workspaces = await unit_of_work.identity.list_workspaces_for_user(
            provisioned.user.id
        )
        memberships = await unit_of_work.identity.list_memberships_for_user(
            provisioned.user.id
        )
    shared = next(workspace for workspace in workspaces if workspace.kind is WorkspaceKind.SHARED)
    shared_membership = next(
        membership
        for membership in memberships
        if membership.workspace_id == shared.id
    )

    assert {workspace.kind for workspace in workspaces} == {
        WorkspaceKind.PERSONAL,
        WorkspaceKind.SHARED,
    }
    assert shared.slug == "ihpan"
    assert shared.name == "IHPAN"
    assert shared_membership.role is WorkspaceRole.OWNER
    assert shared_membership.is_active


@pytest.mark.asyncio
async def test_foreign_email_does_not_join_the_shared_workspace(
    database: Database,
) -> None:
    service = _service(database, domain_workspace_grants=(_IHPAN_GRANT,))
    outsider = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="outsider",
        email="guest@example.test",
        display_name="Guest",
        email_verified=True,
    )
    lookalike = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="lookalike",
        email="guest@staff.ihpan.edu.pl",
        display_name="Lookalike",
        email_verified=True,
    )

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        outsider_workspaces = await unit_of_work.identity.list_workspaces_for_user(
            outsider.user.id
        )
        lookalike_workspaces = await unit_of_work.identity.list_workspaces_for_user(
            lookalike.user.id
        )
        shared = await unit_of_work.identity.lock_workspace_by_slug_for_membership_mutation(
            "ihpan"
        )

    assert all(workspace.kind is WorkspaceKind.PERSONAL for workspace in outsider_workspaces)
    assert all(workspace.kind is WorkspaceKind.PERSONAL for workspace in lookalike_workspaces)
    assert shared is None


@pytest.mark.asyncio
async def test_later_ihpan_logins_join_as_editors_and_revoked_members_stay_out(
    database: Database,
) -> None:
    service = _service(database, domain_workspace_grants=(_IHPAN_GRANT,))
    owner = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="ihpan-owner",
        email="owner@ihpan.edu.pl",
        display_name="Owner",
        email_verified=True,
    )
    editor = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="ihpan-editor",
        email="editor@IHPAN.EDU.PL",
        display_name="Editor",
        email_verified=True,
    )
    returning = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="already-here",
        email="old@example.test",
        display_name="Old",
        email_verified=True,
    )
    returning_after_domain = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="already-here",
        email="old@ihpan.edu.pl",
        display_name="Old",
        email_verified=True,
    )

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        shared = await unit_of_work.identity.lock_workspace_by_slug_for_membership_mutation(
            "ihpan"
        )
        assert shared is not None
        owner_membership = await unit_of_work.identity.get_membership(
            workspace_id=shared.id,
            user_id=owner.user.id,
        )
        editor_membership = await unit_of_work.identity.get_membership(
            workspace_id=shared.id,
            user_id=editor.user.id,
        )
        returning_membership = await unit_of_work.identity.get_membership(
            workspace_id=shared.id,
            user_id=returning.user.id,
        )
        assert editor_membership is not None
        editor_membership.revoke()
        await unit_of_work.commit()

    await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="ihpan-editor",
        email="editor@ihpan.edu.pl",
        display_name="Editor",
        email_verified=True,
    )

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        still_revoked = await unit_of_work.identity.get_membership(
            workspace_id=shared.id,
            user_id=editor.user.id,
        )

    assert owner_membership is not None
    assert owner_membership.role is WorkspaceRole.OWNER
    assert editor_membership.role is WorkspaceRole.EDITOR
    assert returning.user.id == returning_after_domain.user.id
    assert returning_membership is not None
    assert returning_membership.role is WorkspaceRole.EDITOR
    assert still_revoked is not None
    assert not still_revoked.is_active


@pytest.mark.asyncio
async def test_personal_membership_stays_owner_and_membership_changes_are_audited(
    database: Database,
) -> None:
    service = _service(database)
    owner = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="owner-subject",
        email="owner@example.test",
        display_name="Owner",
    )
    member = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="member-subject",
        email="member@example.test",
        display_name="Member",
    )
    shared = await service.create_shared_workspace(
        actor=ActorContext(
            user_id=owner.user.id,
            credential_reference="session-owner",
        ),
        slug="team",
        name="Team",
    )
    with pytest.raises(IdentityInvariantError):
        await service.create_shared_workspace(
            actor=ActorContext(
                user_id=owner.user.id,
                credential_reference="session-owner",
            ),
            slug=" team ",
            name="Duplicate team",
        )

    with pytest.raises(LastWorkspaceOwnerError):
        await service.add_or_reactivate_member(
            actor=ActorContext(
                user_id=owner.user.id,
                credential_reference="session-owner",
            ),
            workspace_id=shared.id,
            user_id=owner.user.id,
            role=WorkspaceRole.VIEWER,
        )

    with pytest.raises(IdentityInvariantError):
        await service.add_or_reactivate_member(
            actor=ActorContext(
                user_id=owner.user.id,
                credential_reference="session-owner",
            ),
            workspace_id=owner.personal_workspace.id,
            user_id=owner.user.id,
            role=WorkspaceRole.VIEWER,
        )

    await service.add_or_reactivate_member(
        actor=ActorContext(
            user_id=owner.user.id,
            credential_reference="session-owner",
        ),
        workspace_id=shared.id,
        user_id=member.user.id,
        role=WorkspaceRole.VIEWER,
    )
    await service.change_member_role(
        actor=ActorContext(
            user_id=owner.user.id,
            credential_reference="session-owner",
        ),
        workspace_id=shared.id,
        user_id=member.user.id,
        role=WorkspaceRole.EDITOR,
    )
    await service.remove_member(
        actor=ActorContext(
            user_id=owner.user.id,
            credential_reference="session-owner",
        ),
        workspace_id=shared.id,
        user_id=member.user.id,
    )

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        events = await unit_of_work.security_audit.list_for_workspace(
            shared.id,
            limit=10,
        )
    operations = {event.operation for event in events}
    assert "workspace.membership.role_change" in operations
    assert "workspace.membership.remove" in operations
    assert all(event.credential_reference == "session-owner" for event in events)

    now = datetime.now(UTC)
    active_session = AuthSession(
        user_id=member.user.id,
        secret_digest=b"session-secret-digest",
        csrf_digest=b"csrf-secret-digest",
        expires_at=now + timedelta(hours=1),
    )
    active_token = PersonalAccessToken(
        user_id=member.user.id,
        workspace_id=shared.id,
        public_prefix="nrt_disable_user_test",
        secret_digest=b"pat-secret-digest",
        label="disable-user-test",
        scopes=(WorkspaceCapability.VIEW_GRAPH,),
        expires_at=now + timedelta(hours=1),
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.identity.add_auth_session(active_session)
        await unit_of_work.identity.add_personal_access_token(active_token)
        await unit_of_work.commit()

    await service.disable_user(user_id=member.user.id)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        stored_session = await unit_of_work.identity.get_auth_session(active_session.id)
        stored_token = (
            await unit_of_work.identity.get_personal_access_token_for_user_workspace(
                token_id=active_token.id,
                user_id=member.user.id,
                workspace_id=shared.id,
            )
        )
    assert stored_session is not None and stored_session.is_revoked
    assert stored_token is not None and stored_token.is_revoked
    async with database.engine.connect() as connection:
        disabled_event = (
            (
                await connection.execute(
                    text(
                        "SELECT resource_type, resource_id "
                        "FROM security_audit_events "
                        "WHERE operation = 'user.disable'"
                    )
                )
            )
            .mappings()
            .one()
        )
    assert disabled_event["resource_type"] == "user"
    assert disabled_event["resource_id"] == str(member.user.id)


def _workspace_pat(
    *,
    user_id: UUID,
    workspace_id: UUID,
    label: str,
    scopes: tuple[WorkspaceCapability, ...],
    secret_digest: bytes,
) -> PersonalAccessToken:
    return PersonalAccessToken(
        user_id=user_id,
        workspace_id=workspace_id,
        public_prefix=f"nrt_{label}"[:32],
        secret_digest=secret_digest,
        label=label,
        scopes=scopes,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


@pytest.mark.asyncio
async def test_membership_and_role_changes_revoke_affected_workspace_pats(
    database: Database,
) -> None:
    service = _service(database)
    owner = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="owner-subject",
        email="owner@example.test",
        display_name="Owner",
    )
    member = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="member-subject",
        email="member@example.test",
        display_name="Member",
    )
    shared = await service.create_shared_workspace(
        actor=ActorContext(
            user_id=owner.user.id,
            credential_reference="session-owner",
        ),
        slug="pat-revocation-team",
        name="PAT revocation team",
    )
    owner_actor = ActorContext(
        user_id=owner.user.id,
        credential_reference="session-owner",
    )
    await service.add_or_reactivate_member(
        actor=owner_actor,
        workspace_id=shared.id,
        user_id=member.user.id,
        role=WorkspaceRole.EDITOR,
    )

    editor_only_token = _workspace_pat(
        user_id=member.user.id,
        workspace_id=shared.id,
        label="editor-only",
        scopes=(WorkspaceCapability.EDIT_GRAPH,),
        secret_digest=b"pat-editor-only-digest",
    )
    viewer_compatible_token = _workspace_pat(
        user_id=member.user.id,
        workspace_id=shared.id,
        label="viewer-compatible",
        scopes=(WorkspaceCapability.VIEW_GRAPH,),
        secret_digest=b"pat-viewer-compatible-digest",
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.identity.add_personal_access_token(editor_only_token)
        await unit_of_work.identity.add_personal_access_token(viewer_compatible_token)
        await unit_of_work.commit()

    await service.change_member_role(
        actor=owner_actor,
        workspace_id=shared.id,
        user_id=member.user.id,
        role=WorkspaceRole.VIEWER,
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        demoted_editor_token = (
            await unit_of_work.identity.get_personal_access_token_for_user_workspace(
                token_id=editor_only_token.id,
                user_id=member.user.id,
                workspace_id=shared.id,
            )
        )
        demoted_viewer_token = (
            await unit_of_work.identity.get_personal_access_token_for_user_workspace(
                token_id=viewer_compatible_token.id,
                user_id=member.user.id,
                workspace_id=shared.id,
            )
        )
        demotion_events = await unit_of_work.security_audit.list_for_workspace(
            shared.id,
            limit=20,
        )
    assert demoted_editor_token is not None and demoted_editor_token.is_revoked
    assert demoted_viewer_token is not None and not demoted_viewer_token.is_revoked
    assert any(
        event.operation == "credential.pat.revoke"
        and event.resource_id == str(editor_only_token.id)
        and event.user_id == owner.user.id
        for event in demotion_events
    )

    removal_token = _workspace_pat(
        user_id=member.user.id,
        workspace_id=shared.id,
        label="remove-member",
        scopes=(WorkspaceCapability.VIEW_GRAPH,),
        secret_digest=b"pat-remove-member-digest",
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.identity.add_personal_access_token(removal_token)
        await unit_of_work.commit()

    await service.remove_member(
        actor=owner_actor,
        workspace_id=shared.id,
        user_id=member.user.id,
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        removed_token = (
            await unit_of_work.identity.get_personal_access_token_for_user_workspace(
                token_id=removal_token.id,
                user_id=member.user.id,
                workspace_id=shared.id,
            )
        )
        still_revoked_editor_token = (
            await unit_of_work.identity.get_personal_access_token_for_user_workspace(
                token_id=editor_only_token.id,
                user_id=member.user.id,
                workspace_id=shared.id,
            )
        )
        removal_events = await unit_of_work.security_audit.list_for_workspace(
            shared.id,
            limit=30,
        )
    assert removed_token is not None and removed_token.is_revoked
    assert (
        still_revoked_editor_token is not None and still_revoked_editor_token.is_revoked
    )
    assert any(
        event.operation == "credential.pat.revoke"
        and event.resource_id == str(removal_token.id)
        for event in removal_events
    )

    editor_revoked_at = still_revoked_editor_token.revoked_at
    viewer_revoked_at = removed_token.revoked_at
    assert editor_revoked_at is not None
    assert viewer_revoked_at is not None

    await service.add_or_reactivate_member(
        actor=owner_actor,
        workspace_id=shared.id,
        user_id=member.user.id,
        role=WorkspaceRole.EDITOR,
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        restored_editor_token = (
            await unit_of_work.identity.get_personal_access_token_for_user_workspace(
                token_id=editor_only_token.id,
                user_id=member.user.id,
                workspace_id=shared.id,
            )
        )
        restored_removal_token = (
            await unit_of_work.identity.get_personal_access_token_for_user_workspace(
                token_id=removal_token.id,
                user_id=member.user.id,
                workspace_id=shared.id,
            )
        )
        membership = await unit_of_work.identity.get_membership(
            workspace_id=shared.id,
            user_id=member.user.id,
        )
    assert membership is not None and membership.is_active
    assert restored_editor_token is not None and restored_editor_token.is_revoked
    assert restored_editor_token.revoked_at == editor_revoked_at
    assert restored_removal_token is not None and restored_removal_token.is_revoked
    assert restored_removal_token.revoked_at == viewer_revoked_at


@pytest.mark.asyncio
async def test_concurrent_owner_removals_preserve_one_shared_owner(
    database: Database,
) -> None:
    service = _service(database)
    owner_one = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="owner-one-subject",
        email="owner-one@example.test",
        display_name="Owner One",
    )
    owner_two = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="owner-two-subject",
        email="owner-two@example.test",
        display_name="Owner Two",
    )
    shared = await service.create_shared_workspace(
        actor=ActorContext(user_id=owner_one.user.id),
        slug="concurrent-team",
        name="Concurrent Team",
    )
    await service.add_or_reactivate_member(
        actor=ActorContext(user_id=owner_one.user.id),
        workspace_id=shared.id,
        user_id=owner_two.user.id,
        role=WorkspaceRole.OWNER,
    )

    results = await asyncio.gather(
        service.remove_member(
            actor=ActorContext(user_id=owner_one.user.id),
            workspace_id=shared.id,
            user_id=owner_one.user.id,
        ),
        service.remove_member(
            actor=ActorContext(user_id=owner_two.user.id),
            workspace_id=shared.id,
            user_id=owner_two.user.id,
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(result, WorkspaceMembership) for result in results) == 1
    assert sum(isinstance(result, LastWorkspaceOwnerError) for result in results) == 1
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        owner_count = await unit_of_work.identity.count_active_owners(shared.id)
    assert owner_count == 1


@pytest.mark.asyncio
async def test_personal_and_platform_credentials_resolve_typed_principals(
    database: Database,
) -> None:
    service = _service(database)
    provisioned = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="publisher",
        email="publisher@example.test",
        display_name="Publisher",
    )
    personal = PersonalAccessToken(
        user_id=provisioned.user.id,
        workspace_id=provisioned.personal_workspace.id,
        public_prefix="nrt_publication",
        secret_digest=b"personal-digest",
        label="publication",
        scopes=(WorkspaceCapability.PUBLISH_PLUGIN,),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    platform = PlatformAccessToken(
        principal_reference="release-bot",
        public_prefix="gpat_publication",
        secret_digest=b"platform-digest",
        label="global publication",
        scopes=(PlatformTokenScope.PUBLISH_GLOBAL,),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await service.create_personal_access_token(
        actor=ActorContext(provisioned.user.id),
        token=personal,
    )
    await service.create_platform_access_token(token=platform)

    workspace_principal = await service.authenticate_personal_access_token(
        public_prefix=personal.public_prefix,
        secret_digest=personal.secret_digest,
        required_capability=WorkspaceCapability.PUBLISH_PLUGIN,
    )
    platform_principal = await service.authenticate_platform_access_token(
        public_prefix=platform.public_prefix,
        secret_digest=platform.secret_digest,
        required_scope=PlatformTokenScope.PUBLISH_GLOBAL,
    )

    assert workspace_principal.actor.user_id == provisioned.user.id
    assert workspace_principal.workspace_id == provisioned.personal_workspace.id
    assert (
        workspace_principal.actor.credential_workspace_id
        == provisioned.personal_workspace.id
    )
    assert platform_principal.principal_reference == "release-bot"
    assert platform_principal.credential_reference == f"platform-token:{platform.id}"

    with pytest.raises(CredentialAuthenticationError):
        await service.authenticate_personal_access_token(
            public_prefix=personal.public_prefix,
            secret_digest=b"wrong-digest",
        )

    other_workspace = await service.create_shared_workspace(
        actor=ActorContext(provisioned.user.id),
        slug="other-pat-workspace",
        name="Other PAT workspace",
    )
    with pytest.raises(NotFoundError):
        await service.authorize(
            actor=workspace_principal.actor,
            workspace_id=other_workspace.id,
            capability=WorkspaceCapability.VIEW_GRAPH,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("active", [True, False])
async def test_role_change_returns_complete_member_after_commit(
    database: Database,
    active: bool,
) -> None:
    service = _service(database)
    owner = await service.provision_oidc_identity(
        issuer="https://issuer.example.test",
        subject="result-owner",
        email="owner@example.test",
        display_name="Owner",
    )
    actor = ActorContext(user_id=owner.user.id)
    workspace = await service.create_shared_workspace(
        actor=actor,
        slug="result-team",
        name="Result team",
    )
    member = User(email="member@example.test", display_name="Member", active=active)
    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=member.id,
        role=WorkspaceRole.EDITOR,
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.identity.add_user(member)
        await unit_of_work.identity.add_membership(membership)
        await unit_of_work.commit()

    result = await service.change_member_role(
        actor=actor,
        workspace_id=workspace.id,
        user_id=member.id,
        role=WorkspaceRole.VIEWER,
    )
    assert result.user == member
    assert result.user.active is active
    assert result.membership.role is WorkspaceRole.VIEWER
    assert (
        result.membership.authorization_version == membership.authorization_version + 1
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        persisted = await unit_of_work.identity.get_membership(
            workspace_id=workspace.id, user_id=member.id
        )
    assert persisted == result.membership

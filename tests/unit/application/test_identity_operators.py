"""Operator-only user disable and re-enable."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from grafy_core.application.identity import IdentityService
from grafy_core.domain.errors import (
    NotFoundError,
    OperatorRequiredError,
    OperatorSelfDisableError,
)
from grafy_core.domain.identity import (
    ActorContext,
    AuthSession,
    IdentityProvisioningResult,
    PersonalAccessToken,
    WorkspaceCapability,
)
from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

ISSUER = "https://issuer.example.test"


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    created = create_database(f"sqlite+aiosqlite:///{tmp_path / 'operators.sqlite3'}")
    async with created.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    try:
        yield created
    finally:
        await created.dispose()


def _service(database: Database) -> IdentityService:
    # Mixed case on purpose: the allowlist matches normalized emails.
    return IdentityService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        operator_emails=("Ops@Example.Test", "second-ops@example.test"),
    )


async def _user(
    service: IdentityService,
    subject: str,
    email: str,
    *,
    email_verified: bool = True,
) -> IdentityProvisioningResult:
    return await service.provision_oidc_identity(
        issuer=ISSUER,
        subject=subject,
        email=email,
        display_name=subject,
        email_verified=email_verified,
    )


def _actor(provisioned: IdentityProvisioningResult) -> ActorContext:
    return ActorContext(
        user_id=provisioned.user.id,
        credential_reference=f"session-{provisioned.user.id}",
    )


async def _give_credentials(
    database: Database, provisioned: IdentityProvisioningResult
) -> tuple[AuthSession, PersonalAccessToken]:
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    session = AuthSession(
        user_id=provisioned.user.id,
        secret_digest=b"session-secret-digest",
        csrf_digest=b"csrf-secret-digest",
        expires_at=expires_at,
    )
    token = PersonalAccessToken(
        user_id=provisioned.user.id,
        workspace_id=provisioned.personal_workspace.id,
        public_prefix=f"nrt_{uuid4().hex[:12]}",
        secret_digest=b"pat-secret-digest",
        label="operator-test",
        scopes=(WorkspaceCapability.VIEW_PROJECT,),
        expires_at=expires_at,
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.identity.add_auth_session(session)
        await unit_of_work.identity.add_personal_access_token(token)
        await unit_of_work.commit()
    return session, token


async def _is_active(
    database: Database, provisioned: IdentityProvisioningResult
) -> bool:
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        user = await unit_of_work.identity.get_user(provisioned.user.id)
    assert user is not None
    return user.active


async def _audit(database: Database, operation: str) -> list[dict[str, object]]:
    async with database.engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT actor_kind, user_id, credential_reference, resource_id "
                    "FROM security_audit_events WHERE operation = :operation"
                ),
                {"operation": operation},
            )
        ).mappings()
        return [dict(row) for row in rows]


async def test_an_operator_disables_and_re_enables_a_user(database: Database) -> None:
    service = _service(database)
    operator = await _user(service, "ops", "ops@example.test")
    target = await _user(service, "target", "target@example.test")
    session, token = await _give_credentials(database, target)

    disabled = await service.disable_user(
        actor=_actor(operator), user_id=target.user.id
    )

    assert not disabled.active
    assert not await _is_active(database, target)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        stored_session = await unit_of_work.identity.get_auth_session(session.id)
        stored_token = (
            await unit_of_work.identity.get_personal_access_token_for_user_workspace(
                token_id=token.id,
                user_id=target.user.id,
                workspace_id=target.personal_workspace.id,
            )
        )
    assert stored_session is not None and stored_session.is_revoked
    assert stored_token is not None and stored_token.is_revoked
    (disable_event,) = await _audit(database, "user.disable")
    assert disable_event["actor_kind"] == "authenticated"
    assert disable_event["credential_reference"] == f"session-{operator.user.id}"
    assert disable_event["resource_id"] == str(target.user.id)
    assert all(
        event["credential_reference"] == f"session-{operator.user.id}"
        for event in await _audit(database, "credential.session.revoke")
    )

    seen = await service.get_user_for_operator(
        actor=_actor(operator), user_id=target.user.id
    )
    assert not seen.active

    enabled = await service.enable_user(actor=_actor(operator), user_id=target.user.id)

    assert enabled.active
    assert await _is_active(database, target)
    (enable_event,) = await _audit(database, "user.enable")
    assert enable_event["actor_kind"] == "authenticated"
    assert enable_event["resource_id"] == str(target.user.id)
    # Re-enabling restores the account, not the credentials the disable revoked.
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        stored_session = await unit_of_work.identity.get_auth_session(session.id)
    assert stored_session is not None and stored_session.is_revoked


@pytest.mark.parametrize(
    ("email", "email_verified"),
    [
        ("member@example.test", True),
        ("ops@example.test", False),
    ],
    ids=["not-listed", "listed-but-unverified"],
)
async def test_only_a_verified_listed_operator_may_act(
    database: Database, email: str, email_verified: bool
) -> None:
    service = _service(database)
    caller = await _user(service, "caller", email, email_verified=email_verified)
    target = await _user(service, "target", "target@example.test")

    with pytest.raises(OperatorRequiredError):
        await service.disable_user(actor=_actor(caller), user_id=target.user.id)
    with pytest.raises(OperatorRequiredError):
        await service.enable_user(actor=_actor(caller), user_id=target.user.id)
    with pytest.raises(OperatorRequiredError):
        await service.get_user_for_operator(
            actor=_actor(caller), user_id=target.user.id
        )

    assert await _is_active(database, target)
    assert await _audit(database, "user.disable") == []


async def test_a_workspace_pat_never_carries_operator_authority(
    database: Database,
) -> None:
    service = _service(database)
    operator = await _user(service, "ops", "ops@example.test")
    target = await _user(service, "target", "target@example.test")
    pat_actor = ActorContext(
        user_id=operator.user.id,
        credential_reference="pat-ops",
        credential_workspace_id=operator.personal_workspace.id,
    )

    with pytest.raises(OperatorRequiredError):
        await service.disable_user(actor=pat_actor, user_id=target.user.id)
    assert await _is_active(database, target)


async def test_an_operator_cannot_disable_themselves(database: Database) -> None:
    service = _service(database)
    operator = await _user(service, "ops", "ops@example.test")

    with pytest.raises(OperatorSelfDisableError):
        await service.disable_user(actor=_actor(operator), user_id=operator.user.id)
    assert await _is_active(database, operator)


async def test_a_disabled_operator_loses_operator_authority(
    database: Database,
) -> None:
    service = _service(database)
    first = await _user(service, "ops", "ops@example.test")
    second = await _user(service, "second-ops", "second-ops@example.test")

    await service.disable_user(actor=_actor(second), user_id=first.user.id)

    with pytest.raises(OperatorRequiredError):
        await service.enable_user(actor=_actor(first), user_id=first.user.id)
    await service.enable_user(actor=_actor(second), user_id=first.user.id)
    assert await _is_active(database, first)


async def test_an_unknown_user_is_not_found(database: Database) -> None:
    service = _service(database)
    operator = await _user(service, "ops", "ops@example.test")

    with pytest.raises(NotFoundError):
        await service.disable_user(actor=_actor(operator), user_id=uuid4())
    with pytest.raises(NotFoundError):
        await service.enable_user(actor=_actor(operator), user_id=uuid4())


async def test_without_configured_operators_nobody_may_act(
    database: Database,
) -> None:
    service = IdentityService(lambda: SqlAlchemyUnitOfWork(database.sessions))
    caller = await _user(service, "ops", "ops@example.test")
    target = await _user(service, "target", "target@example.test")

    with pytest.raises(OperatorRequiredError):
        await service.disable_user(actor=_actor(caller), user_id=target.user.id)

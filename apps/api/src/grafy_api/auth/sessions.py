"""Browser sessions and personal access tokens, without an HTTP request."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hmac
from secrets import token_urlsafe
from uuid import UUID

from grafy_core.domain.identity import (
    PAT_ALLOWED_CAPABILITIES,
    AuthSession,
    PersonalAccessToken,
    WorkspaceCapability,
)
from grafy_core.domain.security_audit import (
    SecurityAuditActorKind,
    SecurityAuditEvent,
    SecurityAuditOutcome,
)
from grafy_core.ports.identity import IdentityUnitOfWorkPort

from grafy_api.auth.secrets import digest_secret


# Stored rows and clients address a token by this prefix. It is the wire format.
PAT_PUBLIC_PREFIX = "nrt_"


@dataclass(frozen=True, slots=True)
class IssuedSession:
    session: AuthSession
    cookie_value: str = field(repr=False)
    csrf_value: str = field(repr=False)


def parse_session_cookie(value: str) -> tuple[UUID, str]:
    identifier, separator, secret = value.partition(".")
    if not separator or not secret:
        raise ValueError("invalid session cookie")
    try:
        session_id = UUID(identifier)
    except ValueError as exc:
        raise ValueError("invalid session cookie") from exc
    return session_id, secret


def session_id_from_cookie(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value.partition(".")[0])
    except ValueError:
        return None


def credential_matches(session: AuthSession, secret: str) -> bool:
    if session.is_revoked:
        return False
    return hmac.compare_digest(session.secret_digest, digest_secret(secret))


def session_is_expired(
    session: AuthSession,
    *,
    now: datetime,
    idle_seconds: int,
) -> bool:
    last_activity = session.last_used_at or session.created_at
    return session.expires_at <= now or now - last_activity >= timedelta(
        seconds=idle_seconds
    )


def valid_session_from_cookie(
    session: AuthSession | None,
    cookie_value: str | None,
    *,
    idle_seconds: int,
) -> AuthSession | None:
    if session is None or cookie_value is None:
        return None
    _, separator, secret = cookie_value.partition(".")
    if not separator or not secret:
        return None
    now = datetime.now(UTC)
    if not credential_matches(session, secret) or session_is_expired(
        session,
        now=now,
        idle_seconds=idle_seconds,
    ):
        return None
    return session


def session_audit_event(
    *,
    user_id: UUID,
    credential_reference: str | None,
    operation: str,
    session_id: UUID,
) -> SecurityAuditEvent:
    return SecurityAuditEvent(
        actor_kind=SecurityAuditActorKind.AUTHENTICATED,
        user_id=user_id,
        credential_reference=credential_reference,
        operation=operation,
        outcome=SecurityAuditOutcome.SUCCESS,
        resource_type="auth_session",
        resource_id=str(session_id),
    )


async def issue_session_in_unit_of_work(
    unit_of_work: IdentityUnitOfWorkPort,
    user_id: UUID,
    *,
    replacing_cookie: str | None,
    absolute_seconds: int,
    idle_seconds: int,
) -> IssuedSession:
    session_secret = token_urlsafe(32)
    csrf_value = token_urlsafe(32)
    session = AuthSession(
        user_id=user_id,
        secret_digest=digest_secret(session_secret),
        csrf_digest=digest_secret(csrf_value),
        expires_at=datetime.now(UTC) + timedelta(seconds=absolute_seconds),
    )
    await persist_session_in_unit_of_work(
        unit_of_work,
        session,
        replacing_cookie=replacing_cookie,
        idle_seconds=idle_seconds,
    )
    return IssuedSession(
        session=session,
        cookie_value=f"{session.id}.{session_secret}",
        csrf_value=csrf_value,
    )


async def persist_session_in_unit_of_work(
    unit_of_work: IdentityUnitOfWorkPort,
    session: AuthSession,
    *,
    replacing_cookie: str | None,
    idle_seconds: int,
) -> None:
    replacing_session_id = session_id_from_cookie(replacing_cookie)
    replaced = None
    if replacing_session_id is not None:
        replaced = valid_session_from_cookie(
            await unit_of_work.identity.get_auth_session(replacing_session_id),
            replacing_cookie,
            idle_seconds=idle_seconds,
        )
    if replaced is not None:
        replaced.revoke()
        await unit_of_work.security_audit.add(
            session_audit_event(
                user_id=replaced.user_id,
                credential_reference=f"session:{replaced.id}",
                operation="credential.session.revoke",
                session_id=replaced.id,
            )
        )
    await unit_of_work.identity.add_auth_session(session)
    await unit_of_work.security_audit.add(
        session_audit_event(
            user_id=session.user_id,
            credential_reference=f"session:{session.id}",
            operation="credential.session.create",
            session_id=session.id,
        )
    )


def issue_personal_access_token(
    *,
    user_id: UUID,
    workspace_id: UUID,
    label: str,
    scopes: tuple[WorkspaceCapability, ...],
    expires_at: datetime,
) -> tuple[PersonalAccessToken, str]:
    if not set(scopes).issubset(PAT_ALLOWED_CAPABILITIES):
        raise ValueError("Personal access token scope is not available")
    secret = token_urlsafe(32)
    public_prefix = f"{PAT_PUBLIC_PREFIX}{secret[:12]}"
    token = PersonalAccessToken(
        user_id=user_id,
        workspace_id=workspace_id,
        public_prefix=public_prefix,
        secret_digest=digest_secret(secret),
        label=label,
        scopes=scopes,
        expires_at=expires_at,
    )
    return token, f"{public_prefix}.{secret}"


def parse_personal_access_token(value: str) -> tuple[str, str]:
    public_prefix, separator, secret = value.partition(".")
    if (
        not separator
        or not public_prefix
        or not secret
        or not public_prefix.startswith(PAT_PUBLIC_PREFIX)
    ):
        raise ValueError("invalid personal access token")
    return public_prefix, secret

"""OIDC and browser credential security at the API boundary."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import math
from secrets import token_bytes, token_urlsafe
from collections.abc import Callable
from typing import Any, NoReturn, cast
from urllib.parse import urlsplit
from uuid import UUID

from authlib.jose import JsonWebToken, JoseError
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.exceptions import InvalidTag
import httpx
from fastapi import HTTPException, Request, Response, status

from grafy_core.application.identity import IdentityService
from grafy_core.domain.errors import (
    CredentialAuthenticationError,
    NotFoundError,
    UserDisabledError,
)
from grafy_core.domain.identity import (
    ActorContext,
    AuthSession,
    IdentityProvisioningResult,
    OidcLoginTransaction,
    PAT_ALLOWED_CAPABILITIES,
    PersonalAccessToken,
    WorkspaceCapability,
    WorkspacePatPrincipal,
)
from grafy_core.domain.security_audit import (
    SecurityAuditActorKind,
    SecurityAuditEvent,
    SecurityAuditOutcome,
)
from grafy_core.ports.identity import IdentityUnitOfWorkPort

from grafy_api.diagnostics import (
    DiagnosticContext,
    diagnostic_scope,
    record_failure,
)
from grafy_api.settings import Settings
from grafy_api.v1.routes.auth.abuse import (
    AuthAbuseControl,
    BrowserAbuseKeys,
    request_browser_keys,
    set_browser_abuse_cookie as _set_browser_abuse_cookie,
)


SESSION_COOKIE = "grafy_session"
CSRF_COOKIE = "grafy_csrf"
OIDC_TRANSACTION_COOKIE = "grafy_oidc_transaction"


class OidcProtocolError(Exception):
    """A bounded OIDC failure safe to expose as a generic HTTP error."""

    def __init__(self, code: str, *, transaction_consumed: bool = False) -> None:
        self.code = code
        self.transaction_consumed = transaction_consumed
        super().__init__(code)


class OidcCallbackInternalError(Exception):
    """Safe internal callback failure with transaction lifecycle state."""

    def __init__(self, *, transaction_consumed: bool) -> None:
        self.transaction_consumed = transaction_consumed
        super().__init__("callback_internal_error")


@dataclass(frozen=True, slots=True)
class IssuedSession:
    session: AuthSession
    cookie_value: str = field(repr=False)
    csrf_value: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        unit_of_work_factory: Callable[[], IdentityUnitOfWorkPort],
        identity_service: IdentityService,
        abuse_control: AuthAbuseControl | None = None,
    ) -> None:
        self._settings = settings
        self._unit_of_work_factory = unit_of_work_factory
        self._identity_service = identity_service
        configured_browser_cookie_secret = settings.oidc_auth_wrapping_key
        self._browser_cookie_secret = (
            configured_browser_cookie_secret.get_secret_value().encode("utf-8")
            if configured_browser_cookie_secret is not None
            else token_bytes(32)
        )
        self._abuse_control = abuse_control or AuthAbuseControl(
            window_seconds=settings.auth_rate_window_seconds,
            login_start_limit=settings.auth_login_start_rate_limit,
            callback_limit=settings.auth_callback_rate_limit,
            session_failure_limit=settings.auth_session_failure_rate_limit,
            pat_creation_limit=settings.auth_pat_creation_rate_limit,
            outstanding_login_limit=settings.auth_outstanding_login_limit,
            network_outstanding_login_limit=(
                settings.auth_outstanding_login_network_limit
            ),
            outstanding_login_ttl_seconds=settings.oidc_login_transaction_ttl_seconds,
        )
        self._provider_metadata: ProviderMetadata | None = None
        self._provider_metadata_expires_at: datetime | None = None
        self._jwks: dict[str, object] | list[object] | None = None
        self._jwks_expires_at: datetime | None = None

    async def start_login(
        self,
        *,
        return_path: str,
        transaction_id: UUID | None = None,
    ) -> tuple[str, UUID]:
        self._require_oidc_configuration()
        safe_return_path = self._validate_return_path(return_path)
        metadata = await self._provider()
        state = token_urlsafe(32)
        nonce = token_urlsafe(32)
        verifier = token_urlsafe(32)
        transaction_id = transaction_id or UUID(bytes=token_bytes(16))
        now = datetime.now(UTC)
        transaction = OidcLoginTransaction(
            id=transaction_id,
            state_digest=self.digest_secret(state),
            nonce_digest=self.digest_secret(nonce),
            encrypted_pkce_verifier=self._encrypt_verifier(
                verifier,
                transaction_id,
            ),
            pkce_key_version=self._settings.oidc_auth_wrapping_key_version,
            return_path=safe_return_path,
            created_at=now,
            expires_at=now
            + timedelta(seconds=self._settings.oidc_login_transaction_ttl_seconds),
        )
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.identity.add_login_transaction(transaction)
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.UNAUTHENTICATED,
                    operation="oidc.login.start",
                    outcome=SecurityAuditOutcome.SUCCESS,
                )
            )
            await unit_of_work.commit()
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        authorization_params = {
            "response_type": "code",
            "client_id": self._require_value(self._settings.oidc_client_id),
            "redirect_uri": self._settings.oidc_callback_url,
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return (
            f"{metadata.authorization_endpoint}?{httpx.QueryParams(authorization_params)}",
            transaction_id,
        )

    async def callback(
        self,
        *,
        transaction_id_value: str | None,
        state: str | None,
        code: str | None,
        error: str | None,
        current_session_cookie: str | None = None,
    ) -> tuple[IdentityProvisioningResult, IssuedSession, str]:
        self._require_oidc_configuration()
        transaction_id = self._parse_transaction_id(transaction_id_value)
        if error is not None or code is None or state is None:
            consumed = await self._consume_transaction_for_failure(
                transaction_id,
                state=state,
            )
            raise OidcProtocolError(
                "provider_callback_failed",
                transaction_consumed=consumed,
            )
        transaction, verifier, return_path = await self._consume_transaction(
            transaction_id=transaction_id,
            state=state,
        )
        issued: IssuedSession | None = None
        try:
            try:
                claims = await self._exchange_code(
                    code=code,
                    verifier=verifier,
                    nonce_digest=transaction.nonce_digest,
                )
            except (httpx.HTTPError, OidcProtocolError, JoseError) as exc:
                raise OidcProtocolError(
                    "provider_token_validation_failed",
                    transaction_consumed=True,
                ) from exc
            issuer = self._require_value(self._settings.oidc_issuer)
            subject = claims.get("sub")
            if not isinstance(subject, str) or not subject:
                raise OidcProtocolError("missing_subject", transaction_consumed=True)
            email = claims.get("email")
            email_verified = claims.get("email_verified") is True
            display_name = claims.get("name")
            if not isinstance(email, str):
                email = None
            if not isinstance(display_name, str):
                display_name = None
            try:
                provisioned = await self._identity_service.provision_oidc_identity(
                    issuer=issuer,
                    subject=subject,
                    email=email,
                    display_name=display_name,
                    email_verified=email_verified,
                )
            except UserDisabledError as exc:
                raise OidcProtocolError(
                    "identity_not_eligible",
                    transaction_consumed=True,
                ) from exc
            async with self._unit_of_work_factory() as unit_of_work:
                issued = await self._issue_session_in_unit_of_work(
                    unit_of_work,
                    provisioned.user.id,
                    replacing_cookie=current_session_cookie,
                )
                await unit_of_work.security_audit.add(
                    SecurityAuditEvent(
                        actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                        user_id=provisioned.user.id,
                        credential_reference=f"session:{issued.session.id}",
                        operation="oidc.callback.success",
                        outcome=SecurityAuditOutcome.SUCCESS,
                        resource_type="auth_session",
                        resource_id=str(issued.session.id),
                    )
                )
                await unit_of_work.commit()
            return provisioned, issued, return_path
        except OidcProtocolError:
            raise
        except Exception as exc:
            raise OidcCallbackInternalError(transaction_consumed=True) from exc

    async def issue_session(
        self,
        user_id: UUID,
        *,
        replacing_cookie: str | None = None,
    ) -> IssuedSession:
        async with self._unit_of_work_factory() as unit_of_work:
            issued = await self._issue_session_in_unit_of_work(
                unit_of_work,
                user_id,
                replacing_cookie=replacing_cookie,
            )
            await unit_of_work.commit()
        return issued

    async def _issue_session_in_unit_of_work(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        user_id: UUID,
        *,
        replacing_cookie: str | None,
    ) -> IssuedSession:
        session_secret = token_urlsafe(32)
        csrf_value = token_urlsafe(32)
        session = AuthSession(
            user_id=user_id,
            secret_digest=self.digest_secret(session_secret),
            csrf_digest=self.digest_secret(csrf_value),
            expires_at=datetime.now(UTC)
            + timedelta(seconds=self._settings.auth_session_absolute_seconds),
        )
        await self._persist_session_in_unit_of_work(
            unit_of_work,
            session,
            replacing_cookie=replacing_cookie,
        )
        return IssuedSession(
            session=session,
            cookie_value=f"{session.id}.{session_secret}",
            csrf_value=csrf_value,
        )

    async def _persist_session_in_unit_of_work(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        session: AuthSession,
        *,
        replacing_cookie: str | None,
    ) -> None:
        replacing_session_id = self._session_id_from_cookie(replacing_cookie)
        replaced = None
        if replacing_session_id is not None:
            replaced = self._valid_session_from_cookie(
                await unit_of_work.identity.get_auth_session(replacing_session_id),
                replacing_cookie,
            )
        if replaced is not None:
            replaced.revoke()
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=replaced.user_id,
                    credential_reference=f"session:{replaced.id}",
                    operation="credential.session.revoke",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    resource_type="auth_session",
                    resource_id=str(replaced.id),
                )
            )
        await unit_of_work.identity.add_auth_session(session)
        await unit_of_work.security_audit.add(
            SecurityAuditEvent(
                actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                user_id=session.user_id,
                credential_reference=f"session:{session.id}",
                operation="credential.session.create",
                outcome=SecurityAuditOutcome.SUCCESS,
                resource_type="auth_session",
                resource_id=str(session.id),
            )
        )

    def issue_personal_access_token(
        self,
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
        public_prefix = f"nrt_{secret[:12]}"
        token = PersonalAccessToken(
            user_id=user_id,
            workspace_id=workspace_id,
            public_prefix=public_prefix,
            secret_digest=self.digest_secret(secret),
            label=label,
            scopes=scopes,
            expires_at=expires_at,
        )
        return token, f"{public_prefix}.{secret}"

    async def require_browser_actor(self, request: Request) -> ActorContext:
        cookie_value = request.cookies.get(SESSION_COOKIE)
        if cookie_value is None:
            await self._raise_authentication_required(request)
        try:
            session_id, secret = self._parse_session_cookie(cookie_value)
        except HTTPException as exc:
            if not await self._abuse_control.allow_session_failure(
                self.browser_abuse_keys(request).browser_key
            ):
                raise HTTPException(
                    status_code=429, detail="Too many authentication attempts"
                ) from exc
            raise
        async with self._unit_of_work_factory() as unit_of_work:
            session = await unit_of_work.identity.get_auth_session(session_id)
            if (
                session is None
                or session.is_revoked
                or not hmac.compare_digest(
                    session.secret_digest,
                    self.digest_secret(secret),
                )
            ):
                await self._raise_authentication_required(request)
            now = datetime.now(UTC)
            last_activity = session.last_used_at or session.created_at
            idle_expired = now - last_activity >= timedelta(
                seconds=self._settings.auth_session_idle_seconds
            )
            if session.expires_at <= now or idle_expired:
                session.revoke(revoked_at=now)
                await unit_of_work.commit()
                await self._raise_authentication_required(request)
            user = await unit_of_work.identity.get_user(session.user_id)
            if user is None or not user.active:
                session.revoke(revoked_at=now)
                await unit_of_work.commit()
                await self._raise_authentication_required(request)
            request.state.auth_session = session
            request.state.auth_actor_user_id = session.user_id
            request.state.auth_credential_reference = f"session:{session.id}"
            self._check_cookie_request(request)
            session.last_used_at = now
            await unit_of_work.commit()
        return ActorContext(
            user_id=session.user_id,
            credential_reference=f"session:{session.id}",
        )

    async def require_workspace_pat_principal(
        self,
        request: Request,
        authorization: str,
    ) -> WorkspacePatPrincipal:
        scheme, separator, value = authorization.partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not value
            or any(character.isspace() for character in value)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            public_prefix, secret = self._parse_personal_access_token(value)
            principal = await self._identity_service.authenticate_personal_access_token(
                public_prefix=public_prefix,
                secret_digest=self.digest_secret(secret),
            )
        except (CredentialAuthenticationError, HTTPException) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        request.state.auth_actor_user_id = principal.actor.user_id
        request.state.auth_credential_reference = principal.actor.credential_reference
        return principal

    async def current_session(self, request: Request) -> AuthSession:
        session = getattr(request.state, "auth_session", None)
        if not isinstance(session, AuthSession):
            await self.require_browser_actor(request)
            session = request.state.auth_session
        return cast(AuthSession, session)

    async def logout(self, request: Request) -> None:
        session = await self.current_session(request)
        async with self._unit_of_work_factory() as unit_of_work:
            stored = await unit_of_work.identity.get_auth_session(session.id)
            if stored is not None:
                stored.revoke()
                await unit_of_work.security_audit.add(
                    SecurityAuditEvent(
                        actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                        user_id=session.user_id,
                        credential_reference=f"session:{session.id}",
                        operation="credential.session.revoke",
                        outcome=SecurityAuditOutcome.SUCCESS,
                        resource_type="auth_session",
                        resource_id=str(session.id),
                    )
                )
                await unit_of_work.commit()

    async def audit_unauthenticated_failure(
        self,
        *,
        operation: str,
        error_code: str,
        workspace_id: UUID | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> None:
        event = SecurityAuditEvent(
            actor_kind=SecurityAuditActorKind.UNAUTHENTICATED,
            operation=operation,
            outcome=SecurityAuditOutcome.FAILURE,
            workspace_id=workspace_id,
            resource_type=resource_type,
            resource_id=resource_id,
            error_code=error_code,
        )
        await self._write_failure_audit_event(event)

    async def audit_authenticated_failure(
        self,
        *,
        user_id: UUID,
        credential_reference: str,
        operation: str,
        error_code: str,
        workspace_id: UUID | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> None:
        event = SecurityAuditEvent(
            actor_kind=SecurityAuditActorKind.AUTHENTICATED,
            user_id=user_id,
            credential_reference=credential_reference,
            operation=operation,
            outcome=SecurityAuditOutcome.FAILURE,
            workspace_id=workspace_id,
            resource_type=resource_type,
            resource_id=resource_id,
            error_code=error_code,
        )
        await self._write_failure_audit_event(event)

    async def _write_failure_audit_event(self, event: SecurityAuditEvent) -> None:
        try:
            async with self._unit_of_work_factory() as unit_of_work:
                await unit_of_work.security_audit.add(event)
                await unit_of_work.commit()
        except Exception as exc:
            context = DiagnosticContext(
                actor_id=event.user_id,
                workspace_id=event.workspace_id,
            )
            with diagnostic_scope(context, inherit=True):
                record_failure(
                    exc,
                    operation=f"security.audit.write.{event.operation}",
                )

    async def audit_request_failure(
        self,
        request: Request,
        *,
        operation: str,
        error_code: str,
        workspace_id: UUID | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> None:
        user_id = getattr(request.state, "auth_actor_user_id", None)
        credential_reference = getattr(request.state, "auth_credential_reference", None)
        if isinstance(user_id, UUID) and isinstance(credential_reference, str):
            await self.audit_authenticated_failure(
                user_id=user_id,
                credential_reference=credential_reference,
                operation=operation,
                error_code=error_code,
                workspace_id=workspace_id,
                resource_type=resource_type,
                resource_id=resource_id,
            )
            return
        await self.audit_unauthenticated_failure(
            operation=operation,
            error_code=error_code,
            workspace_id=workspace_id,
            resource_type=resource_type,
            resource_id=resource_id,
        )

    async def list_sessions(self, *, actor: ActorContext) -> list[AuthSession]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.identity.list_auth_sessions_for_user(
                actor.user_id
            )

    async def revoke_session(
        self,
        *,
        actor: ActorContext,
        session_id: UUID,
    ) -> AuthSession:
        async with self._unit_of_work_factory() as unit_of_work:
            session = await unit_of_work.identity.get_auth_session_for_user(
                session_id=session_id,
                user_id=actor.user_id,
            )
            if session is None:
                raise NotFoundError("Auth session", str(session_id))
            session.revoke()
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    operation="credential.session.revoke",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    resource_type="auth_session",
                    resource_id=str(session.id),
                )
            )
            await unit_of_work.commit()
            return session

    def set_session_cookies(self, response: Response, issued: IssuedSession) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            issued.cookie_value,
            max_age=self._settings.auth_session_absolute_seconds,
            httponly=True,
            secure=self._settings.auth_cookie_secure,
            samesite="lax",
            path="/",
        )
        response.set_cookie(
            CSRF_COOKIE,
            issued.csrf_value,
            max_age=self._settings.auth_session_absolute_seconds,
            httponly=False,
            secure=self._settings.auth_cookie_secure,
            samesite="lax",
            path="/",
        )

    def clear_session_cookies(self, response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")

    def clear_transaction_cookie(self, response: Response) -> None:
        response.delete_cookie(
            OIDC_TRANSACTION_COOKIE,
            path="/api/v1/auth/oidc",
        )

    def set_transaction_cookie(self, response: Response, transaction_id: str) -> None:
        response.set_cookie(
            OIDC_TRANSACTION_COOKIE,
            transaction_id,
            max_age=self._settings.oidc_login_transaction_ttl_seconds,
            httponly=True,
            secure=self._settings.auth_cookie_secure,
            samesite="lax",
            path="/api/v1/auth/oidc",
        )

    async def cleanup_expired(
        self, *, now: datetime | None = None
    ) -> tuple[int, int, int]:
        cutoff = now or datetime.now(UTC)
        async with self._unit_of_work_factory() as unit_of_work:
            transactions = (
                await unit_of_work.identity.delete_expired_login_transactions(cutoff)
            )
            sessions = await unit_of_work.identity.delete_expired_sessions(cutoff)
            tokens = await unit_of_work.identity.delete_expired_personal_access_tokens(
                cutoff
            )
            await unit_of_work.commit()
        return transactions, sessions, tokens

    def browser_abuse_keys(self, request: Request) -> BrowserAbuseKeys:
        return request_browser_keys(request, secret=self._browser_cookie_secret)

    def set_browser_abuse_cookie(
        self,
        response: Response,
        browser_key: str,
    ) -> None:
        _set_browser_abuse_cookie(
            response,
            browser_key,
            secret=self._browser_cookie_secret,
            secure=self._settings.auth_cookie_secure,
        )

    async def allow_login_start(
        self,
        browser_key: str,
        network_key: str | None = None,
    ) -> bool:
        return await self._abuse_control.allow_login_start(browser_key, network_key)

    async def allow_callback(
        self,
        browser_key: str,
        network_key: str | None = None,
    ) -> bool:
        return await self._abuse_control.allow_callback(browser_key, network_key)

    async def allow_pat_creation(self, user_key: str) -> bool:
        return await self._abuse_control.allow_pat_creation(user_key)

    async def reserve_login(
        self,
        browser_key: str,
        transaction_id: UUID,
        network_key: str | None = None,
    ) -> bool:
        return await self._abuse_control.reserve_login(
            browser_key,
            transaction_id,
            network_key,
        )

    async def release_login(
        self,
        transaction_id_value: str | None,
    ) -> None:
        if transaction_id_value is None:
            return
        try:
            transaction_id = UUID(transaction_id_value)
        except ValueError:
            return
        await self._abuse_control.release_login(transaction_id)

    async def cleanup_malformed_callback(self, request: Request) -> bool:
        """Consume pending login state and return whether callback limits allow it."""
        abuse_keys = self.browser_abuse_keys(request)
        allowed = await self.allow_callback(
            abuse_keys.browser_key,
            abuse_keys.network_key,
        )
        consumed_transaction_id = await self.replace_login_transaction(
            request.cookies.get(OIDC_TRANSACTION_COOKIE)
        )
        if consumed_transaction_id is not None:
            await self.release_login(str(consumed_transaction_id))
        return allowed

    async def replace_login_transaction(self, value: str | None) -> UUID | None:
        if value is None:
            return None
        try:
            transaction_id = UUID(value)
        except ValueError:
            return None
        async with self._unit_of_work_factory() as unit_of_work:
            transaction = await unit_of_work.identity.lock_login_transaction(
                transaction_id
            )
            if transaction is None or transaction.is_consumed:
                return None
            transaction.consume()
            await unit_of_work.commit()
            return transaction_id

    async def _consume_transaction(
        self,
        *,
        transaction_id: UUID,
        state: str,
    ) -> tuple[OidcLoginTransaction, str, str]:
        async with self._unit_of_work_factory() as unit_of_work:
            transaction = await unit_of_work.identity.lock_login_transaction(
                transaction_id
            )
            if transaction is None or transaction.is_consumed:
                raise OidcProtocolError("invalid_login_transaction")
            if transaction.expires_at <= datetime.now(UTC):
                transaction.consume()
                await unit_of_work.commit()
                raise OidcProtocolError(
                    "expired_login_transaction",
                    transaction_consumed=True,
                )
            if not hmac.compare_digest(
                transaction.state_digest, self.digest_secret(state)
            ):
                transaction.consume()
                await unit_of_work.commit()
                raise OidcProtocolError("invalid_state", transaction_consumed=True)
            try:
                verifier = self._decrypt_verifier(transaction)
            except OidcProtocolError:
                transaction.consume()
                await unit_of_work.commit()
                raise OidcProtocolError(
                    "invalid_pkce_verifier",
                    transaction_consumed=True,
                )
            transaction.consume()
            await unit_of_work.commit()
            return transaction, verifier, transaction.return_path

    async def _consume_transaction_for_failure(
        self,
        transaction_id: UUID,
        *,
        state: str | None,
    ) -> bool:
        async with self._unit_of_work_factory() as unit_of_work:
            transaction = await unit_of_work.identity.lock_login_transaction(
                transaction_id
            )
            if transaction is None or transaction.is_consumed:
                return False
            if state is not None and not hmac.compare_digest(
                transaction.state_digest,
                self.digest_secret(state),
            ):
                transaction.consume()
                await unit_of_work.commit()
                raise OidcProtocolError("invalid_state", transaction_consumed=True)
            transaction.consume()
            await unit_of_work.commit()
            return True

    async def _exchange_code(
        self,
        *,
        code: str,
        verifier: str,
        nonce_digest: bytes,
    ) -> dict[str, object]:
        metadata = await self._provider()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._settings.oidc_callback_url,
            "client_id": self._require_value(self._settings.oidc_client_id),
            "code_verifier": verifier,
        }
        if self._settings.oidc_client_secret is not None:
            data["client_secret"] = self._settings.oidc_client_secret.get_secret_value()
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(metadata.token_endpoint, data=data)
        if response.status_code != 200:
            raise OidcProtocolError("provider_token_exchange_failed")
        try:
            raw_payload = response.json()
        except (TypeError, ValueError) as exc:
            raise OidcProtocolError("invalid_token_response") from exc
        if not isinstance(raw_payload, dict):
            raise OidcProtocolError("missing_id_token")
        payload = cast(dict[str, object], raw_payload)
        id_token = payload.get("id_token")
        if not isinstance(id_token, str):
            raise OidcProtocolError("missing_id_token")
        return await self._validate_id_token(id_token, nonce_digest=nonce_digest)

    async def _validate_id_token(
        self,
        encoded: str,
        *,
        nonce_digest: bytes,
    ) -> dict[str, object]:
        jwks = await self._keys()
        decoder: Any = JsonWebToken(self._settings.oidc_allowed_signing_algorithms)
        try:
            claims = decoder.decode(encoded, cast(Any, jwks))
        except (JoseError, ValueError, TypeError):
            try:
                refreshed_jwks = await self._keys(force_refresh=True)
                claims = decoder.decode(encoded, cast(Any, refreshed_jwks))
            except (JoseError, OidcProtocolError, ValueError, TypeError) as refresh_exc:
                raise OidcProtocolError("invalid_id_token") from refresh_exc
        try:
            claims.validate(leeway=60)
        except (JoseError, ValueError, TypeError) as exc:
            raise OidcProtocolError("invalid_id_token") from exc
        values = cast(dict[str, object], dict(claims))
        issuer = self._require_value(self._settings.oidc_issuer)
        if values.get("iss") != issuer:
            raise OidcProtocolError("invalid_issuer")
        audience = values.get("aud")
        client_id = self._require_value(self._settings.oidc_client_id)
        if isinstance(audience, str):
            audiences = [audience]
        elif isinstance(audience, list):
            audience_values = cast(list[object], audience)
            audiences = [item for item in audience_values if isinstance(item, str)]
            if len(audiences) != len(audience_values):
                raise OidcProtocolError("invalid_audience")
        else:
            raise OidcProtocolError("invalid_audience")
        if client_id not in audiences:
            raise OidcProtocolError("invalid_audience")
        authorized_party = values.get("azp")
        if authorized_party is not None and authorized_party != client_id:
            raise OidcProtocolError("invalid_authorized_party")
        if len(audiences) > 1 and authorized_party != client_id:
            raise OidcProtocolError("missing_authorized_party")
        if not isinstance(values.get("sub"), str):
            raise OidcProtocolError("missing_subject")
        nonce = values.get("nonce")
        if not isinstance(nonce, str) or not nonce:
            raise OidcProtocolError("missing_nonce")
        if not hmac.compare_digest(nonce_digest, self.digest_secret(nonce)):
            raise OidcProtocolError("invalid_nonce")
        for claim in ("exp", "iat"):
            claim_value = values.get(claim)
            if (
                isinstance(claim_value, bool)
                or not isinstance(claim_value, (int, float))
                or not math.isfinite(claim_value)
            ):
                raise OidcProtocolError(f"missing_{claim}")
        now = datetime.now(UTC).timestamp()
        exp = cast(float, values["exp"])
        issued_at = cast(float, values["iat"])
        if exp <= now - 60:
            raise OidcProtocolError("expired_id_token")
        if issued_at > now + 60:
            raise OidcProtocolError("future_id_token")
        not_before = values.get("nbf")
        if not_before is not None and (
            isinstance(not_before, bool)
            or not isinstance(not_before, (int, float))
            or not math.isfinite(not_before)
            or not_before > now + 60
        ):
            raise OidcProtocolError("future_id_token")
        return values

    async def _provider(self) -> ProviderMetadata:
        now = datetime.now(UTC)
        if (
            self._provider_metadata is not None
            and self._provider_metadata_expires_at is not None
        ):
            if self._provider_metadata_expires_at > now:
                return self._provider_metadata
        issuer = self._require_value(self._settings.oidc_issuer)
        discovery_url = f"{issuer}/.well-known/openid-configuration"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(discovery_url)
            response.raise_for_status()
            raw_payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            if (
                self._provider_metadata is not None
                and self._provider_metadata_expires_at is not None
                and self._provider_metadata_expires_at > now
            ):
                return self._provider_metadata
            raise OidcProtocolError("provider_discovery_unavailable") from exc
        if not isinstance(raw_payload, dict):
            raise OidcProtocolError("invalid_provider_metadata")
        payload = cast(dict[str, object], raw_payload)
        if payload.get("issuer") != issuer:
            raise OidcProtocolError("provider_issuer_mismatch")
        authorization_endpoint = payload.get("authorization_endpoint")
        token_endpoint = payload.get("token_endpoint")
        jwks_uri = payload.get("jwks_uri")
        if not all(
            isinstance(value, str)
            for value in (authorization_endpoint, token_endpoint, jwks_uri)
        ):
            raise OidcProtocolError("invalid_provider_metadata")
        authorization_url = cast(str, authorization_endpoint)
        token_url = cast(str, token_endpoint)
        keys_url = cast(str, jwks_uri)
        metadata = ProviderMetadata(
            issuer=issuer,
            authorization_endpoint=authorization_url,
            token_endpoint=token_url,
            jwks_uri=keys_url,
        )
        self._provider_metadata = metadata
        self._provider_metadata_expires_at = now + timedelta(minutes=5)
        return metadata

    async def _keys(
        self, *, force_refresh: bool = False
    ) -> dict[str, object] | list[object]:
        now = datetime.now(UTC)
        if (
            not force_refresh
            and self._jwks is not None
            and self._jwks_expires_at is not None
        ):
            if self._jwks_expires_at > now:
                return self._jwks
        metadata = await self._provider()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(metadata.jwks_uri)
            response.raise_for_status()
            raw_payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            if (
                self._jwks is not None
                and self._jwks_expires_at is not None
                and self._jwks_expires_at > now
                and not force_refresh
            ):
                return self._jwks
            raise OidcProtocolError("provider_keys_unavailable") from exc
        if not isinstance(raw_payload, (dict, list)):
            raise OidcProtocolError("invalid_provider_keys")
        payload = cast(dict[str, object] | list[object], raw_payload)
        self._jwks = payload
        self._jwks_expires_at = now + timedelta(minutes=5)
        return payload

    def _encrypt_verifier(self, verifier: str, transaction_id: UUID) -> bytes:
        nonce = token_bytes(12)
        ciphertext = ChaCha20Poly1305(self._wrapping_key()).encrypt(
            nonce,
            verifier.encode("ascii"),
            transaction_id.bytes,
        )
        return nonce + ciphertext

    def _decrypt_verifier(self, transaction: OidcLoginTransaction) -> str:
        if (
            transaction.pkce_key_version
            != self._settings.oidc_auth_wrapping_key_version
        ):
            raise OidcProtocolError("unsupported_key_version")
        encrypted = transaction.encrypted_pkce_verifier
        try:
            plaintext = ChaCha20Poly1305(self._wrapping_key()).decrypt(
                encrypted[:12],
                encrypted[12:],
                transaction.id.bytes,
            )
            return plaintext.decode("ascii")
        except (InvalidTag, ValueError, UnicodeDecodeError) as exc:
            raise OidcProtocolError("invalid_pkce_verifier") from exc

    def _check_cookie_request(self, request: Request) -> None:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return
        if request.headers.get("origin") != self._settings.public_origin:
            raise HTTPException(status_code=403, detail="Origin validation failed")
        csrf_cookie = request.cookies.get(CSRF_COOKIE)
        csrf_header = request.headers.get("x-csrf-token")
        if csrf_cookie is None or csrf_header is None:
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        session = cast(AuthSession, request.state.auth_session)
        if not hmac.compare_digest(csrf_cookie, csrf_header) or not hmac.compare_digest(
            session.csrf_digest,
            self.digest_secret(csrf_header),
        ):
            raise HTTPException(status_code=403, detail="CSRF validation failed")

    def _validate_return_path(self, value: str) -> str:
        parsed = urlsplit(value)
        if (
            not value.startswith("/")
            or value.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or "\x00" in value
            or "\\" in value
        ):
            raise OidcProtocolError("invalid_return_path")
        return value

    def _parse_transaction_id(self, value: str | None) -> UUID:
        if value is None:
            raise OidcProtocolError("missing_login_transaction")
        try:
            return UUID(value)
        except ValueError as exc:
            raise OidcProtocolError("invalid_login_transaction") from exc

    def _parse_session_cookie(self, value: str) -> tuple[UUID, str]:
        identifier, separator, secret = value.partition(".")
        if not separator or not secret:
            raise HTTPException(status_code=401, detail="Authentication required")
        try:
            session_id = UUID(identifier)
        except ValueError as exc:
            raise HTTPException(
                status_code=401, detail="Authentication required"
            ) from exc
        return session_id, secret

    @staticmethod
    def _parse_personal_access_token(value: str) -> tuple[str, str]:
        public_prefix, separator, secret = value.partition(".")
        if not separator or not public_prefix or not secret:
            raise HTTPException(status_code=401, detail="Authentication required")
        if not public_prefix.startswith("nrt_"):
            raise HTTPException(status_code=401, detail="Authentication required")
        return public_prefix, secret

    @staticmethod
    def _session_id_from_cookie(value: str | None) -> UUID | None:
        if value is None:
            return None
        try:
            return UUID(value.partition(".")[0])
        except ValueError:
            return None

    def _valid_session_from_cookie(
        self,
        session: AuthSession | None,
        cookie_value: str | None,
    ) -> AuthSession | None:
        if session is None or cookie_value is None:
            return None
        _, separator, secret = cookie_value.partition(".")
        if not separator or not secret:
            return None
        last_activity = session.last_used_at or session.created_at
        now = datetime.now(UTC)
        if (
            session.is_revoked
            or session.expires_at <= now
            or now - last_activity
            >= timedelta(seconds=self._settings.auth_session_idle_seconds)
        ):
            return None
        if not hmac.compare_digest(session.secret_digest, self.digest_secret(secret)):
            return None
        return session

    async def _raise_authentication_required(self, request: Request) -> NoReturn:
        if not await self._abuse_control.allow_session_failure(
            self.browser_abuse_keys(request).browser_key
        ):
            raise HTTPException(
                status_code=429, detail="Too many authentication attempts"
            )
        raise HTTPException(status_code=401, detail="Authentication required")

    def _wrapping_key(self) -> bytes:
        self._require_oidc_configuration()
        configured_key = self._settings.oidc_auth_wrapping_key
        if configured_key is None:
            raise OidcProtocolError("oidc_not_configured")
        value = configured_key.get_secret_value()
        return hashlib.sha256(value.encode()).digest()

    def _require_oidc_configuration(self) -> None:
        if not self._settings.oidc_is_configured:
            raise OidcProtocolError("oidc_not_configured")

    @staticmethod
    def _require_value(value: str | None) -> str:
        if value is None or not value.strip():
            raise OidcProtocolError("oidc_not_configured")
        return value

    @staticmethod
    def digest_secret(value: str) -> bytes:
        return hashlib.sha256(value.encode("utf-8")).digest()


def bounded_oidc_failure(error: OidcProtocolError) -> HTTPException:
    del error
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="OIDC callback failed",
    )


__all__ = [
    "AuthService",
    "CSRF_COOKIE",
    "IssuedSession",
    "OIDC_TRANSACTION_COOKIE",
    "OidcProtocolError",
    "SESSION_COOKIE",
    "bounded_oidc_failure",
]

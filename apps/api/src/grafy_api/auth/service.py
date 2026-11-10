"""Browser login, session, and personal-access-token workflows.

OIDC protocol, login transactions, session credentials, and audit writes live
in their own modules. This type is the workflow those pieces share, including
the request-state the browser routes read.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from secrets import token_bytes, token_urlsafe
from typing import NoReturn, cast
from uuid import UUID

from authlib.jose import JoseError
from fastapi import HTTPException, Request, Response, status
import httpx

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
from grafy_shared.config import AuthConfig

from grafy_api.auth.abuse import (
    AuthAbuseControl,
    BrowserAbuseKeys,
    request_browser_keys,
    set_browser_abuse_cookie as write_browser_abuse_cookie,
)
from grafy_api.auth.audit import failure_audit_event, write_failure_audit_event
from grafy_api.auth.errors import (
    OidcCallbackInternalError,
    OidcProtocolError,
    require_config_value,
)
from grafy_api.auth.http import (
    OIDC_TRANSACTION_COOKIE,
    SESSION_COOKIE,
    check_cookie_request,
    clear_session_cookies,
    clear_transaction_cookie,
    set_session_cookies,
    set_transaction_cookie,
)
from grafy_api.auth.provider import pkce_challenge
from grafy_api.auth.provider import OidcProvider
from grafy_api.auth.secrets import digest_secret as hash_secret
from grafy_api.auth.sessions import (
    IssuedSession,
    credential_matches,
    issue_personal_access_token as mint_personal_access_token,
    issue_session_in_unit_of_work,
    parse_personal_access_token,
    parse_session_cookie,
    session_audit_event,
    session_is_expired,
)
from grafy_api.auth.transactions import LoginTransactions


class AuthService:
    def __init__(
        self,
        *,
        auth: AuthConfig,
        public_origin: str,
        unit_of_work_factory: Callable[[], IdentityUnitOfWorkPort],
        identity_service: IdentityService,
        abuse_control: AuthAbuseControl | None = None,
    ) -> None:
        self._auth = auth
        # public_origin is AppConfig and oidc_callback_path is AuthConfig; the
        # browser redirect target is their only joint derivation, so it is resolved
        # once here rather than giving either section a copy of the other's value.
        self._public_origin = public_origin
        self._oidc_callback_url = auth.resolved_callback_url(public_origin)
        self._unit_of_work_factory = unit_of_work_factory
        self._identity_service = identity_service
        configured_browser_cookie_secret = auth.oidc_auth_wrapping_key
        self._browser_cookie_secret = (
            configured_browser_cookie_secret.get_secret_value().encode("utf-8")
            if configured_browser_cookie_secret is not None
            else token_bytes(32)
        )
        self.abuse = abuse_control or AuthAbuseControl(
            window_seconds=auth.auth_rate_window_seconds,
            login_start_limit=auth.auth_login_start_rate_limit,
            callback_limit=auth.auth_callback_rate_limit,
            session_failure_limit=auth.auth_session_failure_rate_limit,
            pat_creation_limit=auth.auth_pat_creation_rate_limit,
            outstanding_login_limit=auth.auth_outstanding_login_limit,
            network_outstanding_login_limit=(auth.auth_outstanding_login_network_limit),
            outstanding_login_ttl_seconds=auth.oidc_login_transaction_ttl_seconds,
        )
        self.provider = OidcProvider(auth, callback_url=self._oidc_callback_url)
        self.transactions = LoginTransactions(auth)

    @staticmethod
    def digest_secret(value: str) -> bytes:
        return hash_secret(value)

    @property
    def pat_max_lifetime_seconds(self) -> int:
        """The configured ceiling for one personal access token's expiry."""

        return self._auth.personal_access_token_max_lifetime_seconds

    async def start_login(
        self,
        *,
        return_path: str,
        transaction_id: UUID | None = None,
    ) -> tuple[str, UUID]:
        self.transactions.require_configured()
        safe_return_path = self.transactions.validate_return_path(return_path)
        metadata = await self.provider.discover()
        state = token_urlsafe(32)
        nonce = token_urlsafe(32)
        verifier = token_urlsafe(32)
        transaction_id = transaction_id or UUID(bytes=token_bytes(16))
        now = datetime.now(UTC)
        transaction = OidcLoginTransaction(
            id=transaction_id,
            state_digest=hash_secret(state),
            nonce_digest=hash_secret(nonce),
            encrypted_pkce_verifier=self.transactions.encrypt_verifier(
                verifier,
                transaction_id,
            ),
            pkce_key_version=self._auth.oidc_auth_wrapping_key_version,
            return_path=safe_return_path,
            created_at=now,
            expires_at=now
            + timedelta(seconds=self._auth.oidc_login_transaction_ttl_seconds),
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
        authorization_params = {
            "response_type": "code",
            "client_id": self.transactions.client_id(),
            "redirect_uri": self._oidc_callback_url,
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce_challenge(verifier),
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
        self.transactions.require_configured()
        transaction_id = self.transactions.parse_transaction_id(transaction_id_value)
        if error is not None or code is None or state is None:
            consumed = await self.transactions.consume_for_failure(
                self._unit_of_work_factory,
                transaction_id,
                state=state,
            )
            raise OidcProtocolError(
                "provider_callback_failed",
                transaction_consumed=consumed,
            )
        _transaction, verifier, return_path = (
            await self.transactions.consume_for_callback(
                unit_of_work_factory=self._unit_of_work_factory,
                transaction_id=transaction_id,
                state=state,
            )
        )
        try:
            try:
                claims = await self.provider.exchange_code(
                    code=code,
                    verifier=verifier,
                    nonce_digest=_transaction.nonce_digest,
                )
            except (httpx.HTTPError, OidcProtocolError, JoseError) as exc:
                raise OidcProtocolError(
                    "provider_token_validation_failed",
                    transaction_consumed=True,
                ) from exc
            issuer = require_config_value(self._auth.oidc_issuer)
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
                issued = await issue_session_in_unit_of_work(
                    unit_of_work,
                    provisioned.user.id,
                    replacing_cookie=current_session_cookie,
                    absolute_seconds=self._auth.auth_session_absolute_seconds,
                    idle_seconds=self._auth.auth_session_idle_seconds,
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
            issued = await issue_session_in_unit_of_work(
                unit_of_work,
                user_id,
                replacing_cookie=replacing_cookie,
                absolute_seconds=self._auth.auth_session_absolute_seconds,
                idle_seconds=self._auth.auth_session_idle_seconds,
            )
            await unit_of_work.commit()
        return issued

    def issue_personal_access_token(
        self,
        *,
        user_id: UUID,
        workspace_id: UUID,
        label: str,
        scopes: tuple[WorkspaceCapability, ...],
        expires_at: datetime,
    ) -> tuple[PersonalAccessToken, str]:
        return mint_personal_access_token(
            user_id=user_id,
            workspace_id=workspace_id,
            label=label,
            scopes=scopes,
            expires_at=expires_at,
        )

    async def require_browser_actor(self, request: Request) -> ActorContext:
        cookie_value = request.cookies.get(SESSION_COOKIE)
        if cookie_value is None:
            await self._raise_authentication_required(request)
        try:
            session_id, secret = parse_session_cookie(cookie_value)
        except ValueError as exc:
            if not await self.abuse.allow_session_failure(
                self.browser_abuse_keys(request).browser_key
            ):
                raise HTTPException(
                    status_code=429, detail="Too many authentication attempts"
                ) from exc
            raise HTTPException(
                status_code=401, detail="Authentication required"
            ) from exc
        async with self._unit_of_work_factory() as unit_of_work:
            session = await unit_of_work.identity.get_auth_session(session_id)
            if session is None or not credential_matches(session, secret):
                await self._raise_authentication_required(request)
            now = datetime.now(UTC)
            if session_is_expired(
                session,
                now=now,
                idle_seconds=self._auth.auth_session_idle_seconds,
            ):
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
            check_cookie_request(request, public_origin=self._public_origin)
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
            public_prefix, secret = parse_personal_access_token(value)
            principal = await self._identity_service.authenticate_personal_access_token(
                public_prefix=public_prefix,
                secret_digest=hash_secret(secret),
            )
        except (CredentialAuthenticationError, ValueError) as exc:
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
                    session_audit_event(
                        user_id=session.user_id,
                        credential_reference=f"session:{session.id}",
                        operation="credential.session.revoke",
                        session_id=session.id,
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
        await write_failure_audit_event(
            self._unit_of_work_factory,
            failure_audit_event(
                actor_kind=SecurityAuditActorKind.UNAUTHENTICATED,
                operation=operation,
                error_code=error_code,
                workspace_id=workspace_id,
                resource_type=resource_type,
                resource_id=resource_id,
            ),
        )

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
        await write_failure_audit_event(
            self._unit_of_work_factory,
            failure_audit_event(
                actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                operation=operation,
                error_code=error_code,
                user_id=user_id,
                credential_reference=credential_reference,
                workspace_id=workspace_id,
                resource_type=resource_type,
                resource_id=resource_id,
            ),
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
                session_audit_event(
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    operation="credential.session.revoke",
                    session_id=session.id,
                )
            )
            await unit_of_work.commit()
            return session

    def set_session_cookies(self, response: Response, issued: IssuedSession) -> None:
        set_session_cookies(
            response,
            issued,
            max_age=self._auth.auth_session_absolute_seconds,
            secure=self._auth.auth_cookie_secure,
        )

    def clear_session_cookies(self, response: Response) -> None:
        clear_session_cookies(response)

    def clear_transaction_cookie(self, response: Response) -> None:
        clear_transaction_cookie(response)

    def set_transaction_cookie(self, response: Response, transaction_id: str) -> None:
        set_transaction_cookie(
            response,
            transaction_id,
            max_age=self._auth.oidc_login_transaction_ttl_seconds,
            secure=self._auth.auth_cookie_secure,
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

    def set_browser_abuse_cookie(self, response: Response, browser_key: str) -> None:
        write_browser_abuse_cookie(
            response,
            browser_key,
            secret=self._browser_cookie_secret,
            secure=self._auth.auth_cookie_secure,
        )

    async def replace_login_transaction(self, value: str | None) -> UUID | None:
        return await self.transactions.replace(self._unit_of_work_factory, value)

    async def release_login(self, transaction_id_value: str | None) -> None:
        if transaction_id_value is None:
            return
        try:
            transaction_id = UUID(transaction_id_value)
        except ValueError:
            return
        await self.abuse.release_login(transaction_id)

    async def cleanup_malformed_callback(self, request: Request) -> bool:
        """Consume pending login state and return whether callback limits allow it."""

        abuse_keys = self.browser_abuse_keys(request)
        allowed = await self.abuse.allow_callback(
            abuse_keys.browser_key,
            abuse_keys.network_key,
        )
        consumed_transaction_id = await self.replace_login_transaction(
            request.cookies.get(OIDC_TRANSACTION_COOKIE)
        )
        if consumed_transaction_id is not None:
            await self.release_login(str(consumed_transaction_id))
        return allowed

    async def _raise_authentication_required(self, request: Request) -> NoReturn:
        if not await self.abuse.allow_session_failure(
            self.browser_abuse_keys(request).browser_key
        ):
            raise HTTPException(
                status_code=429, detail="Too many authentication attempts"
            )
        raise HTTPException(status_code=401, detail="Authentication required")

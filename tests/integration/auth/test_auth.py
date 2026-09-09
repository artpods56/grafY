import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr, TypeAdapter
import pytest
from sqlalchemy import select

from grafy_api.settings import Settings
from grafy_api.v1.routes.auth.abuse import (
    BROWSER_ABUSE_COOKIE,
    make_browser_abuse_cookie,
)
from grafy_api.v1.routes.workspaces.models import (
    PersonalAccessTokenCreatedResponse,
    PersonalAccessTokenCreateRequest,
    PersonalAccessTokenScope,
    WorkspaceCreateRequest,
    WorkspaceInvitationCreateRequest,
)
from grafy_api.v1.routes.auth.services import (
    OIDC_TRANSACTION_COOKIE,
    AuthService,
    IssuedSession,
    OidcProtocolError,
)
from grafy_core.application.identity import IdentityService
from grafy_core.domain.identity import (
    OidcLoginTransaction,
    WorkspaceCapability,
    WorkspaceRole,
)
from grafy_core.domain.security_audit import (
    SecurityAuditActorKind,
    SecurityAuditEvent,
    SecurityAuditOutcome,
)
from grafy_persistence import schema
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.support.clients import GrafyApi
from tests.support.factories.identity import IdentitySeeder
from tests.testkit import (
    app_with_overrides,
    client_with_overrides,
    create_db_url,
    db,
    seed,
)


def _csrf_headers(issued: IssuedSession) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": issued.csrf_value}


def _auth_service(settings: Settings, database: Database) -> AuthService:
    def unit_of_work_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(database.sessions)

    return AuthService(
        settings=settings,
        unit_of_work_factory=unit_of_work_factory,
        identity_service=IdentityService(unit_of_work_factory),
    )


async def _seed_oidc_transaction(
    database: Database,
    auth: AuthService,
    settings: Settings,
    transaction_id: UUID,
    *,
    state: str,
    expires_at: datetime,
) -> None:
    transaction = OidcLoginTransaction(
        id=transaction_id,
        state_digest=auth.digest_secret(state),
        nonce_digest=auth.digest_secret("callback-nonce"),
        # Pre-seeding a transaction with a known verifier requires the
        # private wrapper; start_login would need a live provider round-trip.
        encrypted_pkce_verifier=auth._encrypt_verifier(  # pyright: ignore[reportPrivateUsage]
            "verifier",
            transaction_id,
        ),
        pkce_key_version=settings.oidc_auth_wrapping_key_version,
        return_path="/",
        expires_at=expires_at,
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.identity.add_login_transaction(transaction)
        await unit_of_work.commit()


async def test_v1_routes_fail_closed_but_health_is_public(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "auth.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        _, workspace, _ = await seed(database.sessions)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)

            assert api.workspace(workspace.id).list_members().status_code == 401
            assert api.workspaces.list().status_code == 401
            assert api.auth.get_session().status_code == 401


async def test_unauthenticated_workspace_failure_is_audited_once(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "workspace-auth-failure.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        _, _, _ = await seed(database.sessions)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)

            assert api.workspaces.list().status_code == 401

        async with database.sessions() as session:
            events = list(
                await session.scalars(
                    select(SecurityAuditEvent).where(
                        schema.security_audit_events.c.operation.in_(
                            ["auth.session.verify", "workspace.list"]
                        )
                    )
                )
            )

        assert [(e.operation, e.error_code, e.actor_kind) for e in events] == [
            (
                "auth.session.verify",
                "authentication_required",
                SecurityAuditActorKind.UNAUTHENTICATED,
            )
        ]


async def test_session_verification_failures_are_rate_limited(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "auth-rate.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "auth_session_failure_rate_limit": 1,
            }
        )
        _, _, _ = await seed(database.sessions)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)

            assert api.auth.get_session().status_code == 401
            assert api.auth.get_session().status_code == 429


async def test_cookie_requests_require_exact_origin_and_csrf(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "csrf.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        user, _, _ = await seed(database.sessions)
        issued = await _auth_service(app_settings, database).issue_session(user.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(issued)
            payload = WorkspaceCreateRequest(slug="team", name="Team")

            assert api.workspaces.create(payload).status_code == 403
            assert (
                api.workspaces.create(
                    payload,
                    headers={
                        "Origin": "http://evil.example",
                        "X-CSRF-Token": issued.csrf_value,
                    },
                ).status_code
                == 403
            )

        async with database.sessions() as session:
            events = list(
                await session.scalars(
                    select(SecurityAuditEvent).where(
                        schema.security_audit_events.c.operation
                        == "auth.session.verify"
                    )
                )
            )

        assert events
        assert all(
            event.actor_kind is SecurityAuditActorKind.AUTHENTICATED for event in events
        )
        assert {event.error_code for event in events} == {"origin_rejected"}


async def test_authenticated_csrf_failure_is_audited_once_at_auth_boundary(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "csrf-single-audit.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        user, _, _ = await seed(database.sessions)
        issued = await _auth_service(app_settings, database).issue_session(user.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(issued)

            response = api.workspaces.create(
                WorkspaceCreateRequest(slug="team", name="Team"),
                headers={
                    "Origin": "http://testserver",
                    "X-CSRF-Token": "wrong-csrf-token",
                },
            )

            assert response.status_code == 403

        async with database.sessions() as session:
            events = list(
                await session.scalars(
                    select(SecurityAuditEvent).where(
                        schema.security_audit_events.c.operation.in_(
                            ["auth.session.verify", "workspace.create"]
                        )
                    )
                )
            )

        assert [(e.operation, e.error_code) for e in events] == [
            ("auth.session.verify", "csrf_rejected")
        ]


async def test_session_idle_expiry_is_enforced_at_boundary(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "idle.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        user, _, _ = await seed(database.sessions)
        issued = await _auth_service(app_settings, database).issue_session(user.id)
        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            stored = await unit_of_work.identity.get_auth_session(issued.session.id)
            assert stored is not None
            stored.last_used_at = datetime.now(UTC) - timedelta(
                seconds=app_settings.auth_session_idle_seconds
            )
            await unit_of_work.commit()

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(issued)

            assert api.auth.get_session().status_code == 401


async def test_session_absolute_expiry_is_enforced(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "absolute.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        user, _, _ = await seed(database.sessions)
        issued = await _auth_service(app_settings, database).issue_session(user.id)
        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            stored = await unit_of_work.identity.get_auth_session(issued.session.id)
            assert stored is not None
            stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await unit_of_work.commit()

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(issued)

            assert api.auth.get_session().status_code == 401


async def test_logout_revokes_the_current_session(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "logout.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        user, _, _ = await seed(database.sessions)
        issued = await _auth_service(app_settings, database).issue_session(user.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(issued)

            assert api.auth.logout(headers=_csrf_headers(issued)).status_code == 204
            assert api.auth.get_session().status_code == 401

        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            session = await unit_of_work.identity.get_auth_session(issued.session.id)

        assert session is not None
        assert session.is_revoked


async def test_expired_callback_consumes_transaction_and_releases_reservation(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "expired-callback.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "oidc_issuer": "https://issuer.example.test",
                "oidc_client_id": "grafy-client",
                "oidc_auth_wrapping_key": SecretStr("expired-callback-key"),
                "auth_outstanding_login_limit": 1,
            }
        )
        _, _, _ = await seed(database.sessions)
        application = app_with_overrides(settings=app_settings)
        # The OIDC handlers and abuse-cookie middleware resolve the service
        # through application.state, and the outstanding-login slots live in
        # that instance, so callback flows must drive it directly.
        auth = application.state.identity.auth_service
        transaction_id = UUID(int=701)
        await _seed_oidc_transaction(
            database,
            auth,
            app_settings,
            transaction_id,
            state="expired-state",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        await auth.reserve_login("expired-browser", transaction_id)

        with TestClient(application) as client:
            configured_key = app_settings.oidc_auth_wrapping_key
            assert configured_key is not None
            wrapping_key = configured_key.get_secret_value().encode("utf-8")
            client.cookies.set(
                BROWSER_ABUSE_COOKIE,
                make_browser_abuse_cookie("expired-browser", secret=wrapping_key),
            )
            client.cookies.set(OIDC_TRANSACTION_COOKIE, str(transaction_id))

            response = client.get(
                "/v1/auth/oidc/callback",
                params={"state": "expired-state", "code": "expired-code"},
            )

            assert response.status_code == 400
            assert OIDC_TRANSACTION_COOKIE in response.headers.get("set-cookie", "")

        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            transaction = await unit_of_work.identity.get_login_transaction(
                transaction_id
            )

        assert transaction is not None
        assert transaction.is_consumed
        assert await auth.reserve_login("expired-browser", UUID(int=702))


async def test_callback_failure_before_consumption_preserves_transaction_and_slot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    settings: Settings,
) -> None:
    database_url = create_db_url(tmp_path, "callback-before-consume.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "oidc_issuer": "https://issuer.example.test",
                "oidc_client_id": "grafy-client",
                "oidc_auth_wrapping_key": SecretStr("before-consume-key"),
                "auth_outstanding_login_limit": 1,
            }
        )
        _, _, _ = await seed(database.sessions)
        application = app_with_overrides(settings=app_settings)
        # The OIDC handlers and abuse-cookie middleware resolve the service
        # through application.state, and the outstanding-login slots live in
        # that instance, so callback flows must drive it directly.
        auth = application.state.identity.auth_service
        transaction_id = UUID(int=703)
        await _seed_oidc_transaction(
            database,
            auth,
            app_settings,
            transaction_id,
            state="before-state",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await auth.reserve_login("before-browser", transaction_id)

        async def fail_before_consumption(**_kwargs: object) -> tuple[object, str, str]:
            raise RuntimeError("before-consumption sentinel")

        monkeypatch.setattr(auth, "_consume_transaction", fail_before_consumption)

        with TestClient(application, raise_server_exceptions=False) as client:
            configured_key = app_settings.oidc_auth_wrapping_key
            assert configured_key is not None
            wrapping_key = configured_key.get_secret_value().encode("utf-8")
            client.cookies.set(
                BROWSER_ABUSE_COOKIE,
                make_browser_abuse_cookie("before-browser", secret=wrapping_key),
            )
            client.cookies.set(OIDC_TRANSACTION_COOKIE, str(transaction_id))

            response = client.get(
                "/v1/auth/oidc/callback",
                params={"state": "before-state", "code": "before-code"},
            )

            assert response.status_code == 500
            assert OIDC_TRANSACTION_COOKIE not in response.headers.get("set-cookie", "")

        assert not await auth.reserve_login("before-browser", UUID(int=704))

        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            transaction = await unit_of_work.identity.get_login_transaction(
                transaction_id
            )

        assert transaction is not None
        assert not transaction.is_consumed


async def test_callback_failure_after_consumption_clears_transaction_and_releases_slot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    settings: Settings,
) -> None:
    database_url = create_db_url(tmp_path, "callback-after-consume.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "oidc_issuer": "https://issuer.example.test",
                "oidc_client_id": "grafy-client",
                "oidc_auth_wrapping_key": SecretStr("after-consume-key"),
                "auth_outstanding_login_limit": 1,
            }
        )
        _, _, _ = await seed(database.sessions)
        application = app_with_overrides(settings=app_settings)
        # The OIDC handlers and abuse-cookie middleware resolve the service
        # through application.state, and the outstanding-login slots live in
        # that instance, so callback flows must drive it directly.
        auth = application.state.identity.auth_service
        transaction_id = UUID(int=705)
        await _seed_oidc_transaction(
            database,
            auth,
            app_settings,
            transaction_id,
            state="after-state",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await auth.reserve_login("after-browser", transaction_id)

        async def fail_after_consumption(**_kwargs: object) -> dict[str, object]:
            raise RuntimeError("after-consumption sentinel")

        monkeypatch.setattr(auth, "_exchange_code", fail_after_consumption)

        with TestClient(application, raise_server_exceptions=False) as client:
            configured_key = app_settings.oidc_auth_wrapping_key
            assert configured_key is not None
            wrapping_key = configured_key.get_secret_value().encode("utf-8")
            client.cookies.set(
                BROWSER_ABUSE_COOKIE,
                make_browser_abuse_cookie("after-browser", secret=wrapping_key),
            )
            client.cookies.set(OIDC_TRANSACTION_COOKIE, str(transaction_id))

            response = client.get(
                "/v1/auth/oidc/callback",
                params={"state": "after-state", "code": "after-code"},
            )

            assert response.status_code == 500
            assert OIDC_TRANSACTION_COOKIE in response.headers.get("set-cookie", "")
            assert "Max-Age=0" in response.headers.get("set-cookie", "")

        assert await auth.reserve_login("after-browser", UUID(int=706))

        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            transaction = await unit_of_work.identity.get_login_transaction(
                transaction_id
            )

        assert transaction is not None
        assert transaction.is_consumed


async def test_pat_create_shows_secret_once_and_revoke_is_audited(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "pat.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        user, workspace, _ = await seed(database.sessions)
        issued = await _auth_service(app_settings, database).issue_session(user.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(issued)
            tokens = api.workspace(workspace.id)
            created = tokens.create_token_ok(
                PersonalAccessTokenCreateRequest(
                    label="read-only",
                    scopes=(PersonalAccessTokenScope.VIEW_GRAPH,),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
                headers=_csrf_headers(issued),
            )
            listed = tokens.list_tokens(headers=_csrf_headers(issued))
            # A scope outside the PAT allow-list cannot be expressed by the
            # typed request model; exercise that boundary through the raw client.
            disallowed = client.post(
                f"/v1/workspaces/{workspace.id}/personal-access-tokens",
                headers=_csrf_headers(issued),
                json={
                    "label": "admin",
                    "scopes": [WorkspaceCapability.MANAGE_MEMBERS.value],
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
            )
            revoked = tokens.revoke_token(created.id, headers=_csrf_headers(issued))
            raw_token = created.token.get_secret_value()
            client.cookies.clear()
            rejected_revoked_token = client.get(
                f"/v1/workspaces/{workspace.id}/nodes",
                headers={"Authorization": f"Bearer {raw_token}"},
            )

            assert raw_token not in repr(created)
            assert raw_token not in str(dict(created))
            assert raw_token not in str(created.model_dump())
            assert raw_token not in created.model_dump_json()
            assert (
                raw_token
                not in TypeAdapter(PersonalAccessTokenCreatedResponse)
                .dump_json(created)
                .decode()
            )

            class NestedToken(BaseModel):
                token: SecretStr

            assert raw_token not in NestedToken(token=created.token).model_dump_json()
            redacted_with_caller_exclude = created.model_dump_json(exclude={"label"})
            assert raw_token not in redacted_with_caller_exclude
            assert '"label"' not in redacted_with_caller_exclude
            assert listed.status_code == 200
            assert raw_token not in listed.text
            assert disallowed.status_code == 422
            assert revoked.status_code == 204
            assert rejected_revoked_token.status_code == 401
            assert rejected_revoked_token.headers["www-authenticate"] == "Bearer"
            assert raw_token not in rejected_revoked_token.text

        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            events = await unit_of_work.security_audit.list_for_workspace(
                workspace.id,
                limit=100,
            )

        operations = [event.operation for event in events]
        assert "credential.pat.create" in operations
        assert "credential.pat.revoke" in operations


async def test_workspace_route_accepts_personal_access_token_without_browser_cookie(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "workspace-pat-http.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        user, workspace, _ = await seed(database.sessions)
        issued = await _auth_service(app_settings, database).issue_session(user.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(issued)
            created = api.workspace(workspace.id).create_token_ok(
                PersonalAccessTokenCreateRequest(
                    label="catalog e2e",
                    scopes=(PersonalAccessTokenScope.VIEW_GRAPH,),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
                headers=_csrf_headers(issued),
            )
            raw_token = created.token.get_secret_value()
            client.cookies.clear()

            response = client.get(
                f"/v1/workspaces/{workspace.id}/nodes",
                headers={"Authorization": f"Bearer {raw_token}"},
            )

            assert response.status_code == 200, response.text


async def test_owner_can_issue_manage_secrets_personal_access_token(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "manage-secrets-pat.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        user, workspace, _ = await seed(database.sessions)
        seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
        editor = await seeder.user(
            email="editor@example.test",
            display_name="Editor",
        )
        await seeder.membership(
            user=editor,
            workspace=workspace,
            role=WorkspaceRole.EDITOR,
        )
        issued = await _auth_service(app_settings, database).issue_session(user.id)
        editor_issued = await _auth_service(app_settings, database).issue_session(
            editor.id
        )

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(issued)
            created = api.workspace(workspace.id).create_token_ok(
                PersonalAccessTokenCreateRequest(
                    label="e2e secrets",
                    scopes=(PersonalAccessTokenScope.MANAGE_SECRETS,),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
                headers=_csrf_headers(issued),
            )

            assert created.scopes == (WorkspaceCapability.MANAGE_SECRETS,)

            api.authenticate(editor_issued)
            denied = api.workspace(workspace.id).create_token(
                PersonalAccessTokenCreateRequest(
                    label="not an owner",
                    scopes=(PersonalAccessTokenScope.MANAGE_SECRETS,),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
                headers=_csrf_headers(editor_issued),
            )

            assert denied.status_code == 403


async def test_workspace_pat_scope_limits_writes_and_bearer_write_skips_csrf(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "workspace-pat-scope.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "workspace": tmp_path / "workbench",
            }
        )
        user, workspace, _ = await seed(database.sessions)
        issued = await _auth_service(app_settings, database).issue_session(user.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(issued)
            workspace_api = api.workspace(workspace.id)
            read_only = workspace_api.create_token_ok(
                PersonalAccessTokenCreateRequest(
                    label="read only",
                    scopes=(PersonalAccessTokenScope.VIEW_GRAPH,),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
                headers=_csrf_headers(issued),
            )
            editor = workspace_api.create_token_ok(
                PersonalAccessTokenCreateRequest(
                    label="upload e2e",
                    scopes=(PersonalAccessTokenScope.EDIT_GRAPH,),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
                headers=_csrf_headers(issued),
            )
            read_only_token = read_only.token.get_secret_value()
            editor_token = editor.token.get_secret_value()
            client.cookies.clear()

            denied = workspace_api.uploads.upload(
                "sample.png",
                b"\x89PNG\r\n\x1a\n",
                content_type="image/png",
                headers={"Authorization": f"Bearer {read_only_token}"},
            )
            uploaded = workspace_api.uploads.upload(
                "sample.png",
                b"\x89PNG\r\n\x1a\n",
                content_type="image/png",
                headers={"Authorization": f"Bearer {editor_token}"},
            )

            assert denied.status_code == 403
            assert uploaded.status_code == 200, uploaded.text


async def test_workspace_route_rejects_ambiguous_and_cross_workspace_pat_use(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "workspace-pat-boundary.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        user, workspace, _ = await seed(database.sessions)
        issued = await _auth_service(app_settings, database).issue_session(user.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(issued)
            created = api.workspace(workspace.id).create_token_ok(
                PersonalAccessTokenCreateRequest(
                    label="workspace bound",
                    scopes=(PersonalAccessTokenScope.VIEW_GRAPH,),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
                headers=_csrf_headers(issued),
            )
            raw_token = created.token.get_secret_value()
            authorization = {"Authorization": f"Bearer {raw_token}"}

            ambiguous = api.workspace(workspace.id).catalog.list_nodes(
                headers=authorization
            )
            client.cookies.clear()
            wrong_workspace = api.workspace(UUID(int=999)).catalog.list_nodes(
                headers=authorization
            )
            browser_only = api.workspace(workspace.id).list_tokens(
                headers=authorization
            )

            assert ambiguous.status_code == 401
            assert wrong_workspace.status_code == 404
            assert browser_only.status_code == 401


async def test_workspace_pat_capability_failure_audit_uses_token_actor(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "workspace-pat-audit.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        user, workspace, _ = await seed(database.sessions)
        issued = await _auth_service(app_settings, database).issue_session(user.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(issued)
            created = api.workspace(workspace.id).create_token_ok(
                PersonalAccessTokenCreateRequest(
                    label="audit scope",
                    scopes=(PersonalAccessTokenScope.VIEW_GRAPH,),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
                headers=_csrf_headers(issued),
            )
            raw_token = created.token.get_secret_value()
            client.cookies.clear()

            denied = client.post(
                f"/v1/workspaces/{workspace.id}/graph-folders",
                headers={"Authorization": f"Bearer {raw_token}"},
                json={"name": "Denied"},
            )

            assert denied.status_code == 403

        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            events = await unit_of_work.security_audit.list_for_workspace(
                workspace.id,
                limit=100,
            )

        failure = next(
            event
            for event in events
            if event.operation == "graph.folder.create"
            and event.outcome is SecurityAuditOutcome.FAILURE
        )
        assert failure.actor_kind is SecurityAuditActorKind.AUTHENTICATED
        assert failure.user_id == user.id
        assert failure.credential_reference == f"pat:{created.id}"
        assert raw_token not in repr(failure)


async def test_callback_validation_is_bounded_and_consumes_transaction(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "callback-validation.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "oidc_issuer": "https://issuer.example.test",
                "oidc_client_id": "grafy-client",
                "oidc_auth_wrapping_key": SecretStr("callback-test-key"),
                "auth_callback_rate_limit": 1,
            }
        )
        _, _, _ = await seed(database.sessions)
        application = app_with_overrides(settings=app_settings)
        # The OIDC handlers and abuse-cookie middleware resolve the service
        # through application.state, and the outstanding-login slots live in
        # that instance, so callback flows must drive it directly.
        auth = application.state.identity.auth_service
        transaction_id = UUID(int=42)
        await _seed_oidc_transaction(
            database,
            auth,
            app_settings,
            transaction_id,
            state="valid-state",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await auth.reserve_login("testclient", transaction_id)
        state_sentinel = "S" * 513

        with TestClient(application) as client:
            configured_key = app_settings.oidc_auth_wrapping_key
            assert configured_key is not None
            wrapping_key = configured_key.get_secret_value().encode("utf-8")
            client.cookies.set(
                BROWSER_ABUSE_COOKIE,
                make_browser_abuse_cookie("testclient", secret=wrapping_key),
            )
            client.cookies.set(OIDC_TRANSACTION_COOKIE, str(transaction_id))
            first = client.get(
                "/v1/auth/oidc/callback",
                params={"state": state_sentinel},
            )
            second = client.get(
                "/v1/auth/oidc/callback",
                params={"state": state_sentinel},
            )

            assert first.status_code == 422
            assert state_sentinel not in first.text
            assert OIDC_TRANSACTION_COOKIE in first.headers.get("set-cookie", "")
            assert "Path=/api/v1/auth/oidc" in first.headers.get("set-cookie", "")
            assert second.status_code == 429
            assert "Too many callback attempts" in second.text
            assert second.json()["code"] == "http.capacity_exceeded"

        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            stored = await unit_of_work.identity.lock_login_transaction(transaction_id)
        assert stored is not None
        assert stored.is_consumed

        async with database.sessions() as session:
            callback_events = list(
                await session.scalars(
                    select(SecurityAuditEvent).where(
                        schema.security_audit_events.c.operation
                        == "oidc.login.callback"
                    )
                )
            )

        assert {(e.operation, e.error_code) for e in callback_events} == {
            ("oidc.login.callback", "rate_limited"),
            ("oidc.login.callback", "validation_failed"),
        }
        assert await auth.reserve_login("testclient", UUID(int=43))


async def test_login_validation_is_bounded_and_audited(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "login-validation.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "auth_login_start_rate_limit": 1,
            }
        )
        _, _, _ = await seed(database.sessions)
        sentinel = "R" * 2049

        with client_with_overrides(settings=app_settings) as client:
            first = client.get("/v1/auth/oidc/login", params={"return_path": sentinel})
            client.cookies.clear()
            second = client.get("/v1/auth/oidc/login", params={"return_path": sentinel})

            assert first.status_code == 422
            assert second.status_code == 429
            assert second.json()["code"] == "http.capacity_exceeded"
            assert sentinel not in first.text
            assert sentinel not in second.text

        async with database.sessions() as session:
            events = list(
                await session.scalars(
                    select(SecurityAuditEvent).where(
                        schema.security_audit_events.c.operation == "oidc.login.start"
                    )
                )
            )

        assert {e.error_code for e in events} == {
            "validation_failed",
            "rate_limited",
        }


async def test_oidc_query_sentinels_are_absent_from_request_logs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_url = create_db_url(tmp_path, "oidc-query-logs.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        _, _, _ = await seed(database.sessions)
        return_path = "/after?one-time=return-path-sentinel"
        code = "oidc-code-sentinel"
        state = "oidc-state-sentinel"
        provider_error = "provider-error-sentinel"
        caplog.set_level(logging.INFO)

        application = app_with_overrides(settings=app_settings)
        # The login start reaches the provider discovery fetch. Without this
        # stub it performs real socket I/O against GRAFY_OIDC_ISSUER from
        # .env in the pytest process, which on macOS + CPython 3.14 poisons
        # fork() and segfaults later docker subprocess spawns (e.g. the
        # plugin egress test) for the remainder of the suite.
        auth = application.state.identity.auth_service

        async def unavailable_provider(**_kwargs: object) -> dict[str, object]:
            raise OidcProtocolError("provider_discovery_unavailable")

        monkeypatch.setattr(auth, "_provider", unavailable_provider)

        with TestClient(application) as client:
            client.get("/v1/auth/oidc/login", params={"return_path": return_path})
            client.get(
                "/v1/auth/oidc/callback",
                params={"code": code, "state": state, "error": provider_error},
            )

        assert all(
            sentinel not in caplog.text
            for sentinel in (
                return_path,
                "return-path-sentinel",
                "%2Fafter%3Fone-time%3Dreturn-path-sentinel",
                code,
                state,
                provider_error,
            )
        )


async def test_auth_http_exception_is_audited_as_authenticated_failure(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "auth-http-error.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        user, _, _ = await seed(database.sessions)
        issued = await _auth_service(app_settings, database).issue_session(user.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(issued)
            # A malformed session id cannot be expressed by the typed
            # facade method; exercise that boundary through the raw client.
            response = client.delete(
                "/v1/auth/sessions/not-a-uuid",
                headers=_csrf_headers(issued),
            )

            assert response.status_code == 404

        async with database.sessions() as session:
            events = list(
                await session.scalars(
                    select(SecurityAuditEvent).where(
                        schema.security_audit_events.c.operation
                        == "auth.session.request"
                    )
                )
            )

        assert [(e.actor_kind, e.operation, e.error_code) for e in events] == [
            (
                SecurityAuditActorKind.AUTHENTICATED,
                "auth.session.request",
                "not_found",
            )
        ]


async def test_workspace_and_pat_request_validation_is_bounded(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "dto-validation.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        user, workspace, _ = await seed(database.sessions)
        issued = await _auth_service(app_settings, database).issue_session(user.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(issued)
            # Rejected payloads cannot be expressed by the typed request
            # models; exercise those boundaries through the raw client.
            whitespace = client.post(
                "/v1/workspaces",
                headers=_csrf_headers(issued),
                json={"slug": "   ", "name": "Team"},
            )
            invalid_slug = client.post(
                "/v1/workspaces",
                headers=_csrf_headers(issued),
                json={"slug": "bad slug!", "name": "Team"},
            )
            normalized = api.workspaces.create(
                WorkspaceCreateRequest(slug="  Team-Name  ", name="Team"),
                headers=_csrf_headers(issued),
            )
            duplicate_normalized = api.workspaces.create(
                WorkspaceCreateRequest(slug=" team-name ", name="Duplicate team"),
                headers=_csrf_headers(issued),
            )
            duplicate_scopes = client.post(
                f"/v1/workspaces/{workspace.id}/personal-access-tokens",
                headers=_csrf_headers(issued),
                json={
                    "label": "duplicate",
                    "scopes": ["view_graph", "view_graph"],
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
            )
            blank_label = client.post(
                f"/v1/workspaces/{workspace.id}/personal-access-tokens",
                headers=_csrf_headers(issued),
                json={
                    "label": "   ",
                    "scopes": ["view_graph"],
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
            )

            assert whitespace.status_code == 422
            assert invalid_slug.status_code == 422
            assert normalized.status_code == 201
            assert normalized.json()["slug"] == "team-name"
            assert duplicate_normalized.status_code == 409
            assert duplicate_scopes.status_code == 422
            assert blank_label.status_code == 422


async def test_workspace_failure_audits_preserve_route_metadata(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "workspace-failure-metadata.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(database_url)}
        )
        owner, workspace, _ = await seed(database.sessions)
        seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
        viewer = await seeder.user(email="viewer@example.test", display_name="Viewer")
        await seeder.membership(
            user=viewer, workspace=workspace, role=WorkspaceRole.VIEWER
        )
        viewer_issued = await _auth_service(app_settings, database).issue_session(
            viewer.id
        )
        missing_workspace_id = UUID(int=999)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(viewer_issued)
            capability = api.workspace(workspace.id).create_invitation(
                WorkspaceInvitationCreateRequest(
                    email=owner.email or "owner@example.test",
                    role=WorkspaceRole.VIEWER,
                ),
                headers=_csrf_headers(viewer_issued),
            )
            not_found = api.workspace(missing_workspace_id).list_members()
            # A whitespace-only name is rejected server-side and cannot be
            # expressed by the typed request model; use the raw client.
            validation = client.post(
                "/v1/workspaces",
                headers=_csrf_headers(viewer_issued),
                json={"slug": "valid", "name": "   "},
            )

            assert capability.status_code == 403
            assert not_found.status_code == 404
            assert validation.status_code == 422

        async with database.sessions() as session:
            failures = list(
                await session.scalars(
                    select(SecurityAuditEvent)
                    .where(
                        schema.security_audit_events.c.outcome
                        == SecurityAuditOutcome.FAILURE,
                        schema.security_audit_events.c.operation.like("workspace.%"),
                    )
                    .order_by(schema.security_audit_events.c.occurred_at)
                )
            )

        assert [
            (
                e.actor_kind,
                e.operation,
                e.workspace_id,
                e.resource_type,
                e.resource_id,
                e.error_code,
            )
            for e in failures
        ] == [
            (
                SecurityAuditActorKind.AUTHENTICATED,
                "workspace.invitation.create",
                workspace.id,
                "workspace_invitation",
                None,
                "capability_denied",
            ),
            (
                SecurityAuditActorKind.AUTHENTICATED,
                "workspace.membership.list",
                missing_workspace_id,
                "workspace_membership",
                None,
                "not_found",
            ),
            (
                SecurityAuditActorKind.AUTHENTICATED,
                "workspace.create",
                None,
                "workspace",
                None,
                "validation_failed",
            ),
        ]

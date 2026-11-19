import asyncio
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from uuid import UUID

import pytest

from grafy_api.auth.secrets import digest_secret
from grafy_api.auth.sessions import parse_personal_access_token
from grafy_core.application.identity import IdentityService
from grafy_core.domain.identity import ActorContext, WorkspaceCapability
from grafy_persistence.database import create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_shared.config import AppConfig, AuthConfig
from scripts import dev_pat


ISSUER = "http://keycloak.localhost:8081/realms/grafy"
OWNER_SUBJECT = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.chdir(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    database_url = f"sqlite+aiosqlite:///{workspace / 'grafy.sqlite3'}"
    for name, value in {
        "ENVIRONMENT": "development",
        "PUBLIC_ORIGIN": "http://localhost:3000",
        "WORKSPACE": str(workspace),
        "DATABASE_URL": database_url,
        "OIDC_ISSUER": ISSUER,
        "OIDC_CLIENT_ID": "grafy-web",
        "OIDC_AUTH_WRAPPING_KEY": "test-wrapping-key",
        "PERSONAL_ACCESS_TOKEN_MAX_LIFETIME_SECONDS": "2592000",
    }.items():
        monkeypatch.setenv(f"GRAFY_{name}", value)
    return database_url


@pytest.mark.parametrize(
    ("variable", "value", "error"),
    [
        ("ENVIRONMENT", "production", "GRAFY_ENVIRONMENT must be development"),
        ("PUBLIC_ORIGIN", "https://grafy.example", "must be a loopback HTTP origin"),
        (
            "OIDC_ISSUER",
            "http://keycloak.localhost.evil/realms/grafy",
            "local HTTP Keycloak",
        ),
        (
            "OIDC_ISSUER",
            "http://localhost:8081/realms/production",
            "local HTTP Keycloak",
        ),
        (
            "DATABASE_URL",
            "postgresql+asyncpg://user:do-not-print@localhost/db",
            "local SQLite",
        ),
        ("DATABASE_URL", "sqlite+aiosqlite://remote/grafy.sqlite3", "local SQLite"),
        ("DATABASE_URL", "sqlite+aiosqlite:///file:db?uri=true", "local SQLite"),
        ("DATABASE_URL", "sqlite+aiosqlite:///:memory:", "local SQLite"),
        (
            "DATABASE_URL",
            "sqlite+aiosqlite:///outside.sqlite3",
            "inside GRAFY_WORKSPACE",
        ),
        ("DATABASE_URL", "not-a-url-do-not-print", "local SQLite"),
        (
            "DATABASE_URL",
            "postgresql+asyncpg://user@localhost:do-not-print/db",
            "local SQLite",
        ),
        (
            "PUBLIC_ORIGIN",
            "not-an-origin-do-not-print",
            "Could not read local Grafy configuration",
        ),
    ],
)
def test_refuses_unsafe_config(
    database_url: str,
    variable: str,
    value: str,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(f"GRAFY_{variable}", value)
    assert dev_pat.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert error in captured.err
    assert "do-not-print" not in captured.err
    assert not Path(database_url.removeprefix("sqlite+aiosqlite:///")).exists()


def test_refuses_symlink_outside_workspace(database_url: str, tmp_path: Path) -> None:
    outside = tmp_path / "outside.sqlite3"
    outside.touch()
    database = Path(database_url.removeprefix("sqlite+aiosqlite:///"))
    database.symlink_to(outside)
    with pytest.raises(dev_pat.DevPatError, match="inside GRAFY_WORKSPACE"):
        dev_pat.dev_target(AppConfig(), AuthConfig())


def test_missing_db_is_not_created(
    database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert dev_pat.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "database is missing" in captured.err
    assert not Path(database_url.removeprefix("sqlite+aiosqlite:///")).exists()


async def seed_owner(
    database_url: str, *, subject: str = OWNER_SUBJECT
) -> tuple[UUID, UUID]:
    database = create_database(database_url)
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        enrolled = await IdentityService(
            lambda: SqlAlchemyUnitOfWork(database.sessions)
        ).provision_oidc_identity(
            issuer=ISSUER,
            subject=subject,
            email="owner@grafy.local",
            display_name="Grafy Owner",
            email_verified=True,
        )
        return enrolled.user.id, enrolled.personal_workspace.id
    finally:
        await database.dispose()


def test_matches_owner_by_subject(
    database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    asyncio.run(seed_owner(database_url, subject="different-subject"))
    assert dev_pat.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Sign in as owner" in captured.err


@pytest.mark.parametrize("days", ["0", "-1", "31"])
def test_refuses_invalid_lifetime(
    database_url: str, days: str, capsys: pytest.CaptureFixture[str]
) -> None:
    Path(database_url.removeprefix("sqlite+aiosqlite:///")).touch()
    assert dev_pat.main(["--expires-days", days]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "within the configured PAT lifetime" in captured.err


def test_mints_authenticatable_workspace_pat(
    database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    user_id, workspace_id = asyncio.run(seed_owner(database_url))
    before = datetime.now(UTC)
    assert (
        dev_pat.main(
            [
                "--json",
                "--name",
                "SDK smoke test",
                "--expires-days",
                "2",
                "--scope",
                "view_project",
                "--scope",
                "view_runs",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    payload: dict[str, str] = json.loads(captured.out)
    assert payload == {"workspace_id": str(workspace_id), "token": payload["token"]}
    prefix, secret = parse_personal_access_token(payload["token"])

    async def verify() -> None:
        database = create_database(database_url)

        def uow_factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(database.sessions)

        try:
            identity = IdentityService(uow_factory)
            principal = await identity.authenticate_personal_access_token(
                public_prefix=prefix, secret_digest=digest_secret(secret)
            )
            assert principal.workspace_id == workspace_id
            assert principal.actor.user_id == user_id
            assert principal.capabilities == {
                WorkspaceCapability.VIEW_PROJECT,
                WorkspaceCapability.VIEW_RUNS,
            }
            async with uow_factory() as uow:
                stored = await uow.identity.get_personal_access_token_by_prefix(prefix)
                assert stored is not None
                assert stored.label == "SDK smoke test"
                assert stored.secret_digest == digest_secret(secret)
                assert before + timedelta(days=2) <= stored.expires_at
                assert stored.expires_at <= datetime.now(UTC) + timedelta(days=2)
                audit = await uow.security_audit.list_for_workspace(
                    workspace_id, limit=1
                )
                assert audit[0].operation == "credential.pat.create"
                assert audit[0].credential_reference == "dev-pat"
            await identity.revoke_personal_access_token(
                actor=ActorContext(user_id=user_id),
                workspace_id=workspace_id,
                token_id=principal.token_id,
            )
            async with uow_factory() as uow:
                revoked = await uow.identity.get_personal_access_token_by_prefix(prefix)
                assert revoked is not None and revoked.is_revoked
        finally:
            await database.dispose()

    asyncio.run(verify())


def test_plain_output_contains_only_a_new_token(
    database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    asyncio.run(seed_owner(database_url))
    tokens: set[str] = set()
    for _ in range(2):
        assert dev_pat.main([]) == 0
        captured = capsys.readouterr()
        assert captured.err == ""
        (token,) = captured.out.splitlines()
        assert token == token.strip()
        assert token not in tokens
        parse_personal_access_token(token)
        tokens.add(token)

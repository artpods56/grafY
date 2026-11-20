"""Mint a personal Workspace PAT for the imported local Keycloak owner."""

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from pydantic import ValidationError
from pydantic_settings import SettingsError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from grafy_api.auth.sessions import issue_personal_access_token
from grafy_core.application.identity import IdentityService
from grafy_core.domain.errors import GrafyCoreError
from grafy_core.domain.identity import (
    PAT_ALLOWED_CAPABILITIES,
    ActorContext,
    WorkspaceCapability,
)
from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_shared.config import AppConfig, AuthConfig


# The fixed OIDC subject in infra/keycloak/realm-import/grafy-realm.json.
DEV_OWNER_SUBJECT = "11111111-1111-4111-8111-111111111111"
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class DevPatError(RuntimeError):
    pass


@dataclass(frozen=True)
class DevTarget:
    database_url: str
    issuer: str


def local_endpoint(value: str, *, hosts: set[str], path: str) -> bool:
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        return False
    return (
        url.scheme == "http"
        and url.hostname in hosts
        and url.username is None
        and (port is None or port > 0)
        and url.path.rstrip("/") == path
        and not url.query
        and not url.fragment
    )


def dev_target(app: AppConfig, auth: AuthConfig) -> DevTarget:
    if app.environment != "development":
        raise DevPatError("GRAFY_ENVIRONMENT must be development")
    if not local_endpoint(app.public_origin, hosts=LOOPBACK_HOSTS, path=""):
        raise DevPatError("GRAFY_PUBLIC_ORIGIN must be a loopback HTTP origin")
    issuer = auth.oidc_issuer
    if issuer is None or not local_endpoint(
        issuer, hosts=LOOPBACK_HOSTS | {"keycloak.localhost"}, path="/realms/grafy"
    ):
        raise DevPatError(
            "GRAFY_OIDC_ISSUER must use the local HTTP Keycloak grafy realm"
        )

    try:
        url = make_url(app.resolved_database_url)
    except (ArgumentError, ValueError):
        raise DevPatError("GRAFY_DATABASE_URL must be a local SQLite file") from None

    database = url.database
    if (
        url.drivername != "sqlite+aiosqlite"
        or url.host is not None
        or url.username is not None
        or url.password is not None
        or url.port is not None
        or url.query
        or not database
        or database.startswith(("file:", "//", "\\"))
        or database == ":memory:"
    ):
        raise DevPatError("GRAFY_DATABASE_URL must be a local SQLite file")
    path = Path(database).resolve()
    if "?" in str(path):
        raise DevPatError("GRAFY_DATABASE_URL must be a plain SQLite file path")
    if not path.is_relative_to(app.workspace.resolve()):
        raise DevPatError("The SQLite file must be inside GRAFY_WORKSPACE")
    if not path.is_file():
        raise DevPatError(
            "Local SQLite database is missing. Start Grafy and sign in as owner."
        )
    return DevTarget(database_url=f"sqlite+aiosqlite:///{path}", issuer=issuer)


async def mint(
    target: DevTarget,
    *,
    name: str,
    scopes: tuple[WorkspaceCapability, ...],
    expires_at: datetime,
) -> tuple[str, str]:
    database = create_database(target.database_url)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(database.sessions, cleanups=database.cleanups)

    try:
        async with uow_factory() as uow:
            owner = await uow.identity.get_oidc_identity(
                issuer=target.issuer, subject=DEV_OWNER_SUBJECT
            )
            if owner is None:
                raise DevPatError(
                    "Local owner is missing. Sign in as owner in Grafy first."
                )
            workspace = await uow.identity.get_personal_workspace(owner.user_id)
            if workspace is None:
                raise DevPatError(
                    "Local owner has no personal Workspace. Sign in as owner first."
                )

        token, raw_token = issue_personal_access_token(
            user_id=owner.user_id,
            workspace_id=workspace.id,
            label=name,
            scopes=scopes,
            expires_at=expires_at,
        )
        await IdentityService(uow_factory).create_personal_access_token(
            actor=ActorContext(user_id=owner.user_id, credential_reference="dev-pat"),
            token=token,
        )
        return raw_token, str(workspace.id)
    finally:
        await database.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="Include Workspace ID in JSON"
    )
    parser.add_argument("--name", default="Local development", help="Label in Grafy")
    parser.add_argument(
        "--expires-days", type=int, default=1, help="Lifetime in days (default: 1)"
    )
    parser.add_argument(
        "--scope",
        action="append",
        type=WorkspaceCapability,
        choices=sorted(PAT_ALLOWED_CAPABILITIES),
        help="Repeat to grant multiple capabilities (default: view_project)",
    )
    args = parser.parse_args(argv)
    name: str = args.name.strip()
    days: int = args.expires_days
    scopes: tuple[WorkspaceCapability, ...] = tuple(
        dict.fromkeys(args.scope or [WorkspaceCapability.VIEW_PROJECT])
    )

    try:
        app = AppConfig()
        auth = AuthConfig()
        target = dev_target(app, auth)
        if not 1 <= len(name) <= 160:
            raise DevPatError("--name must contain 1 to 160 characters")
        now = datetime.now(UTC)
        max_days = min(
            auth.personal_access_token_max_lifetime_seconds // 86400,
            (datetime.max.replace(tzinfo=UTC) - now).days,
        )
        if not 0 < days <= max_days:
            raise DevPatError(
                "--expires-days must be positive and within the configured PAT lifetime"
            )
        expires_at = now + timedelta(days=days)
        token, workspace_id = asyncio.run(
            mint(target, name=name, scopes=scopes, expires_at=expires_at)
        )
    except DevPatError as exc:
        print(f"dev-pat: {exc}", file=sys.stderr)
        return 1
    except (ValidationError, SettingsError, OSError):
        print("dev-pat: Could not read local Grafy configuration", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print(
            "dev-pat: Could not use the local database. Check that migrations are current.",
            file=sys.stderr,
        )
        return 1
    except GrafyCoreError:
        print(
            "dev-pat: Owner is inactive or cannot grant the requested scopes",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps({"token": token, "workspace_id": workspace_id})
        if args.json
        else token
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

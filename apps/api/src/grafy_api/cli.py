"""Grafy operator CLI."""

import argparse
import asyncio
from datetime import UTC, datetime
import getpass
import hashlib
from secrets import token_urlsafe
import sys
from uuid import UUID

from grafy_core.application.identity import IdentityService
from grafy_core.domain.errors import IdentityInvariantError
from grafy_core.domain.identity import (
    PlatformAccessToken,
    PlatformTokenPrincipal,
    PlatformTokenScope,
    WorkspacePatPrincipal,
)
from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from grafy_api.cli_credentials import (
    CliCredentialError,
    CredentialDigest,
    delete_sensitive_cli_token,
    load_sensitive_cli_token,
    parse_sensitive_bearer_token,
    store_sensitive_cli_token,
)
from grafy_api.settings import get_settings




def _parse_aware_timestamp(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timestamp must be ISO 8601") from exc
    if timestamp.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return timestamp


def _load_credential_digest(database_url: str) -> CredentialDigest:
    raw_token = load_sensitive_cli_token(database_url)
    return parse_sensitive_bearer_token(raw_token)


async def _authenticate_credential(
    identity: IdentityService,
    credential: CredentialDigest,
) -> WorkspacePatPrincipal | PlatformTokenPrincipal:
    if credential.kind == "personal":
        return await identity.authenticate_personal_access_token(
            public_prefix=credential.public_prefix,
            secret_digest=credential.secret_digest,
        )
    return await identity.authenticate_platform_access_token(
        public_prefix=credential.public_prefix,
        secret_digest=credential.secret_digest,
    )


async def _run_auth(args: argparse.Namespace) -> None:
    settings = get_settings()
    if args.command == "logout":
        removed = delete_sensitive_cli_token(settings.app.resolved_database_url)
        print("Removed stored Grafy credential" if removed else "No stored credential")
        return

    database = create_database(settings.app.resolved_database_url)
    try:
        identity = IdentityService(lambda: SqlAlchemyUnitOfWork(database.sessions))
        if args.command == "login":
            raw_token = getpass.getpass("Grafy token: ")
            credential = parse_sensitive_bearer_token(raw_token)
            principal = await _authenticate_credential(identity, credential)
            store_sensitive_cli_token(settings.app.resolved_database_url, raw_token)
        elif args.command == "status":
            credential = _load_credential_digest(settings.app.resolved_database_url)
            principal = await _authenticate_credential(identity, credential)
        else:
            raise ValueError("Unsupported Grafy auth command")
        if isinstance(principal, WorkspacePatPrincipal):
            print(
                f"Authenticated user {principal.actor.user_id} for Workspace "
                f"{principal.workspace_id} via {principal.actor.credential_reference}"
            )
        else:
            print(
                f"Authenticated platform principal {principal.principal_reference!r} "
                f"via {principal.credential_reference}"
            )
    finally:
        await database.dispose()


async def _run_admin(args: argparse.Namespace) -> None:
    settings = get_settings()
    database = create_database(settings.app.resolved_database_url)
    try:
        identity = IdentityService(lambda: SqlAlchemyUnitOfWork(database.sessions))
        if args.admin_command == "disable-user":
            await identity.disable_user(user_id=UUID(args.user_id))
            print(f"Disabled user {args.user_id}")
            return
        if (
            args.admin_command == "platform-token"
            and args.platform_token_command == "create"
        ):
            secret = token_urlsafe(32)
            public_prefix = f"gpat_{secret[:12]}"
            scopes = tuple(PlatformTokenScope(scope) for scope in args.scope)
            if len(scopes) != len(set(scopes)):
                raise SystemExit("Platform token scopes must not be repeated")
            if args.expires_at <= datetime.now(UTC):
                raise SystemExit("Platform token expiry must be in the future")
            token = PlatformAccessToken(
                principal_reference=args.principal,
                public_prefix=public_prefix,
                secret_digest=hashlib.sha256(secret.encode("utf-8")).digest(),
                label=args.label,
                scopes=scopes,
                expires_at=args.expires_at,
            )
            await identity.create_platform_access_token(token=token)
            print(f"{public_prefix}.{secret}")
            print("Store this token now; it will not be shown again.", file=sys.stderr)
            return
        if (
            args.admin_command == "platform-token"
            and args.platform_token_command == "list"
        ):
            for token in await identity.list_platform_access_tokens():
                status = "revoked" if token.is_revoked else "active"
                scopes = ",".join(scope.value for scope in token.scopes)
                print(
                    f"{token.id} {token.public_prefix} {status} "
                    f"principal={token.principal_reference!r} label={token.label!r} "
                    f"scopes={scopes} expires={token.expires_at.isoformat()}"
                )
            return
        if (
            args.admin_command == "platform-token"
            and args.platform_token_command == "revoke"
        ):
            token = await identity.revoke_platform_access_token(
                token_id=UUID(args.token_id)
            )
            print(f"Revoked platform token {token.id}")
            return
        raise ValueError("Unsupported Grafy admin command")
    finally:
        await database.dispose()


async def _run(args: argparse.Namespace) -> None:
    if args.group == "auth":
        await _run_auth(args)
        return
    if args.group == "admin":
        await _run_admin(args)
        return
    raise ValueError("Unsupported Grafy command")


def main() -> None:
    parser = argparse.ArgumentParser(prog="grafy")
    groups = parser.add_subparsers(dest="group", required=True)

    auth = groups.add_parser("auth")
    auth_commands = auth.add_subparsers(dest="command", required=True)
    auth_commands.add_parser(
        "login", help="verify and store a token in the OS keychain"
    )
    auth_commands.add_parser("status", help="verify the active CLI credential")
    auth_commands.add_parser("logout", help="remove the token from the OS keychain")

    admin = groups.add_parser("admin")
    admin_commands = admin.add_subparsers(dest="admin_command", required=True)
    disable_user = admin_commands.add_parser("disable-user")
    disable_user.add_argument("user_id")
    platform_token = admin_commands.add_parser("platform-token")
    platform_token_commands = platform_token.add_subparsers(
        dest="platform_token_command",
        required=True,
    )
    create_platform_token = platform_token_commands.add_parser("create")
    create_platform_token.add_argument(
        "--principal",
        required=True,
        help="stable non-secret actor reference recorded for global operations",
    )
    create_platform_token.add_argument(
        "--label",
        required=True,
        help="operator-facing purpose for token inventory and rotation",
    )
    create_platform_token.add_argument(
        "--scope",
        required=True,
        action="append",
        choices=tuple(scope.value for scope in PlatformTokenScope),
        help="one allowed global operation; repeat to grant multiple operations",
    )
    create_platform_token.add_argument(
        "--expires-at",
        required=True,
        type=_parse_aware_timestamp,
        help="absolute ISO 8601 expiry with a UTC offset",
    )
    platform_token_commands.add_parser("list")
    revoke_platform_token = platform_token_commands.add_parser("revoke")
    revoke_platform_token.add_argument("token_id")

    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except (CliCredentialError, IdentityInvariantError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

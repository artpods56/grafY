"""Grafy operator CLI."""

import argparse
import asyncio
import getpass
from uuid import UUID

from grafy_core.application.identity import IdentityService
from grafy_core.domain.errors import IdentityInvariantError
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


def _load_credential_digest(database_url: str) -> CredentialDigest:
    raw_token = load_sensitive_cli_token(database_url)
    return parse_sensitive_bearer_token(raw_token)


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
            principal = await identity.authenticate_personal_access_token(
                public_prefix=credential.public_prefix,
                secret_digest=credential.secret_digest,
            )
            store_sensitive_cli_token(settings.app.resolved_database_url, raw_token)
        elif args.command == "status":
            credential = _load_credential_digest(settings.app.resolved_database_url)
            principal = await identity.authenticate_personal_access_token(
                public_prefix=credential.public_prefix,
                secret_digest=credential.secret_digest,
            )
        else:
            raise ValueError("Unsupported Grafy auth command")
        print(
            f"Authenticated user {principal.actor.user_id} for Workspace "
            f"{principal.workspace_id} via {principal.actor.credential_reference}"
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

    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except (CliCredentialError, IdentityInvariantError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

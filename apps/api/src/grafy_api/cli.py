"""Grafy operator CLI."""

import argparse
import asyncio
from datetime import UTC, datetime
import getpass
import hashlib
from pathlib import Path
from secrets import token_urlsafe
import sys
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from grafy_core.application.identity import IdentityService
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.errors import IdentityInvariantError
from grafy_core.domain.identity import (
    PlatformAccessToken,
    PlatformTokenPrincipal,
    PlatformTokenScope,
    WorkspacePatPrincipal,
)
from grafy_core.domain.plugin_releases import PlatformPluginActor
from grafy_core.domain.plugin_revocations import (
    PluginReleaseRevocationError,
    PluginReleaseRevocationReason,
)
from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from grafy_api.plugins.runtime.admission import isolated_release_admission
from grafy_api.cli_credentials import (
    CliCredentialError,
    CredentialDigest,
    delete_sensitive_cli_token,
    load_sensitive_cli_token,
    parse_sensitive_bearer_token,
    store_sensitive_cli_token,
)
from grafy_api.plugins.publication.workflow import SystemPluginPublicationWorkflow
from grafy_api.plugins.publication.sandbox import DockerPluginDirectoryPublisher
from grafy_api.plugins.publication.source import (
    PluginDirectoryPublisher,
    PluginPublishingError,
)
from grafy_api.plugins.profiles import runtime_profile
from grafy_api.plugins.publication.oci import PluginOciImageBuilder
from grafy_api.plugins.runtime.egress import PluginEgressBrokerPolicy
from grafy_api.plugins.runtime.network_policy import (
    NetworkPolicy,
    load_network_policy_manifest,
)
from grafy_api.settings import get_settings
from grafy_api.storage import configured_file_storage
from grafy_api.system_plugin_inventory import (
    CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH,
    load_system_plugin_inventory,
)
from grafy_core.domain.system_plugin_inventory import (
    SystemPluginInventoryError,
)


class PluginCheckReport(BaseModel):
    """Read-only CLI summary of one verified Plugin working copy."""

    status: Literal["valid"] = "valid"
    slug: str
    loader_target: str
    node_count: int = Field(ge=0)
    artifact_type_count: int = Field(ge=0)
    capabilities: tuple[str, ...]
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    lock_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_profile: str


def _parse_release_reference(value: str) -> tuple[str, int]:
    slug, separator, revision_text = value.rpartition("@")
    if not separator or slug == "":
        raise argparse.ArgumentTypeError("release must use SLUG@REVISION")
    try:
        revision = int(revision_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("release revision must be an integer") from exc
    if revision < 1:
        raise argparse.ArgumentTypeError("release revision must be positive")
    return slug, revision


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


async def _run_network_policy(args: argparse.Namespace) -> None:
    """Validate the deployment network policy without mutating anything."""

    settings = get_settings()
    manifest = args.manifest or settings.egress.resolved_network_policy_manifest
    if manifest is None:
        policy = NetworkPolicy.from_config(settings.egress)
        source = "legacy GRAFY_PLUGIN_*_EGRESS_DESTINATIONS translation"
    else:
        policy = load_network_policy_manifest(manifest)
        source = str(manifest)
    print(f"network policy source: {source}")
    for profile in policy.profiles:
        print(
            "profile plane="
            f"{profile.plane.value} name={profile.name} "
            f"mode={profile.mode.value} origins={len(profile.allowed_origins)} "
            f"digest={profile.policy_digest}"
        )
    for assignment in policy.assignments:
        target = "plane-default"
        if assignment.scope is not None:
            target = f"scope={assignment.scope.value}"
            if assignment.workspace_id is not None:
                target += f" workspace={assignment.workspace_id}"
        if assignment.slug is not None:
            target += f" slug={assignment.slug}"
        if assignment.revision is not None:
            target += f" revision={assignment.revision}"
        print(
            f"assignment plane={assignment.plane.value} {target} -> "
            f"{assignment.profile}"
        )
    print("network policy OK")


async def _run(args: argparse.Namespace) -> None:
    if args.group == "auth":
        await _run_auth(args)
        return
    if args.group == "admin":
        await _run_admin(args)
        return
    if args.group == "network-policy":
        await _run_network_policy(args)
        return
    if args.group != "plugin":
        raise ValueError("Unsupported Grafy command")
    settings = get_settings()
    if args.command == "check":
        directory = Path(args.directory)
        publisher = PluginDirectoryPublisher(
            settings.plugins.resolved_plugin_roots,
            runtime_profile=settings.plugins.plugin_runtime_profile,
            wheelhouse=settings.plugins.resolved_plugin_wheelhouse,
        )
        try:
            verified = await asyncio.to_thread(publisher.verify, directory)
        except PluginPublishingError as exc:
            print(f"Plugin check failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        report = PluginCheckReport(
            slug=verified.catalog.slug,
            loader_target=verified.loader_target,
            node_count=len(verified.catalog.nodes),
            artifact_type_count=len(verified.catalog.artifact_types),
            capabilities=tuple(
                capability.value for capability in verified.capabilities.capabilities
            ),
            source_digest=verified.source_digest,
            lock_digest=verified.lock_digest,
            runtime_profile=verified.runtime_profile,
        )
        print(report.model_dump_json(indent=2))
        return
    database = create_database(settings.app.resolved_database_url)
    try:
        identity = IdentityService(lambda: SqlAlchemyUnitOfWork(database.sessions))
        storage = configured_file_storage(settings.storage, settings.app.workspace)
        releases = PluginReleaseService(
            lambda: SqlAlchemyUnitOfWork(database.sessions),
            storage,
            bucket=settings.storage.storage_bucket,
        )
        if args.command == "revoke":
            credential = _load_credential_digest(settings.app.resolved_database_url)
            if credential.kind != "platform":
                raise SystemExit("Global Plugin revocation requires a platform token")
            principal = await identity.authenticate_platform_access_token(
                public_prefix=credential.public_prefix,
                secret_digest=credential.secret_digest,
                required_scope=PlatformTokenScope.REVOKE_GLOBAL,
            )
            slug, revision = args.release
            revocation = await releases.revoke_system(
                slug=slug,
                revision=revision,
                reason=PluginReleaseRevocationReason(args.reason),
                platform_actor=PlatformPluginActor(principal.principal_reference),
            )
            print(
                f"Revoked System Plugin {revocation.slug} release "
                f"{revocation.revision} for {revocation.reason.value}"
            )
            return
        plugins = settings.plugins
        profile = runtime_profile(
            plugins.plugin_runtime_profile,
            native_base_image=plugins.plugin_runtime_native_base_image,
            native_base_image_digest=plugins.plugin_runtime_native_base_image_digest,
        )
        image_builder = PluginOciImageBuilder(
            storage,
            bucket=settings.storage.storage_bucket,
            profile=profile,
            docker_binary=settings.plugins.plugin_docker_binary,
        )
        system_inventory = load_system_plugin_inventory(
            CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH
        )
        credential = _load_credential_digest(settings.app.resolved_database_url)
        if credential.kind != "platform":
            raise SystemExit("System Plugin operations require a platform token")
        required_scope = (
            PlatformTokenScope.PUBLISH_GLOBAL
            if args.command == "publish"
            else PlatformTokenScope.PROMOTE_GLOBAL
        )
        principal = await identity.authenticate_platform_access_token(
            public_prefix=credential.public_prefix,
            secret_digest=credential.secret_digest,
            required_scope=required_scope,
        )
        system_publication = SystemPluginPublicationWorkflow(
            image_builder,
            releases,
            isolated_release_admission(
                profile=profile,
                egress_policy=PluginEgressBrokerPolicy.from_config(settings.egress),
                network_policy=NetworkPolicy.from_config(settings.egress),
            ),
            system_inventory,
        )
        platform_actor = PlatformPluginActor(principal.principal_reference)
        if args.command == "publish":
            inventory_entry = system_inventory.entry_for(args.slug)
            if settings.plugins.resolved_plugin_wheelhouse is not None:
                raise SystemExit(
                    "System sandbox publication requires dependencies to be "
                    "present in the frozen source or fetched from configured "
                    "package indexes; host wheelhouse mounts are not supported"
                )
            publisher = DockerPluginDirectoryPublisher(
                settings.plugins.resolved_plugin_roots,
                runtime_profile=settings.plugins.plugin_runtime_profile,
                image=args.sandbox_image,
                docker_binary=settings.plugins.plugin_docker_binary,
                scratch_root=(
                    settings.plugins.resolved_plugin_publisher_scratch_root
                ),
            )
            verified = await asyncio.to_thread(
                publisher.verify,
                Path(args.directory),
                expected_slug=args.slug,
                loader_target=inventory_entry.loader_target,
            )
            release = await system_publication.publish_verified(
                verified,
                platform_actor=platform_actor,
            )
            print(
                f"Published System Plugin {release.release.slug} release "
                f"{release.release.revision}; promote it explicitly to activate it"
            )
            return
        slug, revision = args.release
        selection = await system_publication.promote(
            slug=slug,
            revision=revision,
            platform_actor=platform_actor,
            expected_generation=args.if_generation,
        )
        print(
            f"Promoted System Plugin {selection.slug} release "
            f"{selection.selected_revision} at generation {selection.generation}"
        )
        return
        raise ValueError("Unsupported Grafy Plugin command")
    finally:
        await database.dispose()


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

    plugin = groups.add_parser("plugin")
    commands = plugin.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check",
        help="verify a Plugin directory without publishing it",
    )
    check.add_argument("directory")
    publish = commands.add_parser(
        "publish",
        help="verify and publish a System Plugin release without activating it",
    )
    publish.add_argument(
        "directory",
        help="Plugin project to verify and freeze",
    )
    publish.add_argument(
        "--slug",
        required=True,
        help="expected Plugin slug; must match the inspected declaration",
    )
    publish.add_argument(
        "--sandbox-image",
        required=True,
        help="publisher image used to verify the candidate in isolation",
    )

    promote = commands.add_parser(
        "promote",
        help="activate one published global Plugin release",
    )
    promote.add_argument(
        "release",
        type=_parse_release_reference,
        help="exact inactive global release as SLUG@REVISION",
    )
    promote.add_argument(
        "--if-generation",
        type=int,
        help="optional compare-and-swap guard for concurrent automation",
    )
    revoke = commands.add_parser("revoke")
    revoke.add_argument(
        "release",
        type=_parse_release_reference,
        help="exact global release as SLUG@REVISION",
    )
    revoke.add_argument(
        "--reason",
        required=True,
        choices=tuple(reason.value for reason in PluginReleaseRevocationReason),
    )
    network_policy_group = groups.add_parser("network-policy")
    network_policy_commands = network_policy_group.add_subparsers(
        dest="command",
        required=True,
    )
    validate_policy = network_policy_commands.add_parser(
        "validate",
        help="Validate the deployment network policy (non-mutating)",
    )
    validate_policy.add_argument(
        "--manifest",
        type=Path,
        help="Manifest to validate; defaults to GRAFY_NETWORK_POLICY_MANIFEST",
    )

    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except (
        CliCredentialError,
        IdentityInvariantError,
        PluginReleaseRevocationError,
        PluginPublishingError,
        SystemPluginInventoryError,
    ) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

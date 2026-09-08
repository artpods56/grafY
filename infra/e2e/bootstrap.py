#!/usr/bin/env python3
"""Prepare one disposable Grafy deployment for the live HTTP E2E test."""

import asyncio
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import os
from pathlib import Path
from secrets import token_hex, token_urlsafe
import subprocess
import sys
from uuid import UUID

from grafy_core.application.identity import IdentityService
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.identity import (
    ActorContext,
    PersonalAccessToken,
    User,
    Workspace,
    WorkspaceCapability,
    WorkspaceKind,
    WorkspaceMembership,
    WorkspaceRole,
)
from grafy_core.domain.plugin_releases import PlatformPluginActor
from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from grafy_api.plugins.runtime.admission import isolated_release_admission
from grafy_api.plugins.profiles import runtime_profile
from grafy_api.plugins.publication.oci import PluginOciImageBuilder
from grafy_api.plugins.publication.workflow import SystemPluginPublicationWorkflow
from grafy_api.plugins.publication.source import PluginDirectoryPublisher
from grafy_api.settings import get_settings
from grafy_api.storage import configured_file_storage
from grafy_api.system_plugin_inventory import (
    CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH,
    load_system_plugin_inventory,
)
from grafy_api.system_plugin_loader import (
    SystemPluginDeploymentManifest,
    write_system_plugin_deployment_manifest,
)


E2E_USER_ID = UUID("00000000-0000-4000-8000-000000000001")
E2E_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
ISOLATED_PLUGIN_SLUGS = ("external.llm",)
PAT_SCOPES = (
    WorkspaceCapability.VIEW_GRAPH,
    WorkspaceCapability.VIEW_ARTIFACTS,
    WorkspaceCapability.VIEW_EXECUTION,
    WorkspaceCapability.CREATE_GRAPH,
    WorkspaceCapability.EDIT_GRAPH,
    WorkspaceCapability.EXECUTE_GRAPH,
    WorkspaceCapability.MANAGE_SECRETS,
)


def write_sensitive_file(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            stream.write(value)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


async def seed_workspace(token_path: Path) -> None:
    settings = get_settings()
    database = create_database(settings.resolved_database_url)
    try:
        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            if await unit_of_work.identity.get_user(E2E_USER_ID) is not None:
                raise RuntimeError("E2E bootstrap requires a fresh database")
            if await unit_of_work.identity.get_workspace(E2E_WORKSPACE_ID) is not None:
                raise RuntimeError("E2E bootstrap requires a fresh database")
            await unit_of_work.identity.add_user(
                User(
                    id=E2E_USER_ID,
                    email="owner@grafy-e2e.invalid",
                    email_verified=True,
                    display_name="Grafy E2E owner",
                )
            )
            await unit_of_work.identity.add_workspace(
                Workspace(
                    id=E2E_WORKSPACE_ID,
                    slug="grafy-e2e",
                    name="Grafy E2E",
                    kind=WorkspaceKind.SHARED,
                )
            )
            await unit_of_work.identity.add_membership(
                WorkspaceMembership(
                    workspace_id=E2E_WORKSPACE_ID,
                    user_id=E2E_USER_ID,
                    role=WorkspaceRole.OWNER,
                )
            )
            await unit_of_work.commit()

        secret = token_urlsafe(32)
        public_prefix = f"nrt_{secret[:12]}"
        token = PersonalAccessToken(
            user_id=E2E_USER_ID,
            workspace_id=E2E_WORKSPACE_ID,
            public_prefix=public_prefix,
            secret_digest=sha256(secret.encode("utf-8")).digest(),
            label="live-e2e",
            scopes=PAT_SCOPES,
            expires_at=datetime.now(UTC) + timedelta(hours=2),
        )
        identity = IdentityService(lambda: SqlAlchemyUnitOfWork(database.sessions))
        await identity.create_personal_access_token(
            actor=ActorContext(
                user_id=E2E_USER_ID,
                credential_reference="e2e-bootstrap",
            ),
            token=token,
        )
        write_sensitive_file(token_path, f"{public_prefix}.{secret}")
    finally:
        await database.dispose()


async def publish_plugins(deployment_manifest_path: Path) -> None:
    settings = get_settings()
    database = create_database(settings.resolved_database_url)
    try:
        storage = configured_file_storage(settings)
        releases = PluginReleaseService(
            lambda: SqlAlchemyUnitOfWork(database.sessions),
            storage,
            bucket=settings.storage_bucket,
        )
        profile = runtime_profile(
            settings.plugin_runtime_profile,
            native_base_image=settings.plugin_runtime_native_base_image,
            native_base_image_digest=settings.plugin_runtime_native_base_image_digest,
        )
        inventory = load_system_plugin_inventory(
            CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH
        )
        image_builder = PluginOciImageBuilder(
            storage,
            bucket=settings.storage_bucket,
            profile=profile,
            docker_binary=settings.plugin_docker_binary,
        )
        workflow = SystemPluginPublicationWorkflow(
            image_builder,
            releases,
            isolated_release_admission(
                profile=profile,
                egress_policy=settings.resolved_plugin_egress_policy,
                network_policy=settings.resolved_network_policy,
            ),
            inventory,
        )
        publisher = PluginDirectoryPublisher(
            settings.resolved_plugin_roots,
            runtime_profile=settings.plugin_runtime_profile,
            wheelhouse=settings.resolved_plugin_wheelhouse,
        )
        repository_root = CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH.parents[1]
        actor = PlatformPluginActor("live-e2e-bootstrap")
        published_revisions: dict[str, int] = {}
        for slug in ISOLATED_PLUGIN_SLUGS:
            entry = inventory.entry_for(slug)
            verified = await asyncio.to_thread(
                publisher.verify,
                repository_root / entry.project,
                expected_slug=slug,
                loader_target=entry.loader_target,
            )
            release = await workflow.publish_verified(
                verified,
                platform_actor=actor,
            )
            published_revisions[slug] = release.revision

        write_system_plugin_deployment_manifest(
            deployment_manifest_path,
            SystemPluginDeploymentManifest(plugins=()),
        )
        for slug in ISOLATED_PLUGIN_SLUGS:
            await workflow.promote(
                slug=slug,
                revision=published_revisions[slug],
                platform_actor=actor,
            )
    finally:
        await database.dispose()


async def run() -> None:
    token_path = Path(
        os.environ.get("GRAFY_E2E_PAT_FILE", "/run/grafy-e2e/workspace.pat")
    )
    deployment_manifest_path = Path(
        os.environ.get(
            "GRAFY_E2E_SYSTEM_PLUGIN_DEPLOYMENT_MANIFEST",
            "/data/e2e/system-plugin-deployment.json",
        )
    )
    builder_name = f"grafy-e2e-bootstrap-{os.getpid()}-{token_hex(4)}"
    builder_attempted = False
    try:
        try:
            builder_attempted = True
            created = subprocess.run(
                (
                    "docker",
                    "buildx",
                    "create",
                    "--name",
                    builder_name,
                    "--driver",
                    "docker-container",
                    "--use",
                    "--bootstrap",
                ),
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                "Could not provision the live E2E OCI image builder"
            ) from exc
        if created.returncode != 0:
            detail = (created.stderr or created.stdout).strip()[-4_000:]
            raise RuntimeError(
                "Live E2E OCI image builder provisioning failed with exit code "
                f"{created.returncode}: {detail}"
            )

        await seed_workspace(token_path)
        await publish_plugins(deployment_manifest_path)
        print(
            f"Prepared Grafy live E2E Workspace {E2E_WORKSPACE_ID}; "
            f"PAT written to {token_path}"
        )
    finally:
        active_error = sys.exception()
        if builder_attempted:
            try:
                removed = subprocess.run(
                    ("docker", "buildx", "rm", "--force", builder_name),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                if active_error is None:
                    raise RuntimeError(
                        "Could not remove the live E2E OCI image builder"
                    ) from exc
                detail = str(exc).strip()[-4_000:]
                print(
                    "Live E2E cleanup warning: could not remove OCI image "
                    f"builder {builder_name}: {detail}",
                    file=sys.stderr,
                )
            else:
                if removed.returncode != 0:
                    detail = (removed.stderr or removed.stdout).strip()[-4_000:]
                    message = (
                        "Live E2E OCI image builder cleanup failed with exit code "
                        f"{removed.returncode} for {builder_name}: {detail}"
                    )
                    if active_error is None:
                        raise RuntimeError(message)
                    print(f"Live E2E cleanup warning: {message}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(run())

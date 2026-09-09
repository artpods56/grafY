"""Bind staged releases to exact checked-in source and installed host bytes."""

from hashlib import sha256
from pathlib import Path
import os
import subprocess
import tempfile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_releases import (
    PluginExecutionPolicy,
    PluginRelease,
    PluginReleaseScope,
    plugin_contract_digest,
)
from grafy_core.domain.plugin_selection import PluginReleaseSelection
from grafy_persistence import schema

from grafy_api.plugins.publication.source import (
    PluginPublishingError,
    build_deterministic_archive,
    scan_source_tree,
)
from grafy_api.system_host_bindings import SystemHostPluginBinding
from grafy_api.system_plugin_inventory import (
    SystemPluginInventory,
    SystemPluginInventoryEntry,
    SystemPluginInventoryError,
)
from grafy_api.system_plugin_loader import (
    SystemPluginDeploymentEntry,
    SystemPluginDeploymentError,
    SystemPluginDeploymentManifest,
    installed_distribution_build_digest,
    load_system_plugin_deployment,
    write_system_plugin_deployment_manifest,
    wheel_distribution_build_digest,
)


_WHEEL_BUILD_TIMEOUT_SECONDS = 600
_WHEEL_BUILD_DIAGNOSTIC_MAX_CHARS = 4096
_WHEEL_BUILD_ENV_VARIABLES = ("PATH", "TMPDIR", "TMP", "TEMP")


class SystemPluginDeploymentBuildError(RuntimeError):
    """A staged release cannot be bound to the installed API image."""


class SystemPluginDeploymentManifestBuilder:
    """Bind staged System releases to exact installed host package bytes."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def build(
        self,
        inventory: SystemPluginInventory,
        *,
        repository_root: Path,
        output: Path,
        slug: str | None = None,
        revision: int | None = None,
    ) -> SystemPluginDeploymentManifest:
        if (slug is None) != (revision is None):
            raise SystemPluginDeploymentBuildError(
                "System deployment slug and revision must be provided together"
            )
        if revision is not None and (isinstance(revision, bool) or revision < 1):
            raise SystemPluginDeploymentBuildError(
                "System deployment revision must be a positive integer"
            )

        try:
            resolved_repository_root = repository_root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SystemPluginDeploymentBuildError(
                f"System Plugin repository root {repository_root} is inaccessible"
            ) from exc
        if not resolved_repository_root.is_dir():
            raise SystemPluginDeploymentBuildError(
                f"System Plugin repository root {repository_root} is not a directory"
            )

        async with self._sessions() as session:
            async with session.begin():
                releases = await self._target_releases(
                    session,
                    inventory,
                    slug=slug,
                    revision=revision,
                )
                selections = await self._observed_selections(session)
                entries: list[SystemPluginDeploymentEntry] = []
                for release in releases:
                    inventory_entry = inventory.entry_for(release.release.slug)
                    await self._require_staged_release(
                        session,
                        inventory_entry,
                        release,
                    )
                    source_entries = self._require_project_source(
                        resolved_repository_root,
                        inventory_entry,
                        release,
                    )
                    if (
                        inventory_entry.execution_policy
                        is PluginExecutionPolicy.ISOLATED_ONLY
                    ):
                        continue
                    try:
                        source_wheel_build_digest = self._source_wheel_build_digest(
                            inventory_entry,
                            release,
                            source_entries,
                        )
                    except SystemPluginDeploymentError as exc:
                        raise SystemPluginDeploymentBuildError(
                            f"Failed to verify the wheel rebuilt for System "
                            f"Plugin {release.release.slug!r} staged revision "
                            f"{release.release.revision}"
                        ) from exc

                    selection = selections.get(release.release.slug)
                    if selection is None:
                        selection_generation = 1
                    elif (
                        selection.selected_release_id == release.release.id
                        and selection.selected_revision == release.release.revision
                    ):
                        selection_generation = selection.generation
                    else:
                        selection_generation = selection.generation + 1

                    try:
                        host_build_digest = installed_distribution_build_digest(
                            inventory_entry.distribution_name
                        )
                        if host_build_digest != source_wheel_build_digest:
                            raise SystemPluginDeploymentBuildError(
                                f"System Plugin {release.release.slug!r} installed "
                                "distribution does not match the wheel rebuilt "
                                f"from staged revision {release.release.revision}"
                            )
                        binding = SystemHostPluginBinding.from_release(
                            release,
                            selection_generation=selection_generation,
                            loader_target=inventory_entry.loader_target,
                            host_build_digest=host_build_digest,
                        )
                    except (
                        SystemPluginInventoryError,
                        SystemPluginDeploymentError,
                        ValueError,
                    ) as exc:
                        raise SystemPluginDeploymentBuildError(
                            f"Failed to bind staged System Plugin "
                            f"{release.release.slug!r} revision {release.release.revision}"
                        ) from exc
                    entries.append(
                        SystemPluginDeploymentEntry(
                            binding=binding,
                            distribution_name=inventory_entry.distribution_name,
                            loader_target=inventory_entry.loader_target,
                            host_build_digest=host_build_digest,
                        )
                    )

        manifest = SystemPluginDeploymentManifest(plugins=tuple(entries))
        try:
            load_system_plugin_deployment(manifest)
            write_system_plugin_deployment_manifest(output, manifest)
        except SystemPluginDeploymentError as exc:
            raise SystemPluginDeploymentBuildError(
                f"Failed to verify or write System Plugin deployment manifest {output}"
            ) from exc
        return manifest

    def _require_project_source(
        self,
        repository_root: Path,
        entry: SystemPluginInventoryEntry,
        release: InstalledPluginRelease,
    ) -> list[tuple[str, bytes]]:
        project = repository_root.joinpath(*entry.project.split("/"))
        try:
            resolved_project = project.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SystemPluginDeploymentBuildError(
                f"System Plugin {entry.slug!r} project {entry.project!r} is "
                "inaccessible"
            ) from exc
        if not resolved_project.is_relative_to(repository_root):
            raise SystemPluginDeploymentBuildError(
                f"System Plugin {entry.slug!r} project {entry.project!r} escapes "
                f"repository root {repository_root}"
            )
        if not resolved_project.is_dir():
            raise SystemPluginDeploymentBuildError(
                f"System Plugin {entry.slug!r} project {entry.project!r} is not "
                "a directory"
            )
        try:
            entries = scan_source_tree(resolved_project)
            source_digest = sha256(build_deterministic_archive(entries)).hexdigest()
            lock_digest = sha256(
                (resolved_project / "uv.lock").read_bytes()
            ).hexdigest()
        except (OSError, PluginPublishingError) as exc:
            raise SystemPluginDeploymentBuildError(
                f"Failed to snapshot System Plugin {entry.slug!r} project "
                f"{entry.project!r}"
            ) from exc
        if source_digest != release.release.source_digest:
            raise SystemPluginDeploymentBuildError(
                f"System Plugin {entry.slug!r} project source digest does not match "
                f"staged revision {release.release.revision}"
            )
        if lock_digest != release.release.lock_digest:
            raise SystemPluginDeploymentBuildError(
                f"System Plugin {entry.slug!r} project lock digest does not match "
                f"staged revision {release.release.revision}"
            )
        return entries

    def _source_wheel_build_digest(
        self,
        entry: SystemPluginInventoryEntry,
        release: InstalledPluginRelease,
        entries: list[tuple[str, bytes]],
    ) -> str:
        with tempfile.TemporaryDirectory(
            prefix="grafy-system-plugin-wheel-"
        ) as temporary_directory:
            temporary_root = Path(temporary_directory)
            snapshot = temporary_root / "source"
            for name, content in entries:
                destination = snapshot / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            output = temporary_root / "dist"
            command = (
                "uv",
                "build",
                "--wheel",
                "--offline",
                "--no-cache",
                "--no-index",
                "--find-links",
                str(snapshot / "wheels"),
                "--no-config",
                "--no-progress",
                "--no-build-logs",
                "--out-dir",
                str(output),
                str(snapshot),
            )
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=_WHEEL_BUILD_TIMEOUT_SECONDS,
                    close_fds=True,
                    env=self._wheel_build_environment(),
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise SystemPluginDeploymentBuildError(
                    f"Failed to rebuild System Plugin {entry.slug!r} wheel from "
                    f"staged revision {release.release.revision}"
                ) from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                raise SystemPluginDeploymentBuildError(
                    f"Failed to rebuild System Plugin {entry.slug!r} wheel from "
                    f"staged revision {release.release.revision}: "
                    f"{detail[-_WHEEL_BUILD_DIAGNOSTIC_MAX_CHARS:]}"
                )
            wheels = tuple(output.glob("*.whl"))
            if len(wheels) != 1:
                raise SystemPluginDeploymentBuildError(
                    f"System Plugin {entry.slug!r} wheel build produced "
                    f"{len(wheels)} wheels"
                )
            return wheel_distribution_build_digest(
                wheels[0],
                entry.distribution_name,
            )

    @staticmethod
    def _wheel_build_environment() -> dict[str, str]:
        """Minimal sanitized environment for the offline wheel build.

        Only the variables required to resolve the ``uv`` executable and
        create temporary files are preserved, so ambient project, cache, or
        index configuration cannot leak into the reconstructed build.
        """
        return {
            name: os.environ[name]
            for name in _WHEEL_BUILD_ENV_VARIABLES
            if name in os.environ
        }

    async def _target_releases(
        self,
        session: AsyncSession,
        inventory: SystemPluginInventory,
        *,
        slug: str | None,
        revision: int | None,
    ) -> tuple[InstalledPluginRelease, ...]:
        statement = (
            select(PluginRelease, PluginInstallation)
            .join(
                PluginInstallation,
                schema.plugin_installations.c.release_id == schema.plugin_releases.c.id,
            )
            .where(
                schema.plugin_installations.c.scope == PluginReleaseScope.SYSTEM,
                schema.plugin_installations.c.workspace_id.is_(None),
            )
        )
        if slug is not None:
            inventory.entry_for(slug)
            statement = statement.where(
                schema.plugin_releases.c.slug == slug,
                schema.plugin_releases.c.revision == revision,
            )
        rows = [
            InstalledPluginRelease(release=release, installation=installation)
            for release, installation in await session.execute(statement)
        ]
        if slug is not None:
            if not rows:
                raise SystemPluginDeploymentBuildError(
                    f"Published System Plugin {slug!r} revision {revision} does not exist"
                )
            return tuple(rows)

        latest_by_slug: dict[str, InstalledPluginRelease] = {}
        for release in rows:
            current = latest_by_slug.get(release.release.slug)
            if current is None or release.release.revision > current.release.revision:
                latest_by_slug[release.release.slug] = release
        inventory_slugs = {entry.slug for entry in inventory.plugins}
        if set(latest_by_slug) != inventory_slugs:
            missing = sorted(inventory_slugs - set(latest_by_slug))
            unexpected = sorted(set(latest_by_slug) - inventory_slugs)
            raise SystemPluginDeploymentBuildError(
                "Latest staged System releases must exactly cover the checked-in "
                f"inventory; missing={missing}, unexpected={unexpected}"
            )
        return tuple(latest_by_slug[key] for key in sorted(latest_by_slug))

    async def _observed_selections(
        self,
        session: AsyncSession,
    ) -> dict[str, PluginReleaseSelection]:
        selections = list(
            await session.scalars(
                select(PluginReleaseSelection).where(
                    schema.plugin_release_selections.c.scope
                    == PluginReleaseScope.SYSTEM,
                    schema.plugin_release_selections.c.workspace_id.is_(None),
                )
            )
        )
        return {selection.slug: selection for selection in selections}

    async def _require_staged_release(
        self,
        session: AsyncSession,
        entry: SystemPluginInventoryEntry,
        release: InstalledPluginRelease,
    ) -> None:
        try:
            if (
                release.installation.scope is not PluginReleaseScope.SYSTEM
                or release.installation.workspace_id is not None
                or release.release.slug != entry.slug
                or release.release.catalog.slug != release.release.slug
            ):
                raise SystemPluginInventoryError(
                    f"Staged System release {entry.slug!r} has inconsistent identity"
                )
            entry.require_catalog_authority(release.release.catalog)
            if (
                plugin_contract_digest(release.release.catalog)
                != release.release.contract_digest
            ):
                raise SystemPluginInventoryError(
                    f"Staged System release {entry.slug!r} contract digest does not "
                    "match its catalog"
                )
            if release.descriptor_digest != release.release.descriptor.digest:
                raise SystemPluginInventoryError(
                    f"Staged System release {entry.slug!r} descriptor digest does "
                    "not match"
                )
            if release.installation.execution_policy is not entry.execution_policy:
                raise SystemPluginInventoryError(
                    f"Staged System release {entry.slug!r} execution policy does "
                    "not match the checked-in inventory"
                )
            if release.release.capabilities.capabilities != entry.capabilities:
                raise SystemPluginInventoryError(
                    f"Staged System release {entry.slug!r} capabilities do not "
                    "match the checked-in inventory"
                )
            if release.release.loader_target != entry.loader_target:
                raise SystemPluginInventoryError(
                    f"Staged System release {entry.slug!r} loader target does not "
                    "match the checked-in inventory"
                )
            if release.release.runtime_artifact is None:
                raise SystemPluginInventoryError(
                    f"Staged System release {entry.slug!r} has no retained OCI artifact"
                )
            if (
                release.release.runtime_image_digest
                != release.release.runtime_artifact.manifest_digest
            ):
                raise SystemPluginInventoryError(
                    f"Staged System release {entry.slug!r} OCI digest does not match"
                )
            revoked = await session.scalar(
                select(schema.plugin_release_revocations.c.installation_id).where(
                    schema.plugin_release_revocations.c.installation_id
                    == release.installation.id
                )
            )
            if revoked is not None:
                raise SystemPluginInventoryError(
                    f"Staged System release {entry.slug!r} is revoked"
                )
        except SystemPluginInventoryError as exc:
            raise SystemPluginDeploymentBuildError(str(exc)) from exc


__all__ = [
    "SystemPluginDeploymentBuildError",
    "SystemPluginDeploymentManifestBuilder",
]

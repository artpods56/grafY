"""Publish, select, and resolve immutable System Plugin releases."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from hashlib import sha256
from io import BytesIO

from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.canonical_conversions import CANONICAL_ARTIFACT_CONVERSIONS
from grafy_core.domain.plugin_catalog import PluginCatalogRelease
from grafy_core.domain.errors import (
    NotFoundError,
    ObjectAlreadyExistsError,
)
from grafy_core.domain.plugin_releases import (
    PluginArtifactConversionContract,
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginExecutionPolicy,
    PlatformPluginActor,
    PluginRelease,
    PluginReleaseDescriptor,
    PluginReleaseError,
    PluginReleaseNamespace,
    PluginRuntimeArtifact,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_selection import PluginReleaseSelection
from grafy_core.domain.plugin_revocations import (
    SystemPluginRevocationDrainError,
    PluginReleaseRevocation,
    PluginReleaseRevocationError,
    PluginReleaseRevocationReason,
)
from grafy_core.file_contracts import BUILTIN_FILE_FORMATS, build_extension_table
from grafy_core.ports.plugin_releases import PluginReleaseUnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort, SaveFileCommand


_CANONICAL_CONVERSION_CONTRACTS = {
    (contract.key.id, contract.key.version): contract
    for contract in (
        PluginArtifactConversionContract.from_conversion(conversion)
        for conversion in CANONICAL_ARTIFACT_CONVERSIONS
    )
}

SYSTEM_PLUGIN_NAMESPACE = PluginReleaseNamespace()


@dataclass(frozen=True, slots=True)
class SystemPluginPromotionCandidate:
    """Exact release and prospective selection checked before promotion."""

    release: InstalledPluginRelease
    selection: PluginReleaseSelection
    expected_generation: int


def require_canonical_conversion_references(
    catalog: PluginCatalogManifest,
) -> None:
    """Reject release conversion contracts not owned exactly by deployment code."""

    for conversion in catalog.artifact_conversions:
        key = (conversion.key.id, conversion.key.version)
        if _CANONICAL_CONVERSION_CONTRACTS.get(key) == conversion:
            continue
        raise PluginReleaseError(
            f"Plugin {catalog.slug!r} artifact conversion "
            f"{conversion.key.id}@{conversion.key.version} is not an exact "
            "deployment-owned canonical conversion"
        )


def _require_no_extension_claim_collision(
    catalog: PluginCatalogManifest,
    installed_catalogs: Iterable[PluginCatalogManifest],
) -> None:
    """Refuse an installation whose extension claim the deployment already holds.

    A release carries no scope, so a collision means something only against the
    set a deployment has installed. The builtin file formats are part of every
    deployment's table, and each installed catalog contributes its owned types
    and its exact dependencies.
    """

    claims: list[tuple[ArtifactTypeKey, tuple[str, ...]]] = [
        (spec.key, spec.extensions) for spec in BUILTIN_FILE_FORMATS
    ]
    for installed in (*installed_catalogs, catalog):
        claims.extend(
            (
                ArtifactTypeKey(contract.key.id, contract.key.schema_version),
                contract.extensions,
            )
            for contract in (
                *installed.artifact_types,
                *installed.artifact_type_dependencies,
            )
        )
    _ = build_extension_table(claims)


class PluginReleaseService:
    """Release boundary for the digest-addressed freezes a deployment runs.

    Source objects are content-addressed under the ``plugin-releases/``
    namespace, so a failed publication can only leave an orphaned object in
    that known garbage-collectable namespace; rows stay append-only.
    """

    def __init__(
        self,
        unit_of_work_factory: Callable[[], PluginReleaseUnitOfWorkPort],
        storage: FileStoragePort,
        *,
        bucket: str,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._storage = storage
        self._bucket = bucket

    async def reusable_runtime_artifact(
        self,
        *,
        catalog: PluginCatalogManifest,
        capabilities: PluginCapabilityManifest,
        source_digest: str,
        lock_digest: str,
        runtime_profile: str,
        loader_target: str,
    ) -> PluginRuntimeArtifact | None:
        """Return the retained artifact for an identical verified release."""

        async with self._unit_of_work_factory() as unit_of_work:
            release = await unit_of_work.plugin_releases.get_by_source_digest(
                catalog.slug,
                source_digest,
            )
        if release is None or release.runtime_artifact is None:
            return None
        if (
            release.catalog != catalog
            or release.capabilities != capabilities
            or release.lock_digest != lock_digest
            or release.runtime_profile != runtime_profile.strip()
            or release.loader_target != loader_target
        ):
            return None
        return release.runtime_artifact

    async def publish_system(
        self,
        *,
        catalog: PluginCatalogManifest,
        capabilities: PluginCapabilityManifest,
        source_archive: bytes,
        lock_digest: str,
        runtime_profile: str,
        runtime_artifact: PluginRuntimeArtifact,
        execution_policy: PluginExecutionPolicy,
        platform_actor: PlatformPluginActor,
        loader_target: str,
    ) -> InstalledPluginRelease:
        """Append an immutable global release without implicitly promoting it."""

        require_canonical_conversion_references(catalog)
        if not source_archive:
            raise PluginReleaseError("Plugin source archive must not be empty")
        runtime_profile = runtime_profile.strip()
        source_digest = sha256(source_archive).hexdigest()
        contract_digest = plugin_contract_digest(catalog)
        profile_digest = plugin_profile_digest(runtime_profile)
        protocol_digest = plugin_protocol_digest()
        source_object_key = f"plugin-releases/{catalog.slug}/{source_digest}.tar.gz"
        descriptor = PluginReleaseDescriptor(
            source_digest=source_digest,
            contract_digest=contract_digest,
            capability_digest=capabilities.digest,
            protocol_digest=protocol_digest,
            profile_digest=profile_digest,
            lock_digest=lock_digest,
            runtime_profile=runtime_profile,
            loader_target=loader_target,
            runtime_artifact=runtime_artifact,
        )
        async with self._unit_of_work_factory() as unit_of_work:
            existing = await unit_of_work.plugin_releases.get_by_descriptor_digest(
                catalog.slug,
                descriptor.digest,
            )
            if existing is not None:
                if existing.catalog != catalog or existing.capabilities != capabilities:
                    raise PluginReleaseError(
                        "Plugin release descriptor digest matched different metadata"
                    )
                release = existing
            else:
                revision = await unit_of_work.plugin_releases.next_revision(
                    catalog.slug,
                )
                await self._save_source_archive(
                    source_object_key,
                    source_archive,
                    source_digest,
                )
                release = PluginRelease(
                    slug=catalog.slug,
                    revision=revision,
                    catalog=catalog,
                    contract_digest=contract_digest,
                    capabilities=capabilities,
                    capability_digest=capabilities.digest,
                    protocol_digest=protocol_digest,
                    profile_digest=profile_digest,
                    source_object_key=source_object_key,
                    source_digest=source_digest,
                    lock_digest=lock_digest,
                    runtime_profile=runtime_profile,
                    loader_target=loader_target,
                    runtime_image_digest=runtime_artifact.manifest_digest,
                    runtime_artifact=runtime_artifact,
                    descriptor_digest=descriptor.digest,
                    published_by_platform_actor=platform_actor.reference,
                )
                await unit_of_work.plugin_releases.add(release)
            installed = await unit_of_work.plugin_releases.get_by_revision(
                SYSTEM_PLUGIN_NAMESPACE,
                catalog.slug,
                release.revision,
            )
            if installed is None:
                installation = PluginInstallation.from_release(
                    release,
                    namespace=SYSTEM_PLUGIN_NAMESPACE,
                    execution_policy=execution_policy,
                    installed_by_platform_actor=platform_actor.reference,
                )
                await unit_of_work.plugin_releases.add_installation(installation)
                installed = InstalledPluginRelease(
                    release=release,
                    installation=installation,
                )
            await unit_of_work.commit()
            return installed

    async def prepare_system_promotion(
        self,
        *,
        slug: str,
        revision: int,
        platform_actor: PlatformPluginActor,
        expected_generation: int | None = None,
    ) -> SystemPluginPromotionCandidate:
        """Build the exact post-promotion selection without mutating persistence."""

        namespace = SYSTEM_PLUGIN_NAMESPACE
        async with self._unit_of_work_factory() as unit_of_work:
            release = await unit_of_work.plugin_releases.get_by_revision(
                namespace,
                slug,
                revision,
            )
            if release is None:
                raise NotFoundError("System Plugin release", f"{slug}@{revision}")
            current = await unit_of_work.plugin_releases.get_selection(
                namespace,
                slug,
            )
            actor_reference = f"platform:{platform_actor.reference}"
            if current is None:
                if expected_generation not in (None, 0):
                    raise PluginReleaseError(
                        f"System Plugin selection {slug!r} changed concurrently"
                    )
                prospective = PluginReleaseSelection.from_release(
                    release,
                    actor_reference=actor_reference,
                )
                observed_generation = 0
            else:
                if (
                    expected_generation is not None
                    and current.generation != expected_generation
                ):
                    raise PluginReleaseError(
                        f"System Plugin selection {slug!r} changed concurrently"
                    )
                observed_generation = current.generation
                prospective = replace(current)
                prospective.select(
                    release,
                    publish=True,
                    actor_reference=actor_reference,
                )
            return SystemPluginPromotionCandidate(
                release=release,
                selection=prospective,
                expected_generation=observed_generation,
            )

    async def promote_system(
        self,
        *,
        slug: str,
        revision: int,
        platform_actor: PlatformPluginActor,
        expected_generation: int,
    ) -> PluginReleaseSelection:
        namespace = SYSTEM_PLUGIN_NAMESPACE
        async with self._unit_of_work_factory() as unit_of_work:
            release = await unit_of_work.plugin_releases.get_by_revision(
                namespace,
                slug,
                revision,
            )
            if release is None:
                raise NotFoundError("System Plugin release", f"{slug}@{revision}")
            _require_no_extension_claim_collision(
                release.release.catalog,
                await self._installed_catalogs(unit_of_work, slug=slug),
            )
            selection = await unit_of_work.plugin_releases.get_selection(
                namespace,
                slug,
            )
            actor_reference = f"platform:{platform_actor.reference}"
            if selection is None:
                if expected_generation != 0:
                    raise PluginReleaseError(
                        f"System Plugin selection {slug!r} changed concurrently"
                    )
                selection = PluginReleaseSelection.from_release(
                    release,
                    actor_reference=actor_reference,
                )
                await unit_of_work.plugin_releases.add_selection(selection)
            else:
                if selection.generation != expected_generation:
                    raise PluginReleaseError(
                        f"System Plugin selection {slug!r} changed concurrently"
                    )
                previous_generation = selection.generation
                selection.select(
                    release,
                    publish=True,
                    actor_reference=actor_reference,
                )
                if selection.generation != previous_generation:
                    await unit_of_work.plugin_releases.update_selection(
                        selection,
                        expected_generation=previous_generation,
                    )
            await unit_of_work.commit()
            return selection

    async def _installed_catalogs(
        self,
        unit_of_work: PluginReleaseUnitOfWorkPort,
        *,
        slug: str,
    ) -> list[PluginCatalogManifest]:
        """Selected catalogs a new installation would sit beside.

        The candidate's own family is excluded because its selection is what
        the installation replaces.
        """

        current = await unit_of_work.plugin_releases.list_current(
            SYSTEM_PLUGIN_NAMESPACE
        )
        return [
            release.release.catalog
            for release in current
            if release.release.catalog.slug != slug
        ]

    async def list_catalog(self) -> list[PluginCatalogRelease]:
        """Read selected releases and admission state in one transaction."""
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.plugin_releases.list_catalog()

    async def get_by_revision(
        self,
        slug: str,
        revision: int,
    ) -> InstalledPluginRelease | None:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.plugin_releases.get_by_revision(
                SYSTEM_PLUGIN_NAMESPACE,
                slug,
                revision,
            )

    async def get_selection(self, slug: str) -> PluginReleaseSelection | None:
        """Read the exact mutable selection for one Plugin family."""

        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.plugin_releases.get_selection(
                SYSTEM_PLUGIN_NAMESPACE,
                slug,
            )

    async def revoke_system(
        self,
        *,
        slug: str,
        revision: int,
        reason: PluginReleaseRevocationReason,
        platform_actor: PlatformPluginActor,
    ) -> PluginReleaseRevocation:
        """Permanently revoke one exact release as platform authority."""

        namespace = SYSTEM_PLUGIN_NAMESPACE
        async with self._unit_of_work_factory() as unit_of_work:
            active = await unit_of_work.plugin_releases.lock_system_revocation()
            if active:
                raise SystemPluginRevocationDrainError(
                    slug=slug,
                    revision=revision,
                    active_executions=active,
                )
            release = await unit_of_work.plugin_releases.get_by_revision(
                namespace,
                slug,
                revision,
            )
            if release is None:
                raise NotFoundError("System Plugin release", f"{slug}@{revision}")
            proposed = PluginReleaseRevocation.from_release(
                release,
                reason=reason,
                revoked_by_platform_actor=platform_actor.reference,
            )
            existing = (
                await unit_of_work.plugin_releases.get_revocation_by_installation_id(
                    release.installation.id
                )
            )
            if existing is not None:
                if existing.has_same_intent(proposed):
                    return existing
                raise PluginReleaseRevocationError(
                    "Plugin release revocation already exists with different "
                    f"immutable intent for system::{slug}@{revision} "
                    f"({release.release.id})"
                )
            revocation = await unit_of_work.plugin_releases.add_revocation(proposed)
            await unit_of_work.commit()
            return revocation

    async def get_system_revocation(
        self,
        *,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None:
        async with self._unit_of_work_factory() as unit_of_work:
            release = await unit_of_work.plugin_releases.get_by_revision(
                SYSTEM_PLUGIN_NAMESPACE,
                slug,
                revision,
            )
            if release is None:
                return None
            return (
                await unit_of_work.plugin_releases.get_revocation_by_installation_id(
                    release.installation.id
                )
            )

    async def list_runtime_artifacts(self) -> list[PluginRuntimeArtifact]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.plugin_releases.list_runtime_artifacts()

    async def _save_source_archive(
        self,
        object_key: str,
        source_archive: bytes,
        source_digest: str,
    ) -> None:
        try:
            stored = await self._storage.save(
                SaveFileCommand(
                    bucket=self._bucket,
                    path=object_key,
                    stream=BytesIO(source_archive),
                    content_type="application/gzip",
                    metadata={
                        "source": "plugin-release",
                        "sha256": source_digest,
                    },
                )
            )
        except ObjectAlreadyExistsError:
            existing = await self._storage.load(self._bucket, object_key)
            try:
                existing_digest = sha256(existing.read()).hexdigest()
            finally:
                existing.close()
            if existing_digest != source_digest:
                raise PluginReleaseError(
                    f"Stored Plugin source {object_key!r} does not match its digest"
                )
            return
        if stored.sha256 != source_digest:
            raise PluginReleaseError(
                f"Stored Plugin source {object_key!r} changed while being written"
            )


__all__ = [
    "SYSTEM_PLUGIN_NAMESPACE",
    "PluginReleaseService",
    "SystemPluginPromotionCandidate",
    "require_canonical_conversion_references",
]

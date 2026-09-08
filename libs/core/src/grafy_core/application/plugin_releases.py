"""Publish, select, and resolve immutable scoped Plugin releases."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from hashlib import sha256
from io import BytesIO
from uuid import UUID

from grafy_core.application.identity import authorize_workspace
from grafy_core.canonical_conversions import CANONICAL_ARTIFACT_CONVERSIONS
from grafy_core.domain.plugin_catalog import PluginCatalogRelease
from grafy_core.domain.errors import (
    NotFoundError,
    ObjectAlreadyExistsError,
)
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceCapability,
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
    PluginReleaseHeadConflictError,
    PluginReleaseNamespace,
    PluginReleaseScope,
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
from grafy_core.ports.plugin_releases import PluginReleaseUnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort, SaveFileCommand


_CANONICAL_CONVERSION_CONTRACTS = {
    (contract.key.id, contract.key.version): contract
    for contract in (
        PluginArtifactConversionContract.from_conversion(conversion)
        for conversion in CANONICAL_ARTIFACT_CONVERSIONS
    )
}


@dataclass(frozen=True, slots=True)
class SystemPluginPromotionCandidate:
    """Exact release and prospective selection checked before promotion."""

    release: InstalledPluginRelease
    selection: PluginReleaseSelection
    expected_generation: int


def require_workspace_catalog_authority(catalog: PluginCatalogManifest) -> None:
    """Require Workspace-owned identities to use the slug's family namespace."""

    family = catalog.slug.rsplit(".", maxsplit=1)[-1]
    prefixes = (f"{catalog.slug}.", f"{family}.")
    identities = [("node", node.operator_id) for node in catalog.nodes]
    identities.extend(
        ("artifact type", artifact.key.id) for artifact in catalog.artifact_types
    )
    for identity_kind, identity in identities:
        if identity.startswith(prefixes):
            continue
        raise PluginReleaseError(
            f"Workspace Plugin {catalog.slug!r} owned {identity_kind} "
            f"{identity!r} must use one of the family namespaces {prefixes!r}"
        )


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


class PluginReleaseService:
    """Shared release boundary for human- and agent-authored Plugin freezes.

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

    async def authorize_publisher(
        self,
        workspace_id: UUID,
        published_by_user_id: UUID,
    ) -> None:
        """Require an active Plugin-publishing actor before expensive work."""

        async with self._unit_of_work_factory() as unit_of_work:
            await self._require_publisher(
                unit_of_work,
                workspace_id,
                published_by_user_id,
            )

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

    async def publish(
        self,
        *,
        workspace_id: UUID,
        catalog: PluginCatalogManifest,
        capabilities: PluginCapabilityManifest,
        source_archive: bytes,
        lock_digest: str,
        runtime_profile: str,
        runtime_artifact: PluginRuntimeArtifact | None,
        published_by_user_id: UUID,
        loader_target: str,
        expected_base_revision: int | None = None,
    ) -> InstalledPluginRelease:
        require_workspace_catalog_authority(catalog)
        return await self._append_release(
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.WORKSPACE,
                workspace_id=workspace_id,
            ),
            catalog=catalog,
            capabilities=capabilities,
            source_archive=source_archive,
            lock_digest=lock_digest,
            runtime_profile=runtime_profile,
            loader_target=loader_target,
            runtime_artifact=runtime_artifact,
            execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
            published_by_user_id=published_by_user_id,
            published_by_platform_actor=None,
            select_release=True,
            expected_base_revision=expected_base_revision,
        )

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

        return await self._append_release(
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.SYSTEM,
                workspace_id=None,
            ),
            catalog=catalog,
            capabilities=capabilities,
            source_archive=source_archive,
            lock_digest=lock_digest,
            runtime_profile=runtime_profile,
            loader_target=loader_target,
            runtime_artifact=runtime_artifact,
            execution_policy=execution_policy,
            published_by_user_id=None,
            published_by_platform_actor=platform_actor.reference,
            select_release=False,
            expected_base_revision=None,
        )

    async def prepare_system_promotion(
        self,
        *,
        slug: str,
        revision: int,
        platform_actor: PlatformPluginActor,
        expected_generation: int | None = None,
    ) -> SystemPluginPromotionCandidate:
        """Build the exact post-promotion selection without mutating persistence."""

        namespace = PluginReleaseNamespace(
            scope=PluginReleaseScope.SYSTEM,
            workspace_id=None,
        )
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
        namespace = PluginReleaseNamespace(
            scope=PluginReleaseScope.SYSTEM,
            workspace_id=None,
        )
        async with self._unit_of_work_factory() as unit_of_work:
            release = await unit_of_work.plugin_releases.get_by_revision(
                namespace,
                slug,
                revision,
            )
            if release is None:
                raise NotFoundError("System Plugin release", f"{slug}@{revision}")
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

    async def _append_release(
        self,
        *,
        namespace: PluginReleaseNamespace,
        catalog: PluginCatalogManifest,
        capabilities: PluginCapabilityManifest,
        source_archive: bytes,
        lock_digest: str,
        runtime_profile: str,
        runtime_artifact: PluginRuntimeArtifact | None,
        execution_policy: PluginExecutionPolicy,
        published_by_user_id: UUID | None,
        published_by_platform_actor: str | None,
        select_release: bool,
        expected_base_revision: int | None,
        loader_target: str,
    ) -> InstalledPluginRelease:
        require_canonical_conversion_references(catalog)
        if not source_archive:
            raise PluginReleaseError("Plugin source archive must not be empty")
        if namespace.scope is PluginReleaseScope.SYSTEM and runtime_artifact is None:
            raise PluginReleaseError(
                "System Plugin releases require a retained runtime artifact"
            )
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
            # Authorization takes the Workspace lock before any release reads.
            # It also serializes first publications, which have no selection row yet.
            if namespace.scope is PluginReleaseScope.WORKSPACE:
                if namespace.workspace_id is None or published_by_user_id is None:
                    raise PluginReleaseError(
                        "Workspace Plugin publication requires a Workspace publisher"
                    )
                await self._require_publisher(
                    unit_of_work,
                    namespace.workspace_id,
                    published_by_user_id,
                )
            selection = None
            if select_release:
                selection = await unit_of_work.plugin_releases.get_selection(
                    namespace,
                    catalog.slug,
                )
            if expected_base_revision is not None:
                current_revision = (
                    0 if selection is None else selection.selected_revision
                )
                if current_revision != expected_base_revision:
                    assert namespace.workspace_id is not None
                    raise PluginReleaseHeadConflictError(
                        workspace_id=namespace.workspace_id,
                        slug=catalog.slug,
                        expected_revision=expected_base_revision,
                        actual_revision=current_revision,
                    )
            existing = await unit_of_work.plugin_releases.get_by_descriptor_digest(
                catalog.slug,
                descriptor.digest,
            )
            if namespace.scope is PluginReleaseScope.WORKSPACE:
                system_namespace = PluginReleaseNamespace(
                    scope=PluginReleaseScope.SYSTEM,
                    workspace_id=None,
                )
                if (
                    existing is None
                    and await unit_of_work.plugin_releases.family_exists(
                        system_namespace,
                        catalog.slug,
                    )
                ):
                    raise PluginReleaseError(
                        f"Workspace Plugin {catalog.slug!r} conflicts with a "
                        "System Plugin family"
                    )
                self._require_no_cross_scope_identity_collisions(
                    catalog,
                    await unit_of_work.plugin_releases.list_catalogs(system_namespace),
                    scope=PluginReleaseScope.WORKSPACE,
                )
            else:
                if (
                    existing is None
                    and await unit_of_work.plugin_releases.workspace_family_exists(
                        catalog.slug
                    )
                ):
                    raise PluginReleaseError(
                        f"System Plugin {catalog.slug!r} conflicts with a Workspace "
                        "Plugin family"
                    )
                self._require_no_cross_scope_identity_collisions(
                    catalog,
                    await unit_of_work.plugin_releases.list_workspace_catalogs(),
                    scope=PluginReleaseScope.SYSTEM,
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
                    runtime_image_digest=(
                        None
                        if runtime_artifact is None
                        else runtime_artifact.manifest_digest
                    ),
                    runtime_artifact=runtime_artifact,
                    descriptor_digest=descriptor.digest,
                    published_by_user_id=published_by_user_id,
                    published_by_platform_actor=published_by_platform_actor,
                )
                await unit_of_work.plugin_releases.add(release)
            installed = await unit_of_work.plugin_releases.get_by_revision(
                namespace,
                catalog.slug,
                release.revision,
            )
            if installed is None:
                installation = PluginInstallation.from_release(
                    release,
                    namespace=namespace,
                    execution_policy=execution_policy,
                    installed_by_user_id=published_by_user_id,
                    installed_by_platform_actor=published_by_platform_actor,
                )
                await unit_of_work.plugin_releases.add_installation(installation)
                installed = InstalledPluginRelease(
                    release=release,
                    installation=installation,
                )
            if select_release:
                actor_reference = f"user:{published_by_user_id}"
                if selection is None:
                    await unit_of_work.plugin_releases.add_selection(
                        PluginReleaseSelection.from_release(
                            installed,
                            actor_reference=actor_reference,
                        )
                    )
                else:
                    expected_generation = selection.generation
                    selection.select(
                        installed,
                        publish=True,
                        actor_reference=actor_reference,
                    )
                    if selection.generation != expected_generation:
                        await unit_of_work.plugin_releases.update_selection(
                            selection,
                            expected_generation=expected_generation,
                        )
            await unit_of_work.commit()
            return installed

    @staticmethod
    def _require_no_cross_scope_identity_collisions(
        catalog: PluginCatalogManifest,
        retained_catalogs: list[PluginCatalogManifest],
        *,
        scope: PluginReleaseScope,
    ) -> None:
        retained_scope = (
            PluginReleaseScope.SYSTEM
            if scope is PluginReleaseScope.WORKSPACE
            else PluginReleaseScope.WORKSPACE
        )
        retained_nodes = {
            (node.operator_id, node.operator_version)
            for retained_catalog in retained_catalogs
            if retained_catalog != catalog
            for node in retained_catalog.nodes
        }
        for node in catalog.nodes:
            key = (node.operator_id, node.operator_version)
            if key in retained_nodes:
                raise PluginReleaseError(
                    f"{scope.value.title()} Plugin {catalog.slug!r} node "
                    f"{node.operator_id}@{node.operator_version} conflicts with a "
                    f"retained {retained_scope.value.title()} Plugin identity"
                )
        retained_artifacts = {
            (artifact.key.id, artifact.key.schema_version)
            for retained_catalog in retained_catalogs
            if retained_catalog != catalog
            for artifact in retained_catalog.artifact_types
        }
        for artifact in catalog.artifact_types:
            key = (artifact.key.id, artifact.key.schema_version)
            if key in retained_artifacts:
                raise PluginReleaseError(
                    f"{scope.value.title()} Plugin {catalog.slug!r} artifact type "
                    f"{artifact.key.id}@{artifact.key.schema_version} conflicts "
                    f"with a retained {retained_scope.value.title()} Plugin identity"
                )

    async def list_catalog(self, workspace_id: UUID) -> list[PluginCatalogRelease]:
        """Read selected releases and admission state in one transaction."""
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.plugin_releases.list_catalog(workspace_id)

    async def list_current(
        self,
        workspace_id: UUID,
    ) -> list[InstalledPluginRelease]:
        namespace = PluginReleaseNamespace(
            scope=PluginReleaseScope.WORKSPACE,
            workspace_id=workspace_id,
        )
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.plugin_releases.list_current(namespace)

    async def list_current_system(self) -> list[InstalledPluginRelease]:
        namespace = PluginReleaseNamespace(
            scope=PluginReleaseScope.SYSTEM,
            workspace_id=None,
        )
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.plugin_releases.list_current(namespace)

    async def get_system_by_revision(
        self,
        slug: str,
        revision: int,
    ) -> InstalledPluginRelease | None:
        namespace = PluginReleaseNamespace(
            scope=PluginReleaseScope.SYSTEM,
            workspace_id=None,
        )
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.plugin_releases.get_by_revision(
                namespace,
                slug,
                revision,
            )

    async def get_by_revision(
        self,
        workspace_id: UUID,
        slug: str,
        revision: int,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> InstalledPluginRelease | None:
        namespace = PluginReleaseNamespace(
            scope=scope,
            workspace_id=(
                workspace_id if scope is PluginReleaseScope.WORKSPACE else None
            ),
        )
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.plugin_releases.get_by_revision(
                namespace,
                slug,
                revision,
            )

    async def get_selection(
        self,
        workspace_id: UUID,
        slug: str,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> PluginReleaseSelection | None:
        """Read the exact mutable selection for one scoped Plugin family."""

        namespace = PluginReleaseNamespace(
            scope=scope,
            workspace_id=(
                workspace_id if scope is PluginReleaseScope.WORKSPACE else None
            ),
        )
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.plugin_releases.get_selection(namespace, slug)

    async def revoke(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        revision: int,
        reason: PluginReleaseRevocationReason,
        revoked_by_user_id: UUID,
    ) -> PluginReleaseRevocation:
        """Permanently revoke one exact release owned by a Workspace."""

        return await self._revoke_release(
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.WORKSPACE,
                workspace_id=workspace_id,
            ),
            slug=slug,
            revision=revision,
            reason=reason,
            revoked_by_user_id=revoked_by_user_id,
            revoked_by_platform_actor=None,
        )

    async def revoke_system(
        self,
        *,
        slug: str,
        revision: int,
        reason: PluginReleaseRevocationReason,
        platform_actor: PlatformPluginActor,
    ) -> PluginReleaseRevocation:
        """Permanently revoke one exact System release as platform authority."""

        return await self._revoke_release(
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.SYSTEM,
                workspace_id=None,
            ),
            slug=slug,
            revision=revision,
            reason=reason,
            revoked_by_user_id=None,
            revoked_by_platform_actor=platform_actor.reference,
        )

    async def get_revocation(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None:
        return await self._get_revocation(
            PluginReleaseNamespace(
                scope=PluginReleaseScope.WORKSPACE,
                workspace_id=workspace_id,
            ),
            slug,
            revision,
        )

    async def get_system_revocation(
        self,
        *,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None:
        return await self._get_revocation(
            PluginReleaseNamespace(
                scope=PluginReleaseScope.SYSTEM,
                workspace_id=None,
            ),
            slug,
            revision,
        )

    async def _revoke_release(
        self,
        *,
        namespace: PluginReleaseNamespace,
        slug: str,
        revision: int,
        reason: PluginReleaseRevocationReason,
        revoked_by_user_id: UUID | None,
        revoked_by_platform_actor: str | None,
    ) -> PluginReleaseRevocation:
        async with self._unit_of_work_factory() as unit_of_work:
            if namespace.scope is PluginReleaseScope.WORKSPACE:
                if namespace.workspace_id is None or revoked_by_user_id is None:
                    raise PluginReleaseRevocationError(
                        "Workspace Plugin revocation requires a Workspace actor"
                    )
                await self._require_publisher(
                    unit_of_work,
                    namespace.workspace_id,
                    revoked_by_user_id,
                )
            elif revoked_by_platform_actor is None:
                raise PluginReleaseRevocationError(
                    "System Plugin revocation requires a platform actor"
                )

            if namespace.scope is PluginReleaseScope.SYSTEM:
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
                raise NotFoundError(
                    f"{namespace.scope.value.title()} Plugin release",
                    f"{slug}@{revision}",
                )
            proposed = PluginReleaseRevocation.from_release(
                release,
                reason=reason,
                revoked_by_user_id=revoked_by_user_id,
                revoked_by_platform_actor=revoked_by_platform_actor,
            )
            existing = (
                await unit_of_work.plugin_releases.get_revocation_by_installation_id(
                    release.installation_id
                )
            )
            if existing is not None:
                if existing.has_same_intent(proposed):
                    return existing
                raise PluginReleaseRevocationError(
                    "Plugin release revocation already exists with different "
                    f"immutable intent for {namespace.scope.value}:"
                    f"{namespace.workspace_id}:{slug}@{revision} ({release.id})"
                )
            revocation = await unit_of_work.plugin_releases.add_revocation(proposed)
            await unit_of_work.commit()
            return revocation

    async def _get_revocation(
        self,
        namespace: PluginReleaseNamespace,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None:
        async with self._unit_of_work_factory() as unit_of_work:
            release = await unit_of_work.plugin_releases.get_by_revision(
                namespace,
                slug,
                revision,
            )
            if release is None:
                return None
            return await unit_of_work.plugin_releases.get_revocation_by_installation_id(
                release.installation_id
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

    @staticmethod
    async def _require_publisher(
        unit_of_work: PluginReleaseUnitOfWorkPort,
        workspace_id: UUID,
        published_by_user_id: UUID,
    ) -> None:
        await authorize_workspace(
            unit_of_work.identity,
            actor=ActorContext(
                user_id=published_by_user_id,
                credential_reference="plugin-publication",
            ),
            workspace_id=workspace_id,
            capability=WorkspaceCapability.PUBLISH_PLUGIN,
        )


__all__ = [
    "PluginReleaseService",
    "SystemPluginPromotionCandidate",
    "require_canonical_conversion_references",
    "require_workspace_catalog_authority",
]

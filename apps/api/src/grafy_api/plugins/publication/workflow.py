"""Verified publication and promotion of System Plugin releases."""


from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import (
    PlatformPluginActor,
    PluginCatalogManifest,
    PluginExecutionPolicy,
)
from grafy_core.domain.plugin_selection import PluginReleaseSelection
from grafy_core.file_contracts import ExtensionClaimCollisionError

from grafy_api.plugins.runtime.admission import (
    ReleaseExecutionAdmission,
    ReleaseExecutionRejection,
)
from grafy_api.plugins.publication.oci import PluginOciImageBuilder
from grafy_api.plugins.publication.source import (
    PluginPublishingError,
    VerifiedPluginCandidate,
)
from grafy_core.domain.system_plugin_inventory import (
    SystemPluginInventory,
    SystemPluginInventoryError,
)


def require_network_contract(catalog: PluginCatalogManifest) -> None:
    """Reject newly published nodes that request egress without a contract.

    Historical releases keep their persisted contracts untouched; only new
    publication must declare how each ``network.egress`` node obtains its
    destinations.
    """

    for node in catalog.nodes:
        if (
            PluginRuntimeCapability.NETWORK_EGRESS in set(node.required_capabilities)
            and node.http_egress is None
        ):
            raise PluginPublishingError(
                f"Node {node.operator_id}@{node.operator_version} requests "
                "network.egress without an HTTP egress contract; declare its "
                "configured URL fields or its dynamic destinations"
            )


class SystemPluginPublicationWorkflow:
    """Stage and explicitly promote global releases from a trusted publisher.

    Verification is deliberately outside this boundary. A one-shot platform
    publisher or CI sandbox supplies ``VerifiedPluginCandidate``; the online
    API does not expose this workflow or receive Docker build authority.
    """

    def __init__(
        self,
        image_builder: PluginOciImageBuilder,
        releases: PluginReleaseService,
        admission: ReleaseExecutionAdmission,
        system_inventory: SystemPluginInventory,
    ) -> None:
        self._image_builder = image_builder
        self._releases = releases
        self._admission = admission
        self._system_inventory = system_inventory

    async def publish_verified(
        self,
        verified: VerifiedPluginCandidate,
        *,
        platform_actor: PlatformPluginActor,
    ) -> InstalledPluginRelease:
        try:
            entry = self._system_inventory.entry_for(verified.catalog.slug)
            self._system_inventory.require_catalog_authority(verified.catalog)
            require_network_contract(verified.catalog)
        except SystemPluginInventoryError as exc:
            raise PluginPublishingError(str(exc)) from exc
        if verified.capabilities.capabilities != entry.capabilities:
            raise PluginPublishingError(
                f"System Plugin {entry.slug!r} capabilities do not match the "
                "checked-in inventory"
            )
        if verified.loader_target != entry.loader_target:
            raise PluginPublishingError(
                f"System Plugin {entry.slug!r} was inspected with loader target "
                f"{verified.loader_target!r}, expected {entry.loader_target!r}"
            )
        runtime_artifact = await self._releases.reusable_runtime_artifact(
            catalog=verified.catalog,
            capabilities=verified.capabilities,
            source_digest=verified.source_digest,
            lock_digest=verified.lock_digest,
            runtime_profile=verified.runtime_profile,
            loader_target=verified.loader_target,
        )
        if runtime_artifact is None:
            runtime_artifact = await self._image_builder.build_and_store(
                candidate=verified,
            )
        return await self._releases.publish_system(
            catalog=verified.catalog,
            capabilities=verified.capabilities,
            source_archive=verified.source_archive,
            lock_digest=verified.lock_digest,
            runtime_profile=verified.runtime_profile,
            runtime_artifact=runtime_artifact,
            loader_target=verified.loader_target,
            execution_policy=entry.execution_policy,
            platform_actor=platform_actor,
        )

    async def promote(
        self,
        *,
        slug: str,
        revision: int,
        platform_actor: PlatformPluginActor,
        expected_generation: int | None = None,
    ) -> PluginReleaseSelection:
        try:
            candidate = await self._releases.prepare_system_promotion(
                slug=slug,
                revision=revision,
                platform_actor=platform_actor,
                expected_generation=expected_generation,
            )
        except NotFoundError as exc:
            raise PluginPublishingError(
                f"System Plugin release {slug!r} revision {revision} does not exist"
            ) from exc
        try:
            entry = self._system_inventory.entry_for(candidate.release.release.slug)
            self._system_inventory.require_catalog_authority(
                candidate.release.release.catalog
            )
        except SystemPluginInventoryError as exc:
            raise PluginPublishingError(str(exc)) from exc
        if (
            candidate.release.installation.execution_policy
            is not entry.execution_policy
        ):
            raise PluginPublishingError(
                f"System Plugin {entry.slug!r} execution policy does not match "
                "the checked-in inventory"
            )
        if candidate.release.release.capabilities.capabilities != entry.capabilities:
            raise PluginPublishingError(
                f"System Plugin {entry.slug!r} capabilities do not match the "
                "checked-in inventory"
            )
        if candidate.release.release.loader_target != entry.loader_target:
            raise PluginPublishingError(
                f"System Plugin {entry.slug!r} loader target does not match the "
                "checked-in inventory"
            )
        decision = self._admission.decide(
            candidate.release,
            selection=candidate.selection,
        )
        if isinstance(decision, ReleaseExecutionRejection):
            raise PluginPublishingError(
                f"System Plugin release {slug!r} revision {revision} cannot be "
                f"promoted ({decision.reason}): {decision.detail}"
            )
        if (
            candidate.release.installation.execution_policy
            is PluginExecutionPolicy.HOST_ELIGIBLE
        ):
            raise PluginPublishingError(
                f"System Plugin release {slug!r} revision {revision} cannot be "
                "promoted with the retired host-eligible execution policy; "
                "System Plugins must use isolated-only execution"
            )
        try:
            return await self._releases.promote_system(
                slug=slug,
                revision=revision,
                platform_actor=platform_actor,
                expected_generation=candidate.expected_generation,
            )
        except ExtensionClaimCollisionError as exc:
            raise PluginPublishingError(str(exc)) from exc


__all__ = [
    "SystemPluginPublicationWorkflow",
    "require_network_contract",
]

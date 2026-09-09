"""Verified publication workflows for Workspace and System Plugin releases."""

import asyncio
from pathlib import Path
from uuid import UUID

from grafy_core.application.plugin_releases import (
    PluginReleaseService,
    require_canonical_conversion_references,
    require_workspace_catalog_authority,
)
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import (
    PlatformPluginActor,
    PluginCatalogManifest,
    PluginExecutionPolicy,
    PluginNodeContract,
    PluginNodeHttpEgressContract,
    PluginReleaseError,
    PluginReleaseHeadConflictError,
)
from grafy_core.domain.plugin_selection import PluginReleaseSelection

from grafy_api.plugins.runtime.admission import (
    ReleaseExecutionAdmission,
    ReleaseExecutionRejection,
    ReleaseExecutionRoute,
)
from grafy_api.plugins.publication.oci import PluginOciImageBuilder
from grafy_api.plugins.publication.source import (
    PluginDirectoryPublisher,
    PluginPublishingError,
    VerifiedPluginCandidate,
)
from grafy_api.system_plugin_inventory import (
    SystemPluginInventory,
    SystemPluginInventoryError,
)


class PluginPublicationConflictError(RuntimeError):
    """The reviewed working copy or release head changed before publication."""


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


def render_plugin_capability_diff(
    previous: PluginCatalogManifest | None,
    proposed: PluginCatalogManifest,
) -> tuple[str, ...]:
    """Render security-relevant authority changes between two catalogs.

    Publication review surfaces this diff so adding ``network.egress``, a
    configured URL field, or flipping ``dynamic_destinations`` to true is a
    visible, reviewed release change.
    """

    changes: list[str] = []
    previous_nodes: dict[str, PluginNodeContract] = {}
    if previous is not None:
        previous_nodes = {
            f"{node.operator_id}@{node.operator_version}": node
            for node in previous.nodes
        }
    for node in proposed.nodes:
        key = f"{node.operator_id}@{node.operator_version}"
        existing = previous_nodes.pop(key, None)
        if existing is None:
            if node.required_capabilities:
                rendered = ", ".join(
                    capability.value for capability in node.required_capabilities
                )
                changes.append(f"new node {key} requests capabilities: {rendered}")
            if node.http_egress is not None:
                changes.append(_describe_http_egress(key, node.http_egress))
            continue
        previous_capabilities = set(existing.required_capabilities)
        proposed_capabilities = set(node.required_capabilities)
        for capability in sorted(
            proposed_capabilities - previous_capabilities,
            key=lambda value: value.value,
        ):
            changes.append(f"node {key} now requests {capability.value}")
        for capability in sorted(
            previous_capabilities - proposed_capabilities,
            key=lambda value: value.value,
        ):
            changes.append(f"node {key} no longer requests {capability.value}")
        _diff_http_egress(changes, key, existing.http_egress, node.http_egress)
    for key in sorted(previous_nodes):
        node = previous_nodes[key]
        if node.required_capabilities:
            rendered = ", ".join(
                capability.value for capability in node.required_capabilities
            )
            changes.append(f"removed node {key} previously requested: {rendered}")
    return tuple(changes)


def _diff_http_egress(
    changes: list[str],
    key: str,
    previous: PluginNodeHttpEgressContract | None,
    proposed: PluginNodeHttpEgressContract | None,
) -> None:
    if previous is None and proposed is None:
        return
    if previous is None:
        assert proposed is not None
        changes.append(f"node {key} now declares HTTP egress")
        changes.append(_describe_http_egress(key, proposed))
        return
    if proposed is None:
        changes.append(f"node {key} no longer declares HTTP egress")
        return
    previous_fields = set(previous.configured_inputs)
    proposed_fields = set(proposed.configured_inputs)
    for field_name in sorted(proposed_fields - previous_fields):
        changes.append(f"node {key} now declares configured URL field {field_name!r}")
    for field_name in sorted(previous_fields - proposed_fields):
        changes.append(
            f"node {key} no longer declares configured URL field {field_name!r}"
        )
    if previous.dynamic_destinations != proposed.dynamic_destinations:
        direction = "now" if proposed.dynamic_destinations else "no longer"
        changes.append(f"node {key} {direction} requests dynamic destinations")


def _describe_http_egress(
    key: str,
    http_egress: PluginNodeHttpEgressContract,
) -> str:
    parts: list[str] = []
    if http_egress.configured_inputs:
        rendered_fields = ", ".join(
            f"{field_name!r}" for field_name in http_egress.configured_inputs
        )
        parts.append(f"configured URL fields {rendered_fields}")
    if http_egress.dynamic_destinations:
        parts.append("dynamic destinations")
    if not parts:
        return f"node {key} declares an empty HTTP egress contract"
    return f"node {key} declares HTTP egress: " + ", ".join(parts)


class PluginPublicationWorkflow:
    """Verify, build, and append one immutable Plugin release."""

    def __init__(
        self,
        publisher: PluginDirectoryPublisher,
        image_builder: PluginOciImageBuilder,
        releases: PluginReleaseService,
        system_inventory: SystemPluginInventory,
    ) -> None:
        self._publisher = publisher
        self._image_builder = image_builder
        self._releases = releases
        self._system_inventory = system_inventory

    async def verify(
        self,
        directory: Path,
        *,
        expected_slug: str,
    ) -> VerifiedPluginCandidate:
        verified = await asyncio.to_thread(
            self._publisher.verify,
            directory,
            expected_slug=expected_slug,
        )
        try:
            require_workspace_catalog_authority(verified.catalog)
            require_canonical_conversion_references(verified.catalog)
            self._system_inventory.require_workspace_catalog_authority(verified.catalog)
            require_network_contract(verified.catalog)
        except (PluginReleaseError, SystemPluginInventoryError) as exc:
            raise PluginPublishingError(str(exc)) from exc
        return verified

    async def publish(
        self,
        *,
        workspace_id: UUID,
        directory: Path,
        expected_slug: str,
        published_by_user_id: UUID,
        reviewed_source_digest: str | None = None,
        reviewed_base_revision: int | None = None,
    ) -> InstalledPluginRelease:
        await self._releases.authorize_publisher(
            workspace_id,
            published_by_user_id,
        )
        verified = await self.verify(directory, expected_slug=expected_slug)
        source_digest = verified.source_digest
        if (
            reviewed_source_digest is not None
            and source_digest != reviewed_source_digest
        ):
            raise PluginPublicationConflictError(
                "Plugin working copy changed after review"
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
        try:
            return await self._releases.publish(
                workspace_id=workspace_id,
                catalog=verified.catalog,
                capabilities=verified.capabilities,
                source_archive=verified.source_archive,
                lock_digest=verified.lock_digest,
                runtime_profile=verified.runtime_profile,
                runtime_artifact=runtime_artifact,
                loader_target=verified.loader_target,
                published_by_user_id=published_by_user_id,
                expected_base_revision=reviewed_base_revision,
            )
        except PluginReleaseHeadConflictError as exc:
            raise PluginPublicationConflictError(str(exc)) from exc


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
            and decision is not ReleaseExecutionRoute.IN_PROCESS
        ):
            raise PluginPublishingError(
                f"System Plugin release {slug!r} revision {revision} requires an "
                "exact deployment host binding for its prospective selection "
                "generation before promotion"
            )
        return await self._releases.promote_system(
            slug=slug,
            revision=revision,
            platform_actor=platform_actor,
            expected_generation=candidate.expected_generation,
        )


__all__ = [
    "PluginPublicationConflictError",
    "PluginPublicationWorkflow",
    "SystemPluginPublicationWorkflow",
    "render_plugin_capability_diff",
    "require_network_contract",
]

"""Resolve persisted System selections into a verified deployment baseline."""

from grafy_core.domain.plugin_host_bindings import SystemHostPluginBinding
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
from grafy_core.domain.system_plugin_inventory import (
    SystemPluginInventory,
    SystemPluginInventoryEntry,
    SystemPluginInventoryError,
)
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from grafy_persistence import schema
from grafy_persistence.system_cutover import (
    SystemBaselineArtifactType,
    SystemBaselineManifest,
    SystemBaselineOperator,
    SystemBaselineRelease,
)


class SystemBaselineManifestGenerator:
    """Resolve static inventory entries to exact persisted System selections."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def generate(
        self,
        inventory: SystemPluginInventory,
        *,
        host_bindings: tuple[SystemHostPluginBinding, ...] | None = None,
    ) -> SystemBaselineManifest:
        async with self._sessions() as session:
            async with session.begin():
                selected_rows = (
                    await session.execute(
                        select(
                            PluginRelease,
                            PluginInstallation,
                            schema.plugin_release_selections.c.selected_revision,
                            schema.plugin_release_selections.c.generation,
                            schema.plugin_release_selections.c.lifecycle,
                        )
                        .join(
                            schema.plugin_release_selections,
                            schema.plugin_release_selections.c.selected_release_id
                            == schema.plugin_releases.c.id,
                        )
                        .join(
                            PluginInstallation,
                            and_(
                                schema.plugin_installations.c.release_id
                                == schema.plugin_releases.c.id,
                                schema.plugin_installations.c.scope
                                == schema.plugin_release_selections.c.scope,
                                schema.plugin_installations.c.workspace_id.is_not_distinct_from(
                                    schema.plugin_release_selections.c.workspace_id
                                ),
                            ),
                        )
                        .where(
                            schema.plugin_release_selections.c.scope
                            == PluginReleaseScope.SYSTEM,
                            schema.plugin_release_selections.c.lifecycle != "withdrawn",
                        )
                    )
                ).all()

                releases_by_slug = {row[0].slug: row for row in selected_rows}
                inventory_by_slug = {
                    plugin.slug: plugin for plugin in inventory.plugins
                }
                if set(releases_by_slug) != set(inventory_by_slug):
                    missing = sorted(set(inventory_by_slug) - set(releases_by_slug))
                    unexpected = sorted(set(releases_by_slug) - set(inventory_by_slug))
                    raise SystemPluginInventoryError(
                        "Enabled System selections do not exactly match the static "
                        f"inventory; missing={missing}, unexpected={unexpected}"
                    )

                bindings_by_slug = self._host_bindings_by_slug(
                    inventory,
                    host_bindings,
                )
                baseline_releases: list[SystemBaselineRelease] = []
                for slug in sorted(inventory_by_slug):
                    entry = inventory_by_slug[slug]
                    (
                        raw_release,
                        installation,
                        selected_revision,
                        generation,
                        _lifecycle,
                    ) = releases_by_slug[slug]
                    release = InstalledPluginRelease(
                        release=raw_release,
                        installation=installation,
                    )
                    inventory.require_catalog_authority(release.release.catalog)
                    await self._verify_release(
                        session,
                        entry,
                        release,
                        selected_revision=selected_revision,
                    )
                    binding = bindings_by_slug.get(slug)
                    if binding is not None:
                        mismatch = binding.release_mismatch(release)
                        if mismatch is not None:
                            raise SystemPluginInventoryError(
                                f"System host binding {slug!r} has a {mismatch} "
                                "mismatch"
                            )
                        if binding.selection_generation != generation:
                            raise SystemPluginInventoryError(
                                f"System host binding {slug!r} selection generation "
                                "does not match"
                            )
                        if binding.loader_target != entry.loader_target:
                            raise SystemPluginInventoryError(
                                f"System host binding {slug!r} loader target does "
                                "not match the static inventory"
                            )

                    runtime_artifact = release.release.runtime_artifact
                    if (
                        runtime_artifact is None
                        or release.release.runtime_image_digest is None
                    ):
                        raise SystemPluginInventoryError(
                            f"Selected System release {slug!r} has no retained OCI "
                            "artifact"
                        )
                    baseline_releases.append(
                        SystemBaselineRelease(
                            release_id=release.release.id,
                            slug=release.release.slug,
                            revision=release.release.revision,
                            selection_generation=generation,
                            source_digest=release.release.source_digest,
                            lock_digest=release.release.lock_digest,
                            descriptor_digest=release.release.descriptor.digest,
                            contract_digest=release.release.contract_digest,
                            capability_digest=release.release.capability_digest,
                            protocol_digest=release.release.protocol_digest,
                            profile_digest=release.release.profile_digest,
                            runtime_image_digest=release.release.runtime_image_digest,
                            runtime_archive_digest=runtime_artifact.archive_digest,
                            operators=tuple(
                                SystemBaselineOperator(
                                    operator_id=node.operator_id,
                                    operator_version=node.operator_version,
                                )
                                for node in sorted(
                                    release.release.catalog.nodes,
                                    key=lambda node: (
                                        node.operator_id,
                                        node.operator_version,
                                    ),
                                )
                            ),
                            artifact_types=tuple(
                                SystemBaselineArtifactType(
                                    artifact_type_id=artifact.key.id,
                                    schema_version=artifact.key.schema_version,
                                )
                                for artifact in sorted(
                                    release.release.catalog.artifact_types,
                                    key=lambda artifact: (
                                        artifact.key.id,
                                        artifact.key.schema_version,
                                    ),
                                )
                            ),
                        )
                    )
                return SystemBaselineManifest(releases=tuple(baseline_releases))

    def _host_bindings_by_slug(
        self,
        inventory: SystemPluginInventory,
        host_bindings: tuple[SystemHostPluginBinding, ...] | None,
    ) -> dict[str, SystemHostPluginBinding]:
        if host_bindings is None:
            return {}
        bindings_by_slug = {binding.slug: binding for binding in host_bindings}
        if len(bindings_by_slug) != len(host_bindings):
            raise SystemPluginInventoryError(
                "Exact System host bindings must have unique slugs"
            )
        expected = {
            plugin.slug
            for plugin in inventory.plugins
            if plugin.execution_policy is PluginExecutionPolicy.HOST_ELIGIBLE
        }
        if set(bindings_by_slug) != expected:
            missing = sorted(expected - set(bindings_by_slug))
            unexpected = sorted(set(bindings_by_slug) - expected)
            raise SystemPluginInventoryError(
                "Exact host bindings must cover every host-eligible inventory "
                f"entry and no isolated entry; missing={missing}, "
                f"unexpected={unexpected}"
            )
        return bindings_by_slug

    async def _verify_release(
        self,
        session: AsyncSession,
        entry: SystemPluginInventoryEntry,
        release: InstalledPluginRelease,
        *,
        selected_revision: int,
    ) -> None:
        if (
            release.installation.scope is not PluginReleaseScope.SYSTEM
            or release.installation.workspace_id is not None
            or release.release.slug != entry.slug
            or release.release.revision != selected_revision
        ):
            raise SystemPluginInventoryError(
                f"Selected System release {entry.slug!r} has inconsistent identity"
            )
        if release.release.catalog.slug != release.release.slug:
            raise SystemPluginInventoryError(
                f"Selected System release {entry.slug!r} catalog slug does not match"
            )
        if (
            plugin_contract_digest(release.release.catalog)
            != release.release.contract_digest
        ):
            raise SystemPluginInventoryError(
                f"Selected System release {entry.slug!r} contract digest does not "
                "match its catalog"
            )
        if release.descriptor_digest != release.release.descriptor.digest:
            raise SystemPluginInventoryError(
                f"Selected System release {entry.slug!r} descriptor digest does not "
                "match"
            )
        if release.installation.execution_policy is not entry.execution_policy:
            raise SystemPluginInventoryError(
                f"Selected System release {entry.slug!r} execution policy does not "
                "match the static inventory"
            )
        if release.release.capabilities.capabilities != entry.capabilities:
            raise SystemPluginInventoryError(
                f"Selected System release {entry.slug!r} capabilities do not match "
                "the static inventory"
            )
        if release.release.loader_target != entry.loader_target:
            raise SystemPluginInventoryError(
                f"Selected System release {entry.slug!r} loader target does not "
                "match the static inventory"
            )
        if release.release.runtime_artifact is None:
            raise SystemPluginInventoryError(
                f"Selected System release {entry.slug!r} has no retained OCI artifact"
            )
        if (
            release.release.runtime_image_digest
            != release.release.runtime_artifact.manifest_digest
        ):
            raise SystemPluginInventoryError(
                f"Selected System release {entry.slug!r} OCI digest does not match"
            )
        revoked = await session.scalar(
            select(schema.plugin_release_revocations.c.installation_id).where(
                schema.plugin_release_revocations.c.installation_id
                == release.installation.id
            )
        )
        if revoked is not None:
            raise SystemPluginInventoryError(
                f"Selected System release {entry.slug!r} is revoked"
            )

"""Static System Plugin inventory and exact baseline-manifest generation."""

from collections.abc import Iterable
from pathlib import Path, PurePosixPath
import tomllib
from typing import Annotated, ClassVar, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from grafy_core.canonical_conversions import CANONICAL_ARTIFACT_CONVERSIONS
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_releases import (
    PluginArtifactConversionContract,
    PluginCatalogManifest,
    PluginExecutionPolicy,
    PluginRelease,
    PluginReleaseScope,
    plugin_contract_digest,
)
from grafy_persistence import schema

from grafy_api.system_cutover import (
    SystemBaselineArtifactType,
    SystemBaselineManifest,
    SystemBaselineOperator,
    SystemBaselineRelease,
)
from grafy_api.system_host_bindings import SystemHostPluginBinding


SYSTEM_PLUGIN_SLUGS = frozenset(
    {
        "external.gis",
        "external.llm",
        "external.ocr",
        "external.sql",
    }
)
CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH = (
    Path(__file__).resolve().parents[4] / "plugins" / "system-plugins.toml"
)
SystemPluginIdentityPrefix = Annotated[
    str,
    Field(
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$",
        min_length=1,
        max_length=255,
    ),
]
_CANONICAL_CONVERSIONS_BY_KEY = {
    (contract.key.id, contract.key.version): contract
    for contract in (
        PluginArtifactConversionContract.from_conversion(conversion)
        for conversion in CANONICAL_ARTIFACT_CONVERSIONS
    )
}


class SystemPluginInventoryError(RuntimeError):
    """The platform inventory or selected releases are not a valid baseline."""


class _InventoryValue(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class SystemPluginInventoryEntry(_InventoryValue):
    """Static package metadata; never an exact deployment binding."""

    slug: str = Field(
        pattern=r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$",
        max_length=100,
    )
    project: str = Field(min_length=1, max_length=255)
    distribution_name: str = Field(
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=255,
    )
    loader_target: str = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$",
        max_length=512,
    )
    execution_policy: PluginExecutionPolicy
    capabilities: tuple[PluginRuntimeCapability, ...] = ()
    operator_prefixes: tuple[SystemPluginIdentityPrefix, ...] = Field(min_length=1)
    artifact_type_prefixes: tuple[SystemPluginIdentityPrefix, ...] = ()

    @field_validator("project")
    @classmethod
    def validate_project_path(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("System Plugin project must use POSIX separators")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise ValueError("System Plugin project must be a safe relative path")
        return value

    @field_validator("capabilities")
    @classmethod
    def normalize_capabilities(
        cls,
        value: tuple[PluginRuntimeCapability, ...],
    ) -> tuple[PluginRuntimeCapability, ...]:
        if len(value) != len(set(value)):
            raise ValueError("System Plugin capabilities must be unique")
        return tuple(sorted(value, key=lambda capability: capability.value))

    @field_validator(
        "operator_prefixes",
        "artifact_type_prefixes",
    )
    @classmethod
    def normalize_identity_prefixes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("System Plugin identity prefixes must be unique")
        return tuple(sorted(value))

    def require_catalog_authority(self, catalog: PluginCatalogManifest) -> None:
        """Require one System catalog to stay inside its inventory authority."""

        if catalog.slug != self.slug:
            raise SystemPluginInventoryError(
                f"System Plugin catalog {catalog.slug!r} does not match inventory "
                f"entry {self.slug!r}"
            )
        self._require_identities(
            "node",
            ((node.operator_id, None) for node in catalog.nodes),
            self.operator_prefixes,
        )
        self._require_identities(
            "artifact type",
            (
                (artifact.key.id, artifact.key.schema_version)
                for artifact in catalog.artifact_types
            ),
            self.artifact_type_prefixes,
        )
        for conversion in catalog.artifact_conversions:
            key = (conversion.key.id, conversion.key.version)
            canonical = _CANONICAL_CONVERSIONS_BY_KEY.get(key)
            if canonical != conversion:
                raise SystemPluginInventoryError(
                    f"System Plugin {self.slug!r} artifact conversion "
                    f"{conversion.key.id}@{conversion.key.version} is not an exact "
                    "deployment-owned canonical conversion"
                )

    def _require_identities(
        self,
        identity_kind: str,
        identities: Iterable[tuple[str, int | None]],
        prefixes: tuple[str, ...],
    ) -> None:
        for identity, version in identities:
            if any(_matches_identity_prefix(identity, prefix) for prefix in prefixes):
                continue
            rendered_version = "" if version is None else f"@{version}"
            raise SystemPluginInventoryError(
                f"System Plugin {self.slug!r} owned {identity_kind} "
                f"{identity}{rendered_version} is outside its allowlisted prefixes"
            )


class SystemPluginInventory(_InventoryValue):
    schema_version: int = Field(default=1, ge=1, le=1)
    plugins: tuple[SystemPluginInventoryEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_complete_collision_free_platform_inventory(self) -> Self:
        slugs = [plugin.slug for plugin in self.plugins]
        if len(slugs) != len(set(slugs)):
            raise ValueError("System Plugin inventory slugs must be unique")
        observed_slugs = frozenset(slugs)
        if observed_slugs != SYSTEM_PLUGIN_SLUGS:
            missing = sorted(SYSTEM_PLUGIN_SLUGS - observed_slugs)
            unexpected = sorted(observed_slugs - SYSTEM_PLUGIN_SLUGS)
            raise ValueError(
                "System Plugin inventory must exactly cover platform families; "
                f"missing={missing}, unexpected={unexpected}"
            )
        loader_targets = [plugin.loader_target for plugin in self.plugins]
        if len(loader_targets) != len(set(loader_targets)):
            raise ValueError("System Plugin inventory loader targets must be unique")
        if any(plugin.slug == "builtin.module" for plugin in self.plugins):
            raise ValueError("Graph Module operators are not System Plugins")
        prefix_groups = (
            tuple(
                (plugin.slug, prefix)
                for plugin in self.plugins
                for prefix in plugin.operator_prefixes
            ),
            tuple(
                (plugin.slug, prefix)
                for plugin in self.plugins
                for prefix in plugin.artifact_type_prefixes
            ),
        )
        for assignments in prefix_groups:
            prefix_owners: dict[str, str] = {}
            for slug, prefix in assignments:
                existing_owner = prefix_owners.setdefault(prefix, slug)
                if existing_owner != slug:
                    raise ValueError(
                        f"System Plugin identity prefix {prefix!r} is assigned "
                        f"to both {existing_owner!r} and {slug!r}"
                    )

        project_distributions: dict[str, str] = {}
        distribution_projects: dict[str, str] = {}
        for plugin in self.plugins:
            existing_distribution = project_distributions.setdefault(
                plugin.project,
                plugin.distribution_name,
            )
            if existing_distribution != plugin.distribution_name:
                raise ValueError(
                    f"System Plugin project {plugin.project!r} names multiple "
                    "distributions"
                )
            existing_project = distribution_projects.setdefault(
                plugin.distribution_name,
                plugin.project,
            )
            if existing_project != plugin.project:
                raise ValueError(
                    f"System Plugin distribution {plugin.distribution_name!r} "
                    "names multiple projects"
                )
        return self

    def entry_for(self, slug: str) -> SystemPluginInventoryEntry:
        for entry in self.plugins:
            if entry.slug == slug:
                return entry
        raise SystemPluginInventoryError(
            f"System Plugin {slug!r} is not present in the checked-in inventory"
        )

    def require_catalog_authority(self, catalog: PluginCatalogManifest) -> None:
        entry = self.entry_for(catalog.slug)
        entry.require_catalog_authority(catalog)
        operator_authorities = tuple(
            (plugin.slug, prefix)
            for plugin in self.plugins
            for prefix in plugin.operator_prefixes
        )
        artifact_type_authorities = tuple(
            (plugin.slug, prefix)
            for plugin in self.plugins
            for prefix in plugin.artifact_type_prefixes
        )
        for node in catalog.nodes:
            self._require_most_specific_owner(
                entry,
                "node",
                node.operator_id,
                operator_authorities,
            )
        for artifact in catalog.artifact_types:
            self._require_most_specific_owner(
                entry,
                "artifact type",
                artifact.key.id,
                artifact_type_authorities,
            )

    def _require_most_specific_owner(
        self,
        entry: SystemPluginInventoryEntry,
        identity_kind: str,
        identity: str,
        authorities: tuple[tuple[str, str], ...],
    ) -> None:
        matches = [
            (prefix.count("."), slug, prefix)
            for slug, prefix in authorities
            if _matches_identity_prefix(identity, prefix)
        ]
        if not matches:
            return
        _, owner_slug, owner_prefix = max(matches)
        if owner_slug == entry.slug:
            return
        raise SystemPluginInventoryError(
            f"System Plugin {entry.slug!r} owned {identity_kind} {identity!r} "
            f"falls under prefix {owner_prefix!r} delegated to {owner_slug!r}"
        )

    def require_workspace_catalog_authority(
        self,
        catalog: PluginCatalogManifest,
    ) -> None:
        """Reserve every checked-in System identity prefix from Workspaces."""

        operator_prefixes = tuple(
            prefix for entry in self.plugins for prefix in entry.operator_prefixes
        )
        artifact_type_prefixes = tuple(
            prefix for entry in self.plugins for prefix in entry.artifact_type_prefixes
        )
        self._require_workspace_identities(
            catalog,
            "node",
            (node.operator_id for node in catalog.nodes),
            operator_prefixes,
        )
        self._require_workspace_identities(
            catalog,
            "artifact type",
            (artifact.key.id for artifact in catalog.artifact_types),
            artifact_type_prefixes,
        )

    @staticmethod
    def _require_workspace_identities(
        catalog: PluginCatalogManifest,
        identity_kind: str,
        identities: Iterable[str],
        prefixes: tuple[str, ...],
    ) -> None:
        for identity in identities:
            reserved = next(
                (
                    prefix
                    for prefix in prefixes
                    if _matches_identity_prefix(identity, prefix)
                ),
                None,
            )
            if reserved is None:
                continue
            raise SystemPluginInventoryError(
                f"Workspace Plugin {catalog.slug!r} owned {identity_kind} "
                f"{identity!r} uses platform-reserved System prefix {reserved!r}"
            )


def _matches_identity_prefix(identity: str, prefix: str) -> bool:
    return identity == prefix or identity.startswith(f"{prefix}.")


def load_system_plugin_inventory(path: Path) -> SystemPluginInventory:
    """Read one checked-in inventory and validate the complete platform set."""

    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        return SystemPluginInventory.model_validate(document)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise SystemPluginInventoryError(
            f"Cannot load System Plugin inventory {path}: {exc}"
        ) from exc


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


__all__ = [
    "CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH",
    "SYSTEM_PLUGIN_SLUGS",
    "SystemBaselineManifestGenerator",
    "SystemPluginInventory",
    "SystemPluginInventoryEntry",
    "SystemPluginInventoryError",
    "load_system_plugin_inventory",
]

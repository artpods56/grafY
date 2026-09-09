"""Validated catalog policy, independent of HTTP response serialization."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal
from uuid import UUID

from grafy_core.canonical_conversions import CANONICAL_ARTIFACT_CONVERSIONS
from grafy_core.domain.module_library import Module, ModuleRelease
from grafy_core.domain.modules import GraphModuleDefinition
from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import (
    PluginArtifactConversionContract,
    PluginArtifactTypeContract,
    PluginNodeContract,
    PluginReleaseScope,
)
from grafy_core.domain.plugin_revocations import PluginReleaseRevocation
from grafy_core.domain.plugin_selection import (
    PluginFamilyLifecycle,
    PluginReleaseSelection,
)
from grafy_core.plugins import InstalledPlugin, NodeRegistration, PluginRegistry
from grafy_api.plugins.runtime.admission import (
    PluginNonRunnableReason,
    ReleaseExecutionAdmission,
    ReleaseExecutionRejection,
)

GRAPH_MODULE_PLUGIN_SLUG = "graph.module"


CatalogNonRunnableReason = (
    PluginNonRunnableReason
    | Literal[
        "deprecated",
        "withdrawn",
    ]
)


@dataclass(frozen=True, slots=True)
class PluginCatalogReleaseState:
    selection: PluginReleaseSelection | None = None
    revocation: PluginReleaseRevocation | None = None


@dataclass(frozen=True, slots=True)
class PluginReleaseReadiness:
    runnable: bool
    reason: CatalogNonRunnableReason | None = None
    detail: str | None = None


def plugin_release_readiness(
    release: InstalledPluginRelease,
    admission: ReleaseExecutionAdmission | None,
    *,
    state: PluginCatalogReleaseState | None = None,
    node_contract: PluginNodeContract | None = None,
) -> PluginReleaseReadiness:
    if admission is None:
        return PluginReleaseReadiness(
            runnable=False,
            reason="plugin_runtime_unavailable",
            detail="Plugin release execution is not configured for this workbench.",
        )
    release_state = state or PluginCatalogReleaseState()
    decision = admission.decide(
        release,
        node_contract=node_contract,
        selection=release_state.selection,
        revocation=release_state.revocation,
    )
    if isinstance(decision, ReleaseExecutionRejection) and decision.reason == "revoked":
        return PluginReleaseReadiness(
            runnable=False,
            reason=decision.reason,
            detail=decision.detail,
        )
    if (
        release_state.selection is not None
        and release_state.selection.lifecycle is not PluginFamilyLifecycle.PUBLISHED
    ):
        lifecycle = release_state.selection.lifecycle
        return PluginReleaseReadiness(
            runnable=False,
            reason=lifecycle.value,
            detail=(
                f"This Plugin family is {lifecycle.value} and unavailable for "
                "new insertion. Existing exact pins remain retained."
            ),
        )
    if isinstance(decision, ReleaseExecutionRejection):
        return PluginReleaseReadiness(
            runnable=False,
            reason=decision.reason,
            detail=decision.detail,
        )
    return PluginReleaseReadiness(runnable=True)


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    builtin_plugins: tuple[InstalledPlugin, ...]
    builtin_nodes: tuple[NodeRegistration, ...]
    module_boundary_nodes: tuple[NodeRegistration, ...]
    modules: tuple[tuple[Module, ModuleRelease, GraphModuleDefinition], ...]
    releases: tuple[InstalledPluginRelease, ...]
    artifact_contracts: tuple[PluginArtifactTypeContract, ...]
    conversions: tuple[PluginArtifactConversionContract, ...]
    node_readiness: Mapping[tuple[str, str, int], PluginReleaseReadiness]
    release_readiness: Mapping[str, PluginReleaseReadiness]

    @classmethod
    def from_registry(
        cls,
        registry: PluginRegistry,
        module_listing: list[tuple[Module, ModuleRelease, GraphModuleDefinition]],
        plugin_releases: list[InstalledPluginRelease],
        *,
        workspace_id: UUID,
        release_admission: ReleaseExecutionAdmission | None = None,
        plugin_release_states: Mapping[UUID, PluginCatalogReleaseState] | None = None,
    ) -> "CatalogSnapshot":
        release_states = plugin_release_states or {}
        system_releases = [
            release
            for release in plugin_releases
            if release.scope is PluginReleaseScope.SYSTEM
        ]
        workspace_releases = [
            release
            for release in plugin_releases
            if release.scope is PluginReleaseScope.WORKSPACE
        ]
        foreign_workspace_releases = [
            release
            for release in workspace_releases
            if release.workspace_id != workspace_id
        ]
        if foreign_workspace_releases:
            rendered = ", ".join(
                sorted(
                    f"{release.slug}@{release.revision} owned by {release.workspace_id}"
                    for release in foreign_workspace_releases
                )
            )
            raise ValueError(
                f"Workspace Plugin catalog received foreign releases: {rendered}"
            )
        system_slugs = {release.slug for release in system_releases}
        workspace_slugs = {release.slug for release in workspace_releases}
        if len(system_slugs) != len(system_releases):
            raise ValueError("System Plugin catalog contains duplicate current slugs")
        if len(workspace_slugs) != len(workspace_releases):
            raise ValueError(
                "Workspace Plugin catalog contains duplicate current slugs"
            )
        cross_scope_slugs = system_slugs & workspace_slugs
        if cross_scope_slugs:
            rendered = ", ".join(sorted(cross_scope_slugs))
            raise ValueError(
                f"Workspace Plugin releases conflict with System Plugins: {rendered}"
            )
        reserved_slugs = {GRAPH_MODULE_PLUGIN_SLUG} & (system_slugs | workspace_slugs)
        if reserved_slugs:
            raise ValueError(
                f"Plugin releases conflict with reserved Module provider: "
                f"{GRAPH_MODULE_PLUGIN_SLUG}"
            )

        installed_plugin_slugs = {
            plugin.slug
            for plugin in registry.plugins
            if plugin.slug != GRAPH_MODULE_PLUGIN_SLUG
        }
        plugin_slug_collisions = installed_plugin_slugs & (
            system_slugs | workspace_slugs
        )
        if plugin_slug_collisions:
            rendered = ", ".join(sorted(plugin_slug_collisions))
            raise ValueError(
                "Published Plugin releases conflict with reserved builtin "
                f"families: {rendered}"
            )

        host_nodes = {registration.key: registration for registration in registry.nodes}
        reserved_builtin_keys = {
            key
            for key, registration in host_nodes.items()
            if registration.plugin_slug != GRAPH_MODULE_PLUGIN_SLUG
        }
        release_node_owners: dict[tuple[str, int], InstalledPluginRelease] = {}
        for release in plugin_releases:
            for contract in release.catalog.nodes:
                key = (contract.operator_id, contract.operator_version)
                other_release = release_node_owners.get(key)
                if other_release is not None:
                    raise ValueError(
                        f"{release.scope.value.title()} Plugin {release.slug!r} "
                        f"operator {key[0]}@{key[1]} conflicts with "
                        f"{other_release.scope.value} Plugin "
                        f"{other_release.slug!r}"
                    )
                if key in reserved_builtin_keys:
                    host_registration = host_nodes[key]
                    raise ValueError(
                        f"{release.scope.value.title()} Plugin {release.slug!r} "
                        f"operator {key[0]}@{key[1]} conflicts with builtin "
                        f"{host_registration.plugin_slug!r}"
                    )
                release_node_owners[key] = release

        module_node_keys: set[tuple[str, int]] = set()
        for _, _, definition in module_listing:
            key = definition.reference.operator_key
            if (
                key in host_nodes
                or key in release_node_owners
                or key in module_node_keys
            ):
                raise ValueError(
                    f"Module {definition.reference.graph_id}@"
                    f"{definition.reference.revision} operator {key[0]}@{key[1]} "
                    "conflicts with another catalog entry"
                )
            module_node_keys.add(key)

        node_readiness = {
            (release.slug, contract.operator_id, contract.operator_version): (
                plugin_release_readiness(
                    release,
                    release_admission,
                    state=release_states.get(release.id),
                    node_contract=contract,
                )
            )
            for release in plugin_releases
            for contract in release.catalog.nodes
        }
        release_readiness: dict[str, PluginReleaseReadiness] = {}
        for release in plugin_releases:
            node_states = [
                node_readiness[
                    (release.slug, contract.operator_id, contract.operator_version)
                ]
                for contract in release.catalog.nodes
            ]
            if any(readiness.runnable for readiness in node_states):
                release_readiness[release.slug] = PluginReleaseReadiness(runnable=True)
            else:
                release_readiness[release.slug] = plugin_release_readiness(
                    release,
                    release_admission,
                    state=release_states.get(release.id),
                )
        declared_host_artifacts = {
            (spec.key.id, spec.key.schema_version): spec
            for spec in registry.declared_artifact_types
        }
        expanded_host_artifact_contracts = {
            (spec.key.id, spec.key.schema_version): (
                PluginArtifactTypeContract.from_spec(spec)
            )
            for spec in registry.artifact_types
        }
        seen_artifact_owners: dict[tuple[str, int], InstalledPluginRelease] = {}
        for release in plugin_releases:
            for release_contract in release.catalog.artifact_types:
                key = (release_contract.key.id, release_contract.key.schema_version)
                other_release = seen_artifact_owners.get(key)
                if other_release is not None:
                    raise ValueError(
                        f"{release.scope.value.title()} Plugin {release.slug!r} artifact "
                        f"type {key[0]}@{key[1]} conflicts with "
                        f"{other_release.scope.value} Plugin {other_release.slug!r}"
                    )
                installed = declared_host_artifacts.get(key)
                if installed is not None:
                    overlays_matching_host = (
                        release.scope is PluginReleaseScope.SYSTEM
                        and registry.artifact_type_owner(installed.key) == release.slug
                        and release_contract
                        == PluginArtifactTypeContract.from_spec(installed)
                    )
                    if not overlays_matching_host:
                        raise ValueError(
                            f"{release.scope.value.title()} Plugin {release.slug!r} "
                            f"artifact type {key[0]}@{key[1]} conflicts with the "
                            "host catalog contract"
                        )
                seen_artifact_owners[key] = release

        canonical_conversion_contracts = {
            (conversion.key.id, conversion.key.version): (
                PluginArtifactConversionContract.from_conversion(conversion)
            )
            for conversion in CANONICAL_ARTIFACT_CONVERSIONS
        }
        for release in plugin_releases:
            for contract in release.catalog.artifact_conversions:
                key = (contract.key.id, contract.key.version)
                canonical_contract = canonical_conversion_contracts.get(key)
                if canonical_contract is None:
                    raise ValueError(
                        f"{release.scope.value.title()} Plugin {release.slug!r} "
                        f"declares non-canonical artifact conversion "
                        f"{key[0]}@{key[1]}"
                    )
                if contract != canonical_contract:
                    raise ValueError(
                        f"{release.scope.value.title()} Plugin {release.slug!r} "
                        f"artifact conversion {key[0]}@{key[1]} conflicts with "
                        "the deployment-owned canonical contract"
                    )

        serialized_artifact_contracts: dict[
            tuple[str, int], PluginArtifactTypeContract
        ] = dict(expanded_host_artifact_contracts)
        for release in plugin_releases:
            for contract in (
                *release.catalog.artifact_types,
                *release.catalog.artifact_type_dependencies,
            ):
                key = (contract.key.id, contract.key.schema_version)
                installed = declared_host_artifacts.get(key)
                if installed is not None:
                    if contract != PluginArtifactTypeContract.from_spec(installed):
                        raise ValueError(
                            f"{release.scope.value.title()} Plugin {release.slug!r} "
                            f"artifact type {key[0]}@{key[1]} conflicts with the "
                            "host catalog contract"
                        )
                    continue
                existing = serialized_artifact_contracts.get(key)
                if existing is not None and existing != contract:
                    raise ValueError(
                        f"Plugin releases declare different exact contracts for "
                        f"artifact type {key[0]}@{key[1]}"
                    )
                serialized_artifact_contracts.setdefault(key, contract)

        builtin_nodes = [
            registration
            for registration in registry.nodes
            if registration.plugin_slug != GRAPH_MODULE_PLUGIN_SLUG
        ]
        module_boundary_nodes = [
            registration
            for registration in registry.nodes
            if registration.plugin_slug == GRAPH_MODULE_PLUGIN_SLUG
        ]
        builtin_plugins = [
            plugin
            for plugin in registry.plugins
            if plugin.slug != GRAPH_MODULE_PLUGIN_SLUG
        ]
        return cls(
            builtin_plugins=tuple(builtin_plugins),
            builtin_nodes=tuple(builtin_nodes),
            module_boundary_nodes=tuple(module_boundary_nodes),
            modules=tuple(module_listing),
            releases=tuple(plugin_releases),
            artifact_contracts=tuple(serialized_artifact_contracts.values()),
            conversions=tuple(canonical_conversion_contracts.values()),
            node_readiness=MappingProxyType(node_readiness),
            release_readiness=MappingProxyType(release_readiness),
        )

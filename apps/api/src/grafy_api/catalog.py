"""Validated catalog policy, independent of HTTP response serialization."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from grafy_core.artifacts import ArtifactTypeKey, ArtifactTypeSpec
from grafy_core.canonical_conversions import CANONICAL_ARTIFACT_CONVERSIONS
from grafy_core.conversions import ArtifactConversion
from grafy_core.domain.module_library import Module, ModuleRelease
from grafy_core.domain.modules import GraphModuleDefinition
from grafy_core.file_contracts import BUILTIN_FILE_FORMATS, build_extension_table
from grafy_core.plugins import InstalledPlugin, NodeRegistration, PluginRegistry

GRAPH_MODULE_PLUGIN_SLUG = "graph.module"

type ModuleListing = Sequence[tuple[Module, ModuleRelease, GraphModuleDefinition]]


def _by_key(
    specs: tuple[ArtifactTypeSpec, ...],
) -> dict[tuple[str, int], ArtifactTypeSpec]:
    return {(spec.key.id, spec.key.schema_version): spec for spec in specs}


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    """What this deployment can execute: the families it installed and its Modules.

    There is no per-entry readiness. A family that was not installed into the
    registry has no entry here at all, so every entry is executable by
    definition (ADR 0017).
    """

    builtin_plugins: tuple[InstalledPlugin, ...]
    builtin_nodes: tuple[NodeRegistration, ...]
    module_boundary_nodes: tuple[NodeRegistration, ...]
    modules: tuple[tuple[Module, ModuleRelease, GraphModuleDefinition], ...]
    artifact_types: tuple[ArtifactTypeSpec, ...]
    conversions: tuple[ArtifactConversion[Any, Any], ...]
    extension_claims: Mapping[str, ArtifactTypeKey]

    @classmethod
    def from_registry(
        cls,
        registry: PluginRegistry,
        module_listing: ModuleListing,
    ) -> "CatalogSnapshot":
        registered_keys = {registration.key for registration in registry.nodes}
        module_node_keys: set[tuple[str, int]] = set()
        for _, _, definition in module_listing:
            key = definition.reference.operator_key
            if key in registered_keys or key in module_node_keys:
                raise ValueError(
                    f"Module {definition.reference.graph_id}@"
                    f"{definition.reference.revision} operator {key[0]}@{key[1]} "
                    "conflicts with another catalog entry"
                )
            module_node_keys.add(key)

        # File formats are deployment-owned; an installed family that declares
        # the same exact type replaces the deployment's copy in place.
        serialized = _by_key(BUILTIN_FILE_FORMATS)
        serialized.update(_by_key(registry.artifact_types))
        extension_claims = build_extension_table(
            (spec.key, spec.extensions) for spec in serialized.values()
        )

        return cls(
            builtin_plugins=tuple(
                plugin
                for plugin in registry.plugins
                if plugin.slug != GRAPH_MODULE_PLUGIN_SLUG
            ),
            builtin_nodes=tuple(
                registration
                for registration in registry.nodes
                if registration.plugin_slug != GRAPH_MODULE_PLUGIN_SLUG
            ),
            module_boundary_nodes=tuple(
                registration
                for registration in registry.nodes
                if registration.plugin_slug == GRAPH_MODULE_PLUGIN_SLUG
            ),
            modules=tuple(module_listing),
            artifact_types=tuple(serialized.values()),
            conversions=tuple(CANONICAL_ARTIFACT_CONVERSIONS),
            extension_claims=extension_claims,
        )


__all__ = [
    "GRAPH_MODULE_PLUGIN_SLUG",
    "CatalogSnapshot",
    "ModuleListing",
]

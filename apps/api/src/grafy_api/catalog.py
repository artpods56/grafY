"""Validated catalog policy, independent of HTTP response serialization."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from grafy_core.artifacts import ArtifactTypeKey, ArtifactTypeSpec
from grafy_core.canonical_conversions import CANONICAL_ARTIFACT_CONVERSIONS
from grafy_core.conversions import ArtifactConversion
from grafy_core.file_contracts import BUILTIN_FILE_FORMATS, build_extension_table
from grafy_core.plugins import InstalledPlugin, NodeRegistration, PluginRegistry


def _by_key(
    specs: tuple[ArtifactTypeSpec, ...],
) -> dict[tuple[str, int], ArtifactTypeSpec]:
    return {(spec.key.id, spec.key.schema_version): spec for spec in specs}


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    """The node and artifact families installed by this deployment.

    There is no per-entry readiness. A family that was not installed into the
    registry has no entry here at all, so every entry is executable by
    definition (ADR 0017).
    """

    builtin_plugins: tuple[InstalledPlugin, ...]
    builtin_nodes: tuple[NodeRegistration, ...]
    artifact_types: tuple[ArtifactTypeSpec, ...]
    conversions: tuple[ArtifactConversion[Any, Any], ...]
    extension_claims: Mapping[str, ArtifactTypeKey]

    @classmethod
    def from_registry(
        cls,
        registry: PluginRegistry,
    ) -> "CatalogSnapshot":
        # File formats are deployment-owned; an installed family that declares
        # the same exact type replaces the deployment's copy in place.
        serialized = _by_key(BUILTIN_FILE_FORMATS)
        serialized.update(_by_key(registry.artifact_types))
        extension_claims = build_extension_table(
            (spec.key, spec.extensions) for spec in serialized.values()
        )

        return cls(
            builtin_plugins=tuple(registry.plugins),
            builtin_nodes=tuple(registry.nodes),
            artifact_types=tuple(serialized.values()),
            conversions=tuple(CANONICAL_ARTIFACT_CONVERSIONS),
            extension_claims=extension_claims,
        )


__all__ = [
    "CatalogSnapshot",
]

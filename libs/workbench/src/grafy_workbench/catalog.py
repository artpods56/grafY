"""App-owned builtin operators and their supported versions."""

from collections.abc import Iterable
from dataclasses import dataclass

from grafy_core.operators.modules import MODULE_BOUNDARY_REGISTRATIONS
from grafy_core.plugins import (
    Plugin,
    PluginRegistry,
    UnknownOperatorError,
)

from grafy_workbench.arithmetic import ARITHMETIC
from grafy_workbench.file import FILES
from grafy_workbench.image import IMAGES
from grafy_workbench.schema import SCHEMAS
from grafy_workbench.sequence import SEQUENCES
from grafy_workbench.table import TABLES
from grafy_workbench.text import TEXT


BUILTIN_FAMILIES: tuple[Plugin, ...] = (
    IMAGES,
    SEQUENCES,
    ARITHMETIC,
    TEXT,
    SCHEMAS,
    TABLES,
    FILES,
)

MODULE_BOUNDARY_OPERATOR_IDS = frozenset(
    registration.node_class.operator_id
    for registration in MODULE_BOUNDARY_REGISTRATIONS
)


def build_builtin_registry(
    families: Iterable[Plugin] = BUILTIN_FAMILIES,
) -> PluginRegistry:
    registry = PluginRegistry()
    registry.register_module_boundaries(MODULE_BOUNDARY_REGISTRATIONS)
    for plugin in families:
        registry.install(plugin)
    registry.freeze()
    return registry


@dataclass(frozen=True, slots=True)
class BuiltinNodeCatalog:
    """Resolves builtin operators in-process. Missing versions are compile errors."""

    registry: PluginRegistry
    build_digest: str

    @classmethod
    def load(
        cls,
        build_digest: str,
        families: Iterable[Plugin] = BUILTIN_FAMILIES,
    ) -> "BuiltinNodeCatalog":
        return cls(
            registry=build_builtin_registry(families),
            build_digest=build_digest,
        )

    def reserved_operator_ids(self) -> frozenset[str]:
        return frozenset(
            registration.node_class.operator_id
            for registration in self.registry.nodes
            if registration.plugin_slug != "graph.module"
        )

    def node_registration(self, operator_id: str, operator_version: int):
        try:
            return self.registry.node_registration(operator_id, operator_version)
        except UnknownOperatorError as exc:
            raise UnknownOperatorError(
                f"Unknown builtin operator {operator_id}@{operator_version}"
            ) from exc

    def build_node(self, operator_id: str, operator_version: int, context):
        try:
            return self.registry.build_node(
                operator_id,
                operator_version,
                context,
            )
        except UnknownOperatorError as exc:
            raise UnknownOperatorError(
                f"Unknown builtin operator {operator_id}@{operator_version}"
            ) from exc

"""Request-local immutable release contracts shared by preflight and compilation."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import PluginNodeContract, PluginReleaseScope
from grafy_api.execution.errors import GraphExecutionError
from grafy_api.execution.requests import RunNodeRequest


type ReleaseContractKey = tuple[UUID, PluginReleaseScope, str, int]


class ExactPluginReleaseLookup(Protocol):
    async def get_by_revision(
        self,
        workspace_id: UUID,
        slug: str,
        revision: int,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> InstalledPluginRelease | None: ...


@dataclass(frozen=True, slots=True)
class ResolvedPluginRelease:
    release: InstalledPluginRelease
    node_contracts: Mapping[tuple[str, int], PluginNodeContract] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "node_contracts",
            MappingProxyType(
                {
                    (contract.operator_id, contract.operator_version): contract
                    for contract in self.release.release.catalog.nodes
                }
            ),
        )

    def contract_for(self, node: RunNodeRequest) -> PluginNodeContract:
        contract = self.node_contracts.get((node.operator_id, node.operator_version))
        if contract is None:
            release = self.release
            raise GraphExecutionError(
                f"Node {node.id!r} pins {release.installation.scope.value.title()} Plugin "
                f"release {release.release.slug!r} revision {release.release.revision}, which does "
                f"not declare operator {node.operator_id}@{node.operator_version}"
            )
        return contract


async def resolve_plugin_release(
    workspace_id: UUID,
    node: RunNodeRequest,
    lookup: ExactPluginReleaseLookup,
    cache: dict[ReleaseContractKey, ResolvedPluginRelease],
) -> ResolvedPluginRelease:
    pin = node.plugin_release
    if pin is None:
        raise GraphExecutionError(
            f"Node {node.id!r} is a Plugin and must pin one exact "
            "Plugin release with scope, slug, and revision"
        )
    key = (workspace_id, pin.scope, pin.slug, pin.revision)
    resolved = cache.get(key)
    if resolved is None:
        release = await lookup.get_by_revision(
            workspace_id,
            pin.slug,
            pin.revision,
            scope=pin.scope,
        )
        if release is None:
            owner_context = (
                "in this workspace"
                if pin.scope is PluginReleaseScope.WORKSPACE
                else "in the System Plugin catalog"
            )
            raise GraphExecutionError(
                f"Node {node.id!r} pins {pin.scope.value.title()} Plugin "
                f"release {pin.slug!r} revision {pin.revision}, which does "
                f"not exist {owner_context}"
            )
        resolved = ResolvedPluginRelease(release)
        cache[key] = resolved
    return resolved

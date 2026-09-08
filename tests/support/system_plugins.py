"""Explicit Plugin registry fixtures with no production discovery fallback."""

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from grafy_core.domain.plugin_catalog import PluginCatalogRelease
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_identity import PluginExecutionPolicy
from grafy_core.domain.plugin_releases import (
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginRelease,
    PluginReleaseNamespace,
    PluginReleaseScope,
    PluginRuntimeArtifact,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_revocations import PluginReleaseRevocation
from grafy_core.domain.plugin_selection import PluginReleaseSelection
from grafy_core.domain.modules import (
    MODULE_INPUT_OPERATOR_ID,
    MODULE_OUTPUT_OPERATOR_ID,
)
from grafy_core.operators.modules import MODULE_BOUNDARY_REGISTRATIONS
from grafy_core.plugins import Plugin, PluginRegistry, UnknownOperatorError
from grafy_workbench import BUILTIN_FAMILIES

from grafy_api.system_host_bindings import LoadedSystemPlugin, SystemHostPluginBinding
from grafy_api.v1.models import ArtifactTypeBindingModel
from grafy_api.execution.requests import (
    RunInputPlugRequest,
    RunNodeRequest,
)


TEST_SYSTEM_PLUGINS: tuple[Plugin, ...] = BUILTIN_FAMILIES
TEST_BUILD_DIGEST = "a" * 64


def build_explicit_plugin_registry(
    plugins: Iterable[Plugin] = TEST_SYSTEM_PLUGINS,
) -> PluginRegistry:
    registry = PluginRegistry()
    registry.register_module_boundaries(MODULE_BOUNDARY_REGISTRATIONS)
    for plugin in plugins:
        registry.install(plugin)
    registry.freeze()
    return registry


class SelectedSystemReleaseLookup:
    """Exact persisted-release view for a synthetic selected deployment."""

    def __init__(
        self,
        releases: tuple[InstalledPluginRelease, ...],
        selections: tuple[PluginReleaseSelection, ...],
    ) -> None:
        self._releases = {
            (release.scope, release.slug, release.revision): release
            for release in releases
        }
        self._selections = {
            (selection.scope, selection.slug): selection for selection in selections
        }
        self.release_reads = 0

    async def get_by_revision(
        self,
        workspace_id: UUID,
        slug: str,
        revision: int,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> InstalledPluginRelease | None:
        self.release_reads += 1
        release = self._releases.get((scope, slug, revision))
        if release is None:
            return None
        expected_workspace_id = (
            workspace_id if scope is PluginReleaseScope.WORKSPACE else None
        )
        if release.workspace_id != expected_workspace_id:
            return None
        return release

    async def get_selection(
        self,
        workspace_id: UUID,
        slug: str,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> PluginReleaseSelection | None:
        del workspace_id
        return self._selections.get((scope, slug))

    async def list_catalog(self, workspace_id: UUID) -> list[PluginCatalogRelease]:
        releases = [
            *await self.list_current_system(),
            *await self.list_current(workspace_id),
        ]
        return [
            PluginCatalogRelease(
                release=release,
                selection=self._selections[(release.scope, release.slug)],
                revocation=None,
            )
            for release in releases
        ]

    async def list_current_system(self) -> list[InstalledPluginRelease]:
        return [
            release
            for release in self._releases.values()
            if release.scope is PluginReleaseScope.SYSTEM
        ]

    async def list_current(
        self,
        workspace_id: UUID,
    ) -> list[InstalledPluginRelease]:
        return [
            release
            for release in self._releases.values()
            if release.scope is PluginReleaseScope.WORKSPACE
            and release.workspace_id == workspace_id
        ]

    async def get_revocation(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None:
        del workspace_id, slug, revision
        return None

    async def get_system_revocation(
        self,
        *,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None:
        del slug, revision
        return None


@dataclass(frozen=True, slots=True)
class SelectedSystemPluginDeployment:
    registry: PluginRegistry
    releases: tuple[InstalledPluginRelease, ...]
    selections: tuple[PluginReleaseSelection, ...]
    host_bindings: tuple[SystemHostPluginBinding, ...]
    loaded_plugins: tuple[LoadedSystemPlugin, ...]
    release_lookup: SelectedSystemReleaseLookup

    def pin_node(self, node: RunNodeRequest) -> RunNodeRequest:
        try:
            registration = self.registry.node_registration(
                node.operator_id,
                node.operator_version,
            )
        except UnknownOperatorError:
            if node.operator_id.startswith("graph.module."):
                return node.model_copy(
                    update={"kind": "module", "plugin_release": None}
                )
            return node
        if registration.plugin_slug == "graph.module":
            return node.model_copy(update={"kind": "module", "plugin_release": None})
        return node.model_copy(
            update={
                "kind": "builtin",
                "plugin_release": None,
            }
        )


def synthetic_system_release(
    plugin: Plugin,
    *,
    revision: int = 1,
) -> InstalledPluginRelease:
    catalog = PluginCatalogManifest.from_plugin(plugin)
    capabilities = PluginCapabilityManifest(
        capabilities=tuple(
            dict.fromkeys(
                (
                    *plugin.capabilities,
                    *(
                        capability
                        for registration in plugin.nodes
                        for capability in registration.required_capabilities
                    ),
                )
            )
        )
    )
    runtime = PluginRuntimeArtifact(
        object_key=f"plugin-releases/system/{plugin.slug}/runtime.oci.tar",
        archive_digest="a" * 64,
        manifest_digest="b" * 64,
        config_digest="c" * 64,
    )
    release = PluginRelease(
        slug=catalog.slug,
        revision=revision,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key=f"plugin-releases/system/{plugin.slug}/source.tar.gz",
        source_digest="d" * 64,
        lock_digest="e" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
        runtime_image_digest=runtime.manifest_digest,
        runtime_artifact=runtime,
        published_by_platform_actor="test:system",
    )
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.SYSTEM,
                workspace_id=None,
            ),
            execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
            installed_by_user_id=None,
            installed_by_platform_actor="test:system",
        ),
    )


def build_selected_system_plugin_deployment(
    plugins: Iterable[Plugin] = TEST_SYSTEM_PLUGINS,
) -> SelectedSystemPluginDeployment:
    registry = build_explicit_plugin_registry(plugins)
    builtin_slugs = {family.slug for family in BUILTIN_FAMILIES}
    releases = tuple(
        synthetic_system_release(plugin)
        for plugin in plugins
        if plugin.slug not in builtin_slugs
    )
    selections = tuple(
        PluginReleaseSelection.from_release(release) for release in releases
    )
    return SelectedSystemPluginDeployment(
        registry=registry,
        releases=releases,
        selections=selections,
        host_bindings=(),
        loaded_plugins=(),
        release_lookup=SelectedSystemReleaseLookup(releases, selections),
    )


def pin_selected_system_nodes(
    nodes: Iterable[RunNodeRequest],
    plugins: Iterable[Plugin] = TEST_SYSTEM_PLUGINS,
) -> list[RunNodeRequest]:
    slugs_by_operator = {
        registration.key: plugin.slug
        for plugin in plugins
        for registration in plugin.nodes
    }
    pinned_nodes: list[RunNodeRequest] = []
    for node in nodes:
        if node.operator_id in {
            MODULE_INPUT_OPERATOR_ID,
            MODULE_OUTPUT_OPERATOR_ID,
        } or node.operator_id.startswith("graph.module."):
            pinned_nodes.append(
                node.model_copy(update={"kind": "module", "plugin_release": None})
            )
            continue
        slug = slugs_by_operator.get((node.operator_id, node.operator_version))
        if slug is None:
            pinned_nodes.append(node)
            continue
        pinned_nodes.append(
            node.model_copy(
                update={
                    "kind": "builtin",
                    "plugin_release": None,
                }
            )
        )
    return pinned_nodes


def selected_system_run_node(
    *,
    id: str,
    operator_id: str,
    operator_version: int,
    config: dict[str, object] | None = None,
    input_plugs: list[RunInputPlugRequest] | None = None,
    artifact_type_bindings: list[ArtifactTypeBindingModel] | None = None,
    plugin_slug: str | None = None,
    kind: str | None = None,
    plugin_release: object | None = None,
) -> RunNodeRequest:
    del plugin_slug, kind, plugin_release
    return RunNodeRequest(
        kind="builtin",
        id=id,
        operator_id=operator_id,
        operator_version=operator_version,
        config={} if config is None else config,
        input_plugs=[] if input_plugs is None else input_plugs,
        artifact_type_bindings=(
            [] if artifact_type_bindings is None else artifact_type_bindings
        ),
    )


__all__ = [
    "TEST_BUILD_DIGEST",
    "TEST_SYSTEM_PLUGINS",
    "SelectedSystemPluginDeployment",
    "SelectedSystemReleaseLookup",
    "build_explicit_plugin_registry",
    "build_selected_system_plugin_deployment",
    "pin_selected_system_nodes",
    "selected_system_run_node",
]

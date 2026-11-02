"""Explicit Plugin registry fixtures with no production discovery fallback."""

from collections.abc import Iterable

from grafy_core.domain.modules import (
    MODULE_INPUT_OPERATOR_ID,
    MODULE_OUTPUT_OPERATOR_ID,
)
from grafy_core.operators.modules import MODULE_BOUNDARY_REGISTRATIONS
from grafy_core.plugins import Plugin, PluginRegistry
from grafy_workbench import BUILTIN_FAMILIES
from grafy_plugin_image import IMAGES as IMAGE_OPERATORS
from grafy_plugin_table import TABLES as TABLE_OPERATORS
from tests.support.scenarios.sequences import SEQUENCES
from tests.support.scenarios.text_fixtures import TEXT_FIXTURES

from grafy_api.v1.models import ArtifactTypeBindingModel
from grafy_api.execution.requests import (
    RunInputPlugRequest,
    RunNodeRequest,
)

from tests.support.scenarios.arithmetic import ARITHMETIC_TEST_PLUGIN


# Plugins installed into the test registry as builtins purely to give engine
# tests richer fixtures than the shipped catalog needs. They are never published
# as Plugin releases and never reach production.
TEST_FIXTURE_PLUGINS: tuple[Plugin, ...] = (
    ARITHMETIC_TEST_PLUGIN,
    SEQUENCES,
    TEXT_FIXTURES,
    IMAGE_OPERATORS,
    TABLE_OPERATORS,
)
TEST_SYSTEM_PLUGINS: tuple[Plugin, ...] = (*BUILTIN_FAMILIES, *TEST_FIXTURE_PLUGINS)
TEST_BUILD_DIGEST = "a" * 64



def build_explicit_plugin_registry(
    plugins: Iterable[Plugin] = TEST_SYSTEM_PLUGINS,
) -> PluginRegistry:
    """Install test nodes as builtins, without publishing matching releases.

    A catalog must not also receive published releases for these same families;
    that describes a builtin/Plugin identity collision, not this test runtime.
    """
    registry = PluginRegistry()
    registry.register_module_boundaries(MODULE_BOUNDARY_REGISTRATIONS)
    for plugin in plugins:
        registry.install(plugin)
    registry.freeze()
    return registry


class SelectedSystemPluginDeployment:
    """Retired name kept as the registry-only view tests already pass around."""

    def __init__(self, registry: PluginRegistry) -> None:
        self.registry = registry

    def pin_node(self, node: RunNodeRequest) -> RunNodeRequest:
        return pin_selected_system_nodes([node])[0]


def build_selected_system_plugin_deployment(
    plugins: Iterable[Plugin] = TEST_SYSTEM_PLUGINS,
) -> SelectedSystemPluginDeployment:
    return SelectedSystemPluginDeployment(build_explicit_plugin_registry(plugins))


def pin_selected_system_nodes(
    nodes: Iterable[RunNodeRequest],
    plugins: Iterable[Plugin] = TEST_SYSTEM_PLUGINS,
) -> list[RunNodeRequest]:
    """Label each node with the origin its operator resolves to in this build.

    Operators come from installed families or from Graph Module boundaries; there is
    no third source, so a node that names neither is left untouched and the request
    model rejects it.
    """

    origin_by_operator = {
        registration.key: (
            "module" if plugin.slug == "graph.module" else "builtin"
        )
        for plugin in plugins
        for registration in plugin.nodes
    }
    pinned: list[RunNodeRequest] = []
    for node in nodes:
        if node.operator_id in {
            MODULE_INPUT_OPERATOR_ID,
            MODULE_OUTPUT_OPERATOR_ID,
        } or node.operator_id.startswith("graph.module."):
            pinned.append(node.model_copy(update={"kind": "module"}))
            continue
        origin = origin_by_operator.get((node.operator_id, node.operator_version))
        if origin is None:
            pinned.append(node)
            continue
        pinned.append(node.model_copy(update={"kind": origin}))
    return pinned


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
) -> RunNodeRequest:
    del plugin_slug, kind
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
    "TEST_FIXTURE_PLUGINS",
    "TEST_SYSTEM_PLUGINS",
    "build_explicit_plugin_registry",
    "build_selected_system_plugin_deployment",
    "pin_selected_system_nodes",
    "selected_system_run_node",
]

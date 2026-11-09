"""Explicit Plugin registry fixtures with no production discovery fallback."""

from collections.abc import Iterable

from grafy_core.plugins import Plugin, PluginRegistry
from grafy_workbench import BUILTIN_FAMILIES
from grafy_plugin_image import IMAGES as IMAGE_OPERATORS
from grafy_plugin_table import TABLES as TABLE_OPERATORS
from tests.support.scenarios.sequences import SEQUENCES
from tests.support.scenarios.arithmetic import ARITHMETIC_TEST_PLUGIN


# Plugins installed into the test registry as builtins purely to give engine
# tests richer fixtures than the shipped catalog needs. They are never published
# as Plugin releases and never reach production.
TEST_FIXTURE_PLUGINS: tuple[Plugin, ...] = (
    ARITHMETIC_TEST_PLUGIN,
    SEQUENCES,
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
    for plugin in plugins:
        registry.install(plugin)
    registry.freeze()
    return registry


class SelectedSystemPluginDeployment:
    """The registry-only view tests pass around."""

    def __init__(self, registry: PluginRegistry) -> None:
        self.registry = registry


def build_selected_system_plugin_deployment(
    plugins: Iterable[Plugin] = TEST_SYSTEM_PLUGINS,
) -> SelectedSystemPluginDeployment:
    return SelectedSystemPluginDeployment(build_explicit_plugin_registry(plugins))


__all__ = [
    "TEST_BUILD_DIGEST",
    "TEST_FIXTURE_PLUGINS",
    "TEST_SYSTEM_PLUGINS",
    "build_explicit_plugin_registry",
    "build_selected_system_plugin_deployment",
]

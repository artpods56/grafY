"""Emit a Plugin catalog contract from an isolated publisher subprocess.

The inspector runs inside the Plugin's own locked environment against an
unpacked source snapshot. Workspace publication uses the fixed
``grafy_plugin:PLUGIN`` target. System publication may supply only the exact
checked-in loader target that will be baked into the retained OCI image.
"""

from importlib import import_module
import sys

from pydantic import BaseModel, ConfigDict

from grafy_core.domain.plugin_releases import (
    PluginCapabilityManifest,
    PluginCatalogManifest,
)
from grafy_core.plugins import Plugin
from grafy_core.runtime.plugin_loader import (
    DEFAULT_PLUGIN_LOADER_TARGET,
    split_plugin_loader_target,
)


class InspectionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    catalog: PluginCatalogManifest
    capabilities: PluginCapabilityManifest


def inspect_plugin(
    loader_target: str = DEFAULT_PLUGIN_LOADER_TARGET,
) -> InspectionResult:
    module_name, attribute_name = split_plugin_loader_target(loader_target)
    module = import_module(module_name)
    plugin = getattr(module, attribute_name, None)
    if not isinstance(plugin, Plugin):
        raise SystemExit(
            "The installed project must export a grafy_core Plugin from "
            f"the exact loader target {loader_target!r}"
        )
    return InspectionResult(
        catalog=PluginCatalogManifest.from_plugin(plugin),
        capabilities=PluginCapabilityManifest(capabilities=plugin.capabilities),
    )


def main() -> None:
    if len(sys.argv) > 2:
        raise SystemExit(
            "usage: python -m grafy_core.plugin_inspector [LOADER_TARGET]"
        )
    loader_target = (
        DEFAULT_PLUGIN_LOADER_TARGET if len(sys.argv) == 1 else sys.argv[1]
    )
    print(inspect_plugin(loader_target).model_dump_json())


if __name__ == "__main__":
    main()

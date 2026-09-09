"""Inventory file loading and compatibility exports for shared contracts."""

import tomllib
from pathlib import Path

from grafy_core.domain.system_plugin_inventory import (
    SYSTEM_PLUGIN_SLUGS as SYSTEM_PLUGIN_SLUGS,
)
from grafy_core.domain.system_plugin_inventory import (
    SystemPluginIdentityPrefix as SystemPluginIdentityPrefix,
)
from grafy_core.domain.system_plugin_inventory import (
    SystemPluginInventory as SystemPluginInventory,
)
from grafy_core.domain.system_plugin_inventory import (
    SystemPluginInventoryEntry as SystemPluginInventoryEntry,
)
from grafy_core.domain.system_plugin_inventory import (
    SystemPluginInventoryError as SystemPluginInventoryError,
)
from grafy_persistence.system_baseline import (
    SystemBaselineManifestGenerator as SystemBaselineManifestGenerator,
)
from pydantic import (
    ValidationError,
)

CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH = (
    Path(__file__).resolve().parents[4] / "plugins" / "system-plugins.toml"
)


def load_system_plugin_inventory(path: Path) -> SystemPluginInventory:
    """Read one checked-in inventory and validate the complete platform set."""

    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        return SystemPluginInventory.model_validate(document)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise SystemPluginInventoryError(
            f"Cannot load System Plugin inventory {path}: {exc}"
        ) from exc


__all__ = [
    "CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH",
    "SYSTEM_PLUGIN_SLUGS",
    "SystemBaselineManifestGenerator",
    "SystemPluginInventory",
    "SystemPluginInventoryEntry",
    "SystemPluginInventoryError",
    "load_system_plugin_inventory",
]

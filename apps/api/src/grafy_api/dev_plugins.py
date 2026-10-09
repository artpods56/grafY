"""Explicit development-only loading of unsandboxed local Plugins."""

import importlib
import logging
from collections.abc import Sequence
from pathlib import Path

from grafy_core.domain.plugin_catalog import PluginCatalogRelease
from grafy_core.domain.system_plugin_inventory import SystemPluginInventoryError
from grafy_core.plugins import Plugin

from grafy_api.system_plugin_inventory import (
    CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH,
    load_system_plugin_inventory,
)

logger = logging.getLogger(__name__)


class DevPluginError(RuntimeError):
    """A requested local Plugin could not be installed in the API process."""


def load_dev_plugins(
    entries: Sequence[str],
    *,
    inventory_path: Path = CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH,
) -> tuple[Plugin, ...]:
    plugins: list[Plugin] = []
    slugs: set[str] = set()
    inventory = None
    for entry in entries:
        if ":" in entry:
            loader_target = entry
        else:
            if inventory is None:
                inventory = load_system_plugin_inventory(inventory_path)
            try:
                loader_target = inventory.entry_for(entry).loader_target
            except SystemPluginInventoryError as exc:
                known = ", ".join(plugin.slug for plugin in inventory.plugins)
                raise DevPluginError(
                    f"Unknown dev Plugin slug {entry!r}; known slugs: {known}"
                ) from exc
        module_name, _, attribute = loader_target.partition(":")
        if not module_name or not attribute or ":" in attribute:
            raise DevPluginError(
                f"Invalid dev Plugin loader target {loader_target!r}; expected module:attribute"
            )
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            raise DevPluginError(
                f"Cannot import dev Plugin {entry!r} ({loader_target}); "
                "install it into the API environment with `uv sync --all-extras`"
            ) from exc
        try:
            value = getattr(module, attribute)
        except AttributeError as exc:
            raise DevPluginError(
                f"Dev Plugin {entry!r}: module {module_name!r} has no attribute {attribute!r}"
            ) from exc
        if not isinstance(value, Plugin):
            raise DevPluginError(
                f"Dev Plugin {entry!r} ({loader_target}) must be a Plugin, "
                f"got {type(value).__name__}"
            )
        if value.slug in slugs:
            raise DevPluginError(
                f"Duplicate dev Plugin slug {value.slug!r} from {entry!r}"
            )
        slugs.add(value.slug)
        plugins.append(value)
        logger.warning(
            "dev_plugin_loaded slug=%s loader_target=%s in_process=true sandboxed=false",
            value.slug,
            loader_target,
        )
    return tuple(plugins)


def without_shadowed_releases(
    entries: Sequence[PluginCatalogRelease], slugs: frozenset[str]
) -> list[PluginCatalogRelease]:
    """Hide catalog releases whose slug is supplied by a local dev Plugin."""
    return [entry for entry in entries if entry.release.release.slug not in slugs]

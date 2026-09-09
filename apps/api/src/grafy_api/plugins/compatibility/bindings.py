"""Host-registry compatibility validation and binding-model exports."""

from grafy_core.domain.plugin_host_bindings import (
    LoadedSystemPlugin as LoadedSystemPlugin,
)
from grafy_core.domain.plugin_host_bindings import (
    SystemHostPluginBinding as SystemHostPluginBinding,
)
from grafy_core.plugins import PluginRegistry, UnknownOperatorError


class SystemHostBindingError(RuntimeError):
    """A declared host binding does not match the loaded host registry."""


def validate_system_host_bindings(
    bindings: tuple[SystemHostPluginBinding, ...],
    loaded_plugins: tuple[LoadedSystemPlugin, ...],
    registry: PluginRegistry,
) -> None:
    """Fail composition when a binding differs from the loaded implementation."""

    slugs = [binding.slug for binding in bindings]
    if len(slugs) != len(set(slugs)):
        raise SystemHostBindingError(
            "A deployment can bind only one selected System release per slug"
        )
    loaded_by_slug = {plugin.slug: plugin for plugin in loaded_plugins}
    if len(loaded_by_slug) != len(loaded_plugins):
        raise SystemHostBindingError(
            "Loaded System Plugin manifests must have unique slugs"
        )
    if set(loaded_by_slug) != set(slugs):
        raise SystemHostBindingError(
            "Loaded System Plugin manifests must exactly cover the host bindings"
        )
    for binding in bindings:
        loaded = loaded_by_slug[binding.slug]
        if loaded.loader_target != binding.loader_target:
            raise SystemHostBindingError(
                f"System host binding {binding.slug!r} loader target does not "
                "match the loaded deployment manifest"
            )
        if loaded.host_build_digest != binding.host_build_digest:
            raise SystemHostBindingError(
                f"System host binding {binding.slug!r} build digest does not "
                "match the loaded deployment manifest"
            )
        declared_keys = {
            (contract.operator_id, contract.operator_version)
            for contract in binding.catalog.nodes
        }
        loaded_keys = {
            registration.key
            for registration in registry.nodes
            if registration.plugin_slug == binding.slug
        }
        if loaded_keys != declared_keys:
            raise SystemHostBindingError(
                f"System host binding {binding.slug!r} operators do not match "
                "the loaded host registry"
            )
        for contract in binding.catalog.nodes:
            try:
                registration = registry.node_registration(
                    contract.operator_id,
                    contract.operator_version,
                )
            except UnknownOperatorError as exc:
                raise SystemHostBindingError(
                    f"System host binding {binding.slug!r} requires missing "
                    f"operator {contract.operator_id}@{contract.operator_version}"
                ) from exc
            if registration.plugin_slug != binding.slug:
                raise SystemHostBindingError(
                    f"System host binding {binding.slug!r} operator "
                    f"{contract.operator_id}@{contract.operator_version} is owned "
                    f"by loaded Plugin {registration.plugin_slug!r}"
                )
            loaded_contract = type(contract).from_registration(registration)
            if loaded_contract != contract:
                raise SystemHostBindingError(
                    f"System host binding {binding.slug!r} operator contract "
                    f"{contract.operator_id}@{contract.operator_version} does not "
                    "match the loaded host implementation"
                )


__all__ = [
    "LoadedSystemPlugin",
    "SystemHostBindingError",
    "SystemHostPluginBinding",
    "validate_system_host_bindings",
]

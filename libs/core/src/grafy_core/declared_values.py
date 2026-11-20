"""Value classes noted before a node contract is derived.

A node class derives its ports when the class body runs. That is often before
``ArtifactValues`` exists. ``Plugin.register`` and the built-in file and raster
declarations note the class here first. Noting the same class and key again is
a no-op. Noting the same class for a different key fails.
"""

from grafy_core.artifacts import ArtifactTypeKey

_keys: dict[type[object], ArtifactTypeKey] = {}


def note_declaration(value_type: type[object], key: ArtifactTypeKey) -> None:
    existing = _keys.get(value_type)
    if existing is None:
        _keys[value_type] = key
        return
    if existing == key:
        return
    raise ValueError(
        f"Artifact value class {value_type.__module__}.{value_type.__qualname__} "
        "is declared for both "
        f"{existing.id}@{existing.schema_version} and "
        f"{key.id}@{key.schema_version}"
    )


def declared_key(value_type: type[object]) -> ArtifactTypeKey | None:
    return _keys.get(value_type)

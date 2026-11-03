"""Per-node implementation identity (ADR 0020, issue #194).

A node's implementation identity answers one question: would this node's *code*
compute differently now? It is the operator id and version, a digest of the
static import closure of the node's implementation module inside its own family
package, that family's locked third-party dependency versions, and a
deployment-wide execution epoch. `grafy_core` is outside the closure: a core
change that alters node outputs bumps an artifact schema version or the epoch.

Nothing here imports or executes a family module. The closure is read from the
AST, so catalog load pays only for parsing source files and one `uv.lock`.
"""

import ast
import hashlib
import importlib.util
import json
import tomllib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Final, cast

from grafy_core.domain.graph_documents import GraphNode
from grafy_core.plugins import PluginRegistry

#: Deployment-wide epoch. Bump it by hand to invalidate every stored result.
EXECUTION_EPOCH: Final[str] = "1"

__all__ = [
    "EXECUTION_EPOCH",
    "RegistryImplementationDigests",
    "family_project_name",
    "implementation_digest",
    "import_closure",
    "import_closure_digest",
    "locked_dependency_versions",
]


def _family_root(top_level: str) -> Path:
    """The source directory of a family package, without importing it."""
    try:
        spec = importlib.util.find_spec(top_level)
    except (ImportError, ValueError):
        spec = None
    if spec is None or not spec.submodule_search_locations:
        raise ModuleNotFoundError(
            f"Top-level package {top_level!r} was not found", name=top_level
        )
    locations: Iterator[str] = iter(spec.submodule_search_locations)
    first = next(locations, None)
    if first is None:
        raise ModuleNotFoundError(
            f"Top-level package {top_level!r} was not found", name=top_level
        )
    return Path(first)


def _module_source(root: Path, parts: tuple[str, ...]) -> tuple[Path, bool] | None:
    """Locate ``(path, is_package)`` for one dotted name inside the family root.

    ``None`` means the name has no file in the family: it is stdlib, third
    party, another family, or a plain attribute imported from a package.
    """
    if len(parts) == 1:
        package_init = root / "__init__.py"
        return (package_init, True) if package_init.is_file() else None
    leaf = parts[-1]
    module_file = root.joinpath(*parts[1:-1]) / f"{leaf}.py"
    if module_file.is_file():
        return (module_file, False)
    package_init = root.joinpath(*parts[1:]) / "__init__.py"
    if package_init.is_file():
        return (package_init, True)
    return None


def _static_imports(
    path: Path, *, parts: tuple[str, ...], is_package: bool, top_level: str
) -> tuple[tuple[str, ...], ...]:
    """Dotted names this file imports, as name parts, family-scoped.

    ``ast.walk`` covers the whole tree on purpose: imports inside functions,
    ``if TYPE_CHECKING:`` blocks and ``try/except`` bodies all count, because
    the point is that nothing the module can reach goes unnoticed.
    """
    tree = ast.parse(path.read_bytes(), filename=str(path))
    found: list[tuple[str, ...]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = tuple(alias.name.split("."))
                if target[0] == top_level:
                    found.append(target)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module is None:
                    continue
                base = tuple(node.module.split("."))
                if base[0] != top_level:
                    continue
                found.append(base)
                # ``from P import n``: n may itself be a module of the family.
                found.extend(base + (alias.name,) for alias in node.names)
            else:
                anchor = parts if is_package else parts[:-1]
                ascend = node.level - 1
                if ascend >= len(anchor):
                    continue  # escapes above the family root: never in-family
                if node.module is not None:
                    anchor = anchor + tuple(node.module.split("."))
                found.append(anchor)
                # ``from . import z`` / ``from .m import z``: z may be a submodule.
                found.extend(anchor + (alias.name,) for alias in node.names)
    return tuple(found)


def _closure_files(module_name: str) -> dict[str, Path]:
    """Map every family module in the static import closure to its source file.

    Ancestors are included because importing ``a.b.c`` runs ``a/__init__.py``
    and ``a/b/__init__.py``; the visited set makes import cycles terminate.
    """
    parts = tuple(module_name.split("."))
    top_level = parts[0]
    root = _family_root(top_level)
    if _module_source(root, parts) is None:
        raise ModuleNotFoundError(
            f"Module {module_name!r} has no source file in package {top_level!r}",
            name=module_name,
        )
    files: dict[str, Path] = {}
    queue: list[tuple[str, ...]] = [parts]
    seen: set[tuple[str, ...]] = set()
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        source = _module_source(root, current)
        if source is None:
            continue
        path, is_package = source
        files[".".join(current)] = path
        for depth in range(1, len(current)):
            queue.append(current[:depth])
        queue.extend(
            _static_imports(
                path, parts=current, is_package=is_package, top_level=top_level
            )
        )
    return files


def import_closure(module_name: str) -> frozenset[str]:
    """Dotted names in the static import closure of ``module_name``.

    The closure stays inside ``module_name``'s top-level package: stdlib,
    third-party packages, ``grafy_core`` and sibling families are never part
    of it. Names with no file inside the family are ignored, and every
    ancestor package ``__init__`` of an included module is included.
    """
    return frozenset(_closure_files(module_name))


def import_closure_digest(module_name: str) -> str:
    """sha256 hex over the source bytes of every module in the closure."""
    files = _closure_files(module_name)
    digest = hashlib.sha256()
    for name in sorted(files):
        file_digest = hashlib.sha256(files[name].read_bytes()).hexdigest()
        digest.update(f"{name}\0{file_digest}\n".encode("utf-8"))
    return digest.hexdigest()


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, dict):
        return cast("Mapping[str, object]", value)
    return None


def _entries(
    document: Mapping[str, object], key: str
) -> tuple[Mapping[str, object], ...]:
    raw = document.get(key)
    if not isinstance(raw, list):
        return ()
    return tuple(
        entry
        for item in cast("list[object]", raw)
        if (entry := _as_mapping(item)) is not None
    )


def _is_workspace_member(entry: Mapping[str, object]) -> bool:
    source = entry.get("source")
    if not isinstance(source, Mapping):
        return False
    return "editable" in source or "virtual" in source


def _dependency_name(entry: Mapping[str, object]) -> str | None:
    name = entry.get("name")
    return name if isinstance(name, str) else None


def _dependency_version(entry: Mapping[str, object]) -> str | None:
    version = entry.get("version")
    return version if isinstance(version, str) else None


def locked_dependency_versions(uv_lock: Path, project_name: str) -> tuple[str, ...]:
    """Sorted ``name==version`` strings for a project's locked third-party deps.

    The walk starts at the project's own ``dependencies`` (never
    ``dev-dependencies`` or optional groups) and follows the lock transitively.
    A package whose ``source`` carries ``editable`` or ``virtual`` is a
    workspace member: it is neither included nor walked through, so a family's
    identity never carries another family or a core change inside it.
    """
    document = tomllib.loads(uv_lock.read_text(encoding="utf-8"))
    by_name: dict[str, list[Mapping[str, object]]] = {}
    for entry in _entries(document, "package"):
        name = _dependency_name(entry)
        if name is not None:
            by_name.setdefault(name, []).append(entry)
    project_entries = by_name.get(project_name)
    if project_entries is None:
        raise KeyError(f"Project {project_name!r} is not a package in {uv_lock}")

    result: set[str] = set()
    visited: set[tuple[str, str | None]] = set()
    stack: list[Mapping[str, object]] = [
        dependency
        for project in project_entries
        for dependency in _entries(project, "dependencies")
    ]
    while stack:
        dependency = stack.pop()
        name = _dependency_name(dependency)
        if name is None:
            continue
        version = _dependency_version(dependency)
        if (name, version) in visited:
            continue
        visited.add((name, version))
        matched = False
        for entry in by_name.get(name, ()):
            entry_version = _dependency_version(entry)
            if version is not None and entry_version != version:
                continue
            if _is_workspace_member(entry):
                continue
            matched = True
            if entry_version is not None:
                result.add(f"{name}=={entry_version}")
            stack.extend(_entries(entry, "dependencies"))
        if version is not None and not matched:
            result.add(f"{name}=={version}")
    return tuple(sorted(result))


def family_project_name(module_name: str) -> str:
    """The lock name of the family owning a module (``grafy_plugin_gis`` -> ``grafy-plugin-gis``)."""
    return module_name.split(".")[0].replace("_", "-")


def _canonical_digest(
    *,
    operator_id: str,
    operator_version: int,
    closure_digest: str,
    dependencies: tuple[str, ...],
    execution_epoch: str,
) -> str:
    payload = {
        "operator": [operator_id, operator_version],
        "closure": closure_digest,
        "dependencies": list(dependencies),
        "epoch": execution_epoch,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def implementation_digest(
    *,
    operator_id: str,
    operator_version: int,
    module_name: str,
    uv_lock: Path,
    execution_epoch: str = EXECUTION_EPOCH,
) -> str:
    """The full implementation identity of one node, as a sha256 hex digest."""
    return _canonical_digest(
        operator_id=operator_id,
        operator_version=operator_version,
        closure_digest=import_closure_digest(module_name),
        dependencies=locked_dependency_versions(
            uv_lock, family_project_name(module_name)
        ),
        execution_epoch=execution_epoch,
    )


class RegistryImplementationDigests:
    """Implementation digests for a whole operator catalog, computed at load.

    Every closure and lock parse happens once up front (per module and per
    family project), which is what "at catalog load" means: fingerprinting a
    node then reads a cache. An operator missing from the mapping raises at
    lookup instead of silently receiving a default digest.
    """

    def __init__(
        self,
        modules: Mapping[tuple[str, int], str],
        *,
        uv_lock: Path,
        execution_epoch: str = EXECUTION_EPOCH,
    ) -> None:
        closure_digests: dict[str, str] = {}
        dependency_sets: dict[str, tuple[str, ...]] = {}
        self._digests: dict[tuple[str, int], str] = {}
        for (operator_id, operator_version), module_name in modules.items():
            if module_name not in closure_digests:
                closure_digests[module_name] = import_closure_digest(module_name)
            project_name = family_project_name(module_name)
            if project_name not in dependency_sets:
                dependency_sets[project_name] = locked_dependency_versions(
                    uv_lock, project_name
                )
            self._digests[(operator_id, operator_version)] = _canonical_digest(
                operator_id=operator_id,
                operator_version=operator_version,
                closure_digest=closure_digests[module_name],
                dependencies=dependency_sets[project_name],
                execution_epoch=execution_epoch,
            )

    @classmethod
    def from_registry(
        cls,
        registry: PluginRegistry,
        *,
        uv_lock: Path,
        execution_epoch: str = EXECUTION_EPOCH,
    ) -> "RegistryImplementationDigests":
        """Build the digests of every node a registry registers."""
        modules = {
            registration.key: registration.node_class.__module__
            for registration in registry.nodes
        }
        return cls(modules, uv_lock=uv_lock, execution_epoch=execution_epoch)

    def implementation_digest(self, node: GraphNode) -> str:
        key = (node.operator_id, node.operator_version)
        if key not in self._digests:
            raise KeyError(
                f"No implementation digest for operator "
                f"{node.operator_id}@{node.operator_version}"
            )
        return self._digests[key]

"""Node contract modules keep their use-case boundaries.

`grafy_core.nodes` re-exports the public port, context, and derivation
definitions. The leaves never import that facade. Derivation may import
ports. Ports and context import neither each other nor derivation.
"""

import ast
import importlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE_DIR = REPO_ROOT / "libs" / "core" / "src" / "grafy_core"

FACADE = "nodes"
SPLIT_MODULES = (
    "node_ports",
    "node_context",
    "node_derivation",
)
GRAFY_CORE_PREFIX = "grafy_core."
ALLOWED_EDGES: dict[str, frozenset[str]] = {
    "node_ports": frozenset(),
    "node_context": frozenset(),
    "node_derivation": frozenset({"node_ports"}),
}
EXPECTED_PRIVATE_DEFINITIONS: dict[str, frozenset[str]] = {
    "node_ports": frozenset(),
    "node_context": frozenset(),
    "node_derivation": frozenset(
        {
            "_concrete_type",
            "_is_sequence_origin",
            "_sequence_item_type",
            "_unwrap_optional",
        }
    ),
}


def _source(module: str) -> str:
    return (CORE_DIR / f"{module}.py").read_text(encoding="utf-8")


def _referenced_split_module(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        candidates = (alias.name for alias in node.names)
    elif isinstance(node, ast.ImportFrom):
        candidates = (node.module or "",)
    else:
        return None
    for candidate in candidates:
        if not candidate.startswith(GRAFY_CORE_PREFIX):
            continue
        referenced = candidate[len(GRAFY_CORE_PREFIX) :]
        if referenced in SPLIT_MODULES or referenced == FACADE:
            return referenced
    return None


def _imported_split_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        referenced = _referenced_split_module(node)
        if referenced is not None:
            modules.add(referenced)
    return modules


def _top_level_definitions(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.TypeAlias):
            target = node.name
            assert isinstance(target, ast.Name)
            names.append(target.id)
        elif isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names.extend(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
    return names


def _public_leaf_definitions() -> dict[str, str]:
    definitions: dict[str, str] = {}
    for module_name in SPLIT_MODULES:
        for name in _top_level_definitions(ast.parse(_source(module_name))):
            if name.startswith("_"):
                continue
            assert name not in definitions, f"{name} defined in more than one leaf"
            definitions[name] = module_name
    return definitions


def test_leaves_use_only_the_allowed_dependency_edges() -> None:
    for module_name in SPLIT_MODULES:
        imported = _imported_split_modules(ast.parse(_source(module_name)))
        allowed = ALLOWED_EDGES[module_name]
        assert imported <= allowed, (
            f"{module_name} imports {sorted(imported - allowed)}; allowed edges "
            f"are {sorted(allowed)}"
        )


def test_facade_imports_every_split_module() -> None:
    imported = _imported_split_modules(ast.parse(_source(FACADE)))
    assert imported == set(SPLIT_MODULES)


def test_no_split_module_imports_a_private_name() -> None:
    for module_name in (FACADE, *SPLIT_MODULES):
        tree = ast.parse(_source(module_name))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            referenced = _referenced_split_module(node)
            if referenced is None:
                continue
            for alias in node.names:
                assert not alias.name.startswith("_"), (
                    f"{module_name} imports private {alias.name!r} from "
                    f"grafy_core.{referenced}"
                )


def test_private_helpers_live_only_in_their_own_module() -> None:
    for module_name in SPLIT_MODULES:
        defined = {
            name
            for name in _top_level_definitions(ast.parse(_source(module_name)))
            if name.startswith("_")
        }
        assert defined == EXPECTED_PRIVATE_DEFINITIONS[module_name]


def test_no_nested_function_definitions() -> None:
    for module_name in (FACADE, *SPLIT_MODULES):
        tree = ast.parse(_source(module_name))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            nested = [
                inner
                for inner in ast.walk(node)
                if inner is not node
                and isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
            assert not nested, (
                f"{module_name}.{node.name} nests {sorted(item.name for item in nested)}"
            )


def test_facade_reexports_use_the_same_public_names() -> None:
    tree = ast.parse(_source(FACADE))
    exported: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        referenced = _referenced_split_module(node)
        if referenced is None:
            continue
        assert referenced in SPLIT_MODULES
        for alias in node.names:
            assert alias.asname == alias.name, f"{alias.name} is not same-name"
            assert not alias.name.startswith("_")
            exported.add(alias.name)
    assert exported == set(_public_leaf_definitions())


def test_facade_exports_are_the_same_objects_as_the_leaf_definitions() -> None:
    facade = importlib.import_module(f"{GRAFY_CORE_PREFIX}{FACADE}")
    leaf_modules = {
        module_name: importlib.import_module(f"{GRAFY_CORE_PREFIX}{module_name}")
        for module_name in SPLIT_MODULES
    }
    for name, module_name in _public_leaf_definitions().items():
        leaf = leaf_modules[module_name]
        assert hasattr(facade, name), f"facade does not export {name}"
        assert getattr(facade, name) is getattr(leaf, name), (
            f"facade {name} is not the {module_name} object"
        )

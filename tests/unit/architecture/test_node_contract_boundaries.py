"""Node contract modules keep their use-case boundaries.

`grafy_core.nodes` re-exports the public port, context, and derivation
definitions. The leaves never import that facade. Derivation may import
ports. Ports and context import neither each other nor derivation.
"""

import ast
import importlib
from pathlib import Path

import pytest

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
            "_Described",
            "_Member",
            "_classify_member",
            "_concrete_type",
            "_declared_class",
            "_describe",
            "_describe_members",
            "_is_file_base",
            "_is_sequence_origin",
            "_markers",
            "_one_marker",
            "_plug_flags",
            "_ref_parameter",
            "_ref_port",
            "_required_key",
            "_required_type",
            "_sequence_item_type",
            "_value_port",
            "_without_none",
        }
    ),
}


def _source(module: str) -> str:
    return (CORE_DIR / f"{module}.py").read_text(encoding="utf-8")


def _referenced_split_modules(node: ast.AST) -> set[str]:
    candidates: list[str] = []
    if isinstance(node, ast.Import):
        candidates = [alias.name for alias in node.names]
    elif isinstance(node, ast.ImportFrom):
        if node.level == 1:
            module = f"grafy_core.{node.module}" if node.module else "grafy_core"
        elif node.level == 0:
            module = node.module or ""
        else:
            return set()
        candidates = (
            [f"{module}.{alias.name}" for alias in node.names]
            if module == "grafy_core"
            else [module]
        )
    return {
        candidate[len(GRAFY_CORE_PREFIX) :]
        for candidate in candidates
        if candidate.startswith(GRAFY_CORE_PREFIX)
        and candidate[len(GRAFY_CORE_PREFIX) :] in (FACADE, *SPLIT_MODULES)
    }


def _imported_split_modules(tree: ast.Module) -> set[str]:
    return {
        referenced
        for node in ast.walk(tree)
        for referenced in _referenced_split_modules(node)
    }


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from .nodes import Node", {"nodes"}),
        ("from . import nodes as facade", {"nodes"}),
        ("from grafy_core import nodes as facade", {"nodes"}),
        ("from .node_derivation import _concrete_type", {"node_derivation"}),
        ("from grafy_core.node_derivation import _concrete_type", {"node_derivation"}),
        (
            "import grafy_core.node_ports, grafy_core.nodes as facade",
            {"node_ports", "nodes"},
        ),
        (
            "from grafy_core import node_ports, nodes",
            {"node_ports", "nodes"},
        ),
        ("from grafy_core.artifacts import ArtifactRef", set[str]()),
        ("from unrelated import nodes", set[str]()),
        ("from ..nodes import Node", set[str]()),
    ],
)
def test_import_detection_covers_equivalent_spellings(
    source: str, expected: set[str]
) -> None:
    assert _imported_split_modules(ast.parse(source)) == expected


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
            referenced = _referenced_split_modules(node)
            if not referenced:
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
        referenced = _referenced_split_modules(node)
        if not referenced:
            continue
        assert referenced <= set(SPLIT_MODULES)
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

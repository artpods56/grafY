"""The in-memory adapters keep their facade, their direction, and their flatness."""

import ast
import inspect
from importlib.util import resolve_name
from pathlib import Path
from types import ModuleType

import pytest

import grafy_core.runtime.in_memory as in_memory
import grafy_core.runtime.in_memory.agents as agents_module
import grafy_core.runtime.in_memory.artifacts as artifacts_module
import grafy_core.runtime.in_memory.collaboration as collaboration_module
import grafy_core.runtime.in_memory.projects as projects_module
import grafy_core.runtime.in_memory.runs as runs_module
import grafy_core.runtime.in_memory.store as store_module
import grafy_core.runtime.in_memory.uow as uow_module
import grafy_core.runtime.in_memory.uploads as uploads_module
import grafy_core.runtime.in_memory.workspace_packs as workspace_packs_module
from grafy_core.runtime.in_memory import InMemoryDataStore, InMemoryUnitOfWork

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE = "grafy_core.runtime.in_memory"
PACKAGE_ROOT = REPO_ROOT / "libs/core/src/grafy_core/runtime/in_memory"
MONOLITH = REPO_ROOT / "libs/core/src/grafy_core/runtime/in_memory.py"

STORE = "store"
UNIT_OF_WORK = "uow"
REPOSITORIES = (
    "agents",
    "artifacts",
    "collaboration",
    "projects",
    "runs",
    "uploads",
    "workspace_packs",
)
# Imports flow downwards only: facade -> unit of work -> repositories -> store.
ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    STORE: frozenset(),
    **{name: frozenset({STORE}) for name in REPOSITORIES},
    UNIT_OF_WORK: frozenset({STORE, *REPOSITORIES}),
}
MODULES: dict[str, ModuleType] = {
    "agents": agents_module,
    "artifacts": artifacts_module,
    "collaboration": collaboration_module,
    "projects": projects_module,
    "runs": runs_module,
    "store": store_module,
    "uow": uow_module,
    "uploads": uploads_module,
    "workspace_packs": workspace_packs_module,
}
FACADE_CLASSES = (
    "InMemoryAgentConversationRepository",
    "InMemoryAgentTurnRepository",
    "InMemoryArtifactRepository",
    "InMemoryCollaborationRepository",
    "InMemoryDataStore",
    "InMemoryLibraryFolderRepository",
    "InMemoryProjectRepository",
    "InMemoryResultStoreRepository",
    "InMemoryRunRepository",
    "InMemoryUnitOfWork",
    "InMemoryUploadRepository",
    "InMemoryWorkspacePackRepository",
)


def _sibling_files() -> list[Path]:
    return sorted(p for p in PACKAGE_ROOT.glob("*.py") if p.stem != "__init__")


def _imported_modules(source: str, package: str) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, package)
            modules.append(module)
            modules.extend(f"{module}.{alias.name}" for alias in node.names)
    return modules


def _package_imports(path: Path) -> list[str]:
    """Every module of this package the file reaches for, facade included."""
    prefix = f"{PACKAGE}."
    return [
        module
        for module in _imported_modules(path.read_text(), PACKAGE)
        if module == PACKAGE or module.startswith(prefix)
    ]


def _sibling(name: str) -> str:
    """Which module of the package an import names, aliases included."""
    return name.removeprefix(f"{PACKAGE}.").split(".")[0]


def _nested_defs(tree: ast.AST) -> list[int]:
    """Lines where a def sits inside another def. Lambdas do not count."""
    nested: list[int] = []

    def visit(node: ast.AST, depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                if depth:
                    nested.append(child.lineno)
                visit(child, depth + 1)
            else:
                visit(child, depth)

    visit(tree, 0)
    return nested


def test_the_in_memory_monolith_is_gone_and_the_package_is_present() -> None:
    assert not MONOLITH.exists()
    assert not MONOLITH.with_suffix(".pyc").exists()
    assert (PACKAGE_ROOT / "__init__.py").is_file()
    assert {path.stem for path in _sibling_files()} == set(MODULES)


@pytest.mark.parametrize("module", sorted(ALLOWED_IMPORTS))
def test_each_module_imports_only_the_neighbours_it_is_allowed(
    module: str,
) -> None:
    offenders = [
        sibling
        for name in _package_imports(PACKAGE_ROOT / f"{module}.py")
        # The facade is checked separately: no module may import through it.
        if name != PACKAGE
        and (sibling := _sibling(name)) not in ALLOWED_IMPORTS[module]
    ]
    assert offenders == []


def test_no_module_imports_through_the_package_facade() -> None:
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _sibling_files()
        if PACKAGE in _package_imports(path)
    ]
    assert offenders == []


def test_the_in_memory_modules_define_no_nested_functions() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT).as_posix()}:{line}"
        for path in [PACKAGE_ROOT / "__init__.py", *_sibling_files()]
        for line in _nested_defs(ast.parse(path.read_text()))
    ]
    assert offenders == []


def test_the_facade_exports_the_objects_the_modules_define() -> None:
    defined: dict[str, type] = {}
    for module in MODULES.values():
        for name, value in vars(module).items():
            if name.startswith("_") or not inspect.isclass(value):
                continue
            if inspect.getmodule(value) is module:
                defined[name] = value

    assert set(FACADE_CLASSES) <= set(defined)
    assert set(defined) <= set(in_memory.__all__)
    for name, value in defined.items():
        assert getattr(in_memory, name) is value
    assert InMemoryDataStore is in_memory.InMemoryDataStore
    assert InMemoryUnitOfWork is uow_module.InMemoryUnitOfWork

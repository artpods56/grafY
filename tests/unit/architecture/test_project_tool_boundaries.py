import ast
from importlib import import_module
from importlib.util import resolve_name
from pathlib import Path

import pytest

AGENTS_ROOT = Path(__file__).resolve().parents[3] / "apps/api/src/grafy_api/agents"
DEPENDENCIES: dict[str, set[str]] = {
    "project_tools": {
        "project_context",
        "tool_ports",
        "tool_arguments",
        "tool_views",
        "turns",
    },
    "project_context": {"tool_ports", "tool_views"},
    "tool_ports": set(),
    "tool_arguments": set(),
    "tool_views": set(),
}


@pytest.mark.parametrize("name", DEPENDENCIES)
def test_project_tool_import_directions(name: str) -> None:
    tree = ast.parse((AGENTS_ROOT / f"{name}.py").read_text())
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, "grafy_api.agents")
            modules.append(module)
            modules.extend(f"{module}.{alias.name}" for alias in node.names)

    for module in modules:
        assert not module.startswith("grafy_api.v1"), module
        assert ".routes" not in module, module
        for target in (*DEPENDENCIES, "turns"):
            prefix = f"grafy_api.agents.{target}"
            if module == prefix or module.startswith(f"{prefix}."):
                assert target in DEPENDENCIES[name], (name, module)


@pytest.mark.parametrize("name", DEPENDENCIES)
def test_project_tool_definitions_are_not_nested(name: str) -> None:
    tree = ast.parse((AGENTS_ROOT / f"{name}.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for statement in node.body:
                assert not any(
                    isinstance(
                        child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
                    )
                    for child in ast.walk(statement)
                ), (name, node.name)


@pytest.mark.parametrize(
    ("module", "names"),
    [
        ("tool_ports", ("RegistryNodePorts",)),
        (
            "tool_arguments",
            ("ContentAddressedArguments", "ARGUMENT_ARTIFACT_NAMESPACE"),
        ),
        ("project_context", ("ProjectContextReader",)),
        (
            "tool_views",
            (
                "ArtifactModelViews",
                "MAX_VIEW_CHARS",
                "TABLE_VIEW_ROWS",
                "SEQUENCE_VIEW_ITEMS",
            ),
        ),
    ],
)
def test_project_tool_reexports_preserve_identity(
    module: str, names: tuple[str, ...]
) -> None:
    public = import_module("grafy_api.agents.project_tools")
    owner = import_module(f"grafy_api.agents.{module}")
    for name in names:
        assert getattr(public, name) is getattr(owner, name)

import ast
from hashlib import sha256
from importlib.util import resolve_name
from pathlib import Path
from typing import cast

import pytest
import tomllib

REPO_ROOT = Path(__file__).resolve().parents[3]

PUBLISHED_PLUGIN_FAMILIES = (
    "image",
    "table",
    "gis",
    "llm",
    "mistral",
    "python",
    "sql",
    "typesafe",
)
INSTALLED_PLUGIN_FAMILIES = tuple(
    family for family in PUBLISHED_PLUGIN_FAMILIES if family != "python"
)
WORKBENCH_FAMILIES = (
    "image",
    "value",
    "text",
    "schema",
    "table",
)
SYSTEM_PLUGIN_FAMILIES = PUBLISHED_PLUGIN_FAMILIES
SYSTEM_PLUGIN_IMPORTS = tuple(
    f"grafy_plugin_{family}" for family in PUBLISHED_PLUGIN_FAMILIES
)
LEGACY_NAMESPACE = "proto" + "type"


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


@pytest.mark.parametrize(
    ("source", "package", "expected"),
    [
        (
            "import grafy_api.v1.routes as routes",
            "grafy_api.execution",
            "grafy_api.v1.routes",
        ),
        (
            "from grafy_api.v1 import routes",
            "grafy_api.execution",
            "grafy_api.v1.routes",
        ),
        ("from ..v1 import routes", "grafy_api.execution", "grafy_api.v1.routes"),
        ("from .. import v1", "grafy_api.execution", "grafy_api.v1"),
        (
            "from ...v1.routes import artifacts",
            "grafy_api.plugins.runtime",
            "grafy_api.v1.routes.artifacts",
        ),
        (
            "from ..publication import source",
            "grafy_api.plugins.runtime",
            "grafy_api.plugins.publication.source",
        ),
        (
            "from . import views",
            "grafy_api.v1.routes.artifacts",
            "grafy_api.v1.routes.artifacts.views",
        ),
        ("from fastapi import Depends", "grafy_api.execution", "fastapi"),
    ],
)
def test_import_boundary_scan_resolves_python_import_forms(
    source: str, package: str, expected: str
) -> None:
    assert expected in _imported_modules(source, package)


def test_plugin_families_are_installed_from_the_workspace() -> None:
    root_document = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    root_project = cast(dict[str, object], root_document["project"])
    root_dependencies = cast(list[str], root_project["dependencies"])
    assert not root_project.get("optional-dependencies")
    for family in INSTALLED_PLUGIN_FAMILIES:
        assert f"grafy-plugin-{family}" in root_dependencies

    workspace = cast(dict[str, object], root_document["tool"])["uv"]
    workspace = cast(dict[str, object], workspace)["workspace"]
    workspace = cast(dict[str, object], workspace)
    members = cast(list[str], workspace["members"])
    excluded = cast(list[str], workspace["exclude"])
    for family in PUBLISHED_PLUGIN_FAMILIES:
        project_path = f"plugins/{family}"
        assert project_path in members
        assert project_path not in excluded
        plugin_document = tomllib.loads(
            (REPO_ROOT / project_path / "pyproject.toml").read_text()
        )
        plugin_sources = cast(
            dict[str, object], cast(dict[str, object], plugin_document["tool"])["uv"]
        )["sources"]
        assert cast(dict[str, object], plugin_sources)["grafy-core"] == {
            "workspace": True
        }
        assert not (REPO_ROOT / project_path / "wheels").exists()
        plugin_text = (REPO_ROOT / project_path / "pyproject.toml").read_text()
        assert "wheels/" not in plugin_text
        assert "SOURCE_DATE_EPOCH" not in plugin_text

    core_wheel = (
        REPO_ROOT
        / "tests/fixtures/plugin-notes/wheels/grafy_core-0.1.0-py3-none-any.whl"
    )
    assert sha256(core_wheel.read_bytes()).hexdigest() == (
        "bb1a53b247ef934625d985b3bdb1f3fbe6e726b0f002d77f60d452906475bcd2"
    )


def test_relational_dependencies_are_owned_by_persistence() -> None:
    api_document = tomllib.loads((REPO_ROOT / "apps/api/pyproject.toml").read_text())
    core_document = tomllib.loads((REPO_ROOT / "libs/core/pyproject.toml").read_text())
    persistence_document = tomllib.loads(
        (REPO_ROOT / "libs/persistence/pyproject.toml").read_text()
    )

    api_project = cast(dict[str, object], api_document["project"])
    core_project = cast(dict[str, object], core_document["project"])
    persistence_project = cast(dict[str, object], persistence_document["project"])
    api_dependencies = cast(list[str], api_project["dependencies"])
    core_dependencies = cast(list[str], core_project["dependencies"])
    persistence_dependencies = cast(list[str], persistence_project["dependencies"])

    assert "grafy-persistence" in api_dependencies
    for dependencies in (api_dependencies, core_dependencies):
        assert not any(
            requirement.startswith(("aiosqlite", "alembic", "sqlalchemy"))
            for requirement in dependencies
        )
    for dependency in ("aiosqlite", "alembic", "sqlalchemy"):
        assert any(
            requirement.startswith(dependency)
            for requirement in persistence_dependencies
        )


FORBIDDEN_SHARED_IMPORTS = (
    "grafy_api",
    "grafy_client",
    "grafy_core",
    "grafy_mcp",
    "grafy_persistence",
    "grafy_storage",
    "grafy_workbench",
    *SYSTEM_PLUGIN_IMPORTS,
)


def test_shared_configuration_is_a_leaf_package() -> None:
    """`grafy_shared` imports nothing from this workspace (ADR 0011).

    The point of the shared config package is that any layer, including `grafy_core`
    and `libs/storage`, can import its own configuration. One workspace import in the
    other direction makes that a cycle and the package stops being a leaf.
    """

    shared_root = REPO_ROOT / "libs/shared/src/grafy_shared"
    offenders: list[str] = []

    for path in shared_root.rglob("*.py"):
        package = ".".join(path.parent.relative_to(shared_root.parent).parts)
        for module in _imported_modules(path.read_text(), package):
            if any(
                module == forbidden or module.startswith(f"{forbidden}.")
                for forbidden in FORBIDDEN_SHARED_IMPORTS
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {module}")

    assert offenders == []


def test_configuration_does_not_build_the_runtime_it_configures() -> None:
    """The composed `Settings` never imports the plugin runtime (ADR 0011).

    `settings.py` used to construct `NetworkPolicy` and `PluginEgressBrokerPolicy`, so
    configuration imported the thing it configures and the runtime could not read its
    own section without a cycle. The runtime builds those objects with `from_config`.
    """

    api_source_root = REPO_ROOT / "apps/api/src"
    path = api_source_root / "grafy_api/settings.py"
    package = ".".join(path.parent.relative_to(api_source_root).parts)
    offenders = [
        module
        for module in _imported_modules(path.read_text(), package)
        if module == "grafy_api.plugins.runtime"
        or module.startswith("grafy_api.plugins.runtime.")
    ]

    assert offenders == []


def test_retained_python_sources_do_not_use_legacy_namespace() -> None:
    source_roots = (
        REPO_ROOT / "libs/core/src/grafy_core",
        REPO_ROOT / "libs/workbench/src/grafy_workbench",
        *(
            REPO_ROOT / "plugins" / family / "src" / f"grafy_plugin_{family}"
            for family in SYSTEM_PLUGIN_FAMILIES
        ),
        REPO_ROOT / "apps/api/src/grafy_api",
    )
    offenders: list[str] = []

    for source_root in source_roots:
        for path in source_root.rglob("*.py"):
            relative_path = path.relative_to(REPO_ROOT)
            if LEGACY_NAMESPACE in relative_path.as_posix().lower():
                offenders.append(str(relative_path))
                continue
            if LEGACY_NAMESPACE in path.read_text().lower():
                offenders.append(str(relative_path))

    assert offenders == []


def test_converged_operator_implementations_are_owned_by_the_application() -> None:
    for module in (
        "images.py",
        "prompts.py",
        "schemas.py",
        "sequences.py",
        "tables.py",
        "text.py",
    ):
        assert not (REPO_ROOT / "libs/core/src/grafy_core/operators" / module).exists()

    for family in WORKBENCH_FAMILIES:
        assert (REPO_ROOT / "libs/workbench/src/grafy_workbench" / family).is_dir()
        if family not in {"image", "table"}:
            assert not (REPO_ROOT / "plugins" / family).exists()

def test_plugin_families_do_not_import_http_or_api_modules() -> None:
    offenders: list[str] = []
    for family in PUBLISHED_PLUGIN_FAMILIES:
        source_root = REPO_ROOT / "plugins" / family / "src"
        for path in source_root.rglob("*.py"):
            package = ".".join(path.parent.relative_to(source_root).parts)
            for module in _imported_modules(path.read_text(), package):
                if module == "grafy_api" or module.startswith("grafy_api."):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {module}")
                if module == "fastapi" or module.startswith("fastapi."):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {module}")
    assert offenders == []


def test_execution_and_plugin_hosting_do_not_import_http_or_legacy_hosting() -> None:
    api_root = REPO_ROOT / "apps/api/src/grafy_api"
    offenders: list[str] = []
    for owner in (api_root / "execution", api_root / "plugins/runtime"):
        forbidden = [
            "grafy_api.v1.routes",
            "grafy_api.plugins.compatibility",
            "fastapi",
            "starlette",
        ]
        if owner.name == "runtime":
            forbidden.append("grafy_api.execution")
        for path in owner.rglob("*.py"):
            package = ".".join(path.parent.relative_to(api_root.parent).parts)
            for module in _imported_modules(path.read_text(), package):
                if any(
                    module == name or module.startswith(name + ".")
                    for name in forbidden
                ):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {module}")
    assert offenders == []


def test_application_owners_do_not_depend_on_route_modules() -> None:
    api_root = REPO_ROOT / "apps/api/src/grafy_api"
    paths = [
        *(api_root / "realtime").glob("*.py"),
        api_root / "graph_contracts.py",
        api_root / "artifact_availability.py",
        api_root / "node_secrets.py",
        api_root / "uploads.py",
    ]
    offenders: list[str] = []
    for path in paths:
        package = ".".join(path.parent.relative_to(api_root.parent).parts)
        for module in _imported_modules(path.read_text(), package):
            if module == "grafy_api.v1.routes" or module.startswith(
                "grafy_api.v1.routes."
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {module}")
            if path.name == "publish.py" and (
                module == "grafy_api.app_state"
                or module.startswith("grafy_api.app_state.")
            ):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}: request resource lookup"
                )
    assert offenders == []

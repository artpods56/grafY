import ast
from importlib.util import resolve_name
from hashlib import sha256
from pathlib import Path
import tomllib
from typing import cast

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]

PUBLISHED_PLUGIN_FAMILIES = (
    "gis",
    "llm",
    "ocr",
    "sql",
)
WORKBENCH_FAMILIES = (
    "arithmetic",
    "image",
    "sequence",
    "text",
    "schema",
    "table",
)
SYSTEM_PLUGIN_FAMILIES = PUBLISHED_PLUGIN_FAMILIES
SYSTEM_PLUGIN_IMPORTS = tuple(
    f"grafy_plugin_{family}" for family in PUBLISHED_PLUGIN_FAMILIES
)
FORBIDDEN_CORE_IMPORTS = (
    "aiosqlite",
    "alembic",
    "asyncpg",
    "fastapi",
    "grafy_api",
    "grafy_persistence",
    *SYSTEM_PLUGIN_IMPORTS,
    "grafy_storage",
    "sqlalchemy",
)
FORBIDDEN_PLUGIN_OUTER_LAYER_IMPORTS = (
    "grafy_api",
    "grafy_mcp",
    "grafy_persistence",
    "grafy_storage",
)
FORBIDDEN_API_PLUGIN_IMPORTS = (
    "grafy_plugin_gis",
    "grafy_plugin_llm",
    "grafy_plugin_ocr",
    "grafy_plugin_sql",
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
            "from ..compatibility import loader",
            "grafy_api.plugins.runtime",
            "grafy_api.plugins.compatibility.loader",
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


def test_optional_plugin_dependencies_are_not_owned_by_host_projects() -> None:
    root_document = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    api_document = tomllib.loads((REPO_ROOT / "apps/api/pyproject.toml").read_text())
    core_document = tomllib.loads((REPO_ROOT / "libs/core/pyproject.toml").read_text())

    root_project = cast(dict[str, object], root_document["project"])
    api_project = cast(dict[str, object], api_document["project"])
    core_project = cast(dict[str, object], core_document["project"])

    root_dependencies = cast(list[str], root_project["dependencies"])
    root_extras = cast(dict[str, list[str]], root_project["optional-dependencies"])
    api_dependencies = cast(list[str], api_project["dependencies"])
    core_dependencies = cast(list[str], core_project["dependencies"])

    assert not any(
        requirement.startswith("grafy-plugin-ocr") for requirement in root_dependencies
    )
    assert not any(
        requirement.startswith("grafy-plugin-llm") for requirement in root_dependencies
    )
    assert not any(
        requirement.startswith("grafy-plugin-sql") for requirement in root_dependencies
    )
    assert root_extras["ocr"] == ["grafy-plugin-ocr"]
    assert root_extras["llm"] == ["grafy-plugin-llm"]
    assert root_extras["sql"] == ["grafy-plugin-sql"]

    for dependencies in (api_dependencies, core_dependencies):
        assert not any(
            requirement.startswith(
                ("grafy-plugin-llm", "grafy-plugin-ocr", "grafy-plugin-sql")
            )
            for requirement in dependencies
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


def test_core_does_not_import_outer_layers_or_domain_adapters() -> None:
    core_root = REPO_ROOT / "libs/core/src/grafy_core"
    offenders: list[str] = []

    for path in core_root.rglob("*.py"):
        text = path.read_text()
        for forbidden in FORBIDDEN_CORE_IMPORTS:
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {forbidden}")

    assert offenders == []


def test_persistence_does_not_import_api_or_plugins() -> None:
    persistence_root = REPO_ROOT / "libs/persistence/src/grafy_persistence"
    offenders: list[str] = []

    for path in persistence_root.rglob("*.py"):
        text = path.read_text()
        for forbidden in ("grafy_api", *SYSTEM_PLUGIN_IMPORTS):
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {forbidden}")

    assert offenders == []


def test_api_host_does_not_import_optional_plugin_implementations() -> None:
    api_root = REPO_ROOT / "apps/api/src/grafy_api"
    offenders: list[str] = []

    for path in api_root.rglob("*.py"):
        text = path.read_text()
        for forbidden in FORBIDDEN_API_PLUGIN_IMPORTS:
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {forbidden}")

    assert offenders == []


def test_system_plugins_depend_on_core_not_outer_layers() -> None:
    offenders: list[str] = []

    for family in SYSTEM_PLUGIN_FAMILIES:
        plugin_root = REPO_ROOT / "plugins" / family / "src" / f"grafy_plugin_{family}"
        for path in plugin_root.rglob("*.py"):
            text = path.read_text()
            for forbidden in FORBIDDEN_PLUGIN_OUTER_LAYER_IMPORTS:
                if f"import {forbidden}" in text or f"from {forbidden}" in text:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {forbidden}")

    assert offenders == []


def test_system_plugins_do_not_import_other_plugin_implementations() -> None:
    offenders: list[str] = []

    for family in SYSTEM_PLUGIN_FAMILIES:
        plugin_root = REPO_ROOT / "plugins" / family / "src" / f"grafy_plugin_{family}"
        forbidden_imports = set(SYSTEM_PLUGIN_IMPORTS) - {f"grafy_plugin_{family}"}
        for path in plugin_root.rglob("*.py"):
            text = path.read_text()
            for forbidden in sorted(forbidden_imports):
                if f"import {forbidden}" in text or f"from {forbidden}" in text:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {forbidden}")

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
        "arithmetic.py",
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
        assert not (REPO_ROOT / "plugins" / family).exists()

    for family in PUBLISHED_PLUGIN_FAMILIES:
        project_root = REPO_ROOT / "plugins" / family
        document = tomllib.loads((project_root / "pyproject.toml").read_text())
        project = cast(dict[str, object], document["project"])

        assert (project_root / "uv.lock").is_file()
        assert "grafy-core==0.1.0" in cast(list[str], project["dependencies"])
        core_wheel = project_root / "wheels/grafy_core-0.1.0-py3-none-any.whl"
        assert sha256(core_wheel.read_bytes()).hexdigest() == (
            "03d5e7615c4d093a7ab3cc4a41c00ff834c29a725738e41763f2b03175ffd64d"
        )
        assert "workspace = true" not in (project_root / "pyproject.toml").read_text()


def test_host_eligible_plugins_carry_their_exact_build_backend() -> None:
    inventory = tomllib.loads((REPO_ROOT / "plugins/system-plugins.toml").read_text())

    for plugin in cast(list[dict[str, object]], inventory["plugins"]):
        if plugin["execution_policy"] != "host-eligible":
            continue
        project_root = REPO_ROOT.joinpath(*cast(str, plugin["project"]).split("/"))
        document = tomllib.loads((project_root / "pyproject.toml").read_text())
        build_system = cast(dict[str, object], document["build-system"])
        wheel = project_root / "wheels/setuptools-84.0.0-py3-none-any.whl"

        assert build_system["requires"] == ["setuptools==84.0.0"]
        assert sha256(wheel.read_bytes()).hexdigest() == (
            "51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670"
        )


def test_execution_and_plugin_hosting_do_not_import_http_or_legacy_hosting() -> None:
    api_root = REPO_ROOT / "apps/api/src/grafy_api"
    offenders: list[str] = []
    for owner in (api_root / "execution", api_root / "plugins/runtime"):
        forbidden = [
            "grafy_api.v1.routes",
            "grafy_api.plugins.compatibility",
            "grafy_api.system_plugin_loader",
            "grafy_api.system_plugin_deployment",
            "grafy_api.system_host_bindings",
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


def test_execution_http_models_preserve_public_request_and_event_identity() -> None:
    from grafy_api.execution import events, requests
    from grafy_api.v1.routes.executions import models

    for module, names in (
        (
            requests,
            ("RunRequest", "RunNodeRequest", "RunEdgeRequest", "PinnedOutputRequest"),
        ),
        (events, ("ExecutionStatusEvent", "NodeStatusEvent", "NodeProgressEvent")),
    ):
        for name in names:
            assert getattr(models, name) is getattr(module, name)


def test_application_owners_do_not_depend_on_route_modules() -> None:
    api_root = REPO_ROOT / "apps/api/src/grafy_api"
    paths = [
        *(api_root / "realtime").glob("*.py"),
        api_root / "graph_contracts.py",
        api_root / "artifact_availability.py",
        api_root / "node_secrets.py",
        api_root / "staged_uploads.py",
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


def test_workspace_transport_compatibility_exports_preserve_model_identity() -> None:
    from grafy_api.v1.routes.auth import models as legacy
    from grafy_api.v1.routes.workspaces import models

    for name in (
        "PersonalAccessTokenCreatedResponse",
        "PersonalAccessTokenCreateRequest",
        "PersonalAccessTokenResponse",
        "PersonalAccessTokenScope",
        "UserResponse",
        "WorkspaceCreateRequest",
        "WorkspaceInvitationCandidateRequest",
        "WorkspaceInvitationCandidateResponse",
        "WorkspaceInvitationCreateRequest",
        "WorkspaceInvitationOwnerResponse",
        "WorkspaceInvitationPersonResponse",
        "WorkspaceInvitationRecipientResponse",
        "WorkspaceInvitationWorkspaceResponse",
        "WorkspaceMemberResponse",
        "WorkspaceMemberRoleRequest",
        "WorkspaceResponse",
    ):
        assert getattr(legacy, name) is getattr(models, name)


def test_baseline_compatibility_exports_preserve_shared_contract_identity() -> None:
    from grafy_api import system_host_bindings, system_plugin_inventory
    from grafy_core.domain import (
        plugin_host_bindings,
        system_plugin_inventory as inventory_contracts,
    )
    from grafy_persistence.system_baseline import SystemBaselineManifestGenerator

    for name in ("LoadedSystemPlugin", "SystemHostPluginBinding"):
        assert getattr(system_host_bindings, name) is getattr(
            plugin_host_bindings, name
        )
    for name in (
        "SystemPluginInventory",
        "SystemPluginInventoryEntry",
        "SystemPluginInventoryError",
    ):
        assert getattr(system_plugin_inventory, name) is getattr(
            inventory_contracts, name
        )
    assert (
        system_plugin_inventory.SystemBaselineManifestGenerator
        is SystemBaselineManifestGenerator
    )


def test_historical_host_exports_resolve_to_compatibility_implementations() -> None:
    from importlib import import_module

    for old_name, owner in (
        ("system_plugin_loader", "loader"),
        ("system_plugin_deployment", "deployment"),
        ("system_host_bindings", "bindings"),
    ):
        legacy = import_module(f"grafy_api.{old_name}")
        implementation = import_module(f"grafy_api.plugins.compatibility.{owner}")
        assert legacy.__all__ == implementation.__all__
        for name in legacy.__all__:
            assert getattr(legacy, name) is getattr(implementation, name)

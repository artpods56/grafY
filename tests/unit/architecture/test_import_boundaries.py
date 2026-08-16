import tomllib
from pathlib import Path
from typing import cast


REPO_ROOT = Path(__file__).resolve().parents[3]

FORBIDDEN_CORE_IMPORTS = (
    "aiosqlite",
    "alembic",
    "asyncpg",
    "fastapi",
    "mistralai",
    "grafy_api",
    "grafy_persistence",
    "grafy_plugin_gis",
    "grafy_plugin_llm",
    "grafy_plugin_ocr",
    "grafy_plugin_sql",
    "grafy_storage",
    "sqlalchemy",
)
FORBIDDEN_OCR_PLUGIN_IMPORTS = (
    "grafy_api",
    "grafy_storage",
)
FORBIDDEN_LLM_PLUGIN_IMPORTS = FORBIDDEN_OCR_PLUGIN_IMPORTS
FORBIDDEN_API_PLUGIN_IMPORTS = (
    "daytona",
    "mistralai",
    "pydantic_ai",
    "grafy_plugin_gis",
    "grafy_plugin_llm",
    "grafy_plugin_ocr",
    "grafy_plugin_sql",
)
FORBIDDEN_AGENT_OUTER_IMPORTS = (
    "daytona",
    "fastapi",
    "grafy_agent_worker",
    "grafy_api",
    "grafy_persistence",
    "grafy_storage",
    "uvicorn",
)
FORBIDDEN_MCP_IMPORTS = (
    "aiosqlite",
    "fastapi",
    "grafy_api",
    "grafy_persistence",
    "grafy_plugin_gis",
    "grafy_plugin_llm",
    "grafy_plugin_ocr",
    "grafy_plugin_sql",
    "grafy_storage",
    "sqlalchemy",
)
LEGACY_NAMESPACE = "proto" + "type"
API_ROUTE_AREAS = (
    "agent_authoring",
    "artifacts",
    "catalog",
    "executions",
    "node_secrets",
    "saved_graphs",
    "uploads",
    "auth",
    "workspaces",
    "collaboration",
)
API_SERVICE_AREAS = (
    "artifacts",
    "catalog",
    "executions",
    "node_secrets",
    "uploads",
)
API_ROUTE_STANDARD_FILES = (
    "__init__.py",
    "dependencies.py",
    "models.py",
    "views.py",
)


def test_api_routes_are_organized_as_capability_slices() -> None:
    routes_root = REPO_ROOT / "apps/api/src/grafy_api/v1/routes"

    assert {path.name for path in routes_root.glob("*.py")} == {"__init__.py"}
    for area in API_ROUTE_AREAS[:7]:
        area_root = routes_root / area
        assert area_root.is_dir()
        for module in API_ROUTE_STANDARD_FILES:
            assert (area_root / module).is_file()
    assert (routes_root / "agent_authoring" / "services.py").is_file()
    assert {path.name for path in (routes_root / "auth").glob("*.py")} == {
        "__init__.py",
        "abuse.py",
        "dependencies.py",
        "models.py",
        "services.py",
        "views.py",
    }
    assert {path.name for path in (routes_root / "workspaces").glob("*.py")} == {
        "__init__.py",
        "views.py",
    }
    assert {path.name for path in (routes_root / "collaboration").glob("*.py")} == {
        "__init__.py",
        "dependencies.py",
        "hub.py",
        "models.py",
        "publish.py",
        "views.py",
    }
    for area in API_SERVICE_AREAS:
        assert (routes_root / area / "services.py").is_file()


def test_mistral_sdk_dependency_is_owned_by_optional_plugins() -> None:
    root_document = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    api_document = tomllib.loads((REPO_ROOT / "apps/api/pyproject.toml").read_text())
    core_document = tomllib.loads((REPO_ROOT / "libs/core/pyproject.toml").read_text())
    plugin_document = tomllib.loads(
        (REPO_ROOT / "plugins/ocr/pyproject.toml").read_text()
    )
    llm_plugin_document = tomllib.loads(
        (REPO_ROOT / "plugins/llm/pyproject.toml").read_text()
    )

    root_project = cast(dict[str, object], root_document["project"])
    api_project = cast(dict[str, object], api_document["project"])
    core_project = cast(dict[str, object], core_document["project"])
    plugin_project = cast(dict[str, object], plugin_document["project"])
    llm_plugin_project = cast(dict[str, object], llm_plugin_document["project"])

    root_dependencies = cast(list[str], root_project["dependencies"])
    root_extras = cast(dict[str, list[str]], root_project["optional-dependencies"])
    api_dependencies = cast(list[str], api_project["dependencies"])
    core_dependencies = cast(list[str], core_project["dependencies"])
    plugin_dependencies = cast(list[str], plugin_project["dependencies"])
    llm_plugin_dependencies = cast(list[str], llm_plugin_project["dependencies"])

    assert not any(
        requirement.startswith("grafy-plugin-ocr") for requirement in root_dependencies
    )
    assert not any(
        requirement.startswith("grafy-plugin-llm") for requirement in root_dependencies
    )
    assert not any(
        requirement.startswith("grafy-plugin-sql") for requirement in root_dependencies
    )
    assert not any(
        requirement.startswith("mistralai") for requirement in root_dependencies
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
        assert not any(
            requirement.startswith("mistralai") for requirement in dependencies
        )

    assert any(
        requirement.startswith("mistralai") for requirement in plugin_dependencies
    )
    assert any(
        requirement.startswith("mistralai") for requirement in llm_plugin_dependencies
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
        for forbidden in (
            "grafy_api",
            "grafy_plugin_gis",
            "grafy_plugin_llm",
            "grafy_plugin_ocr",
            "grafy_plugin_sql",
        ):
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


def test_agent_library_owns_tools_but_not_provider_or_host_adapters() -> None:
    agent_root = REPO_ROOT / "libs/agent/src/grafy_agent"
    offenders: list[str] = []

    for path in agent_root.rglob("*.py"):
        text = path.read_text()
        for forbidden in FORBIDDEN_AGENT_OUTER_IMPORTS:
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {forbidden}")

    assert offenders == []


def test_mcp_depends_on_the_http_api_contract_not_internal_packages() -> None:
    mcp_root = REPO_ROOT / "apps/mcp/src/grafy_mcp"
    offenders: list[str] = []

    for path in mcp_root.rglob("*.py"):
        text = path.read_text()
        for forbidden in FORBIDDEN_MCP_IMPORTS:
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {forbidden}")

    assert offenders == []


def test_ocr_plugin_depends_on_core_ports_not_outer_layers() -> None:
    plugin_root = REPO_ROOT / "plugins/ocr/src/grafy_plugin_ocr"
    offenders: list[str] = []

    for path in plugin_root.rglob("*.py"):
        text = path.read_text()
        for forbidden in FORBIDDEN_OCR_PLUGIN_IMPORTS:
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {forbidden}")

    assert offenders == []


def test_llm_plugin_depends_on_core_ports_not_outer_layers() -> None:
    plugin_root = REPO_ROOT / "plugins/llm/src/grafy_plugin_llm"
    offenders: list[str] = []

    for path in plugin_root.rglob("*.py"):
        text = path.read_text()
        for forbidden in FORBIDDEN_LLM_PLUGIN_IMPORTS:
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {forbidden}")

    assert offenders == []


def test_sql_plugin_depends_on_core_ports_not_outer_layers() -> None:
    plugin_root = REPO_ROOT / "plugins/sql/src/grafy_plugin_sql"
    offenders: list[str] = []

    for path in plugin_root.rglob("*.py"):
        text = path.read_text()
        for forbidden in FORBIDDEN_LLM_PLUGIN_IMPORTS:
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {forbidden}")

    assert offenders == []


def test_retained_python_sources_do_not_use_legacy_namespace() -> None:
    source_roots = (
        REPO_ROOT / "libs/agent/src/grafy_agent",
        REPO_ROOT / "libs/core/src/grafy_core",
        REPO_ROOT / "plugins/llm/src/grafy_plugin_llm",
        REPO_ROOT / "plugins/ocr/src/grafy_plugin_ocr",
        REPO_ROOT / "plugins/sql/src/grafy_plugin_sql",
        REPO_ROOT / "apps/api/src/grafy_api",
        REPO_ROOT / "apps/agent-worker/src/grafy_agent_worker",
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

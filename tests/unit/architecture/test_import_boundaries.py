import ast
from hashlib import sha256
from importlib.util import resolve_name
from pathlib import Path
import subprocess
import sys
from typing import cast
from zipfile import ZipFile

import pytest
import tomllib

from grafy_core.domain.plugin_releases import (
    PluginCatalogManifest,
    plugin_contract_digest,
)
from grafy_plugin_llm import LLM
from tests.support.plugin_contract_digests import (
    stored_contract_digest_before_canonicalization,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

PUBLISHED_PLUGIN_FAMILIES = (
    "image",
    "table",
    "gis",
    "llm",
    "mistral",
    "ocr",
    "python",
    "sql",
    "typesafe",
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
    assert not any(
        requirement.startswith("grafy-plugin-mistral")
        for requirement in root_dependencies
    )
    assert not any(
        requirement.startswith("grafy-plugin-typesafe")
        for requirement in root_dependencies
    )
    assert root_extras["ocr"] == ["grafy-plugin-ocr"]
    assert root_extras["llm"] == ["grafy-plugin-llm"]
    assert root_extras["mistral"] == ["grafy-plugin-mistral"]
    assert root_extras["sql"] == ["grafy-plugin-sql"]
    assert root_extras["typesafe"] == ["grafy-plugin-typesafe"]

    for dependencies in (api_dependencies, core_dependencies):
        assert not any(
            requirement.startswith(
                (
                    "grafy-plugin-llm",
                    "grafy-plugin-mistral",
                    "grafy-plugin-ocr",
                    "grafy-plugin-sql",
                    "grafy-plugin-typesafe",
                )
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

    for family in PUBLISHED_PLUGIN_FAMILIES:
        project_root = REPO_ROOT / "plugins" / family
        document = tomllib.loads((project_root / "pyproject.toml").read_text())
        project = cast(dict[str, object], document["project"])

        assert (project_root / "uv.lock").is_file()
        assert "grafy-core==0.1.0" in cast(list[str], project["dependencies"])
        core_wheel = project_root / "wheels/grafy_core-0.1.0-py3-none-any.whl"
        assert sha256(core_wheel.read_bytes()).hexdigest() == (
            "1a98b285ca632ba44640aa85113d2894f3f847fab58cf8d18e1c5bca0113d1bb"
        )
        assert "workspace = true" not in (project_root / "pyproject.toml").read_text()


_GUEST_DIGEST_PROBE = """
import sys

sys.path.insert(0, sys.argv[1])

import grafy_core
from grafy_core.domain.plugin_releases import (
    PluginCatalogManifest,
    plugin_contract_digest,
    plugin_contract_digest_matches,
)

catalog = PluginCatalogManifest.model_validate_json(sys.stdin.read())
print(grafy_core.__file__)
print(plugin_contract_digest(catalog))
print(plugin_contract_digest_matches(catalog, sys.argv[2]))
"""


def test_vendored_sdk_wheels_accept_the_digest_the_host_stores() -> None:
    """Every vendored SDK wheel must canonicalize the catalog digest itself.

    The guest runtime hashes the catalog with the SDK wheel installed in its own
    image, so a wheel built before empty-default canonicalization rejects every
    release the host publishes now. The wheel is run, not grepped: the symbols
    being present says nothing about which fields the wheel's canonicalization
    drops, so a wheel built from a different field-role table would pass a
    source-text check and still reject the release the host just stored.
    """

    catalog = PluginCatalogManifest.from_plugin(LLM)
    payload = catalog.model_dump_json()
    canonical = plugin_contract_digest(catalog)
    historical = stored_contract_digest_before_canonicalization(catalog)
    assert historical != canonical

    wheels = sorted(REPO_ROOT.glob("*/**/wheels/grafy_core-*.whl"))
    assert len(wheels) >= len(PUBLISHED_PLUGIN_FAMILIES) + 1
    for wheel in wheels:
        guest = subprocess.run(
            [sys.executable, "-c", _GUEST_DIGEST_PROBE, str(wheel), historical],
            input=payload,
            capture_output=True,
            text=True,
        )
        assert guest.returncode == 0, f"{wheel}: {guest.stderr}"
        module_file, digest, accepts_historical = guest.stdout.splitlines()
        assert str(wheel) in module_file, module_file
        assert digest == canonical, wheel
        assert accepts_historical == "True", wheel


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


def _modules_in_wheel(wheel: Path) -> set[str]:
    with ZipFile(wheel) as archive:
        names = archive.namelist()

    modules: set[str] = set()
    for name in names:
        if not name.endswith(".py"):
            continue
        parts = name.removesuffix(".py").split("/")
        if parts[-1] == "__init__":
            parts.pop()
        if parts:
            modules.add(".".join(parts))
    return modules


def _imported_core_modules(source: str) -> set[str]:
    """Absolute ``grafy_core`` modules imported by one source file.

    Imported names are deliberately not expanded into attribute paths:
    ``from grafy_core.artifacts import ArtifactKind`` names one module and one
    symbol, and only the module belongs to the wheel's module list.
    """

    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return {
        module
        for module in modules
        if module == "grafy_core" or module.startswith("grafy_core.")
    }


def test_vendored_sdk_wheels_contain_every_module_their_plugins_import() -> None:
    """A Plugin resolves ``grafy_core`` from its committed vendored wheel.

    The monorepo copy under ``libs/core`` is not on the Plugin's path, so a
    stale wheel stays invisible until Plugin publication runs the candidate's
    tests inside the publisher sandbox. Run ``just sdk-wheel`` and commit the
    rebuilt wheel whenever ``libs/core`` gains a module a Plugin imports.
    """

    missing: list[str] = []
    for wheel_root in sorted((REPO_ROOT / "plugins").glob("*/wheels")):
        project = wheel_root.parent
        wheels = sorted(wheel_root.glob("grafy_core-*.whl"))
        assert len(wheels) <= 1, f"{project.name} vendors {len(wheels)} SDK wheels"
        if not wheels:
            continue

        available = _modules_in_wheel(wheels[0])
        for source in sorted((project / "src").rglob("*.py")):
            for module in sorted(_imported_core_modules(source.read_text())):
                if module not in available:
                    missing.append(
                        f"{project.name}: {module} (imported by {source.name})"
                    )

    assert not missing, (
        "Vendored SDK wheels are missing grafy_core modules their Plugins "
        "import. Run `just sdk-wheel` and commit the rebuilt wheels:\n  "
        + "\n  ".join(sorted(set(missing)))
    )

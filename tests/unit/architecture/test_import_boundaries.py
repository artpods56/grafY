import ast
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
)
INSTALLED_PLUGIN_FAMILIES = PUBLISHED_PLUGIN_FAMILIES
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
FORBIDDEN_PERSISTENCE_IMPORTS = ("grafy_api", *SYSTEM_PLUGIN_IMPORTS)
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
            "grafy_api.runs",
            "grafy_api.v1.routes",
        ),
        (
            "from grafy_api.v1 import routes",
            "grafy_api.runs",
            "grafy_api.v1.routes",
        ),
        ("from ..v1 import routes", "grafy_api.runs", "grafy_api.v1.routes"),
        ("from .. import v1", "grafy_api.runs", "grafy_api.v1"),
        (
            "from ...routes import artifacts",
            "grafy_api.v1.routes.catalog",
            "grafy_api.v1.routes.artifacts",
        ),
        (
            "from ..catalog import views",
            "grafy_api.v1.routes.catalog",
            "grafy_api.v1.routes.catalog.views",
        ),
        (
            "from . import views",
            "grafy_api.v1.routes.artifacts",
            "grafy_api.v1.routes.artifacts.views",
        ),
        ("from fastapi import Depends", "grafy_api.runs", "fastapi"),
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
    """`grafy_core` is the inner layer: no HTTP host, adapter, relational stack or family.

    The whole package, not only `grafy_core.kernel`: the kernel guard below covers the
    Project kernel, and an import that reaches an outer layer from anywhere else in
    core makes the domain untestable on its own and turns a host dependency into a
    cycle. `grafy_persistence` and `grafy_storage` are the adapters core defines ports
    for, `grafy_api` is the host, and a `grafy_plugin_*` family is application code the
    host installs (ADR 0007), so core may not name any of them. `sqlalchemy`,
    `alembic`, `aiosqlite` and `asyncpg` belong to persistence for the same reason
    `test_relational_dependencies_are_owned_by_persistence` keeps them out of its
    dependencies.

    Two transport names are deliberately absent. `pydantic` is how the domain models
    are written, and `httpx` appears once, in `grafy_core/egress.py`, because the egress
    authority has to build the transport it pins now that families run in-process
    (ADR 0017) — it dials nothing itself and stays the only such module.
    """

    core_root = REPO_ROOT / "libs/core/src/grafy_core"
    assert any(core_root.rglob("*.py"))
    offenders: list[str] = []

    for path in core_root.rglob("*.py"):
        package = ".".join(path.parent.relative_to(core_root.parents[1]).parts)
        for module in _imported_modules(path.read_text(), package):
            if any(
                module == forbidden or module.startswith(f"{forbidden}.")
                for forbidden in FORBIDDEN_CORE_IMPORTS
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {module}")

    assert offenders == []


def test_persistence_does_not_import_api_or_plugins() -> None:
    """The relational adapter reads the domain and is read by the host, never the reverse.

    `grafy_persistence` may import `grafy_core` (it maps domain records to rows) and the
    SQLAlchemy stack it owns. An import of `grafy_api` would make a schema depend on the
    HTTP host that serves it, and an import of a `grafy_plugin_*` family would put a
    node family's models inside the storage layer that only stores their digests; either
    one ends in a cycle through the host that installs the family.
    """

    persistence_root = REPO_ROOT / "libs/persistence/src/grafy_persistence"
    assert any(persistence_root.rglob("*.py"))
    offenders: list[str] = []

    for path in persistence_root.rglob("*.py"):
        package = ".".join(path.parent.relative_to(persistence_root.parents[1]).parts)
        for module in _imported_modules(path.read_text(), package):
            if any(
                module == forbidden or module.startswith(f"{forbidden}.")
                for forbidden in FORBIDDEN_PERSISTENCE_IMPORTS
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {module}")

    assert offenders == []


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
    """The composed `Settings` imports no application module at all (ADR 0011).

    `settings.py` used to construct `NetworkPolicy` and `PluginEgressBrokerPolicy`, so
    configuration imported the thing it configures and the runtime could not read its
    own section without a cycle. Every policy object is now built by the application
    from a plain section, which is what keeps configuration a leaf.
    """

    api_source_root = REPO_ROOT / "apps/api/src"
    path = api_source_root / "grafy_api/settings.py"
    package = ".".join(path.parent.relative_to(api_source_root).parts)
    offenders = [
        module
        for module in _imported_modules(path.read_text(), package)
        if module == "grafy_api" or module.startswith("grafy_api.")
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


FORBIDDEN_FAMILY_CONFIG_IMPORTS = ("grafy_shared",)


def test_system_plugin_implementations_do_not_import_shared_configuration() -> None:
    """A node family is configured by its host and never reads host configuration itself.

    `grafy_shared` is the operator's `GRAFY_*` surface, and only the composition root
    reads the composed `Settings` (ADR 0011, "Families share workspace dependencies":
    the composition root reads configuration and supplies the values runtime services
    need). A family that imported it would decide its own operator values instead of
    receiving them, which is the coupling ADR 0011 removed from `grafy_api/settings.py`,
    and it would act on values its host never passed it.

    The deleted version of this guard justified itself with the vendored wheels a Plugin
    sandbox resolved at runtime; those wheels are gone (ADR 0017), so the reason stated
    here is the one that still holds.
    """

    offenders: list[str] = []

    for family in SYSTEM_PLUGIN_FAMILIES:
        source_root = REPO_ROOT / "plugins" / family / "src"
        assert any((source_root / f"grafy_plugin_{family}").rglob("*.py"))
        for path in source_root.rglob("*.py"):
            package = ".".join(path.parent.relative_to(source_root).parts)
            for module in _imported_modules(path.read_text(), package):
                if any(
                    module == forbidden or module.startswith(f"{forbidden}.")
                    for forbidden in FORBIDDEN_FAMILY_CONFIG_IMPORTS
                ):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {module}")

    assert offenders == []


def test_system_plugins_do_not_import_other_plugin_implementations() -> None:
    """One node family never reaches into another family's implementation (ADR 0017).

    The composition root installs each family into the `PluginRegistry` from one static
    tuple, and every family keeps its own package and its own third-party dependencies
    (ADR 0017). A `grafy_plugin_x` module importing `grafy_plugin_y` installs a
    dependency the host was never told about, drags y's dependency set into x's image,
    and lets a deployment that installs one family silently acquire another's behaviour.
    """

    offenders: list[str] = []

    for family in SYSTEM_PLUGIN_FAMILIES:
        source_root = REPO_ROOT / "plugins" / family / "src"
        forbidden_imports = sorted(
            set(SYSTEM_PLUGIN_IMPORTS) - {f"grafy_plugin_{family}"}
        )
        for path in source_root.rglob("*.py"):
            package = ".".join(path.parent.relative_to(source_root).parts)
            for module in _imported_modules(path.read_text(), package):
                if any(
                    module == forbidden or module.startswith(f"{forbidden}.")
                    for forbidden in forbidden_imports
                ):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {module}")

    assert offenders == []


# Deliberately NOT restored: `test_system_plugins_depend_on_core_not_outer_layers`,
# deleted by 93063148 alongside the guards this file has been recovering, forbade a
# family importing `grafy_api`, `grafy_mcp`, `grafy_persistence`, `grafy_storage` or
# `grafy_workbench`. It fails today on exactly one module, and that module is a defect
# rather than a boundary worth reopening. `plugins/gis/src/grafy_plugin_gis/smoke.py`
# imports `grafy_storage.LocalFileObjectStore`, and it is not family code: its docstring
# says it exercises the installed family "without an API", and it plays the host itself —
# it builds `InMemoryUnitOfWork()` and `LocalFileObjectStore(root / "objects")` and
# injects both into the family's own ports (`RasterScanOutputWriter(storage=..., uow=...)`,
# `RasterScanResolver(storage=..., uow=...)`), and CI plus `docs/how-to-run-gis.md` run it
# as `-m grafy_plugin_gis.smoke`. Constructing an object store is composition-root work
# (ADR 0011), so the repair is to move that harness out of the family package to sit next
# to `scripts/smoke_workbench.py`, not to let families import storage. No guard ships for
# this boundary in the meantime and no exemption names that file: an exemption would turn
# a defect into policy, and the suite must not read as covering what it does not cover.


def test_run_runtime_does_not_import_http_or_route_modules() -> None:
    api_root = REPO_ROOT / "apps/api/src/grafy_api"
    offenders: list[str] = []
    forbidden = [
        "grafy_api.v1.routes",
        "grafy_api.plugins",
        "fastapi",
        "starlette",
    ]
    for path in (api_root / "runs").rglob("*.py"):
        package = ".".join(path.parent.relative_to(api_root.parent).parts)
        for module in _imported_modules(path.read_text(), package):
            if any(
                module == name or module.startswith(name + ".") for name in forbidden
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {module}")
    assert offenders == []


def test_application_owners_do_not_depend_on_route_modules() -> None:
    api_root = REPO_ROOT / "apps/api/src/grafy_api"
    paths = [
        *(api_root / "realtime").glob("*.py"),
        *(api_root / "agents").rglob("*.py"),
        api_root / "project_contracts.py",
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
            if module == "grafy_api.app_state" or module.startswith(
                "grafy_api.app_state."
            ):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}: request resource lookup"
                )
    assert offenders == []


def test_run_runtime_has_no_release_or_sandbox_dependency() -> None:
    owners = (
        "services/application.py",
        "services/composition.py",
        "runs/node_runner.py",
        "runs/contract.py",
        "runs/node_execution.py",
        "node_secrets.py",
    )
    root = REPO_ROOT / "apps/api/src/grafy_api"
    for owner in owners:
        path = root / owner
        package = "grafy_api." + str(Path(owner).parent).replace("/", ".")
        imports = _imported_modules(path.read_text(), package)
        assert not any(
            module.startswith(
                (
                    "grafy_api.plugins",
                    "grafy_api.execution.releases",
                    "grafy_core.runtime.plugin_",
                )
            )
            for module in imports
        ), f"{owner} must execute application families through the static registry"


KERNEL_FORBIDDEN_IMPORTS = (
    "grafy_api",
    "grafy_client",
    "grafy_mcp",
    "grafy_persistence",
    "grafy_storage",
    "grafy_workbench",
    "grafy_core.agents",
    "grafy_core.application",
    "grafy_core.runtime",
    "fastapi",
    "starlette",
    "sqlalchemy",
    "httpx",
    *SYSTEM_PLUGIN_IMPORTS,
)


def test_project_kernel_imports_no_adapter_http_or_family_code() -> None:
    """The Project kernel is pure core (ADR 0020, issue #194).

    Fingerprints, the result store port and the scheduler must be testable with no
    HTTP, persistence adapter, storage or node family around them. Hosts depend on
    the kernel; the kernel never reaches back out to a host.
    """

    kernel_root = REPO_ROOT / "libs/core/src/grafy_core/kernel"
    assert any(kernel_root.glob("*.py"))
    offenders: list[str] = []

    for path in kernel_root.rglob("*.py"):
        package = ".".join(path.parent.relative_to(kernel_root.parents[1]).parts)
        for module in _imported_modules(path.read_text(), package):
            if any(
                module == forbidden or module.startswith(f"{forbidden}.")
                for forbidden in KERNEL_FORBIDDEN_IMPORTS
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {module}")

    assert offenders == []

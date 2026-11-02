"""Supported artifact imports must work independently of import order."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "first_module",
    [
        "grafy_core.artifacts",
        "grafy_core.domain.modules",
        "grafy_core.ports.artifacts",
        "grafy_core.runtime.in_memory",
        "grafy_core.plugins",
    ],
)
def test_supported_artifact_imports_survive_any_import_order(first_module: str) -> None:
    # Artifact models used to re-export ports and in-memory repositories lazily so
    # that a host importing them first still worked. Each owner is imported directly
    # now, so the same order independence has to hold without that indirection.
    source = f"""
from importlib import import_module
import_module({first_module!r})
from grafy_core import artifacts
from grafy_core.ports.artifacts import ArtifactRepositoryPort, UnitOfWorkPort
from grafy_core.runtime.in_memory import InMemoryDataStore, InMemoryUnitOfWork
assert ArtifactRepositoryPort.__module__ == "grafy_core.ports.artifacts"
assert UnitOfWorkPort.__module__ == "grafy_core.ports.artifacts"
assert InMemoryDataStore.__module__ == "grafy_core.runtime.in_memory"
assert InMemoryUnitOfWork.__module__ == "grafy_core.runtime.in_memory"
namespace = {{}}
exec('from grafy_core.artifacts import *', namespace)
for name in artifacts.__all__:
    assert namespace[name] is getattr(artifacts, name)
for name in (
    "ArtifactRepositoryPort",
    "InMemoryDataStore",
    "InMemoryUnitOfWork",
    "UnitOfWorkPort",
    "unknown_export",
):
    try:
        getattr(artifacts, name)
    except AttributeError:
        pass
    else:
        raise AssertionError(f"artifact models must not own {{name!r}}")
"""
    result = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
